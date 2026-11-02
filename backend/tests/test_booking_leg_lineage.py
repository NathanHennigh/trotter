from copy import deepcopy
from datetime import datetime, timezone
from datetime import timedelta
from hashlib import sha256

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import Base, BookingObservation, Segment, Trip, User, ItineraryHistory
from app.services.booking_ledger import record_user_decision, record_cancellation
from app.services.builder import build_segments_and_trips_detailed
from app.services.parser import ParsedFlight


def stamp(value):
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)


@pytest.fixture
def context(monkeypatch):
    monkeypatch.setenv('BOOKING_LEG_RECONCILIATION_ENABLED', 'true')
    monkeypatch.setenv('FLIGHT_IMPORT_RECOVERY_USER_IDS', '*')
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = User(email='owner@example.invalid', name='Alex Morgan')
        other = User(email='other@example.invalid', name='Other Person')
        db.add_all([user, other]); db.commit()
        yield db, user, other


def flight(*, revision=29, day='2026-03-10', arrival='TPE', number='BR51', pointer='original block'):
    value = ParsedFlight(dep_airport='IAH', arr_airport=arrival,
        dep_time=stamp(day + 'T06:00:00'), arr_time=stamp(day + 'T20:00:00'),
        pnr='BOOK01', airline='BR', flight_number=number, source='shape_numbered_flight_cards',
        ownership='self', passenger_names=['Alex Morgan'],
        passenger_evidence=[{'name': 'Alex Morgan', 'role': 'traveler', 'applies': True,
                             'complete': True, 'scope_ambiguous': False}])
    value.parser_version = revision
    value.source_leg = {'version': 1, 'key': sha256(pointer.encode()).hexdigest(), 'sequence': 1}
    value.source_received_at = stamp('2026-01-02T12:00:00')
    value.time_provenance = {'status': 'normalized', 'version': 1, 'departure_local_date': day,
        'departure': {'basis': 'airport_local', 'local': day + 'T00:00:00', 'utc': value.dep_time.isoformat()},
        'arrival': {'basis': 'airport_local', 'local': day + 'T04:00:00', 'utc': value.arr_time.isoformat()}}
    return value


def ingest(db, user, value, source='original'):
    result = build_segments_and_trips_detailed(db, user.id, [value],
        source_message_id=source, source_event_at=value.source_received_at)
    db.flush()
    return result


def fields(row):
    return row.id, row.dep_airport, row.arr_airport, row.dep_time, row.arr_time, row.flight_number, row.pnr


@pytest.mark.parametrize('change', ['date', 'airport', 'number', 'date_and_airport'])
def test_same_document_higher_revision_corrects_existing_leg_without_new_id(context, change):
    db, user, _ = context
    old = flight()
    ingest(db, user, old); db.commit()
    before = fields(db.query(Segment).one())
    original_facts = deepcopy(db.query(BookingObservation).one().facts)
    new = flight(revision=30,
        day='2026-03-15' if 'date' in change else '2026-03-10',
        arrival='MNL' if 'airport' in change else 'TPE',
        number='BR53' if change == 'number' else 'BR51')
    result = ingest(db, user, new)
    row = db.query(Segment).one()
    assert result.updated == 1 and row.id == before[0]
    assert row.arr_airport == new.arr_airport and row.dep_time.date() == new.dep_time.date()
    assert row.flight_number == new.flight_number
    assert db.query(BookingObservation).order_by(BookingObservation.id).first().facts == original_facts
    assert any(h.snapshot['id'] == row.id for h in db.query(ItineraryHistory).filter_by(entity_type='segment'))
    wanted = fields(row)
    ingest(db, user, old)
    assert fields(db.query(Segment).one()) == wanted
    ingest(db, user, new)
    assert fields(db.query(Segment).one()) == wanted


@pytest.mark.parametrize('case', ['same_revision_conflict', 'different_booking', 'different_source',
    'different_block', 'ambiguous_block', 'missing_pointer', 'manual', 'hold', 'canceled', 'later_schedule'])
def test_correction_requires_unique_proven_lineage_and_respects_protections(context, case):
    db, user, _ = context
    old = flight()
    if case == 'missing_pointer':
        old.source_leg = {}
    ingest(db, user, old); db.commit()
    row = db.query(Segment).one()
    if case == 'manual':
        row.meta_json = {**row.meta_json, 'source': 'manual'}
    if case in {'hold', 'canceled'}:
        record_user_decision(db, user.id, old, status=case)
    if case == 'later_schedule':
        row.meta_json = {**row.meta_json, 'source_received_at': '2026-01-03T12:00:00'}
    db.commit()
    before = fields(row)
    new = flight(revision=29 if case == 'same_revision_conflict' else 30, day='2026-03-15')
    source = 'original'
    if case == 'different_booking':
        new.pnr = 'OTHER1'
    if case == 'different_source':
        source = 'another-message'
    if case == 'different_block':
        new.source_leg['key'] = 'b' * 64
    if case == 'ambiguous_block':
        new.source_leg['ambiguous'] = True
    ingest(db, user, new, source)
    assert fields(db.get(Segment, before[0])) == before
    if case == 'missing_pointer':
        assert db.query(Segment).count() == 1


