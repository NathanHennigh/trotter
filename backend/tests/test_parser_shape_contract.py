from __future__ import annotations

import time

from app.services.parser import _extract_pnr, _extract_pnr_aliases, parse_email


def _parse(
    subject: str,
    body: str,
    *,
    sender: str = "test@example.com",
    received_at: str = "Tue, 01 Jan 2019 12:00:00 +0000",
):
    started = time.perf_counter()
    result = parse_email(
        html="",
        plain_text=body,
        attachments=[],
        user_name="",
        aliases=[],
        received_at=received_at,
        subject=subject,
        from_email=sender,
    )
    assert time.perf_counter() - started < 1.0
    return result


def _segments(result):
    return [
        (flight.flight_number, flight.dep_airport, flight.arr_airport, flight.pnr, flight.source)
        for flight in result.flights
    ]


def test_southwest_labeled_connections_keep_all_segments() -> None:
    body = """
    Southwest Airlines
    Confirmation # QYEAXO
    Your itinerary
    Flight 1:
    Thursday, 12/27/2018
    FLIGHT
    # 4184
    DEPARTS
    EWR 07:25
    AM
    ARRIVES
    STL 09:10
    AM
    Flight 2:
    Tuesday, 01/01/2019
    FLIGHT
    # 1783
    DEPARTS
    STL 08:30
    AM
    ARRIVES
    EWR 11:45
    AM
    """

    result = _parse("St. Louis trip (QYEAXO): itinerary.", body, sender="Southwest <ifly.southwest.com>")

    assert _segments(result) == [
        ("WN4184", "EWR", "STL", "QYEAXO", "shape_southwest_itinerary_blocks"),
        ("WN1783", "STL", "EWR", "QYEAXO", "shape_southwest_itinerary_blocks"),
    ]


def test_southwest_forwarded_markdown_lines_keep_return_segment() -> None:
    body = """
    ---------- Forwarded message ---------
    From: Southwest Airlines <ifly.southwest.com>
    Subject: 12/27 St. Louis trip (QYEAXO): Get prepared to fly!
    Your complete itinerary
    *Flight 1:* Thursday, 12/27/2018
    FLIGHT
    *# 4184*
    DEPARTS
    *EWR 7:25*AM
    New York/Newark
    ARRIVES
    *STL 9:10*AM
    St. Louis
    *Flight 2:* Tuesday 01/01/2019
    FLIGHT
    *# 1783*
    DEPARTS
    *STL 8:30*AM
    St. Louis
    ARRIVES
    *EWR 11:45*AM
    New York/Newark
    Confirmation # *QYEAXO*
    """

    result = _parse("Fwd: 12/27 St. Louis trip (QYEAXO): Get prepared to fly!", body, sender="David <gmail.com>")

    assert _segments(result) == [
        ("WN4184", "EWR", "STL", "QYEAXO", "shape_southwest_itinerary_blocks"),
        ("WN1783", "STL", "EWR", "QYEAXO", "shape_southwest_itinerary_blocks"),
    ]


def test_southwest_receipt_sections_keep_wn_airline_code() -> None:
    body = """
    Southwest Airlines
    Your itinerary
    Flight:
    Friday, 08/12/2022
    FLIGHT
    # 0018
    DEPARTS
    HOU 10:30
    AM
    Houston (Hobby)
    ARRIVES
    DAL 11:40
    AM
    Dallas (Love)
    Confirmation # 4JD5M8
    """

    result = _parse("Your Dallas trip (4JD5M8)", body, sender="Southwest <ifly.southwest.com>")

    assert _segments(result) == [
        ("WN18", "HOU", "DAL", "4JD5M8", "shape_southwest_itinerary_blocks"),
    ]


