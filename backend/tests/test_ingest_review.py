from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import get_db
from app.models import Base, BookingObservation, ItineraryHistory, Message, MessageStatus, Segment, Trip, User
from app.routers import ingest_review
from app.routers.auth import get_current_user
from app.services.builder import build_segments_and_trips_detailed
from app.services.import_lock import user_import_lock


def fact(*, pnr="ABC123", number="UA1540", day="2025-02-18", ownership="unknown"):
    return SimpleNamespace(
        dep_airport="IAH", arr_airport="DCA", dep_time=datetime.fromisoformat(day + "T12:00:00"),
        arr_time=datetime.fromisoformat(day + "T15:00:00"), airline="UA", flight_number=number,
        pnr=pnr, source="text", source_received_at=datetime(2025, 1, 29, 12, tzinfo=timezone.utc),
        pnr_aliases=[], ownership=ownership, passenger_names=[], passenger_evidence=[], nonstop=False,
    )


@pytest.fixture
def api():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    db = factory()
    user = User(email="nathan@example.com", name="Nathan", travel_name_aliases=[])
    other = User(email="private@example.com", name="Private Other User", travel_name_aliases=["Private Alias"])
    db.add_all([user, other])
    db.commit()
    db.refresh(user)
    db.refresh(other)
    app = FastAPI()
    app.include_router(ingest_review.router)
    def get_test_db():
        with factory() as request_db:
            yield request_db
    app.dependency_overrides[get_db] = get_test_db
    app.dependency_overrides[get_current_user] = lambda: user
    with TestClient(app, raise_server_exceptions=False) as client:
        yield SimpleNamespace(engine=engine, db=db, user=user, other=other, app=app, client=client)
    db.close()
    engine.dispose()


def seed(api, flights=None, *, user=None, message="receipt"):
    owner = user or api.user
    flights = flights or [fact()]
    build_segments_and_trips_detailed(api.db, owner.id, flights, source_message_id=message)
    api.db.add(Message(user_id=owner.id, provider_msg_id=message, status=MessageStatus.REVIEW_REQUIRED,
                       parse_error="passenger_identity_unresolved", parse_evidence={"resolved": False, "original_detail": "retain"}))
    api.db.commit()
    return api.db.query(BookingObservation).filter_by(user_id=owner.id, source_message_id=message).order_by(BookingObservation.id).all()


@pytest.mark.parametrize("method,path,payload", [
    ("get", "/ingest/booking-observations", None),
    ("post", "/ingest/booking-observations/1/decision", {"decision": "self"}),
    ("get", "/ingest/travel-name-aliases", None),
    ("put", "/ingest/travel-name-aliases", {"aliases": ["Nathan"]}),
])
def test_all_review_endpoints_require_authentication(api, method, path, payload):
    api.app.dependency_overrides.pop(get_current_user)
    response = api.client.request(method, path, json=payload)
    assert response.status_code in (401, 403)


def test_observation_listing_and_decisions_never_expose_or_change_other_users(api):
    [own] = seed(api)
    [private] = seed(api, user=api.other, message="private-message")
    response = api.client.get("/ingest/booking-observations")
    assert response.status_code == 200
    assert [row["id"] for row in response.json()["observations"]] == [own.id]
    assert api.client.get("/ingest/booking-observations", params={"source_message_id": "private-message"}).json()["observations"] == []
    for observation_id in (private.id, 999999):
        denied = api.client.post(f"/ingest/booking-observations/{observation_id}/decision", json={"decision": "self"})
        assert denied.status_code == 404
        assert denied.json() == {"detail": "Booking observation not found"}
    assert api.db.query(BookingObservation).count() == 2


def test_self_decision_activates_exact_held_fact_and_survives_email_replay(api):
    [observation] = seed(api)
    raw_facts = deepcopy(observation.facts)
    response = api.client.post(f"/ingest/booking-observations/{observation.id}/decision", json={"decision": "self"})
    assert response.status_code == 200, response.text
    assert response.json()["inserted"] == 1 and response.json()["message_status"] == "accepted"
    api.db.expire_all()
    decision = api.db.get(BookingObservation, response.json()["decision_id"])
    assert decision.facts["user_decision"]["source_observation_id"] == observation.id
    assert api.db.query(Segment).one().flight_number == "UA1540"
    assert api.db.get(BookingObservation, observation.id).facts == raw_facts
    message = api.db.query(Message).filter_by(user_id=api.user.id).one()
    assert message.parse_evidence["original_detail"] == "retain"
    assert message.parse_evidence["user_decisions"][0]["decision"] == "self"
    replay = build_segments_and_trips_detailed(api.db, api.user.id, [fact()], source_message_id="receipt")
    assert replay.held_unknown == 0
    assert api.db.query(Segment).count() == 1


