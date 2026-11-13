from copy import deepcopy
from datetime import datetime, timezone
from html import escape

import pytest

from app.services.frontier_itinerary import extract_frontier_connection_cards
from app.services.parser import parse_email


def receipt():
    return '''FRONTIER PURCHASE CONFIRMATION
Your flight confirmation code is:
TEST12
FLIGHTS
DEPARTING FLIGHT 901
 & 902
Dallas (DFW) to San Diego (SAN)
Depart: 5/17/2027 3:43 PM | Arrive: 5/17/2027 9:02 PM
Total Duration: 7 hr 19 min
1 Stop - Las Vegas (LAS)
DFW to LAS
Depart: 5/17/2027 3:43 PM | Arrive: 5/17/2027 4:49 PM
Layover: 3 hr 3 min
LAS to SAN
Depart: 5/17/2027 7:52 PM | Arrive: 5/17/2027 9:02 PM
PASSENGERS
ADULT(S)
1 - Alex Taylor
SERVICES
Terms and conditions Frontier Airlines
'''


def prepare(text, html=False, owner='Alex Taylor'):
    return parse_email(plain_text='' if html else text,
        html='<html><body>' + ''.join('<p>' + escape(line) + '</p>' for line in text.splitlines()) + '</body></html>' if html else '',
        attachments=[], user_name=owner, aliases=[], subject='Your flight confirmation',
        from_email='Frontier <notice@example.test>', received_at=datetime(2027, 4, 1, tzinfo=timezone.utc))


@pytest.mark.parametrize('html', [False, True])
def test_summary_is_two_explicit_numbered_legs_with_exact_utc_and_scope(html):
    result = prepare(receipt(), html)
    assert [(f.flight_number, f.dep_airport, f.arr_airport, f.dep_time.isoformat(), f.arr_time.isoformat()) for f in result.flights] == [
        ('F9901','DFW','LAS','2027-05-17T20:43:00+00:00','2027-05-17T23:49:00+00:00'),
        ('F9902','LAS','SAN','2027-05-18T02:52:00+00:00','2027-05-18T04:02:00+00:00')]
    assert all(f.ownership == 'self' and f.pnr == 'TEST12' and f.pnr_aliases == [] for f in result.flights)
    assert len({f.source_leg['key'] for f in result.flights}) == 2
    assert len({f.source_leg['document_card_key'] for f in result.flights}) == 1
    assert all(f.time_provenance['date_evidence']['printed_layover_minutes'] == 183 for f in result.flights)


@pytest.mark.parametrize('before,after', [
    (' & 902', ' &'), (' & 902', ' & 902 & 903'), (' & 902',' & 901'),
    (' & 902', ' & 0000'),
    ('LAS to SAN\nDepart: 5/17/2027 7:52 PM | Arrive: 5/17/2027 9:02 PM',''),
    ('5/17/2027 7:52 PM','5/17/2027 7:52'),
    ('5/17/2027 7:52 PM','5/18/2027 7:52 PM'),
    ('Layover: 3 hr 3 min','Layover: 3 hr 4 min'),
    ('Total Duration: 7 hr 19 min','Total Duration: 7 hr 18 min'),
    ('1 Stop - Las Vegas (LAS)','1 Stop - Denver (DEN)'),
    ('LAS to SAN','DEN to SAN'), ('DFW to LAS','DFW to DEN'),
    ('5/17/2027 4:49 PM','5/17/2027 4:49 AM'),
    ('5/17/2027 3:43 PM','2/30/2027 3:43 PM'),
    ('TEST12','TEST12-OTHER'),
    ('Layover: 3 hr 3 min','Layover: 3 hr 63 min'),
    ('Layover: 3 hr 3 min','Layover: 3 hr 3 min Layover: 3 hr 4 min'),
    ('Total Duration: 7 hr 19 min','Total Duration: 7 hr 19 min Total Duration: 7 hr 20 min'),
])
def test_incomplete_or_contradictory_connection_holds_without_summary_fallback(before, after):
    text = receipt().replace(before, after)
    assert extract_frontier_connection_cards(text) == []
    assert prepare(text).flights == []


def test_distinct_booking_fields_hold_instead_of_cross_booking_aliases():
    text = receipt() + '\nConfirmation code: OTHER1\n'
    assert extract_frontier_connection_cards(text) == []
    assert prepare(text).flights == []


@pytest.mark.parametrize('owner,ownership', [('Jamie Other','other'), ('Alex Taylor','self')])
def test_named_scope_remains_strict(owner, ownership):
    assert {f.ownership for f in prepare(receipt(), owner=owner).flights} == {ownership}


def test_unrecognized_single_flight_keeps_existing_parser():
    text = receipt().split('DEPARTING FLIGHT')[0] + '''DEPARTING FLIGHT 903
Philadelphia (PHL) to Nashville (BNA)
Depart: 5/17/2027 3:34 PM | Arrive: 5/17/2027 4:54 PM
Total Duration: 2 hr 20 min
PASSENGERS
ADULT(S)
1 - Alex Taylor
'''
    assert extract_frontier_connection_cards(text) is None
    flights = prepare(text).flights
    assert len(flights) == 1 and flights[0].flight_number == 'F9903'


def test_recognized_oversized_document_holds():
    assert extract_frontier_connection_cards(receipt() + 'x' * 200_001) == []


