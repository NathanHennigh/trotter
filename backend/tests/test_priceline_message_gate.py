"""Dated agency cards warrant extraction; dates and ownership remain separate proofs."""
from html import escape

import pytest

from app.services.flight_evidence import assess_flight_evidence
from app.services.flight_message import prepare_flight_message
from app.services.parser import parse_email
from test_parser_message_alternatives import message
from test_priceline_itinerary import itinerary, one_way


def _html(text):
    return "<div>" + "</div><div>".join(escape(line) for line in text.splitlines()) + "</div>"


@pytest.mark.parametrize("as_html", [False, True])
def test_dated_cards_survive_other_travel_promotions_without_clock_or_name_guesses(as_html):
    text = one_way()
    raw = message("Deals. Book now. Rental car." if as_html else text, _html(text) if as_html else "")
    result = prepare_flight_message(raw, user_name="Alex Jordan Taylor", aliases=[])
    assert result["evidence"].verdict == "parse"
    assert "dated_agency_flight_cards" in result["evidence"].signals
    flight, = result["parse_result"].flights
    assert (flight.flight_number, flight.pnr, flight.ownership) == ("AA905", "TEST12", "self")
    assert flight.dep_time.isoformat() == "2025-01-11T17:02:00+00:00"
    assert flight.arr_time.isoformat() == "2025-01-11T21:07:00+00:00"
    assert flight.source_leg["booking_references"] == {"primary": "TEST12", "aliases": []}


@pytest.mark.parametrize("as_html", [False, True])
def test_contradictory_dated_cards_are_reviewed_without_heuristic_fallback(as_html):
    text = itinerary().replace("Your Flight Confirmation for Sun, December 22, 2024", "Your upcoming journey")
    text = text.replace("Sun Dec 22 2024 - Fri Jan 10 2025", "Monday, December 23, 2024\n-\nFriday, January 10, 2025")
    result = prepare_flight_message(message("" if as_html else text, _html(text) if as_html else ""),
                                    user_name="Alex Jordan Taylor", aliases=[])
    assert result["evidence"].verdict == "parse"
    assert "dated_agency_flight_cards" in result["evidence"].signals
    assert result["parse_result"].status.value == "review_required"
    assert result["parse_result"].flights == []


@pytest.mark.parametrize("wrapper", ["template", "noscript", 'div hidden', 'div style="display:none"'])
def test_inert_agency_cards_cannot_admit_an_unrelated_message(wrapper):
    html = "<body>Weekly deals.<" + wrapper + ">" + _html(one_way()) + "</" + wrapper.split()[0] + "></body>"
    result = prepare_flight_message(message("Deals. Book now.", html), user_name="Alex Jordan Taylor", aliases=[])
    assert result["evidence"].verdict == "skip"
    assert result["parse_result"] is None


def test_trip_number_and_rental_dates_alone_do_not_admit_cards():
    evidence = assess_flight_evidence(subject="Your upcoming journey", sender="booking@example.test",
        body="Priceline Trip Number: 123-456-789-10\nSat Jan 11 2025 - Sat Jan 11 2025\nNeed a Rental Car?\n12:02 PM - 03:07 PM\nAdd a Hotel")
    assert "dated_agency_flight_cards" not in evidence.signals
    assert evidence.verdict == "skip"


@pytest.mark.parametrize("references,expected", [
    ("Confirmation code: OTHER1", None),
    ("Airline Confirmation Numbers\nDelta Air Lines: OTHER1", None),
    ("Airline Confirmation Numbers\nAmerican Airlines: TEST12\nConfirmation code: OTHER1", "TEST12"),
    ("Airline Confirmation Numbers\nAmerican Airlines: TEST12\nAmerican Airlines Confirmation code: TEST12", "TEST12"),
    ("Airline Confirmation Numbers\nAmerican Airlines: TEST12\nAmerican Airlines Confirmation code: OTHER1", None),
])
def test_only_one_explicit_carrier_reference_can_bind_to_its_cards(references, expected):
    text = one_way().replace("Airline Confirmation Numbers\nAmerican Airlines: TEST12", references)
    parsed = parse_email(html="", plain_text=text, attachments=[], user_name="Alex Jordan Taylor", aliases=[])
    flight, = parsed.flights
    assert flight.pnr == expected
    assert flight.pnr_aliases == []
    if expected:
        assert flight.source_leg["booking_references"] == {"primary": expected, "aliases": []}
    else:
        assert not flight.source_leg.get("booking_references")
