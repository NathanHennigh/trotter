"""Corroborating receipts retain date proof without rewriting their evidence."""
from copy import deepcopy
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import Base, BookingObservation, Segment, User
from app.services.booking_import import apply_booking_message
from app.services.builder import _merge_flight_provenance
from app.services.flight_times import normalize_flight_times, resolve_printed_elapsed_arrival
from app.services.parser import ParsedFlight, ParseResult


def flight(*, proof=True, minutes=141, arrival_hour=22, arrival_minute=46):
    value = ParsedFlight('BNA', 'IAH', datetime(2024, 12, 1, 20, 25, tzinfo=timezone.utc),
        datetime(2024, 12, 1, arrival_hour, arrival_minute, tzinfo=timezone.utc),
        airline='UA', flight_number='UA2311', pnr='BOOK01', source='named_receipt',
        ownership='self', passenger_names=['Alex Avery'])
    if proof:
        resolve_printed_elapsed_arrival(value, minutes=minutes)
    normalize_flight_times(value)
    return value


def test_same_normalized_clocks_preserve_proof_without_mutating_incoming_fact():
    previous = flight().time_provenance
    incoming = flight(proof=False)
    original = deepcopy(incoming.time_provenance)
    meta = {'time_provenance': deepcopy(previous)}
    for _ in range(2):
        _merge_flight_provenance(meta, incoming, incoming_is_current=True)
        assert meta['time_provenance'] == previous
        assert incoming.time_provenance == original
    meta['time_provenance']['date_evidence']['minutes'] = 1
    assert previous['date_evidence']['minutes'] == 141


@pytest.mark.parametrize('endpoint,key,value', [
    ('departure', 'basis', 'absolute'), ('arrival', 'basis', 'absolute'),
    ('departure', 'airport', 'ATL'), ('arrival', 'airport', 'DFW'),
    ('departure', 'timezone', 'America/New_York'), ('arrival', 'timezone', 'UTC'),
    ('departure', 'local', '2024-12-01T20:26:00'), ('arrival', 'local', '2024-12-01T22:47:00'),
    ('departure', 'utc', '2024-12-02T02:26:00+00:00'), ('arrival', 'utc', '2024-12-02T04:47:00+00:00'),
    ('arrival', 'original', '2024-12-01T22:47:00+00:00'),
])
def test_changed_endpoint_interpretation_never_inherits_date_proof(endpoint, key, value):
    previous = flight().time_provenance
    incoming = flight(proof=False)
    incoming.time_provenance[endpoint][key] = value
    meta = {'time_provenance': deepcopy(previous)}
    _merge_flight_provenance(meta, incoming, incoming_is_current=True)
    assert meta['time_provenance'] == incoming.time_provenance
    assert 'date_evidence' not in meta['time_provenance']


@pytest.mark.parametrize('change', ['local_date', 'status', 'version', 'missing_endpoint',
                                  'missing_clock', 'unverified', 'other_proof_kind', 'malformed_old'])
def test_incomplete_or_unverified_provenance_is_not_carried_forward(change):
    previous = flight().time_provenance
    incoming = flight(proof=False)
    if change == 'local_date': incoming.time_provenance['departure_local_date'] = '2024-12-02'
    elif change == 'status': incoming.time_provenance['status'] = 'needs_review'
    elif change == 'version': incoming.time_provenance['version'] = 2
    elif change == 'missing_endpoint': incoming.time_provenance.pop('arrival')
    elif change == 'missing_clock': incoming.time_provenance['arrival'].pop('utc')
    elif change == 'unverified': previous['date_evidence']['status'] = 'needs_review'
    elif change == 'other_proof_kind': previous['date_evidence']['kind'] = 'flight_endpoint_scope'
    elif change == 'malformed_old': previous = []
    meta = {'time_provenance': previous}
    _merge_flight_provenance(meta, incoming, incoming_is_current=True)
    assert 'date_evidence' not in meta['time_provenance']


@pytest.mark.parametrize('new_proof', [None, {}, {'kind': 'printed_elapsed', 'minutes': 140,
                                                'status': 'needs_review'}])
def test_incoming_alternate_proof_always_wins(new_proof):
    incoming = flight(proof=False)
    incoming.time_provenance['date_evidence'] = new_proof
    meta = {'time_provenance': flight().time_provenance}
    _merge_flight_provenance(meta, incoming, incoming_is_current=True)
    assert meta['time_provenance']['date_evidence'] == new_proof


def test_later_same_clock_receipt_keeps_segment_proof_and_original_observations_on_repeat():
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = User(name='Alex Avery', email='alex@example.test')
        db.add(user); db.flush()
        messages = [('duration-receipt', flight(), '2024-11-01T12:00:00Z'),
                    ('airline-receipt', flight(proof=False), '2024-11-02T12:00:00Z')]
        for source, value, event in messages:
            apply_booking_message(db, user.id, ParseResult(flights=[deepcopy(value)]),
                source_message_id=source, subject='Flight confirmation', received_at=event)
        db.flush()
        saved = db.query(Segment).one()
        old_id, old_meta = saved.id, deepcopy(saved.meta_json)
        old_observations = [(row.id, deepcopy(row.facts)) for row in db.query(BookingObservation).order_by(BookingObservation.id)]
        assert saved.meta_json['time_provenance']['date_evidence']['minutes'] == 141
        assert 'date_evidence' not in old_observations[1][1]['time_provenance']
        for source, value, event in messages:
            apply_booking_message(db, user.id, ParseResult(flights=[deepcopy(value)]),
                source_message_id=source, subject='Flight confirmation', received_at=event)
        assert db.query(Segment).one().id == old_id
        assert saved.meta_json == old_meta
        assert [(row.id, row.facts) for row in db.query(BookingObservation).order_by(BookingObservation.id)] == old_observations


def test_real_schedule_change_drops_previous_date_proof():
    incoming = flight(proof=False, arrival_minute=56)
    meta = {'time_provenance': flight().time_provenance}
    _merge_flight_provenance(meta, incoming, incoming_is_current=True)
    assert 'date_evidence' not in meta['time_provenance']
    assert meta['time_provenance']['arrival']['local'].endswith('22:56:00')
