"""A new split-card interpretation cannot rewrite a protected old aggregate."""
from copy import deepcopy
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import (Base, BookingObservation, FlightShare, Segment, Trip, User,
    TravelInboxAssignment, TravelInboxEvidence, TravelInboxItem)
from app.services.booking_import import apply_booking_message
from app.services.booking_ledger import record_user_decision
from app.services.booking_legacy_repair import _state
from app.services.builder import build_segments_and_trips_detailed
from app.services.flight_import_rollout import FEATURE_FLAGS, ALLOWLIST_ENV
from test_frontier_connection_cards import prepare, receipt


def rows(db, model):
    primary = list(model.__table__.primary_key.columns)
    records = db.query(model).all()
    result = {tuple(getattr(row,c.name) for c in primary):
        {c.name: deepcopy(getattr(row,c.name)) for c in model.__table__.columns} for row in records}
    assert len(result)==len(records)
    return result


@pytest.mark.parametrize('lane',['off','unlisted','on'])
@pytest.mark.parametrize('local_legacy',[False,True])
@pytest.mark.parametrize('protection',['manual','personal_note','user_edited','source','public','unlisted',
    'manual_grouped_member','accepted_share','assignment','held','canceled','later_source'])
def test_protected_summary_and_both_card_siblings_remain_held(monkeypatch,lane,local_legacy,protection):
    monkeypatch.setattr('app.services.builder.enrich_segment',lambda *args,**kwargs:None)
    for flag in FEATURE_FLAGS:monkeypatch.setenv(flag,'false' if lane=='off' else 'true')
    monkeypatch.setenv(ALLOWLIST_ENV,'1' if lane=='on' else '2')
    engine=create_engine('sqlite:///:memory:');Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all([User(id=1,name='Alex Taylor',email='alex@example.test'),
            User(id=2,name='Jamie Other',email='jamie@example.test')]);db.flush()
        parsed=prepare(receipt());old=deepcopy(parsed.flights[0]);old.source='shape_labeled_route_time_blocks'
        old.source_leg={};old.parser_version=27;old.arr_airport='SAN';old.arr_time=parsed.flights[1].arr_time
        old.time_provenance.pop('date_evidence',None);old.time_provenance['arrival']=deepcopy(parsed.flights[1].time_provenance['arrival'])
        build_segments_and_trips_detailed(db,1,[old],source_message_id='original',source_event_at=old.source_received_at)
        db.flush();segment=db.query(Segment).one();trip=db.get(Trip,segment.trip_id)
        if local_legacy:
            segment.dep_time=datetime(2027,5,17,15,43);segment.arr_time=datetime(2027,5,17,21,2)
            segment.meta_json={k:v for k,v in segment.meta_json.items() if k!='time_provenance'}
            trip.start_ts,trip.end_ts=segment.dep_time,segment.arr_time
        if protection in ('manual','personal_note','user_edited'):
            segment.meta_json={**segment.meta_json,protection:'explicit owner choice'}
        if protection=='source':segment.meta_json={**segment.meta_json,'source':'user_review'}
        if protection in ('public','unlisted'):trip.visibility=protection
        if protection=='manual_grouped_member':
            db.add(Segment(trip_id=trip.id,mode='flight',dep_airport='SAN',arr_airport='DFW',
                dep_time=datetime(2027,5,21,10),arr_time=datetime(2027,5,21,14),flight_number='AA777',pnr='OTHER1',
                meta_json={'manual_grouping':True}))
        if protection=='accepted_share':
            db.add(FlightShare(sender_id=2,recipient_email='alex@example.test',recipient_user_id=1,
                passenger_name='Alex Taylor',client_request_id='request',request_hash='a'*64,token_hash='b'*64,
                token_encrypted=b'inert',item_ids=[],flights=[],status='accepted',accepted_segment_ids=[segment.id],
                expires_at=datetime(2027,5,1,tzinfo=timezone.utc)))
        if protection=='assignment':
            item=TravelInboxItem(user_id=1,record_key='a'*64,flight_key='b'*64,reason='unassigned')
            db.add(item);db.flush()
            db.add(TravelInboxEvidence(item_id=item.id,observation_id=segment.meta_json['observation_ids'][0]))
            db.add(TravelInboxAssignment(item_id=item.id,user_id=1,passenger_name='Alex Taylor'))
        if protection in ('held','canceled'):record_user_decision(db,1,old,status='hold' if protection=='held' else 'canceled')
        if protection=='later_source':segment.meta_json={**segment.meta_json,'source_received_at':'2027-04-02T00:00:00+00:00'}
        foreign=Trip(user_id=2,title='Unrelated',visibility='private',start_ts=datetime(2027,5,17),end_ts=datetime(2027,5,18))
        db.add(foreign);db.flush()
        db.add(Segment(trip_id=foreign.id,mode='flight',dep_airport='DFW',arr_airport='SAN',dep_time=segment.dep_time,
            arr_time=segment.arr_time,flight_number='F9901',pnr='TEST12',meta_json={'source_message_ids':['original']}));db.flush()
        physical_before={model.__tablename__:rows(db,model) for model in (Segment,Trip,BookingObservation,
            TravelInboxItem,TravelInboxEvidence,TravelInboxAssignment,FlightShare)}
        other_before=_state(db,2);snapshots=[]
        for _ in range(4):
            applied=apply_booking_message(db,1,prepare(receipt()),source_message_id='original',
                subject='Your flight confirmation',plain_text=receipt(),html='',received_at=old.source_received_at)
            db.flush()
            assert applied.build.held>=2
            assert rows(db,Segment)==physical_before['segments'] and rows(db,Trip)==physical_before['trips']
            for model in (BookingObservation,TravelInboxItem,TravelInboxEvidence,TravelInboxAssignment,FlightShare):
                after=rows(db,model)
                assert all(after[key]==value for key,value in physical_before[model.__tablename__].items())
            assert _state(db,2)==other_before
            snapshots.append(_state(db,1))
        assert snapshots[1]==snapshots[2]==snapshots[3]
    engine.dispose()
