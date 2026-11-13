"""A narrow, auditable inference may join two booked legs, never invent one."""
from copy import deepcopy
from datetime import datetime, timedelta
from hashlib import sha256

import pytest

from app.models import BookingObservation, ItineraryHistory, Segment, Trip, User
from app.services import builder
from test_contextual_trip_grouping import enabled, snapshot
from test_legacy_local_clock_replay import account
from test_booking_import_worker import worker


def leg(db, user, dep, arr, departure, *, pnr="OWN001", number="WN100", ownership="self"):
    arrival = departure + timedelta(hours=2)
    trip = Trip(user_id=user.id, title="Original title", start_ts=departure, end_ts=arrival, visibility="private")
    db.add(trip); db.flush()
    row = Segment(trip_id=trip.id, mode="flight", dep_airport=dep, arr_airport=arr,
        dep_time=departure, arr_time=arrival, airline="WN", flight_number=number, pnr=pnr)
    db.add(row); db.flush()
    provenance = {"version":1,"status":"normalized","departure_local_date":departure.date().isoformat()}
    facts = {"dep_airport":dep,"arr_airport":arr,"dep_time":departure.isoformat(),"arr_time":arrival.isoformat(),
        "airline":"WN","flight_number":number,"pnr":pnr,"ownership":ownership,"time_provenance":provenance,
        "passenger_evidence":[{"name":"Alex Avery","role":"traveler","complete":True,"applies":True}]}
    observation = BookingObservation(user_id=user.id,evidence_key=sha256(f"{user.id}:{row.id}".encode()).hexdigest(),
        source_message_id=f"source-{row.id}",source_event_at=departure-timedelta(days=10),pnr=pnr,
        travel_date=departure.date().isoformat(),dep_airport=dep,arr_airport=arr,flight_number=number,
        ownership=ownership,facts=facts)
    db.add(observation); db.flush()
    row.meta_json = {"ownership":ownership,"observation_ids":[observation.id],"time_provenance":provenance}
    db.flush()
    return row, observation


def pair(db, user, *, gap=timedelta(days=4), same_pnr=False):
    first, proof = leg(db,user,"DAL","ONT",datetime(2027,5,1,15))
    second, other = leg(db,user,"SAN","DAL",first.arr_time+gap,
        pnr="OWN001" if same_pnr else "OWN002",number="WN200")
    return [first,second],[proof,other]


@pytest.mark.parametrize("same_pnr", [False,True])
@pytest.mark.parametrize("seed", ["outbound","return","both"])
def test_unique_closed_loop_merges_only_membership_and_retains_history(account, enabled, same_pnr, seed):
    db,user=account
    rows,proofs=pair(db,user,same_pnr=same_pnr)
    before=snapshot(rows)
    source_before=snapshot(proofs)
    selected={rows[0].trip_id} if seed=="outbound" else {rows[1].trip_id} if seed=="return" else {r.trip_id for r in rows}
    assert not builder._airports_are_near("ONT","SAN")
    builder.rebuild_affected_trips(db,user.id,selected)
    assert len({r.trip_id for r in rows})==db.query(Trip).count()==1
    assert db.query(Segment).count()==2
    assert snapshot(proofs)==source_before
    for row in rows:
        old=before[row.id]
        assert all(getattr(row,key)==value for key,value in old.items() if key not in {"trip_id","meta_json"})
        assert {k:v for k,v in row.meta_json.items() if k!="trip_grouping_inferences"}==old["meta_json"]
        inference=row.meta_json["trip_grouping_inferences"]
        assert len(inference)==1 and inference[0]["kind"]=="closed_loop_open_jaw"
        assert inference[0]["minimum_gap_hours"]==4 and inference[0]["maximum_gap_days"]==7
        assert inference[0]["maximum_airport_distance_km"]==200
        assert 150<inference[0]["away_airport_distance_km"]<=200
        assert inference[0]["transfer"]=="unrecorded"
    stable=snapshot(rows),snapshot(db.query(Trip)),snapshot(db.query(ItineraryHistory))
    for _ in range(3):
        builder.rebuild_affected_trips(db,user.id,{r.trip_id for r in rows})
        assert (snapshot(rows),snapshot(db.query(Trip)),snapshot(db.query(ItineraryHistory)))==stable


@pytest.mark.parametrize("hours,allowed", [(0,False),(0.5,False),(3.99,False),(4,True),(168,True),(168.01,False)])
def test_new_exception_has_inclusive_time_bounds(account,hours,allowed):
    db,user=account
    rows,proofs=pair(db,user,gap=timedelta(hours=hours))
    assert bool(builder._bounded_open_jaw_pairs(rows,proofs,set())) is allowed


