"""Sanitized regressions for complete booking cards and lossy repeated cells."""
from html import escape

import pytest

from app.services.parser import parse_email


def parse(body, *, html=False, sender="Travel <travel@example.test>", subject="Your flight itinerary"):
    return parse_email(html="".join(f"<div>{escape(line)}</div>" for line in body.splitlines()) if html else "",
        plain_text="" if html else body, attachments=[], user_name="Alex Avery", aliases=["Alex Jordan Avery"],
        received_at="Fri, 10 Jul 2025 12:00:00 +0000", from_email=sender, subject=subject)


def local(flight):
    p = flight.time_provenance
    return flight.flight_number, flight.dep_airport, flight.arr_airport, p["departure"]["local"], p["arrival"]["local"]


def test_carrier_confirmation_table_does_not_alias_separate_itineraries():
    body = """Your confirmation codes
United
UAL123
JetBlue
JBL456
Capital One Travel
H-AGENCY
Manage Your Trip
You're flying with multiple itineraries.
July 12, 2025
United - UA123
Houston
IAH
2:48 p.m.
Washington, D.C.
DCA
6:45 p.m.
July 14, 2025
JetBlue - B6456
Washington, D.C.
DCA
3:00 p.m.
Orlando
MCO
5:40 p.m.
Booking reference: UAL123
Confirmation code: JBL456
"""
    result = parse(body, html=True)
    assert [(flight.flight_number, flight.pnr, flight.pnr_aliases) for flight in result.flights] == [
        ("UA123", "UAL123", []), ("B6456", "JBL456", [])]
    assert all(flight.source_leg["booking_references"]["primary"] == flight.pnr for flight in result.flights)


@pytest.mark.parametrize("html", [False, True])
def test_labeled_agency_cards_keep_individual_duration_and_clocks(html):
    body = """Passengers:
Alex Jordan Avery (Adult), E-ticket 0060000000001
Saturday, July 12, 2025
Delta Air Lines - Dallas to Los Angeles
Airline Confirmation #: DLT123
From:
DFW
Dallas, TX, US
06:15 AM
To:
LAX
Los Angeles, CA, US
07:25 AM
Flight Number:
DL 439
Operated by Delta Air Lines
Duration:
03H 10M, Non-Stop
Saturday, July 12, 2025
Delta Air Lines - Los Angeles to Anchorage
Airline Confirmation #: DLT123
From:
LAX
Los Angeles, CA, US
11:10 AM
To:
ANC
Anchorage, AK, US
03:26 PM
Flight Number:
DL 487
Operated by Delta Air Lines
Duration:
05H 16M, Non-Stop
"""
    result = parse(body, html=html)
    assert [local(f) for f in result.flights] == [
        ("DL439", "DFW", "LAX", "2025-07-12T06:15:00", "2025-07-12T07:25:00"),
        ("DL487", "LAX", "ANC", "2025-07-12T11:10:00", "2025-07-12T15:26:00")]
    assert all(f.pnr == "DLT123" and not getattr(f, "force_review", False) for f in result.flights)
    assert all(f.time_provenance["date_evidence"]["status"] == "verified" for f in result.flights)
    # An incomplete first card must never borrow the next card's arrival clock.
    partial = parse(body.replace("07:25 AM\n", ""), html=html)
    assert [f.flight_number for f in partial.flights] == ["DL487"]


