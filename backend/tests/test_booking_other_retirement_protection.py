"""Named OTHER mail retains evidence without undoing explicit owner choices."""
from copy import deepcopy
from datetime import timedelta

import pytest

from app.models import BookingObservation, Segment, Trip, User
from app.services.booking_legacy_repair import _state
from app.services.booking_ledger import record_user_decision
from app.services.booking_projection_context import projection_run
from app.services.flight_import_rollout import FEATURE_FLAGS, ALLOWLIST_ENV
from test_booking_lifecycle_hardening import apply, db_user, legs
from test_booking_protected_trip_inserts import protect
from test_booking_import_worker import worker


def seed(db, user):
    values = legs(ownership="other")
    trip = Trip(user_id=user.id, title="Owner's journey", visibility="private",
                start_ts=values[0].dep_time, end_ts=values[-1].arr_time)
    db.add(trip); db.flush()
    for value in values:
        db.add(Segment(trip_id=trip.id, mode="flight", dep_airport=value.dep_airport,
            arr_airport=value.arr_airport, dep_time=value.dep_time, arr_time=value.arr_time,
            airline=value.airline, flight_number=value.flight_number, pnr=value.pnr,
            meta_json={"source":"legacy_receipt", "pnr_aliases":["ALIAS1"]}))
    db.commit()
    return values, db.query(Segment).filter_by(trip_id=trip.id).order_by(Segment.id).all()


def setting(monkeypatch, user_id, lane):
    for flag in FEATURE_FLAGS:
        monkeypatch.setenv(flag, "false" if lane == "off" else "true")
    monkeypatch.setenv(ALLOWLIST_ENV, str(user_id if lane == "on" else user_id + 1000))


PROTECTIONS = ["public", "unlisted", "manual", "user_review", "accepted_flight_share", "flight_share",
    "manual_grouping", "trip_grouping_locked", "manual_trip_id", "manually_edited", "manual_assignment",
    "accepted_reference", "manual_boolean", "user_edited", "personal_note", "alias_self", "alias_hold"]


@pytest.mark.parametrize("lane", ["off", "unlisted", "on"])
@pytest.mark.parametrize("protection", PROTECTIONS)
def test_other_receipt_preserves_protected_full_rows_and_all_evidence(db_user, monkeypatch, lane, protection):
    db, user = db_user
    setting(monkeypatch, user.id, lane)
    values, rows = seed(db, user)
    foreign = User(name="Other Owner", email="other-owner@example.test")
    db.add(foreign); db.flush()
    seed(db, foreign)
    row = rows[0]
    if protection == "unlisted": db.get(Trip,row.trip_id).visibility = "unlisted"
    elif protection in {"manual_boolean", "user_edited", "personal_note", "manual_assignment"}:
        key, value = {"manual_boolean":("manual",True), "user_edited":("user_edited",True),
            "personal_note":("personal_note","Keep these flights"),
            "manual_assignment":("trip_assignment_source","manual")}[protection]
        row.meta_json = {**row.meta_json,key:value}
    elif protection.startswith("alias_"):
        decision = deepcopy(values[0]); decision.pnr = "ALIAS1"
        record_user_decision(db,user.id,decision,ownership="self",
                             status="hold" if protection == "alias_hold" else "active")
    else: protect(db,row,protection)
    db.commit()
    before = deepcopy(_state(db,user.id)); foreign_before = deepcopy(_state(db,foreign.id))
    for repeat in range(4):
        with projection_run(db,user.id):
            outcome = apply(db,user,"named-other",values)
        db.commit()
        current = _state(db,user.id)
        assert outcome.build.removed_other == 0
        assert outcome.review_reason == "protected_other_passenger_conflict"
        assert current["segments"] == before["segments"]
        assert current["trips"] == before["trips"]
        assert all(current["observations"][key] == value for key,value in before["observations"].items())
        assert all(current["history"][key] == value for key,value in before["history"].items())
        observations = db.query(BookingObservation).filter_by(user_id=user.id,source_message_id="named-other").all()
        assert len(observations) == 2 and all(r.ownership == "other" for r in observations)
        assert len(current["inbox"]) >= 2 and len(current["retained_links"]) >= 2
        assert _state(db,foreign.id) == foreign_before
        if repeat: assert current == stable
        stable = deepcopy(current)


@pytest.mark.parametrize("lane", ["off", "unlisted", "on"])
def test_unprotected_other_retirement_remains_exact_and_snapshotted(db_user,monkeypatch,lane):
    db,user=db_user; setting(monkeypatch,user.id,lane)
    values,rows=seed(db,user)
    before=deepcopy(_state(db,user.id))
    outcome=apply(db,user,"named-other",values);db.commit()
    assert outcome.build.removed_other == 2 and outcome.review_reason is None
    after=_state(db,user.id)
    assert not after["segments"] and not after["trips"]
    for sid,row in before["segments"].items():
        assert any(h["entity_type"]=="segment" and h["entity_id"]==int(sid)
                   and h["snapshot"]==row and h["reason"]=="explicit_other_passenger"
                   for h in after["history"].values())
    for _ in range(3):
        apply(db,user,"named-other",values);db.commit()
        assert _state(db,user.id)==after


