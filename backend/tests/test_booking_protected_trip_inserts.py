"""A matching old leg grants no membership or sharing authority for new legs."""
import base64
from copy import deepcopy
from datetime import timedelta

import pytest

from app.models import BookingObservation, ItineraryHistory, Segment, SyncJob, Trip
from app.services import builder
from app.services.booking_ledger import record_user_decision
from test_booking_import_worker import worker
from test_booking_lifecycle_hardening import apply, db_user, legs
from test_booking_lazy_trip_creation import allocations
from test_contextual_trip_grouping import snapshot


def policy(monkeypatch,user_id,value):
    monkeypatch.setenv("BOOKING_CONTEXTUAL_TRIP_GROUPING_ENABLED","false" if value=="off" else "true")
    monkeypatch.setenv("FLIGHT_IMPORT_RECOVERY_USER_IDS",str(user_id+100) if value=="unlisted" else str(user_id))


def protect(db,row,kind):
    trip=db.get(Trip,row.trip_id)
    if kind=="public":trip.visibility="public"
    elif kind in builder._PROTECTED_GROUPING_SOURCES:row.meta_json={**row.meta_json,"source":kind}
    elif kind=="decision":record_user_decision(db,trip.user_id,row,reason="Explicit owner review")
    elif kind=="accepted_reference":
        from app.models import User
        from test_booking_leg_lineage_independent_review import share
        sender=User(name="Sender",email="sender@example.test");db.add(sender);db.flush()
        share(db,sender,db.get(User,trip.user_id),segment_ids=[row.id])
    else:row.meta_json={**row.meta_json,kind:True}
    db.flush()


def schedule():
    values=legs()
    values[1].arr_airport="HOU"
    final=deepcopy(values[1]);final.dep_airport="HOU";final.arr_airport="DAL"
    final.dep_time+=timedelta(hours=2);final.arr_time+=timedelta(hours=2);final.flight_number="WN340"
    return [*values,final]


@pytest.mark.parametrize("setting",["off","unlisted","on"])
@pytest.mark.parametrize("protection",["public","manual","user_review","accepted_flight_share","flight_share",
    "manual_grouping","trip_grouping_locked","manual_trip_id","manually_edited","decision","accepted_reference"])
def test_mixed_receipt_preserves_protected_membership_and_new_leg_privacy(db_user,monkeypatch,setting,protection):
    db,user=db_user;policy(monkeypatch,user.id,setting)
    values=schedule();apply(db,user,"outbound",values[:1])
    old=db.query(Segment).one();protect(db,old,protection)
    old_id,trip_id=old.id,old.trip_id
    old_trip=snapshot([db.get(Trip,trip_id)])
    old_schedule={key:getattr(old,key) for key in ("dep_airport","arr_airport","dep_time","arr_time","flight_number","pnr")}
    original_observations=snapshot(db.query(BookingObservation))
    created=allocations(db)
    result=apply(db,user,"roundtrip",values)
    assert result.build.inserted==2 and result.build.updated==1
    assert len(created)==1 and created[0].visibility=="private"
    for _ in range(4):
        apply(db,user,"roundtrip",values)
        rows=db.query(Segment).all();new=[r for r in rows if r.id!=old_id]
        assert len(rows)==3 and old.trip_id==trip_id
        assert snapshot([db.get(Trip,trip_id)])==old_trip
        assert all(getattr(old,key)==value for key,value in old_schedule.items())
        if protection in builder._PROTECTED_GROUPING_SOURCES:assert old.meta_json["source"]==protection
        assert len({r.trip_id for r in new})==1 and all(r.trip_id!=trip_id for r in new)
        private=db.get(Trip,new[0].trip_id)
        assert private.visibility=="private" and private.start_ts==min(r.dep_time for r in new) and private.end_ts==max(r.arr_time for r in new)
        assert all(snapshot(db.query(BookingObservation))[key]==value for key,value in original_observations.items())
        current=snapshot(rows),snapshot(db.query(Trip)),snapshot(db.query(BookingObservation)),snapshot(db.query(ItineraryHistory))
        if _>=1:assert current==stable
        stable=current
    assert len(created)==1


