from copy import deepcopy
from datetime import timedelta

import pytest

from app.models import BookingObservation, BookingRepairManifest, ItineraryHistory, Segment, Trip
from app.services.booking_ledger import record_flight_observations, record_user_decision
from app.services.booking_legacy_repair import prepare_legacy_repair, apply_legacy_repair
from app.services.booking_repair import RepairConflict
from test_booking_leg_lineage import context, flight, ingest, fields


def setup_case(context):
    db, user, other = context
    old = flight(day='2026-03-10')
    old.source_leg = {}
    ingest(db, user, old)
    legacy = db.query(Segment).one()
    legacy.meta_json = {'source': 'v5', 'source_received_at': '2026-01-02T12:00:00'}
    new = flight(day='2026-03-15', revision=30)
    record_flight_observations(db, user.id, [new], source_message_id='original', source_event_at=new.source_received_at)
    db.commit()
    evidence = db.query(BookingObservation).order_by(BookingObservation.id.desc()).first()
    spec = {'segment_id': legacy.id, 'target_observation_id': evidence.id,
            'reason': 'Original itinerary explicitly prints a separate return date; reviewed old heading-date error.'}
    return db, user, other, legacy, evidence, spec


def apply(db, user, plan):
    return apply_legacy_repair(db, user.id, plan.id, expected_plan_hash=plan.plan_hash)


def test_reviewed_correction_preserves_id_original_evidence_and_retries(context):
    db, user, _, legacy, evidence, spec = setup_case(context)
    before = fields(legacy)
    originals = {r.id: deepcopy(r.facts) for r in db.query(BookingObservation)}
    plan = prepare_legacy_repair(db, user.id, [spec]); db.commit()
    assert fields(db.get(Segment, before[0])) == before
    assert plan.preview_json['updated'][0]['segment_id'] == before[0]
    result = apply(db, user, plan)
    corrected = db.query(Segment).one()
    assert corrected.id == before[0] and corrected.dep_time.day == 15
    assert apply(db, user, plan) == result
    assert {r.id: r.facts for r in db.query(BookingObservation)} == originals


def test_reviewed_supersession_retains_successor_and_full_original_snapshot(context):
    db, user, _, legacy, evidence, spec = setup_case(context)
    successor = Segment(trip_id=legacy.trip_id, mode='flight', dep_airport='IAH', arr_airport='TPE',
        dep_time=flight(day='2026-03-15').dep_time, arr_time=flight(day='2026-03-15').arr_time,
        airline='BR', flight_number='BR51', pnr='BOOK01', meta_json={'source': 'receipt'})
    db.add(successor); db.commit()
    old_id, keep_id = legacy.id, successor.id
    spec.update(segment_id=keep_id, superseded_segment_ids=[old_id])
    plan = prepare_legacy_repair(db, user.id, [spec]); db.commit()
    assert db.query(Segment).count() == 2
    result = apply(db, user, plan)
    assert result['retired_segment_ids'] == [old_id]
    assert db.query(Segment).one().id == keep_id
    snapshots = db.query(ItineraryHistory).filter_by(entity_id=old_id).all()
    assert any(r.entity_type == 'segment' and r.snapshot['dep_time'].startswith('2026-03-10') for r in snapshots)
    assert any(r.entity_type == 'segment_link' and r.snapshot['successor_segment_id'] == keep_id for r in snapshots)


@pytest.mark.parametrize('case', ['other_account', 'other_booking', 'other_origin', 'other_number', 'unknown_passenger',
    'missing_pointer', 'manual', 'hold', 'canceled', 'no_reason', 'same_role_twice'])
def test_unsafe_legacy_repairs_fail_without_changes(context, case):
    db, user, other, legacy, evidence, spec = setup_case(context)
    if case == 'other_account':
        evidence.user_id = other.id
    elif case == 'other_booking':
        legacy.pnr = 'OTHER1'
    elif case == 'other_origin':
        legacy.dep_airport = 'DFW'
    elif case == 'other_number':
        legacy.flight_number = 'BR53'
    elif case == 'unknown_passenger':
        evidence.facts = {**evidence.facts, 'passenger_evidence': []}
    elif case == 'missing_pointer':
        evidence.facts = {**evidence.facts, 'source_leg': {}}
    elif case == 'manual':
        legacy.meta_json = {**legacy.meta_json, 'source': 'manual'}
    elif case in {'hold', 'canceled'}:
        record_user_decision(db, user.id, flight(), status=case)
    elif case == 'no_reason':
        spec['reason'] = ''
    elif case == 'same_role_twice':
        spec['superseded_segment_ids'] = [legacy.id]
    db.commit()
    before = fields(legacy)
    with pytest.raises(RepairConflict):
        prepare_legacy_repair(db, user.id, [spec])
    assert fields(db.get(Segment, before[0])) == before
    assert db.query(BookingRepairManifest).count() == 0


