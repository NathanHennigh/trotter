"""MIME alternatives are independently assessed, never merged into evidence."""
import base64
import json

import pytest

from app.services.flight_message import prepare_flight_message


def message(plain, html):
    def part(kind, text):
        return {"mimeType": kind, "body": {"data": base64.urlsafe_b64encode(text.encode()).decode()}}
    return {"id": "message-1", "internalDate": "1752278400000", "payload": {
        "mimeType": "multipart/alternative", "headers": [
            {"name": "From", "value": "Allegiant <notices@example.test>"},
            {"name": "Subject", "value": "Your upcoming journey"},
            {"name": "Date", "value": "Sat, 12 Jul 2025 00:00:00 +0000"}],
        "parts": [part("text/plain", plain), part("text/html", html)]}}


OPERATIONAL = """Flight Details
Confirmation # ABC123
Departure Date Thursday, September 17, 2026 at 12:27 PM
Departure Airport Orange County (SNA)
Arrival Des Moines (DSM) at 5:44 PM
"""


def test_visible_html_itinerary_survives_plain_marketing_alternative():
    html = "<div>" + OPERATIONAL.replace("\n", "</div><div>") + "</div>"
    result = prepare_flight_message(message("Deals. Credit card. Book now. Rental car.", html),
                                    user_name="Alex Avery", aliases=[])
    assert result["evidence"].verdict == "parse"
    assert "labeled_operational_block" in result["evidence"].signals
    assert result["body_for_filter"] == html
    assert result["parse_result"] is not None


def test_identical_mime_parts_reuse_html_evidence(monkeypatch):
    from unittest.mock import Mock
    from app.services import flight_message

    html = "<div>" + OPERATIONAL.replace("\n", "</div><div>") + "</div>"
    expected = prepare_flight_message(message("", html), user_name="Alex Avery", aliases=[])
    classify = Mock(wraps=flight_message._html_evidence)
    monkeypatch.setattr(flight_message, "_html_evidence", classify)
    result = prepare_flight_message(message(html, html), user_name="Alex Avery", aliases=[])

    assert result["evidence"] == expected["evidence"]
    assert result["body_for_filter"] == html
    assert result["evidence"].verdict == "parse"
    classify.assert_called_once()


def test_hidden_html_itinerary_does_not_override_plain_marketing():
    html = "<div hidden>" + OPERATIONAL + "</div><p>Deals. Book now.</p>"
    result = prepare_flight_message(message("Deals. Book now.", html), user_name="Alex Avery", aliases=[])
    assert result["evidence"].verdict == "skip"
    assert result["parse_result"] is None


def test_two_incomplete_alternatives_do_not_combine_operational_fields():
    plain = "Deals. Flight: UA321 Date: July 31, 2026"
    html = "<p>Deals. From: San Francisco (SFO) To: Orange County (SNA). Credit card.</p>"
    result = prepare_flight_message(message(plain, html), user_name="Alex Avery", aliases=[])
    assert "labeled_operational_block" not in result["evidence"].signals
    assert result["evidence"].verdict != "parse"


@pytest.mark.parametrize("plain,html", [
    ("Deals. Trade executed April 3, 2026. A simple way to get in touch.",
     "<p>Trade executed April 3, 2026. A simple way to get in touch.</p>"),
    ("View your order online.", "<p>Chai maker. Add-Ons: tea and shipping.</p>"),
    ("Deals. Show your member card when you check in with our host April 3, 2026.",
     "<p>Show your member card when you check in with our host April 3, 2026.</p>"),
    ("View your appointment online.", "<p>Medical appointment check-in April 3, 2026.</p>"),
    ("Deals. Book now. Flights FLL to IAH April 3, 2026.",
     "<p>Earn 5,000 bonus points. Flights FLL to IAH April 3, 2026.</p>"),
    ("View your card benefits online.",
     "<p>Credit card benefits April 3, 2026: applied to Uber and to any services, "
     "such as 5X bonuses. Hotel invoice and noon check-in on your itinerary.</p>"),
])
def test_incidental_html_score_does_not_promote_plain_nonflight(plain, html):
    result = prepare_flight_message(message(plain, html), user_name="Alex Avery", aliases=[])
    assert result["evidence"].verdict == "skip"
    assert result["body_for_filter"] == plain
    assert result["parse_result"] is None


