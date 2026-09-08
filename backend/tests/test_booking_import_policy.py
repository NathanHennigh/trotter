"""Cancellation wording and event time must not erase confirmed travel."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, BookingCancellation, BookingObservation, MessageStatus, Segment, User
from app.services.booking_import import _cancellation_intent, apply_booking_message, booking_event_time
from app.services.parser import ParsedFlight, ParseResult


@pytest.mark.parametrize("subject", [
    "Your trip is not canceled", "Flight cancellation request received",
    "Your booking cancellation was denied", "Flight cancellation pending",
    "Your reservation might be canceled", "Re: Your trip was canceled",
])
def test_nonfinal_or_quoted_subject_does_not_cancel(subject):
    assert not _cancellation_intent(subject, "Your confirmed travel details are below.")


@pytest.mark.parametrize("text", [
    "If\nyour flight is canceled, contact support.",
    "When\nyour booking is canceled, a fee may apply.",
    "Your flight is not canceled.",
    "Your flight may be canceled.",
    "On Tuesday, Airline wrote:\nYour flight was canceled.",
])
def test_policy_html_line_breaks_and_quotes_do_not_cancel(text):
    assert not _cancellation_intent("Flight confirmation", text)


@pytest.fixture
def active_booking():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as db:
        user = User(name="Alex Avery", email="alex@example.test")
        db.add(user)
        db.flush()
        start = datetime(2025, 2, 18, 12, tzinfo=timezone.utc)
        flights = [
            ParsedFlight("IAH", "DCA", start, start + timedelta(hours=3), airline="UA", flight_number="UA1685", pnr="CAN123", ownership="self"),
            ParsedFlight("DCA", "IAH", start + timedelta(days=3), start + timedelta(days=3, hours=3), airline="UA", flight_number="UA1381", pnr="CAN123", ownership="self"),
        ]
        parsed = ParseResult(flights=flights)
        apply_booking_message(db, user.id, parsed, source_message_id="confirmed",
                              subject="Booking confirmation", received_at="2025-01-20T12:00:00Z")
        assert db.query(Segment).count() == 2
        yield db, user, parsed
    engine.dispose()


@pytest.mark.parametrize("subject,text,received", [
    ("Fwd: Your trip was canceled", "Forwarded message\nYour trip was canceled.", "2025-02-01T12:00:00Z"),
    ("Your trip was canceled", "Your trip was canceled.", None),
])
def test_missing_cancellation_time_holds_evidence_and_keeps_existing_rows(active_booking, subject, text, received):
    db, user, parsed = active_booking
    outcome = apply_booking_message(db, user.id, parsed, source_message_id="uncertain-time",
                                    subject=subject, plain_text=text, received_at=received)
    assert outcome.status == MessageStatus.REVIEW_REQUIRED
    assert outcome.review_reason == "ambiguous_cancellation_time"
    assert db.query(Segment).count() == 2
    assert db.query(BookingCancellation).count() == 0
    assert db.query(BookingObservation).count() == 4


@pytest.mark.parametrize("subject,text", [
    ("Only your outbound flight was canceled", "Your outbound flight was canceled. Return flight remains confirmed."),
    ("Passenger cancellation for your booking", "Your booking for passenger Morgan Lane was canceled."),
    ("Your flight UA1685 was canceled", "Your flight UA1685 was canceled."),
])
def test_partial_cancellation_without_proven_dated_leg_holds_entire_message(active_booking, subject, text):
    db, user, parsed = active_booking
    outcome = apply_booking_message(db, user.id, parsed, source_message_id="partial",
                                    subject=subject, plain_text=text, received_at="2025-02-01T12:00:00Z")
    assert outcome.review_reason == "ambiguous_cancellation_scope"
    assert db.query(Segment).count() == 2
    assert db.query(BookingCancellation).count() == 0


def test_explicit_flight_number_and_travel_date_cancel_only_that_leg(active_booking):
    db, user, parsed = active_booking
    outcome = apply_booking_message(db, user.id, parsed, source_message_id="dated-leg",
        subject="Your flight UA1685 on February 18, 2025 was canceled",
        received_at="2025-02-01T12:00:00Z")
    assert outcome.canceled == 1
    assert [segment.flight_number for segment in db.query(Segment)] == ["UA1381"]
    cancellation = db.query(BookingCancellation).one()
    assert len(cancellation.scopes) == 1
    assert cancellation.scopes[0]["flight_number"] == "UA1685"


def test_reply_subject_cannot_reapply_old_cancellation(active_booking):
    db, user, parsed = active_booking
    outcome = apply_booking_message(db, user.id, parsed, source_message_id="reply",
        subject="Re: Your trip was canceled", plain_text="Thanks, my current booking is fine.",
        received_at="2025-02-01T12:00:00Z")
    assert not outcome.is_cancellation
    assert db.query(Segment).count() == 2
    assert db.query(BookingCancellation).count() == 0


def test_nested_forward_cannot_claim_the_outer_forward_date_as_original():
    assert booking_event_time("2025-03-01T12:00:00Z", "Fwd: Fwd: Receipt", """
---------- Forwarded message ---------
Date: Fri, 7 Feb 2025 20:00:00 +0000
---------- Forwarded message ---------
Date: Wed, 1 Jan 2025 20:00:00 +0000
""") is None