@pytest.mark.parametrize("resolver",["exact_window","carrier_projection","document_lineage"])
def test_every_candidate_resolver_is_checked_at_actual_insert(db_user,monkeypatch,resolver):
    db,user=db_user;policy(monkeypatch,user.id,"on")
    values=schedule()
    if resolver=="document_lineage":
        from hashlib import sha256
        from app.services.flight_times import normalize_flight_times
        for i,value in enumerate(values):
            value.source="shape_numbered_flight_cards"
            value.source_leg={"version":1,"key":sha256(f"leg-{i}".encode()).hexdigest(),"sequence":i+1}
            value.parser_version=40
            value.passenger_evidence=[{"name":"Alex Morgan","role":"traveler","complete":True,"applies":True,"scope_ambiguous":False}]
            normalize_flight_times(value)
        monkeypatch.setenv("BOOKING_LEG_RECONCILIATION_ENABLED","true")
    apply(db,user,"outbound",values[:1]);old=db.query(Segment).one();protect(db,old,"public")
    trip=db.get(Trip,old.trip_id)
    if resolver=="exact_window":
        trip.start_ts=builder._db_datetime(values[1].dep_time);trip.end_ts=builder._db_datetime(values[2].arr_time)
        incoming=values[1:]
    elif resolver=="carrier_projection":
        monkeypatch.setattr("app.services.carrier_travel_recovery.existing_projection_trip",lambda *a:trip)
        incoming=values[1:]
    else:
        incoming=values
        from app.services import booking_leg_lineage
        find=booking_leg_lineage.find
        matched=[]
        def track(*args,**kwargs):
            result=find(*args,**kwargs)
            if result.segment is not None:matched.append(result.segment.id)
            return result
        monkeypatch.setattr(booking_leg_lineage,"find",track)
    db.flush();before=snapshot([trip])
    result=apply(db,user,"outbound" if resolver=="document_lineage" else "new-legs",incoming)
    assert result.build.inserted==2
    if resolver=="document_lineage":assert old.id in matched
    assert snapshot([trip])==before and db.query(Segment).filter_by(trip_id=trip.id).count()==1
    new=db.query(Segment).filter(Segment.id!=old.id).all()
    assert len(new)==2 and len({row.trip_id for row in new})==1
    assert db.get(Trip,new[0].trip_id).visibility=="private"


@pytest.mark.parametrize("setting",["off","unlisted","on"])
@pytest.mark.parametrize("protection",["public","manual_grouping","accepted_flight_share","flight_share"])
def test_valid_member_schedule_change_refreshes_only_protected_bounds(db_user,monkeypatch,setting,protection):
    db,user=db_user;policy(monkeypatch,user.id,setting)
    value=legs()[0];apply(db,user,"original",[value])
    row=db.query(Segment).one();protect(db,row,protection)
    trip=db.get(Trip,row.trip_id);trip.title="Keep my chosen title";db.flush()
    before=snapshot([trip])[trip.id];original_id=row.id
    originals=snapshot(db.query(BookingObservation))
    changed=deepcopy(value);changed.dep_time+=timedelta(hours=1);changed.arr_time+=timedelta(hours=1)
    result=apply(db,user,"new-schedule",[changed],kind="schedule",at="2025-01-21T12:00:00Z")
    assert result.build.updated==1 and result.build.inserted==0
    assert db.query(Segment).one().id==original_id and row.trip_id==trip.id
    assert trip.start_ts==row.dep_time==builder._db_datetime(changed.dep_time)
    assert trip.end_ts==row.arr_time==builder._db_datetime(changed.arr_time)
    assert {k:v for k,v in snapshot([trip])[trip.id].items() if k not in {"start_ts","end_ts"}}=={k:v for k,v in before.items() if k not in {"start_ts","end_ts"}}
    historical=db.query(ItineraryHistory).filter_by(entity_type="trip",entity_id=trip.id,reason="refresh_protected_trip_bounds").one()
    assert historical.snapshot["start_ts"]==before["start_ts"].isoformat() and historical.snapshot["end_ts"]==before["end_ts"].isoformat()
    stable=None
    for repeat in range(4):
        apply(db,user,"new-schedule",[changed],kind="schedule",at="2025-01-21T12:00:00Z")
        current=snapshot(db.query(Segment)),snapshot(db.query(Trip)),snapshot(db.query(ItineraryHistory))
        if repeat:assert current==stable
        stable=current
        assert all(snapshot(db.query(BookingObservation))[key]==value for key,value in originals.items())


