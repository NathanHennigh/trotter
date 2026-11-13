"""Repeat imports preserve exactly one copy of each real itinerary change."""
from copy import deepcopy
from datetime import timedelta

import pytest

from app.models import BookingCancellation, BookingObservation, ItineraryHistory, Segment, Trip
from app.services.booking_legacy_repair import _state
from app.services.enrichment import enrich_user_segments
from test_booking_lifecycle_hardening import apply, db_user, legs


@pytest.mark.parametrize("contextual_grouping", [False, True])
@pytest.mark.parametrize("autoflush", [False, True])
def test_repeat_schedule_and_cancellation_keep_only_real_history(db_user, monkeypatch, contextual_grouping, autoflush):
    db, user = db_user
    db.autoflush = autoflush
    monkeypatch.setenv("FLIGHT_IMPORT_RECOVERY_USER_IDS", str(user.id))
    monkeypatch.setenv("BOOKING_CONTEXTUAL_TRIP_GROUPING_ENABLED", str(contextual_grouping).lower())
    other_leg = legs()[1]
    other_leg.pnr = "SECOND"
    other_leg.dep_time += timedelta(days=90)
    other_leg.arr_time += timedelta(days=90)
    apply(db, user, "unrelated", [other_leg])
    original = legs()[0]
    apply(db, user, "receipt", [original])
    db.commit()

    def state():
        return _state(db, user.id)

    def replay_twice(message, flights, *, kind="confirmation", at="2025-01-20T12:00:00Z"):
        before = state()
        for _ in range(2):
            apply(db, user, message, flights, kind=kind, at=at)
            db.commit()
            assert state() == before

    replay_twice("receipt", [original])
    current = db.query(Segment).filter_by(flight_number=original.flight_number).one()
    before = state()
    segment_id, trip_id = current.id, current.trip_id
    changed = deepcopy(original)
    changed.dep_time += timedelta(hours=2)
    changed.arr_time += timedelta(hours=2)
    apply(db, user, "schedule", [changed], kind="schedule", at="2025-02-01T00:00:00Z")
    db.commit()
    assert db.get(Segment, segment_id).dep_time == changed.dep_time.replace(tzinfo=None)
    assert db.get(Trip, trip_id).start_ts == changed.dep_time.replace(tzinfo=None)

    def assert_prior_rows_saved(previous, current_state):
        added = [row for key, row in current_state["history"].items() if key not in previous["history"]]
        assert len(added) == 2
        assert {(row["entity_type"], row["entity_id"]) for row in added} == {("segment", segment_id), ("trip", trip_id)}
        for kind, key in (("segment", segment_id), ("trip", trip_id)):
            old = previous[kind + "s"][str(key)]
            assert any(row["entity_type"] == kind and row["snapshot"] == old for row in added)
        assert all(current_state["history"][key] == value for key, value in previous["history"].items())

    assert_prior_rows_saved(before, state())
    replay_twice("schedule", [changed], kind="schedule", at="2025-02-01T00:00:00Z")
    before_cancel = state()
    apply(db, user, "cancel", [changed], kind="cancellation", at="2025-02-05T00:00:00Z")
    db.commit()
    assert db.get(Segment, segment_id) is None
    assert db.get(Trip, trip_id) is None
    assert db.query(Segment).one().flight_number == other_leg.flight_number
    assert_prior_rows_saved(before_cancel, state())
    replay_twice("cancel", [changed], kind="cancellation", at="2025-02-05T00:00:00Z")
    assert db.query(BookingCancellation).count() == 1


def test_enrichment_noop_and_rolled_back_change(db_user, monkeypatch):
    db, user = db_user
    apply(db, user, "receipt", [legs()[0]])
    db.commit()
    before = _state(db, user.id)
    monkeypatch.setattr("app.services.enrichment.enrich_segment", lambda *args, **kwargs: (False, False))
    assert enrich_user_segments(db, user.id, include_provider_lookup=False) == 0
    assert _state(db, user.id) == before
    revised = legs()[0]
    revised.dep_time += timedelta(minutes=45)
    revised.arr_time += timedelta(minutes=45)
    apply(db, user, "schedule", [revised], kind="schedule", at="2025-02-01T00:00:00Z")
    assert db.query(ItineraryHistory).count() > len(before["history"])
    db.rollback()
    assert _state(db, user.id) == before
    assert db.query(BookingObservation).count() == 1
