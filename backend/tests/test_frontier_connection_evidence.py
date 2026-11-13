from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.services.booking_ledger import flight_facts
from app.services.frontier_connection_evidence import same_original_summary_rows, summary_schedule
from test_frontier_connection_cards import prepare, receipt


def pair():
    parsed = prepare(receipt())
    first, last = parsed.flights
    old = deepcopy(first)
    old.source = 'shape_labeled_route_time_blocks'
    old.source_leg = {}
    old.arr_airport, old.arr_time = 'SAN', last.arr_time
    old.time_provenance = deepcopy(old.time_provenance)
    old.time_provenance.pop('date_evidence', None)
    old.time_provenance['arrival'] = deepcopy(last.time_provenance['arrival'])
    def observation(ident, value):
        return SimpleNamespace(id=ident, user_id=1, source_message_id='same-original',
            source_event_at=datetime(2027,4,1,tzinfo=timezone.utc), ownership='self', pnr='TEST12',
            dep_airport=value.dep_airport, arr_airport=value.arr_airport,
            travel_date=value.time_provenance['departure_local_date'],
            flight_number=value.flight_number, facts=flight_facts(value))
    return observation(2, first), observation(1, old)


def test_exact_same_original_old_summary_has_one_bounded_correction():
    current, old = pair()
    assert same_original_summary_rows(current, [old, current], ['Alex Taylor']) == [old]
    assert summary_schedule(current) == ('DFW','SAN','F9901',datetime(2027,5,17,20,43),datetime(2027,5,18,4,2))


@pytest.mark.parametrize('field,value', [('user_id',2), ('source_message_id','another-original'),
    ('source_event_at',None), ('source_event_at',datetime(2027,4,2,tzinfo=timezone.utc)),
    ('pnr','OTHER1'), ('ownership','unknown'), ('ownership','other'),
    ('dep_airport','IAH'), ('arr_airport','SFO'), ('flight_number','F9999')])
def test_other_account_document_booking_passenger_clock_or_route_grants_no_exception(field,value):
    current, old = pair(); setattr(old,field,value)
    assert same_original_summary_rows(current,[old],['Alex Taylor']) == []


@pytest.mark.parametrize('field,value', [('source','user_review'),('source','flight_share'),
    ('force_review',True),('pnr_aliases',['ALIAS1']),('source_leg',{'key':'a'*64}),
    ('dep_time','2027-05-17T20:44:00+00:00'),('arr_time','2027-05-18T04:03:00+00:00')])
def test_manual_ambiguous_or_different_old_interpretation_is_not_summary_authority(field,value):
    current,old=pair();old.facts[field]=value
    assert same_original_summary_rows(current,[old],['Alex Taylor']) == []


@pytest.mark.parametrize('which',['current','old'])
@pytest.mark.parametrize('mutation',['no_complete_name','other_name','ambiguous_name','no_names'])
def test_proof_requires_complete_exact_owner_evidence(which,mutation):
    current,old=pair();row=current if which=='current' else old
    entries=row.facts['passenger_evidence']
    if mutation=='no_names':row.facts['passenger_evidence']=[]
    for entry in entries:
        if mutation=='no_complete_name':entry['complete']=False
        if mutation=='other_name':entry['name']='Jamie Other'
        if mutation=='ambiguous_name':entry['scope_ambiguous']=True
    assert same_original_summary_rows(current,[old],['Alex Taylor']) == []


@pytest.mark.parametrize('mutation', ['no_proof','wrong_template','wrong_digest','wrong_count','wrong_sequence',
    'wrong_first_clock','wrong_second_route','wrong_second_clock','wrong_gap','wrong_total','wrong_summary',
    'duplicate_number','scalar_legs','missing_second','no_timezone_airport','boolean_gap',
    'boolean_version','missing_ambiguity','none_ambiguity','offset_wall','naive_wall','utc_z_wall',
    'wrong_printed_date','wrong_provenance_date'])
def test_malformed_numbered_card_proof_never_bypasses_legacy_hold(mutation):
    current,old=pair();pointer=current.facts['source_leg'];proof=pointer['connection_itinerary']
    if mutation=='no_proof':pointer['connection_itinerary']=None
    if mutation=='wrong_template':pointer['template']='unrelated'
    if mutation=='wrong_digest':pointer['key']='0'*64
    if mutation=='wrong_count':proof['leg_count']=3
    if mutation=='wrong_sequence':proof['leg_sequence']=2
    if mutation=='wrong_first_clock':proof['printed_legs'][0]['arrival_local']='2027-05-17T16:50:00+00:00'
    if mutation=='wrong_second_route':proof['printed_legs'][1]['dep_airport']='DEN'
    if mutation=='wrong_second_clock':proof['printed_legs'][1]['departure_local']='2027-05-17T19:53:00+00:00'
    if mutation=='wrong_gap':proof['printed_layover_minutes']=184
    if mutation=='wrong_total':proof['printed_total_minutes']=440
    if mutation=='wrong_summary':proof['summary_departure_local']='2027-05-17T15:44:00+00:00'
    if mutation=='duplicate_number':proof['printed_legs'][1]['flight_number']='F9901';proof['flight_numbers'][1]='F9901'
    if mutation=='scalar_legs':proof['printed_legs']='bad'
    if mutation=='missing_second':proof['printed_legs'].pop()
    if mutation=='no_timezone_airport':proof['printed_legs'][1]['arr_airport']='ZZZ';proof['summary_route'][1]='ZZZ'
    if mutation=='boolean_gap':proof['printed_layover_minutes']=True
    if mutation=='boolean_version':pointer['version']=True
    if mutation=='missing_ambiguity':pointer.pop('ambiguous')
    if mutation=='none_ambiguity':pointer['ambiguous']=None
    if mutation=='offset_wall':proof['printed_legs'][0]['departure_local']=proof['printed_legs'][0]['departure_local'].replace('+00:00','+03:00')
    if mutation=='naive_wall':proof['printed_legs'][0]['departure_local']=proof['printed_legs'][0]['departure_local'][:-6]
    if mutation=='utc_z_wall':proof['printed_legs'][0]['departure_local']=proof['printed_legs'][0]['departure_local'].replace('+00:00','Z')
    if mutation=='wrong_printed_date':proof['printed_departure_date']='2027-05-18'
    if mutation=='wrong_provenance_date':current.facts['time_provenance']['departure_local_date']='2027-05-18'
    current.facts['time_provenance']['date_evidence']=deepcopy(pointer.get('connection_itinerary'))
    assert summary_schedule(current) is None
    assert same_original_summary_rows(current,[old],['Alex Taylor']) == []


