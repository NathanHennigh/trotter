"""Cancellation authority follows the same visible HTML boundary as the schedule."""
import pytest

from app.models import BookingCancellation, Segment
from app.services.booking_import import apply_booking_message, _booking_lifecycle, visible_message_text
from app.services.parser import parse_email
from test_booking_import import session
from test_expedia_marked_clock_import import itinerary


RECEIPT = "<p>" + itinerary("original", passenger="AVERY/ALEX", pnr="TEST12").replace("\n", "</p><p>") + "</p>"


def apply(db, user, source, html, received):
    parsed = parse_email(html=html, plain_text="", attachments=[], user_name=user.name,
                         aliases=[], received_at=received, subject="Flight receipt")
    assert len(parsed.flights) == 1 and parsed.flights[0].ownership == "self"
    return apply_booking_message(db, user.id, parsed, source_message_id=source,
        subject="Flight receipt", html=html, received_at=received)


@pytest.mark.parametrize("wrapper", ["template", "noscript", "div hidden", 'div style="display:none"', 'div aria-hidden="true"'])
def test_inert_cancellation_does_not_cancel_a_visible_named_flight(session, wrapper):
    db, user = session
    apply(db, user, "receipt", RECEIPT, "2025-01-01T12:00:00Z")
    original = db.query(Segment).one().id
    html = RECEIPT + "<" + wrapper + ">Your flight was canceled.</" + wrapper.split()[0] + ">"
    result = apply(db, user, "hidden-notice", html, "2025-01-02T12:00:00Z")
    assert not result.is_cancellation and result.canceled == 0
    assert db.query(Segment).one().id == original
    assert db.query(BookingCancellation).count() == 0


@pytest.mark.parametrize("malformed", [False, True])
def test_visible_cancellation_in_explicit_body_keeps_its_authority(session, malformed):
    db, user = session
    apply(db, user, "receipt", RECEIPT, "2025-01-01T12:00:00Z")
    html = "<html><head><title>Receipt</title>" + ("" if malformed else "</head>")
    html += "<body>" + RECEIPT + "<p>Your flight was canceled.</p></body></html>"
    result = apply(db, user, "cancellation", html, "2025-01-02T12:00:00Z")
    assert result.is_cancellation and result.canceled == 1
    assert db.query(Segment).count() == 0
    assert db.query(BookingCancellation).count() > 0


DATED_RECEIPT = """Below you'll find your itinerary, important travel information, and trip receipt.
Confirmation # TEST12
Confirmation date: 01/07/2025
Passenger Alex Avery
Your itinerary
Payment information
Payment
January 7, 2025
Payment Amount
$11.20
"""


def test_visible_dated_receipt_preserves_confirmation_without_preheader():
    result = _booking_lifecycle("You're going to your destination!", DATED_RECEIPT, cancellation=False)
    assert result == {"version": 1, "kind": "confirmation", "can_reinstate": True}


@pytest.mark.parametrize("old,new", [
    ("Below you'll find your itinerary, important travel information, and trip receipt.", "Your upcoming trip"),
    ("Confirmation # TEST12", "Your account TEST12"),
    ("Confirmation date: 01/07/2025", "Confirmation date: 02/30/2025"),
    ("Confirmation date: 01/07/2025", ""),
    ("January 7, 2025", "January 8, 2025"),
    ("January 7, 2025", "January 7"),
    ("Payment Amount\n$11.20", "Estimated cost $11.20"),
    ("Confirmation # TEST12", "Confirmation # TEST12\nConfirmation # OTHER1"),
    ("Confirmation # TEST12", "Confirmation # TEST12-EXTRA"),
    ("Confirmation # TEST12", "Confirmation # TEST12/456"),
    ("Confirmation # TEST12", "Confirmation # TEST12_SUFFIX"),
])
def test_receipt_introduction_cannot_borrow_missing_or_conflicting_payment_context(old, new):
    result = _booking_lifecycle("Your trip", DATED_RECEIPT.replace(old, new), cancellation=False)
    assert result["kind"] == "unknown" and not result["can_reinstate"]


def test_operational_reminder_with_old_receipt_remains_operational():
    result = _booking_lifecycle("Check-in for your upcoming flight", DATED_RECEIPT, cancellation=False)
    assert result["kind"] == "operational_notice" and not result["can_reinstate"]


def test_hidden_receipt_introduction_cannot_establish_booking_confirmation():
    body = "<div hidden>" + DATED_RECEIPT.replace("\n", "<br>") + "</div><p>Weekly update</p>"
    result = _booking_lifecycle("Your trip", visible_message_text("", body), cancellation=False)
    assert result["kind"] == "unknown" and not result["can_reinstate"]
