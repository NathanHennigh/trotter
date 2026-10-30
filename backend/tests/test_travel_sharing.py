"""Recipient consent, privacy and lossless flight-sharing regressions."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import get_db
from app.models import (Base, BookingCancellation, BookingObservation, FlightShare, Segment,
                        TravelInboxAssignment, TravelInboxEvidence, TravelInboxItem, Trip, User)
from app.routers.auth import get_current_user
from app.routers.travel_sharing import router
from app.services import travel_sharing as sharing
from app.services.builder import build_segments_and_trips_detailed
from app.services.import_lock import user_import_lock


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setenv("ENCRYPTION_KEY", "11" * 32)
    monkeypatch.setenv("TROTTER_API_URL", "https://api.trotter.example")
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    @event.listens_for(engine, "connect")
    def foreign_keys(conn, _):
        conn.execute("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    db = factory()
    sender = User(email="sender@example.com", name="Sender Person")
    recipient = User(email="recipient@example.com", name="Recipient Person")
    stranger = User(email="stranger@example.com", name="Stranger Person")
    db.add_all([sender, recipient, stranger])
    db.commit()
    for user in (sender, recipient, stranger):
        db.refresh(user)
    app = FastAPI()
    app.include_router(router)
    def request_db():
        with factory() as session:
            yield session
    app.dependency_overrides[get_db] = request_db
    app.dependency_overrides[get_current_user] = lambda: sender
    with TestClient(app, raise_server_exceptions=False) as client:
        yield SimpleNamespace(engine=engine, db=db, factory=factory, sender=sender, recipient=recipient,
                              stranger=stranger, app=app, client=client)
    db.close()
    engine.dispose()


def login(api, user):
    api.app.dependency_overrides[get_current_user] = lambda: user


def test_flight_invitation_authorizes_only_linked_verified_email_for_apple_user(api):
    from app.models import AuthIdentity
    original_email = api.recipient.email
    item, _ = seed(api)
    response = create(api, [item])
    assert response.status_code == 200, response.text
    shared_id = response.json()["share"]["id"]
    api.recipient.email = "private@privaterelay.appleid.com"
    api.db.add_all([
        AuthIdentity(user_id=api.recipient.id, provider="apple", subject="apple-recipient", email=api.recipient.email),
        AuthIdentity(user_id=api.recipient.id, provider="google", subject="google-recipient", email=original_email),
    ])
    api.db.commit()
    assert sharing.authorized_share(api.db, api.recipient, shared_id, role="recipient").id == shared_id
    assert sharing.inbox(api.db, api.recipient)["incoming"][0]["id"] == shared_id
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        sharing.authorized_share(api.db, api.stranger, shared_id, role="recipient")


def seed(api, *, owner=None, passenger="Recipient Person", origin="IAH", destination="DCA",
         date="2026-09-09", number="UA1540", dep="12:00:00", arr="15:00:00", force_review=False):
    owner = owner or api.sender
    observation = BookingObservation(user_id=owner.id, evidence_key=uuid4().hex.ljust(64, "a"),
        source_message_id="private-email-message", source_event_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        pnr="PRIVAT", travel_date=date, dep_airport=origin, arr_airport=destination, flight_number=number,
        ownership="other" if passenger else "unknown",
        facts={"dep_time": f"{date}T{dep}", "arr_time": f"{date}T{arr}", "airline": "UA",
            "source": "private-email", "passenger_names": [passenger, "Private Other Person"],
            "payer": "Private Payer", "force_review": force_review})
    item = TravelInboxItem(user_id=owner.id, record_key=uuid4().hex.ljust(64, "r"),
        flight_key=uuid4().hex.ljust(64, "f"), passenger_name=passenger,
        passenger_key=passenger.casefold() if passenger else None,
        reason="other_traveler" if passenger else "unassigned")
    api.db.add_all([item, observation])
    api.db.flush()
    api.db.add(TravelInboxEvidence(item_id=item.id, observation_id=observation.id))
    api.db.commit()
    return item, observation


def create(api, items, **changes):
    payload = {"item_ids": [row.id for row in items], "recipient_email": api.recipient.email,
               "passenger_name": "Recipient Person", "client_request_id": str(uuid4())}
    payload.update(changes)
    return api.client.post("/travel-sharing", json=payload)


def existing_flight(api, user=None, *, number="UA1540", day=9):
    user = user or api.recipient
    flight = SimpleNamespace(dep_airport="IAH", arr_airport="DCA", dep_time=datetime(2026, 9, day, 12),
        arr_time=datetime(2026, 9, day, 15), airline="UA", flight_number=number, pnr="RECIP1",
        ownership="self", source="email", nonstop=False, passenger_names=[], passenger_evidence=[])
    result = build_segments_and_trips_detailed(api.db, user.id, [flight], source_message_id=f"mail-{day}")
    api.db.commit()
    return api.db.query(Segment).filter(Segment.id.in_(result.affected_segment_ids)).one()


def test_owner_only_inbox_and_assignment_preserve_original_evidence(api):
    own, observation = seed(api, passenger=None)
    foreign, _ = seed(api, owner=api.stranger)
    original = deepcopy(observation.facts)
    listed = api.client.get("/travel-sharing/inbox").json()
    assert [row["id"] for row in listed["items"]] == [own.id]
    assert listed["items"][0]["requires_assignment"] is True
    assert listed["items"][0]["shareable"] is False
    assigned = api.client.patch(f"/travel-sharing/items/{own.id}", json={"passenger_name": "Recipient Person"})
    assert assigned.status_code == 200, assigned.text
    assert assigned.json()["shareable"] and assigned.json()["assigned_passenger_name"] == "Recipient Person"
    api.db.expire_all()
    assert api.db.get(TravelInboxItem, own.id).passenger_name is None
    assert api.db.get(BookingObservation, observation.id).facts == original
    assert api.client.patch(f"/travel-sharing/items/{foreign.id}", json={"passenger_name": "Someone Else"}).status_code == 404
    assert api.db.query(Trip).count() == 0


def test_invitation_sanitized_and_email_bound_with_no_recipient_lookup(api):
    item, _ = seed(api)
    response = create(api, [item], recipient_email="  Recipient@Example.COM ")
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["share"]["recipient_email"] == "recipient@example.com"
    for private in ("PRIVAT", "private-email", "Private Other Person", "Private Payer", "token_hash", "item_ids"):
        assert private not in response.text
    token = result["share_url"].split("#token=")[1]
    assert len(token) == 43
    stored = api.db.query(FlightShare).one()
    assert token != stored.token_hash and token.encode() not in stored.token_encrypted
    login(api, api.stranger)
    assert api.client.post("/travel-sharing/resolve", json={"token": token}).status_code == 404
    assert not api.client.get("/travel-sharing/inbox").json()["incoming"]
    login(api, api.recipient)
    resolved = api.client.post("/travel-sharing/resolve", json={"token": token})
    assert resolved.status_code == 200
    assert len(api.client.get("/travel-sharing/inbox").json()["incoming"]) == 1
    assert api.client.post(f"/travel-sharing/{stored.id}/link").status_code == 404


def test_new_user_can_join_and_receive_invitation_without_account_created_by_sender(api):
    item, _ = seed(api)
    response = create(api, [item], recipient_email="new@example.com")
    assert response.status_code == 200
    assert api.db.query(User).count() == 3
    new = User(email="new@example.com", name="Recipient Person")
    api.db.add(new)
    api.db.commit()
    api.db.refresh(new)
    login(api, new)
    incoming = api.client.get("/travel-sharing/inbox").json()["incoming"]
    assert len(incoming) == 1
    assert api.client.post(f"/travel-sharing/{incoming[0]['id']}/accept").status_code == 200


def test_create_retries_return_same_link_and_reject_reused_request_with_changed_payload(api):
    item, _ = seed(api)
    request_id = str(uuid4())
    first = create(api, [item], client_request_id=request_id)
    second = create(api, [item], client_request_id=request_id)
    assert first.json() == second.json()
    assert api.db.query(FlightShare).count() == 1
    assert create(api, [item], client_request_id=request_id, recipient_email="someone@example.com").status_code == 409
    share_id = first.json()["share"]["id"]
    assert api.client.post(f"/travel-sharing/{share_id}/link").json()["share_url"] == first.json()["share_url"]


def test_production_uses_deployed_backend_url_and_explicit_utc_times(api, monkeypatch):
    monkeypatch.delenv("TROTTER_API_URL")
    monkeypatch.setenv("BACKEND_URL", "https://trotter-api.example.com")
    monkeypatch.setenv("TROTTER_ENV", "production")
    item, _ = seed(api)
    response = create(api, [item])
    assert response.status_code == 200, response.text
    assert response.json()["share_url"].startswith("https://trotter-api.example.com/travel-sharing/open#")
    assert response.json()["share"]["flights"][0]["dep_time"].endswith("+00:00")


@pytest.mark.parametrize("reason", ["no_name", "different_name", "force_review", "incomplete", "canceled", "own", "duplicate"])
def test_unsafe_selections_blocked(api, reason):
    item, observation = seed(api, passenger=None if reason == "no_name" else "Recipient Person", force_review=reason == "force_review")
    if reason == "incomplete":
        observation.facts = {**observation.facts, "arr_time": None}
    if reason == "own":
        item.passenger_name = api.sender.name
    if reason == "canceled":
        api.db.add(BookingCancellation(user_id=api.sender.id, evidence_key="c" * 64, pnr="PRIVAT",
            source_event_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
            scopes=[{"travel_date": observation.travel_date, "dep_airport": "IAH", "arr_airport": "DCA", "flight_number": "UA1540"}], facts={}))
    api.db.commit()
    selected = [item, item] if reason == "duplicate" else [item]
    response = create(api, selected, passenger_name="Someone Else" if reason == "different_name" else "Recipient Person")
    assert response.status_code == 422, response.text
    assert api.db.query(FlightShare).count() == 0


def test_named_ticket_cannot_be_reassigned_to_another_person(api):
    item, _ = seed(api)
    assert api.client.patch(f"/travel-sharing/items/{item.id}", json={"passenger_name": "Someone Else"}).status_code == 422
    assert api.db.query(TravelInboxAssignment).count() == 0


def test_accept_is_idempotent_adds_only_missing_legs_and_keeps_both_owners_existing_data(api):
    own_segment = existing_flight(api, api.sender, day=7)
    kept = existing_flight(api)
    before = {col.name: deepcopy(getattr(kept, col.name)) for col in Segment.__table__.columns}
    own_before = {col.name: deepcopy(getattr(own_segment, col.name)) for col in Segment.__table__.columns}
    first, _ = seed(api)
    second, _ = seed(api, origin="DCA", destination="IAH", date="2026-09-11", number="UA1541")
    share = create(api, [first, second]).json()["share"]
    login(api, api.recipient)
    accepted = api.client.post(f"/travel-sharing/{share['id']}/accept")
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["added_flights"] == 1 and accepted.json()["existing_flights"] == 1
    replay = api.client.post(f"/travel-sharing/{share['id']}/accept")
    assert replay.json() == accepted.json()
    api.db.expire_all()
    kept_after = api.db.get(Segment, kept.id)
    # Trip grouping may combine a return with its existing outbound; flight facts stay exact.
    assert {col: getattr(kept_after, col) for col in before if col != "trip_id"} == {col: val for col, val in before.items() if col != "trip_id"}
    assert {col: getattr(api.db.get(Segment, own_segment.id), col) for col in own_before} == own_before
    assert api.db.query(Segment).join(Trip).filter(Trip.user_id == api.recipient.id).count() == 2
    observations = api.db.query(BookingObservation).filter(BookingObservation.user_id == api.recipient.id,
        BookingObservation.source_message_id.like("flight-share:%")).all()
    assert len(observations) == 2
    encoded = json.dumps([row.facts for row in observations])
    assert "PRIVAT" not in encoded and "private-email" not in encoded and "Private Other Person" not in encoded


def test_different_invitation_for_same_flight_does_not_duplicate(api):
    item, _ = seed(api)
    one = create(api, [item]).json()["share"]["id"]
    two = create(api, [item]).json()["share"]["id"]
    login(api, api.recipient)
    assert api.client.post(f"/travel-sharing/{one}/accept").json()["added_flights"] == 1
    assert api.client.post(f"/travel-sharing/{two}/accept").json()["existing_flights"] == 1
    assert api.db.query(Segment).count() == 1


@pytest.mark.parametrize("already_imported", [False, True])
def test_zero_padded_flight_numbers_match_the_itinerary_normalizer(api, already_imported):
    if already_imported:
        existing_flight(api, number="UA1")
    item, _ = seed(api, number="UA001")
    response = create(api, [item])
    assert response.status_code == 200, response.text
    share = response.json()["share"]
    assert share["flights"][0]["flight_number"] == "UA1"
    login(api, api.recipient)
    response = api.client.post(f"/travel-sharing/{share['id']}/accept")
    assert response.status_code == 200, response.text
    assert response.json()["existing_flights"] == int(already_imported)
    assert api.db.query(Segment).count() == 1


def test_later_own_email_reschedule_updates_shared_leg_without_duplicate_or_artificial_recency(api):
    item, source = seed(api)
    share_id = create(api, [item]).json()["share"]["id"]
    login(api, api.recipient)
    response = api.client.post(f"/travel-sharing/{share_id}/accept")
    assert response.status_code == 200, response.text
    api.db.expire_all()
    original_segment = api.db.query(Segment).one()
    segment_id = original_segment.id
    assert original_segment.meta_json["source_received_at"].startswith("2026-08-01")
    recipient_confirmation = SimpleNamespace(dep_airport="IAH", arr_airport="DCA",
        dep_time=datetime(2026, 9, 9, 13), arr_time=datetime(2026, 9, 9, 16),
        flight_number="UA1540", airline="UA", pnr="RECIP1", source="email",
        source_received_at=datetime(2026, 8, 15, tzinfo=timezone.utc), ownership="self",
        passenger_names=[], passenger_evidence=[], nonstop=False)
    result = build_segments_and_trips_detailed(api.db, api.recipient.id, [recipient_confirmation], source_message_id="my-own-reschedule")
    api.db.commit()
    assert result.inserted == 0 and result.updated == 1
    assert api.db.query(Segment).count() == 1
    updated = api.db.get(Segment, segment_id)
    assert updated.dep_time.hour == 13 and updated.pnr == "RECIP1"
    assert api.db.get(BookingObservation, source.id).pnr == "PRIVAT"


def test_source_cancellation_after_acceptance_does_not_retract_recipient_history(api):
    item, source = seed(api)
    share_id = create(api, [item]).json()["share"]["id"]
    login(api, api.recipient)
    assert api.client.post(f"/travel-sharing/{share_id}/accept").status_code == 200
    api.db.add(BookingCancellation(user_id=api.sender.id, evidence_key="z" * 64, pnr="PRIVAT",
        source_event_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
        scopes=[{"travel_date": source.travel_date, "dep_airport": "IAH", "arr_airport": "DCA", "flight_number": "UA1540"}], facts={}))
    api.db.commit()
    assert api.client.post(f"/travel-sharing/{share_id}/accept").status_code == 200
    assert api.db.query(Segment).count() == 1
    login(api, api.sender)
    assert api.client.post(f"/travel-sharing/{share_id}/revoke").status_code == 409
    assert api.db.query(Segment).count() == 1


@pytest.mark.parametrize("state", ["revoked", "declined", "expired"])
def test_closed_invites_cannot_be_accepted(api, state):
    item, _ = seed(api)
    share_id = create(api, [item]).json()["share"]["id"]
    if state == "revoked":
        assert api.client.post(f"/travel-sharing/{share_id}/revoke").status_code == 200
    elif state == "declined":
        login(api, api.recipient)
        assert api.client.post(f"/travel-sharing/{share_id}/decline").status_code == 200
    else:
        row = api.db.get(FlightShare, share_id)
        row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        api.db.commit()
    login(api, api.recipient)
    assert api.client.post(f"/travel-sharing/{share_id}/accept").status_code == 409
    assert api.db.query(Segment).count() == 0


def test_sender_cannot_accept_and_recipient_cannot_revoke(api):
    item, _ = seed(api)
    share_id = create(api, [item]).json()["share"]["id"]
    assert api.client.post(f"/travel-sharing/{share_id}/accept").status_code == 404
    assert api.client.post(f"/travel-sharing/{share_id}/decline").status_code == 404
    login(api, api.recipient)
    assert api.client.post(f"/travel-sharing/{share_id}/revoke").status_code == 404


def test_source_changes_after_invitation_require_new_invitation(api):
    item, source = seed(api)
    share_id = create(api, [item]).json()["share"]["id"]
    source.facts = {**source.facts, "arr_time": "2026-09-09T16:00:00"}
    api.db.commit()
    login(api, api.recipient)
    response = api.client.post(f"/travel-sharing/{share_id}/accept")
    assert response.status_code == 409, response.text
    assert api.db.query(Segment).count() == 0


def test_import_lock_contention_is_retryable(api):
    item, _ = seed(api)
    share_id = create(api, [item]).json()["share"]["id"]
    login(api, api.recipient)
    with user_import_lock(api.engine, api.recipient.id):
        response = api.client.post(f"/travel-sharing/{share_id}/accept")
        assert response.status_code == 409
    assert api.client.post(f"/travel-sharing/{share_id}/accept").status_code == 200


def test_failed_accept_rolls_back_flights_evidence_and_share_state(api, monkeypatch):
    item, _ = seed(api)
    share_id = create(api, [item]).json()["share"]["id"]
    login(api, api.recipient)
    original = sharing.build_segments_and_trips_detailed
    def failing(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("Injected failure after flight creation")
    monkeypatch.setattr(sharing, "build_segments_and_trips_detailed", failing)
    assert api.client.post(f"/travel-sharing/{share_id}/accept").status_code == 500
    api.db.expire_all()
    assert api.db.get(FlightShare, share_id).status == "pending"
    assert api.db.query(Segment).count() == api.db.query(Trip).count() == 0
    assert api.db.query(BookingObservation).filter_by(user_id=api.recipient.id).count() == 0
    monkeypatch.setattr(sharing, "build_segments_and_trips_detailed", original)
    assert api.client.post(f"/travel-sharing/{share_id}/accept").status_code == 200


def test_conflicting_existing_departure_is_not_overwritten(api):
    before = existing_flight(api, number="UA9999")
    item, _ = seed(api)
    share_id = create(api, [item]).json()["share"]["id"]
    login(api, api.recipient)
    assert api.client.post(f"/travel-sharing/{share_id}/accept").status_code == 409
    api.db.expire_all()
    assert api.db.get(Segment, before.id).flight_number == "UA9999"
    assert api.db.query(Segment).count() == 1


def test_landing_is_generic_fragment_only_and_cannot_inject_web_url(api, monkeypatch):
    monkeypatch.setenv("WEB_APP_URL", "https://app.example.com")
    response = api.client.get("/travel-sharing/open")
    assert response.status_code == 200
    assert "location.hash" in response.text and "trotterv2://flight-share" in response.text
    assert "https://app.example.com" in response.text and "Continue in browser" in response.text
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "no-store" in response.headers["cache-control"]
    monkeypatch.setenv("WEB_APP_URL", "javascript:alert(1)")
    assert "javascript:alert" not in api.client.get("/travel-sharing/open").text


@pytest.mark.parametrize("method,path", [("get", "/travel-sharing/inbox"), ("post", "/travel-sharing"),
    ("post", "/travel-sharing/resolve"), ("patch", f"/travel-sharing/items/{uuid4()}"),
    ("post", f"/travel-sharing/{uuid4()}/accept"), ("post", f"/travel-sharing/{uuid4()}/link")])
def test_private_endpoints_require_auth(api, method, path):
    api.app.dependency_overrides.pop(get_current_user)
    assert api.client.request(method, path, json={}).status_code in {401, 403}