@pytest.mark.parametrize("distance,allowed", [(150,False),(150.01,True),(200,True),(200.01,False)])
def test_only_new150to200km_band_is_affected(account,monkeypatch,distance,allowed):
    db,user=account
    rows,proofs=pair(db,user)
    monkeypatch.setattr(builder,"_haversine_km",lambda *args:distance)
    assert bool(builder._bounded_open_jaw_pairs(rows,proofs,set())) is allowed


@pytest.mark.parametrize("problem", ["coords","country","both_countries","different_country","wrong_origin",
    "unknown","missing_name","incomplete_name","force_review","conflict","wrong_source_clock","missing_number"])
def test_incomplete_or_conflicting_pair_has_no_new_authority(account,monkeypatch,problem):
    db,user=account
    rows,proofs=pair(db,user)
    if problem=="coords": monkeypatch.delitem(builder._AIRPORT_COORDS,"SAN")
    if problem in {"country","both_countries","different_country"}:
        monkeypatch.setitem(builder._AIRPORT_DETAILS,"SAN",{"country":"CA" if problem=="different_country" else None})
        if problem=="both_countries":monkeypatch.setitem(builder._AIRPORT_DETAILS,"ONT",{"country":None})
    if problem=="wrong_origin":rows[1].arr_airport="DFW" # Nearby is insufficient.
    if problem=="unknown":proofs[1].ownership="unknown"
    if problem=="missing_name":proofs[1].facts={**proofs[1].facts,"passenger_evidence":[]}
    if problem=="incomplete_name":proofs[1].facts={**proofs[1].facts,"passenger_evidence":[{"name":"A","role":"traveler","complete":False,"applies":True}]}
    if problem=="force_review":proofs[1].facts={**proofs[1].facts,"force_review":True}
    if problem=="conflict":rows[1].meta_json={**rows[1].meta_json,"booking_conflicts":[{"reason":"post_departure_cancellation_conflict"}]}
    if problem=="wrong_source_clock":proofs[1].facts={**proofs[1].facts,"dep_time":"2027-05-01T10:00:00"}
    if problem=="missing_number":rows[1].flight_number=None
    assert not builder._bounded_open_jaw_pairs(rows,proofs,set())


@pytest.mark.parametrize("extra", ["outbound","return","intervening","overlap_outbound","overlap_return","duplicate"])
def test_ambiguous_or_interrupted_timeline_is_not_paired(account,extra):
    db,user=account
    rows,proofs=pair(db,user)
    if extra=="outbound":value,proof=leg(db,user,"DAL","LAX",rows[0].dep_time-timedelta(days=1),pnr="EXTRA1")
    elif extra=="return":value,proof=leg(db,user,"SAN","DAL",rows[1].dep_time+timedelta(days=1),pnr="EXTRA1")
    elif extra=="intervening":value,proof=leg(db,user,"LAX","LAS",rows[0].dep_time+timedelta(days=2),pnr="EXTRA1")
    elif extra=="overlap_outbound":value,proof=leg(db,user,"DEN","ORD",rows[0].dep_time-timedelta(hours=1),pnr="EXTRA1")
    elif extra=="overlap_return":value,proof=leg(db,user,"DEN","ORD",rows[1].dep_time+timedelta(hours=1),pnr="EXTRA1")
    else:value,proof=leg(db,user,"DAL","ONT",rows[0].dep_time,pnr="EXTRA1")
    assert not builder._bounded_open_jaw_pairs([*rows,value],[*proofs,proof],set())


@pytest.mark.parametrize("protection", ["manual_grouping","trip_grouping_locked","manual_trip_id","manually_edited","accepted_flight_share","public"])
def test_manual_and_shared_boundaries_remain_unchanged(account,enabled,protection):
    db,user=account
    rows,proofs=pair(db,user)
    if protection=="public":db.get(Trip,rows[1].trip_id).visibility="public"
    elif protection=="accepted_flight_share":rows[1].meta_json={**rows[1].meta_json,"source":"accepted_flight_share"}
    else:rows[1].meta_json={**rows[1].meta_json,protection:True}
    before=snapshot(rows),snapshot(db.query(Trip))
    builder.rebuild_affected_trips(db,user.id,{rows[0].trip_id})
    assert (snapshot(rows),snapshot(db.query(Trip)))==before


