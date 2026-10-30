"""Endpoint clocks have independent timezones; ambiguous facts stay held."""
from datetime import datetime, timedelta, timezone
import json

import pytest

from app.services.flight_times import normalize_flight_times
from app.services.parser import ParsedFlight, parse_email


def flight(dep, arr, dep_time, arr_time, **kwargs):
    return ParsedFlight(dep, arr, datetime.fromisoformat(dep_time), datetime.fromisoformat(arr_time), **kwargs)


@pytest.mark.parametrize("dep,arr,departure,arrival,expected_dep,expected_arr", [
    ("IAH", "MCO", "2025-02-21T16:16:00+00:00", "2025-02-21T19:40:00+00:00", "2025-02-21T22:16:00+00:00", "2025-02-22T00:40:00+00:00"),
    ("ATL", "IAH", "2025-02-23T20:49:00+00:00", "2025-02-23T22:10:00+00:00", "2025-02-24T01:49:00+00:00", "2025-02-24T04:10:00+00:00"),
    ("IAH", "TPE", "2025-04-26T01:00", "2025-04-27T06:30", "2025-04-26T06:00:00+00:00", "2025-04-26T22:30:00+00:00"),
    ("NRT", "LAX", "2025-07-11T17:00", "2025-07-11T11:00", "2025-07-11T08:00:00+00:00", "2025-07-11T18:00:00+00:00"),
])
def test_printed_local_clocks_to_utc_are_idempotent(dep, arr, departure, arrival, expected_dep, expected_arr):
    f = flight(dep, arr, departure, arrival)
    normalize_flight_times(f)
    assert f.dep_time.isoformat() == expected_dep
    assert f.arr_time.isoformat() == expected_arr
    saved = dict(f.time_provenance)
    normalize_flight_times(f)
    assert f.time_provenance == saved
    assert f.dep_time.isoformat() == expected_dep


@pytest.mark.parametrize("departure,reason", [
    ("2025-11-02T01:30", "ambiguous_local_time"),
    ("2025-03-09T02:30", "nonexistent_local_time"),
])
def test_dst_uncertainty_is_reviewed_not_guessed(departure, reason):
    f = flight("IAH", "DCA", departure, departure[:10] + "T08:30")
    original = f.dep_time
    normalize_flight_times(f)
    assert f.force_review
    assert f.time_provenance["reason"] == reason
    assert f.dep_time == original


def test_unknown_airport_timezone_is_held():
    f = flight("ZZZ", "DCA", "2025-01-01T10:00", "2025-01-01T15:00")
    normalize_flight_times(f)
    assert f.force_review
    assert f.time_provenance["reason"] == "unknown_airport_timezone"


@pytest.mark.parametrize("departure,arrival", [("2025-03-09T01:30:00-06:00", "2025-03-09T11:00:00-04:00"),
                                              ("2025-03-09T07:30:00Z", "2025-03-09T15:00:00Z")])
def test_jsonld_explicit_offsets_are_absolute(departure, arrival):
    item = {"@type": "FlightReservation", "underName": {"name": "Alex Avery"},
            "reservationFor": {"@type": "Flight", "departureAirport": {"iataCode": "IAH"},
            "arrivalAirport": {"iataCode": "DCA"}, "departureTime": departure, "arrivalTime": arrival}}
    r = parse_email(html='<script type="application/ld+json">' + json.dumps(item) + '</script>',
                    plain_text="", attachments=[], user_name="Alex Avery", aliases=[])
    f = r.flights[0]
    assert f.dep_time == datetime(2025, 3, 9, 7, 30, tzinfo=timezone.utc)
    assert f.arr_time == datetime(2025, 3, 9, 15, tzinfo=timezone.utc)
    assert f.time_provenance["departure"]["basis"] == "absolute"
    assert not getattr(f, "force_review", False)


@pytest.mark.parametrize("dates", ["DTSTART:20250221T221600Z\nDTEND:20250222T004000Z",
    "DTSTART;TZID=America/Chicago:20250221T161600\nDTEND;TZID=America/New_York:20250221T194000",
    "DTSTART:20250221T161600\nDTEND:20250221T194000"])