def test_stale_manifest_rejected(context):
    db, user, _, legacy, _, spec = setup_case(context)
    plan = prepare_legacy_repair(db, user.id, [spec]); db.commit()
    legacy.arr_airport = 'MNL'; db.commit()
    with pytest.raises(RepairConflict, match='changed since preview'):
        apply(db, user, plan)


def test_interruption_is_atomic_and_retryable(context, monkeypatch):
    from app.services import booking_legacy_repair as module
    db, user, _, legacy, _, spec = setup_case(context)
    before = fields(legacy)
    plan = prepare_legacy_repair(db, user.id, [spec]); db.commit()
    real = module.rebuild_affected_trips
    def interrupt(*args):
        real(*args)
        raise RuntimeError('test interruption')
    monkeypatch.setattr(module, 'rebuild_affected_trips', interrupt)
    with pytest.raises(RuntimeError, match='test interruption'):
        apply(db, user, plan)
    assert fields(db.get(Segment, before[0])) == before
    assert db.get(BookingRepairManifest, plan.id).state == 'previewed'
    monkeypatch.setattr(module, 'rebuild_affected_trips', real)
    assert apply(db, user, plan)['flights_after'] == 1


def with_later_unnamed_schedule(context):
    db, user, other, legacy, named, spec = setup_case(context)
    newer = flight(day='2026-03-15', revision=30)
    newer.ownership, newer.passenger_names, newer.passenger_evidence = 'unknown', [], []
    newer.source_received_at += timedelta(days=1)
    newer.dep_time += timedelta(hours=1)
    newer.arr_time += timedelta(hours=1)
    record_flight_observations(db, user.id, [newer], source_message_id='later-schedule', source_event_at=newer.source_received_at)
    db.commit()
    latest = db.query(BookingObservation).order_by(BookingObservation.id.desc()).first()
    spec.update(target_observation_id=latest.id, passenger_proof_observation_ids=[named.id])
    return db, user, other, legacy, named, latest, spec


def test_latest_unnamed_schedule_uses_explicit_same_leg_named_proof(context):
    db, user, _, legacy, named, latest, spec = with_later_unnamed_schedule(context)
    originals = {r.id: deepcopy(r.facts) for r in db.query(BookingObservation)}
    plan = prepare_legacy_repair(db, user.id, [spec]); db.commit()
    result = apply(db, user, plan)
    assert db.get(Segment, legacy.id).dep_time.hour == 7
    assert result['corrections'][0]['passenger_proof_observation_ids'] == [named.id]
    assert db.get(BookingObservation, latest.id).ownership == 'unknown'
    assert {r.id: r.facts for r in db.query(BookingObservation)} == originals


@pytest.mark.parametrize('case', ['wrong_account', 'wrong_day', 'wrong_booking', 'wrong_passenger', 'missing_proof', 'newer_conflict'])
def test_unnamed_schedule_cannot_borrow_unrelated_passenger_proof(context, case):
    db, user, other, legacy, named, latest, spec = with_later_unnamed_schedule(context)
    if case == 'wrong_account': named.user_id = other.id
    elif case == 'wrong_day': named.travel_date = '2026-03-12'; named.facts = {**named.facts, 'time_provenance': {}}
    elif case == 'wrong_booking': named.pnr = 'OTHER1'
    elif case == 'wrong_passenger': named.ownership = 'other'
    elif case == 'missing_proof': spec['passenger_proof_observation_ids'] = []
    elif case == 'newer_conflict': legacy.meta_json = {**legacy.meta_json, 'source_received_at': '2026-01-04T12:00:00'}
    db.commit()
    before = fields(legacy)
    with pytest.raises(RepairConflict): prepare_legacy_repair(db, user.id, [spec])
    assert fields(db.get(Segment, before[0])) == before


def test_reviewed_wall_clock_normalization_installs_proof_while_retaining_later_source_time(context):
    from app.services.booking_ledger import event_time
    db, user, _, legacy, evidence, spec = setup_case(context)
    proof = evidence.facts['time_provenance']
    legacy.dep_time = event_time(proof['departure']['local'])
    legacy.arr_time = event_time(proof['arrival']['local'])
    legacy.meta_json = {**legacy.meta_json, 'source_received_at': '2026-01-04T12:00:00'}
    db.commit()
    plan = prepare_legacy_repair(db, user.id, [spec]); db.commit()
    apply(db, user, plan)
    row = db.get(Segment, legacy.id)
    assert row.meta_json['source_received_at'] == '2026-01-04T12:00:00'
    assert row.meta_json['time_provenance'] == proof
    assert row.meta_json['clock_observation_id'] == evidence.id
    assert row.dep_time == event_time(evidence.facts['dep_time'])
