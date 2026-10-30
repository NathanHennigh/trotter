"""Current apps read airport clocks from ISO strings; offsets preserve instants."""
from datetime import datetime, timezone
from types import SimpleNamespace

from app.routers.trips import SegmentOut, TripOut
from app.services.aircraft_enrichment import aerodatabox_lookup_key
from app.services.flight_display_time import endpoint_local_time
from app.services.flight_times import normalize_flight_times


def late_flight():
    flight = SimpleNamespace(dep_airport="LAS", arr_airport="DCA",
        dep_time=datetime(2026,9,9,23,30,tzinfo=timezone.utc),
        arr_time=datetime(2026,9,10,7,20,tzinfo=timezone.utc), time_provenance={}, force_review=False)
    normalize_flight_times(flight)
    return SegmentOut(id=1,trip_id=1,mode="flight",dep_airport=flight.dep_airport,
        arr_airport=flight.arr_airport,dep_time=flight.dep_time,arr_time=flight.arr_time,
        flight_number="AA1004",airline="AA",meta_json={"time_provenance":flight.time_provenance})


def test_api_clock_and_calendar_are_local_but_parse_to_same_instant():
    segment = late_flight()
    payload = segment.model_dump(mode="json")
    assert payload["dep_time"] == "2026-09-09T23:30:00-07:00"
    assert payload["arr_time"] == "2026-09-10T07:20:00-04:00"
    assert datetime.fromisoformat(payload["dep_time"]) == segment.dep_time
    assert (datetime.fromisoformat(payload["arr_time"])-datetime.fromisoformat(payload["dep_time"])).total_seconds() == 4*3600+50*60
    assert segment.dep_time.isoformat() == "2026-09-10T06:30:00+00:00"


def test_trip_calendar_boundaries_match_first_and_last_airports():
    segment = late_flight()
    trip = TripOut(id=1,start_ts=segment.dep_time,end_ts=segment.arr_time,segments=[segment])
    payload = trip.model_dump(mode="json")
    assert payload["start_ts"] == payload["segments"][0]["dep_time"]
    assert payload["end_ts"] == payload["segments"][0]["arr_time"]
    assert trip.start_ts == segment.dep_time  # Serialization never changes storage.


def test_legacy_unverified_times_and_stale_provenance_are_not_shifted():
    value = datetime(2026,9,9,23,30,tzinfo=timezone.utc)
    assert endpoint_local_time(value,{},"departure","LAS") == value
    segment = late_flight()
    assert endpoint_local_time(value,segment.meta_json,"departure","LAS") == value
    assert endpoint_local_time(segment.dep_time,segment.meta_json,"departure","JFK") == segment.dep_time


def test_sqlite_naive_normalized_values_serialize_with_same_offset():
    segment = late_flight()
    segment.dep_time = segment.dep_time.replace(tzinfo=None)
    assert segment.model_dump(mode="json")["dep_time"] == "2026-09-09T23:30:00-07:00"


def test_provider_lookup_uses_local_service_date_not_utc_rollover():
    assert aerodatabox_lookup_key(late_flight()) == "AA1004|2026-09-09|LAS|DCA"
