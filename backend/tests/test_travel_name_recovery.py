"""Recovery must add only explicitly identified personal flights, losslessly."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import get_db
from app.models import Base, BookingObservation, FlightShare, Segment, TravelInboxItem, TravelNameRecovery, Trip, User
from app.routers.auth import get_current_user
from app.routers.ingest_review import router
from app.services import travel_name_recovery as recovery
from app.services.booking_ledger import cancellation_blocks_flight, record_cancellation, record_user_decision
from app.services.builder import build_segments_and_trips_detailed
from app.services.import_lock import user_import_lock
from app.services.passenger_identity import full_names_match
from app.services.travel_inbox import serialize_item


@pytest.fixture
def api():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    db = factory()
    user = User(email="elisha@example.com", name="Elisha Hennigh")
    other = User(email="different@example.com", name="Different Person")
    db.add_all([user, other])
    db.commit()
    app = FastAPI()
    app.include_router(router)
    def request_db():
        with factory() as session:
            yield session
    app.dependency_overrides[get_db] = request_db
    app.dependency_overrides[get_current_user] = lambda: user
    with TestClient(app) as client:
        yield SimpleNamespace(engine=engine, factory=factory, db=db, user=user, other=other, client=client)
    db.close()
    engine.dispose()


def receipt(api, *, name="Elisha Faith Magno", day=9, evidence=None, force_review=False, user=None,
            message=None, source_at=None):
    evidence = evidence if evidence is not None else [{"name": name, "role": "traveler", "complete": True,
        "applies": True, "scope_ambiguous": False}]
    flight = SimpleNamespace(dep_airport="IAH", arr_airport="DCA", dep_time=datetime(2026, 9, day, 12),
        arr_time=datetime(2026, 9, day, 15), airline="UA", flight_number="UA1540", pnr="BOOK01",
        source="email", source_received_at=source_at or datetime(2026, 8, 1, tzinfo=timezone.utc),
        ownership="other", passenger_names=[name], passenger_evidence=evidence, force_review=force_review,
        nonstop=False, pnr_aliases=[])
    build_segments_and_trips_detailed(api.db, (user or api.user).id, [flight], source_message_id=message or f"receipt-{day}")
    api.db.commit()
    observation = api.db.query(BookingObservation).filter_by(user_id=(user or api.user).id,
        source_message_id=message or f"receipt-{day}").one()
    return flight, observation


def confirm(api, aliases=None):
    response = api.client.put("/ingest/travel-name-aliases", json={"aliases": aliases or ["Elisha Magno", "Elisha Faith Magno"], "confirmed": True})
    assert response.status_code == 200, response.text
    return response.json()["recovery"]["id"]


def run(api, job_id):
    recovery.run_recovery(job_id, session_factory=api.factory)
    api.db.expire_all()
    return api.db.get(TravelNameRecovery, job_id)


@pytest.mark.parametrize("printed,candidate,expected", [
    ("MAGNO/ELISHAFAITH", "Elisha Faith Magno", True),
    ("MAGNO/ELISHAFAITH", "Elisha Magno", False),
    ("MAGNO/ELISHABETH", "Elisha Magno", False),
    ("MADAME ELISHA MAGNO", "Elisha Magno", True),
    ("MME ELISHA MAGNO", "Elisha Magno", True),
    ("M Magno", "Elisha Magno", False),
    ("Elisha Jane Magno", "Elisha Faith Magno", False),
    ("Elisha Magno Jr", "Elisha Magno", False),
])
def test_confirmed_full_names_only(printed, candidate, expected):
    assert full_names_match(printed, candidate) is expected


def test_skip_onboarding_does_not_confirm_names_or_queue_recovery(api):
    response = api.client.post("/ingest/travel-onboarding/complete", json={})
    assert response.status_code == 200
    assert response.json() == {"primary_name": "Elisha Hennigh", "aliases": [], "confirmed": False,
        "onboarding_completed": True, "recovery": None}
    assert api.client.post("/ingest/travel-name-recovery", json={}).status_code == 409


@pytest.mark.parametrize("method,path,payload", [
    ("get", "/ingest/travel-name-aliases", None),
    ("put", "/ingest/travel-name-aliases", {"aliases": []}),
    ("post", "/ingest/travel-name-recovery", {}),
    ("post", "/ingest/travel-onboarding/complete", {}),
    ("post", "/ingest/travel-inbox/unknown/claim-self", {"passenger_name": "Example Person"}),
])
def test_all_identity_endpoints_require_authentication(api, method, path, payload):
    api.client.app.dependency_overrides.pop(get_current_user)
    assert api.client.request(method, path, json=payload).status_code in {401, 403}


def test_recovery_preserves_sources_companions_and_existing_ids_across_retries(api):
    _, first = receipt(api, name="MAGNO/ELISHAFAITH")
    _, second = receipt(api, day=11, evidence=[
        {"name": "Elisha Faith Magno", "role": "traveler", "applies": True, "complete": True},
        {"name": "Another Traveler", "role": "traveler", "applies": True, "complete": True}])
    _, foreign = receipt(api, user=api.other)
    sources = {row.id: deepcopy(row.facts) for row in (first, second, foreign)}
    retained_count = api.db.query(TravelInboxItem).count()
    job_id = confirm(api)
    assert confirm(api) == job_id
    job = run(api, job_id)
    assert (job.state, job.added, job.needs_review) == ("completed", 2, 0)
    segment_ids = [row.id for row in api.db.query(Segment).all()]
    trip_ids = [row.id for row in api.db.query(Trip).all()]
    assert len(segment_ids) == 2
    assert api.db.query(TravelInboxItem).count() == retained_count
    for source_id, facts in sources.items():
        assert api.db.get(BookingObservation, source_id).facts == facts
    inbox = api.db.query(TravelInboxItem).filter_by(user_id=api.user.id).all()
    companion = next(item for item in inbox if item.passenger_name == "Another Traveler")
    assert serialize_item(api.db, api.user.id, companion)["status"] == "retained"
    assert all(serialize_item(api.db, api.user.id, item)["status"] == "belongs_to_you"
               for item in inbox if item.passenger_name != "Another Traveler")
    retry = api.client.post("/ingest/travel-name-recovery", json={}).json()["recovery"]["id"]
    job = run(api, retry)
    assert (job.added, job.existing) == (0, 2)
    assert [row.id for row in api.db.query(Segment).all()] == segment_ids
    assert [row.id for row in api.db.query(Trip).all()] == trip_ids
    assert api.db.query(BookingObservation).filter_by(user_id=api.other.id).count() == 1
    derived = api.db.query(BookingObservation).filter(BookingObservation.source_message_id.like("travel-name:%")).all()
    assert len(derived) == 2
    assert all(row.source_event_at == datetime(2026, 8, 1) for row in derived)


@pytest.mark.parametrize("status,ownership", [("active", "other"), ("canceled", "self"), ("hold", "self")])
def test_explicit_manual_decisions_take_precedence(api, status, ownership):
    flight, observation = receipt(api)
    record_user_decision(api.db, api.user.id, flight, ownership=ownership, status=status, source_observation_id=observation.id)
    api.db.commit()
    job = run(api, confirm(api))
    assert job.added == 0 and job.needs_review == 1
    assert api.db.query(Segment).count() == 0


@pytest.mark.parametrize("cancel_date,scoped", [("2026-08-02T00:00:00Z", True), ("2026-07-20T00:00:00Z", True), (None, False)])
def test_name_confirmation_never_reinstates_canceled_or_uncertain_booking(api, cancel_date, scoped):
    flight, _ = receipt(api)
    record_cancellation(api.db, api.user.id, "BOOK01", source_message_id="cancel", source_event_at=cancel_date,
                        flights=[flight] if scoped else [])
    api.db.commit()
    job = run(api, confirm(api))
    assert job.added == 0 and job.needs_review == 1


def test_recovered_ownership_does_not_override_a_future_cancellation(api):
    flight, _ = receipt(api)
    run(api, confirm(api))
    record_cancellation(api.db, api.user.id, "BOOK01", source_message_id="cancel", source_event_at="2026-08-03T00:00:00Z", flights=[flight])
    api.db.commit()
    assert cancellation_blocks_flight(api.db, api.user.id, flight)
    assert not any(row.facts.get("user_decision") for row in api.db.query(BookingObservation).all())


@pytest.mark.parametrize("changes", [{"role": "payer"}, {"applies": False}, {"scope_ambiguous": True},
                                     {"name": "E Magno"}, {"name": "Elisha Jane Magno"}])
def test_weak_or_wrong_passenger_evidence_does_not_become_personal(api, changes):
    evidence = {"name": "Elisha Faith Magno", "role": "traveler", "applies": True, "complete": True}
    evidence.update(changes)
    receipt(api, evidence=[evidence])
    job = run(api, confirm(api, ["Elisha Faith Magno"]))
    assert job.state == "completed" and job.added == 0


def test_force_review_and_conflicting_middle_names_remain_held(api):
    receipt(api, force_review=True)
    receipt(api, day=11, evidence=[{"name": name, "role": "traveler", "applies": True, "complete": True}
        for name in ("Elisha Faith Magno", "Elisha Jane Magno")])
    job = run(api, confirm(api, ["Elisha Magno"]))
    assert job.added == 0 and job.needs_review == 2


def test_newer_receipt_does_not_allow_older_passenger_assertion_to_win(api):
    receipt(api)
    receipt(api, name="Different Person", source_at=datetime(2026, 8, 2, tzinfo=timezone.utc), message="corrected-receipt")
    job = run(api, confirm(api))
    assert job.added == 0 and job.needs_review == 1


def test_claim_requires_owned_original_full_name(api):
    receipt(api, name="MAGNO/ELISHAFAITH")
    receipt(api, name="Elisha Faith Magno", user=api.other)
    own = api.db.query(TravelInboxItem).filter_by(user_id=api.user.id).one()
    foreign = api.db.query(TravelInboxItem).filter_by(user_id=api.other.id).one()
    path = f"/ingest/travel-inbox/{own.id}/claim-self"
    assert api.client.post(path, json={"passenger_name": "Another Traveler"}).status_code == 422
    assert api.client.post(f"/ingest/travel-inbox/{foreign.id}/claim-self", json={"passenger_name": foreign.passenger_name}).status_code == 404
    response = api.client.post(path, json={"passenger_name": own.passenger_name})
    assert response.status_code == 200, response.text
    assert response.json()["aliases"] == ["MAGNO/ELISHAFAITH"]
    assert run(api, response.json()["recovery"]["id"]).added == 1


def test_active_share_does_not_allow_name_claim_or_automatic_recovery(api):
    receipt(api)
    item = api.db.query(TravelInboxItem).one()
    api.db.add(FlightShare(sender_id=api.user.id, recipient_email="someone@example.test",
        passenger_name=item.passenger_name, client_request_id="test-request", request_hash="a" * 64,
        token_hash="b" * 64, token_encrypted=b"synthetic", item_ids=[item.id], flights=[], status="pending",
        expires_at=recovery.now() + timedelta(days=2)))
    api.db.commit()
    assert api.client.post(f"/ingest/travel-inbox/{item.id}/claim-self",
        json={"passenger_name": item.passenger_name}).status_code == 409
    job = run(api, confirm(api))
    assert job.added == 0 and job.needs_review == 1
    assert serialize_item(api.db, api.user.id, item)["status"] == "needs_review"


def test_new_original_evidence_can_be_rechecked_without_requeuing_derived_evidence(api):
    receipt(api)
    first_id = confirm(api)
    assert run(api, first_id).added == 1
    assert confirm(api) == first_id
    receipt(api, day=11)
    second_id = confirm(api)
    assert second_id != first_id
    job = run(api, second_id)
    assert (job.added, job.existing) == (1, 1)


def test_changed_names_supersede_old_queued_job(api):
    receipt(api)
    old_id = confirm(api)
    new_id = confirm(api, ["Different Passenger"])
    assert new_id != old_id
    assert run(api, old_id).state == "completed"
    assert run(api, new_id).added == 0
    assert api.db.query(Segment).count() == 0


def test_batch_failure_rolls_back_flights_and_cursor_and_retry_deduplicates(api, monkeypatch):
    receipt(api)
    receipt(api, day=11)
    job_id = confirm(api)
    real_build = recovery.build_segments_and_trips_detailed
    def crash_after_projection(*args, **kwargs):
        real_build(*args, **kwargs)
        raise RuntimeError("simulated worker interruption")
    monkeypatch.setattr(recovery, "build_segments_and_trips_detailed", crash_after_projection)
    with pytest.raises(RuntimeError):
        run(api, job_id)
    api.db.expire_all()
    job = api.db.get(TravelNameRecovery, job_id)
    assert job.cursor == job.added == 0 and job.attempts == 1
    assert api.db.query(Segment).count() == api.db.query(Trip).count() == 0
    assert api.db.query(BookingObservation).count() == 2
    assert recovery.discover_recoveries(api.db) == []
    job.next_attempt_at = recovery.now() - timedelta(seconds=1)
    api.db.commit()
    monkeypatch.setattr(recovery, "build_segments_and_trips_detailed", real_build)
    assert run(api, job_id).added == 2
    assert run(api, job_id).added == 2
    assert api.db.query(Segment).count() == 2


def test_bounded_cursor_and_import_lock_allow_resuming_without_duplicate_work(api):
    receipt(api)
    receipt(api, day=11)
    job_id = confirm(api)
    api.db.expire_all()
    with user_import_lock(api.engine, api.user.id):
        job = api.db.get(TravelNameRecovery, job_id)
        recovery.recover_batch(api.db, job, batch_size=1)
        api.db.commit()
        assert (job.state, job.checked, job.added) == ("queued", 1, 1)
        recovery.run_recovery(job_id, session_factory=api.factory)
    assert run(api, job_id).added == 2


@pytest.mark.parametrize("malformed", [None, "garbled", 12, {"name": "Elisha Magno", "role": "traveler", "applies": True}])
def test_legacy_evidence_shapes_never_stall_job(api, malformed):
    _, obs = receipt(api)
    obs.facts = {**obs.facts, "passenger_evidence": malformed}
    api.db.commit()
    job = run(api, confirm(api))
    assert job.state == "completed"
    assert job.added == (1 if isinstance(malformed, dict) else 0)