@pytest.mark.parametrize("changed", ["date","route","number","pnr"])
def test_other_mail_never_retires_a_different_dated_booking_leg(db_user,changed):
    db,user=db_user;values,_=seed(db,user)
    incoming=deepcopy(values[:1])
    if changed=="date": incoming[0].dep_time+=timedelta(days=1); incoming[0].arr_time+=timedelta(days=1)
    elif changed=="route": incoming[0].arr_airport="HOU"
    elif changed=="number": incoming[0].flight_number="WN999"
    else: incoming[0].pnr="OTHER1"
    before=deepcopy(_state(db,user.id))
    outcome=apply(db,user,"different-other",incoming);db.commit()
    after=_state(db,user.id)
    assert outcome.build.removed_other==0
    assert after["segments"]==before["segments"] and after["trips"]==before["trips"]


@pytest.mark.parametrize("protection", ["public","manual","accepted_reference"])
def test_explicit_exact_owner_other_decision_keeps_existing_authority(db_user,protection):
    db,user=db_user;values,rows=seed(db,user)
    protect(db,rows[0],protection)
    record_user_decision(db,user.id,values[0],ownership="other",status="active")
    db.commit()
    outcome=apply(db,user,"replay-reviewed-leg",values[:1]);db.commit()
    assert outcome.build.removed_other==1
    assert db.get(Segment,rows[0].id) is None
    assert db.get(Segment,rows[1].id) is not None


@pytest.mark.parametrize('lane',['off','unlisted','on'])
@pytest.mark.parametrize('protection',['none','public','manual_boolean','accepted_reference'])
def test_normal_worker_other_receipt_obeys_protection(worker,monkeypatch,lane,protection):
    import base64
    from app.models import SyncJob
    from app.services import gmail, flight_query_v4
    from app.services.flight_query_v4 import DiscoveryCandidate
    from app.tasks import import_tasks
    factory,user_id,_=worker; setting(monkeypatch,user_id,lane)
    body='Southwest Airlines\nConfirmation # ROUND1\nPASSENGER\nOther Guest\nYour itinerary\n'
    body+='Flight 1:\nFriday, 02/14/2025\nFLIGHT\n# 120\nDEPARTS\nDAL 12:00 PM\nARRIVES\nAUS 1:00 PM\n'
    payload={'id':'named-other','internalDate':'1738368000000','snippet':'Your flight itinerary and receipt',
        'payload':{'mimeType':'text/plain','headers':[{'name':'Subject','value':'Your flight is booked (ROUND1): itinerary and receipt'},
            {'name':'From','value':'Southwest <ifly@southwest.com>'},{'name':'Date','value':'Sat, 01 Feb 2025 00:00:00 +0000'}],
            'body':{'data':base64.urlsafe_b64encode(body.encode()).decode()}}}
    monkeypatch.setattr(gmail,'get_message',lambda service,key:deepcopy(payload))
    monkeypatch.setattr(gmail,'batch_get_messages',lambda service,ids:({key:deepcopy(payload) for key in ids},{}))
    monkeypatch.setattr(flight_query_v4,'iter_discovery_messages',lambda service,plan:[DiscoveryCandidate({'id':'named-other'},'fixture','offline',False)])
    from app.services.flight_message import prepare_flight_message
    parsed=prepare_flight_message(payload,user_name='Alex Avery',aliases=[],force_parse=False)['parse_result']
    assert len(parsed.flights)==1 and parsed.flights[0].ownership=='other'
    value=parsed.flights[0]
    with factory() as db:
        trip=Trip(user_id=user_id,title='Owner journey',visibility='private',start_ts=value.dep_time,end_ts=value.arr_time)
        db.add(trip);db.flush()
        row=Segment(trip_id=trip.id,mode='flight',dep_airport=value.dep_airport,arr_airport=value.arr_airport,
            dep_time=value.dep_time,arr_time=value.arr_time,airline=value.airline,flight_number=value.flight_number,pnr=value.pnr,meta_json={'source':'legacy'})
        db.add(row);db.flush()
        if protection=='manual_boolean':row.meta_json={**row.meta_json,'manual':True}
        elif protection!='none':protect(db,row,protection)
        db.commit();before=deepcopy(_state(db,user_id))
    for repeat in range(4):
        job=f'other-protection-{repeat}'
        with factory() as db:db.add(SyncJob(id=job,user_id=user_id,state='pending'));db.commit()
        result=import_tasks.run_gmail_import.run(job_id=job,user_id=user_id,mode='sync',limit=0)
        assert result['state']=='completed'
        with factory() as db:
            state=_state(db,user_id)
            if protection=='none':assert not state['segments'] and not state['trips']
            else:assert state['segments']==before['segments'] and state['trips']==before['trips']
            assert len(state['observations'])==1 and len(state['inbox'])==1 and len(state['retained_links'])==1
            # Sync bookkeeping may record cache decisions; all projection and
            # evidence rows must already be stable after the initial receipt.
            projection={k:v for k,v in state.items() if k!='messages'}
            if repeat:assert projection==stable
            stable=deepcopy(projection)
