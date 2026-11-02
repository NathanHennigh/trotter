"""Exact original-link trip reuse preserves ordinary import protections."""
from copy import deepcopy
from datetime import timedelta

import pytest
from test_carrier_travel_recovery import account, run_case, target, process, source
from app.models import Segment, User
from app.services import carrier_travel_recovery as recovery
from app.services.booking_ledger import record_flight_observations, record_cancellation, record_user_decision
from app.services.builder import build_segments_and_trips_detailed


def promoted(db, user):
    _, flight = target(db)
    decision = record_flight_observations(db, user.id, [flight],
        source_message_id=flight.source_message_id, source_event_at=flight.source_received_at)
    assert len(decision.flights) == 1
    return decision.flights[0]


@pytest.mark.parametrize('alteration', ['generic', 'wrong_source', 'wrong_observation', 'wrong_pnr',
    'wrong_route', 'wrong_number', 'wrong_day', 'other_user', 'flag_off', 'two_flights'])
def test_trip_reuse_never_crosses_exact_original_boundary(account, monkeypatch, alteration):
    db, user = account
    run_case(db, user, 'sun-explicit-post-travel')
    flight = promoted(db, user)
    assert recovery.existing_projection_trip(db, user.id, [flight]).id == db.query(Segment).one().trip_id
    user_id = user.id
    flights = [flight]
    if alteration == 'generic': flight.passenger_evidence = []
    elif alteration == 'wrong_source': flight.source_message_id = 'unlinked-source'
    elif alteration == 'wrong_observation': flight.observation_id += 10000
    elif alteration == 'wrong_pnr': flight.pnr = 'ABC123'
    elif alteration == 'wrong_route': flight.arr_airport = 'MIA'
    elif alteration == 'wrong_number': flight.flight_number = 'SY999'
    elif alteration == 'wrong_day':
        flight.time_provenance = None
        flight.dep_time += timedelta(days=1)
        flight.arr_time += timedelta(days=1)
    elif alteration == 'other_user':
        other = User(email='unrelated@example.test', name='Other Person')
        db.add(other); db.flush(); user_id = other.id
    elif alteration == 'flag_off': monkeypatch.setenv('CARRIER_TRAVEL_CORROBORATION_ENABLED', 'false')
    elif alteration == 'two_flights': flights.append(deepcopy(flight))
    assert recovery.existing_projection_trip(db, user_id, flights) is None


def test_newer_schedule_still_updates_existing_recovered_leg(account):
    db, user = account
    process(db, user, source('sun-update-1'))
    process(db, user, source('sun-survey'))
    before = db.query(Segment).one()
    old_id, old_trip, old_departure = before.id, before.trip_id, before.dep_time
    process(db, user, source('sun-update-3'))
    after = db.query(Segment).one()
    assert after.id == old_id and after.trip_id == old_trip
    assert after.dep_time - old_departure == timedelta(hours=2)
    assert after.dep_time.hour == 17


@pytest.mark.parametrize('protection', ['canceled', 'manual_hold'])
def test_trip_reuse_cannot_bypass_normal_ledger_hold(account, monkeypatch, protection):
    db, user = account
    run_case(db, user, 'sun-explicit-post-travel')
    _, flight = target(db)
    if protection == 'canceled':
        record_cancellation(db, user.id, flight.pnr, source_message_id='cancel-after-recovery',
            source_event_at=flight.source_received_at + timedelta(days=1), flights=[flight])
    else:
        record_user_decision(db, user.id, flight, ownership='unknown', status='hold')
    monkeypatch.setattr(recovery, 'existing_projection_trip', lambda *a: pytest.fail('Protected leg reached trip reuse'))
    result = build_segments_and_trips_detailed(db, user.id, [flight],
        source_message_id=flight.source_message_id, source_event_at=flight.source_received_at)
    assert result.held == 1 and result.inserted == result.updated == 0
