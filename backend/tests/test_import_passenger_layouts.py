"""Minimal, anonymized versions of independently audited receipt layouts."""
from datetime import datetime, timezone

import pytest

from app.services.parser import ParsedFlight, parse_email, _extract_pnr, _extract_pnr_aliases
from app.services.passenger_identity import apply_passenger_identity, full_names_match


def identify(text, *, pnrs=("BOOK12",), user="Alex Jordan Avery"):
    flights = [ParsedFlight("IAH", "DCA", datetime(2025, 1, 1, tzinfo=timezone.utc),
               datetime(2025, 1, 1, 3, tzinfo=timezone.utc), pnr=pnr, flight_number=f"UA{index+10}")
               for index, pnr in enumerate(pnrs)]
    apply_passenger_identity(flights, html="", plain_text=text, user_name=user, aliases=[])
    return flights


@pytest.mark.parametrize("printed", ["Avery,Alexjordan", "AVERY/ALEXJORDAN", "Avery, Alex Jordan"])
def test_comma_and_slash_airline_concatenation_is_exact(printed):
    assert full_names_match(printed, "Alex Jordan Avery")
    if "Alex Jordan" not in printed:
        assert not full_names_match(printed, "Alex Avery")
    assert not full_names_match(printed, "Alexandra Jordan Avery")
    assert not full_names_match(printed, "Alex Casey Avery")


def test_numbered_frontier_manifest_survives_loyalty_separators():
    flights = identify("""Confirmation code: BOOK12
PASSENGERS
Subtotal: $0.00
ADULT(S)
1 - Morgan Avery
Not a FRONTIER Milessm Member? Sign Up!
<https://example.test/signup>
2 - Alex Jordan Avery
Not a FRONTIER Milessm Member? Sign Up!
3 - Casey Avery
BUNDLES
PAYMENT: Another Payer
""")
    assert flights[0].passenger_names == ["Morgan Avery", "Alex Jordan Avery", "Casey Avery"]
    assert flights[0].ownership == "self"


@pytest.mark.parametrize("label", ["Passenger name(s)", "Passenger names", "Passenger Name"])
def test_lifemiles_named_passenger_label(label):
    result = identify(f"Booking reference: BOOK12\n{label}:\nAlex Jordan Avery\nFlight details")
    assert result[0].ownership == "self"
    assert result[0].passenger_names == ["Alex Jordan Avery"]


def test_repeated_alaska_traveler_seat_metadata_preserves_second_passenger():
    result = identify("""Traveler(s)
Morgan Avery
Seat: † Class: T (Coach)
Alex Jordan Avery
Seat: † Class: T (Coach)
Confirmation Code: BOOK12
American Flight UA10
""")
    assert result[0].passenger_names == ["Morgan Avery", "Alex Jordan Avery"]
    assert result[0].ownership == "self"


FARE = """Your confirmation codes
United
BOOK12
Frontier
BOOK34
Fare Details
Morgan Avery
Base Fare: $120.00
Taxes and Fees: $40.00
Alex Jordan Avery
Base Fare: $120.00
Taxes and Fees: $40.00
Total US$320.00
Payment Info
Unrelated Payer
"""


def test_combined_capital_one_named_fares_cover_only_explicit_listed_bookings():
    flights = identify(FARE, pnrs=("BOOK12", "BOOK34"))
    assert all(f.ownership == "self" for f in flights)
    assert all(f.passenger_names == ["Morgan Avery", "Alex Jordan Avery"] for f in flights)
    incomplete = identify(FARE.replace("BOOK34", "NOTOUR"), pnrs=("BOOK12", "BOOK34"))
    assert all(f.ownership == "unknown" for f in incomplete)


def test_fare_payer_and_greeting_cannot_establish_ownership():
    result = identify(FARE, user="Unrelated Payer")
    assert result[0].ownership == "other"
    no_fares = identify("Dear Alex Jordan Avery\nFare Details\nAlex Jordan Avery\nPayment Info\nAlex Jordan Avery")
    assert no_fares[0].ownership == "unknown"


def test_passenger_footer_and_route_are_not_names():
    result = identify("Passenger notices\notherwise advises the travel promoter in writing\nPassenger: BNA to IAH")
    assert result[0].passenger_names == []


