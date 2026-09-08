from datetime import datetime, timezone
from itertools import permutations
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import Base, BookingCancellation, BookingObservation, ItineraryHistory, Segment, Trip, User
from app.services.booking_ledger import (
    cancellation_scope_resolved, record_user_decision, snapshot_user_itinerary,
)
from app.services.builder import build_segments_and_trips_detailed, cancel_segments_for_pnr


def dt(value):
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)


@pytest.fixture
def db_user():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = User(email="nathan@example.com", name="Nathan")
        db.add(user)
        db.flush()
        yield db, user


def flight(number="UA1540", pnr="VALID1", dep="IAH", arr="DCA", day="2025-02-18", ownership="self", source="2025-01-29T10:00:00"):
    return SimpleNamespace(
        dep_airport=dep, arr_airport=arr, dep_time=dt(day + "T12:00:00"),
        arr_time=dt(day + "T15:00:00"), airline=number[:2], flight_number=number,
        pnr=pnr, pnr_aliases=[], source="text", source_received_at=dt(source),
        ownership=ownership, passenger_names=["Nathan" if ownership == "self" else "Rachel"],
        passenger_evidence={"source": "passenger_field"}, confidence=90, nonstop=False,
    )


def ingest(db, user, flights, message, **kwargs):
    return build_segments_and_trips_detailed(db, user.id, flights, source_message_id=message, **kwargs)


@pytest.mark.parametrize("order", list(permutations(("valid", "old", "cancel"))))
def test_orlando_replay_is_order_independent_and_preserves_all_evidence(db_user, order):
    db, user = db_user
    valid = [
        flight(),
        flight("B62023", "JET123", "DCA", "MCO", "2025-02-21"),
        flight("NK1651", "SPIRIT", "MCO", "ATL", "2025-02-23"),
        flight("NK512", "SPIRIT", "ATL", "IAH", "2025-02-23"),
    ]
    old = [flight("UA1685", "OLD123"), flight("UA1381", "OLD123", "DCA", "IAH", "2025-02-21")]
    for _ in range(2):
        for event in order:
            if event == "valid":
                ingest(db, user, valid, "valid")
            elif event == "old":
                ingest(db, user, old, "old")
            else:
                cancel_segments_for_pnr(db, user.id, "OLD123", flights=old,
                    source_message_id="cancel", received_at=dt("2025-01-29T11:00:00"))
        assert {row.flight_number for row in db.query(Segment).all()} == {"UA1540", "B62023", "NK1651", "NK512"}
    assert db.query(BookingObservation).count() == 6
    assert db.query(BookingCancellation).count() == 1
    assert {row.source_message_id for row in db.query(BookingObservation).all()} == {"valid", "old"}


def test_older_evidence_cannot_lower_source_timestamp_or_enable_intermediate_cancellation(db_user):
    db, user = db_user
    newer = flight(source="2025-01-29T15:00:00")
    older = flight(source="2025-01-29T10:00:00")
    ingest(db, user, [newer], "newer")
    ingest(db, user, [older], "older")
    segment = db.query(Segment).one()
    assert datetime.fromisoformat(segment.meta_json["source_received_at"]) == datetime(2025, 1, 29, 15)
    assert set(segment.meta_json["source_message_ids"]) == {"newer", "older"}
    assert cancel_segments_for_pnr(db, user.id, "VALID1", flights=[older], source_message_id="cancel",
                                   received_at=dt("2025-01-29T12:00:00")) == 0
    assert db.query(Segment).count() == 1


def test_cancellation_and_supersession_do_not_cross_reused_pnr_dates_or_users(db_user):
    db, user = db_user
    first = flight()
    later = flight(day="2025-06-18")
    second_user = User(email="someone@example.com")
    db.add(second_user)
    db.flush()
    ingest(db, user, [first, later], "dated-confirmation")
    ingest(db, second_user, [first], "other-user-confirmation")
    assert db.query(Segment).count() == 3
    cancel_segments_for_pnr(db, user.id, "VALID1", flights=[first], source_message_id="cancel",
                           received_at=dt("2025-01-29T12:00:00"))
    remaining = db.query(Segment).join(Trip).filter(Trip.user_id == user.id).all()
    assert [segment.dep_time.date().isoformat() for segment in remaining] == ["2025-06-18"]
    assert db.query(Segment).join(Trip).filter(Trip.user_id == second_user.id).count() == 1


