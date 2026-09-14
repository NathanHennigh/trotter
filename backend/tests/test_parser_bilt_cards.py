"""Synthetic confirmations using Bilt's original nested flight-card structure.

The fixture contains no real account, payment, booking code, tracking URL, or
passenger details. These cases exercise the public parser, not a live mailbox.
"""

from datetime import datetime, timezone
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from app.models import MessageStatus
from app.services.parser import _shape_dated_flight_cards, parse_email
from app.services.parser_preprocess import prepare_parser_text


TEMPLATE = (Path(__file__).parent / "fixtures" / "bilt_flight_card.html").read_text(encoding="utf-8")
DEPARTURE = "Wed, 9 Sep 2026"
RETURN = "Fri, 11 Sep 2026"
RECEIVED = datetime(2026, 9, 4, 18, tzinfo=timezone.utc)


def card(flight, dep, arr, dep_time, arr_time, date=DEPARTURE, *, arr_date=None, duration="1h 30m"):
    values = {
        "flight": flight, "duration": duration,
        "dep_code": dep, "dep_city": "Origin city", "dep_time": dep_time, "dep_date": date,
        "arr_code": arr, "arr_city": "Destination city", "arr_time": arr_time,
        "arr_date": arr_date or date,
    }
    result = TEMPLATE
    for name, value in values.items():
        result = result.replace("{{" + name + "}}", value)
    return result


def confirmation(cards):
    # The payer's name matches the user, but no Passenger/Traveler field exists.
    # Summary dates precede the actual cards, as they do in the source emails.
    return """<html><body><table><tr><td>Bilt</td><td>Example Traveler</td></tr></table>
        <h1>Your flight booking is confirmed!</h1>
        <p>Airline confirmation</p><p>XZ4Q7B</p>
        <p>Booking ID</p><p>BLT-EXAMPLE-0001</p>
        <p>Wed, 9 Sep 2026</p><p>Fri, 11 Sep 2026</p>
        <h2>Flight details</h2>""" + "".join(cards) + """
        <h2>Payment summary</h2><p>Cardholder: Example Traveler</p><p>Example payment</p>
        </body></html>"""


def plain(html):
    return BeautifulSoup(html, "html.parser").get_text("\n", strip=True)


def parse(html, mode="multipart"):
    return parse_email(
        html=html if mode != "plain" else "",
        plain_text=plain(html) if mode != "html" else "",
        attachments=[], user_name="Example Traveler", aliases=[],
        received_at=RECEIVED, subject="Your flight booking is confirmed!",
        from_email="Bilt <notifications@members.bilt.com>",
    )


BOOKINGS = [
    [
        ("AA1001", "LAS", "DCA", "11:41am", "07:35pm", DEPARTURE),
        ("AA1002", "BWI", "CLT", "02:54pm", "04:29pm", RETURN),
        ("AA1003", "CLT", "LAS", "06:15pm", "07:56pm", RETURN),
    ],
    [
        ("DL2001", "DTW", "DCA", "10:08am", "11:35am", DEPARTURE),
        ("DL2001", "DCA", "DTW", "12:32pm", "02:02pm", RETURN),
    ],
    [
        ("AA3001", "ACT", "DFW", "05:10am", "06:05am", DEPARTURE),
        ("AA3002", "DFW", "DCA", "07:00am", "11:00am", DEPARTURE),
        ("AA3003", "DCA", "DFW", "05:01pm", "07:29pm", RETURN),
        ("AA3004", "DFW", "ACT", "09:19pm", "10:06pm", RETURN),
    ],
]


@pytest.mark.parametrize("mode", ["plain", "html", "multipart"])
@pytest.mark.parametrize("booking", BOOKINGS, ids=["open_jaw", "same_flight_number_return", "four_connections"])
def test_all_dated_cards_survive_preprocessing_without_inferred_ownership(booking, mode):
    result = parse(confirmation([card(*row) for row in booking]), mode)
    assert len(result.flights) == len(booking)
    for actual, (number, dep, arr, dep_clock, arr_clock, date) in zip(result.flights, booking):
        assert (actual.flight_number, actual.dep_airport, actual.arr_airport) == (number, dep, arr)
        expected_dep = datetime.strptime(date + " " + dep_clock, "%a, %d %b %Y %I:%M%p")
        expected_arr = datetime.strptime(date + " " + arr_clock, "%a, %d %b %Y %I:%M%p")
        assert actual.dep_time == expected_dep.replace(tzinfo=timezone.utc)
        assert actual.arr_time == expected_arr.replace(tzinfo=timezone.utc)
        assert actual.source_received_at == RECEIVED
        assert actual.source == "shape_dated_flight_cards"
        assert actual.pnr == "XZ4Q7B"
        assert actual.ownership == "unknown"
        assert actual.passenger_names == []
        assert actual.passenger_evidence == []
    assert result.status == MessageStatus.REVIEW_REQUIRED
    assert result.passenger_name is None


