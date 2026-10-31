"""Booking aliases need reference evidence, not words from a receipt's footer."""
from datetime import datetime, timezone

import pytest

from app.services.parser import _extract_pnr_aliases, parse_email


@pytest.mark.parametrize("body", [
    "You have until the next business day to cancel this booking without charge.",
    "Purchase Confirmation\nThank you for your purchase with us!",
    "Access your booking\nFlights subtotal: $84.98",
    "Manage my booking\nManage my booking\nStill need help?",
    "Your booking is still available in the app.",
    "Your confirmation shows the flights below.",
    "Booking\nFLIGHTS\nSubtotal: $84.98",
    "Confirmation\nTHANK\nYou for booking with us.",
])
def test_receipt_prose_does_not_supply_booking_aliases(body):
    assert _extract_pnr_aliases(body.upper(), primary="TEST01") == []


@pytest.mark.parametrize("reference", ["WITHOUT", "THANK", "FLIGHTS", "MANAGE", "STILL", "ABCDEF"])
@pytest.mark.parametrize("label", ["Booking reference: ", "Confirmation code is: ", "Record locator "])
def test_explicitly_labeled_all_letter_references_are_valid(reference, label):
    assert _extract_pnr_aliases((label + reference).upper(), primary="TEST01") == [reference]


@pytest.mark.parametrize("label", ["Booking: ", "Booking # ", "Confirmation: ", "Confirmation # "])
def test_short_reference_field_requires_a_label_value_separator(label):
    assert _extract_pnr_aliases(label + "REF123", primary="TEST01") == ["REF123"]


def test_agency_and_airline_record_locators_remain_linked():
    body = "Itinerary for Record Locator BK1234\nUAL Record Locator RF1234\nAirline Confirmation #: RF1234"
    assert _extract_pnr_aliases(body.upper(), primary="RF1234") == ["BK1234"]


def test_carrier_confirmation_table_keeps_only_actual_codes():
    body = """Your confirmation codes
Spirit
TEST01
Capital One Travel
H-TEST01
Booking reference: OTHER1
You may cancel this booking without charge.
Purchase Confirmation
Thank you for your purchase.
Manage my booking
Still need help?
"""
    assert _extract_pnr_aliases(body.upper(), primary="TEST01") == ["OTHER1"]


def test_named_two_leg_receipt_does_not_project_a_terms_word_as_an_alias():
    # Sanitized layout of a forwarded agency receipt: both named travelers
    # belong to the same Spirit itinerary; the footer is not another booking.
    body = """Your confirmation codes
Spirit
TEST01
Capital One Travel
H-TEST01
Outbound to Houston
Economy
February 23, 2025
Spirit - NK1651
Orlando
MCO
5:01 p.m.
1h 48m
Atlanta
ATL
6:49 p.m.
2h layover in Atlanta
Spirit - NK512
Atlanta
ATL
8:49 p.m.
2h 21m
Houston
IAH
10:10 p.m.
Fare Details
Jordan Avery
Base Fare: $100.00
Taxes and Fees: $20.00
Ticket #: 4870000000001
Alex Avery
Base Fare: $100.00
Taxes and Fees: $20.00
Ticket #: 4870000000002
Total US$240.00
Payment Info
Departing from the U.S.? You have until the next business day to cancel this booking without charge.
"""
    result = parse_email(html="", plain_text=body, attachments=[], user_name="Alex Avery", aliases=[],
        received_at=datetime(2025, 1, 16, tzinfo=timezone.utc),
        subject="View your flight details for your Houston trip",
        from_email="Capital One <capitalone@capitalonebooking.com>")
    assert [(flight.flight_number, flight.dep_airport, flight.arr_airport) for flight in result.flights] == [
        ("NK1651", "MCO", "ATL"), ("NK512", "ATL", "IAH")]
    assert all(flight.ownership == "self" and flight.pnr == "TEST01" for flight in result.flights)
    assert all(flight.pnr_aliases == [] for flight in result.flights)