def test_lineage_never_crosses_account_boundary(context):
    db, user, other = context
    ingest(db, user, flight())
    before = fields(db.query(Segment).one())
    incoming = flight(revision=30, day='2026-03-15')
    incoming.passenger_names = ['Other Person']
    incoming.passenger_evidence[0]['name'] = 'Other Person'
    ingest(db, other, incoming)
    assert fields(db.get(Segment, before[0])) == before


def test_two_existing_linked_segments_fail_closed(context):
    db, user, _ = context
    ingest(db, user, flight())
    row = db.query(Segment).one()
    before = fields(row)
    duplicate = Segment(trip_id=row.trip_id, mode='flight', dep_airport=row.dep_airport,
        arr_airport=row.arr_airport, dep_time=row.dep_time, arr_time=row.arr_time,
        airline=row.airline, flight_number=row.flight_number, pnr=row.pnr, meta_json=deepcopy(row.meta_json))
    db.add(duplicate); db.commit()
    result = ingest(db, user, flight(revision=30, day='2026-03-15'))
    assert result.held == 1
    assert fields(db.get(Segment, before[0])) == before
    assert db.query(Segment).count() == 2


def test_feature_disabled_cannot_correct_changed_day(context, monkeypatch):
    db, user, _ = context
    ingest(db, user, flight()); db.commit()
    row = db.query(Segment).one(); before = fields(row)
    monkeypatch.setenv('BOOKING_LEG_RECONCILIATION_ENABLED', 'false')
    ingest(db, user, flight(revision=30, day='2026-03-15'))
    assert fields(db.get(Segment, before[0])) == before


def test_ambiguous_pointer_does_not_block_a_new_explicit_leg(context):
    db, user, _ = context
    incoming = flight()
    incoming.source_leg['ambiguous'] = True
    assert ingest(db, user, incoming).inserted == 1
    assert db.query(Segment).count() == 1
    assert ingest(db, user, incoming).held == 0
    assert db.query(Segment).count() == 1
    changed = flight(revision=30, day='2026-03-15')
    changed.source_leg['ambiguous'] = True
    assert ingest(db, user, changed).held == 1
    assert db.query(Segment).one().dep_time.day == 10


def test_new_unambiguous_pointer_cannot_claim_an_old_ambiguous_block(context):
    db, user, _ = context
    old = flight()
    old.source_leg['ambiguous'] = True
    assert ingest(db, user, old).inserted == 1
    assert ingest(db, user, flight(revision=30, day='2026-03-15')).held == 1
    assert db.query(Segment).count() == 1
    assert db.query(Segment).one().dep_time.day == 10


@pytest.mark.parametrize('legacy', ['copied_heading', 'other_booking', 'normalized', 'held_predecessor'])
@pytest.mark.parametrize('correction_enabled', ['true', 'false', 'unlisted'])
def test_proven_overnight_connection_does_not_duplicate_a_legacy_heading_date(context, monkeypatch, legacy, correction_enabled):
    db, user, _ = context
    monkeypatch.setenv('BOOKING_LEG_RECONCILIATION_ENABLED', 'true' if correction_enabled == 'unlisted' else correction_enabled)
    if correction_enabled == 'unlisted':
        monkeypatch.setenv('FLIGHT_IMPORT_RECOVERY_USER_IDS', str(user.id + 100))
    prior = flight(pointer='preceding block')
    incoming = flight(day='2026-03-11', arrival='MNL', number='BR277', pointer='connection block')
    incoming.dep_airport = 'TPE'
    incoming.time_provenance['date_evidence'] = {'status': 'verified', 'kind': 'printed_elapsed',
        'departure_evidence': {'kind': 'printed_connection', 'status': 'verified',
                              'previous_leg_key': prior.source_leg['key']}}
    if legacy == 'held_predecessor':
        incoming.time_provenance['date_evidence']['departure_evidence']['previous_departure_date'] = '2026-03-10'
        prior.force_review = True
        prior.time_provenance['status'] = 'needs_review'
        prior.source_leg['key'] = 'c' * 64
    trip = Trip(user_id=user.id)
    db.add(trip); db.flush()
    old = Segment(trip_id=trip.id, mode='flight', dep_airport='TPE', arr_airport='MNL',
        dep_time=stamp('2026-03-10T06:00:00'), arr_time=stamp('2026-03-10T08:00:00'),
        airline='BR', flight_number='BR277', pnr='OTHER1' if legacy == 'other_booking' else 'BOOK01',
        meta_json={'source': 'v5', **({'time_provenance': {'status': 'normalized'}} if legacy == 'normalized' else {})})
    db.add(old); db.commit()
    result = build_segments_and_trips_detailed(db, user.id, [prior, incoming],
        source_message_id='original', source_event_at=prior.source_received_at)
    assert result.held == (2 if legacy == 'held_predecessor' else 1 if legacy == 'copied_heading' else 0)
    assert db.get(Segment, old.id).dep_time.day == 10
    assert db.query(Segment).count() == (1 if legacy == 'held_predecessor' else 2 if legacy == 'copied_heading' else 3)


def test_malformed_revision_cannot_update_even_the_same_day(context):
    db, user, _ = context
    ingest(db, user, flight()); db.commit()
    old = fields(db.query(Segment).one())
    changed = flight(revision='30')
    changed.dep_time += timedelta(hours=1)
    changed.arr_time += timedelta(hours=1)
    assert ingest(db, user, changed).held == 1
    assert fields(db.query(Segment).one()) == old
