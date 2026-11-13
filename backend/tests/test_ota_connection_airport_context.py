"""A printed city validates an explicit common airport, never selects one."""
from datetime import datetime, timezone

import pytest

from app.services.parser import _shape_ota_multi_confirmation, parse_email


ITINERARY = """Your confirmation codes
American Airlines
TEST12
Travel Portal
PORTAL1
Outbound to Tulum
Economy Cabin
July 12, 2025
5h 53m
1 stop
American Airlines - AA913
Houston
IAH
5:30 a.m.
2h 34m
Miami
MIA
9:04 a.m.
1h 10m layover in Miami
American Airlines - AA914
Miami
MIA
10:14 a.m.
2h 9m
Tulum
TQO
11:23 a.m.
Fare Details
Alex Taylor
Base Fare: $100.00
Taxes and Fees: $20.00
Ticket #: 0010000000001
Payment Info
"""


def shape(text):
    return _shape_ota_multi_confirmation(text, fallback_pnr=None,
        received_at=datetime(2025, 6, 1, tzinfo=timezone.utc))


@pytest.mark.parametrize("html", [False, True])
def test_common_airport_proves_connection_even_when_city_has_multiple_airports(html):
    result = parse_email(html="<p>" + ITINERARY.replace("\n", "</p><p>") + "</p>" if html else "",
        plain_text="" if html else ITINERARY, attachments=[], user_name="Alex Taylor", aliases=[],
        received_at=datetime(2025, 6, 1, tzinfo=timezone.utc), subject="Your travel receipt")
    first, second = result.flights
    assert (first.flight_number, second.flight_number) == ("AA913", "AA914")
    assert all(f.ownership == "self" and f.pnr == "TEST12" for f in result.flights)
    assert not any(getattr(f, "force_review", False) for f in result.flights)
    assert (first.arr_time.isoformat(), second.dep_time.isoformat(), second.arr_time.isoformat()) == (
        "2025-07-12T13:04:00+00:00", "2025-07-12T14:14:00+00:00", "2025-07-12T16:23:00+00:00")
    proof = second.time_provenance["date_evidence"]["departure_evidence"]
    assert proof["status"] == "verified" and proof["connection_airport"] == "MIA"
    assert proof["layover_minutes"] == 70 and proof["previous_leg_key"] == first.source_leg["key"]
    assert (second.dep_time - first.arr_time).total_seconds() == 70 * 60
    assert (second.arr_time - second.dep_time).total_seconds() == 129 * 60


@pytest.mark.parametrize("place", ["MIA", "Miami International Airport"])
def test_exact_airport_code_or_name_can_validate_established_connection(place):
    first, second = shape(ITINERARY.replace("layover in Miami", "layover in " + place))
    assert not getattr(second, "force_review", False)
    assert second.time_provenance["date_evidence"]["departure_evidence"]["previous_leg_key"] == first.source_leg["key"]


@pytest.mark.parametrize("before,after", [
    ("layover in Miami", "layover in Fort Lauderdale"),
    ("layover in Miami", "layover in Miami Beach"),
    ("layover in Miami", "layover in Miami or Orlando"),
    ("1h 10m layover", "1h 20m layover"),
    ("10:14 a.m.", "10:24 a.m."),
    ("2h 34m", "2h 44m"),
    ("American Airlines - AA914\nMiami\nMIA", "American Airlines - AA914\nMiami\nOPF"),
])
def test_context_does_not_override_conflicting_place_clock_duration_or_airport(before, after):
    second = shape(ITINERARY.replace(before, after))[1]
    assert second.force_review
    assert second.time_provenance["date_evidence"]["status"] == "needs_review"


def test_city_context_cannot_supply_a_missing_endpoint():
    values = shape(ITINERARY.replace("American Airlines - AA914\nMiami\nMIA", "American Airlines - AA914\nMiami"))
    assert not any(f.flight_number == "AA914" and not getattr(f, "force_review", False) for f in values)


def test_multi_airport_city_connection_retains_both_printed_next_day_markers():
    text = (ITINERARY.replace("American Airlines", "ANA").replace("AA913", "NH901").replace("AA914", "NH902")
        .replace("Tulum", "Singapore").replace("TQO", "SIN")
        .replace("Miami", "Tokyo").replace("MIA", "NRT")
        .replace("5h 53m", "1d 1h 40m").replace("5:30 a.m.", "10:05 a.m.")
        .replace("2h 34m", "13h 55m")
        .replace("9:04 a.m.", "2:00 p.m.\nThis flight arrives the next day.\nOperated by United.")
        .replace("1h 10m", "4h 40m").replace("10:14 a.m.", "6:40 p.m.")
        .replace("2h 9m", "7h 5m")
        .replace("11:23 a.m.", "12:45 a.m.\nThis flight arrives the next day.\nOperated by Air Japan."))
    result = parse_email(html="", plain_text=text, attachments=[], user_name="Alex Taylor", aliases=[],
        received_at=datetime(2025, 6, 1, tzinfo=timezone.utc), subject="Your travel receipt")
    first, second = result.flights
    assert not any(getattr(f, "force_review", False) for f in result.flights)
    assert (first.arr_time.isoformat(), second.dep_time.isoformat(), second.arr_time.isoformat()) == (
        "2025-07-13T05:00:00+00:00", "2025-07-13T09:40:00+00:00", "2025-07-13T16:45:00+00:00")
    assert second.time_provenance["arrival"]["local"] == "2025-07-14T00:45:00"
    assert second.time_provenance["date_evidence"]["departure_evidence"]["layover_minutes"] == 280
