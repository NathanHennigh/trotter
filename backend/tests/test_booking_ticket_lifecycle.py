"""Explicit ticket exchanges converge without matching by route proximity."""
from copy import deepcopy
from datetime import timedelta
from itertools import permutations

import pytest

from app.models import BookingObservation, ItineraryHistory, Segment, Trip
from app.services.booking_import import apply_booking_message
from app.services.parser import ParsedFlight, ParseResult
from test_booking_lifecycle_hardening import db_user
from test_ticket_revision_evidence import receipt


@pytest.fixture(autouse=True)
def enable_ticket_reconciliation(monkeypatch):
    monkeypatch.setattr("app.services.booking_ticket_lifecycle.enabled", lambda user_id: True)


def ticket(new=False):
    text, fact = receipt(ticket="0271234567891" if new else "0271234567890",
        previous="0271234567890" if new else None, day=27 if new else 20)
    facts = [fact, deepcopy(fact)]
    facts[1].dep_airport, facts[1].arr_airport = fact.arr_airport, fact.dep_airport
    facts[1].flight_number = "AS222" if not new else "AS333"
    facts[1].dep_time += timedelta(days=2)
    facts[1].arr_time += timedelta(days=2)
    if new:
        facts[0].dep_airport = facts[1].arr_airport = "PDX"
    text = text.replace("Traveler(s):", "Flight 2 . Return\nTraveler(s):")
    flights = [ParsedFlight(row.dep_airport, row.arr_airport, row.dep_time, row.arr_time,
        airline="Alaska", flight_number=row.flight_number, pnr=row.pnr, source="alaska_receipt",
        ownership="self", passenger_names=["Alex Jordan Avery"], passenger_evidence=row.passenger_evidence)
        for row in facts]
    return text, flights


def ingest(db, user, kind):
    text, flights = ticket(kind == "new")
    subject = "Your flight is booked"
    if kind == "reminder":
        text = "Your trip is almost here!"
        subject = "Your flight reminder"
    return apply_booking_message(db, user.id, ParseResult(flights=flights), source_message_id=kind,
        subject=subject, plain_text=text, received_at={"old":"2027-05-01T00:00:00Z",
            "new":"2027-05-02T00:00:00Z", "reminder":"2027-05-03T00:00:00Z"}[kind])


@pytest.mark.parametrize("order", list(permutations(("old", "new", "reminder"))))
def test_complete_ticket_exchange_is_source_order_and_repeat_independent(db_user, order):
    db, user = db_user
    for kind in order:
        ingest(db, user, kind)
    expected = {("PDX", "SFO", "AS123"), ("SFO", "PDX", "AS333")}
    assert {(row.dep_airport, row.arr_airport, row.flight_number) for row in db.query(Segment)} == expected
    assert db.query(Trip).count() == 1
    assert db.query(BookingObservation).count() == 6
    for kind in order:
        ingest(db, user, kind)
    stable = [(row.id, row.trip_id, deepcopy(row.meta_json)) for row in db.query(Segment).order_by(Segment.id)]
    history = db.query(ItineraryHistory).count()
    for kind in reversed(order):
        ingest(db, user, kind)
    assert [(row.id, row.trip_id, row.meta_json) for row in db.query(Segment).order_by(Segment.id)] == stable
    assert db.query(ItineraryHistory).count() == history
    assert db.query(BookingObservation).count() == 6


def test_exchange_preserves_verified_independent_alias_and_original_snapshots(db_user):
    db, user = db_user
    ingest(db, user, "old")
    old_ids = {row.id for row in db.query(Segment)}
    _, flights = ticket()
    for flight in flights:
        flight.pnr = "ALIAS1"
    apply_booking_message(db, user.id, ParseResult(flights=flights), source_message_id="independent",
        subject="Your flight confirmation", received_at="2027-05-01T12:00:00Z")
    ingest(db, user, "new")
    rows = db.query(Segment).all()
    assert {row.id for row in rows if row.pnr == "ALIAS1"} == old_ids
    assert len(rows) == 4
    assert db.query(ItineraryHistory).filter_by(entity_type="ticket_exchange").count() == 2
    assert all(db.query(ItineraryHistory).filter_by(entity_type="segment", entity_id=old_id,
        reason="before_explicit_ticket_exchange").count() for old_id in old_ids)


