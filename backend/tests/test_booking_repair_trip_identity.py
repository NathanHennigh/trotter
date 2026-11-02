"""New-trip allocation is not identity; every reviewed itinerary fact still is."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from app.models import BookingRepairManifest, Segment, Trip
from app.services import booking_legacy_repair as repair
from app.services.booking_ledger import _key
from app.services.booking_repair import RepairConflict
from test_booking_leg_lineage import context  # noqa: F401
from test_booking_legacy_repair import setup_case


def split_case(context, monkeypatch, new_trips=1):
    monkeypatch.setenv('BOOKING_CONTEXTUAL_TRIP_GROUPING_ENABLED', 'true')
    db, user, other, legacy, evidence, spec = setup_case(context)
    # These values deliberately overlap IDs, but are not trip references.
    legacy.meta_json = {**legacy.meta_json, 'reference_numbers': {'trip_id': 2, 'values': [1, 2, 3]}}
    for index in range(new_trips):
        day = datetime(2026, 7 + index * 4, 1, 12, tzinfo=timezone.utc)
        db.add(Segment(trip_id=legacy.trip_id, mode='flight', dep_airport='IAH', arr_airport='ORD',
            dep_time=day, arr_time=day + timedelta(hours=3), airline='AA',
            flight_number=f'AA70{index}', pnr=f'OTHER{index}',
            meta_json={'ownership': 'self', 'observation_ids': [evidence.id]}))
    db.commit()
    return db, user, other, legacy, spec


def apply(db, user, plan):
    return repair.apply_legacy_repair(db, user.id, plan.id, expected_plan_hash=plan.plan_hash)


def assert_reviewed_result(db, user, plan, result):
    assert {k: v for k, v in result.items() if k != 'created_trip_ids'} == plan.preview_json
    assert 'created_trip_ids' not in plan.preview_json
    assert set(result['created_trip_ids']) == {key for key in result['memberships'] if key.startswith('new:')}
    for reference, actual_id in result['created_trip_ids'].items():
        assert db.get(Trip, actual_id).user_id == user.id
        assert sorted(row.id for row in db.query(Segment).filter_by(trip_id=actual_id)) == result['memberships'][reference]


@pytest.mark.parametrize('new_trips', [1, 2])
def test_new_trips_apply_after_other_account_consumes_preview_ids(context, monkeypatch, new_trips):
    db, user, other, legacy, spec = split_case(context, monkeypatch, new_trips)
    before = repair._state(db, user.id)
    plan = repair.prepare_legacy_repair(db, user.id, [spec]); db.commit()
    assert plan.schema_version == plan.manifest_json['version'] == 3
    assert repair._state(db, user.id) == before
    assert plan.preview_json['trips_after'] == plan.preview_json['trips_before'] + new_trips
    saved_preview = deepcopy(plan.preview_json)
    # SQLite ordinarily reuses a rolled-back ID. These inserts force a genuine
    # difference between preview and apply, as PostgreSQL sequences do normally.
    db.add_all([Trip(user_id=other.id, title=f'Other account {n}') for n in range(5)])
    db.commit()
    other_before = repair._state(db, other.id)
    result = apply(db, user, plan)
    assert_reviewed_result(db, user, plan, result)
    assert db.get(Segment, legacy.id).meta_json['reference_numbers'] == {'trip_id': 2, 'values': [1, 2, 3]}
    assert repair._state(db, other.id) == other_before
    assert plan.preview_json == saved_preview
    applied = repair._state(db, user.id)
    assert apply(db, user, plan) == result
    assert repair._state(db, user.id) == applied


def test_interrupted_split_rolls_back_and_retries_after_more_allocations(context, monkeypatch):
    db, user, other, _, spec = split_case(context, monkeypatch)
    before = repair._state(db, user.id)
    plan = repair.prepare_legacy_repair(db, user.id, [spec]); db.commit()
    real = repair.rebuild_affected_trips

    def interrupted(*args):
        real(*args)
        raise RuntimeError('Interrupted after new trip allocation')

    monkeypatch.setattr(repair, 'rebuild_affected_trips', interrupted)
    with pytest.raises(RuntimeError, match='Interrupted'):
        apply(db, user, plan)
    assert repair._state(db, user.id) == before
    assert db.get(BookingRepairManifest, plan.id).state == 'previewed'
    db.add(Trip(user_id=other.id, title='Unrelated allocation')); db.commit()
    monkeypatch.setattr(repair, 'rebuild_affected_trips', real)
    assert_reviewed_result(db, user, plan, apply(db, user, plan))


@pytest.mark.parametrize('change', ['title', 'start_ts', 'end_ts', 'visibility', 'ownership',
    'membership', 'existing_identity', 'extra_trip', 'unrelated_trip', 'corrected_clock', 'corrected_metadata'])
def test_real_apply_differences_still_reject_and_restore_the_entire_account(context, monkeypatch, change):
    db, user, _, legacy, spec = split_case(context, monkeypatch)
    unrelated = Trip(user_id=user.id, title='Retain this empty draft')
    db.add(unrelated); db.commit()
    before = repair._state(db, user.id)
    existing_id = legacy.trip_id
    old_ids = {int(key) for key in before['trips']}
    plan = repair.prepare_legacy_repair(db, user.id, [spec]); db.commit()
    real = repair.rebuild_affected_trips

    def changed(*args):
        result = real(*args)
        created = db.query(Trip).filter(Trip.user_id == user.id, ~Trip.id.in_(old_ids)).one()
        if change == 'title': created.title = 'Different title'
        elif change in {'start_ts', 'end_ts'}:
            setattr(created, change, getattr(created, change) + timedelta(hours=1))
        elif change == 'visibility': created.visibility = 'public'
        elif change == 'ownership': created.user_id = context[2].id
        elif change == 'membership':
            member = db.query(Segment).filter_by(trip_id=created.id).one()
            member.trip_id = existing_id
        elif change == 'existing_identity':
            old = db.get(Trip, existing_id)
            clone = Trip(user_id=old.user_id, title=old.title, start_ts=old.start_ts,
                         end_ts=old.end_ts, visibility=old.visibility)
            db.add(clone); db.flush()
            for member in db.query(Segment).filter_by(trip_id=old.id): member.trip_id = clone.id
            db.flush(); db.delete(old)
        elif change == 'extra_trip': db.add(Trip(user_id=user.id, title='Unexpected draft'))
        elif change == 'unrelated_trip': db.get(Trip, unrelated.id).title = 'Unexpected change'
        elif change == 'corrected_clock': legacy.dep_time += timedelta(minutes=1)
        else: legacy.meta_json = {**legacy.meta_json, 'unexpected': True}
        db.flush()
        return result

    monkeypatch.setattr(repair, 'rebuild_affected_trips', changed)
    with pytest.raises(RepairConflict):
        apply(db, user, plan)
    assert repair._state(db, user.id) == before
    assert db.get(BookingRepairManifest, plan.id).state == 'previewed'


@pytest.mark.parametrize('already_applied', [False, True])
def test_old_manifests_require_a_new_preview_but_keep_applied_results(context, already_applied):
    db, user, _, _, _, spec = setup_case(context)
    plan = repair.prepare_legacy_repair(db, user.id, [spec]); db.commit()
    plan.schema_version = 2
    plan.manifest_json = {**plan.manifest_json, 'version': 2}
    plan.preview_json = {k: v for k, v in plan.preview_json.items() if k != 'projection'}
    plan.plan_hash = _key({'manifest': plan.manifest_json, 'base_fingerprint': plan.base_fingerprint,
                          'preview': plan.preview_json})
    old_result = deepcopy(plan.preview_json)
    if already_applied:
        plan.state, plan.result_json = 'applied', old_result
    db.commit()
    before = repair._state(db, user.id)
    if already_applied:
        assert apply(db, user, plan) == old_result
    else:
        with pytest.raises(RepairConflict, match='older format'):
            apply(db, user, plan)
    assert repair._state(db, user.id) == before