@pytest.mark.parametrize('which',['current','old'])
@pytest.mark.parametrize('field,value',[('dep_airport','IAH'),('arr_airport','SFO'),('flight_number','F9999'),
    ('pnr','OTHER1'),('ownership','other'),('airline','AA')])
def test_indexed_row_and_recorded_facts_must_agree(which,field,value):
    current,old=pair();row=current if which=='current' else old
    row.facts[field]=value
    assert same_original_summary_rows(current,[old],['Alex Taylor']) == []


@pytest.mark.parametrize('which',['current','old'])
def test_indexed_travel_date_must_agree_with_source_local_date(which):
    current,old=pair();row=current if which=='current' else old
    row.travel_date='2027-05-18'
    assert same_original_summary_rows(current,[old],['Alex Taylor']) == []


@pytest.mark.parametrize('protection',['none','manual','user_review','share_metadata','accepted_share','held','canceled','later_source'])
def test_exception_reuses_existing_projector_protections(monkeypatch, protection):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.models import Base, Segment, User
    from app.services.booking_ledger import record_flight_observations, record_user_decision
    from app.services.booking_leg_lineage import find
    from app.services.builder import build_segments_and_trips_detailed
    monkeypatch.setattr('app.services.builder.enrich_segment',lambda *args,**kwargs:None)
    monkeypatch.setenv('BOOKING_LEG_RECONCILIATION_ENABLED','true')
    monkeypatch.setenv('FLIGHT_IMPORT_RECOVERY_USER_IDS','1')
    engine=create_engine('sqlite:///:memory:');Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(User(id=1,name='Alex Taylor',email='alex@example.test'));db.flush()
        flights=prepare(receipt()).flights
        from app.services.parser import PARSER_VERSION
        flights[0].parser_version=PARSER_VERSION
        old=deepcopy(flights[0]);old.source='shape_labeled_route_time_blocks';old.source_leg={}
        old.arr_airport,old.arr_time='SAN',flights[1].arr_time
        old.time_provenance.pop('date_evidence',None)
        old.time_provenance['arrival']=deepcopy(flights[1].time_provenance['arrival'])
        build_segments_and_trips_detailed(db,1,[old],source_message_id='same-original',source_event_at=old.source_received_at)
        db.flush();segment=db.query(Segment).one()
        if protection=='manual':segment.meta_json={**segment.meta_json,'source':'manual'}
        if protection=='user_review':segment.meta_json={**segment.meta_json,'source':'user_review'}
        if protection=='share_metadata':segment.meta_json={**segment.meta_json,'source':'accepted_flight_share'}
        if protection=='accepted_share':
            from app.models import FlightShare
            db.add(User(id=2,name='Jamie Other',email='jamie@example.test'));db.flush()
            db.add(FlightShare(sender_id=2,recipient_email='alex@example.test',recipient_user_id=1,
                passenger_name='Alex Taylor',client_request_id='share-request',request_hash='a'*64,
                token_hash='b'*64,token_encrypted=b'inert',item_ids=[],flights=[],status='accepted',
                accepted_segment_ids=[segment.id],expires_at=datetime(2027,4,2,tzinfo=timezone.utc)))
        if protection in ('held','canceled'):record_user_decision(db,1,old,status='hold' if protection=='held' else 'canceled')
        if protection=='later_source':segment.meta_json={**segment.meta_json,'source_received_at':'2027-04-02T00:00:00+00:00'}
        db.flush()
        decision=record_flight_observations(db,1,[flights[0]],source_message_id='same-original',source_event_at=old.source_received_at)
        db.flush()
        incoming=decision.flights[0]
        assert incoming.observation_id and incoming.source_message_id=='same-original'
        from app.models import BookingObservation
        current=db.get(BookingObservation,incoming.observation_id)
        summary_rows=same_original_summary_rows(current,db.query(BookingObservation).all(),['Alex Taylor'])
        assert len(summary_rows)==1 and summary_rows[0].id in segment.meta_json['observation_ids']
        before=(segment.id,segment.dep_airport,segment.arr_airport,segment.dep_time,segment.arr_time,deepcopy(segment.meta_json))
        result=find(db,1,incoming)
        if protection=='none':
            assert result.status=='linked' and result.segment.id==segment.id and result.overwrite
        else:
            assert result.status in ('held','stale') and result.segment is None
        assert before==(segment.id,segment.dep_airport,segment.arr_airport,segment.dep_time,segment.arr_time,segment.meta_json)
    engine.dispose()
