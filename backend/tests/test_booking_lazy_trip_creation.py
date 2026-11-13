"""Matched or held originals cannot manufacture never-used trip history."""
from copy import deepcopy
from datetime import timedelta

import pytest
from sqlalchemy import event

from app.models import BookingObservation, ItineraryHistory, Segment, Trip
from app.services import builder
from app.services.booking_ledger import record_user_decision
from test_booking_lifecycle_hardening import apply, db_user, legs
from test_contextual_trip_grouping import enabled, snapshot
from test_legacy_local_clock_replay import account, flight, seed, apply as apply_legacy


def allocations(db):
    created = []
    def track(session, *_):
        created.extend(row for row in session.new if isinstance(row, Trip))
    event.listen(db, "before_flush", track)
    return created


@pytest.mark.parametrize("reverse", [False, True])
def test_same_booking_multiple_existing_journeys_never_allocates_repeat_shells(db_user, enabled, reverse):
    db, user = db_user
    values = legs()
    values[1].dep_time += timedelta(days=70)
    values[1].arr_time += timedelta(days=70)
    # A booking may cover separate journeys; this is not authority to join them.
    original = list(reversed(values)) if reverse else values
    first = apply(db,user,"multi-journey",original)
    assert first.build.inserted == 2 and db.query(Trip).count() == 2
    created = allocations(db)
    for _ in range(2):
        result = apply(db,user,"multi-journey",original)
        assert result.build.inserted == 0 and result.build.updated == 2 and result.build.trips == 2
    stable = snapshot(db.query(Segment)),snapshot(db.query(Trip)),snapshot(db.query(BookingObservation)),snapshot(db.query(ItineraryHistory))
    for _ in range(3):
        apply(db,user,"multi-journey",original)
        assert (snapshot(db.query(Segment)),snapshot(db.query(Trip)),snapshot(db.query(BookingObservation)),snapshot(db.query(ItineraryHistory))) == stable
    assert created == []


@pytest.mark.parametrize("protection", ["manual", "reviewed", "ambiguous"])
def test_late_legacy_hold_keeps_rows_and_never_allocates_trip(account,monkeypatch,protection):
    db,user=account
    monkeypatch.setattr(builder,"enrich_segment",lambda *a,**k:None)
    value=flight()
    row=seed(db,user,value,pnr="OLDER1")
    if protection=="manual": row.meta_json={**row.meta_json,"source":"manual"}
    if protection=="reviewed":
        record_user_decision(db,user.id,row,ownership="other")
    db.flush()
    before=snapshot(db.query(Segment)),snapshot(db.query(Trip))
    created=allocations(db)
    for _ in range(3):
        result=apply_legacy(db,user,[value])
        assert result.build.inserted == 0 and result.build.updated == 0
        assert result.build.held == 1 and result.build.trips == 0
        assert (snapshot(db.query(Segment)),snapshot(db.query(Trip)))==before
    assert created==[]


def test_new_template_hold_has_no_trip_allocation_and_preserves_source(db_user,monkeypatch):
    db,user=db_user
    value=legs()[0]
    value.source="shape_alaska_trip_detail_blocks"
    monkeypatch.setattr("app.services.booking_ticket_lifecycle.enabled",lambda uid:False)
    created=allocations(db)
    for _ in range(3):
        result=apply(db,user,"held-card",[value])
        assert result.build.inserted==0 and result.build.held==1 and result.build.trips==0
    assert created==[] and db.query(Trip).count()==db.query(Segment).count()==0
    assert db.query(BookingObservation).count()==1


@pytest.mark.parametrize("protection", ["manual", "accepted_flight_share", "user_review"])
def test_protected_review_holds_preserve_multiple_trips_without_unused_shells(db_user,enabled,protection):
    db,user=db_user
    values=legs()
    values[1].dep_time+=timedelta(days=70);values[1].arr_time+=timedelta(days=70)
    apply(db,user,"protected-booking",values)
    for row in db.query(Segment):
        row.meta_json={**row.meta_json,"source":protection,"personal_note":"Preserve"}
        record_user_decision(db,user.id,row,status="hold")
    db.flush()
    before=snapshot(db.query(Segment)),snapshot(db.query(Trip))
    created=allocations(db)
    for _ in range(3):
        result=apply(db,user,"protected-booking",values)
        assert result.build.inserted==0 and result.build.updated==0 and result.build.held==2
        assert (snapshot(db.query(Segment)),snapshot(db.query(Trip)))==before
    assert not created


def test_actual_new_legs_allocate_once_and_real_retired_trip_history_is_kept(db_user,enabled):
    db,user=db_user
    values=legs()
    created=allocations(db)
    apply(db,user,"return",[values[1]])
    old_trip=db.query(Trip).one().id
    apply(db,user,"outbound",[values[0]])
    assert db.query(Segment).count()==2 and db.query(Trip).count()==1
    assert len(created)==2
    retired=set(row.id for row in created)-{db.query(Trip).one().id}
    assert len(retired)==1
    assert all(db.query(ItineraryHistory).filter_by(entity_type="trip",entity_id=trip_id).count()
               for trip_id in retired)
