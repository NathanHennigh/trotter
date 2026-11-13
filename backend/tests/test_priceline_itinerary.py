"""Bounded, anonymous Priceline cards: no received-date or cross-product guesses."""
from datetime import datetime
from html import escape
from copy import deepcopy
import base64

import pytest

from app.services.flight_times import normalize_flight_times
from app.services.parser import ParsedFlight
from app.services.parser_preprocess import prepare_parser_text
from app.services.priceline_itinerary import extract_priceline_itinerary, has_priceline_flight_itinerary


CARRIERS = {"delta air lines": "DL", "emirates airlines": "EK"}


def itinerary():
    return """Your Flight Confirmation for Sun, December 22, 2024
Priceline Trip Number: 321-654-987-10
Sun Dec 22 2024 - Fri Jan 10 2025
To view your airline confirmation numbers, click here.
This trip is a combination of 2 one-way tickets.
Passengers
and Tickets:
Alex Jordan Taylor
JFK
>
NBO
: 0061234567890
NBO
>
EWR
: 1761234567890
Sun Dec 22
Sun Dec 22
New York City
Nairobi
1 one-way ticket
JFK
AMS
JFK
AMS
06:00 PM - 07:20 AM
Overnight Flight
Delta Air Lines Flight 901
Operated by Example Partner
7h 20m, 3,631 miles
Depart:
Airport (JFK), New York
Arrive:
Airport (AMS), Amsterdam
Economy Class - Example aircraft
4h 40m layover in Amsterdam
AMS
NBO
12:00 PM - 10:00 PM
Delta Air Lines Flight 902
8h 0m, 4,146 miles
Depart:
Airport (AMS), Amsterdam
Arrive:
Airport (NBO), Nairobi
Economy Class
Free cancellation until 11:29 PM ET on 11/04/2024.
Fri Jan 10
Fri Jan 10
Nairobi
Newark
1 one-way ticket
NBO
DXB
04:50 PM - 10:50 PM
Emirates Airlines Flight 903
5h 0m, 2,210 miles
Depart:
Airport (NBO), Nairobi
Arrive:
Airport (DXB), Dubai
Economy Class
4h 5m layover in Dubai
DXB
EWR
02:55 AM - 07:55 AM
Emirates Airlines Flight 904
14h 0m, 6,843 miles
Depart:
Airport (DXB), Dubai
Arrive:
Airport (EWR), Newark
Economy Class
This itinerary departs from JFK and returns to EWR
Important Information
Summary of Charges
Billing Name: Jamie Example
Purchase Date November 1, 2024
Hotel promotions
Tue Jan 14
02:00 PM - 11:00 AM
Car rental pick up 05:00 AM
"""


def parse(text):
    return extract_priceline_itinerary(text, airline_codes=CARRIERS)


def normalized(text):
    values = parse(text)
    assert values
    flights = [ParsedFlight(**value) for value in values]
    for flight in flights:
        normalize_flight_times(flight)
        assert flight.time_provenance["status"] == "normalized"
    return flights