@pytest.mark.parametrize("html", [False, True])
def test_schedule_cards_preserve_repeated_carrier_and_split_airports(html):
    body = """Flight Itinerary Change
Delta Air Lines:
DLT123
One Way
8h 26m
1 Stop
Delta
439
Operated by
Delta
Sat, Jul 12, 2025
6:15am
Dallas, TX (
DFW
)
7:25am
Los Angeles, CA (
LAX
)
Your Seats:
23F
Delta
487
Operated by
Delta
Sat, Jul 12, 2025
11:10am
Los Angeles, CA (
LAX
)
3:26pm
Anchorage, AK (
ANC
)
Your Seats:
27A
RECORD LOCATORS
Delta Air Lines
DLT123
TRAVELERS
Passenger 1:
Alex Jordan Avery
Ticket Number:
0060000000001
"""
    result = parse(body, html=html)
    assert [f.flight_number for f in result.flights] == ["DL439", "DL487"]
    assert all(f.pnr == "DLT123" for f in result.flights)
    assert [f.time_provenance["arrival"]["local"] for f in result.flights] == [
        "2025-07-12T07:25:00", "2025-07-12T15:26:00"]


OVERVIEW = """Flight overview
Travel dates
3/3/2023
Confirmation
SPT123 (Spirit Airlines)
Booking ID
SPT123
Departure
Fri, Mar 3
Spirit Airlines 360
Dallas (DFW)
2:01pm
Fort Lauderdale (FLL)
5:46pm
2h 45m duration
5h 54m stop Fort Lauderdale (FLL)
Spirit Airlines 435
Fort Lauderdale (FLL)
11:40pm
Managua (MGA)
1:22am
+1 day
Arrives on Mar 4, 2023
2h 42m duration
Total duration
11h 21m
Flight overview
Travel dates
3/12/2023
Confirmation
UNT123 (United)
Booking ID
AGY123
Ticket #
0160000000001 (Alex Avery)
Return
Sun, Mar 12
United 1433
Managua (MGA)
1:15pm
Houston (IAH)
5:41pm
3h 26m duration
4h 16m stop Houston (IAH)
United 1636
Houston (IAH)
9:57pm
Terminal:
C
Dallas (DFW)
11:07pm
1h 10m duration
Total duration
8h 52m
Traveler(s)
Alex Avery
Price summary
"""


@pytest.mark.parametrize("html", [False, True])
def test_overview_bookings_keep_dates_references_and_ticket_holder_local(html):
    result = parse(OVERVIEW, html=html)
    assert [f.flight_number for f in result.flights] == ["NK360", "NK435", "UA1433", "UA1636"]
    assert [f.pnr for f in result.flights] == ["SPT123", "SPT123", "UNT123", "UNT123"]
    assert [f.pnr_aliases for f in result.flights] == [[], [], ["AGY123"], ["AGY123"]]
    assert result.flights[0].time_provenance["arrival"]["local"] == "2023-03-03T17:46:00"
    assert result.flights[1].time_provenance["arrival"]["local"] == "2023-03-04T01:22:00"
    assert all(f.ownership == "self" for f in result.flights[2:])
    assert all(not any(e["source"] == "booking_ticket_holder" and e["applies"] for e in f.passenger_evidence)
               for f in result.flights[:2])
    assert all(not getattr(f, "force_review", False) for f in result.flights)


def test_overview_missing_arrival_does_not_borrow_next_flight_endpoint():
    result = parse(OVERVIEW.replace("Fort Lauderdale (FLL)\n5:46pm\n", ""))
    assert [f.flight_number for f in result.flights] == ["NK435", "UA1433", "UA1636"]


def test_incomplete_recognized_booking_cannot_fall_back_to_unbounded_extraction():
    body = """Flight overview
Travel dates
3/3/2023
Confirmation
SPT123 (Spirit Airlines)
Spirit Airlines 360
Dallas (DFW)
2:01pm
Fort Lauderdale (FLL)
Total duration
2h 45m
"""
    assert parse(body).flights == []
    card = """Saturday, July 12, 2025
Airline Confirmation #: DLT123
From:
DFW
06:15 AM
To:
LAX
Flight Number:
DL 439
Duration:
03H 10M
"""
    assert parse(card).flights == []


