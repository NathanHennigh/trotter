"""Original header dates establish chronology only within an unambiguous forward."""
from datetime import datetime, timezone

import pytest

from app.services.booking_import import booking_event_time, booking_time_provenance, booking_time_text


RECEIVED = "2025-02-01T12:00:00Z"
DATE = "January 7, 2025 at 5:17:44 PM GMT+3"


def forwarded(date=DATE, prefix="> ", marker="Begin forwarded message:"):
    return "Sent from my phone\n\n" + marker + "\n\n" + "\n".join(prefix + value for value in [
        "From: Example Agency <receipt@example.test>", "Date: " + date,
        "To: Alex Taylor <alex@example.test>", "Subject: Your flight receipt",
        "Reply-To: receipt@example.test", "", "Your itinerary follows."])


@pytest.mark.parametrize("zone,expected", [
    ("GMT+3", "2025-01-07T14:17:44+00:00"),
    ("GMT-3", "2025-01-07T20:17:44+00:00"),
    ("UTC+05:30", "2025-01-07T11:47:44+00:00"),
    ("GMT+0530", "2025-01-07T11:47:44+00:00"),
    ("+0300", "2025-01-07T14:17:44+00:00"),
    ("-03:30", "2025-01-07T20:47:44+00:00"),
    ("UTC", "2025-01-07T17:17:44+00:00"),
    ("GMT", "2025-01-07T17:17:44+00:00"),
    ("EST", "2025-01-07T22:17:44+00:00"),
    ("PDT", "2025-01-08T00:17:44+00:00"),
])
def test_explicit_zones_have_correct_sign_and_preserved_original_literal(zone, expected):
    date = DATE.replace("GMT+3", zone)
    text = forwarded(date)
    assert booking_event_time(RECEIVED, "Fwd: Flight receipt", text).isoformat() == expected
    provenance = booking_time_provenance(RECEIVED, "Fwd: Flight receipt", text)
    assert provenance["kind"] == "forwarded"
    assert provenance["original_date"] == date
    assert provenance["event_at"] == provenance["earliest"] == provenance["latest"] == expected
    assert provenance["forwarded_header"]["quote_depth"] == 1


@pytest.mark.parametrize("prefix,marker", [("", "---------- Forwarded message ---------"), ("> ", "Begin forwarded message:"), ("> ", "> Begin forwarded message:")])
def test_one_consistent_quote_level_in_contiguous_header_is_allowed(prefix, marker):
    assert booking_event_time(RECEIVED, "Fw: Receipt", forwarded(prefix=prefix, marker=marker)) == datetime(2025, 1, 7, 14, 17, 44, tzinfo=timezone.utc)


@pytest.mark.parametrize("date", [
    "January 7, 2025 at 5:17:44 PM", "January 7 at 5:17:44 PM GMT+3",
    "2025 at 5:17:44 PM GMT+3", "January 2025 at 5:17:44 PM GMT+3",
    "January 7, 2025 GMT+3", "January 7, 2025 at 5:17:44 PM IST",
    "January 7, 2025 at 5:17:44 PM GMT+15", "January 7, 2025 at 5:17:44 PM GMT+14:30",
    "January 7, 2025 at 5:17:44 PM GMT+03:99", "January 7, 2025 at 5:17:44 PM -0000",
    "January 7, 2025 at 5:17:44 PM -00:00", "January 7, 2025 at 5:17:44 PM GMT+3 UTC",
    "February 2, 2025 at 5:17:44 PM GMT+3",
    "Sunday, January 7, 2025 at 5:17:44 PM GMT+3",
])
def test_missing_ambiguous_invalid_or_future_date_cannot_order_a_booking(date):
    assert booking_event_time(RECEIVED, "Fwd: Receipt", forwarded(date)) is None
    assert booking_time_provenance(RECEIVED, "Fwd: Receipt", forwarded(date))["event_at"] is None