@pytest.mark.parametrize("decision", ["other", "canceled"])
def test_removal_decision_is_exact_archived_and_durable(api, decision):
    [observation] = seed(api, [fact(ownership="self")])
    [private] = seed(api, [fact(ownership="self")], user=api.other, message="other-user-booking")
    existing = api.db.query(Segment).join(Trip).filter(Trip.user_id == api.user.id).one()
    original_id, original_trip_id = existing.id, existing.trip_id
    # Same date and booking, different flight number: the selected observation
    # must not cancel this distinct stored fact as a side effect.
    second_trip = Trip(user_id=api.user.id, title="Distinct flight")
    api.db.add(second_trip)
    api.db.flush()
    different = Segment(trip_id=second_trip.id, mode="flight", dep_airport="IAH", arr_airport="DCA",
                        dep_time=datetime(2025, 2, 18, 18), arr_time=datetime(2025, 2, 18, 21),
                        airline="UA", flight_number="UA1685", pnr="ABC123", meta_json={"keep": "distinct"})
    api.db.add(different)
    api.db.commit()
    different_id = different.id
    response = api.client.post(f"/ingest/booking-observations/{observation.id}/decision", json={"decision": decision})
    assert response.status_code == 200, response.text
    assert response.json()["removed"] == 1
    api.db.expire_all()
    assert api.db.get(Segment, original_id) is None
    assert api.db.get(Trip, original_trip_id) is None
    assert api.db.get(Segment, different_id).meta_json == {"keep": "distinct"}
    assert api.db.query(Segment).join(Trip).filter(Trip.user_id == api.other.id).count() == 1
    history = api.db.query(ItineraryHistory).filter_by(entity_type="segment", entity_id=original_id,
                                                       reason=f"user_marked_{decision}").one()
    assert history.snapshot["flight_number"] == "UA1540"
    replay = build_segments_and_trips_detailed(api.db, api.user.id, [fact(ownership="self")], source_message_id="receipt")
    assert replay.inserted == 0
    assert replay.held_other == 1 if decision == "other" else replay.blocked_cancellation == 1


def test_missing_pnr_removal_returns_actionable_422_without_mutation(api):
    [observation] = seed(api, [fact(pnr=None)])
    before = api.db.query(BookingObservation).count()
    response = api.client.post(f"/ingest/booking-observations/{observation.id}/decision", json={"decision": "canceled"})
    assert response.status_code == 422
    assert "no booking reference" in response.json()["detail"]
    assert api.db.query(BookingObservation).count() == before
    assert api.db.query(Segment).count() == 0


def test_one_decision_does_not_resolve_other_ambiguous_legs(api):
    observations = seed(api, [fact(), fact(day="2025-02-19")])
    first = api.client.post(f"/ingest/booking-observations/{observations[0].id}/decision", json={"decision": "self"})
    assert first.status_code == 200
    assert first.json()["message_status"] == "review_required"
    second = api.client.post(f"/ingest/booking-observations/{observations[1].id}/decision", json={"decision": "self"})
    assert second.status_code == 200
    assert second.json()["message_status"] == "accepted"


def test_aliases_are_explicit_validated_and_scoped_to_current_user(api):
    response = api.client.put("/ingest/travel-name-aliases", json={"aliases": ["  Nathan   A. Smith ", "nathan a. smith", "Nate Smith"]})
    assert response.status_code == 200
    assert response.json()["aliases"] == ["Nathan A. Smith", "Nate Smith"]
    assert api.client.get("/ingest/travel-name-aliases").json() == response.json()
    api.db.expire_all()
    assert api.db.get(User, api.other.id).travel_name_aliases == ["Private Alias"]
    invalid = api.client.put("/ingest/travel-name-aliases", json={"aliases": ["mailbox@example.com"]})
    assert invalid.status_code == 422
    assert api.client.get("/ingest/travel-name-aliases").json() == response.json()


def test_conflicting_import_returns_409_and_releases_no_other_workers_lock(api):
    [observation] = seed(api)
    with user_import_lock(api.engine, api.user.id):
        response = api.client.post(f"/ingest/booking-observations/{observation.id}/decision", json={"decision": "self"})
        assert response.status_code == 409
        alias_response = api.client.put("/ingest/travel-name-aliases", json={"aliases": ["Nate"]})
        assert alias_response.status_code == 409
    assert api.db.query(BookingObservation).count() == 1
    assert api.db.query(Segment).count() == 0


def test_failed_projection_rolls_back_decision_and_history_atomically(api, monkeypatch):
    [observation] = seed(api)
    before_observations = api.db.query(BookingObservation).count()
    before_history = api.db.query(ItineraryHistory).count()
    with monkeypatch.context() as patch:
        def fail(*args, **kwargs):
            raise RuntimeError("synthetic projection failure")
        patch.setattr(ingest_review, "build_segments_and_trips_detailed", fail)
        response = api.client.post(f"/ingest/booking-observations/{observation.id}/decision", json={"decision": "self"})
    assert response.status_code == 500
    api.db.expire_all()
    assert api.db.query(BookingObservation).count() == before_observations
    assert api.db.query(ItineraryHistory).count() == before_history
    assert api.db.query(Message).one().status == MessageStatus.REVIEW_REQUIRED
    assert api.client.post(f"/ingest/booking-observations/{observation.id}/decision", json={"decision": "self"}).status_code == 200
