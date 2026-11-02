"""Adversarial review of explicit legacy repair authority and postconditions."""
from copy import deepcopy

import pytest

from app.models import BookingObservation, BookingRepairManifest, ItineraryHistory, Segment, Trip
from app.services.booking_ledger import record_flight_observations, record_user_decision, record_cancellation
from app.services.booking_legacy_repair import prepare_legacy_repair
from app.services.booking_repair import RepairConflict
from test_booking_leg_lineage import context, flight, fields  # noqa: F401
from test_booking_legacy_repair import setup_case


@pytest.mark.parametrize("protection", ["alias_manual_active", "alias_manual_canceled", "alias_cancellation"])
def test_declared_alias_protection_blocks_legacy_date_rewrite(context, protection):
    db, user, _, legacy, evidence, spec = setup_case(context)
    legacy.meta_json = {**legacy.meta_json, "pnr_aliases": ["ALIAS1"]}
    alias = flight(); alias.pnr = "ALIAS1"
    if protection == "alias_cancellation":
        record_cancellation(db, user.id, "ALIAS1", source_message_id="cancel-alias",
                            source_event_at=alias.source_received_at, flights=[alias])
    else:
        record_user_decision(db, user.id, alias, status="active" if protection.endswith("active") else "canceled")
    db.commit()
    before = fields(legacy)
    with pytest.raises(RepairConflict):
        prepare_legacy_repair(db, user.id, [spec])
    assert fields(db.get(Segment, legacy.id)) == before
    assert db.query(BookingRepairManifest).count() == 0


@pytest.mark.parametrize("conflict", ["schedule", "passenger", "event_time", "selected_ownership"])
def test_selected_pointer_must_have_unambiguous_current_evidence(context, conflict):
    db, user, _, legacy, evidence, spec = setup_case(context)
    if conflict == "selected_ownership":
        evidence.ownership = "other"
    else:
        conflicting = flight(day="2026-03-15", revision=30)
        if conflict == "schedule":
            conflicting = flight(day="2026-03-16", revision=30)
        elif conflict == "passenger":
            conflicting.ownership = "other"
            conflicting.passenger_names = ["Other Person"]
            conflicting.passenger_evidence[0]["name"] = "Other Person"
        else:
            from datetime import timedelta
            conflicting.source_received_at += timedelta(days=1)
        record_flight_observations(db, user.id, [conflicting], source_message_id="original",
                                  source_event_at=conflicting.source_received_at)
    db.commit()
    before = fields(legacy)
    with pytest.raises(RepairConflict):
        prepare_legacy_repair(db, user.id, [spec])
    assert fields(db.get(Segment, legacy.id)) == before
    assert db.query(BookingRepairManifest).count() == 0


@pytest.mark.parametrize("fault", ["other_fact", "other_metadata", "new_flight", "old_history"])
def test_unrequested_mutations_roll_back_even_if_the_builder_misbehaves(context, monkeypatch, fault):
    from app.services import booking_legacy_repair as module
    db, user, _, legacy, evidence, spec = setup_case(context)
    other_trip = Trip(user_id=user.id, title="Unrelated journey")
    db.add(other_trip); db.flush()
    other = Segment(trip_id=other_trip.id, mode="flight", dep_airport="LHR", arr_airport="CDG",
                    dep_time=legacy.dep_time, arr_time=legacy.arr_time, airline="BA",
                    flight_number="BA100", pnr="OTHER1", meta_json={"note": "retain"})
    db.add(other); db.commit()
    original = deepcopy(other.meta_json), fields(other)
    old_history = db.query(ItineraryHistory).first()
    history_id = old_history.id
    history_snapshot = deepcopy(old_history.snapshot)
    real = module.rebuild_affected_trips

    def mutate(*args):
        result = real(*args)
        if fault == "other_fact": other.arr_airport = "FRA"
        elif fault == "other_metadata": other.meta_json = {"note": "lost"}
        elif fault == "new_flight":
            db.add(Segment(trip_id=other.trip_id, mode="flight", dep_airport="CDG", arr_airport="FRA",
                dep_time=other.dep_time, arr_time=other.arr_time, airline="BA", flight_number="BA101"))
        else:
            db.delete(db.get(ItineraryHistory, history_id))
        db.flush()
        return result

    monkeypatch.setattr(module, "rebuild_affected_trips", mutate)
    with pytest.raises(RepairConflict):
        prepare_legacy_repair(db, user.id, [spec])
    assert (other.meta_json, fields(other)) == original
    assert db.get(ItineraryHistory, history_id).snapshot == history_snapshot
    assert db.query(Segment).count() == 2
    assert db.query(BookingRepairManifest).count() == 0


@pytest.mark.parametrize("conflict", ["assigned_proof", "superseded_proof", "same_revision_passenger",
    "same_revision_schedule", "same_revision_event", "pending_share_proof", "accepted_share_proof"])
def test_unnamed_target_cannot_borrow_protected_or_obsolete_passenger_proof(context, conflict):
    from app.models import TravelInboxItem, TravelInboxEvidence, TravelInboxAssignment
    from test_booking_legacy_repair import with_later_unnamed_schedule
    db, user, other, legacy, named, latest, spec = with_later_unnamed_schedule(context)
    if conflict == "assigned_proof" or conflict.endswith("share_proof"):
        item = TravelInboxItem(user_id=user.id, record_key="e" * 64, flight_key="f" * 64,
                              passenger_name=other.name if conflict.endswith("share_proof") else user.name,
                              reason="unassigned")
        db.add(item); db.flush()
        db.add(TravelInboxEvidence(item_id=item.id, observation_id=named.id))
        if conflict == "assigned_proof":
            db.add(TravelInboxAssignment(item_id=item.id, user_id=user.id, passenger_name=other.name))
        else:
            from test_booking_leg_lineage_independent_review import share
            invitation = share(db, user, other, item_ids=[item.id])
            if conflict == "pending_share_proof": invitation.status = "pending"
    else:
        revised = flight(day="2026-03-16" if conflict == "same_revision_schedule" else "2026-03-15",
                         revision=31 if conflict == "superseded_proof" else 30)
        if conflict in {"superseded_proof", "same_revision_passenger"}:
            revised.ownership = "other"
            revised.passenger_names = [other.name]
            revised.passenger_evidence[0]["name"] = other.name
        if conflict == "same_revision_event":
            from datetime import timedelta
            revised.source_received_at += timedelta(days=1)
        record_flight_observations(db, user.id, [revised], source_message_id=named.source_message_id,
                                  source_event_at=revised.source_received_at)
    db.commit()
    before = fields(legacy)
    with pytest.raises(RepairConflict):
        prepare_legacy_repair(db, user.id, [spec])
    assert fields(db.get(Segment, legacy.id)) == before
    assert db.query(BookingRepairManifest).count() == 0