def test_eva_local_boarding_table_preserves_traveler_and_international_dates():
    result = parse_email(html="", plain_text="""Check-in Information：
Booking Reference：EVAB12
Name：Avery, Alexjordan
Segment
Flight No.
Departure (Local Time)
Arrival (Local Time)
HOUSTON - TAIPEI (TAOYUAN)
BR051
2025/04/26 01:00
2025/04/27 06:30
Notice
""", attachments=[], user_name="Alex Jordan Avery", aliases=[])
    assert len(result.flights) == 1
    f = result.flights[0]
    assert (f.flight_number, f.dep_airport, f.arr_airport, f.ownership) == ("BR51", "IAH", "TPE", "self")
    assert f.dep_time.isoformat() == "2025-04-26T06:00:00+00:00"
    assert f.arr_time.isoformat() == "2025-04-26T22:30:00+00:00"
    assert f.time_provenance["arrival"]["local"] == "2025-04-27T06:30:00"


def test_ba_eticket_retains_immediately_preceding_operating_flight_number():
    text = """Your Itinerary
AA1555
American Airlines | Economy | Confirmed
16 Nov 2023
21:20
Dallas Ft Worth International
16 Nov 2023
23:13
Nashville International
Passenger
MADAME ALEX JORDAN AVERY
"""
    result = parse_email(html="", plain_text=text, attachments=[], user_name="Alex Jordan Avery", aliases=[])
    assert len(result.flights) == 1
    assert result.flights[0].flight_number == "AA1555"
    assert result.flights[0].ownership == "self"


def test_pdf_issued_ticket_table_extracts_both_passengers_and_actual_times():
    text = """E-Ticket Itinerary & Receipt
Your Booking Reference
QAN123
Passenger Ticket Information
Passenger Name Frequent Flyer No. Ticket No. Issued Ticket Total
Mr Morgan Avery QF 1234567890
Frequent Flyer Bronze
081-1111111111 25 May 25 5.60
Mrs Alex Jordan Avery 081-2222222222 25 May 25 5.60
Your Itinerary
Date Flight Number Departing Arriving Status Flight Information
18 Jun 25 AA 2064 Houston George Bush
Intercontinental Ap
6:28PM
Terminal A
Chicago O'Hare
9:23PM
18 Jun 25
Terminal 3
Economy
Confirmed
Est journey Time: 02:55
Payment Details
Unrelated Payer
"""
    result = parse_email(html="", plain_text=text, attachments=[], user_name="Alex Jordan Avery", aliases=[])
    assert len(result.flights) == 1
    f = result.flights[0]
    assert (f.flight_number, f.dep_airport, f.arr_airport, f.ownership) == ("AA2064", "IAH", "ORD", "self")
    assert f.dep_time.isoformat() == "2025-06-18T23:28:00+00:00"
    assert f.arr_time.isoformat() == "2025-06-19T02:23:00+00:00"
    assert f.passenger_names == ["Mr Morgan Avery", "Mrs Alex Jordan Avery"]


def test_sun_country_delay_has_flight_facts_but_greeting_is_not_traveler():
    text = """Sun Country Airlines
Reservation code: SUN123
Dear Alex Jordan Avery, one or more flights has been affected by a schedule change.
SY739 | Flight Delayed 1h 45m
Nonstop
10:00AM
8:15AM
Dallas/Fort Worth (DFW)
June 19, 2026
| |
4h 50m
3:30PM
2:05PM
Punta Cana (PUJ)
June 19, 2026
CANCEL FLIGHT
"""
    result = parse_email(html="", plain_text=text, attachments=[], user_name="Alex Jordan Avery", aliases=[])
    assert len(result.flights) == 1
    f = result.flights[0]
    assert f.ownership == "unknown"
    assert f.passenger_names == []
    assert f.dep_time.isoformat() == "2026-06-19T15:00:00+00:00"
    assert f.arr_time.isoformat() == "2026-06-19T19:30:00+00:00"


def test_two_boarding_passes_never_borrow_each_others_names():
    def boarding(name, pnr, number):
        return f"Check-in Information:\nBooking Reference:{pnr}\nName:{name}\nSegment\nFlight No.\nDeparture (Local Time)\nArrival (Local Time)\nHOUSTON - TAIPEI (TAOYUAN)\n{number}\n2025/04/26 01:00\n2025/04/27 06:30\n"
    result = parse_email(html="", plain_text=boarding("Avery,Alexjordan", "EVAB12", "BR051") + boarding("Blake,Morgan", "EVAC34", "BR053"),
                         attachments=[], user_name="Alex Jordan Avery", aliases=[])
    assert {(f.flight_number, f.ownership) for f in result.flights} == {("BR51", "self"), ("BR53", "other")}


def test_capital_one_airline_reference_beats_prose_and_agency_code():
    text = "View your booking within the airline's website.\nCapital One Travel confirmation code: H-M-EXAMPLE\nHere's your Frontier confirmation code: *FRT123*".upper()
    assert _extract_pnr(text) == "FRT123"
    assert "WITHIN" not in _extract_pnr_aliases(text, primary="FRT123")