def test_card_keys_bind_raw_printed_card_and_return_independent_objects():
    text = receipt(); first = extract_frontier_connection_cards(text); before = deepcopy(first)
    second = extract_frontier_connection_cards(text)
    second[0]['source_leg']['connection_itinerary']['flight_numbers'].append('F9999')
    assert first == before
    changed = extract_frontier_connection_cards(text.replace('901','904'))
    assert first[0]['source_leg']['key'] != changed[0]['source_leg']['key']


@pytest.mark.parametrize('lane', ['off','unlisted','on'])
@pytest.mark.parametrize('seed', ['empty','legacy_local','normalized_aggregate','normalized_linked_aggregate'])
def test_booking_service_has_two_true_legs_and_preserves_unrelated_rows(monkeypatch, lane, seed):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.models import Base, BookingObservation, Segment, Trip, User
    from app.services.booking_import import apply_booking_message
    from app.services.booking_legacy_repair import _state
    from app.services.flight_import_rollout import FEATURE_FLAGS, ALLOWLIST_ENV
    from app.services.flight_times import normalize_flight_times
    from app.services.parser import ParsedFlight
    monkeypatch.setattr('app.services.builder.enrich_segment', lambda *args, **kwargs: None)
    for flag in FEATURE_FLAGS:
        monkeypatch.setenv(flag, 'false' if lane == 'off' else 'true')
    monkeypatch.setenv(ALLOWLIST_ENV, '1' if lane == 'on' else '2')
    engine=create_engine('sqlite:///:memory:'); Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all([User(id=1,name='Alex Taylor',email='alex@example.test'),User(id=2,name='Jamie Other',email='jamie@example.test')]);db.flush()
        foreign=Trip(id=2,user_id=2,title='Unrelated',start_ts=datetime(2027,5,17,12),end_ts=datetime(2027,5,17,14),visibility='private')
        db.add(foreign);db.flush()
        db.add(Segment(id=10,trip_id=2,mode='flight',dep_airport='DFW',arr_airport='SAN',dep_time=datetime(2027,5,17,12),arr_time=datetime(2027,5,17,14),airline='F9',flight_number='F9901',pnr='TEST12',meta_json={'manual':True}));db.flush()
        other_before=_state(db,2)
        if seed != 'empty':
            original=ParsedFlight('DFW','SAN',datetime(2027,5,17,15,43,tzinfo=timezone.utc),datetime(2027,5,17,21,2,tzinfo=timezone.utc),airline='F9',flight_number='F9901',pnr='TEST12')
            meta={'source':'heuristic','source_received_at':'2027-04-01T00:00:00+00:00'}
            if seed in ('normalized_aggregate','normalized_linked_aggregate'):
                normalize_flight_times(original)
                meta.update(time_provenance=original.time_provenance, source_message_ids=['frontier-document'])
            trip=Trip(id=1,user_id=1,title='Legacy',start_ts=original.dep_time,end_ts=original.arr_time,visibility='private')
            db.add(trip);db.flush()
            db.add(Segment(id=5,trip_id=1,mode='flight',dep_airport='DFW',arr_airport='SAN',dep_time=original.dep_time,arr_time=original.arr_time,airline='F9',flight_number='F9901',pnr='TEST12',meta_json=meta));db.flush()
            if seed=='normalized_linked_aggregate':
                from app.services.booking_ledger import record_flight_observations
                named=prepare(receipt()).flights[0]
                original.ownership=named.ownership;original.passenger_names=named.passenger_names
                original.passenger_evidence=named.passenger_evidence;original.source='shape_labeled_route_time_blocks'
                original.parser_version=27
                recorded=record_flight_observations(db,1,[original],source_message_id='frontier-document',source_event_at=datetime(2027,4,1,tzinfo=timezone.utc))
                db.get(Segment,5).meta_json={**meta,'observation_ids':[recorded.flights[0].observation_id]}
                db.flush()
        snapshots=[]; observations={r.id:deepcopy(r.facts) for r in db.query(BookingObservation).filter_by(user_id=1)}
        for repeat in range(4):
            result=prepare(receipt())
            apply_booking_message(db,1,result,source_message_id='frontier-document',subject='Your flight confirmation',plain_text=receipt(),html='',received_at=datetime(2027,4,1,tzinfo=timezone.utc))
            db.flush()
            active=db.query(Segment).join(Trip).filter(Trip.user_id==1).order_by(Segment.dep_time).all()
            assert [(r.flight_number,r.dep_airport,r.arr_airport) for r in active] == [('F9901','DFW','LAS'),('F9902','LAS','SAN')]
            assert [(r.dep_time.isoformat(),r.arr_time.isoformat()) for r in active] == [('2027-05-17T20:43:00','2027-05-17T23:49:00'),('2027-05-18T02:52:00','2027-05-18T04:02:00')]
            if seed!='empty':assert active[0].id==5
            current={r.id:deepcopy(r.facts) for r in db.query(BookingObservation).filter_by(user_id=1)}
            assert all(current[k]==v for k,v in observations.items());observations=current
            assert len(current)==(3 if seed=='normalized_linked_aggregate' else 2) and _state(db,2)==other_before
            snapshots.append(_state(db,1))
        assert snapshots[1] == snapshots[2] == snapshots[3]
    engine.dispose()