def test_manual_projection_is_preserved_when_its_original_ticket_is_exchanged(db_user):
    db, user = db_user
    ingest(db, user, "old")
    old = db.query(Segment).first()
    old.meta_json = {**old.meta_json, "manually_edited": True, "personal_note": "Reviewed by owner"}
    old_id = old.id
    ingest(db, user, "new")
    assert db.get(Segment, old_id).meta_json["personal_note"] == "Reviewed by owner"
    # A manually grouped member protects the containing trip's membership.
    assert db.query(Segment).count() == 4


@pytest.mark.parametrize("protection", ["public", "unlisted", "manual_grouping", "trip_grouping_locked"])
def test_alaska_exchange_preserves_protected_parent_trip(db_user, protection):
    from app.services.booking_legacy_repair import _state
    db, user = db_user
    ingest(db, user, "old")
    trip = db.query(Trip).one()
    if protection in {"public", "unlisted"}:
        trip.visibility = protection
    else:
        member = db.query(Segment).filter_by(trip_id=trip.id).first()
        member.meta_json = {**member.meta_json, protection: True}
    db.flush()
    initial = _state(db, user.id)
    for kind in ("new", "old", "reminder", "new"):
        ingest(db, user, kind)
    current = _state(db, user.id)
    assert current["trips"][str(trip.id)] == initial["trips"][str(trip.id)]
    for key, row in initial["segments"].items():
        # Reminders may attach evidence, but no protected flight fact or membership changes.
        assert {k:v for k,v in current["segments"][key].items() if k != "meta_json"} == {
            k:v for k,v in row.items() if k != "meta_json"}
    assert db.query(ItineraryHistory).filter_by(entity_type="ticket_exchange").count() == 0
    for _ in range(2):
        for kind in ("old", "new", "reminder"):
            ingest(db, user, kind)
    stable = _state(db, user.id)
    for _ in range(3):
        for kind in ("reminder", "new", "old"):
            ingest(db, user, kind)
        assert _state(db, user.id) == stable


def test_ticket_retirement_gate_can_be_disabled_without_losing_evidence(db_user, monkeypatch):
    db, user = db_user
    monkeypatch.setattr("app.services.booking_ticket_lifecycle.enabled", lambda user_id: False)
    ingest(db, user, "old")
    ingest(db, user, "new")
    assert db.query(Segment).count() == 4
    assert all(row.facts.get("booking_ticket") for row in db.query(BookingObservation))
    monkeypatch.setattr("app.services.booking_ticket_lifecycle.enabled", lambda user_id: True)
    ingest(db, user, "new")
    assert db.query(Segment).count() == 2


@pytest.mark.parametrize("order", [(False, True), (True, False)])
def test_new_ticket_card_template_holds_creation_outside_reconciliation_cohort(db_user, monkeypatch, order):
    from app.models import TravelInboxEvidence
    db, user = db_user
    monkeypatch.setattr("app.services.booking_ticket_lifecycle.enabled", lambda uid: False)
    for repeat in range(3):
        for new in order:
            text, flights = ticket(new)
            for flight in flights:
                flight.source = "shape_alaska_trip_detail_blocks"
            outcome = apply_booking_message(db, user.id, ParseResult(flights=flights),
                source_message_id="card-new" if new else "card-old", subject="Your flight is booked",
                plain_text=text, received_at="2027-05-02T00:00:00Z" if new else "2027-05-01T00:00:00Z")
            assert outcome.review_reason == "ticket_reconciliation_not_enabled"
        assert db.query(Segment).count() == db.query(Trip).count() == 0
        assert db.query(BookingObservation).count() == db.query(TravelInboxEvidence).count() == 4
        assert all(row.facts.get("booking_ticket") and row.facts["ownership"] == "self"
                   for row in db.query(BookingObservation))
        assert db.query(ItineraryHistory).count() == 0
    # Enabling the exact reconciler permits the same retained original sources.
    monkeypatch.setattr("app.services.booking_ticket_lifecycle.enabled", lambda uid: True)
    for new in order:
        text, flights = ticket(new)
        for flight in flights:
            flight.source = "shape_alaska_trip_detail_blocks"
        apply_booking_message(db, user.id, ParseResult(flights=flights),
            source_message_id="card-new" if new else "card-old", subject="Your flight is booked",
            plain_text=text, received_at="2027-05-02T00:00:00Z" if new else "2027-05-01T00:00:00Z")
    assert db.query(Segment).count() == 2
    assert db.query(BookingObservation).count() == 4