@pytest.mark.parametrize("setting",["off","unlisted","on"])
@pytest.mark.parametrize("held",[False,True])
def test_unchanged_or_held_schedule_never_repairs_preexisting_custom_bounds(db_user,monkeypatch,setting,held):
    db,user=db_user;policy(monkeypatch,user.id,setting)
    value=legs()[0];apply(db,user,"original",[value])
    row=db.query(Segment).one();protect(db,row,"public")
    trip=db.get(Trip,row.trip_id);trip.start_ts-=timedelta(days=1);trip.end_ts+=timedelta(days=1)
    if held:record_user_decision(db,user.id,row,status="hold")
    db.flush();before=snapshot([trip]);stable=None
    changed=deepcopy(value)
    if held:changed.dep_time+=timedelta(hours=1);changed.arr_time+=timedelta(hours=1)
    for repeat in range(4):
        outcome=apply(db,user,"notice",[changed],kind="schedule",at="2025-01-21T12:00:00Z")
        assert outcome.build.held==int(held) and snapshot([trip])==before
        assert not db.query(ItineraryHistory).filter_by(reason="refresh_protected_trip_bounds").count()
        current=snapshot(db.query(Segment)),snapshot(db.query(Trip)),snapshot(db.query(ItineraryHistory))
        if repeat>=2:assert current==stable
        stable=current


@pytest.mark.parametrize("setting",["off","unlisted","on"])
@pytest.mark.parametrize("reverse",[False,True])
@pytest.mark.parametrize("protection",["public","manual_grouping","accepted_flight_share"])
def test_actual_worker_orders_do_not_append_to_protected_trip(worker,monkeypatch,setting,reverse,protection):
    from app.services import gmail
    from app.tasks import import_tasks
    factory,user_id,_=worker;policy(monkeypatch,user_id,setting)
    cards=["Flight 1:\nFriday, 02/14/2025\nFLIGHT\n# 120\nDEPARTS\nDAL 12:00 PM\nARRIVES\nAUS 1:00 PM\n",
        "Flight 2:\nMonday, 02/17/2025\nFLIGHT\n# 230\nDEPARTS\nAUS 12:00 PM\nARRIVES\nHOU 1:00 PM\n",
        "Flight 3:\nMonday, 02/17/2025\nFLIGHT\n# 340\nDEPARTS\nHOU 2:00 PM\nARRIVES\nDAL 3:00 PM\n"]
    messages={}
    for kind,body in (("outbound",cards[0]),("roundtrip","\n".join(cards))):
        body="Southwest Airlines\nConfirmation # ROUND1\nPASSENGER\nAlex Avery\nYour itinerary\n"+body
        messages[kind]={"id":kind,"internalDate":"1738368000000","snippet":"Your itinerary and receipt",
            "payload":{"mimeType":"text/plain","headers":[{"name":"Subject","value":"Your flight is booked (ROUND1): itinerary and receipt"},
                {"name":"From","value":"Southwest Airlines <ifly@southwest.com>"},{"name":"Date","value":"Sat, 01 Feb 2025 00:00:00 +0000"}],
                "body":{"data":base64.urlsafe_b64encode(body.encode()).decode()}}}
    monkeypatch.setattr(gmail,"get_message",lambda service,key:messages[key])
    monkeypatch.setattr(gmail,"batch_get_messages",lambda service,ids:({key:messages[key] for key in ids},{}))
    def run(key,job):
        with factory() as db:db.add(SyncJob(id=job,user_id=user_id,state="pending"));db.commit()
        result=import_tasks.run_gmail_import.run(job_id=job,user_id=user_id,mode="exact_reprocess",message_ids=[key])
        assert result["state"]=="completed"
    run("outbound","seed")
    with factory() as db:
        old=db.query(Segment).one();protect(db,old,protection);db.commit()
        old_id,old_trip_id=old.id,old.trip_id;before=snapshot([db.get(Trip,old_trip_id)])
    order=["roundtrip","outbound"] if reverse else ["outbound","roundtrip"]
    stable=None
    for repeat in range(5):
        for kind in order:run(kind,f"protected-{repeat}-{kind}")
        with factory() as db:
            rows=db.query(Segment).all();assert len(rows)==3
            assert db.get(Segment,old_id).trip_id==old_trip_id and snapshot([db.get(Trip,old_trip_id)])==before
            new=[r for r in rows if r.id!=old_id]
            assert len({r.trip_id for r in new})==1 and new[0].trip_id!=old_trip_id
            private=db.get(Trip,new[0].trip_id)
            assert private.visibility=="private" and private.start_ts==min(r.dep_time for r in new) and private.end_ts==max(r.arr_time for r in new)
            current=snapshot(rows),snapshot(db.query(Trip)),snapshot(db.query(BookingObservation)),snapshot(db.query(ItineraryHistory))
            if repeat>=2:assert current==stable
            stable=current