def test_alaska_trip_details_keep_every_connection() -> None:
    body = """
    Alaska Airlines Reservation
    Confirmation code:
    KONA26
    Trip details

    Flight 1 · Sat Aug 22
    Alaska Airlines
    AS 259 · Boeing 737-900 Passenger
    KOA
    SEA
    Kona
    Seattle
    10:25 PM
    7:20 AM
    Sat Aug 22
    Sun Aug 23

    Next flight
    Flight 2 · Sun Aug 23
    Alaska Airlines
    AS 340 · Boeing 737-900 Passenger
    SEA
    DFW
    Seattle
    Dallas/Fort Worth
    8:40 AM
    2:46 PM
    Sun Aug 23
    Sun Aug 23
    Traveler(s):
    Nathan Hennigh
    """

    result = _parse(
        "Your flight is booked: KONA26 to Dallas/Fort Worth on 08/22/2026",
        body,
        sender="Alaska Airlines Reservation <reservation@email.alaskaair.com>",
        received_at="Wed, 22 Jul 2026 21:27:35 +0000",
    )

    assert _segments(result) == [
        ("AS259", "KOA", "SEA", "KONA26", "shape_alaska_trip_detail_blocks"),
        ("AS340", "SEA", "DFW", "KONA26", "shape_alaska_trip_detail_blocks"),
    ]


def test_alaska_partner_award_trip_details_use_operating_airline() -> None:
    body = """
    Alaska Airlines Reservation
    Confirmation code:
    ATL26X
    Trip details
    Flight 1 · Thu Aug 27
    American Airlines
    AA 1008 · Boeing 737-800 Passenger
    American Airlines
    DFW
    ATL
    Dallas/Fort Worth
    Atlanta
    12:10 PM
    3:20 PM
    Thu Aug 27
    Thu Aug 27
    """

    result = _parse(
        "Your flight is booked: ATL26X to Atlanta on 08/27/2026",
        body,
        sender="Alaska Airlines Reservation <reservation@email.alaskaair.com>",
        received_at="Tue, 11 Aug 2026 22:27:07 -0500",
    )

    assert _segments(result) == [
        ("AA1008", "DFW", "ATL", "ATL26X", "shape_alaska_trip_detail_blocks"),
    ]


def test_airline_confirmation_pnr_beats_generic_record_locator() -> None:
    text = """
    Itinerary for Record Locator BB8851
    UAL Record Locator OB5PJV
    Airline Confirmation #: OB5PJV
    """

    assert _extract_pnr(text.upper()) == "OB5PJV"
    assert _extract_pnr_aliases(text.upper(), primary="OB5PJV") == ["BB8851"]


def test_source_pnr_aliases_are_carried_on_parsed_flights() -> None:
    body = """
    Itinerary for Record Locator BB8851
    UAL Record Locator OB5PJV
    United Airlines Flight 3462
    2:20 pm Fri Dec 11 DFW 4:45 pm Fri Dec 11 ORD
    """

    result = _parse("Important Information Regarding Your Travel to Nairobi", body, sender="United <united.com>")

    assert result.flights
    assert result.flights[0].pnr == "OB5PJV"
    assert "BB8851" in result.flights[0].pnr_aliases


def test_emirates_checkin_route_blocks_parse_displayed_layover_itinerary() -> None:
    body = """
    Check in for your flight online
    Booking reference NT24IF
    JFK to DXB
    Saturday, December 31, 2016
    Depart 4:35 PM
    Arrive 2:05 PM
    EK 208
    DXB to NBO
    Sunday, January 1, 2017
    Depart 4:10 PM
    Arrive 8:20 PM
    EK 721
    """

    result = _parse("Check in online for your flight EK208 on 31 December", body, sender="Emirates <emirates.com>")

    assert _segments(result) == [
        ("EK208", "JFK", "DXB", "NT24IF", "shape_checkin_route_blocks"),
        ("EK721", "DXB", "NBO", "NT24IF", "shape_checkin_route_blocks"),
    ]