def test_duplicate_html_copies_and_clock_image_plain_links_do_not_duplicate_flights():
    html = confirmation([card(*row) for row in BOOKINGS[2]])
    text = plain(html)
    for number, *_ in BOOKINGS[2]:
        text = text.replace(number, number + "\n( https://example.invalid/clock.png ) Clock")
    result = parse_email(
        html=html + html, plain_text=text, attachments=[], user_name="Example Traveler",
        aliases=[], received_at=RECEIVED, subject="Your flight booking is confirmed!",
    )
    assert [f.flight_number for f in result.flights] == [row[0] for row in BOOKINGS[2]]


@pytest.mark.parametrize("mode", ["plain", "html", "multipart"])
def test_explicit_overnight_arrival_date_is_preserved(mode):
    result = parse(confirmation([card(
        "AA1004", "LAS", "DCA", "11:30pm", "07:20am", DEPARTURE,
        arr_date="Thu, 10 Sep 2026", duration="4h 50m",
    )]), mode)
    assert len(result.flights) == 1
    assert result.flights[0].arr_time.date().isoformat() == "2026-09-10"
    assert result.flights[0].dep_time.date().isoformat() == "2026-09-09"


def test_card_with_a_missing_arrival_cannot_borrow_the_next_flight_endpoint():
    incomplete = "\n".join(["AA1001", "1h 30m", "ACT", "Origin city", "05:10am", DEPARTURE])
    next_card = plain(card("AA1002", "DFW", "DCA", "07:00am", "11:00am"))
    result = _shape_dated_flight_cards(incomplete + "\n" + next_card, pnr="XZ4Q7B")
    assert [(f.flight_number, f.dep_airport, f.arr_airport) for f in result] == [("AA1002", "DFW", "DCA")]


@pytest.mark.parametrize("change", ["missing_date", "invalid_date", "invalid_airport", "same_airport", "no_duration", "invalid_duration"])
def test_incomplete_or_invalid_card_is_not_promoted_to_high_confidence(change):
    html = card("AA1001", "ACT", "DFW", "05:10am", "06:05am")
    text = plain(html)
    if change == "missing_date":
        text = text.replace(DEPARTURE, "", 1)
    elif change == "invalid_date":
        text = text.replace(DEPARTURE, "Wed, 99 Sep 2026", 1)
    elif change == "invalid_airport":
        text = text.replace("DFW", "ZZZ")
    elif change == "same_airport":
        text = text.replace("DFW", "ACT")
    elif change == "no_duration":
        text = text.replace("1h 30m", "")
    else:
        text = text.replace("1h 30m", "99h 99m")
    assert _shape_dated_flight_cards(text, pnr="XZ4Q7B") == []


def test_repeated_flight_date_and_duration_lines_are_structural_not_boilerplate():
    repeated = "\n".join(["DL2001", "1h 30m", DEPARTURE] * 8 + ["Promotional footer"] * 8)
    bundle = prepare_parser_text(html="", plain_text=repeated)
    assert bundle.clean_text.splitlines().count("DL2001") == 8
    assert bundle.clean_text.splitlines().count("1h 30m") == 8
    assert bundle.clean_text.splitlines().count(DEPARTURE) == 8
    assert bundle.clean_text.splitlines().count("Promotional footer") == 2


def test_marketing_without_complete_cards_does_not_create_flights():
    result = parse_email(
        html="", plain_text="Bilt newsletter\nExplore Washington\nAA1001\nACT\nDFW\nBook now for September",
        attachments=[], user_name="Example Traveler", aliases=[], received_at=RECEIVED,
    )
    assert result.flights == []
