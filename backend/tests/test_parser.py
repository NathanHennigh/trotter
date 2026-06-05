"""Unit tests for the parser service.

Requires: beautifulsoup4, rapidfuzz, icalendar  (all in pyproject.toml).
"""

from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"

bs4 = pytest.importorskip("bs4", reason="beautifulsoup4 not installed")
rapidfuzz = pytest.importorskip("rapidfuzz", reason="rapidfuzz not installed")


# ─────────────────────────── JSON-LD tests ───────────────────────────────────


class TestJsonLdParser:
    def test_single_flight_reservation(self):
        from app.services.parser import extract_jsonld_flights

        html = (FIXTURES / "flight_reservation.html").read_text(encoding="utf-8")
        flights = extract_jsonld_flights(html)

        assert len(flights) == 1
        f = flights[0]
        assert f.dep_airport == "LAX"
        assert f.arr_airport == "JFK"
        assert f.airline == "AA"
        assert f.flight_number == "AA1234"
        assert f.pnr == "ABC123"
        assert f.passenger_name == "Nathan Hennigh"
        assert f.dep_time.year == 2024
        assert f.dep_time.month == 1
        assert f.dep_time.day == 15
        assert f.source == "jsonld"

    def test_multi_leg_returns_two_flights(self):
        from app.services.parser import extract_jsonld_flights

        html = (FIXTURES / "flight_reservation_multi_leg.html").read_text(encoding="utf-8")
        flights = extract_jsonld_flights(html)

        assert len(flights) == 2
        assert flights[0].dep_airport == "SFO"
        assert flights[0].arr_airport == "ORD"
        assert flights[1].dep_airport == "ORD"
        assert flights[1].arr_airport == "LHR"
        assert flights[0].pnr == "XYZ789"
        assert flights[1].pnr == "XYZ789"

    def test_empty_html_returns_empty(self):
        from app.services.parser import extract_jsonld_flights

        assert extract_jsonld_flights("") == []
        assert extract_jsonld_flights("<html><body>No flights here</body></html>") == []

    def test_invalid_jsonld_is_skipped_gracefully(self):
        from app.services.parser import extract_jsonld_flights

        html = '<script type="application/ld+json">{ this is not valid json }</script>'
        assert extract_jsonld_flights(html) == []

    def test_non_flight_jsonld_is_ignored(self):
        from app.services.parser import extract_jsonld_flights

        html = (
            '<script type="application/ld+json">'
            '{"@type": "Product", "name": "Widget"}'
            "</script>"
        )
        assert extract_jsonld_flights(html) == []

    def test_missing_airports_skipped(self):
        from app.services.parser import extract_jsonld_flights

        html = (
            '<script type="application/ld+json">'
            '{"@type":"FlightReservation","reservationFor":{"@type":"Flight",'
            '"departureTime":"2024-01-15T08:00:00Z","arrivalTime":"2024-01-15T12:00:00Z"}}'
            "</script>"
        )
        assert extract_jsonld_flights(html) == []

    def test_flight_number_prefixed_with_airline_code(self):
        from app.services.parser import extract_jsonld_flights

        html = (
            '<script type="application/ld+json">'
            '{"@type":"FlightReservation",'
            '"reservationFor":{"@type":"Flight","flightNumber":"BA456",'
            '"airline":{"iataCode":"BA"},'
            '"departureAirport":{"iataCode":"LHR"},'
            '"arrivalAirport":{"iataCode":"JFK"},'
            '"departureTime":"2024-06-01T09:00:00+01:00",'
            '"arrivalTime":"2024-06-01T11:30:00-05:00"}}'
            "</script>"
        )
        flights = extract_jsonld_flights(html)
        assert len(flights) == 1
        assert flights[0].flight_number == "BA456"
        assert flights[0].airline == "BA"


# ─────────────────────────── ICS tests ───────────────────────────────────────


class TestIcsParser:
    def test_basic_ics_flight(self):
        icalendar = pytest.importorskip("icalendar", reason="icalendar not installed")
        from app.services.parser import extract_ics_flights

        ics = (FIXTURES / "flight.ics").read_text(encoding="utf-8")
        flights = extract_ics_flights(ics)

        assert len(flights) >= 1
        f = flights[0]
        assert f.dep_airport == "LAX"
        assert f.arr_airport == "JFK"
        assert f.airline == "AA"
        assert f.flight_number == "AA1234"
        assert f.dep_time is not None
        assert f.arr_time is not None
        assert f.dep_time.tzinfo is not None
        assert f.source == "ics"

    def test_ics_datetime_timezone_aware(self):
        icalendar = pytest.importorskip("icalendar", reason="icalendar not installed")
        from app.services.parser import extract_ics_flights

        ics = (FIXTURES / "flight.ics").read_text(encoding="utf-8")
        flights = extract_ics_flights(ics)

        assert flights[0].dep_time.tzinfo is not None
        assert flights[0].arr_time.tzinfo is not None

    def test_empty_ics_returns_empty(self):
        icalendar = pytest.importorskip("icalendar", reason="icalendar not installed")
        from app.services.parser import extract_ics_flights

        assert extract_ics_flights("") == []

    def test_invalid_ics_returns_empty(self):
        icalendar = pytest.importorskip("icalendar", reason="icalendar not installed")
        from app.services.parser import extract_ics_flights

        assert extract_ics_flights("NOT A VALID ICS FILE") == []


# ─────────────────────────── Identity check tests ────────────────────────────


class TestCheckIdentity:
    def test_exact_name_match_accepted(self):
        from app.models import MessageStatus
        from app.services.parser import check_identity

        assert check_identity("Nathan Hennigh", "Nathan Hennigh", []) == MessageStatus.ACCEPTED

    def test_case_insensitive_match_accepted(self):
        from app.models import MessageStatus
        from app.services.parser import check_identity

        assert check_identity("NATHAN HENNIGH", "Nathan Hennigh", []) == MessageStatus.ACCEPTED

    def test_partial_name_above_threshold_accepted(self):
        from app.models import MessageStatus
        from app.services.parser import check_identity

        # token_set_ratio("N HENNIGH", "Nathan Hennigh") should be above 85
        assert check_identity("N HENNIGH", "Nathan Hennigh", []) == MessageStatus.ACCEPTED

    def test_unrelated_name_review_required(self):
        from app.models import MessageStatus
        from app.services.parser import check_identity

        assert check_identity("John Smith", "Nathan Hennigh", []) == MessageStatus.REVIEW_REQUIRED

    def test_alias_match_accepted(self):
        from app.models import MessageStatus
        from app.services.parser import check_identity

        assert (
            check_identity("Nate Hennigh", "Nathan Hennigh", ["Nate Hennigh"])
            == MessageStatus.ACCEPTED
        )

    def test_none_passenger_name_review_required(self):
        from app.models import MessageStatus
        from app.services.parser import check_identity

        assert check_identity(None, "Nathan Hennigh", []) == MessageStatus.REVIEW_REQUIRED

    def test_empty_passenger_name_review_required(self):
        from app.models import MessageStatus
        from app.services.parser import check_identity

        assert check_identity("", "Nathan Hennigh", []) == MessageStatus.REVIEW_REQUIRED

    def test_no_user_name_accepted(self):
        """If there's no user info to match against, accept the message."""
        from app.models import MessageStatus
        from app.services.parser import check_identity

        assert check_identity("Any Name", "", []) == MessageStatus.ACCEPTED


# ─────────────────────────── Heuristic parser tests ──────────────────────────