def test_unknown_and_other_are_retained_and_only_exact_unknown_can_inherit_self(db_user):
    db, user = db_user
    unknown = flight(ownership="unknown")
    other = flight("UA999", "OTHER1", ownership="other")
    result = ingest(db, user, [unknown, other], "held")
    assert (result.held_unknown, result.held_other, result.inserted) == (1, 1, 0)
    assert db.query(BookingObservation).count() == 2
    ingest(db, user, [flight()], "self")
    linked = ingest(db, user, [unknown], "linked")
    reused = ingest(db, user, [flight(day="2025-06-18", ownership="unknown")], "unrelated-date")
    assert linked.updated == 1 and linked.held_unknown == 0
    assert reused.held_unknown == 1
    assert db.query(Segment).count() == 1


def test_force_review_cannot_supply_ownership_to_other_messages(db_user):
    db, user = db_user
    result = ingest(db, user, [flight()], "ambiguous", force_review=True)
    assert result.held_unknown == 1
    result = ingest(db, user, [flight(ownership="unknown")], "unknown")
    assert result.held_unknown == 1
    assert db.query(Segment).count() == 0
    assert db.query(BookingObservation).count() == 2


def test_known_other_correction_preserves_complete_legacy_segment_and_trip(db_user):
    db, user = db_user
    legacy = flight(ownership="unknown")
    build_segments_and_trips_detailed(db, user.id, [legacy])
    segment = db.query(Segment).one()
    segment.meta_json = {"original": {"unrecognized": "keep this"}, "pnr_aliases": ["ALIAS1"]}
    original_id, original_trip = segment.id, segment.trip_id
    result = ingest(db, user, [flight(ownership="other")], "other-passenger-proof")
    assert result.removed_other == 1
    assert db.query(Segment).count() == 0
    histories = db.query(ItineraryHistory).filter_by(entity_type="segment", entity_id=original_id).all()
    assert any(row.snapshot["meta_json"].get("original") == {"unrecognized": "keep this"} for row in histories)
    assert any(row.snapshot["trip_id"] == original_trip and row.snapshot["flight_number"] == "UA1540" for row in histories)
    assert db.query(ItineraryHistory).filter_by(entity_type="trip", entity_id=original_trip).count() >= 1
    assert db.query(BookingObservation).count() == 2


def test_unverified_alias_cannot_preserve_canceled_primary_booking(db_user):
    db, user = db_user
    booked = flight()
    booked.pnr_aliases = ["GUESS1"]
    ingest(db, user, [booked], "confirmed")
    cancel_segments_for_pnr(db, user.id, "VALID1", flights=[booked], source_message_id="cancel",
                           received_at=dt("2025-01-29T12:00:00"))
    assert db.query(Segment).count() == 0
    assert db.query(BookingObservation).one().facts["pnr_aliases"] == ["GUESS1"]


def test_unscoped_cancellation_is_retained_for_review_without_poisoning_reused_pnr(db_user):
    db, user = db_user
    assert cancel_segments_for_pnr(db, user.id, "VALID1", source_message_id="unscoped",
                                  received_at=dt("2025-01-29T12:00:00")) == 0
    assert not cancellation_scope_resolved(db, user.id, "VALID1", "unscoped")
    assert db.query(BookingCancellation).one().facts["scope_resolved"] is False
    assert ingest(db, user, [flight(day="2026-06-18")], "later-unrelated").inserted == 1


def test_user_confirmation_survives_conflicting_email_and_cancellation_replay(db_user):
    db, user = db_user
    fact = flight()
    cancel_segments_for_pnr(db, user.id, "VALID1", flights=[fact], source_message_id="cancel",
                           received_at=dt("2025-01-29T12:00:00"))
    record_user_decision(db, user.id, fact, ownership="self", status="active", reason="Nathan confirmed this flight")
    assert ingest(db, user, [flight(ownership="other")], "mismatched-replay").inserted == 1
    assert cancel_segments_for_pnr(db, user.id, "VALID1", flights=[fact], source_message_id="cancel",
                                  received_at=dt("2025-01-29T12:00:00")) == 0
    assert db.query(Segment).count() == 1
    record_user_decision(db, user.id, fact, ownership="self", status="canceled")
    cancel_segments_for_pnr(db, user.id, "VALID1", flights=[fact], source_message_id="manual-application")
    assert ingest(db, user, [fact], "self-replay").blocked_cancellation == 1
    assert db.query(Segment).count() == 0


def test_snapshots_are_additive_idempotent_and_survive_source_row_deletion(db_user):
    db, user = db_user
    fact = flight()
    ingest(db, user, [fact], "original")
    snapshot_user_itinerary(db, user.id, reason="legacy_seed")
    before = db.query(ItineraryHistory).count()
    assert snapshot_user_itinerary(db, user.id, reason="legacy_seed") == 0
    assert db.query(ItineraryHistory).count() == before
    cancel_segments_for_pnr(db, user.id, "VALID1", flights=[fact], source_message_id="cancel",
                           received_at=dt("2025-01-29T12:00:00"))
    assert db.query(ItineraryHistory).count() >= before
    assert db.query(BookingObservation).count() == 1