@pytest.mark.parametrize("policy", ["off","unlisted","on"])
def test_feature_boundary_and_other_account_are_preserved(account,monkeypatch,policy):
    db,user=account
    rows,proofs=pair(db,user)
    other=User(name="Other Traveler",email="other@example.test");db.add(other);db.flush()
    unrelated,unrelated_proofs=pair(db,other)
    before=snapshot(unrelated),snapshot(db.query(Trip).filter_by(user_id=other.id)),snapshot(unrelated_proofs)
    monkeypatch.setenv("BOOKING_CONTEXTUAL_TRIP_GROUPING_ENABLED","false" if policy=="off" else "true")
    monkeypatch.setenv("FLIGHT_IMPORT_RECOVERY_USER_IDS",str(user.id+100) if policy=="unlisted" else str(user.id))
    builder.rebuild_affected_trips(db,user.id,{rows[1].trip_id,unrelated[1].trip_id})
    assert (rows[0].trip_id==rows[1].trip_id) is (policy=="on")
    assert (snapshot(unrelated),snapshot(db.query(Trip).filter_by(user_id=other.id)),snapshot(unrelated_proofs))==before


def test_preceding_context_does_not_stamp_an_unused_pair_reason(account,enabled):
    db,user=account
    rows,proofs=pair(db,user)
    preceding,proof=leg(db,user,"DEN","DAL",rows[0].dep_time-timedelta(hours=3))
    assert builder._bounded_open_jaw_pairs([preceding,*rows],[proof,*proofs],set())
    builder.rebuild_affected_trips(db,user.id,{r.trip_id for r in [preceding,*rows]})
    assert preceding.trip_id==rows[0].trip_id!=rows[1].trip_id
    assert all(not row.meta_json.get("trip_grouping_inferences") for row in [preceding,*rows])


@pytest.mark.parametrize("reverse", [False,True])
@pytest.mark.parametrize("same_pnr", [False,True])
def test_raw_separate_worker_sources_join_once_and_repeat_stably(worker,enabled,monkeypatch,reverse,same_pnr):
    import base64
    from app.models import SyncJob
    from app.services import gmail
    from app.tasks import import_tasks
    factory,user_id,_=worker
    messages={}
    for kind,date,number,dep,arr,start,end,code in [
        ("outbound","Friday, 02/16/2024","40","DAL","ONT","5:45 PM","7:05 PM","OWN001"),
        ("return","Tuesday, 02/20/2024","3704","SAN","DAL","3:40 PM","8:30 PM","OWN001" if same_pnr else "OWN002")]:
        body=(f"Southwest Airlines\nConfirmation # {code}\nPASSENGER\nAlex Avery\n"
              f"Your itinerary\nFlight 1:\n{date}\nFLIGHT\n# {number}\nDEPARTS\n{dep} {start}\nARRIVES\n{arr} {end}\n")
        subject=f"Your flight is booked ({code}): itinerary and receipt"
        messages[kind]={"id":kind,"internalDate":"1706745600000","snippet":subject,
            "payload":{"mimeType":"text/plain","headers":[{"name":"Subject","value":subject},
                {"name":"From","value":"Southwest Airlines <ifly@southwest.com>"},
                {"name":"Date","value":"Thu, 01 Feb 2024 00:00:00 +0000"}],
                "body":{"data":base64.urlsafe_b64encode(body.encode()).decode()}}}
    monkeypatch.setattr(gmail,"get_message",lambda service,key:messages[key])
    monkeypatch.setattr(gmail,"batch_get_messages",lambda service,ids:({key:messages[key] for key in ids},{}))
    order=["return","outbound"] if reverse else ["outbound","return"]
    stable=None
    for repeat in range(5):
        for kind in order:
            job_id=f"open-jaw-{repeat}-{kind}"
            with factory() as db:
                db.add(SyncJob(id=job_id,user_id=user_id,state="pending")); db.commit()
            result=import_tasks.run_gmail_import.run(job_id=job_id,user_id=user_id,mode="exact_reprocess",message_ids=[kind])
            assert result["state"]=="completed"
        with factory() as db:
            rows=db.query(Segment).all()
            assert len(rows)==2 and len({r.trip_id for r in rows})==db.query(Trip).count()==1
            assert {(r.flight_number,r.dep_airport,r.arr_airport) for r in rows}=={("WN40","DAL","ONT"),("WN3704","SAN","DAL")}
            assert all(len(r.meta_json["trip_grouping_inferences"])==1 for r in rows)
            current=snapshot(rows),snapshot(db.query(Trip)),snapshot(db.query(BookingObservation)),snapshot(db.query(ItineraryHistory))
            if repeat>=2: assert current==stable
            stable=current
