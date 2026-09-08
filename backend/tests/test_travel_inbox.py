"""Retention invariants independent of personal itinerary projection and sharing."""
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models import Base, BookingObservation, TravelInboxEvidence, TravelInboxItem, User
from app.services.booking_ledger import record_cancellation, record_flight_observations, record_user_decision
from app.services.travel_inbox import backfill_user_travel_inbox, retain_observation, serialize_item


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = User(name="Alex Avery", email="alex@example.com")
        db.add(user)
        db.commit()
        yield db, user
    engine.dispose()


def flight(*, name="Morgan Blake", ownership="other", pnr="SHARED", day="2025-02-23", number="NK1651"):
    names = ["Alex Avery", name] if ownership == "self" else [name]
    return SimpleNamespace(
        dep_airport="MCO", arr_airport="ATL",
        dep_time=datetime.fromisoformat(day + "T12:00:00+00:00"),
        arr_time=datetime.fromisoformat(day + "T15:00:00+00:00"),
        flight_number=number, pnr=pnr, airline="NK", aircraft=None,
        ownership=ownership, source="receipt", confidence=95,
        passenger_names=names,
        passenger_evidence=[{"name": value, "role": "traveler", "applies": True, "complete": True}
                            for value in names if value],
    )


def record(db, user, value=None, message="receipt", at="2025-01-20T12:00:00+00:00", **kwargs):
    return record_flight_observations(db, user.id, [value or flight()], source_message_id=message,
                                      source_event_at=at, **kwargs)


def item_states(db, user):
    return [serialize_item(db, user.id, item) for item in db.query(TravelInboxItem).filter_by(user_id=user.id)]


def old_rows(db):
    return {name: db.execute(select(table)).all() for name, table in Base.metadata.tables.items()
            if not name.startswith("travel_inbox_")}


def test_other_tickets_and_companions_have_private_stable_records(session):
    db, user = session
    record(db, user)
    item = db.query(TravelInboxItem).one()
    saved_id = item.id
    assert (item.passenger_name, item.reason) == ("Morgan Blake", "other_traveler")
    record(db, user, message="second-receipt", at="2025-01-21T12:00:00Z")
    record(db, user, message="second-receipt", at="2025-01-21T12:00:00Z")
    assert db.query(TravelInboxItem).one().id == saved_id
    assert db.query(TravelInboxEvidence).count() == 2
    record(db, user, flight(ownership="self", pnr="COMPAN"), message="shared")
    assert {(row.passenger_name, row.reason) for row in db.query(TravelInboxItem)} == {
        ("Morgan Blake", "other_traveler"), ("Morgan Blake", "companion"),
    }
    assert all(row["status"] == "retained" for row in item_states(db, user))
    assert db.query(User).count() == 1  # Never creates/looks up a recipient account.


def test_self_only_has_no_speculative_companions(session):
    db, user = session
    record(db, user, flight(name="Alex Avery", ownership="self"))
    no_manifest = flight(ownership="self")
    no_manifest.passenger_names = []
    no_manifest.passenger_evidence = []
    record(db, user, no_manifest, message="manifest-absent")
    assert db.query(TravelInboxItem).count() == 0


def test_unknown_and_ambiguous_sources_stay_unassigned_even_with_apparent_name(session):
    db, user = session
    record(db, user, flight(ownership="unknown"))
    ambiguous = flight(pnr="AMBIG1")
    ambiguous.passenger_evidence[0]["scope_ambiguous"] = True
    record(db, user, ambiguous, message="ambiguous")
    assert len(item_states(db, user)) == 2
    assert all(row["passenger_name"] is None and row["status"] == "needs_review" for row in item_states(db, user))


@pytest.mark.parametrize("changed", [
    {"pnr": "OTHER1"}, {"day": "2025-08-23"}, {"number": "NK512"},
    {"name": "Morgan Faith Blake"}, {"name": "Blake Morgan"},
])
def test_distinct_booking_leg_and_literal_name_are_not_merged(session, changed):
    db, user = session
    record(db, user)
    record(db, user, flight(**changed), message="different")
    assert db.query(TravelInboxItem).count() == 2


def test_weak_booking_identity_does_not_merge_different_emails(session):
    db, user = session
    record(db, user, flight(pnr=None), message="one")
    record(db, user, flight(pnr=None), message="two")
    record(db, user, flight(pnr=None), message="one")
    assert db.query(TravelInboxItem).count() == 2
    assert db.query(TravelInboxEvidence).count() == 2