@pytest.mark.parametrize("plain", ["", "View your booking online.", "Deals. Credit card. Book now."])
def test_real_html_booking_survives_empty_or_truncated_plain(plain):
    html = """<p>Flight confirmation code ABC123</p><p>Passenger: Alex Avery</p>
    <p>Flight AA123 SFO to LAX January 15, 2026</p>
    <p>Departure 8:00 AM Arrival 9:30 AM</p><p>Ticket number 0012345678901</p>"""
    result = prepare_flight_message(message(plain, html), user_name="Alex Avery", aliases=[])
    assert result["evidence"].verdict == "parse"
    assert result["body_for_filter"] == html
    assert result["parse_result"] is not None


def reservation():
    return {"@type": "FlightReservation", "reservationNumber": "ABC123",
            "underName": {"@type": "Person", "name": "Alex Avery"},
            "reservationFor": {"@type": "Flight", "flightNumber": "AA123",
                "airline": {"iataCode": "AA"}, "departureAirport": {"iataCode": "SFO"},
                "arrivalAirport": {"iataCode": "LAX"}, "departureTime": "2026-01-15T08:00:00-08:00",
                "arrivalTime": "2026-01-15T09:30:00-08:00"}}


@pytest.mark.parametrize("plain", ["", "View your booking online.", "Deals. Book now."])
def test_complete_typed_reservation_admits_html_without_visible_route(plain):
    html = '<script type="application/ld+json">' + json.dumps(reservation()) + '</script><p>View your booking.</p>'
    result = prepare_flight_message(message(plain, html), user_name="Alex Avery", aliases=[])
    assert "structured_flight_reservation" in result["evidence"].signals
    assert result["body_for_filter"] == html
    flight, = result["parse_result"].flights
    assert (flight.flight_number, flight.pnr, flight.ownership) == ("AA123", "ABC123", "self")
    assert flight.dep_time.isoformat() == "2026-01-15T16:00:00+00:00"


@pytest.mark.parametrize("mutation", ["date_only", "missing_arrival", "same_airport", "nonflight", "bad_type", "missing_number"])
def test_incomplete_or_unrelated_jsonld_cannot_supply_admission(mutation):
    item = reservation()
    flight = item['reservationFor']
    if mutation == 'date_only':
        flight['departureTime'] = '2026-01-15'
    elif mutation == 'missing_arrival':
        del flight['arrivalTime']
    elif mutation == 'same_airport':
        flight['arrivalAirport'] = {'iataCode': 'SFO'}
    elif mutation == 'nonflight':
        item['@type'] = 'Product'
    elif mutation == 'bad_type':
        item['@type'] = []
    else:
        del flight['flightNumber']
    html = '<script type="application/ld+json">' + json.dumps(item) + '</script><p>View online.</p>'
    result = prepare_flight_message(message('View online.', html), user_name='Alex Avery', aliases=[])
    assert result['evidence'].verdict == 'skip'
    assert result['parse_result'] is None


@pytest.mark.parametrize('other', [None, 1, {'@type': 'ReservationPackage', 'subReservation': [None]}])
def test_valid_jsonld_reservation_does_not_admit_malformed_siblings(other):
    html = '<script type="application/ld+json">' + json.dumps([reservation(), other]) + '</script>'
    result = prepare_flight_message(message('View online.', html), user_name='Alex Avery', aliases=[])
    assert result['evidence'].verdict == 'skip'
    assert result['parse_result'] is None


def test_valid_jsonld_reservation_does_not_admit_a_date_only_second_leg():
    other = reservation()
    other['reservationFor']['departureTime'] = '2026-01-15'
    html = '<script type="application/ld+json">' + json.dumps([reservation(), other]) + '</script>'
    result = prepare_flight_message(message('View online.', html), user_name='Alex Avery', aliases=[])
    assert result['evidence'].verdict == 'skip'
    assert result['parse_result'] is None


def test_oversized_jsonld_document_does_not_admit_unchecked_tail():
    html = '<script type="application/ld+json">' + json.dumps(reservation()) + '</script>' + (' ' * 200_000)
    result = prepare_flight_message(message('View online.', html), user_name='Alex Avery', aliases=[])
    assert result['evidence'].verdict == 'skip'
    assert result['parse_result'] is None


@pytest.mark.parametrize('raw', [
    '{"@type":"FlightReservation", invalid}',
    ('[' * 1500) + '{"@type":"FlightReservation"}' + (']' * 1500),
    '{"@type":"ReservationPackage","subReservation":[' * 10 + json.dumps(reservation()) + ']}' * 10,
])
def test_malformed_or_deep_jsonld_is_not_an_admission_error(raw):
    html = '<script type="application/ld+json">' + raw + '</script>'
    result = prepare_flight_message(message('View online.', html), user_name='Alex Avery', aliases=[])
    assert result['evidence'].verdict == 'skip'
    assert result['parse_result'] is None