@pytest.mark.parametrize("style", ["visible", "quoted_plain", "html", "inline_labels", "unicode"])
def test_complete_cards_have_exact_local_dates_and_one_time_conversion(style):
    text = itinerary()
    if style == "quoted_plain":
        text = "\n".join("> *" + line + "*" for line in text.splitlines())
    elif style == "html":
        html = "<div>" + "</div><div>".join(escape(line) for line in text.splitlines()) + "</div>"
        text = prepare_parser_text(html=html, plain_text="Unrelated MIME alternative").structural_text
    elif style == "inline_labels":
        text = text.replace("Depart:\n", "Depart: ").replace("Arrive:\n", "Arrive: ")
    elif style == "unicode":
        text = text.replace(" - ", " – ").replace(" ", "\xa0")
    values = parse(text)
    assert len(values) == 4
    assert [v["dep_time"].date().isoformat() for v in values] == ["2024-12-22", "2024-12-23", "2025-01-10", "2025-01-11"]
    flights = normalized(text)
    assert [(f.flight_number, f.dep_airport, f.arr_airport, f.dep_time.isoformat(), f.arr_time.isoformat()) for f in flights] == [
        ("DL901", "JFK", "AMS", "2024-12-22T23:00:00+00:00", "2024-12-23T06:20:00+00:00"),
        ("DL902", "AMS", "NBO", "2024-12-23T11:00:00+00:00", "2024-12-23T19:00:00+00:00"),
        ("EK903", "NBO", "DXB", "2025-01-10T13:50:00+00:00", "2025-01-10T18:50:00+00:00"),
        ("EK904", "DXB", "EWR", "2025-01-10T22:55:00+00:00", "2025-01-11T12:55:00+00:00")]
    assert all(f.pnr is None and f.pnr_aliases == [] and f.passenger_names == [] and f.ownership == "unknown" for f in flights)
    assert [f.source_leg["sequence"] for f in flights] == [1, 2, 3, 4]
    assert len({f.source_leg["key"] for f in flights}) == 4
    for f in flights:
        assert f.source == "shape_priceline_trip_cards"
        assert f.source_leg["ambiguous"] is False
        assert len(f.source_leg["key"]) == 64
        proof = f.time_provenance["date_evidence"]
        assert proof["document_date_range"] == ["2024-12-22", "2025-01-10"]
        assert proof["status"] == "verified"
        before = (f.dep_time, f.arr_time)
        normalize_flight_times(f)
        assert (f.dep_time, f.arr_time) == before


def test_journey_ticket_scopes_are_separate_and_exact():
    values = parse(itinerary())
    assert [v["source_leg"]["journey_scope"] for v in values] == [
        {"dep_airport": "JFK", "arr_airport": "NBO", "departure_date": "2024-12-22"}] * 2 + [
        {"dep_airport": "NBO", "arr_airport": "EWR", "departure_date": "2025-01-10"}] * 2
    assert [v["time_provenance"]["date_evidence"]["preceding_printed_layover_minutes"] for v in values] == [None, 280, None, 245]


def test_document_key_does_not_depend_on_interpreted_carrier_catalog():
    original = parse(itinerary())
    revised_catalog = {**CARRIERS, "delta air lines": "ZZ"}
    revised = extract_priceline_itinerary(itinerary(), airline_codes=revised_catalog)
    assert original[0]["flight_number"] != revised[0]["flight_number"]
    assert [v["source_leg"]["key"] for v in original] == [v["source_leg"]["key"] for v in revised]


@pytest.mark.parametrize(("old", "new"), [
    ("Sun Dec 22 2024 - Fri Jan 10 2025", "Sun Dec 22 - Fri Jan 10"),
    ("Sun Dec 22 2024 - Fri Jan 10 2025", "Sun Dec 22 2024 - Fri Jan 10 2024"),
    ("Sun Dec 22 2024 - Fri Jan 10 2025", "Mon Dec 22 2024 - Fri Jan 10 2025"),
    ("Sun Dec 22 2024 - Fri Jan 10 2025", "Sun Dec 32 2024 - Fri Jan 10 2025"),
    ("Sun Dec 22\nSun Dec 22", "Mon Dec 22\nMon Dec 22"),
    ("Sun Dec 22\nSun Dec 22", ""),
    ("Fri Jan 10\nFri Jan 10", ""),
    ("06:00 PM - 07:20 AM", "06:00 - 07:20 AM"),
    ("06:00 PM - 07:20 AM", "00:00 PM - 07:20 AM"),
    ("06:00 PM - 07:20 AM", "06:00 PM - 07:25 AM"),
    ("12:00 PM - 10:00 PM", ""),
    ("12:00 PM - 10:00 PM", "12:05 PM - 10:05 PM"),
    ("7h 20m, 3,631 miles", ""),
    ("7h 20m, 3,631 miles", "7h 70m, 3,631 miles"),
    ("7h 20m, 3,631 miles", "7h 25m, 3,631 miles"),
    ("4h 40m layover in Amsterdam", ""),
    ("4h 40m layover in Amsterdam", "4h 45m layover in Amsterdam"),
    ("4h 40m layover in Amsterdam", "4h 70m layover in Amsterdam"),
    ("4h 40m layover in Amsterdam", "about four hours layover in Amsterdam"),
    ("4h 40m layover in Amsterdam", "4h 40m layover in Paris"),
    ("4h 5m layover in Dubai", "4h 5m layover in Dubai\n4h 5m layover in Dubai"),
    ("Airport (AMS), Amsterdam", "Airport (ZZZ), Unknown"),
    ("Airport (AMS), Amsterdam", "Airport (AMS) or (CDG), ambiguous"),
    ("Delta Air Lines Flight 901", "Unmapped Carrier Flight 901"),
    ("Delta Air Lines Flight 901", "Delta Air Lines Flight 901\nDelta Air Lines Flight 905"),
    ("Depart:\nAirport (JFK), New York", "Depart:\nAirport (JFK), New York\nDepart:\nAirport (JFK), New York"),
    ("Arrive:\nAirport (NBO), Nairobi", "Arrive:\nAirport (NBO), Nairobi\nOvernight Flight"),
    ("Economy Class\nThis itinerary", "Economy Class\n2h 0m layover in Newark\nThis itinerary"),
])
def test_recognized_incomplete_or_contradictory_document_is_held(old, new):
    assert old in itinerary()
    assert parse(itinerary().replace(old, new)) == []


