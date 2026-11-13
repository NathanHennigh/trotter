"""Malformed document repair must preserve body visibility boundaries."""
import pytest

from app.services.flight_evidence import assess_flight_evidence, _flight_numbers
from app.services.html_visibility import visible_html_soup
from app.services.parser_preprocess import prepare_parser_text
from app.services.parser import _html_to_parser_text, _html_table_text_only


ITINERARY = """<table><tr><td>Confirmation code: TEST12</td></tr>
<tr><td>Flight AA901</td><td>SEA to DFW</td></tr>
<tr><td>July 12, 2027</td><td>Departure 10:20 AM</td><td>Arrival 4:15 PM</td></tr>
<tr><td>Passenger</td><td>Alex Taylor</td></tr></table>"""


def gate(html):
    return assess_flight_evidence(subject="Your travel receipt", sender="receipts@example.test", body=html)


def test_explicit_body_survives_direct_nesting_in_unclosed_head():
    normal = "<html><head><title>Receipt</title></head><body>" + ITINERARY + "</body></html>"
    malformed = "<html><head><title>Receipt</title><body>" + ITINERARY + "</body></html>"
    assert gate(malformed) == gate(normal)
    assert gate(malformed).verdict == "parse"
    soup = visible_html_soup(malformed)
    assert soup.body and not soup.head and len(soup.find_all("tr")) == 4


@pytest.mark.parametrize("html", [
    "<html><head>" + ITINERARY + "</head></html>",
    "<html><head><template><body>" + ITINERARY + "</body></template></head></html>",
    "<html><head><script><body>" + ITINERARY + "</body></script></head></html>",
    "<html><head><style><body>" + ITINERARY + "</body></style></head></html>",
    "<html><head><noscript><body>" + ITINERARY + "</body></noscript></head></html>",
    "<template><head><body>" + ITINERARY + "</body></head></template>",
    "<html><head hidden><body>" + ITINERARY + "</body></html>",
    "<html hidden><head><body>" + ITINERARY + "</body></html>",
    "<html><head><body hidden>" + ITINERARY + "</body></html>",
    '<html><head><body style="display:none">' + ITINERARY + "</body></html>",
    '<html><head><body aria-hidden="true">' + ITINERARY + "</body></html>",
    '<html><head><body class="preheader">' + ITINERARY + "</body></html>",
    "<html><head><div><body>" + ITINERARY + "</body></div></head></html>",
    "<html><head><body>" + ITINERARY + "</body><body>Other</body></head></html>",
])
def test_inert_hidden_or_non_direct_body_cannot_be_promoted(html):
    assert gate(html).verdict == "skip"
    assert "TEST12" not in visible_html_soup(html).get_text()


def test_fake_head_fields_cannot_complete_an_unrelated_body():
    html = "<html><head>" + ITINERARY + "<body>Welcome to our weekly update.</body></html>"
    assert gate(html).verdict == "skip"
    assert "TEST12" not in visible_html_soup(html).get_text()


@pytest.mark.parametrize("wrapper", ["template", "script", "style", "noscript"])
def test_inert_subtree_in_valid_body_cannot_supply_booking_evidence(wrapper):
    html = "<body>Weekly update.<" + wrapper + ">" + ITINERARY + "</" + wrapper + "></body>"
    assert gate(html).verdict == "skip"


@pytest.mark.parametrize("wrapper", ["template", "script", "style", "noscript"])
def test_short_visible_text_fallback_cannot_restore_large_inert_ticket(wrapper):
    html = "<body>Weekly update.<" + wrapper + ">" + ITINERARY + (" hidden content " * 150) + "</" + wrapper + "></body>"
    bundle = prepare_parser_text(html=html, plain_text="")
    for view in (bundle.clean_text, bundle.structural_text, bundle.full_text,
                 _html_to_parser_text(html), _html_table_text_only(html)):
        assert "TEST12" not in view and "AA901" not in view


@pytest.mark.parametrize("body", [
    "Class schedule: 9:00 AM 5:30 PM on January 12, 2027",
    "Open studio 10:00 AM 12:15 PM on January 12, 2027",
    "January 12, 2027 workshop Fri-Sun",
    "January 12, 2027 workshop Fri–Sun",
])
def test_clock_meridiem_and_calendar_ranges_are_not_flight_evidence(body):
    evidence = assess_flight_evidence(subject="Weekly classes", sender="news@example.test", body=body)
    assert evidence.verdict == "skip"
    assert not evidence.flight_numbers and not evidence.airport_codes


@pytest.mark.parametrize("text,number", [
    ("AM5", "AM5"), ("AM5 5:30 PM", "AM5"),
    ("FLIGHT AM5:30 PM", "AM5"), ("FLIGHT NUMBER: AM5:30 PM", "AM5"),
    ("FLIGHT BA123:09:00", "BA123"), ("AM15:30 PM", "AM15"),
])
def test_genuine_or_explicit_flight_fields_survive_clock_disambiguation(text, number):
    assert number in _flight_numbers(text)


@pytest.mark.parametrize("context", ["Flight AM5", "Confirmation code TEST12", "Flight itinerary"])
def test_real_weekday_named_airport_route_with_independent_context_is_preserved(context):
    evidence = gate("SAT - SUN January 12, 2027 " + context)
    assert evidence.airport_codes == ("SAT", "SUN")
    assert evidence.verdict == "parse"
