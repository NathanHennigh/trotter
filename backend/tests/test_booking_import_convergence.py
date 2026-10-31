"""A named receipt immediately resolves only its retained, exact dated leg."""
from copy import deepcopy
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, BookingObservation, MessageStatus, Segment, Trip, User
from app.services.booking_import import apply_booking_message
from app.services.booking_ledger import record_cancellation, record_user_decision
from app.services.flight_times import normalize_flight_times
from app.services.parser import ParsedFlight, ParseResult


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as db:
        user = User(name="Alex Avery", email="alex@example.com")
        db.add(user)
        db.flush()
        yield db, user
    engine.dispose()


def flight(ownership="unknown", hour=15, day=21, pnr="TEST01", number="UA123"):
    result = ParsedFlight("IAH", "DCA", datetime(2025, 2, day, hour, tzinfo=timezone.utc),
        datetime(2025, 2, day, hour + 4, tzinfo=timezone.utc), airline="UA", flight_number=number,
        pnr=pnr, ownership=ownership, source="test", passenger_names=["Alex Avery"] if ownership == "self" else [])
    normalize_flight_times(result)
    return result


def apply(db, user, source, value, event="2025-01-02T12:00:00Z"):
    return apply_booking_message(db, user.id, ParseResult(flights=[value]), source_message_id=source,
        subject="Flight confirmation", received_at=event)


def projection(db):
    return [(s.id, s.trip_id, s.dep_airport, s.arr_airport, s.dep_time, s.arr_time,
             s.flight_number, s.pnr, deepcopy(s.meta_json)) for s in db.query(Segment).order_by(Segment.id)]


def observations(db):
    return [(s.id, s.evidence_key, deepcopy(s.facts)) for s in db.query(BookingObservation).order_by(BookingObservation.id)]


@pytest.mark.parametrize("reverse", [False, True])
def test_named_receipt_projects_pending_schedule_on_first_pass_and_is_idempotent(session, reverse):
    db, user = session
    notices = [("receipt", flight("self", hour=14), "2025-01-01T12:00:00Z"),
               ("schedule", flight(hour=15), "2025-01-02T12:00:00Z")]
    for source, value, event in reversed(notices) if reverse else notices:
        apply(db, user, source, value, event)
    assert db.query(Segment).count() == 1
    segment = db.query(Segment).one()
    assert segment.dep_time == datetime(2025, 2, 21, 21)  # 15:00 Houston
    assert segment.arr_time == datetime(2025, 2, 22, 0)  # 19:00 Washington
    assert segment.meta_json["source_received_at"].startswith("2025-01-02T12:00:00")
    original = observations(db)
    assert len(original) == 2
    assert {facts["ownership"] for _, _, facts in original} == {"self", "unknown"}
    before = projection(db)
    for source, value, event in notices:
        apply(db, user, source, value, event)
    assert projection(db) == before
    assert observations(db) == original


def test_new_proof_replays_notices_in_original_event_order(session):
    db, user = session
    apply(db, user, "latest", flight(hour=16), "2025-01-03T12:00:00Z")
    apply(db, user, "middle", flight(hour=15), "2025-01-02T12:00:00Z")
    original = observations(db)
    result = apply(db, user, "receipt", flight("self", hour=14), "2025-01-01T12:00:00Z")
    assert db.query(Segment).one().dep_time == datetime(2025, 2, 21, 22)
    assert observations(db)[:2] == original
    assert db.query(BookingObservation).count() == 3
    assert result.status == MessageStatus.ACCEPTED


def test_replayed_change_is_counted_and_scheduled_for_enrichment(session):
    db, user = session
    pending = flight(hour=15)
    apply(db, user, "pending", pending)
    result = apply(db, user, "receipt", flight("self", hour=14), "2025-01-01T12:00:00Z")
    segment = db.query(Segment).one()
    assert segment.dep_time == datetime(2025, 2, 21, 21)
    assert result.build.inserted == 1
    assert result.build.updated == 1
    assert result.build.affected_segment_ids == {segment.id}
    assert result.status == MessageStatus.ACCEPTED


@pytest.mark.parametrize("malformation", ["provenance_type", "index_pnr", "index_route", "index_number", "index_date"])
def test_inconsistent_saved_evidence_stays_held_without_breaking_import(session, malformation):
    from app.services.booking_import import _retained_flight
    db, user = session
    apply(db, user, "pending", flight())
    row = db.query(BookingObservation).one()
    if malformation == "provenance_type":
        facts = deepcopy(row.facts)
        facts["time_provenance"] = ["bad legacy value"]
        row.facts = facts
    elif malformation == "index_pnr":
        row.pnr = "OTHER1"
    elif malformation == "index_route":
        row.arr_airport = "DFW"
    elif malformation == "index_number":
        row.flight_number = "UA124"
    else:
        row.travel_date = "2025-02-22"
    assert _retained_flight(row) is None
    result = apply(db, user, "receipt", flight("self", hour=14), "2025-01-01T12:00:00Z")
    assert db.query(Segment).one().dep_time == datetime(2025, 2, 21, 20)
    assert db.query(BookingObservation).count() == 2
    assert result.status == MessageStatus.ACCEPTED