def test_duplicate_complete_documents_are_held_not_deduplicated_into_authority():
    assert parse(itinerary() + itinerary()) == []


def test_second_conflicting_range_is_held():
    assert parse(itinerary().replace("Passengers\n", "Sun Dec 22 2024 - Sat Jan 11 2025\nPassengers\n")) == []


def test_connection_rolls_year_only_with_exact_elapsed_proof():
    text = itinerary().replace("Sun, December 22", "Tue, December 31").replace("Sun Dec 22", "Tue Dec 31")
    flights = normalized(text)
    assert flights[0].arr_time == datetime.fromisoformat("2025-01-01T06:20:00+00:00")
    assert flights[1].dep_time == datetime.fromisoformat("2025-01-01T11:00:00+00:00")


def test_received_and_forwarded_dates_never_supply_travel_year():
    prefix = "Date: Friday, January 5, 2035\nForwarded message: Monday, March 12, 2040\n"
    assert parse(prefix + itinerary()) == parse(itinerary())
    assert parse(prefix + itinerary().replace("Sun Dec 22 2024 - Fri Jan 10 2025", "")) == []


def test_unrecognized_layout_remains_available_to_other_extractors():
    assert parse("Delta Air Lines Flight 901\n06:00 PM - 07:20 AM") is None
    assert parse("Priceline Trip Number: 321-654-987-10\nHotel reservation") is None
    assert parse("Your Flight Confirmation\nPriceline Trip Number: 321-654-987-10\nBroken card") == []


@pytest.mark.parametrize(("departure", "arrival", "day"), [
    ("01:30 AM", "02:30 PM", "Sun Nov 03 2024"),  # repeated local hour
    ("02:30 AM", "02:30 PM", "Sun Mar 10 2024"),  # nonexistent local hour
])
def test_ambiguous_or_nonexistent_airport_local_clock_is_held(departure, arrival, day):
    text = f"""Your Flight Confirmation
Priceline Trip Number: 123-456-789-00
{day} - {day}
{day.rsplit(' ', 1)[0]}
{departure} - {arrival}
Delta Air Lines Flight 901
7h 0m
Depart: Airport (JFK)
Arrive: Airport (AMS)
"""
    assert parse(text) == []


