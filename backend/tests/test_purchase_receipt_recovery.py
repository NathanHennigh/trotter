from copy import deepcopy

import pytest

from app.models import BookingObservation, ItineraryHistory, Message, MessageStatus, Segment, Trip
from app.services import flight_template_recovery as recovery
from app.services.parser import PARSER_VERSION, parse_email
from app.tasks.import_tasks import _message_skip_reason
from test_booking_import_worker import worker
from test_flight_template_recovery import setup
from test_legacy_local_clock_replay import account, apply, flight


@pytest.mark.parametrize("subject,sender", [
    ("Your StudentUniverse Order - March 4, 2022", "orders@studentuniverse.com"),
    ("View your flight details for your Multi-city trip", "bookings@capitalonebooking.com"),
    ("View your Capital One Travel Confirmation", "bookings@capitalonebooking.com"),
    ("Fwd: View your flight details for your Seattle trip", "friend@example.test"),
    ("You've redeemed lifemiles!", "tickets@confirmation.lifemiles.com"),
    ("Re: Fwd: You’ve redeemed lifemiles!", "friend@example.test"),
    ("Expedia flight purchase confirmation - example", "itinerary@expediamail.com"),
])
def test_receipt_is_selected_once_even_after_older_screen_or_marker(worker, monkeypatch, subject, sender):
    factory, uid, _ = worker
    setup(monkeypatch, uid)
    assert recovery.eligible(subject, sender)
    previous = recovery.completed_marker(uid)
    previous.pop("agency_receipt_version")
    with factory() as db:
        for n, marker in enumerate((previous, {"screened_out_version": recovery.VERSION})):
            db.add(Message(user_id=uid, provider_msg_id=str(n), subject=subject, from_email=sender,
                           status=MessageStatus.ACCEPTED, parse_version=PARSER_VERSION,
                           parse_evidence={"resolved":True, recovery.MARKER:marker}))
        db.commit()
        first = recovery.select_messages(db, uid)
        assert len(first) == 2
        for row in first:
            assert _message_skip_reason(row, PARSER_VERSION) is None
            row.parse_evidence = {**row.parse_evidence, recovery.MARKER:recovery.completed_marker(uid)}
        db.commit()
        for _ in range(2):
            assert recovery.select_messages(db, uid) == []
            assert all(_message_skip_reason(row,PARSER_VERSION) == "hardened_template_examined" for row in first)


@pytest.mark.parametrize("subject,sender", [
    ("Your StudentUniverse Order - March sale", "offers@studentuniverse.com"),
    ("Your StudentUniverse Order - March 4, 2022", "offers@studentuniverse.com.example.test"),
    ("You’ve redeemed lifemiles!", "travel@unrelated.test"),
    ("Your points have been converted to Lifemiles!", "offers@lifemiles.com"),
    ("View your rental car reservation details", "bookings@capitalonebooking.com"),
    ("Fwd: View your flight details for your Multi-city trip sale", "user@example.test"),
    ("View your Capital One Travel Confirmation", "bookings@notcapitalonebooking.com"),
])
def test_marketing_and_inexact_receipts_are_ineligible(subject, sender):
    assert not recovery.eligible(subject, sender)


ROWS = """Traveler: Alex Avery
Spirit Airlines 123 7:05pm Dallas (DFW-Dallas Fort Worth) to Orlando (MCO-Orlando International)
Airline confirmation: SPT123 (Spirit Airlines)
Fri, Mar 4, 7:05pm - 10:10pm 2h 5m flight duration
Aeromexico 654 1:49pm Orlando (MCO-Orlando International) to Mexico City (MEX-Mexico City Intl.)
Airline confirmation: MEX456 (Aeromexico)
Sat, Mar 5, 1:49pm - 4:40pm 3h 51m flight duration"""


def parsed(body):
    return parse_email(plain_text=body,html="",attachments=[],user_name="Alex Avery",aliases=[],
                       received_at="Sat, 19 Feb 2022 12:00:00 +0000", from_email="itinerary@expediamail.com",
                       subject="Expedia flight purchase confirmation - example").flights


def test_multi_carrier_receipt_keeps_each_labeled_reference():
    rows = parsed(ROWS)
    assert [(f.flight_number,f.pnr,f.pnr_aliases) for f in rows] == [("NK123","SPT123",[]),("AM654","MEX456",[])]


@pytest.mark.parametrize("body", [ROWS.replace("Airline confirmation: MEX456 (Aeromexico)", ""),
    ROWS + "\nAirline confirmation: NEW234 (Aeromexico)"])
def test_incomplete_or_conflicting_carrier_reference_retains_the_fact_for_review(body):
    rows = parsed(body)
    assert [(f.flight_number,f.pnr,f.pnr_aliases) for f in rows] == [("NK123","SPT123",[]),("AM654",None,[])]
    assert rows[1].force_review


@pytest.mark.parametrize("different_reference", [True,False])
def test_changed_clocks_without_a_proven_revision_cannot_overwrite_or_duplicate(account, different_reference):
    db,user=account
    original=flight()
    apply(db,user,[original],source="saved",received="2025-01-01T10:00:00Z")
    old=db.query(Segment).one()
    identity=(old.id,old.trip_id,old.dep_time,old.arr_time)
    incoming=flight(pnr="OTHER2" if different_reference else original.pnr, departure="2025-02-23T15:50:00Z",arrival="2025-02-23T17:10:00Z")
    incoming.source_leg={"booking_references":{"primary":incoming.pnr,"aliases":[],"basis":"carrier_labeled_purchase_receipt"}}
    before=db.query(ItineraryHistory).count()
    for _ in range(2):
        result=apply(db,user,[deepcopy(incoming)],source="purchase",received="2025-01-02T10:00:00Z")
        assert result.build.held == 1 and result.build.inserted == 0
        row=db.query(Segment).one()
        assert (row.id,row.trip_id,row.dep_time,row.arr_time)==identity
        assert db.query(Trip).count()==1 and db.query(ItineraryHistory).count()==before
        assert db.query(BookingObservation).filter_by(source_message_id="purchase").count()==1
