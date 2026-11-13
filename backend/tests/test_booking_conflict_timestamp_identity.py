"""A timestamptz reload cannot turn one retained notice into two conflicts."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.models import BookingCancellation, Segment, Trip
from app.services.booking_legacy_repair import _state
from app.services.booking_ledger import _mark_cancellation_conflicts, _same_cancellation_conflict
from app.services.booking_projection_context import projection_run
from test_booking_lifecycle_hardening import apply, db_user, legs


def conflict(stamp):
    return {"reason": "post_departure_cancellation_conflict", "pnr": "ROUND1",
            "source_message_id": "cancel", "source_event_at": stamp,
            "scope": {"travel_date": "2025-02-14", "dep_airport": "DAL", "arr_airport": "AUS", "flight_number": "WN120"}}


EQUIVALENT = ["2025-02-18T12:00:00", "2025-02-18T12:00:00+00:00", "2025-02-18T12:00:00Z",
              "2025-02-18T07:00:00-05:00", "2025-02-18T15:00:00+03:00",
              datetime(2025, 2, 18, 12), datetime(2025, 2, 18, 12, tzinfo=timezone.utc)]


@pytest.mark.parametrize("old_stamp", EQUIVALENT)
@pytest.mark.parametrize("new_stamp", EQUIVALENT)
def test_equivalent_conflict_instants_have_same_identity_without_mutation(old_stamp, new_stamp):
    left, right = conflict(old_stamp), conflict(new_stamp)
    before = deepcopy((left, right))
    assert _same_cancellation_conflict(left, right)
    assert (left, right) == before


@pytest.mark.parametrize("field,value", [
    ("source_event_at", "2025-02-18T12:00:01Z"),
    ("source_event_at", "2025-02-18T12:00:00+03:00"),
    ("source_message_id", "different-source"), ("pnr", "OTHER1"),
    ("reason", "different-reason"),
    ("scope", {"travel_date": "2025-02-17", "dep_airport": "AUS", "arr_airport": "DAL", "flight_number": "WN230"}),
    ("scope", {"travel_date": "2025-02-14", "dep_airport": "DAL", "arr_airport": "AUS", "flight_number": "WN999"}),
])
def test_distinct_notice_authority_is_not_deduplicated(field, value):
    left, right = conflict(EQUIVALENT[0]), conflict(EQUIVALENT[1])
    right[field] = value
    assert not _same_cancellation_conflict(left, right)


@pytest.mark.parametrize("invalid", [None, "", "not-a-date", "2025-02-30T12:00:00", [], {}, 123, True])
def test_malformed_timestamps_never_match_a_valid_instant(invalid):
    assert not _same_cancellation_conflict(conflict(invalid), conflict(EQUIVALENT[0]))
    if invalid is not None:
        assert not _same_cancellation_conflict(conflict(invalid), conflict(None))
    assert not _same_cancellation_conflict(conflict(invalid), conflict("a-different-invalid-date"))


def test_missing_stamp_and_non_mapping_annotations_are_not_equated():
    missing = conflict(None)
    del missing["source_event_at"]
    assert not _same_cancellation_conflict(missing, conflict(None))
    for malformed in (None, [], "old malformed annotation", 1):
        assert not _same_cancellation_conflict(malformed, conflict(EQUIVALENT[0]))


@pytest.mark.parametrize("stored_stamp", EQUIVALENT[:5])
@pytest.mark.parametrize("offset", [0, -5, 3])
def test_reloaded_notice_preserves_existing_annotation_and_entire_state(db_user, stored_stamp, offset):
    db, user = db_user
    with projection_run(db, user.id):
        apply(db, user, "original", legs())
    trip = db.query(Trip).one()
    trip.visibility = "public"
    apply(db, user, "cancel", legs(), kind="cancellation", at="2025-02-18T12:00:00Z")
    for row in db.query(Segment):
        meta = deepcopy(row.meta_json)
        assert len(meta["booking_conflicts"]) == 1
        meta["booking_conflicts"][0]["source_event_at"] = stored_stamp
        row.meta_json = meta
    db.flush()
    event = db.query(BookingCancellation).one()
    # A transient view models exactly PostgreSQL's reloaded aware timestamptz;
    # retained ORM cancellation/observation rows are never edited by this test.
    reloaded = SimpleNamespace(pnr=event.pnr, source_message_id=event.source_message_id,
        source_event_at=datetime(2025, 2, 18, 12, tzinfo=timezone.utc).astimezone(timezone(timedelta(hours=offset))),
        facts=deepcopy(event.facts))
    before = deepcopy(_state(db, user.id))
    for _ in range(3):
        _mark_cancellation_conflicts(db, user.id, reloaded)
        assert reloaded.retired_conflict_segment_ids == []
        assert _state(db, user.id) == before


def test_new_conflict_serializes_canonical_time_without_rewriting_old_entries(db_user):
    db, user = db_user
    apply(db, user, "original", legs())
    trip = db.query(Trip).one()
    trip.visibility = "public"
    apply(db, user, "cancel", legs(), kind="cancellation", at="2025-02-18T12:00:00Z")
    event = db.query(BookingCancellation).one()
    old = {row.id: deepcopy(row.meta_json["booking_conflicts"]) for row in db.query(Segment)}
    distinct = SimpleNamespace(pnr=event.pnr, source_message_id="different-source",
        source_event_at=datetime(2025, 2, 18, 7, tzinfo=timezone(timedelta(hours=-5))), facts=deepcopy(event.facts))
    _mark_cancellation_conflicts(db, user.id, distinct)
    for row in db.query(Segment):
        assert row.meta_json["booking_conflicts"][:-1] == old[row.id]
        assert row.meta_json["booking_conflicts"][-1]["source_event_at"] == "2025-02-18T12:00:00"
        assert row.meta_json["booking_conflicts"][-1]["source_message_id"] == "different-source"
