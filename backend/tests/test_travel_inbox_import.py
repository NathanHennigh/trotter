"""Real-template retention through parser and import/builder entrypoints.

The fixtures retain the original Orlando email structure with invented names,
booking references and ticket numbers. Tests use only an in-memory database.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import (
    Account, Base, BookingObservation, Segment, TravelInboxEvidence, TravelInboxItem, Trip, User,
)
from app.services.booking_import import apply_booking_message
from app.services.builder import build_segments_and_trips_detailed
from app.services.parser import parse_email
from app.services.travel_inbox import backfill_user_travel_inbox, retain_observation, serialize_item


ROWS = {row["id"]: row for row in json.loads(
    (Path(__file__).parent / "fixtures" / "orlando-bookings.json").read_text(encoding="utf-8")
)}
PERSONAL_FLIGHTS = {("IAH", "DCA", "UA1540"), ("DCA", "MCO", "B62023"),
                   ("MCO", "ATL", "NK1651"), ("ATL", "IAH", "NK512")}
NAMED_INBOX = {("Morgan Blake", "F91418", "other_traveler"),
               ("Morgan Blake", "NK1651", "companion"),
               ("Morgan Blake", "NK512", "companion")}


@pytest.fixture
def mailbox():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as db:
        owner = User(name="Alex Avery", email="owner@example.test", travel_name_aliases=[])
        # Deliberately use the retained passenger's exact name on another
        # account. A name match must never transfer data to this account.
        other_account = User(name="Morgan Blake", email="other-account@example.test", travel_name_aliases=[])
        db.add_all([owner, other_account])
        db.flush()
        for user in (owner, other_account):
            db.add(Account(user_id=user.id, provider="google", refresh_token_encrypted=b"test-only-unused", scopes="test-only"))
        db.flush()
        before_accounts = [(account.id, account.user_id, account.provider, account.scopes, account.refresh_token_encrypted)
                           for account in db.query(Account).order_by(Account.id)]
        yield db, owner, other_account, before_accounts
    engine.dispose()


def parse_fixture(key):
    row = ROWS[key]
    return parse_email(html=row["html"], plain_text=row["plain_text"], attachments=[],
                       user_name="Alex Avery", aliases=[], received_at=row["received_at"],
                       subject=row["subject"], from_email=row["from_email"])


def apply_fixture(db, owner, key):
    row = ROWS[key]
    return apply_booking_message(db, owner.id, parse_fixture(key), source_message_id=key,
                                 html=row["html"], plain_text=row["plain_text"],
                                 subject=row["subject"], received_at=row["received_at"])


def personal_rows(db, owner):
    return [(segment.id, segment.trip_id, segment.dep_airport, segment.arr_airport,
             segment.flight_number, segment.pnr, segment.dep_time, segment.arr_time, segment.meta_json)
            for segment in db.query(Segment).join(Trip).filter(Trip.user_id == owner.id).order_by(Segment.id)]


def inbox_views(db, owner):
    return [serialize_item(db, owner.id, item, include_evidence=True)
            for item in db.query(TravelInboxItem).filter_by(user_id=owner.id).all()]


@pytest.mark.parametrize("order", [
    ["multicity", "frontier", "canceled_confirmation", "cancellation", "return"],
    ["return", "cancellation", "canceled_confirmation", "frontier", "multicity"],
    ["cancellation", "frontier", "return", "multicity", "canceled_confirmation"],
])
def test_orlando_retains_frontier_and_shared_spirit_without_changing_personal_history(mailbox, order):
    db, owner, other_account, before_accounts = mailbox
    for key in order:
        apply_fixture(db, owner, key)
    db.flush()

    personal = db.query(Segment).join(Trip).filter(Trip.user_id == owner.id).all()
    assert {(flight.dep_airport, flight.arr_airport, flight.flight_number) for flight in personal} == PERSONAL_FLIGHTS
    assert db.query(Trip).filter_by(user_id=owner.id).count() == 1
    trip = db.query(Trip).filter_by(user_id=owner.id).one()
    assert (trip.start_ts.date().isoformat(), trip.end_ts.date().isoformat()) == ("2025-02-18", "2025-02-23")

    views = inbox_views(db, owner)
    named = [item for item in views if item["passenger_name"]]
    assert {(item["passenger_name"], item["flight"]["flight_number"], item["reason"]) for item in named} == NAMED_INBOX
    assert all(item["status"] == "retained" for item in named)
    unassigned = [item for item in views if not item["passenger_name"]]
    assert {item["flight"]["flight_number"] for item in unassigned} == {"UA1685", "UA1381"}
    assert all(item["status"] == "canceled" for item in unassigned)
    assert db.query(TravelInboxItem).count() == 5
    assert db.query(TravelInboxEvidence).count() == 7

    for item in named:
        payload = json.dumps(item, default=str)
        assert "Alex Avery" not in payload
        assert "passenger_evidence" not in payload
        assert "passenger_names" not in payload
        assert "@" not in payload
        assert item["evidence"]

    # The passenger's existing account is not looked up, populated or changed.
    assert db.query(User).count() == 2
    assert [(account.id, account.user_id, account.provider, account.scopes, account.refresh_token_encrypted)
            for account in db.query(Account).order_by(Account.id)] == before_accounts
    assert db.query(TravelInboxItem).filter_by(user_id=other_account.id).count() == 0
    assert db.query(Trip).filter_by(user_id=other_account.id).count() == 0

    before_personal = personal_rows(db, owner)
    before_links = [(link.item_id, link.observation_id) for link in db.query(TravelInboxEvidence).order_by(TravelInboxEvidence.id)]
    before_observations = db.query(BookingObservation).count()
    before_ids = {item.id for item in db.query(TravelInboxItem)}
    for key in reversed(order):
        apply_fixture(db, owner, key)
    backfill = backfill_user_travel_inbox(db, owner.id)
    assert backfill["items_added"] == 0
    assert backfill["evidence_added"] == 0
    assert personal_rows(db, owner) == before_personal
    assert {item.id for item in db.query(TravelInboxItem)} == before_ids
    assert [(link.item_id, link.observation_id) for link in db.query(TravelInboxEvidence).order_by(TravelInboxEvidence.id)] == before_links
    assert db.query(BookingObservation).count() == before_observations


def test_direct_builder_entrypoint_retains_other_traveler_before_ownership_gate(mailbox):
    db, owner, _, before_accounts = mailbox
    frontier = build_segments_and_trips_detailed(db, owner.id, parse_fixture("frontier").flights,
                                               source_message_id="direct-frontier")
    assert frontier.held_other == 1
    assert db.query(Segment).count() == 0
    assert {(item["passenger_name"], item["flight"]["flight_number"], item["reason"])
            for item in inbox_views(db, owner)} == {("Morgan Blake", "F91418", "other_traveler")}

    shared = build_segments_and_trips_detailed(db, owner.id, parse_fixture("return").flights,
                                             source_message_id="direct-return")
    assert shared.inserted == 2
    assert {segment.flight_number for segment in db.query(Segment)} == {"NK1651", "NK512"}
    assert {(item["passenger_name"], item["flight"]["flight_number"], item["reason"])
            for item in inbox_views(db, owner)} == NAMED_INBOX
    assert db.query(User).count() == 2
    assert db.query(Account).count() == len(before_accounts)


def test_same_named_existing_account_cannot_read_or_claim_retained_evidence(mailbox):
    db, owner, other_account, _ = mailbox
    apply_fixture(db, owner, "frontier")
    item = db.query(TravelInboxItem).one()
    observation = db.query(BookingObservation).one()
    with pytest.raises(ValueError, match="another user"):
        serialize_item(db, other_account.id, item, include_evidence=True)
    with pytest.raises(ValueError, match="another user"):
        retain_observation(db, other_account.id, observation)
    assert db.query(TravelInboxItem).count() == 1
    assert db.query(TravelInboxEvidence).count() == 1
