"""A complete immutable manifest can close a return-only active cluster."""
from copy import deepcopy
from datetime import datetime, timedelta
from hashlib import sha256
from itertools import permutations

import json
import pytest

from app.models import BookingObservation, ItineraryHistory, Segment, Trip
from app.services import builder
from app.services.booking_ledger import flight_facts
from app.services.flight_times import normalize_flight_times
from app.services.parser import ParsedFlight
from test_contextual_trip_grouping import add_trip, enabled, snapshot
from test_legacy_local_clock_replay import account


def evidence(db, user, source, sequence, dep, arr, when, arrival, *, pnr="CLOSE1", number="AA100", typed=True):
    flight=ParsedFlight(dep,arr,datetime.fromisoformat(when),datetime.fromisoformat(arrival),
        airline="AA",flight_number=number,pnr=pnr,source="receipt",ownership="self",
        passenger_names=[user.name],passenger_evidence=[{"name":user.name,"role":"traveler",
            "complete":True,"applies":True,"scope_ambiguous":False,"scope":{"pnr":pnr}}])
    normalize_flight_times(flight)
    assert not getattr(flight,"force_review",False)
    if typed:flight.source_leg={"version":1,"template":"ota_multi_confirmation","sequence":sequence,
        "key":sha256(f"{source}:{sequence}".encode()).hexdigest(),"ambiguous":False}
    facts=flight_facts(flight)
    row=BookingObservation(user_id=user.id,evidence_key=sha256(f"{source}:{sequence}:{number}".encode()).hexdigest(),
        source_message_id=source,pnr=pnr,travel_date=flight.time_provenance["departure_local_date"],
        dep_airport=dep,arr_airport=arr,flight_number=number,ownership="self",facts=facts)
    db.add(row);db.flush()
    return row,flight


def setup(db,user):
    # Active history has only the source's two returning legs. The earlier
    # outbound cards remain immutable evidence and never become new Segments.
    rows=[];flights=[]
    for seq,dep,arr,when,end in [
        (1,"IAH","JFK","2027-04-01T08:00","2027-04-01T12:00"),
        (2,"JFK","LHR","2027-04-02T09:00","2027-04-02T21:00"),
        (3,"LHR","JFK","2027-05-01T09:00","2027-05-01T12:00"),
        (4,"JFK","IAH","2027-05-02T09:00","2027-05-02T12:00")]:
        row,flight=evidence(db,user,"complete-source",seq,dep,arr,when,end,number=f"AA{seq}00")
        rows.append(row);flights.append(flight)
    following,flight=evidence(db,user,"separate-source",1,"IAH","ORD","2027-06-01T12:00","2027-06-01T15:00",pnr="LATER1",number="AA900",typed=False)
    rows.append(following);flights.append(flight)
    trip=Trip(user_id=user.id,title="Legacy mixed group",visibility="private")
    db.add(trip);db.flush();active=[]
    for row,flight in zip(rows[2:],flights[2:]):
        segment=Segment(trip_id=trip.id,mode="flight",dep_airport=flight.dep_airport,arr_airport=flight.arr_airport,
            dep_time=flight.dep_time.replace(tzinfo=None),arr_time=flight.arr_time.replace(tzinfo=None),
            airline=flight.airline,flight_number=flight.flight_number,pnr=flight.pnr,
            meta_json={"ownership":"self","observation_ids":[row.id],"time_provenance":flight.time_provenance})
        db.add(segment);active.append(segment)
    legacy=Segment(trip_id=trip.id,mode="flight",dep_airport="ORD",arr_airport="IAH",dep_time=datetime(2027,6,4,18),
        arr_time=datetime(2027,6,4,21),airline="UA",flight_number="UA900",pnr="LEGACY",meta_json={"legacy_note":"retain unknown ownership"})
    db.add(legacy);active.append(legacy);db.flush()
    trip.start_ts=min(s.dep_time for s in active);trip.end_ts=max(s.arr_time for s in active)
    other,otherrows=add_trip(db,user,"Unrelated manual title",[
        ("2020-01-01T12:00","2020-01-01T14:00","DFW","SFO"),
        ("2020-01-04T12:00","2020-01-04T14:00","SFO","DFW"),
        ("2028-01-01T12:00","2028-01-01T14:00","DFW","SFO"),
        ("2028-01-04T12:00","2028-01-04T14:00","SFO","DFW")],verified=False)
    db.flush()
    return trip,active,rows,other,otherrows


def breaks(db,user,trip,active,observations):
    trips={t.id:t for t in db.query(Trip)}
    return builder._source_closed_journey_breaks(active,observations,set(),{trip.id},user=user,trips=trips)