def test_sourced_import_and_cancel_leave_unrelated_legacy_rows_exactly_unchanged(db_user):
    db, user = db_user
    legacy_trip = Trip(user_id=user.id, title="Keep my custom trip", start_ts=dt("2024-08-01T12:00:00"),
                       end_ts=dt("2024-08-01T15:00:00"), visibility="private")
    unrelated_empty = Trip(user_id=user.id, title="Unrelated empty draft")
    db.add_all([legacy_trip, unrelated_empty])
    db.flush()
    # Deliberate legacy duplicates: a global rebuild would prune one, but this
    # unrelated historical record is outside the new booking's repair scope.
    for number in ("UA100", "UA100"):
        db.add(Segment(trip_id=legacy_trip.id, mode="flight", dep_airport="EWR", arr_airport="ORD",
                       dep_time=dt("2024-08-01T12:00:00"), arr_time=dt("2024-08-01T15:00:00"),
                       airline="UA", flight_number=number, pnr="LEGACY", meta_json={"legacy_notes": ["retain"]}))
    db.commit()
    def state(rows):
        return {row.id: {column.name: getattr(row, column.name) for column in row.__table__.columns} for row in rows}
    old_segments = state(db.query(Segment).all())
    old_trips = state(db.query(Trip).all())
    fact = flight()
    ingest(db, user, [fact], "new-confirmation")
    cancel_segments_for_pnr(db, user.id, "VALID1", flights=[fact], source_message_id="new-cancellation",
                           received_at=dt("2025-01-29T12:00:00"))
    assert state(db.query(Segment).all()) == old_segments
    assert state(db.query(Trip).all()) == old_trips
    canceled_history_ids = {row.entity_id for row in db.query(ItineraryHistory).filter_by(
        entity_type="segment", reason="canceled_booking").all()}
    assert not canceled_history_ids.intersection(old_segments)


def test_explicit_user_other_decision_can_correct_previously_verified_self(db_user):
    db, user = db_user
    fact = flight()
    ingest(db, user, [fact], "original-self")
    record_user_decision(db, user.id, fact, ownership="other", status="active", reason="User corrected the passenger")
    result = ingest(db, user, [fact], "replayed-self")
    assert result.held_other == 1 and result.removed_other == 1
    assert db.query(Segment).count() == 0
    assert db.query(Trip).count() == 0


def test_scoped_newer_same_booking_confirmation_can_rebook_after_cancellation(db_user):
    db, user = db_user
    old = flight()
    cancel_segments_for_pnr(db, user.id, "VALID1", flights=[old], source_message_id="cancel",
                           received_at=dt("2025-01-29T12:00:00"))
    newer = flight(number="UA1550", source="2025-01-29T13:00:00")
    assert ingest(db, user, [newer], "rebooked").inserted == 1
    assert ingest(db, user, [old], "old-forward").blocked_cancellation == 1
    assert [row.flight_number for row in db.query(Segment).all()] == ["UA1550"]


def test_same_pnr_and_flight_number_on_adjacent_dates_are_distinct_observations(db_user):
    db, user = db_user
    result = ingest(db, user, [flight(), flight(day="2025-02-19")], "two-dated-flights")
    assert result.inserted == 2
    assert {row.dep_time.date().isoformat() for row in db.query(Segment).all()} == {"2025-02-18", "2025-02-19"}


def test_enrichment_only_visits_explicitly_touched_segments_and_archives_them(db_user, monkeypatch):
    from app.services import enrichment
    db, user = db_user
    target = ingest(db, user, [flight()], "target")
    unrelated = ingest(db, user, [flight("UA100", "OTHER1", day="2024-06-01")], "unrelated")
    called = []
    def fake_enrich(segment, **kwargs):
        called.append(segment.id)
        segment.meta_json = {**segment.meta_json, "test_enriched": True}
        return True, False
    monkeypatch.setattr(enrichment, "enrich_segment", fake_enrich)
    monkeypatch.setattr(enrichment, "should_lookup_provider_flight", lambda *args: False)
    assert enrichment.enrich_user_segments(db, user.id, segment_ids=set()) == 0
    assert called == []
    assert enrichment.enrich_user_segments(db, user.id, segment_ids=target.affected_segment_ids) == 1
    assert set(called) == target.affected_segment_ids
    assert not target.affected_segment_ids.intersection(unrelated.affected_segment_ids)
    for segment in db.query(Segment).filter(Segment.id.in_(unrelated.affected_segment_ids)).all():
        assert "test_enriched" not in segment.meta_json
    archived = db.query(ItineraryHistory).filter_by(entity_type="segment", reason="before_segment_enrichment").all()
    assert {row.entity_id for row in archived} == target.affected_segment_ids