@pytest.mark.parametrize('before,after', [
    ('<html><head>', '</head><body>View online.</body></html>'),
    ('<html><body>', '</body></html>'),
    ('', ''),
])
def test_normal_head_or_body_jsonld_metadata_remains_supported(before, after):
    html = before + '<script type="application/ld+json">' + json.dumps(reservation()) + '</script>' + after
    result = prepare_flight_message(message('View online.', html), user_name='Alex Avery', aliases=[])
    assert result['evidence'].verdict == 'parse'
    assert len(result['parse_result'].flights) == 1


@pytest.mark.parametrize('before,after', [
    ('<template>', '</template>'), ('<noscript>', '</noscript>'),
    ('<div hidden>', '</div>'), ('<div aria-hidden="true">', '</div>'),
    ('<div style="display:none">', '</div>'), ('<div style="visibility:hidden">', '</div>'),
    ('<div class="hidden">', '</div>'), ('<html hidden><head>', '</head></html>'),
    ('<head hidden>', '</head>'), ('<template><head>', '</head></template>'),
])
def test_hidden_or_inert_jsonld_cannot_admit_or_supply_a_flight(before, after):
    html = before + '<script type="application/ld+json">' + json.dumps(reservation()) + '</script>' + after
    result = prepare_flight_message(message('View online.', html), user_name='Alex Avery', aliases=[])
    assert result['evidence'].verdict == 'skip'
    assert result['parse_result'] is None
    forced = prepare_flight_message(message('View online.', html), user_name='Alex Avery', aliases=[], force_parse=True)
    assert not forced['parse_result'].flights


def test_hidden_script_itself_cannot_supply_jsonld():
    html = '<script hidden type="application/ld+json">' + json.dumps(reservation()) + '</script>'
    result = prepare_flight_message(message('View online.', html), user_name='Alex Avery', aliases=[])
    assert result['evidence'].verdict == 'skip'
    assert result['parse_result'] is None


CLOCKED_SUMMARY = """<p>Booking no. ABC123</p><h2>Flight summary</h2>
<p>Depart: Monday, 28 April 2025</p><p>06:45 SFO GMT-07 1h 0m Non-stop 07:45 LAX GMT-07</p>
<p>United, UA211 Economy</p><p>Add-ons</p>"""


@pytest.mark.parametrize('before,after', [
    ('<template>', '</template>'), ('<noscript>', '</noscript>'),
    ('<div hidden>', '</div>'), ('<html hidden><body>', '</body></html>'),
])
def test_inert_clocked_summary_does_not_override_plain_text(before, after):
    result = prepare_flight_message(message('View online.', before + CLOCKED_SUMMARY + after),
                                    user_name='Alex Avery', aliases=[])
    assert result['evidence'].verdict == 'skip'
    assert result['parse_result'] is None


def test_clocked_html_summary_with_separate_airport_cells_survives_short_plain():
    result = prepare_flight_message(message('Your booking is confirmed. View online.', CLOCKED_SUMMARY),
                                    user_name='Alex Avery', aliases=[])
    assert result['body_for_filter'] == CLOCKED_SUMMARY
    assert 'clocked_flight_summary' in result['evidence'].signals
    assert result['parse_result'] is not None


@pytest.mark.parametrize('html', [
    CLOCKED_SUMMARY.replace('07:45 LAX GMT-07', 'LAX'),
    CLOCKED_SUMMARY.replace('07:45 LAX GMT-07', '07:45 SFO GMT-07'),
    CLOCKED_SUMMARY.replace('UA211', 'Economy'),
    CLOCKED_SUMMARY.replace('Monday, 28 April 2025', 'next trip'),
    CLOCKED_SUMMARY.replace('07:45 LAX GMT-07', '29:45 LAX GMT-07'),
    '<div hidden>' + CLOCKED_SUMMARY + '</div>',
    CLOCKED_SUMMARY.replace('07:45 LAX GMT-07', '<h2>Flight summary</h2>07:45 LAX GMT-07'),
])
def test_clocked_summary_requires_its_own_visible_number_date_and_both_endpoints(html):
    result = prepare_flight_message(message('View your booking online.', html), user_name='Alex Avery', aliases=[])
    assert result['evidence'].verdict == 'skip'
    assert result['parse_result'] is None