@pytest.mark.parametrize("html", [False, True])
def test_southwest_complete_reminder_never_repeats_dates_or_adds_sparse_clock(html):
    body = """Southwest Airlines
February 16
DAL
ONT
Dallas (Love) to Ontario
Full itinerary
Confirmation #
SWT123
PASSENGER
Alex Avery
Your complete itinerary
Flight :
Friday 02/16/2024
FLIGHT
# 40
DEPARTS
DAL 5:45
PM
Dallas (Love)
ARRIVES
ONT 7:05
PM
Ontario
"""
    result = parse(body, html=html)
    assert [local(f) for f in result.flights] == [
        ("WN40", "DAL", "ONT", "2024-02-16T17:45:00", "2024-02-16T19:05:00")]


def test_named_sparse_southwest_banner_remains_held_with_noncanonical_clocks():
    result = parse("""Southwest Airlines
January 16
PNS
TPA
Pensacola to Tampa
Full itinerary
Confirmation # SWT123
PASSENGER
Alex Avery
""")
    assert len(result.flights) == 1
    flight = result.flights[0]
    assert flight.force_review
    assert flight.time_provenance["status"] == "needs_review"
    assert flight.time_provenance["reason"] == "missing_explicit_flight_clocks"


def test_southwest_whitespace_header_bounds_incomplete_first_leg():
    body = """Southwest Airlines
Confirmation # SWT123
Your itinerary
Flight :
Friday 02/16/2024
FLIGHT
# 40
DEPARTS
DAL 5:45 PM
Flight :
Tuesday 02/20/2024
FLIGHT
# 3704
DEPARTS
SAN 3:40 PM
ARRIVES
DAL 8:30 PM
"""
    result = parse(body)
    assert [f.flight_number for f in result.flights] == ["WN3704"]


SOUTHWEST_CONNECTION = """Southwest Airlines
Confirmation # SWT123
PASSENGER
Alex Avery
Your itinerary
Flight:
Sunday 08/16/2026
FLIGHT
# 0185
DEPARTS
DAL 07:55
AM
Dallas (Love)
ARRIVES
LAS 08:40
AM
Las Vegas
Change planes
FLIGHT
# 4739
DEPARTS
LAS 09:25
AM
Las Vegas
ARRIVES
KOA 12:40
PM
Kona
"""


@pytest.mark.parametrize("html", [False, True])
def test_southwest_connections_preserve_each_repeated_meridiem(html):
    result = parse(SOUTHWEST_CONNECTION, html=html)
    assert [local(f) for f in result.flights] == [
        ("WN185", "DAL", "LAS", "2026-08-16T07:55:00", "2026-08-16T08:40:00"),
        ("WN4739", "LAS", "KOA", "2026-08-16T09:25:00", "2026-08-16T12:40:00")]
    assert all(f.pnr == "SWT123" and not getattr(f, "force_review", False) for f in result.flights)


@pytest.mark.parametrize("html", [False, True])
@pytest.mark.parametrize("missing", ["LAS 09:25\nAM", "KOA 12:40\nPM"])
def test_southwest_missing_meridiem_is_not_inferred_from_other_endpoint(html, missing):
    result = parse(SOUTHWEST_CONNECTION.replace(missing, missing.splitlines()[0]), html=html)
    assert [f.flight_number for f in result.flights] == ["WN185"]


@pytest.mark.parametrize("html", [False, True])
def test_southwest_cards_with_no_explicit_meridiem_cannot_fall_back_to_guessed_clocks(html):
    body = SOUTHWEST_CONNECTION.replace("\nAM\n", "\n").replace("\nPM\n", "\n")
    assert parse(body, html=html).flights == []


@pytest.mark.parametrize("missing", ["ARRIVES\nLAS 08:40\nAM\n", "Sunday 08/16/2026\n"])
def test_southwest_incomplete_card_cannot_borrow_endpoint_or_date(missing):
    body = SOUTHWEST_CONNECTION.replace(missing, "")
    result = parse(body)
    assert [f.flight_number for f in result.flights] == (["WN4739"] if missing.startswith("ARRIVES") else [])