@pytest.mark.parametrize("difference", ["account", "pnr", "day", "number", "other", "force_review",
                                        "missing_time", "uncertain_time", "missing_event"])
def test_new_proof_does_not_promote_unrelated_or_uncertain_facts(session, difference):
    db, user = session
    pending_user = user
    pending = flight()
    event = "2025-01-02T12:00:00Z"
    if difference == "account":
        pending_user = User(name="Morgan Avery", email="morgan@example.com")
        db.add(pending_user)
        db.flush()
    elif difference == "pnr":
        pending.pnr = "OTHER1"
    elif difference == "day":
        pending = flight(day=22)
    elif difference == "number":
        pending.flight_number = "UA124"
    elif difference == "other":
        pending.ownership = "other"
        pending.passenger_names = ["Morgan Avery"]
    elif difference == "force_review":
        pending.force_review = True
    elif difference == "missing_time":
        pending.time_provenance = None
    elif difference == "uncertain_time":
        pending.time_provenance["status"] = "needs_review"
    elif difference == "missing_event":
        event = None
    apply(db, pending_user, "pending", pending, event)
    before = observations(db)
    result = apply(db, user, "receipt", flight("self", hour=14), "2025-01-01T12:00:00Z")
    assert db.query(Segment).count() == 1
    assert db.query(Segment).one().dep_time == datetime(2025, 2, 21, 20)
    assert observations(db)[:1] == before
    assert db.query(BookingObservation).count() == 2
    assert result.status == MessageStatus.ACCEPTED


@pytest.mark.parametrize("decision", ["hold", "canceled", "other"])
def test_manual_negative_decision_is_preserved(session, decision):
    db, user = session
    pending = flight()
    apply(db, user, "pending", pending)
    record_user_decision(db, user.id, pending,
        ownership="other" if decision == "other" else "self",
        status="active" if decision == "other" else decision)
    before = observations(db)
    apply(db, user, "receipt", flight("self", hour=14), "2025-01-01T12:00:00Z")
    assert db.query(Segment).count() == 0
    assert observations(db)[:2] == before


def test_cancellation_does_not_gain_new_event_time_from_later_received_proof(session):
    db, user = session
    pending = flight()
    apply(db, user, "pending", pending)
    record_cancellation(db, user.id, pending.pnr, source_message_id="cancel",
        source_event_at=datetime(2025, 1, 3), flights=[pending])
    apply(db, user, "receipt", flight("self", hour=14), "2025-01-01T12:00:00Z")
    assert db.query(Segment).count() == 0
    assert db.query(BookingObservation).count() == 2


def test_older_canceled_notice_does_not_overwrite_genuinely_newer_rebooking(session):
    db, user = session
    pending = flight()
    apply(db, user, "pending", pending)
    record_cancellation(db, user.id, pending.pnr, source_message_id="cancel",
        source_event_at=datetime(2025, 1, 3), flights=[pending])
    result = apply(db, user, "rebooked", flight("self", hour=14), "2025-01-04T12:00:00Z")
    assert db.query(Segment).one().dep_time == datetime(2025, 2, 21, 20)
    assert db.query(BookingObservation).count() == 2
    assert result.status == MessageStatus.ACCEPTED


def test_existing_self_proof_does_not_replay_retained_notices_again(session, monkeypatch):
    from app.services import booking_import
    db, user = session
    apply(db, user, "pending", flight())
    apply(db, user, "receipt", flight("self", hour=14), "2025-01-01T12:00:00Z")
    calls = []
    original = booking_import.build_segments_and_trips_detailed
    def build(*args, **kwargs):
        calls.append(kwargs["source_message_id"])
        return original(*args, **kwargs)
    monkeypatch.setattr(booking_import, "build_segments_and_trips_detailed", build)
    apply(db, user, "receipt-again", flight("self", hour=14), "2025-01-01T12:00:00Z")
    assert calls == ["receipt-again"]


def test_replay_failure_rolls_back_new_proof_and_projection_atomically(session, monkeypatch):
    from app.services import booking_import
    db, user = session
    apply(db, user, "pending", flight())
    db.commit()
    before = observations(db)
    original = booking_import.build_segments_and_trips_detailed
    def build(*args, **kwargs):
        result = original(*args, **kwargs)
        if kwargs["source_message_id"] == "pending":
            raise RuntimeError("interrupted")
        return result
    monkeypatch.setattr(booking_import, "build_segments_and_trips_detailed", build)
    with pytest.raises(RuntimeError, match="interrupted"):
        apply(db, user, "receipt", flight("self", hour=14), "2025-01-01T12:00:00Z")
    db.rollback()
    assert db.query(Segment).count() == 0
    assert observations(db) == before