def test_new_ticket_card_gate_preserves_existing_adopted_rows_and_normal_extractor(db_user, monkeypatch):
    db, user = db_user
    monkeypatch.setattr("app.services.booking_ticket_lifecycle.enabled", lambda uid: False)
    ingest(db, user, "old")  # Established normal extractor behavior is unchanged.
    old_ids = {row.id for row in db.query(Segment)}
    original = [(row.id, row.dep_time, row.arr_time) for row in db.query(Segment)]
    for new in [False, True]:
        text, flights = ticket(new)
        for flight in flights:
            flight.source = "shape_alaska_trip_detail_blocks"
        outcome = apply_booking_message(db, user.id, ParseResult(flights=flights),
            source_message_id="card-new" if new else "card-old", subject="Your flight is booked",
            plain_text=text, received_at="2027-05-02T00:00:00Z" if new else "2027-05-01T00:00:00Z")
        assert outcome.review_reason == ("ticket_reconciliation_not_enabled" if new else None)
    assert {row.id for row in db.query(Segment)} == old_ids
    assert [(row.id, row.dep_time, row.arr_time) for row in db.query(Segment)] == original


@pytest.mark.parametrize("context", ["malformed_ticket", "multiple_passengers"])
def test_new_template_hold_cannot_be_bypassed_by_unvalidated_ticket_context(db_user, monkeypatch, context):
    db, user = db_user
    monkeypatch.setattr("app.services.booking_ticket_lifecycle.enabled", lambda uid: False)
    text, flights = ticket()
    if context == "malformed_ticket":
        text = text.replace("0271234567890", "invalid-ticket")
    else:
        text = text.replace("Ticket 0271234567890", "Ticket 0271234567890\nBlair Avery\nTicket 0271234567899")
        for flight in flights:
            flight.passenger_names.append("Blair Avery")
            flight.passenger_evidence.append({"name": "Blair Avery", "source": "booking_ticket_holder",
                "role": "traveler", "complete": True, "scope": {"pnr": flight.pnr}, "applies": True})
    for flight in flights:
        flight.source = "shape_alaska_trip_detail_blocks"
    def ingest_card():
        return apply_booking_message(db, user.id, ParseResult(flights=deepcopy(flights)),
            source_message_id="unsupported-card", subject="Your flight is booked",
            plain_text=text, received_at="2027-05-01T00:00:00Z")
    for _ in range(2):
        assert ingest_card().review_reason == "ticket_reconciliation_not_enabled"
        assert db.query(Segment).count() == db.query(Trip).count() == 0
        assert db.query(BookingObservation).count() == 2
        assert all(not row.facts.get("booking_ticket") for row in db.query(BookingObservation))
    monkeypatch.setattr("app.services.booking_ticket_lifecycle.enabled", lambda uid: True)
    ingest_card()
    assert db.query(Segment).count() == 2
    assert db.query(ItineraryHistory).filter_by(entity_type="ticket_exchange").count() == 0
    assert all(not row.facts.get("booking_ticket") for row in db.query(BookingObservation))


def test_old_observation_pointer_cannot_retire_an_amended_different_leg(db_user):
    db, user = db_user
    ingest(db, user, "old")
    changed = db.query(Segment).first()
    changed.arr_airport = "LAX"
    changed_id = changed.id
    ingest(db, user, "new")
    assert db.get(Segment, changed_id).arr_airport == "LAX"
    assert db.query(Segment).count() == 3


def test_exchange_preserves_id_of_physical_leg_that_did_not_change(db_user):
    db, user = db_user
    ingest(db, user, "old")
    old = db.query(Segment).filter_by(dep_airport="SEA").one()
    old_id = old.id
    _, old_flights = ticket()
    text, successor = ticket(new=True)
    successor[0] = old_flights[0]
    apply_booking_message(db, user.id, ParseResult(flights=successor), source_message_id="new",
        subject="Your flight is booked", plain_text=text, received_at="2027-05-02T00:00:00Z")
    assert db.get(Segment, old_id) is not None
    assert db.query(Segment).count() == 2
    assert db.get(Segment, old_id).meta_json["booking_ticket"]["ticket_number"] == "0271234567891"
