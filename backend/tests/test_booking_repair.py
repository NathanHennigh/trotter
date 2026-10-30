from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import Base, BookingObservation, BookingRepairManifest, Message, MessageStatus, Segment, Trip, User
from app.services.booking_import import booking_time_provenance
from app.services.booking_ledger import record_cancellation, record_user_decision
from app.services.booking_repair import RepairConflict, apply_repair, prepare_repair
from app.services.builder import build_segments_and_trips_detailed
from app.services.parser import ParsedFlight


def dt(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


@pytest.fixture
def ctx():
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        owner = User(email='alex@example.invalid', name='Alex Morgan', travel_name_aliases=['Alex Blake'],
                     travel_names_confirmed_at=dt('2026-10-01T00:00:00Z'))
        other = User(email='other@example.invalid', name='Other Person')
        db.add_all([owner, other]); db.commit()
        yield SimpleNamespace(db=db, owner=owner, other=other)


def parsed(*, day='2026-03-23', name='Alex Blake', normalized=True):
    departure, arrival = f'{day}T11:00:00+00:00', f'{day}T13:25:00+00:00'
    flight = ParsedFlight(dep_airport='BNA', arr_airport='DFW', dep_time=dt(departure), arr_time=dt(arrival),
        airline='AA', flight_number='AA2787', pnr='BOOK01', source='receipt', ownership='self' if name else 'unknown',
        passenger_names=[name] if name else [], passenger_evidence=[{'name': name, 'role': 'traveler',
            'complete': True, 'applies': True, 'scope_ambiguous': False}] if name else [])
    flight.force_review = False
    if normalized:
        flight.time_provenance = {'version': 1, 'status': 'normalized', 'departure_local_date': day,
            'departure': {'basis': 'airport_local', 'airport': 'BNA', 'timezone': 'America/Chicago', 'local': f'{day}T06:00:00', 'utc': departure},
            'arrival': {'basis': 'airport_local', 'airport': 'DFW', 'timezone': 'America/Chicago', 'local': f'{day}T08:25:00', 'utc': arrival}}
    return flight


def payload(ctx, flight=None, *, message_id='m1', received='2026-03-01T10:00:00Z', user=None):
    user = user or ctx.owner
    row = Message(user_id=user.id, provider_msg_id=message_id, subject='Your flight receipt')
    ctx.db.add(row); ctx.db.commit()
    return {'full_msg': {'id': message_id, 'payload': 'synthetic source evidence'}, 'msg_id': message_id,
        'subject': row.subject, 'plain_text': 'Passenger Alex Blake', 'html': '', 'internal_ts': dt(received),
        'received_at': dt(received), 'document_provenance': [],
        'parse_result': SimpleNamespace(flights=[flight or parsed()])}


def apply(ctx, plan):
    result = apply_repair(ctx.db, ctx.owner.id, plan.id, expected_plan_hash=plan.plan_hash)
    ctx.db.commit()
    return result


def test_preview_is_persisted_without_projecting_then_exact_plan_is_idempotent(ctx):
    source = payload(ctx)
    plan = prepare_repair(ctx.db, ctx.owner.id, [source]); ctx.db.commit()
    assert plan.state == 'previewed' and len(plan.preview_json['added']) == 1
    assert ctx.db.query(Segment).count() == ctx.db.query(BookingObservation).count() == 0
    assert 'plain_text' not in str(plan.manifest_json) and 'synthetic source evidence' not in str(plan.manifest_json)
    first = apply(ctx, plan)
    ids = [row.id for row in ctx.db.query(Segment)]
    assert first['flights_after'] == 1
    assert apply(ctx, plan) == first
    assert [row.id for row in ctx.db.query(Segment)] == ids


def test_time_correction_preserves_existing_segment_and_original_observation_ids(ctx):
    old = parsed(normalized=False)
    old.dep_time, old.arr_time = dt('2026-03-23T06:00:00Z'), dt('2026-03-23T08:25:00Z')
    old.source_received_at = dt('2026-03-01T10:00:00Z')
    build_segments_and_trips_detailed(ctx.db, ctx.owner.id, [old], source_message_id='m1')
    ctx.db.commit()
    existing = ctx.db.query(Segment).one(); segment_id = existing.id
    observations = {row.id: deepcopy(row.facts) for row in ctx.db.query(BookingObservation)}
    source = payload(ctx)
    plan = prepare_repair(ctx.db, ctx.owner.id, [source]); ctx.db.commit()
    assert not plan.preview_json['added'] and plan.preview_json['updated'][0]['segment_id'] == segment_id
    apply(ctx, plan)
    row = ctx.db.query(Segment).one()
    assert row.id == segment_id and row.dep_time.hour == 11 and row.arr_time.hour == 13
    assert all(ctx.db.get(BookingObservation, key).facts == facts for key, facts in observations.items())


def test_schedule_date_link_uses_one_latest_flight_and_retains_named_evidence(ctx):
    left = payload(ctx, parsed(), message_id='old')
    right = payload(ctx, parsed(day='2026-03-24', name=None), message_id='new', received='2026-03-24T07:00:00Z')
    ids = {row.provider_msg_id: row.id for row in ctx.db.query(Message)}
    link = {'from': {'message_id': ids['old'], 'flight_number': 'AA2787', 'departure_local_date': '2026-03-23'},
            'to': {'message_id': ids['new'], 'flight_number': 'AA2787', 'departure_local_date': '2026-03-24'}}
    plan = prepare_repair(ctx.db, ctx.owner.id, [left, right], schedule_links=[link]); ctx.db.commit()
    assert len(plan.preview_json['added']) == 1
    apply(ctx, plan)
    row = ctx.db.query(Segment).one()
    assert row.dep_time.date().isoformat() == '2026-03-24'
    assert row.meta_json['reconciles_observation_ids']
    assert ctx.db.query(BookingObservation).filter_by(source_message_id='old').one().ownership == 'self'


@pytest.mark.parametrize('decision', ['hold', 'canceled'])
def test_schedule_link_never_overrides_manual_hold_or_cancellation(ctx, decision):
    old = parsed()
    build_segments_and_trips_detailed(ctx.db, ctx.owner.id, [old], source_message_id='old')
    if decision == 'hold':
        record_user_decision(ctx.db, ctx.owner.id, old, status='hold')
    else:
        record_cancellation(ctx.db, ctx.owner.id, old.pnr, source_message_id='cancel',
                            source_event_at=dt('2026-03-02T12:00:00Z'), flights=[old])
    ctx.db.commit()
    left = payload(ctx, old, message_id='old')
    right = payload(ctx, parsed(day='2026-03-24', name=None), message_id='new', received='2026-03-24T07:00:00Z')
    ids = {row.provider_msg_id: row.id for row in ctx.db.query(Message)}
    link = {'from': {'message_id': ids['old'], 'flight_number': 'AA2787', 'departure_local_date': '2026-03-23'},
            'to': {'message_id': ids['new'], 'flight_number': 'AA2787', 'departure_local_date': '2026-03-24'}}
    with pytest.raises(RepairConflict, match='canceled|held'):
        prepare_repair(ctx.db, ctx.owner.id, [left, right], schedule_links=[link])
    assert ctx.db.query(Segment).count() == 1
    assert ctx.db.query(BookingRepairManifest).count() == 0


def test_stale_or_tampered_manifest_fails_before_account_changes(ctx):
    plan = prepare_repair(ctx.db, ctx.owner.id, [payload(ctx)]); ctx.db.commit()
    digest = plan.plan_hash
    plan.manifest_json = {**plan.manifest_json, 'schedule_links': [{'bad': 'edit'}]}; ctx.db.commit()
    with pytest.raises(RepairConflict, match='checksum'):
        apply_repair(ctx.db, ctx.owner.id, plan.id, expected_plan_hash=digest)
    assert ctx.db.query(Segment).count() == 0


def test_changed_account_and_foreign_account_sources_are_rejected(ctx):
    foreign = payload(ctx, message_id='foreign', user=ctx.other)
    with pytest.raises(RepairConflict, match='owned'):
        prepare_repair(ctx.db, ctx.owner.id, [foreign])
    plan = prepare_repair(ctx.db, ctx.owner.id, [payload(ctx)]); ctx.db.commit()
    ctx.owner.travel_name_aliases = ['Changed Name']; ctx.db.commit()
    with pytest.raises(RepairConflict, match='changed'):
        apply(ctx, plan)
    with pytest.raises(RepairConflict, match='not found'):
        apply_repair(ctx.db, ctx.other.id, plan.id, expected_plan_hash=plan.plan_hash)
    assert ctx.db.query(Segment).count() == 0


def test_interrupted_apply_rolls_back_every_projection_and_remains_retryable(ctx, monkeypatch):
    from app.services import booking_repair
    plan = prepare_repair(ctx.db, ctx.owner.id, [payload(ctx)]); ctx.db.commit()
    real = booking_repair.build_segments_and_trips_detailed
    def interrupted(*args, **kwargs):
        real(*args, **kwargs)
        raise RuntimeError('simulated interruption')
    monkeypatch.setattr(booking_repair, 'build_segments_and_trips_detailed', interrupted)
    with pytest.raises(RuntimeError):
        apply(ctx, plan)
    assert ctx.db.query(Segment).count() == ctx.db.query(BookingObservation).count() == 0
    assert ctx.db.get(BookingRepairManifest, plan.id).state == 'previewed'
    monkeypatch.setattr(booking_repair, 'build_segments_and_trips_detailed', real)
    assert apply(ctx, plan)['flights_after'] == 1


def test_forwarded_unknown_timezone_is_interval_not_new_received_time():
    result = booking_time_provenance('2026-03-10T16:57:36Z', 'Fwd: Your flight receipt',
        '---------- Forwarded message ---------\nDate: Sun, Mar 8, 2026, 8:18 PM\nSubject: Your receipt')
    assert result['kind'] == 'forwarded_timezone_unknown'
    assert result['event_at'] is None
    assert result['earliest'].startswith('2026-03-08T06:18')
    assert result['latest'].startswith('2026-03-09T08:18')


def test_forwarded_missing_year_never_invents_chronology():
    result = booking_time_provenance('2026-03-10T16:57:36Z', 'Fwd: Receipt',
        '---------- Forwarded message ---------\nDate: Mar 8, 8:18 PM\nSubject: Receipt')
    assert result['kind'] == 'forwarded_unknown'
    assert result['event_at'] is None and 'earliest' not in result


def test_apply_rejects_pending_unrelated_session_writes(ctx):
    plan = prepare_repair(ctx.db, ctx.owner.id, [payload(ctx)]); ctx.db.commit()
    owner_id, plan_id, digest = ctx.owner.id, plan.id, plan.plan_hash
    ctx.other.name = 'Unrelated pending profile edit'
    with pytest.raises(RepairConflict, match='clean dedicated session'):
        apply_repair(ctx.db, owner_id, plan_id, expected_plan_hash=digest)
    ctx.db.rollback()
    assert ctx.db.query(Segment).count() == 0
    assert ctx.other.name == 'Other Person'


@pytest.mark.parametrize('named_placeholder', [False, True])
def test_pdf_resolves_only_unnamed_same_message_body_placeholder(ctx, named_placeholder):
    complete = parsed(); complete.document_provenance = {'sha256': 'a' * 64, 'pages': [1]}
    placeholder = parsed(name='Other Passenger' if named_placeholder else None)
    placeholder.pnr = None; placeholder.flight_number = None; placeholder.ownership = 'unknown'
    source = payload(ctx, complete)
    source['parse_result'].flights.insert(0, placeholder)
    row = ctx.db.query(Message).one(); row.status = MessageStatus.REVIEW_REQUIRED
    row.parse_error = 'passenger_identity_unresolved'; ctx.db.commit()
    plan = prepare_repair(ctx.db, ctx.owner.id, [source]); ctx.db.commit()
    assert len(plan.preview_json['added']) == 1
    assert bool(plan.preview_json['held']) is named_placeholder
    apply(ctx, plan)
    ctx.db.refresh(row)
    assert row.status == (MessageStatus.REVIEW_REQUIRED if named_placeholder else MessageStatus.ACCEPTED)
    assert ctx.db.query(BookingObservation).filter_by(source_message_id='m1').count() == 2


def test_malformed_recovery_link_cannot_update_another_booking(ctx):
    other_booking = parsed(); other_booking.pnr = 'OTHER1'
    build_segments_and_trips_detailed(ctx.db, ctx.owner.id, [other_booking], source_message_id='other-booking')
    ctx.db.commit()
    original = ctx.db.query(Segment).one(); before = (original.id, original.pnr, original.dep_time)
    incoming = parsed(); incoming.recovery_observation_ids = [ctx.db.query(BookingObservation).one().id]
    with pytest.raises(ValueError, match='Recovery correction'):
        build_segments_and_trips_detailed(ctx.db, ctx.owner.id, [incoming], source_message_id='malformed')
    ctx.db.rollback()
    assert (original.id, original.pnr, original.dep_time) == before