class TestHeuristicParser:
    def test_delta_trip_details_compact_route(self):
        from app.services.parser import parse_email

        text = """
        Your LGA > ATL Trip Details
        Everything you need to know for your upcoming flight.
        DELTA CONFIRMATION: ABC123
        DEPARTURE LGA 6:20 PM Mon, Apr 27 DL343
        DESTINATION ATL 8:53 PM Mon, Apr 27
        Get Ready To Go
        """

        result = parse_email(
            html="",
            plain_text=text,
            attachments=[],
            user_name="Nathan Hennigh",
            aliases=[],
            received_at="Fri, 24 Apr 2020 12:00:00 +0000",
            subject="Your LGA > ATL Trip Details",
            from_email="DeltaAirLines@t.delta.com",
        )

        assert len(result.flights) == 1
        flight = result.flights[0]
        assert flight.dep_airport == "LGA"
        assert flight.arr_airport == "ATL"
        assert flight.flight_number == "DL343"
        assert flight.dep_time.year == 2020
        assert flight.dep_time.hour == 18
        assert flight.arr_time.hour == 20

    def test_aa_trip_confirmation_rows(self):
        from app.services.parser import parse_email

        text = """
        Your trip confirmation-PEPHOZ
        Thursday, November 1, 2018 LGA DFW 3:59 PM 6:59 PM New York La Guardia
        Dallas/Fort Worth American Airlines 1608 Economy
        Sunday, November 4, 2018 DFW LGA 4:47 PM 9:03 PM Dallas/Fort Worth
        New York La Guardia American Airlines 1294 Economy
        """

        result = parse_email(
            html="",
            plain_text=text,
            attachments=[],
            user_name="Nathan Hennigh",
            aliases=[],
            received_at="Wed, 31 Oct 2018 12:00:00 +0000",
            subject="Your trip confirmation-PEPHOZ 01NOV",
            from_email="American Airlines <notify.email.aa.com>",
        )

        assert [flight.flight_number for flight in result.flights] == ["AA1608", "AA1294"]
        assert [(flight.dep_airport, flight.arr_airport) for flight in result.flights] == [
            ("LGA", "DFW"),
            ("DFW", "LGA"),
        ]
        assert result.flights[0].dep_time.year == 2018

    def test_united_eticket_rows(self):
        from app.services.parser import parse_email

        text = """
        FLIGHT INFORMATION Day, Date Flight Class Departure City and Time Arrival City and Time
        Wed, 27MAR19 UA2044 N SAN FRANCISCO, CA (SFO) 3:00 PM NEWARK, NJ (EWR - LIBERTY) 11:36 PM 757-200
        Mon, 01APR19 UA1885 N NEWARK, NJ (EWR - LIBERTY) 4:00 PM SAN FRANCISCO, CA (SFO) 7:26 PM A320
        """

        result = parse_email(
            html="",
            plain_text=text,
            attachments=[],
            user_name="Nathan Hennigh",
            aliases=[],
            received_at="Tue, 26 Mar 2019 12:00:00 +0000",
            subject="eTicket Itinerary and Receipt for Confirmation EM1HC7",
            from_email="United Airlines <united.com>",
        )

        assert [flight.flight_number for flight in result.flights] == ["UA2044", "UA1885"]
        assert [(flight.dep_airport, flight.arr_airport) for flight in result.flights] == [
            ("SFO", "EWR"),
            ("EWR", "SFO"),
        ]
        assert result.flights[0].dep_time.year == 2019

    def test_frontier_confirmation_rows(self):
        from app.services.parser import parse_email

        text = """
        Your Flight Confirmation Code A6RVTV
        DEPARTING FLIGHT 507 Dallas (DFW) to Denver (DEN)
        Depart: 3/4/2022 6:00 AM | Arrive: 3/4/2022 7:12 AM Total Duration
        RETURNING FLIGHT 506 Denver (DEN) to Dallas (DFW)
        Depart: 3/11/2022 8:00 PM | Arrive: 3/11/2022 10:56 PM Total Duration
        """

        result = parse_email(
            html="",
            plain_text=text,
            attachments=[],
            user_name="Nathan Hennigh",
            aliases=[],
            received_at="Thu, 03 Mar 2022 12:00:00 +0000",
            subject="Your Flight Confirmation Code A6RVTV",
            from_email="Frontier Airlines <emails.flyfrontier.com>",
        )

        assert [flight.flight_number for flight in result.flights] == ["F9507", "F9506"]
        assert [(flight.dep_airport, flight.arr_airport) for flight in result.flights] == [
            ("DFW", "DEN"),
            ("DEN", "DFW"),
        ]

    def test_studentuniverse_departs_arrives_rows(self):
        from app.services.parser import parse_email

        text = """
        Your StudentUniverse Order
        Traveler Nathan Hennigh
        Royal Air Maroc Flight 0262 has been confirmed and departs NBO 3:30AM
        Sat, Jul 16, 2016 arrives CMN 9:50AM Sat, Jul 16, 2016 8hr 20min
        Royal Air Maroc Flight 0200 departs CMN 3:05PM Sat, Jul 16, 2016
        arrives JFK 5:55PM Sat, Jul 16, 2016
        """

        result = parse_email(
            html="",
            plain_text=text,
            attachments=[],
            user_name="Nathan Hennigh",
            aliases=[],
            received_at="Mon, 13 Jun 2016 12:00:00 +0000",
            subject="Your StudentUniverse Order - June 13, 2016",
            from_email="StudentUniverse <travel@studentuniverse.com>",
        )

        assert [flight.flight_number for flight in result.flights] == ["AT0262", "AT0200"]
        assert [(flight.dep_airport, flight.arr_airport) for flight in result.flights] == [
            ("NBO", "CMN"),
            ("CMN", "JFK"),
        ]

    def test_southwest_forwarded_pretrip_markup(self):
        from app.services.parser import parse_email

        text = """
        From: Southwest Airlines
        Confirmation # *3YWWF2*
        PASSENGER Nathan Hennigh
        Your complete itinerary
        *Flight :* Saturday 01/14/2023
        FLIGHT # 1783
        DEPARTS *BNA 2:20*PM Nashville
        ARRIVES *DAL 4:30*PM Dallas (Love)
        """

        result = parse_email(
            html="",
            plain_text=text,
            attachments=[],
            user_name="Nathan Hennigh",
            aliases=[],
            received_at="Fri, 13 Jan 2023 12:00:00 +0000",
            subject="Fwd: What you'll need for your Dallas trip (3YWWF2).",
            from_email="Southwest Airlines <SouthwestAirlines@iluv.southwest.com>",
        )

        assert len(result.flights) == 1
        assert result.flights[0].flight_number == "WN1783"
        assert result.flights[0].dep_airport == "BNA"
        assert result.flights[0].arr_airport == "DAL"

    def test_emirates_labeled_route_time_rows(self):
        from app.services.parser import parse_email

        text = """
        Your itinerary
        Booking reference NPDTXW
        *Depart* *Arrive*
        * NBO * Nairobi * DXB * Dubai * 16:50 * Friday 10 Jan 20 * 22:50 * Friday 10 Jan 20 *
        Flight * EK720 *Aircraft* Boeing 777-300ER
        * DXB * Dubai * EWR * Newark * 02:40 * Saturday 11 Jan 20 * 07:55 * Saturday 11 Jan 20 *
        Flight * EK223 *Aircraft* Boeing 777-300ER
        Passengers Nathancharles Hennigh
        """

        result = parse_email(
            html="",
            plain_text=text,
            attachments=[],
            user_name="Nathan Hennigh",
            aliases=["Nathancharles Hennigh"],
            received_at="Thu, 09 Jan 2020 12:00:00 +0000",
            subject="Your itinerary - NPDTXW",
            from_email="Emirates <do-not-reply@emirates.email>",
        )

        assert [flight.flight_number for flight in result.flights] == ["EK720", "EK223"]
        assert [(flight.dep_airport, flight.arr_airport) for flight in result.flights] == [
            ("NBO", "DXB"),
            ("DXB", "EWR"),
        ]
        assert result.flights[0].dep_time.year == 2020

    def test_spirit_confirmation_table_without_flight_number(self):
        from app.services.parser import parse_email

        html = """
        <html><body>
        <p>Spirit Airlines Flight Confirmation: GJPWKE</p>
        <tr id="FlightHeader"><td><strong>SUNDAY, AUGUST 18, 2019 </strong></td><td>TIME</td></tr>
        <tr id="FlightFrom"><td>New York, NY - LaGuardia </td><td>1:49 PM</td><td>03 h 51 min</td></tr>
        <tr id="FlightTo"><td>Dallas/Fort Worth, TX </td><td>4:40 PM </td><td></td></tr>
        </body></html>
        """

        result = parse_email(
            html=html,
            plain_text="",
            attachments=[],
            user_name="Nathan Hennigh",
            aliases=[],
            received_at="Tue, 30 Jul 2019 12:00:00 +0000",
            subject="Spirit Airlines Flight Confirmation: GJPWKE",
            from_email="Spirit Airlines <booking@fly.spirit-airlines.com>",
        )

        assert len(result.flights) == 1
        assert result.flights[0].airline == "NK"
        assert result.flights[0].dep_airport == "LGA"
        assert result.flights[0].arr_airport == "DFW"

    def test_no_flight_text_returns_empty(self):
        from app.services.parser import extract_heuristic_flights

        result = extract_heuristic_flights("Hello, world! No flights here.")
        assert result == []

    def test_iso_datetime_flight_extraction(self):
        from app.services.parser import extract_heuristic_flights

        text = (
            "Your flight AA1234 departs from LAX on 2024-01-15T08:00:00-08:00 "
            "and arrives at JFK at 2024-01-15T16:30:00-05:00."
        )
        flights = extract_heuristic_flights(text)
        assert len(flights) == 1
        assert flights[0].dep_airport == "LAX"
        assert flights[0].arr_airport == "JFK"
        assert flights[0].airline == "AA"
        assert flights[0].flight_number == "AA1234"

    def test_unknown_airline_code_ignored(self):
        from app.services.parser import extract_heuristic_flights

        # "ZZ" is not in KNOWN_AIRLINES
        text = "Your flight ZZ9999 departs LAX on 2024-01-15T08:00:00Z arrives JFK 2024-01-15T16:00:00Z."
        flights = extract_heuristic_flights(text)
        assert flights == []