@pytest.mark.parametrize("order",[(0,1,2,3,4),(4,3,2,1,0),(2,4,0,3,1)])
def test_source_closure_splits_only_membership_and_keeps_unknown_legacy(account,enabled,order):
    db,user=account;trip,active,rows,other,otherrows=setup(db,user)
    before=snapshot(db.query(Segment));oldtrip=snapshot([trip]);immutable=snapshot(rows);unrelated=snapshot([other]),snapshot(otherrows)
    assert len(builder._cluster_saved_segments(active,"DFW"))==1
    assert breaks(db,user,trip,list(reversed(active)),[rows[i] for i in order])=={(active[1].id,active[2].id)}
    builder.rebuild_affected_trips(db,user.id,{trip.id})
    assert active[0].trip_id==active[1].trip_id!=active[2].trip_id==active[3].trip_id
    assert snapshot(rows)==immutable and (snapshot([other]),snapshot(otherrows))==unrelated
    after=snapshot(db.query(Segment));assert before.keys()==after.keys()
    for sid in before:assert {k:v for k,v in before[sid].items() if k!='trip_id'}=={k:v for k,v in after[sid].items() if k!='trip_id'}
    history=list(db.query(ItineraryHistory));assert history
    for h in history:
        assert h.user_id==user.id
        expected=before[h.entity_id] if h.entity_type=='segment' else oldtrip[h.entity_id]
        assert h.snapshot==json.loads(json.dumps(expected,default=lambda value:value.isoformat()))
    stable=snapshot(db.query(Segment)),snapshot(db.query(Trip)),snapshot(db.query(ItineraryHistory))
    for _ in range(3):
        builder.rebuild_affected_trips(db,user.id,{r.trip_id for r in active})
        assert (snapshot(db.query(Segment)),snapshot(db.query(Trip)),snapshot(db.query(ItineraryHistory)))==stable


@pytest.mark.parametrize("problem",["missing_card","wrong_template","ambiguous","sequence","bool_version","owner","account","trip_owner","facts_pnr","facts_route","facts_number","airline","initial_name","incomplete","scope_day","scope_route","current_clock","alias","same_pnr","unknown_next","source_same","connection","openjaw"])
def test_unproved_closure_keeps_existing_grouping_policy(account,problem):
    db,user=account;trip,active,rows,_,_=setup(db,user)
    if problem=='missing_card':rows=rows[1:]
    elif problem=='wrong_template':rows[0].facts['source_leg']['template']='heuristic'
    elif problem=='ambiguous':rows[0].facts['source_leg']['ambiguous']=True
    elif problem=='sequence':rows[0].facts['source_leg']['sequence']=2
    elif problem=='bool_version':rows[0].facts['source_leg']['version']=True
    elif problem=='owner':user.name='Jamie Baker'
    elif problem=='account':rows[3].user_id=user.id+1
    elif problem=='trip_owner':trip.user_id=user.id+1
    elif problem=='facts_pnr':rows[3].facts['pnr']='BAD001'
    elif problem=='facts_route':rows[3].facts['arr_airport']='DFW'
    elif problem=='facts_number':rows[3].facts['flight_number']='AA888'
    elif problem=='airline':active[1].airline='UA'
    elif problem=='initial_name':rows[3].facts['passenger_evidence'][0]['name']='A Avery'
    elif problem=='incomplete':rows[3].facts['passenger_evidence'][0]['complete']=False
    elif problem=='scope_day':rows[3].facts['passenger_evidence'][0]['scope']['departure_date']='2027-05-01'
    elif problem=='scope_route':rows[3].facts['passenger_evidence'][0]['scope']['dep_airport']='LHR'
    elif problem=='current_clock':active[1].arr_time+=timedelta(minutes=5)
    elif problem=='alias':active[2].meta_json['pnr_aliases']=['CLOSE1']
    elif problem=='same_pnr':active[2].pnr='CLOSE1'
    elif problem=='unknown_next':rows[4].ownership='unknown'
    elif problem=='source_same':rows[4].source_message_id=rows[3].source_message_id
    elif problem=='connection':active[2].dep_time=active[1].arr_time+timedelta(hours=5)
    elif problem=='openjaw':active[2].dep_airport='HOU'
    assert breaks(db,user,trip,active,rows)==set()


@pytest.mark.parametrize("protection",["public","unlisted","manual","personal_note","user_edited","manually_edited","manual_grouping","trip_grouping_locked","user_decision","source_manual","source_user_review","source_accepted_flight_share","source_flight_share"])
def test_new_boundary_never_overrides_protected_or_annotated_trip(account,protection):
    db,user=account;trip,active,rows,_,_=setup(db,user)
    if protection in ('public','unlisted'):trip.visibility=protection
    elif protection.startswith('source_'):active[0].meta_json['source']=protection[7:]
    else:active[0].meta_json[protection]=True
    assert breaks(db,user,trip,active,rows)==set()


def test_long_single_booking_stay_does_not_gain_an_internal_break(account):
    db,user=account;trip,active,rows,_,_=setup(db,user)
    # Shifting its outbound earlier does not turn the stay into a new journey.
    for row in rows[:2]:
        for key in ('dep_time','arr_time'):row.facts[key]=(datetime.fromisoformat(row.facts[key])-timedelta(days=68)).isoformat()
        for key in ('departure','arrival'):row.facts['time_provenance'][key]['utc']=(datetime.fromisoformat(row.facts['time_provenance'][key]['utc'])-timedelta(days=68)).isoformat()
        row.travel_date=(datetime.fromisoformat(row.travel_date)-timedelta(days=68)).date().isoformat()
        row.facts['time_provenance']['departure_local_date']=row.travel_date
    assert breaks(db,user,trip,active,rows)=={(active[1].id,active[2].id)}