def test_repair_script_fetch_failure_preserves_existing_graph(db_user, monkeypatch, tmp_path):
    import importlib.util
    from pathlib import Path
    from app.models import Account, Message
    db, user = db_user
    ingest(db, user, [flight()], "legacy")
    db.add(Account(user_id=user.id, provider="google", refresh_token_encrypted=b"test", scopes="gmail.readonly"))
    db.add(Message(user_id=user.id, provider_msg_id="unavailable"))
    db.commit()
    expected_ids = {row.id for row in db.query(Segment).all()}
    expected_trip_ids = {row.id for row in db.query(Trip).all()}
    spec = importlib.util.spec_from_file_location("repair_script_under_test", Path(__file__).parents[1] / "scripts" / "rebuild_flight_segments.py")
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    monkeypatch.setattr(script, "SessionLocal", lambda: db)
    monkeypatch.setattr(script, "build_gmail_service", lambda _: object())
    monkeypatch.setattr(script, "_backup_path", lambda _: tmp_path / "backup.json")
    def unavailable(*args):
        raise RuntimeError("synthetic fetch failure")
    monkeypatch.setattr(script, "get_message", unavailable)
    report = script.rebuild(user.email, apply=True, limit=None, progress_every=1)
    assert report["fetch_errors"] == 1
    assert report["before_segments"] == report["after_segments"] == 1
    assert {row.id for row in db.query(Segment).all()} == expected_ids
    assert {row.id for row in db.query(Trip).all()} == expected_trip_ids
    assert (tmp_path / "backup.json").exists()


def test_user_decision_preserves_explicit_source_for_weak_booking_identity(db_user):
    db, user = db_user
    value = flight(pnr=None, ownership="unknown")
    ingest(db, user, [value], "weak-source")
    source = db.query(BookingObservation).filter_by(source_message_id="weak-source").one()
    decision = record_user_decision(db, user.id, value, source_observation_id=source.id)
    assert decision.facts["user_decision"]["source_observation_id"] == source.id
    assert source.facts.get("user_decision") is None
    legacy = record_user_decision(db, user.id, value)
    assert "source_observation_id" not in legacy.facts["user_decision"]


@pytest.mark.parametrize("changed", [
    {"day": "2025-02-19"}, {"dep": "DCA", "arr": "IAH"},
    {"number": "UA999"}, {"pnr": "OTHER1"}, {"pnr": None},
])
def test_user_decision_rejects_different_source_scope_before_archiving_or_mutation(db_user, changed):
    db, user = db_user
    ingest(db, user, [flight()], "original-scope")
    source = db.query(BookingObservation).filter_by(source_message_id="original-scope").one()
    before = tuple(db.query(model).count() for model in (BookingObservation, ItineraryHistory, Segment, Trip))
    with pytest.raises(ValueError, match="exact booking and dated flight"):
        record_user_decision(db, user.id, flight(**changed), source_observation_id=source.id)
    assert tuple(db.query(model).count() for model in (BookingObservation, ItineraryHistory, Segment, Trip)) == before


def test_user_decision_rejects_missing_and_other_owner_sources_before_mutation(db_user):
    db, user = db_user
    other = User(email="private-observation@example.com")
    db.add(other)
    db.flush()
    ingest(db, other, [flight()], "private-source")
    source = db.query(BookingObservation).filter_by(source_message_id="private-source").one()
    before = tuple(db.query(model).count() for model in (BookingObservation, ItineraryHistory, Segment, Trip))
    for source_id in (source.id, source.id + 99999):
        with pytest.raises(ValueError, match="not found for this user"):
            record_user_decision(db, user.id, flight(), source_observation_id=source_id)
        assert tuple(db.query(model).count() for model in (BookingObservation, ItineraryHistory, Segment, Trip)) == before


def test_source_scope_uses_same_canonical_flight_number_as_review_api(db_user):
    db, user = db_user
    ingest(db, user, [flight(number="UA01540")], "zero-padded-flight")
    source = db.query(BookingObservation).filter_by(source_message_id="zero-padded-flight").one()
    decision = record_user_decision(db, user.id, flight(number="UA1540"), source_observation_id=source.id)
    assert decision.facts["user_decision"]["source_observation_id"] == source.id