# ─────────────────────────── Airport extraction helper tests ─────────────────


class TestAirportExtraction:
    def test_extracts_iata_codes(self):
        from app.services.parser import _extract_airports

        airports = _extract_airports("Flying from LAX to JFK via ORD")
        assert "LAX" in airports
        assert "JFK" in airports
        assert "ORD" in airports

    def test_common_words_excluded(self):
        from app.services.parser import _extract_airports

        airports = _extract_airports("THE flight was NOT delayed AND you ARE confirmed")
        assert "THE" not in airports
        assert "NOT" not in airports
        assert "AND" not in airports
        assert "ARE" not in airports

    def test_deduplication_preserves_order(self):
        from app.services.parser import _extract_airports

        airports = _extract_airports("LAX to JFK then JFK to LHR")
        assert airports == ["LAX", "JFK", "LHR"]

    def test_valid_non_trip_codes_do_not_win_without_route_context(self):
        from app.services.parser import extract_heuristic_flights

        text = (
            "Your flight AA1234 departs from LAX on 2024-01-15T08:00:00-08:00 "
            "and arrives at JFK at 2024-01-15T16:30:00-05:00. "
            "Bag drop opens early. View details at https://example.com/rts/go2.aspx"
        )

        flights = extract_heuristic_flights(text)

        assert len(flights) == 1
        assert flights[0].dep_airport == "LAX"
        assert flights[0].arr_airport == "JFK"

    def test_pnr_requires_label_and_ignores_common_words(self):
        from app.services.parser import extract_heuristic_flights

        text = (
            "PLEASE review your eTicket Itinerary and Receipt. "
            "Confirmation E37N05. "
            "Flight UA2275 departs from IAD on 2024-12-20T22:24:00Z "
            "and arrives at IAH at 2024-12-21T01:45:00Z."
        )

        flights = extract_heuristic_flights(text)

        assert len(flights) == 1
        assert flights[0].pnr == "E37N05"

    def test_structured_multi_leg_receipt_uses_nearest_route_and_times(self):
        from app.services.parser import extract_heuristic_flights

        text = (
            "Confirmation Number: E48NQG "
            "Flight 1 of 2 UA677 Class: United Economy (K) "
            "Sun, Dec 15, 2024 Sun, Dec 15, 2024 07:30 AM 11:25 AM "
            "Houston, TX, US (IAH) Washington, DC, US (DCA) "
            "Flight 2 of 2 UA2275 Class: United Economy (T) "
            "Thu, Dec 19, 2024 Fri, Dec 20, 2024 10:24 PM 01:00 AM "
            "Washington, DC, US (IAD) Houston, TX, US (IAH)"
        )

        flights = extract_heuristic_flights(text)

        assert len(flights) == 2
        assert flights[0].flight_number == "UA677"
        assert flights[0].dep_airport == "IAH"
        assert flights[0].arr_airport == "DCA"
        assert flights[0].dep_time.hour == 7
        assert flights[0].arr_time.hour == 11
        assert flights[1].flight_number == "UA2275"
        assert flights[1].dep_airport == "IAD"
        assert flights[1].arr_airport == "IAH"
        assert flights[1].dep_time.day == 19
        assert flights[1].arr_time.day == 20
        assert {flight.pnr for flight in flights} == {"E48NQG"}

    def test_capital_one_compact_multi_leg_receipt(self):
        from app.services.parser import extract_heuristic_flights

        text = (
            "Your ANA confirmation code: CB5Q98 Capital One Travel H-YDTJHJ "
            "Outbound to Singapore September 29, 2025 1 stop "
            "ANA - NH6451 Houston IAH 10:05 a.m. 13h 55m Tokyo NRT 2:00 p.m. "
            "This flight arrives the next day. 4h 40m layover in Tokyo "
            "ANA - NH801 Tokyo NRT 6:40 p.m. 7h 5m Singapore SIN 12:45 a.m. "
            "This flight arrives the next day. "
            "Return to Houston October 03, 2025 1 stop "
            "ANA - NH802 Singapore SIN 6:15 a.m. 7h 15m Tokyo NRT 2:30 p.m. "
            "ANA - NH6450 Tokyo NRT 5:00 p.m. 11h 55m Houston IAH 2:55 p.m."
        )

        flights = extract_heuristic_flights(text)

        assert [f.flight_number for f in flights] == ["NH6451", "NH801", "NH802", "NH6450"]
        assert [(f.dep_airport, f.arr_airport) for f in flights] == [
            ("IAH", "NRT"),
            ("NRT", "SIN"),
            ("SIN", "NRT"),
            ("NRT", "IAH"),
        ]
        assert {f.pnr for f in flights} == {"CB5Q98"}

    def test_justfly_no_year_itinerary_uses_received_year(self):
        from app.services.parser import extract_heuristic_flights

        text = (
            "Iberia Confirmation Number: KHMFT YOUR ITINERARY Departure "
            "Iberia Flight 4358 6:00am Sun. May 29 Los Angeles, CA (LAX) "
            "1:59pm Sun. May 29 Miami, FL (MIA) "
            "Iberia Flight 4610 5:55pm Sun. May 29 Miami, FL (MIA) "
            "8:25am Mon. May 30 Madrid (MAD) "
            "Iberia Flight 3340 11:00am Mon. May 30 Madrid (MAD) "
            "12:00pm Mon. May 30 Marrakech (RAK)"
        )

        flights = extract_heuristic_flights(text, received_at="Thu, 14 Apr 2022 17:27:21 -0400")

        assert [f.dep_airport for f in flights] == ["LAX", "MIA", "MAD"]
        assert [f.arr_airport for f in flights] == ["MIA", "MAD", "RAK"]
        assert flights[0].dep_time.year == 2022
        assert {f.pnr for f in flights} == {"KHMFT"}

    def test_airasia_reschedule_prefers_new_schedule(self):
        from app.services.parser import extract_heuristic_flights

        text = (
            "Booking Number: MDHIYD Original Schedule Flight number : Z2211 "
            "Departure Date : 28 Apr, 2025 Depart from Manila Int'l(MNL) : 06:45hrs, local time "
            "Arrive in Caticlan (Godofredo P. Ramos) (MPH) : 07:45hrs, local time "
            "New Schedule Flight number : Z2211 Departure Date : 28 Apr, 2025 "
            "Depart from Manila Int'l(MNL) : 06:25hrs, local time "
            "Arrive in Caticlan (Godofredo P. Ramos) (MPH) : 07:25hrs, local time"
        )

        flights = extract_heuristic_flights(text)

        assert len(flights) == 1
        assert flights[0].dep_airport == "MNL"
        assert flights[0].arr_airport == "MPH"
        assert flights[0].dep_time.hour == 6
        assert flights[0].dep_time.minute == 25
        assert flights[0].pnr == "MDHIYD"

    def test_southwest_itinerary_receipt(self):
        from app.services.parser import extract_heuristic_flights

        text = (
            "Southwest Airlines Confirmation # 37X6VR Your itinerary "
            "Flight 1: Sunday, 08/04/2024 Est. Travel Time: 4h 25m "
            "Wanna Get Away FLIGHT # 1074 DEPARTS HOU 09:00 AM Houston (Hobby) "
            "ARRIVES PUJ 02:25 PM Punta Cana "
            "Flight 2: Sunday, 08/11/2024 Est. Travel Time: 9h 30m "
            "Wanna Get Away FLIGHT # 0822 DEPARTS PUJ 03:05 PM Punta Cana "
            "ARRIVES BWI 07:00 PM Baltimore - Stop: Change planes "
            "FLIGHT # 1304 DEPARTS BWI 09:20 PM Baltimore ARRIVES HOU 11:35 PM Houston (Hobby)"
        )

        flights = extract_heuristic_flights(text)

        assert [flight.flight_number for flight in flights] == ["WN1074", "WN822", "WN1304"]
        assert [(flight.dep_airport, flight.arr_airport) for flight in flights] == [
            ("HOU", "PUJ"),
            ("PUJ", "BWI"),
            ("BWI", "HOU"),
        ]
        assert {flight.pnr for flight in flights} == {"37X6VR"}

    def test_southwest_forward_with_marked_times(self):
        from app.services.parser import extract_heuristic_flights

        text = (
            "Southwest Airlines Confirmation # 9ABC12 Your itinerary "
            "Flight 1: Sunday, 12/18/2022 "
            "FLIGHT # 1783 DEPARTS *BNA 2:20*PM Nashville "
            "ARRIVES *DAL 4:30*PM Dallas (Love)"
        )

        flights = extract_heuristic_flights(text)

        assert len(flights) == 1
        assert flights[0].flight_number == "WN1783"
        assert (flights[0].dep_airport, flights[0].arr_airport) == ("BNA", "DAL")
        assert flights[0].dep_time.hour == 14
        assert flights[0].arr_time.hour == 16

    def test_american_inline_receipt_segments(self):
        from app.services.parser import extract_heuristic_flights

        text = (
            "American Airlines Record Locator: XCIFWY "
            "Sunday October 1, 2023 "
            "BNA Nashville 12:23 PM AA 4567 operated by American Eagle "
            "RDU Raleigh-Durham 2:56 PM "
            "RDU Raleigh-Durham 5:44 PM AA 1740 "
            "DFW Dallas/Fort Worth 7:54 PM"
        )

        flights = extract_heuristic_flights(text)

        assert [flight.flight_number for flight in flights] == ["AA4567", "AA1740"]
        assert [(flight.dep_airport, flight.arr_airport) for flight in flights] == [
            ("BNA", "RDU"),
            ("RDU", "DFW"),
        ]

    def test_american_hold_table_segments(self):
        from app.services.parser import extract_heuristic_flights

        text = (
            "American Airlines Trip Hold Record Locator XCIFWY "
            "AMERICAN AIRLINES 4567 Nashville(BNA) Sun Oct 01 12:23 PM "
            "Raleigh/Durham(RDU) Sun Oct 01 02:56 PM "
            "AMERICAN AIRLINES 1740 Raleigh/Durham(RDU) Sun Oct 01 05:44 PM "
            "Dallas/Fort Worth(DFW) Sun Oct 01 07:54 PM"
        )

        flights = extract_heuristic_flights(
            text,
            received_at="Wed, 20 Sep 2023 10:00:00 -0500",
        )

        assert [flight.flight_number for flight in flights] == ["AA4567", "AA1740"]
        assert [(flight.dep_airport, flight.arr_airport) for flight in flights] == [
            ("BNA", "RDU"),
            ("RDU", "DFW"),
        ]

    def test_partner_award_receipt_segments(self):
        from app.services.parser import extract_heuristic_flights

        text = (
            "Alaska Mileage Plan Partner Award American Airlines 3243 "
            "Tue, Mar 17 02:46 PM DFW Dallas/Fort Worth "
            "Tue, Mar 17 04:38 PM BNA Nashville "
            "American Airlines 2787 Mon, Mar 23 06:09 AM BNA Nashville "
            "Mon, Mar 23 08:19 AM DFW Dallas/Fort Worth"
        )

        flights = extract_heuristic_flights(
            text,
            received_at="Tue, 10 Mar 2026 09:00:00 -0500",
        )

        assert [flight.flight_number for flight in flights] == ["AA3243", "AA2787"]
        assert [(flight.dep_airport, flight.arr_airport) for flight in flights] == [
            ("DFW", "BNA"),
            ("BNA", "DFW"),
        ]

    def test_airline_route_flight_rows_without_airline_code_prefix(self):
        from app.services.parser import extract_heuristic_flights

        text = (
            "JetBlue booking confirmation. Your JetBlue confirmation code is LTBUMI "
            "PUJ FLL Flight 0174 Thu, Jun 25 2:33 PM Terminal: A - Thu, Jun 25 5:08 PM "
            "FLL DFW Flight 2279 Thu, Jun 25 8:42 PM Terminal: 3 - Thu, Jun 25 11:01 PM"
        )

        flights = extract_heuristic_flights(
            text,
            received_at="Tue, 28 Apr 2026 22:34:56 +0000",
        )

        assert [flight.flight_number for flight in flights] == ["B60174", "B62279"]
        assert [(flight.dep_airport, flight.arr_airport) for flight in flights] == [
            ("PUJ", "FLL"),
            ("FLL", "DFW"),
        ]
        assert {flight.pnr for flight in flights} == {"LTBUMI"}

    def test_parse_email_uses_normalized_html_even_when_plain_text_exists(self):
        from app.services.parser import parse_email

        html = """
        <html><body>
        <p>Your JetBlue confirmation code is LTBUMI</p>
        <p>PUJ</p><p>FLL</p><p>Flight</p><p>0174</p>
        <p>Thu, Jun 25</p><p>2:33 PM</p><p>Terminal: A -</p>
        <p>Thu, Jun 25</p><p>5:08 PM</p>
        <p>FLL</p><p>DFW</p><p>Flight</p><p>2279</p>
        <p>Thu, Jun 25</p><p>8:42 PM</p><p>Terminal: 3 -</p>
        <p>Thu, Jun 25</p><p>11:01 PM</p>
        </body></html>
        """

        result = parse_email(
            html=html,
            plain_text="JetBlue booking confirmation for NATHAN HENNIGH - LTBUMI",
            attachments=[],
            user_name="Nathan Hennigh",
            aliases=[],
            received_at="Tue, 28 Apr 2026 22:34:56 +0000",
            subject="JetBlue booking confirmation for NATHAN HENNIGH - LTBUMI",
            from_email="JetBlue <jetblueairways@needtoknow.jetblue.com>",
        )

        assert [flight.flight_number for flight in result.flights] == ["B60174", "B62279"]
        assert [(flight.dep_airport, flight.arr_airport) for flight in result.flights] == [
            ("PUJ", "FLL"),
            ("FLL", "DFW"),
        ]

    def test_arrives_route_rows_from_trip_monitor_email(self):
        from app.services.parser import extract_heuristic_flights

        text = (
            "Confirmation code LTBUMI JetBlue Airways June 25th PUJ 2:33 PM "
            "B6 0174 Arrives FLL 5:08 PM 3h 34m layover FLL June 25th FLL "
            "8:42 PM B6 2279 Arrives Dallas (DFW) 11:01 PM"
        )

        flights = extract_heuristic_flights(
            text,
            received_at="Tue, 28 Apr 2026 22:38:10 +0000",
        )

        assert [flight.flight_number for flight in flights] == ["B60174", "B62279"]
        assert [(flight.dep_airport, flight.arr_airport) for flight in flights] == [
            ("PUJ", "FLL"),
            ("FLL", "DFW"),
        ]

    def test_compact_route_uses_nearby_trip_date_not_purchase_date(self):
        from app.services.parser import extract_heuristic_flights

        text = (
            "Capital One Travel Confirmation. Purchase Date: December 17, 2025. "
            "Outbound to Singapore September 29, 2025 1 stop ANA - NH6451 "
            "Houston IAH 10:05 a.m. 13h 55m Tokyo NRT 2:00 p.m. "
            "This flight arrives the next day. ANA - NH801 Tokyo NRT 6:40 p.m. "
            "7h 5m Singapore SIN 12:45 a.m."
        )

        flights = extract_heuristic_flights(text)

        assert flights[0].flight_number == "NH6451"
        assert (flights[0].dep_airport, flights[0].arr_airport) == ("IAH", "NRT")
        assert flights[0].dep_time.month == 9
        assert flights[0].dep_time.day == 29

    def test_generic_route_table_itinerary_rows(self):
        from app.services.parser import extract_heuristic_flights

        text = (
            "Reservation code #WNAUQY Itinerary Confirmation Code: WNAUQY Date Departs "
            "Arrives Flt # Route Passengers Sun, Mar 12 7:00 AM 9:55 AM AM 651 "
            "Operated by AEROLITORAL DBA AEROMEXICO CONNECT MGA to MEX "
            "Nathan Charles Hennigh Mon, Mar 13 10:00 AM 1:46 PM AM 2682 "
            "Operated by AEROLITORAL DBA AEROMEXICO CONNECT MEX to DFW "
            "Nathan Charles Hennigh"
        )

        flights = extract_heuristic_flights(
            text,
            received_at="Sat, 11 Mar 2023 13:01:32 +0000 (GMT)",
        )

        assert [flight.flight_number for flight in flights] == ["AM651", "AM2682"]
        assert [(flight.dep_airport, flight.arr_airport) for flight in flights] == [
            ("MGA", "MEX"),
            ("MEX", "DFW"),
        ]
        assert {flight.pnr for flight in flights} == {"WNAUQY"}

    def test_generic_city_time_confirmation_table(self):
        from app.services.parser import extract_heuristic_flights

        text = (
            "Spirit Airlines\nYOUR CONFIRMATION CODE\nUF8K9P\nBooking Date\nWednesday, September 21, 2022\n"
            "Flight\nFRIDAY, MARCH 03, 2023\nTIME\nDURATION\nDallas/Fort Worth, TX\n"
            "2:01 PM\n02 h 45 min\nFort Lauderdale, FL\n5:46 PM\nFLIGHT\nTERMINAL\n360\nE\n"
            "Change Aircraft\nFRIDAY, MARCH 03, 2023\nTIME\nDURATION\nFort Lauderdale, FL\n"
            "11:40 PM\n02 h 42 min\nManagua, Nicaragua\n1:22 AM+\nFLIGHT\nTERMINAL\n435\n4"
        )

        flights = extract_heuristic_flights(text)

        assert [flight.flight_number for flight in flights] == ["NK360", "NK435"]
        assert [(flight.dep_airport, flight.arr_airport) for flight in flights] == [
            ("DFW", "FLL"),
            ("FLL", "MGA"),
        ]
        assert flights[1].arr_time.day == 4
        assert {flight.pnr for flight in flights} == {"UF8K9P"}

    def test_v5_city_database_table_works_without_airport_codes(self):
        from app.services.parser import extract_v5_flights

        text = (
            "Delta Air Lines\nConfirmation DLTEST\nFlight\nMONDAY, JULY 14, 2025\n"
            "TIME\nDURATION\nAtlanta, GA\n8:10 AM\n04 h 05 min\n"
            "Salt Lake City, UT\n10:15 AM\nFLIGHT\n123"
        )

        flights = extract_v5_flights(text, pnr="DLTEST", received_at=None)

        assert len(flights) == 1
        assert flights[0].dep_airport == "ATL"
        assert flights[0].arr_airport == "SLC"
        assert flights[0].flight_number == "DL123"
        assert flights[0].confidence is not None

    def test_v5_city_database_table_parses_same_day_connections(self):
        from app.services.parser import extract_v5_flights

        text = (
            "Delta Air Lines\nConfirmation MCO123\nFlight\nMONDAY, JULY 14, 2025\n"
            "TIME\nDURATION\nHouston, TX\n6:05 AM\n02 h 05 min\n"
            "Atlanta, GA\n9:10 AM\nFLIGHT\n111\n"
            "Atlanta, GA\n10:15 AM\n01 h 28 min\n"
            "Orlando, FL\n11:43 AM\nFLIGHT\n222"
        )

        flights = extract_v5_flights(text, pnr="MCO123", received_at=None)

        assert [flight.flight_number for flight in flights] == ["DL111", "DL222"]
        assert [(flight.dep_airport, flight.arr_airport) for flight in flights] == [
            ("IAH", "ATL"),
            ("ATL", "MCO"),
        ]

    def test_v5_city_database_table_maps_nashville_to_bna(self):
        from app.services.parser import extract_v5_flights

        text = (
            "Delta Air Lines\nConfirmation BNA123\nFlight\nSUNDAY, DECEMBER 01, 2024\n"
            "TIME\nDURATION\nHouston, TX\n8:00 AM\n01 h 55 min\n"
            "Nashville, TN\n9:55 AM\nFLIGHT\n333"
        )

        flights = extract_v5_flights(text, pnr="BNA123", received_at=None)

        assert len(flights) == 1
        assert flights[0].dep_airport == "IAH"
        assert flights[0].arr_airport == "BNA"
        assert flights[0].flight_number == "DL333"

    def test_html_table_parser_preserves_columns_for_v5(self):
        from app.services.parser import parse_email

        html = """
        <html><body>
          <table>
            <tr>
              <th>Date</th><th>Departs</th><th>Departure Time</th>
              <th>Arrives</th><th>Arrival Time</th><th>Flight</th>
            </tr>
            <tr>
              <td>Monday, July 14, 2025</td><td>Atlanta, GA</td><td>8:10 AM</td>
              <td>Salt Lake City, UT</td><td>10:15 AM</td><td>DL123</td>
            </tr>
          </table>
        </body></html>
        """

        result = parse_email(
            html=html,
            plain_text="",
            attachments=[],
            user_name="",
            aliases=[],
            from_email="Delta Air Lines <noreply@example.com>",
            subject="Your flight confirmation",
        )

        assert len(result.flights) == 1
        assert result.flights[0].dep_airport == "ATL"
        assert result.flights[0].arr_airport == "SLC"
        assert result.flights[0].flight_number == "DL123"

    def test_v5_rejects_baggage_table_airport_like_codes(self):
        from app.services.parser import extract_v5_flights

        text = (
            "Baggage policy\nFriday, July 18, 2025\nBAG\n8:00 AM\n"
            "02 h 00 min\nRTS\n10:00 AM\nFLIGHT\n123\n"
            "First bag and second bag charges may apply."
        )

        assert extract_v5_flights(text, pnr=None, received_at=None) == []

    def test_generic_united_booking_confirmation_block(self):
        from app.services.parser import extract_heuristic_flights

        text = (
            "Confirmation number: E48NQG Flight to Washington Dec 15, 2024 "
            "Nonstop 7:30 AM 11:25 AM IAH 2h 55m DCA Houston, TX, US "
            "Washington, DC, US FLIGHT INFO Duration: 2h 55m UA 677 Airbus A320 "
            "Flight to Houston Dec 19, 2024 Nonstop +1 day arrival 10:24 PM 1:00 AM "
            "IAD 3h 36m IAH Washington, DC, US Houston, TX, US FLIGHT INFO "
            "Duration: 3h 36m UA 2275 Boeing 737-800"
        )

        flights = extract_heuristic_flights(text)

        assert [flight.flight_number for flight in flights] == ["UA677", "UA2275"]
        assert [(flight.dep_airport, flight.arr_airport) for flight in flights] == [
            ("IAH", "DCA"),
            ("IAD", "IAH"),
        ]
        assert flights[1].arr_time.day == 20
        assert {flight.pnr for flight in flights} == {"E48NQG"}

    def test_capital_one_city_with_comma_route_block(self):
        from app.services.parser import extract_heuristic_flights

        text = (
            "Your confirmation codes United E37N05 Outbound to Houston "
            "December 19, 2024 3h 36m Nonstop United - UA2275 "
            "Washington, D.C. IAD 10:24 p.m. 3h 36m Houston IAH 1:00 a.m. "
            "This flight arrives the next day."
        )

        flights = extract_heuristic_flights(text)

        assert len(flights) == 1
        assert flights[0].dep_airport == "IAD"
        assert flights[0].arr_airport == "IAH"
        assert flights[0].flight_number == "UA2275"
        assert flights[0].pnr == "E37N05"

    def test_capital_one_airline_confirmation_codes_extracts_real_pnr(self):
        from app.services.parser import extract_heuristic_flights

        text = (
            "Your confirmation codes American Airlines GWYCFS Capital One Travel H-N-14LRD4 "
            "Outbound to Tulum Basic Economy August 16, 2025 5h 53m 1 stop "
            "American Airlines - AA1047 Houston IAH 5:30 a.m. 2h 34m Miami MIA 9:04 a.m. "
            "American Airlines - AA172 Miami MIA 10:14 a.m. 2h 9m Tulum TQO 11:23 a.m."
        )

        flights = extract_heuristic_flights(text)

        assert [flight.flight_number for flight in flights] == ["AA1047", "AA172"]
        assert {flight.pnr for flight in flights} == {"GWYCFS"}

    def test_labeled_round_trip_itinerary_segments_are_not_cross_paired(self):
        from app.services.parser import extract_heuristic_flights

        text = (
            "Airline confirmation: SSYQON Houston (IAH) Charlotte (CLT) "
            "Depart : Sat, Aug 09, 2025 06:11 am IAH 09:50 am CLT "
            "2h 39m American Airlines AA 3162 Airbus A321 "
            "Return : Mon, Aug 11, 2025 07:41 pm CLT 09:13 pm IAH "
            "2h 32m American Airlines AA 2935 Boeing 737-800"
        )

        flights = extract_heuristic_flights(text)

        assert [flight.flight_number for flight in flights] == ["AA3162", "AA2935"]
        assert [(flight.dep_airport, flight.arr_airport) for flight in flights] == [
            ("IAH", "CLT"),
            ("CLT", "IAH"),
        ]
        assert flights[0].arr_time.day == 9
        assert flights[1].arr_time.day == 11
        assert {flight.pnr for flight in flights} == {"SSYQON"}

    def test_compact_checkin_row_parses_return_segment(self):
        from app.services.parser import extract_heuristic_flights

        text = (
            "Confirmation code: SSYQON Monday, August 11, 2025 "
            "CLT Charlotte 7:41 PM AA 2935 IAH Houston George Bush 9:13 PM Check in now"
        )

        flights = extract_heuristic_flights(text)

        assert len(flights) == 1
        assert flights[0].flight_number == "AA2935"
        assert flights[0].dep_airport == "CLT"
        assert flights[0].arr_airport == "IAH"

    def test_repeated_same_flight_copy_keeps_earliest_plausible_segment(self):
        from app.services.parser import extract_heuristic_flights

        text = (
            "Outbound to Washington March 07, 2024 Nonstop Spirit Airlines - NK202 "
            "Dallas/Fort Worth DFW 8:51 p.m. 2h 56m Baltimore BWI 11:47 p.m. "
            "Return to Dallas March 11, 2024 Nonstop Frontier - F93283 "
            "Baltimore BWI 1:34 p.m. 2h 41m Dallas/Fort Worth DFW 4:15 p.m. "
            "Duplicate policy text Spirit Airlines - NK202 Dallas/Fort Worth DFW "
            "8:51 p.m. 2h 56m Baltimore BWI 11:47 p.m."
        )

        flights = extract_heuristic_flights(text)

        assert [flight.flight_number for flight in flights] == ["NK202", "F93283"]
        assert flights[0].dep_time.day == 7

    def test_generic_volaris_like_itinerary_block(self):
        from app.services.parser import extract_heuristic_flights

        text = (
            "Reservation code ABC123 Flight to Mexico City Jan 17, 2024 "
            "Nonstop 8:15 AM 10:45 AM IAH 2h 30m MEX "
            "Flight information Duration: 2h 30m Y4 857 Volaris"
        )

        flights = extract_heuristic_flights(text)

        assert len(flights) == 1
        assert flights[0].airline == "Y4"
        assert flights[0].flight_number == "Y4857"
        assert flights[0].dep_airport == "IAH"
        assert flights[0].arr_airport == "MEX"

    def test_hotel_only_travel_confirmation_is_not_a_flight(self):
        from app.services.parser import extract_heuristic_flights

        text = (
            "Here is your travel confirmation for Trip ID 1004623008. "
            "Hotel Mon, Aug 18, 2025 - Sat, Aug 23, 2025 2 guests, 5 nights. "
            "Secrets Tulum Resort & Beach Club Check-in: Mon, Aug 18, 2025, 03:00 pm "
            "Check-out: Sat, Aug 23, 2025, 12:00 pm Tulum 77760 MX. "
            "Add to your trip Book a flight Fly anywhere or any time with hundreds of airlines worldwide."
        )

        assert extract_heuristic_flights(text) == []

    def test_priceline_checkin_alert_parses_full_segment(self):
        from app.services.parser import parse_email

        result = parse_email(
            html="",
            plain_text=(
                "American Airlines Flight 1382 Departs: Departs Newark Liberty Intl Airport (EWR) "
                "Saturday, January 11 2020 at 12:02 PM Arrives: Arrives Dallas/Fort Worth Intl "
                "Airport (DFW) Saturday, January 11 2020 at 3:07 PM"
            ),
            attachments=[],
            user_name="",
            aliases=[],
            subject="Fwd: Check in now for American Airlines Flight 1382 from EWR to DFW",
            from_email="Priceline.com <trans@priceline.com>",
        )

        assert len(result.flights) == 1
        assert result.flights[0].flight_number == "AA1382"
        assert (result.flights[0].dep_airport, result.flights[0].arr_airport) == ("EWR", "DFW")

    def test_allegiant_itinerary_parses_outbound_and_return(self):
        from app.services.parser import parse_email

        result = parse_email(
            html="",
            plain_text=(
                "Your confirmation number is: 97BCD4 Flight Details Departing Flight Information "
                "Date Tue, Jul 23, 2019 Flight # 1915 Departure Airport Newark Liberty International "
                "Airport (EWR) Map Departs 12:00 PM Arrival Airport Destin/Fort Walton Beach FL (VPS) "
                "Map Arrives 01:45 PM Returning Flight Information Date Sun, Aug 04, 2019 Flight # 1904 "
                "Departure Airport Destin/Fort Walton Beach FL (VPS) Map Departs 07:30 AM Arrival Airport "
                "Newark Liberty International Airport (EWR) Map Arrives 11:00 AM"
            ),
            attachments=[],
            user_name="",
            aliases=[],
        )

        assert [flight.flight_number for flight in result.flights] == ["G41915", "G41904"]
        assert [(flight.dep_airport, flight.arr_airport) for flight in result.flights] == [
            ("EWR", "VPS"),
            ("VPS", "EWR"),
        ]

    def test_plain_aa_trip_details_parses_table_rows(self):
        from app.services.parser import parse_email

        result = parse_email(
            html="",
            plain_text=(
                "AA Record Locator: WAOIUG Your Itinerary Carrier Flight Number Departing Arriving "
                "AMERICAN AIRLINES 1198 SFO San Francisco May 28, 2019 05:50 AM DFW Dallas/ Fort Worth "
                "May 28, 2019 11:24 AM AMERICAN AIRLINES 446 DFW Dallas/ Fort Worth Jun 11, 2019 "
                "10:24 PM SFO San Francisco Jun 12, 2019 12:10 AM"
            ),
            attachments=[],
            user_name="",
            aliases=[],
        )

        assert [flight.flight_number for flight in result.flights] == ["AA1198", "AA446"]
        assert result.flights[1].arr_time.day == 12

    def test_sun_country_trip_details_parse_route(self):
        from app.services.parser import parse_email

        result = parse_email(
            html="",
            plain_text=(
                "Reservation code: E5J34M Trip Details Dallas/Ft. Worth, TX to Punta Cana, "
                "Dominican Republic SY739 Nonstop 8:15AM Dallas/Ft. Worth, TX (DFW) June 19, 2026 "
                "4h 50m 2:05PM Punta Cana, Dominican Republic (PUJ) June 19, 2026"
            ),
            attachments=[],
            user_name="",
            aliases=[],
        )

        assert len(result.flights) == 1
        assert result.flights[0].flight_number == "SY739"
        assert (result.flights[0].dep_airport, result.flights[0].arr_airport) == ("DFW", "PUJ")

    def test_frontier_simple_confirmation_row(self):
        from app.services.parser import parse_email

        result = parse_email(
            html="",
            plain_text=(
                "Trip Confirmation Number: D7S3FZ ORLANDO, FL (MCO) RALEIGH/DURHAM, NC (RDU) "
                "Depart: Fri, Dec 14, 2018 Flight Departure Arrival Duration F9 1712 "
                "09:03 AM ORLANDO, FL (MCO) 10:55 AM RALEIGH/DURHAM, NC (RDU) 1hr 52min"
            ),
            attachments=[],
            user_name="",
            aliases=[],
        )

        assert len(result.flights) == 1
        assert result.flights[0].flight_number == "F91712"
        assert result.flights[0].pnr == "D7S3FZ"

    def test_delta_receipt_itinerary_row(self):
        from app.services.parser import parse_email

        result = parse_email(
            html="",
            plain_text=(
                "Your Trip Confirmation #: GVPIAT Fri, 08FEB DEPART ARRIVE DELTA 1353 "
                "Basic Economy (E) NYC-KENNEDY 5:15pm SAN FRANCISCO, CA 8:59pm"
            ),
            attachments=[],
            user_name="",
            aliases=[],
            received_at="Fri, 01 Feb 2019 12:00:00 +0000",
        )

        assert len(result.flights) == 1
        assert result.flights[0].flight_number == "DL1353"
        assert (result.flights[0].dep_airport, result.flights[0].arr_airport) == ("JFK", "SFO")

    def test_expedia_flight_rows_parse_each_segment(self):
        from app.services.parser import parse_email

        result = parse_email(
            html="",
            plain_text=(
                "Itinerary # 72252633231840 Dallas (DFW) to Denver (DEN) Frontier Airlines 507 "
                "6:00am Dallas, TX, United States (DFW-Dallas-Fort Worth Intl.) to Denver, CO, "
                "United States (DEN-Denver Intl.) Economy Fri, Mar 4, 6:00am - 7:12am 2h 12m "
                "flight duration Denver (DEN) to Dallas (DFW) Frontier Airlines 506 8:00pm "
                "Denver, CO, United States (DEN-Denver Intl.) to Dallas, TX, United States "
                "(DFW-Dallas-Fort Worth Intl.) Fri, Mar 11, 8:00pm - 10:56pm 1h 56m flight duration"
            ),
            attachments=[],
            user_name="",
            aliases=[],
            received_at="Sat, 19 Feb 2022 12:00:00 +0000",
        )

        assert [flight.flight_number for flight in result.flights] == ["F9507", "F9506"]

    def test_ba_eticket_row_infers_airports_from_places(self):
        from app.services.parser import parse_email

        result = parse_email(
            html="",
            plain_text=(
                "British Airways booking reference: TEHAV3 AA1044: American Airlines | Economy | Confirmed "
                "Depart: 27 Sep 2023 19:21 - Dallas Ft Worth (TX) (Dallas) - Terminal 0 "
                "Arrive: 27 Sep 2023 21:19 - Nashville International (TN) Passenger list MR NATHAN HENNIGH"
            ),
            attachments=[],
            user_name="",
            aliases=[],
        )

        assert len(result.flights) == 1
        assert result.flights[0].flight_number == "AA1044"
        assert (result.flights[0].dep_airport, result.flights[0].arr_airport) == ("DFW", "BNA")

    def test_lifemiles_award_table_parses_segments(self):
        from app.services.parser import parse_email

        result = parse_email(
            html="",
            plain_text=(
                "Your reservation code: 4ZVDLA Flight 1 UA2371 New York(LGA) - Houston(IAH) "
                "Departure: April, 8 th, 2025 07:45 Arrival: April, 8 th, 2025 10:48 "
                "Flight 2 UA1297 Houston(IAH) - New York(LGA) Departure: April, 14 th, 2025 14:30 "
                "Arrival: April, 14 th, 2025 19:07"
            ),
            attachments=[],
            user_name="",
            aliases=[],
        )

        assert [flight.flight_number for flight in result.flights] == ["UA2371", "UA1297"]

    def test_iberia_purchase_details_parse_connection_without_cross_pairing(self):
        from app.services.parser import parse_email

        result = parse_email(
            html="",
            plain_text=(
                "The receipts of your purchase for the booking MEQQ0 from Tangier, Morocco to Madrid, Spain "
                "Tuesday, June 7, 2022 IB8797 Flight operated by Iberia Regional Air Nostrum Departure 12:25 h "
                "Tangier (Tangier) Arrival 14:50 h Madrid (Madrid) from Madrid, Spain to Palma de Mallorca, Spain "
                "Tuesday, June 7, 2022 IB3912 Flight operated by Iberia Express Departure 15:45 h Madrid (Madrid) "
                "Arrival 17:10 h Palma de Mallorca (Palma de Mallorca)"
            ),
            attachments=[],
            user_name="",
            aliases=[],
        )

        assert [flight.flight_number for flight in result.flights] == ["IB8797", "IB3912"]
        assert [(flight.dep_airport, flight.arr_airport) for flight in result.flights] == [
            ("TNG", "MAD"),
            ("MAD", "PMI"),
        ]

    def test_priceline_forwarded_checkin_omits_repeated_depart_arrive_labels(self):
        from app.services.parser import parse_email

        result = parse_email(
            html="",
            plain_text=(
                "Check in now for Emirates Airlines Flight 720 from NBO to DXB, Confirmation NPDTXW "
                "Emirates Airlines Flight 720 Departs: Jomo Kenyatta Intl Airport (NBO) "
                "Friday, January 10 2020 at 4:50 PM Arrives: Dubai Intl Airport (DXB) "
                "Friday, January 10 2020 at 10:50 PM Terminal: 1B"
            ),
            attachments=[],
            user_name="",
            aliases=[],
        )

        assert len(result.flights) == 1
        assert result.flights[0].flight_number == "EK720"
        assert (result.flights[0].dep_airport, result.flights[0].arr_airport) == ("NBO", "DXB")

    def test_united_forwarded_reservation_table_parses_segments(self):
        from app.services.parser import parse_email

        result = parse_email(
            html="",
            plain_text=(
                "Itinerary for Record Locator BB8851 UAL Record Locator OB5PJV "
                "Fri 11Dec 2020 United Airlines 3462 Dallas Dallas/Fort Worth Intl Apt, US "
                "Terminal:E 02:20 PM Chicago O'Hare International Apt, US Terminal:2 04:45 PM "
                "Duration: 2h 25m United Airlines 907 Chicago O'Hare International Apt, US "
                "Terminal:1 06:35 PM Frankfurt International Apt, DE Terminal:1 09:45 AM Duration: 8h 10m"
            ),
            attachments=[],
            user_name="",
            aliases=[],
        )

        assert [flight.flight_number for flight in result.flights] == ["UA3462", "UA907"]
        assert [(flight.dep_airport, flight.arr_airport) for flight in result.flights] == [
            ("DFW", "ORD"),
            ("ORD", "FRA"),
        ]

    def test_alaska_partner_confirmation_parses_operating_airline(self):
        from app.services.parser import parse_email

        result = parse_email(
            html="",
            plain_text=(
                "Confirmation code: LGCOFH Flight information Flight: American 2787 "
                "Departs: Nashville (BNA) on Tue, Mar 24, 2026 at 6:00 am "
                "Arrives: Dallas-Ft. Worth, TX (DFW) on Tue, Mar 24, 2026 at 8:25 am"
            ),
            attachments=[],
            user_name="",
            aliases=[],
        )

        assert len(result.flights) == 1
        assert result.flights[0].flight_number == "AA2787"
        assert result.flights[0].pnr == "LGCOFH"

    def test_justfly_booking_shell_without_itinerary_does_not_parse(self):
        from app.services.parser import parse_email

        result = parse_email(
            html=(
                "You're all set! To view or print your boarding pass, go to your airline's "
                "website and enter your confirmation number. JustFly Booking Number: 218-974-582 "
                "Ethiopian Airlines Confirmation Number: UTIKKU Manage my Booking"
            ),
            plain_text="",
            attachments=[],
            user_name="",
            aliases=[],
            subject="Re: Your trip confirmation and receipt",
            from_email="David Hennigh <davidandjuliahennigh@gmail.com>",
        )

        assert result.flights == []

    def test_legacy_terminal_itinerary_parses_without_forward_wrapper(self):
        import json

        from app.services.parser import parse_email

        fixture = json.loads(
            (FIXTURES / "regressions" / "gmail.com__Fwd_Important_Information_Regarding_Your__176e6a1ed4.json")
            .read_text(encoding="utf-8")
        )
        body = fixture["plain_text"].split("Dear DAVID HENNIGH,", 1)[1]

        result = parse_email(
            html="",
            plain_text=body,
            attachments=[],
            user_name="",
            aliases=[],
            received_at=fixture["received_at"],
            subject="Important Information Regarding Your Travel to Nairobi",
            from_email="travel@example.com",
        )

        assert len(result.flights) == 6
        assert [(flight.dep_airport, flight.arr_airport) for flight in result.flights] == [
            ("DFW", "ORD"),
            ("ORD", "FRA"),
            ("FRA", "NBO"),
            ("NBO", "FRA"),
            ("FRA", "EWR"),
            ("EWR", "DFW"),
        ]

    def test_ba_eticket_itinerary_vertical_receipt_parses(self):
        from app.services.parser import parse_email

        result = parse_email(
            html="",
            plain_text=(
                "Your Itinerary\n"
                "ABC123\n"
                "American Airlines | Economy | Confirmed\n"
                "27 Sep 2023\n"
                "19:21\n"
                "Dallas Ft Worth (TX) (Dallas)\n"
                "Terminal 0\n"
                "27 Sep 2023\n"
                "21:19\n"
                "Nashville International (TN)\n"
                "Passenger MR NATHAN HENNIGH"
            ),
            attachments=[],
            user_name="",
            aliases=[],
            subject="Fwd: Your e-ticket receipt TEHAV3: 27 Sep 2023 19:21",
        )

        assert len(result.flights) == 1
        flight = result.flights[0]
        assert (flight.dep_airport, flight.arr_airport) == ("DFW", "BNA")
        assert flight.airline == "AA"
        assert flight.dep_time.hour == 19
        assert flight.arr_time.hour == 21

    def test_frontier_departing_row_parses_without_confirmation_shell(self):
        from app.services.parser import parse_email

        result = parse_email(
            html="",
            plain_text=(
                "Departing Flight 3283 Mar. 11, 2024 BWI 1:34 PM DFW 4:15 PM "
                "Total Time: 03 hrs 41 min | Non-Stop"
            ),
            attachments=[],
            user_name="",
            aliases=[],
            subject="Important information for your upcoming trip",
        )

        assert len(result.flights) == 1
        flight = result.flights[0]
        assert (flight.dep_airport, flight.arr_airport) == ("BWI", "DFW")
        assert flight.flight_number == "F93283"

    def test_southwest_sparse_trip_email_parses_route_and_date(self):
        from datetime import datetime, timezone

        from app.services.parser import parse_email

        result = parse_email(
            html="",
            plain_text=(
                "January 16\n"
                "PNS\n"
                "TPA\n"
                "Pensacola to Tampa\n"
                "Full itinerary\n"
                "Confirmation # ABC123"
            ),
            attachments=[],
            user_name="",
            aliases=[],
            received_at=datetime(2021, 12, 17, tzinfo=timezone.utc),
            subject="Fwd: Your 01/16 trip to Tampa is all set.",
        )

        assert len(result.flights) == 1
        flight = result.flights[0]
        assert (flight.dep_airport, flight.arr_airport) == ("PNS", "TPA")
        assert flight.airline == "WN"
        assert flight.dep_time.year == 2022
        assert flight.dep_time.month == 1
        assert flight.dep_time.day == 16

    def test_southwest_sparse_trip_email_parses_parenthesized_place_names(self):
        from datetime import datetime, timezone

        from app.services.parser import parse_email

        result = parse_email(
            html="",
            plain_text=(
                "January 14\n"
                "BNA\n"
                "DAL\n"
                "Nashville to Dallas (Love)\n"
                "Full itinerary\n"
                "Confirmation # ABC123"
            ),
            attachments=[],
            user_name="",
            aliases=[],
            received_at=datetime(2021, 12, 17, tzinfo=timezone.utc),
            subject="Fwd: Your 01/14 trip to Dallas (Love) is all set.",
        )

        assert len(result.flights) == 1
        flight = result.flights[0]
        assert (flight.dep_airport, flight.arr_airport) == ("BNA", "DAL")
        assert flight.airline == "WN"
        assert flight.dep_time.year == 2022

    def test_subject_place_route_parses_direct_or_forwarded_email(self):
        from app.services.parser import parse_email

        result = parse_email(
            html="",
            plain_text=(
                "Attached to this email is the E-Ticket Itinerary Receipt that "
                "includes all your flight details."
            ),
            attachments=[],
            user_name="",
            aliases=[],
            subject=(
                "Confirmation and E-Ticket Flight Itinerary for 67RXDT from Houston "
                "George Bush Intercontinental Ap to Chicago O'Hare on 18Jun25 for HENNIGH"
            ),
        )

        assert len(result.flights) == 1
        flight = result.flights[0]
        assert (flight.dep_airport, flight.arr_airport) == ("IAH", "ORD")
        assert flight.dep_time.year == 2025
        assert flight.dep_time.month == 6
        assert flight.dep_time.day == 18
