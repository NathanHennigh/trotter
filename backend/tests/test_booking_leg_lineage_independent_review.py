"""Independent fail-closed checks for document-local correction authority."""
from copy import deepcopy
from datetime import timedelta

import pytest

from app.models import BookingObservation, FlightShare, Segment, Trip, TravelInboxItem, TravelInboxEvidence, TravelInboxAssignment
from app.services.booking_ledger import record_user_decision
from test_booking_leg_lineage import context, flight, ingest, fields, stamp  # noqa: F401


def share(db, sender, recipient, *, segment_ids=None, item_ids=None):
    value = FlightShare(sender_id=sender.id, recipient_user_id=recipient.id,
        recipient_email=recipient.email, passenger_name=recipient.name,
        client_request_id="independent-share", request_hash="a" * 64,
        token_hash="b" * 64, token_encrypted=b"synthetic-no-token",
        item_ids=item_ids or [], flights=[], status="accepted",
        expires_at=stamp("2030-01-01T00:00:00"), accepted_segment_ids=segment_ids or [])
    db.add(value); db.flush()
    return value


@pytest.mark.parametrize("protection", ["active_alias_decision", "accepted_reference", "assigned_item", "outgoing_share"])
def test_correction_preserves_decision_and_sharing_references(context, protection):
    db, user, other = context
    old = flight()
    old.pnr_aliases = ["ALIAS1"]
    ingest(db, user, old); db.commit()
    row = db.query(Segment).one()
    if protection == "active_alias_decision":
        alias = deepcopy(old); alias.pnr = "ALIAS1"
        record_user_decision(db, user.id, alias, ownership="self", status="active")
    elif protection == "accepted_reference":
        # The recipient's own confirmation may already have refreshed source.
        row.meta_json = {**row.meta_json, "source": "receipt"}
        share(db, other, user, segment_ids=[row.id])
    else:
        item = TravelInboxItem(user_id=user.id, record_key="c" * 64, flight_key="d" * 64,
                              passenger_name=user.name, reason="unassigned")
        db.add(item); db.flush()
        db.add(TravelInboxEvidence(item_id=item.id, observation_id=db.query(BookingObservation).filter_by(
            source_message_id="original").one().id))
        if protection == "assigned_item":
            db.add(TravelInboxAssignment(item_id=item.id, user_id=user.id, passenger_name=other.name))
        else:
            share(db, user, other, item_ids=[item.id])
    db.commit()
    before = fields(row)
    corrected = flight(revision=30, day="2026-03-15")
    corrected.pnr_aliases = ["ALIAS1"]
    result = ingest(db, user, corrected)
    assert result.held == 1
    assert fields(db.get(Segment, row.id)) == before
    assert db.query(Segment).count() == 1


@pytest.mark.parametrize("change", ["received_later", "received_missing", "forged_revision", "current_named_other"])
def test_uncertain_document_authority_cannot_replace_original(context, change):
    db, user, _ = context
    old = flight()
    ingest(db, user, old); db.commit()
    row = db.query(Segment).one()
    before = fields(row)
    new = flight(revision=30, day="2026-03-15")
    if change == "received_later": new.source_received_at += timedelta(days=1)
    elif change == "received_missing": new.source_received_at = None
    elif change == "forged_revision": new.parser_version = "30"
    else:
        new.ownership = "other"
        new.passenger_names = ["Other Person"]
        new.passenger_evidence[0]["name"] = "Other Person"
    ingest(db, user, new)
    assert fields(db.get(Segment, row.id)) == before


def test_matching_target_duplicate_is_held_for_reviewed_merge(context):
    db, user, _ = context
    ingest(db, user, flight()); db.commit()
    row = db.query(Segment).one()
    corrected = flight(revision=30, day="2026-03-15")
    target_trip = Trip(user_id=user.id)
    db.add(target_trip); db.flush()
    target = Segment(trip_id=target_trip.id, mode="flight", dep_airport=corrected.dep_airport,
        arr_airport=corrected.arr_airport, dep_time=corrected.dep_time, arr_time=corrected.arr_time,
        airline=corrected.airline, flight_number=corrected.flight_number, pnr="OTHER1", meta_json={})
    db.add(target); db.commit()
    before = fields(row), fields(target)
    result = ingest(db, user, corrected)
    assert result.held == 1 and db.query(Segment).count() == 2
    assert (fields(row), fields(target)) == before
