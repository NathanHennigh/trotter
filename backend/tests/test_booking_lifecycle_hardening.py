"""Synthetic mailbox regressions for cancellation scope and durable repeats."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from itertools import permutations

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.models import (Base, BookingCancellation, BookingObservation, ItineraryHistory,
                        MessageStatus, Segment, Trip, User)
from app.services.booking_import import _booking_lifecycle, _retained_flight, apply_booking_message
from app.services.parser import ParsedFlight, ParseResult


@pytest.fixture
def db_user(monkeypatch):
    monkeypatch.setattr("app.services.builder.enrich_segment", lambda *args, **kwargs: None)
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = User(name="Alex Morgan", email="alex@example.test")
        db.add(user)
        db.flush()
        yield db, user
    engine.dispose()


def legs(carrier="WN", ownership="self"):
    result = []
    for day, route, number in [(14, ("DAL", "AUS"), "120"), (17, ("AUS", "DAL"), "230")]:
        departure = datetime(2025, 2, day, 12, tzinfo=timezone.utc)
        result.append(ParsedFlight(*route, departure, departure + timedelta(hours=1),
            airline=carrier, flight_number=carrier + number, pnr="ROUND1", source="synthetic",
            ownership=ownership, passenger_names=["Alex Morgan"] if ownership == "self" else ["Other Guest"]))
    return result


def apply(db, user, source, flights, *, kind="confirmation", at="2025-01-20T12:00:00Z"):
    subjects = {"confirmation": "Your flight is booked: ROUND1",
        "cancellation": "Alex Morgan's trip (ROUND1): This reservation has been canceled.",
        "reminder": "Your Austin trip (ROUND1) is almost here!",
        "schedule": "Updated flight schedule"}
    bodies = {"confirmation": "Your reservation is booked and confirmed.",
        "cancellation": "Your reservation has been canceled. Confirmation number: ROUND1.",
        "reminder": "Your complete itinerary. Manage your booking. See you soon!",
        "schedule": "Your departure time has changed. Your reservation is already confirmed."}
    return apply_booking_message(db, user.id, ParseResult(flights=deepcopy(flights)),
        source_message_id=source, subject=subjects[kind], plain_text=bodies[kind], received_at=at)


@pytest.mark.parametrize("carrier", ["WN", "UA"])
@pytest.mark.parametrize("order", list(permutations(("confirmation", "cancellation", "reminder"))))
def test_predeparture_cancellation_wins_over_later_reminder_in_every_order(db_user, carrier, order):
    db, user = db_user
    schedule = legs(carrier)
    times = {"confirmation": "2025-01-20T12:00:00Z", "cancellation": "2025-02-10T12:00:00Z",
             "reminder": "2025-02-10T14:00:00Z"}
    for _ in range(3):
        for kind in order:
            apply(db, user, kind, schedule, kind=kind, at=times[kind])
        assert db.query(Segment).count() == 0
        assert db.query(Trip).count() == 0
        assert db.query(BookingCancellation).count() == 1
        assert db.query(BookingObservation).count() == 6
    cancellation = db.query(BookingCancellation).one()
    assert len(cancellation.scopes) == 2
    assert cancellation.facts["strict_lifecycle"] is True
    assert {row.facts["booking_lifecycle"]["kind"] for row in db.query(BookingObservation)} == {
        "confirmation", "cancellation", "operational_notice"}


def test_real_rebooking_survives_later_reminder_and_cancellation_repeat(db_user):
    db, user = db_user
    schedule = legs()
    apply(db, user, "cancel", schedule, kind="cancellation", at="2025-02-01T12:00:00Z")
    apply(db, user, "new-ticket", schedule, at="2025-02-02T12:00:00Z")
    apply(db, user, "reminder", schedule, kind="reminder", at="2025-02-03T12:00:00Z")
    original_ids = [row.id for row in db.query(Segment).order_by(Segment.id)]
    outcome = apply(db, user, "cancel", schedule, kind="cancellation", at="2025-02-01T12:00:00Z")
    assert outcome.canceled == 0
    assert [row.id for row in db.query(Segment).order_by(Segment.id)] == original_ids
    assert len(original_ids) == 2


def test_new_reminder_cannot_reinstate_a_legacy_cancellation_event(db_user):
    db, user = db_user
    from app.services.booking_ledger import record_cancellation
    record_cancellation(db, user.id, "ROUND1", source_message_id="legacy-cancel",
        source_event_at=datetime(2025, 2, 10, 12), flights=legs())
    outcome = apply(db, user, "new-reminder", legs(), kind="reminder", at="2025-02-11T12:00:00Z")
    assert outcome.build.blocked_cancellation == 2
    assert db.query(Segment).count() == 0


@pytest.mark.parametrize("cancel_first", [False, True])
def test_midtrip_partial_refund_never_retroactively_cancels_outbound(db_user, cancel_first):
    db, user = db_user
    schedule = legs()
    if not cancel_first:
        apply(db, user, "original", schedule)
    outcome = apply(db, user, "midtrip-cancel", schedule, kind="cancellation", at="2025-02-16T20:00:00Z")
    assert outcome.review_reason == "post_departure_cancellation_conflict"
    assert outcome.status == MessageStatus.REVIEW_REQUIRED
    cancellation = db.query(BookingCancellation).one()
    assert [scope["flight_number"] for scope in cancellation.scopes] == ["WN230"]
    assert [scope["flight_number"] for scope in cancellation.facts["review_scopes"]] == ["WN120"]
    for _ in range(2):
        apply(db, user, "original", schedule)
        apply(db, user, "late-reminder", schedule, kind="reminder", at="2025-02-17T06:00:00Z")
        assert [row.flight_number for row in db.query(Segment)] == ([] if cancel_first else ["WN120"])
    assert len(cancellation.facts["flights"]) == 2


@pytest.mark.parametrize("cancel_first", [False, True])
def test_notice_after_both_travel_dates_holds_conflict_without_restoring_or_deleting(db_user, cancel_first):
    db, user = db_user
    schedule = legs("G4")
    if not cancel_first:
        apply(db, user, "original", schedule)
    before = [(row.id, row.trip_id, deepcopy(row.meta_json)) for row in db.query(Segment)]
    outcome = apply(db, user, "posttrip-cancel", schedule, kind="cancellation", at="2025-02-18T12:00:00Z")
    assert outcome.canceled == 0
    assert outcome.review_reason == "post_departure_cancellation_conflict"
    cancellation = db.query(BookingCancellation).one()
    assert cancellation.scopes == [] and len(cancellation.facts["review_scopes"]) == 2
    apply(db, user, "original", schedule)
    rows = db.query(Segment).all()
    assert [(row.id, row.trip_id, {key: value for key, value in row.meta_json.items()
                                 if key != "booking_conflicts"}) for row in rows] == before
    assert all(row.meta_json["booking_conflicts"][0]["reason"] == "post_departure_cancellation_conflict"
               for row in rows)
    # A second pass cannot grow conflict annotations or history.
    stable = [(row.id, deepcopy(row.meta_json)) for row in rows]
    apply(db, user, "posttrip-cancel", schedule, kind="cancellation", at="2025-02-18T12:00:00Z")
    assert [(row.id, row.meta_json) for row in db.query(Segment)] == stable


@pytest.mark.parametrize("ownership", ["other", "unknown"])
def test_unproven_cancellation_never_deletes_verified_other_passenger_scope(db_user, ownership):
    db, user = db_user
    apply(db, user, "mine", legs())
    outcome = apply(db, user, "another-cancel", legs(ownership=ownership), kind="cancellation",
                    at="2025-02-10T12:00:00Z")
    assert outcome.status == MessageStatus.ACCEPTED
    assert db.query(Segment).count() == 2
    cancellation = db.query(BookingCancellation).one()
    assert len(cancellation.scopes) == 2
    assert cancellation.facts["personal_scopes"] == []
    assert db.query(BookingObservation).count() == 4


def test_cancellation_does_not_cross_same_day_route_different_flight_or_account(db_user):
    db, user = db_user
    target = legs()[0]
    other = deepcopy(target)
    other.flight_number = "WN999"
    other.dep_time += timedelta(hours=5)
    other.arr_time += timedelta(hours=5)
    apply(db, user, "mine", [target, other])
    second = User(name="Other Guest", email="other@example.test")
    db.add(second)
    db.flush()
    apply(db, second, "other-user", [target])
    apply(db, user, "only-target", [target], kind="cancellation", at="2025-02-10T12:00:00Z")
    assert [row.flight_number for row in db.query(Segment).join(Trip).filter(Trip.user_id == user.id)] == ["WN999"]
    assert db.query(Segment).join(Trip).filter(Trip.user_id == second.id).count() == 1


@pytest.mark.parametrize("contextual", [False, True])
def test_single_leg_repeats_do_not_allocate_empty_candidate_trips_or_grow_history(db_user, monkeypatch, contextual):
    db, user = db_user
    monkeypatch.setattr("app.services.booking_enrichment.enabled", lambda user_id: contextual)
    schedule = legs()
    apply(db, user, "full-ticket", schedule)
    assert db.query(Trip).count() == 1
    for index, leg in enumerate(schedule):
        apply(db, user, f"leg-{index}", [leg], kind="schedule", at="2025-02-01T12:00:00Z")
    allocated = []
    def track(session, *_):
        allocated.extend(item for item in session.new if isinstance(item, Trip))
    event.listen(db, "before_flush", track)
    def state():
        return ([(row.id, row.trip_id, deepcopy(row.meta_json)) for row in db.query(Segment).order_by(Segment.id)],
                db.query(BookingObservation).count(), db.query(BookingCancellation).count(),
                db.query(ItineraryHistory).count())
    for index, leg in enumerate(schedule):
        apply(db, user, f"leg-{index}", [leg], kind="schedule", at="2025-02-01T12:00:00Z")
    stable = state()
    for _ in range(2):
        for index, leg in enumerate(schedule):
            apply(db, user, f"leg-{index}", [leg], kind="schedule", at="2025-02-01T12:00:00Z")
        assert state() == stable
    assert allocated == []
    assert db.query(Trip).count() == 1


def test_reparsed_midtrip_notice_cannot_apply_an_older_overbroad_tombstone(db_user):
    db, user = db_user
    from app.services.booking_ledger import record_cancellation
    schedule = legs()
    apply(db, user, "original", schedule)
    record_cancellation(db, user.id, "ROUND1", source_message_id="old-parser-cancel",
        source_event_at=datetime(2025, 2, 16, 20), flights=schedule)
    apply(db, user, "reviewed-parser-cancel", schedule, kind="cancellation", at="2025-02-16T20:00:00Z")
    assert [row.flight_number for row in db.query(Segment)] == ["WN120"]
    assert db.query(BookingCancellation).count() == 2  # Original evidence retained.


def test_verified_independent_alias_survives_primary_cancellation_and_late_reminder(db_user):
    db, user = db_user
    booked = legs()[0]
    alias = deepcopy(booked)
    alias.pnr = "ALIAS1"
    apply(db, user, "original", [booked])
    apply(db, user, "independent-ticket", [alias])
    segment_id = db.query(Segment).one().id
    apply(db, user, "cancel-primary", [booked], kind="cancellation", at="2025-02-10T12:00:00Z")
    apply(db, user, "late-reminder", [booked], kind="reminder", at="2025-02-10T14:00:00Z")
    segment = db.query(Segment).one()
    assert segment.id == segment_id and segment.pnr == "ALIAS1"
    assert "ROUND1" not in segment.meta_json.get("pnr_aliases", [])


def test_legacy_immutable_fact_hash_still_roundtrips_without_lifecycle_field(db_user):
    db, user = db_user
    from app.services.booking_ledger import _key, event_time
    from app.services.flight_times import normalize_flight_times
    booked = legs()[0]
    normalize_flight_times(booked)
    apply(db, user, "old-original", [booked])
    original = db.query(BookingObservation).one()
    facts = deepcopy(original.facts)
    facts.pop("booking_lifecycle")
    original.facts = facts
    original.evidence_key = _key({"message": original.source_message_id,
        "event_at": event_time(original.source_event_at), "facts": facts})
    db.flush()
    assert _retained_flight(original, ownership="self") is not None
    assert original.facts == facts


def test_receipt_wording_can_reinstate_but_reminder_with_quoted_confirmation_cannot():
    receipt = "Here's your itinerary & receipt. See ya soon!"
    assert _booking_lifecycle("You're going to Austin on 02/14!", receipt,
                              cancellation=False)["can_reinstate"]
    assert not _booking_lifecycle("Your Austin trip is almost here!", receipt,
                                  cancellation=False)["can_reinstate"]


def test_carrier_recovery_treats_post_departure_cancellation_as_uncertain():
    from types import SimpleNamespace
    from app.services.carrier_travel_recovery import _uncertain_cancellation
    assert _uncertain_cancellation(SimpleNamespace(parse_error="post_departure_cancellation_conflict"))


def test_named_companion_cancellation_status_requires_its_own_passenger_scope(db_user):
    from app.services.travel_inbox import _cancellation_state
    db, user = db_user
    apply(db, user, "companion", legs(ownership="other"))
    companion = db.query(BookingObservation).filter_by(source_message_id="companion").first()
    apply(db, user, "owner-cancel", legs(), kind="cancellation", at="2025-02-10T12:00:00Z")
    assert _cancellation_state(db, user.id, companion, passenger_name="Other Guest") is None
    apply(db, user, "companion-cancel", legs(ownership="other"), kind="cancellation",
          at="2025-02-10T13:00:00Z")
    assert _cancellation_state(db, user.id, companion, passenger_name="Other Guest") == "canceled"


def test_other_passenger_notice_cannot_apply_an_existing_legacy_tombstone(db_user):
    from app.services.booking_ledger import record_cancellation
    db, user = db_user
    apply(db, user, "mine", legs())
    record_cancellation(db, user.id, "ROUND1", source_message_id="legacy",
        source_event_at=datetime(2025, 2, 1), flights=legs())
    apply(db, user, "other-cancel", legs(ownership="other"), kind="cancellation",
          at="2025-02-10T12:00:00Z")
    assert db.query(Segment).count() == 2


def test_conditions_footer_is_not_an_actual_mixed_cancellation_rebooking(db_user):
    db, user = db_user
    outcome = apply_booking_message(db, user.id, ParseResult(flights=legs("G4")),
        source_message_id="airline-cancel", subject="Your itinerary ROUND1",
        plain_text="Your booking has been canceled.\nConfirmation number: ROUND1\n"
            "Terms and Conditions\nA missed flight shall be deemed a customer-initiated cancellation "
            "and the remaining itinerary, including any return flights, will be canceled.",
        received_at="2025-02-18T12:00:00Z")
    assert outcome.review_reason == "post_departure_cancellation_conflict"
    assert len(db.query(BookingCancellation).one().facts["review_scopes"]) == 2