@pytest.mark.parametrize("missing", [None, "DAL 07:55\nAM", "LAS 08:40\nAM", "all"])
def test_compact_southwest_receipt_cannot_borrow_the_next_flight_clocks(missing):
    body = SOUTHWEST_CONNECTION
    if missing == "all":
        body = body.replace("\nAM\n", "\n").replace("\nPM\n", "\n")
    elif missing:
        body = body.replace(missing, missing.splitlines()[0])
    result = parse(body.replace("\n", " "))
    expected = [
        ("WN185", "DAL", "LAS", "2026-08-16T07:55:00", "2026-08-16T08:40:00"),
        ("WN4739", "LAS", "KOA", "2026-08-16T09:25:00", "2026-08-16T12:40:00")]
    assert [local(f) for f in result.flights] == ([] if missing == "all" else expected[1:] if missing else expected)


def test_numbered_round_trip_preserves_duplicate_endpoint_dates():
    body = """Confirmation Number: UNT123
Flight 1 of 2 UA2656
Class: United Economy
Wed, Aug 05, 2026
Wed, Aug 05, 2026
06:26 PM
09:47 PM
Orange County, CA, US (SNA)
Denver, CO, US (DEN)
Flight 2 of 2 UA725
Class: United Economy
Sun, Aug 09, 2026
Sun, Aug 09, 2026
08:32 PM
10:01 PM
Denver, CO, US (DEN)
Orange County, CA, US (SNA)
Traveler Details
AVERY/ALEX
"""
    result = parse(body, html=True, subject="Your reservation has been canceled")
    assert [f.flight_number for f in result.flights] == ["UA2656", "UA725"]
    assert [f.time_provenance["departure_local_date"] for f in result.flights] == ["2026-08-05", "2026-08-09"]


@pytest.mark.parametrize("separator", [".", "·", "•", "|"])
def test_alaska_card_separators_and_tracking_links_are_not_references(separator):
    body = f"""Alaska Airlines
Confirmation code:
https://example.test/tracking/123
ASK123
Trip details
Flight 1 {separator} Mon Oct 20
Alaska Airlines
AS 3492 {separator} Embraer 175
SNA
SFO
Santa Ana
San Francisco
5:47 PM
7:19 PM
Mon Oct 20
Mon Oct 20
Traveler(s):
Alex Avery
15C {separator} Class: S COACH
Flight 2 {separator} Thu Oct 23
Alaska Airlines
AS 269 {separator} Boeing 737
SFO
SNA
San Francisco
Santa Ana
5:04 PM
6:41 PM
Thu Oct 23
Thu Oct 23
Traveler(s):
Alex Avery
29C {separator} Class: L COACH
"""
    result = parse(body)
    assert [f.flight_number for f in result.flights] == ["AS3492", "AS269"]
    assert all(f.pnr == "ASK123" and not f.pnr_aliases for f in result.flights)
    assert [f.time_provenance["departure_local_date"] for f in result.flights] == ["2025-10-20", "2025-10-23"]


def test_seat_assignment_cards_keep_explicit_carrier_and_agency_pair():
    body = """Passenger(s):
AVERY/ALEX
United Confirmation Code:
UNT123
Expedia Confirmation Code:
AGY123
Sunday, Mar 12, 2023
Flight Details
United
Flight Number
: UA1433
From
: Managua (MGA-Augusto C. Sandino Intl.)
To
: Houston, TX (IAH-George Bush Intercontinental)
Status
: CONFIRMED
Depart
:
1:15 PM
Arrive
:
5:41 PM
Class
: Coach
"""
    result = parse(body, html=True)
    assert [local(f) for f in result.flights] == [
        ("UA1433", "MGA", "IAH", "2023-03-12T13:15:00", "2023-03-12T17:41:00")]
    assert result.flights[0].pnr == "UNT123"
    assert result.flights[0].pnr_aliases == ["AGY123"]