@pytest.mark.parametrize("text", [
    forwarded().replace("> Date:", "Date:"),
    forwarded().replace("> Subject:", ">> Subject:"),
    forwarded().replace("> Date:", "> Date: " + DATE + "\n> Date:"),
    forwarded().replace("> Date:", "> Unrelated body text\n> Date:"),
    forwarded().replace("> Date:", "> \n> Date:"),
    forwarded().replace("Begin forwarded message:", "The text says Begin forwarded message: after this"),
    forwarded().replace("> Subject: Your flight receipt", "> Subject: Re: Your flight receipt"),
    forwarded().replace("> Subject: Your flight receipt", "> Subject: Fwd: Your flight receipt"),
    forwarded().replace("> Subject: Your flight receipt", "> Subject: Fw: Your flight receipt"),
    forwarded() + "\nBegin forwarded message:\nDate: " + DATE,
    "On Tuesday, Example <example@example.test>\nwrote:\n" + forwarded(),
    forwarded() + "\nOn Tuesday, Example <example@example.test>\nwrote:\nAn older receipt",
    forwarded().replace("> To:", "> Sent: " + DATE + "\n> To:"),
    forwarded(prefix=">> "),
    forwarded().replace("> From:", "> From: " + "A" * 1600 + "\n> From:"),
])
def test_nested_inconsistent_or_non_header_dates_have_no_revision_authority(text):
    assert booking_event_time(RECEIVED, "Fwd: Receipt", text) is None


@pytest.mark.parametrize("subject", ["Re: Receipt", "Fwd: Fwd: Receipt", "Fwd: Re: Receipt"])
def test_reply_or_nested_forward_subject_is_unknown(subject):
    assert booking_event_time(RECEIVED, subject, forwarded()) is None


def test_later_body_date_cannot_replace_the_single_original_header():
    text = forwarded() + "\n> Date: January 20, 2025 at 5:00 PM GMT+3"
    assert booking_event_time(RECEIVED, "Fwd: Receipt", text) == datetime(2025, 1, 7, 14, 17, 44, tzinfo=timezone.utc)


@pytest.mark.parametrize("field", ["From", "Subject"])
@pytest.mark.parametrize("prefix", ["", "> "])
def test_missing_original_sender_or_subject_cannot_establish_any_time_interval(field, prefix):
    text = "\n".join(line for line in forwarded(prefix=prefix).splitlines() if not line.startswith(prefix + field + ":"))
    assert booking_event_time(RECEIVED, "Fwd: Receipt", text) is None
    result = booking_time_provenance(RECEIVED, "Fwd: Receipt", text.replace(" GMT+3", ""))
    assert result["kind"] == "forwarded_unknown" and result["event_at"] is None
    assert "earliest" not in result and "latest" not in result


def test_unknown_timezone_stays_an_interval_without_a_received_time_fallback():
    date = "January 7, 2025 at 5:17:44 PM"
    result = booking_time_provenance(RECEIVED, "Fwd: Receipt", forwarded(date))
    assert result["event_at"] is None and result["kind"] == "forwarded_timezone_unknown"
    assert result["original_date"] == date
    assert result["earliest"] == "2025-01-07T03:17:44+00:00"
    assert result["latest"] == "2025-01-08T05:17:44+00:00"


def test_missing_receipt_time_cannot_validate_a_future_original_header():
    assert booking_event_time(None, "Fwd: Receipt", forwarded()) is None


@pytest.mark.parametrize("wrapper", ["template", "noscript", "div hidden", 'div style="display:none"'])
def test_inert_html_forward_headers_cannot_establish_chronology(wrapper):
    text = forwarded(prefix="").replace("\n", "<br>")
    html = "<p>Weekly update</p><" + wrapper + ">" + text + "</" + wrapper.split()[0] + ">"
    assert booking_event_time(RECEIVED, "Fwd: Receipt", booking_time_text("", html)) is None


def test_nonforwarded_received_time_contract_is_unchanged():
    assert booking_event_time(RECEIVED, "Flight receipt", forwarded()).isoformat() == RECEIVED.replace("Z", "+00:00")