def test_duplicate_receipt_name_normalization_without_fuzzy_identity(session):
    db, user = session
    record(db, user)
    record(db, user, flight(name=" MORGAN  BLAKE "), message="formatting")
    assert db.query(TravelInboxItem).count() == 1
    assert db.query(TravelInboxEvidence).count() == 2


def test_same_flight_in_different_accounts_remains_separate_and_cannot_be_linked(session):
    db, user = session
    other = User(name="Morgan Blake", email="morgan@example.com")
    db.add(other)
    db.flush()
    record(db, user)
    observation = db.query(BookingObservation).one()
    with pytest.raises(ValueError, match="another user"):
        retain_observation(db, other.id, observation)
    own_item = db.query(TravelInboxItem).one()
    with pytest.raises(ValueError, match="another user"):
        serialize_item(db, other.id, own_item)
    assert db.query(TravelInboxItem).filter_by(user_id=other.id).count() == 0


def test_later_passenger_evidence_does_not_erase_unknown_source_or_id(session):
    db, user = session
    record(db, user, flight(ownership="unknown"), message="unknown")
    original = db.query(TravelInboxItem).one().id
    record(db, user, message="complete", at="2025-01-21T12:00:00Z")
    assert db.get(TravelInboxItem, original).passenger_name is None
    assert db.query(TravelInboxItem).count() == 2
    assert len({row.flight_key for row in db.query(TravelInboxItem)}) == 1
    assert db.query(TravelInboxEvidence).count() == 2


def test_raw_shared_manifest_is_never_part_of_the_inbox_read_payload(session):
    db, user = session
    record(db, user, flight(ownership="self"))
    row = serialize_item(db, user.id, db.query(TravelInboxItem).one(), include_evidence=True)
    assert row["passenger_name"] == "Morgan Blake"
    assert row["evidence"][0]["source_message_id"] == "receipt"
    assert "Alex Avery" not in repr(row)
    assert "passenger_evidence" not in repr(row) and "passenger_names" not in repr(row)
    assert "recipient" not in repr(row)


def test_latest_facts_follow_source_time_instead_of_import_order(session):
    db, user = session
    newer = flight()
    newer.aircraft = "A321"
    record(db, user, newer, message="newer", at="2025-01-21T12:00:00Z")
    record(db, user, message="older")
    assert item_states(db, user)[0]["flight"]["aircraft"] == "A321"


@pytest.mark.parametrize("reverse", [False, True])
def test_current_reason_is_source_chronological_not_import_order(session, reverse):
    db, user = session
    sources = [(flight(), "older", "2025-01-20T12:00:00Z"),
               (flight(ownership="self"), "newer", "2025-01-21T12:00:00Z")]
    for value, message, at in reversed(sources) if reverse else sources:
        record(db, user, value, message=message, at=at)
    record_user_decision(db, user.id, flight(), ownership="self")
    row = item_states(db, user)[0]
    assert row["reason"] == "companion" and row["status"] == "retained"


def test_initial_alias_never_claims_a_named_travelers_ticket(session):
    db, user = session
    record(db, user)
    user.travel_name_aliases = ["M Blake"]
    assert item_states(db, user)[0]["status"] == "retained"
    user.travel_name_aliases = ["Morgan Blake"]
    assert item_states(db, user)[0]["status"] == "belongs_to_you"


def test_cancellation_retains_tickets_and_does_not_cross_pnr_dates(session):
    db, user = session
    record(db, user)
    record(db, user, flight(day="2025-08-23"), message="later-trip")
    record_cancellation(db, user.id, "SHARED", source_message_id="cancellation",
                        source_event_at="2025-01-21T12:00:00Z", flights=[flight()])
    states = {row["flight"]["travel_date"]: row["status"] for row in item_states(db, user)}
    assert states == {"2025-02-23": "canceled", "2025-08-23": "retained"}
    assert db.query(TravelInboxItem).count() == db.query(TravelInboxEvidence).count() == 2
    record(db, user, message="receipt-after-cancellation", at="2025-01-22T12:00:00Z")
    assert next(row for row in item_states(db, user) if row["flight"]["travel_date"] == "2025-02-23")["status"] == "needs_review"


def test_undated_cancellation_keeps_ticket_for_review(session):
    db, user = session
    record(db, user)
    record_cancellation(db, user.id, "SHARED", source_message_id="cancellation", flights=[flight()])
    assert item_states(db, user)[0]["status"] == "needs_review"


