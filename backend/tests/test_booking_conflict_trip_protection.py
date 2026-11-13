"""Publishing or locking a new journey removes automatic retirement authority."""
from contextlib import ExitStack
from copy import deepcopy

import pytest

from app.models import BookingCancellation, BookingObservation, Segment, Trip, User
from app.services.booking_legacy_repair import _state
from app.services.booking_ledger import flight_scope
from app.services.booking_projection_context import CREATION_MARKER, projection_run
from test_booking_lifecycle_hardening import apply, db_user, legs


@pytest.mark.parametrize("same_run", [False, True])
@pytest.mark.parametrize("lane", ["off", "unlisted", "on"])
@pytest.mark.parametrize("protection", ["public", "unlisted", "manual_grouping", "trip_grouping_locked",
                                       "manual_trip_id", "manual_assignment"])
def test_postdeparture_conflict_preserves_protected_parent_trip(db_user, monkeypatch, protection, same_run, lane):
    from app.services.flight_import_rollout import FEATURE_FLAGS, ALLOWLIST_ENV
    db, user = db_user
    for flag in FEATURE_FLAGS:
        monkeypatch.setenv(flag, str(lane != "off").lower())
    monkeypatch.setenv(ALLOWLIST_ENV, str(user.id if lane == "on" else user.id + 999))
    other = User(name=user.name, email="other-trip@example.test")
    db.add(other)
    db.flush()
    apply(db, other, "other-booking", legs())
    other_before = deepcopy(_state(db, other.id))
    with ExitStack() as stack:
        stack.enter_context(projection_run(db, user.id))
        apply(db, user, "original", legs())
        rows = db.query(Segment).join(Trip).filter(Trip.user_id == user.id).order_by(Segment.id).all()
        assert all(CREATION_MARKER in row.meta_json for row in rows)
        trip = db.get(Trip, rows[0].trip_id)
        assert {row.trip_id for row in rows} == {trip.id}
        trip.title = "Owner selected journey"
        if protection in {"public", "unlisted"}:
            trip.visibility = protection
        else:
            key, value = (("trip_assignment_source", "manual") if protection == "manual_assignment"
                          else (protection, trip.id if protection == "manual_trip_id" else True))
            # A sibling's explicit grouping choice protects the whole parent,
            # including the other member's exact conflicting scope.
            rows[0].meta_json = {**rows[0].meta_json, key: value}
        db.flush()
        before = deepcopy(_state(db, user.id))
        original_observations = deepcopy(before["observations"])
        if not same_run:
            stack.close()
            db.commit()
            stack.enter_context(projection_run(db, user.id))
        result = apply(db, user, "ambiguous-cancel", legs(), kind="cancellation", at="2025-02-18T12:00:00Z")
        assert result.review_reason == "post_departure_cancellation_conflict"
        assert result.held_conflict_retirements == 0
        assert result.canceled == 0
        after = _state(db, user.id)
        assert after["trips"] == before["trips"]
        assert after["segments"].keys() == before["segments"].keys()
        for sid, row in after["segments"].items():
            old = before["segments"][sid]
            assert {key: value for key, value in row.items() if key != "meta_json"} == {key: value for key, value in old.items() if key != "meta_json"}
            assert {key: value for key, value in row["meta_json"].items() if key != "booking_conflicts"} == old["meta_json"]
            conflict, = row["meta_json"]["booking_conflicts"]
            assert conflict["reason"] == "post_departure_cancellation_conflict"
            assert conflict["source_message_id"] == "ambiguous-cancel"
            assert conflict["scope"] == flight_scope(db.get(Segment, int(sid)))
        assert all(after["observations"][key] == value for key, value in original_observations.items())
        cancellation = db.query(BookingCancellation).filter_by(user_id=user.id).one()
        assert len(cancellation.facts["review_scopes"]) == 2
        assert not cancellation.scopes
        assert db.query(BookingObservation).filter_by(user_id=user.id).count() == 4
        stable = deepcopy(after)
        for repeat in range(4):
            repeated = apply(db, user, "ambiguous-cancel", legs(), kind="cancellation", at="2025-02-18T12:00:00Z")
            assert repeated.held_conflict_retirements == repeated.canceled == 0
            current = _state(db, user.id)
            if repeat == 0:
                # The first repeat can capture the real final annotated row.
                # It cannot change an active row, existing evidence or history.
                assert {key: value for key, value in current.items() if key != "history"} == {key: value for key, value in stable.items() if key != "history"}
                assert all(current["history"][key] == value for key, value in stable["history"].items())
                for hid in current["history"].keys() - stable["history"].keys():
                    history = current["history"][hid]
                    assert history["entity_type"] == "segment"
                    assert history["reason"] == "before_booking_cancellation"
                    assert history["snapshot"] == stable["segments"][str(history["entity_id"])]
                stable = deepcopy(current)
            else:
                assert current == stable
        assert _state(db, other.id) == other_before