def test_ics_absolute_and_floating_clock_interpretation(dates):
    ics = "BEGIN:VCALENDAR\nVERSION:2.0\nBEGIN:VEVENT\nSUMMARY:Flight UA123 (IAH) to (MCO)\n" + dates + "\nEND:VEVENT\nEND:VCALENDAR"
    r = parse_email(html="", plain_text="Passenger: Alex Avery", attachments=[("flight.ics", ics.encode())], user_name="Alex Avery", aliases=[])
    assert r.flights[0].dep_time == datetime(2025, 2, 21, 22, 16, tzinfo=timezone.utc)
    assert r.flights[0].arr_time == datetime(2025, 2, 22, 0, 40, tzinfo=timezone.utc)


@pytest.mark.parametrize("dep_place,arr_place,dep_date,dep_clock,arr_date,arr_clock,expected_dep,expected_arr", [
    ("New York (JFK)", "Los Angeles (LAX)", "11 Jul 2025", "17:00", "11 Jul 2025", "16:45", "2025-07-11T21:00:00+00:00", "2025-07-11T23:45:00+00:00"),
    ("Tokyo (NRT)", "Los Angeles (LAX)", "11 Jul 2025", "17:00", "11 Jul 2025", "11:00", "2025-07-11T08:00:00+00:00", "2025-07-11T18:00:00+00:00"),
    ("New York (JFK)", "London (LHR)", "11 Jul 2025", "22:00", "12 Jul 2025", "10:00", "2025-07-12T02:00:00+00:00", "2025-07-12T09:00:00+00:00"),
])
def test_explicit_eticket_dates_never_get_a_speculative_extra_day(dep_place, arr_place, dep_date, dep_clock, arr_date, arr_clock, expected_dep, expected_arr):
    text = f"Your Itinerary\nAA123\nAmerican Airlines | Economy | Confirmed\n{dep_date}\n{dep_clock}\n{dep_place}\n{arr_date}\n{arr_clock}\n{arr_place}\nPassenger: Alex Avery"
    result = parse_email(html="", plain_text=text, attachments=[], user_name="Alex Avery", aliases=[])
    assert len(result.flights) == 1
    f = result.flights[0]
    assert f.dep_time.isoformat() == expected_dep
    assert f.arr_time.isoformat() == expected_arr
    assert not getattr(f, "force_review", False)


@pytest.mark.parametrize("clocks", ["2025-02-21T16:16:00-06:00\n2025-02-21T19:40:00-05:00",
    "2025-02-21T22:16:00Z\n2025-02-22T00:40:00Z",
    "2025-02-21T22:16:00 UTC\n2025-02-22T00:40:00 GMT"])
def test_plain_iso_offsets_remain_absolute_without_jsonld(clocks):
    result = parse_email(html="", plain_text="UA123 (IAH) to (MCO)\n" + clocks + "\nPassenger: Alex Avery", attachments=[], user_name="Alex Avery", aliases=[])
    assert len(result.flights) == 1
    assert result.flights[0].dep_time.isoformat() == "2025-02-21T22:16:00+00:00"
    assert result.flights[0].arr_time.isoformat() == "2025-02-22T00:40:00+00:00"
    assert result.flights[0].time_provenance["departure"]["basis"] == "absolute"


def test_impossible_explicit_arrival_date_is_held_instead_of_inventing_overnight():
    text = "Your Itinerary\nAA123\nAmerican Airlines | Economy | Confirmed\n11 Jul 2025\n22:00\nNew York (JFK)\n11 Jul 2025\n10:00\nLondon (LHR)\nPassenger: Alex Avery"
    f = parse_email(html="", plain_text=text, attachments=[], user_name="Alex Avery", aliases=[]).flights[0]
    assert f.force_review
    assert f.time_provenance["reason"] == "inconsistent_flight_times"
    assert f.time_provenance["arrival"]["local"] == "2025-07-11T10:00:00"