def test_vertical_route_date_time_blocks_parse_emirates_checkin_shape() -> None:
    body = """
    Booking reference = Booking reference NT24IF
    = Your itinerary =
    == Outbound | New York to Nairobi | Total travel time: 19 hr 45 min ==
    = Depart =
    = Arrive =
    == JFK ==
    New York == DXB ==
    Dubai == 16:35 ==
    Saturday
    31 Dec 16 == 14:05 ==
    Sunday
    01 Jan 17 Flight
    EK208 Aircraft
    Airbus A380-800 Stops
    Economy == Connection in DXB : 2 hr 5 min ==
    = Depart =
    = Arrive =
    == DXB ==
    Dubai == NBO ==
    Nairobi == 16:10 ==
    Sunday
    01 Jan 17 == 20:20 ==
    Sunday
    01 Jan 17 Flight
    EK721 Aircraft
    """

    result = _parse("Check in online for your flight EK208 on 31 December", body, sender="Emirates <emirates.com>")

    assert _segments(result) == [
        ("EK208", "JFK", "DXB", "NT24IF", "shape_vertical_route_date_time_blocks"),
        ("EK721", "DXB", "NBO", "NT24IF", "shape_vertical_route_date_time_blocks"),
    ]


def test_southwest_sparse_checkin_keeps_confirmation_pnr_evidence() -> None:
    body = """
    ---------- Forwarded message ---------
    From: Southwest Airlines <ifly.southwest.com>
    Subject: Your 01/16 trip to Tampa is all set.
    January 16
    PNS
    TPA
    Pensacola to Tampa
    Full itinerary
    Confirmation # *3WVTUA*
    PASSENGER
    David Hennigh
    """

    result = _parse("Fwd: Your 01/16 trip to Tampa is all set.", body, sender="David <gmail.com>")

    assert _segments(result) == [
        (None, "PNS", "TPA", "3WVTUA", "v5_southwest_sparse"),
    ]


def test_labeled_depart_arrive_segments_parse_ota_receipt_shape() -> None:
    body = """
    Booking reference YSCMJG
    Royal Air Maroc
    Flight 0201
    departs JFK
    8:30PM
    Thu, Aug 11, 2016
    arrives CMN
    8:20AM
    Fri, Aug 12, 2016
    Flight 0263
    departs CMN
    4:15PM
    Fri, Aug 12, 2016
    arrives NBO
    2:00AM
    Sat, Aug 13, 2016
    """

    result = _parse("Your StudentUniverse Order", body, sender="StudentUniverse <studentuniverse.com>")

    assert _segments(result) == [
        ("AT201", "JFK", "CMN", "YSCMJG", "shape_labeled_depart_arrive_segments"),
        ("AT263", "CMN", "NBO", "YSCMJG", "shape_labeled_depart_arrive_segments"),
    ]


def test_allegiant_trip_detail_sections_parse_visible_return_without_number() -> None:
    body = """
    Your Flight Details
    Confirmation #
    97BCD4
    Departure Date
    Tuesday, July 23, 2019 at 12:00 PM
    Departure Airport
    Newark Liberty International Airport (EWR)
    Arrival
    Destin-Fort Walton Beach Airport (VPS) at 1:45 PM
    Your Return Flight
    Departure Date
    Sunday, August 04, 2019 at 7:30 AM
    Departure Airport
    Destin-Fort Walton Beach Airport (VPS)
    Arrival
    Newark Liberty International Airport (EWR) at 11:00 AM
    """

    result = _parse("Your upcoming trip is only 28 days away", body, sender="Allegiant <e.allegiant.com>")

    assert _segments(result) == [
        (None, "EWR", "VPS", "97BCD4", "shape_allegiant_trip_detail_sections"),
        (None, "VPS", "EWR", "97BCD4", "shape_allegiant_trip_detail_sections"),
    ]


def test_delta_receipt_table_shape_parses_old_receipt() -> None:
    body = """
    Flight Receipt and Itinerary
    Your Trip Confirmation #:
    GVPIAT
    Fri, 08FEB
    DEPART
    ARRIVE
    DELTA 1353
    Basic Economy
    NYC-KENNEDY
    5:15pm
    SAN FRANCISCO, CA
    8:59pm
    """

    result = _parse("Your Flight Receipt - NATHAN HENNIGH 08FEB19", body, sender="Delta <delta.com>")

    assert _segments(result) == [
        ("DL1353", "JFK", "SFO", "GVPIAT", "shape_delta_receipt_table"),
    ]