@pytest.mark.parametrize("broken", ["12:00 PM - 10:00 PM", "14h 0m, 6,843 miles"])
def test_public_parser_does_not_fall_back_for_incomplete_sibling_card(broken):
    from app.services.parser import parse_email
    from app.models import MessageStatus
    result = parse_email(html="", plain_text=itinerary().replace(broken, ""), attachments=[],
                         subject="Your Priceline itinerary", user_name="Alex Jordan Taylor", aliases=[],
                         received_at="2035-01-01T12:00:00Z")
    assert result.flights == []
    assert result.status == MessageStatus.REVIEW_REQUIRED


def test_unrelated_trip_number_does_not_block_existing_valid_agency_layout():
    from app.services.parser import parse_email
    from test_parser_marked_schedule_changes import CARD
    kwargs = dict(html="", attachments=[], subject="Changed flight details", user_name="Alex Taylor",
                  aliases=[], received_at="2027-01-01T12:00:00Z")
    original, = parse_email(plain_text=CARD, **kwargs).flights
    result, = parse_email(plain_text="Priceline Trip Number: 321-654-987-10\n" + CARD, **kwargs).flights
    assert result == original
    assert result.source == "shape_labeled_agency_card"
    assert not has_priceline_flight_itinerary("Priceline Trip Number: 321-654-987-10\n" + CARD)


@pytest.mark.parametrize("inline_headings", [False, True])
def test_later_reminder_without_confirmation_title_keeps_explicit_changed_clock(inline_headings):
    text = itinerary().replace("Your Flight Confirmation for Sun, December 22, 2024", "Thanks for booking your flight with priceline.com.")
    text = text.replace("Priceline Trip Number:", "Priceline\nTrip Number:")
    text = text.replace("4h 5m layover in Dubai", "3h 50m layover in Dubai").replace("02:55 AM", "02:40 AM").replace("14h 0m", "14h 15m")
    if inline_headings:
        text = text.replace("Sun Dec 22\nSun Dec 22", "Sun Dec 22 New York City Nairobi 2 one way ticket(s)").replace("Fri Jan 10\nFri Jan 10", "Fri Jan 10 Nairobi Newark 2 one way ticket(s)")
    assert has_priceline_flight_itinerary(text)
    result = normalized(text)
    assert len(result) == 4
    assert result[-1].dep_time.isoformat() == "2025-01-10T22:40:00+00:00"
    assert result[-1].arr_time.isoformat() == "2025-01-11T12:55:00+00:00"
    assert result[-1].time_provenance["date_evidence"]["preceding_printed_layover_minutes"] == 230


def one_way():
    return """Thanks for booking your flight with priceline.com.
Priceline
Trip Number: 123-456-789-10
Need a Rental Car?
Pick-up: Sat January 11 - 03:30 PM
Drop-off: Sun January 12 - 02:30 PM
Newark, NJ Dallas, TX
Sat Jan 11 2025 - Sat Jan 11 2025
Airline Confirmation Numbers
American Airlines: TEST12
Passengers:
Alex Jordan Taylor
Ticket Number: 0011234567890
Sat Jan 11 Newark Dallas
EWR DFW
12:02 PM - 03:07 PM
American Airlines Flight 905
4h 5m, 1,369 miles
Depart: Airport (EWR), Newark
Arrive: Airport (DFW), Dallas
Important Information
Add a Hotel
Check-in: Sat January 11
"""


def test_one_way_ignores_rental_promotion_dates_and_keeps_single_dated_flight():
    from app.services.parser import parse_email
    text = one_way()
    assert has_priceline_flight_itinerary(text)
    result = extract_priceline_itinerary(text, airline_codes={"american airlines": "AA"})
    assert len(result) == 1
    assert result[0]["dep_time"].isoformat() == "2025-01-11T12:02:00+00:00"
    parsed = parse_email(html="", plain_text=text, attachments=[], user_name="Alex Jordan Taylor", aliases=[], received_at="2025-01-09T12:00:00Z")
    flight, = parsed.flights
    assert (flight.flight_number, flight.pnr, flight.dep_time.isoformat(), flight.arr_time.isoformat()) == ("AA905", "TEST12", "2025-01-11T17:02:00+00:00", "2025-01-11T21:07:00+00:00")