@pytest.mark.parametrize("ownership,status", [("self", "active"), ("self", "canceled"), ("other", "active")])
def test_personal_history_decisions_do_not_claim_or_cancel_companion(session, ownership, status):
    db, user = session
    record(db, user, flight(ownership="self"))
    saved_id = db.query(TravelInboxItem).one().id
    record_user_decision(db, user.id, flight(ownership="self"), ownership=ownership, status=status)
    row = item_states(db, user)[0]
    assert row["id"] == saved_id and row["status"] == "retained"
    assert row["observation_count"] == 2


def test_manual_other_without_manifest_retains_unnamed_ticket(session):
    db, user = session
    record_user_decision(db, user.id, flight(), ownership="other")
    row = item_states(db, user)[0]
    assert row["passenger_name"] is None and row["status"] == "needs_review"
    record_user_decision(db, user.id, flight(), ownership="self")
    assert item_states(db, user)[0]["id"] == row["id"]
    assert item_states(db, user)[0]["status"] == "belongs_to_you"


def test_explicit_self_confirmation_overrides_old_cancellation_for_unassigned_ticket(session):
    db, user = session
    record(db, user, flight(ownership="unknown"))
    record_cancellation(db, user.id, "SHARED", source_message_id="canceled",
                        source_event_at="2025-01-22T12:00:00Z", flights=[flight()])
    assert item_states(db, user)[0]["status"] == "canceled"
    record_user_decision(db, user.id, flight(), ownership="self", status="active")
    assert item_states(db, user)[0]["status"] == "belongs_to_you"


def test_weak_identity_user_decision_links_only_explicit_original_source(session):
    db, user = session
    unknown = flight(ownership="unknown", pnr=None)
    record(db, user, unknown, message="original")
    original = db.query(BookingObservation).one()
    original_item = db.query(TravelInboxItem).one().id
    record(db, user, unknown, message="separate-email")
    record_user_decision(db, user.id, unknown, ownership="self", source_observation_id=original.id)
    states = {row["id"]: row for row in item_states(db, user)}
    assert states[original_item]["status"] == "belongs_to_you"
    assert states[original_item]["observation_count"] == 2
    assert next(row for key, row in states.items() if key != original_item)["status"] == "needs_review"


def test_synthesized_personal_review_does_not_relabel_other_traveler_as_companion(session):
    db, user = session
    record(db, user)
    original = db.query(BookingObservation).one()
    decision = record_user_decision(db, user.id, flight(), ownership="self", source_observation_id=original.id)
    synthesized = flight(ownership="self")
    synthesized.source = "user_review"
    synthesized.passenger_names = ["Morgan Blake"]
    synthesized.passenger_evidence = flight().passenger_evidence
    record(db, user, synthesized, message=f"user-decision:{decision.id}", at="2026-01-01T12:00:00Z")
    row = item_states(db, user)[0]
    assert row["reason"] == "other_traveler" and row["status"] == "needs_review"
    assert db.query(BookingObservation).count() == 3  # Synthesized facts remain saved.
    assert backfill_user_travel_inbox(db, user.id)["items_added"] == 0
    assert item_states(db, user)[0]["reason"] == "other_traveler"


def test_retention_rolls_back_with_import_transaction(session):
    db, user = session
    record(db, user)
    assert db.query(TravelInboxItem).count() == 1
    db.rollback()
    assert db.query(TravelInboxItem).count() == db.query(BookingObservation).count() == 0
    assert db.query(TravelInboxEvidence).count() == 0


def test_backfill_is_additive_and_idempotent_for_all_old_rows(session):
    db, user = session
    value = flight()
    db.add(BookingObservation(
        user_id=user.id, evidence_key="a" * 64, source_message_id="legacy", pnr=value.pnr,
        travel_date="2025-02-23", dep_airport="MCO", arr_airport="ATL", flight_number=value.flight_number,
        ownership="other", facts={"passenger_names": value.passenger_names, "passenger_evidence": value.passenger_evidence},
    ))
    db.flush()
    before = old_rows(db)
    assert backfill_user_travel_inbox(db, user.id) == {
        "items_added": 1, "evidence_added": 1, "total_items": 1, "total_evidence": 1,
    }
    saved_id = db.query(TravelInboxItem).one().id
    assert backfill_user_travel_inbox(db, user.id) == {
        "items_added": 0, "evidence_added": 0, "total_items": 1, "total_evidence": 1,
    }
    assert old_rows(db) == before
    assert db.query(TravelInboxItem).one().id == saved_id