@pytest.mark.parametrize("reverse", [False, True])
def test_removal_of_other_booking_revisits_original_personal_receipt_immediately(session, reverse):
    from test_legacy_local_clock_replay import seed
    db, user = session
    other = flight("other", hour=14, pnr="OTHER1")
    other.passenger_names = ["Morgan Avery"]
    seed(db, user, other)
    own = flight("self", hour=15, pnr="OWN001")
    notices = [("own-receipt", own), ("other-receipt", other)]
    outcomes = {}
    for source, value in reversed(notices) if reverse else notices:
        outcomes[source] = apply(db, user, source, value)
    segment = db.query(Segment).one()
    assert (segment.pnr, segment.dep_time) == ("OWN001", datetime(2025, 2, 21, 21))
    assert "OTHER1" not in segment.meta_json.get("pnr_aliases", [])
    removed = outcomes["other-receipt"]
    assert removed.build.removed_other == 1
    assert removed.build.removed_leg_scopes == [{"travel_date": "2025-02-21",
        "dep_airport": "IAH", "arr_airport": "DCA", "flight_number": "UA123"}]
    if not reverse:
        assert outcomes["own-receipt"].review_reason == "legacy_flight_identity_conflict"
        assert removed.build.inserted == 1
        assert removed.build.affected_segment_ids == {segment.id}
    assert removed.status == MessageStatus.ACCEPTED
    before, evidence = projection(db), observations(db)
    assert len(evidence) == 2
    for source, value in notices:
        apply(db, user, source, value)
    assert projection(db) == before
    assert observations(db) == evidence


@pytest.mark.parametrize("protection", ["hold", "canceled", "other", "cancellation",
                                        "unknown", "force_review", "missing_event", "missing_time"])
def test_other_projection_removal_never_bypasses_retained_receipt_protection(session, protection):
    from test_legacy_local_clock_replay import seed
    db, user = session
    other = flight("other", hour=14, pnr="OTHER1")
    other.passenger_names = ["Morgan Avery"]
    seed(db, user, other)
    own = flight("unknown" if protection == "unknown" else "self", hour=15, pnr="OWN001")
    if protection == "force_review":
        own.force_review = True
    if protection == "missing_time":
        own.time_provenance = None
        # Preserve the historical local-clock representation; this is not a
        # validated same-source match that may bypass the collision hold.
        own.dep_time = datetime(2025, 2, 21, 15, tzinfo=timezone.utc)
        own.arr_time = datetime(2025, 2, 21, 19, tzinfo=timezone.utc)
    if protection == "missing_time":
        from app.services.booking_ledger import record_flight_observations
        record_flight_observations(db, user.id, [own], source_message_id="own-receipt",
                                  source_event_at=datetime(2025, 1, 2))
    else:
        apply(db, user, "own-receipt", own, None if protection == "missing_event" else "2025-01-02T12:00:00Z")
    if protection in {"hold", "canceled", "other"}:
        record_user_decision(db, user.id, own, ownership="other" if protection == "other" else "self",
            status="active" if protection == "other" else protection)
    elif protection == "cancellation":
        record_cancellation(db, user.id, own.pnr, source_message_id="cancel-own",
            source_event_at=datetime(2025, 1, 3), flights=[own])
    before = observations(db)
    result = apply(db, user, "other-receipt", other, "2025-01-04T12:00:00Z")
    assert result.build.removed_other == 1
    assert result.build.inserted == 0
    assert observations(db)[:len(before)] == before
    assert result.status == MessageStatus.ACCEPTED
    assert db.query(Segment).count() == 0


@pytest.mark.parametrize("different", ["account", "date", "number", "route"])
def test_other_removal_recheck_is_exact_user_and_physical_leg(session, different):
    from app.services.booking_ledger import record_flight_observations
    from test_legacy_local_clock_replay import seed
    db, user = session
    other = flight("other", hour=14, pnr="OTHER1")
    seed(db, user, other)
    own = flight("self", hour=15, pnr="OWN001")
    owner = user
    if different == "account":
        owner = User(name="Taylor Avery", email="taylor@example.com")
        db.add(owner)
        db.flush()
    elif different == "date":
        own = flight("self", hour=15, day=22, pnr="OWN001")
    elif different == "number":
        own.flight_number = "UA124"
    else:
        own.arr_airport = "IAD"
    own.source_received_at = datetime(2025, 1, 2)
    record_flight_observations(db, owner.id, [own], source_message_id="held-own",
                              source_event_at=datetime(2025, 1, 2))
    result = apply(db, user, "other-receipt", other)
    assert result.build.removed_other == 1 and result.build.inserted == 0
    assert db.query(Segment).count() == 0