def test_damaged_one_way_without_title_still_cannot_use_loose_clock_defaults():
    assert extract_priceline_itinerary(one_way().replace("12:02 PM - 03:07 PM", ""), airline_codes={"american airlines": "AA"}) == []


def test_split_range_and_contradictory_section_dates_remain_recognized_but_held():
    text = itinerary().replace("Your Flight Confirmation for Sun, December 22, 2024", "Congrats, your flight on Sunday, December 22, 2024 is confirmed!")
    text = text.replace("Sun Dec 22 2024 - Fri Jan 10 2025", "Monday, December 23, 2024\n-\nFriday, January 10, 2025")
    assert has_priceline_flight_itinerary(text)
    assert parse(text) == []


from test_booking_import_worker import worker, run


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("broken", ["12:00 PM - 10:00 PM", "14h 0m, 6,843 miles", "contradictory_section_date"])
def test_incomplete_cards_remain_unresolved_through_actual_worker(worker, monkeypatch, enabled, broken):
    from app.models import Message, MessageStatus, Segment, Trip, User
    from app.services import flight_query_v4, gmail
    from app.services.flight_import_rollout import FEATURE_FLAGS, ALLOWLIST_ENV
    from app.services.flight_query_v4 import DiscoveryCandidate
    factory, user_id, _ = worker
    for flag in FEATURE_FLAGS:
        monkeypatch.setenv(flag, str(enabled).lower())
    monkeypatch.setenv(ALLOWLIST_ENV, str(user_id))
    text = (itinerary().replace("Sun Dec 22 2024 - Fri Jan 10 2025", "Monday, December 23, 2024\n-\nFriday, January 10, 2025")
            .replace("Your Flight Confirmation for Sun, December 22, 2024", "Congrats, your flight on Sunday, December 22, 2024 is confirmed!")
            if broken == "contradictory_section_date" else itinerary().replace(broken, ""))
    source = {"id": "incomplete-trip-cards", "internalDate": "1730462400000",
              "snippet": "Your Priceline flight confirmation",
              "payload": {"mimeType": "text/plain", "headers": [
                  {"name": "Subject", "value": "Your Priceline itinerary"},
                  {"name": "From", "value": "ItineraryAir@trans.priceline.com"},
                  {"name": "Date", "value": "Fri, 1 Nov 2024 12:00:00 +0000"}],
                  "body": {"data": base64.urlsafe_b64encode(text.encode()).decode()}}}
    original_source = deepcopy(source)
    retained_partial = {"version": 1, "reason": "incomplete_card", "printed_route": ["AMS", "NBO"]}
    with factory() as db:
        db.get(User, user_id).name = "Alex Jordan Taylor"
        message = Message(user_id=user_id, provider_msg_id=source["id"], status=MessageStatus.REVIEW_REQUIRED,
                          ignored=False, parse_version=1,
                          parse_evidence={"resolved": False, "partial_flight_evidence": retained_partial})
        db.add(message)
        db.commit()
        message_id = message.id
    monkeypatch.setattr(gmail, "batch_get_messages", lambda service, ids: ({key: source for key in ids}, {}))
    monkeypatch.setattr(gmail, "get_message", lambda service, key: source)
    monkeypatch.setattr(flight_query_v4, "iter_discovery_messages", lambda service, plan: [
        DiscoveryCandidate({"id": source["id"]}, "fixture", "offline", False)] if plan else [])
    for repeat in range(2):
        run(factory, user_id, "reparse", f"incomplete-priceline-{repeat}")
        with factory() as db:
            message = db.get(Message, message_id)
            assert message.provider_msg_id == source["id"]
            assert message.status == MessageStatus.REVIEW_REQUIRED
            assert message.ignored is False
            assert message.parse_evidence.get("resolved") is False
            evidence = message.parse_evidence
            assert retained_partial == evidence.get("partial_flight_evidence") or retained_partial in evidence.get("partial_flight_evidence_history", [])
            assert db.query(Segment).count() == 0
            assert db.query(Trip).count() == 0
    assert source == original_source
