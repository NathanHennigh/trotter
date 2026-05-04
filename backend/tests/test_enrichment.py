from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from app.models import Segment
from app.services import aircraft_enrichment
from app.services import weather_enrichment
from app.services.enrichment import enrich_segment


def test_historical_weather_uses_nearest_hour_and_scores_weather(monkeypatch):
    monkeypatch.setattr(
        weather_enrichment,
        "get_airport",
        lambda code: SimpleNamespace(
            iata_code=code,
            latitude=29.984,
            longitude=-95.341,
        ),
    )
    monkeypatch.setattr(
        weather_enrichment,
        "_fetch_open_meteo",
        lambda airport, event_time: {
            "hourly": {
                "time": ["2025-08-16T14:00", "2025-08-16T15:00", "2025-08-16T16:00"],
                "temperature_2m": [80.1, 85.7, 81.0],
                "apparent_temperature": [83.0, 91.2, 84.0],
                "precipitation": [0.0, 0.4, 0.0],
                "rain": [0.0, 0.4, 0.0],
                "snowfall": [0.0, 0.0, 0.0],
                "weather_code": [2, 95, 1],
                "cloud_cover": [30, 100, 20],
                "wind_speed_10m": [8.0, 22.0, 7.0],
                "wind_gusts_10m": [12.0, 44.0, 10.0],
            }
        },
    )

    result = weather_enrichment.historical_weather_for_airport_event(
        "IAH",
        datetime(2025, 8, 16, 15, 20, tzinfo=timezone.utc),
    )

    assert result is not None
    assert result["provider"] == "open-meteo"
    assert result["airport"] == "IAH"
    assert result["observed_at"] == "2025-08-16T15:00"
    assert result["summary"] == "Thunderstorms"
    assert result["temperature_f"] == 85.7
    assert result["severity_score"] > 100


def test_aircraft_enrichment_prefers_existing_email_data_without_api(monkeypatch):
    monkeypatch.setattr(aircraft_enrichment, "_from_aerodatabox", lambda segment: None)
    monkeypatch.setattr(aircraft_enrichment, "lookup_faa_registration", lambda registration: None)

    segment = Segment(
        mode="flight",
        dep_airport="IAH",
        arr_airport="LAX",
        dep_time=datetime(2025, 1, 10, 12, 0, tzinfo=timezone.utc),
        arr_time=datetime(2025, 1, 10, 15, 0, tzinfo=timezone.utc),
        airline="UA",
        flight_number="UA1234",
        meta_json={"enrichment": {"aircraft": {"equipment_code": "Boeing 737 MAX 9", "source": "email"}}},
    )

    changed, _ = enrich_segment(segment, include_weather=False)

    aircraft = segment.meta_json["enrichment"]["aircraft"]
    assert changed
    assert aircraft["equipment_code"] == "Boeing 737 MAX 9"
    assert aircraft["model"] == "Boeing 737 MAX 9"
    assert aircraft["source"] == "email"


def test_faa_registry_merge_resolves_n_number(monkeypatch):
    monkeypatch.setattr(
        aircraft_enrichment,
        "_load_faa_rows",
        lambda: (
            {
                "123AA": {
                    "N NUMBER": "123AA",
                    "MFR MDL CODE": "05655",
                    "SERIAL NUMBER": "777",
                }
            },
            {"05655": {"CODE": "05655", "MFR": "BOEING", "MODEL": "737-9"}},
        ),
    )

    result = aircraft_enrichment.lookup_faa_registration("N123AA")

    assert result is not None
    assert result.registration == "N123AA"
    assert result.model == "BOEING 737-9"
    assert result.serial_number == "777"


def test_aerodatabox_result_is_normalized(monkeypatch):
    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return [
                {
                    "number": "UA1234",
                    "departure": {"airport": {"iata": "IAH"}},
                    "arrival": {"airport": {"iata": "LAX"}},
                    "aircraft": {
                        "reg": "N123AA",
                        "hexIcao": "A05F2A",
                        "model": "Boeing 737 MAX 9",
                        "modelCode": "B39M",
                        "iataCodeShort": "7M9",
                        "icaoCode": "B39M",
                    },
                }
            ]

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setenv("AERODATABOX_API_KEY", "test-key")
    monkeypatch.setattr(aircraft_enrichment.httpx, "Client", FakeClient)
    monkeypatch.setattr(aircraft_enrichment, "lookup_faa_registration", lambda registration: None)

    segment = Segment(
        mode="flight",
        dep_airport="IAH",
        arr_airport="LAX",
        dep_time=datetime(2025, 1, 10, 12, 0, tzinfo=timezone.utc),
        arr_time=datetime(2025, 1, 10, 15, 0, tzinfo=timezone.utc),
        airline="UA",
        flight_number="UA1234",
        meta_json={},
    )

    aircraft, changed = aircraft_enrichment.enrich_aircraft(segment)

    assert changed
    assert aircraft["source"] == "aerodatabox"
    assert aircraft["model"] == "Boeing 737 MAX 9"
    assert aircraft["equipment_code"] == "7M9"
    assert aircraft["registration"] == "N123AA"


def test_provider_schedule_repairs_low_confidence_segment_times(monkeypatch):
    monkeypatch.setenv("AERODATABOX_RAPIDAPI_KEY", "test-key")
    provider_flight = {
        "number": "UA1234",
        "status": "Arrived",
        "departure": {
            "airport": {"iata": "IAH"},
            "scheduledTime": {"utc": "2025-01-10T12:00:00Z"},
        },
        "arrival": {
            "airport": {"iata": "LAX"},
            "scheduledTime": {"utc": "2025-01-10T15:45:00Z"},
        },
        "aircraft": {"model": "Boeing 737-900", "iataCodeShort": "739"},
    }
    monkeypatch.setattr(aircraft_enrichment, "lookup_aerodatabox_flight", lambda segment: provider_flight)
    monkeypatch.setattr(aircraft_enrichment, "lookup_faa_registration", lambda registration: None)
    import app.services.enrichment as enrichment

    monkeypatch.setattr(enrichment, "lookup_aerodatabox_flight", lambda segment: provider_flight)

    segment = Segment(
        mode="flight",
        dep_airport="IAH",
        arr_airport="LAX",
        dep_time=datetime(2025, 1, 10, 12, 0),
        arr_time=datetime(2025, 1, 10, 12, 5),
        airline="UA",
        flight_number="UA1234",
        meta_json={"source": "parser", "confidence": 30},
    )

    changed, _ = enrich_segment(segment, include_provider_lookup=True)

    schedule = segment.meta_json["enrichment"]["schedule"]
    assert changed
    assert segment.arr_time == datetime(2025, 1, 10, 15, 45)
    assert schedule["applied_to_segment"] is True
    assert schedule["departure"]["airport"] == "IAH"
    assert schedule["arrival"]["airport"] == "LAX"
    assert segment.meta_json["enrichment"]["aircraft"]["model"] == "Boeing 737-900"


def test_provider_schedule_does_not_replace_strong_plausible_email_times(monkeypatch):
    monkeypatch.setenv("AERODATABOX_RAPIDAPI_KEY", "test-key")
    provider_flight = {
        "number": "UA1234",
        "departure": {
            "airport": {"iata": "IAH"},
            "scheduledTime": {"utc": "2025-01-10T14:00:00Z"},
        },
        "arrival": {
            "airport": {"iata": "LAX"},
            "scheduledTime": {"utc": "2025-01-10T18:00:00Z"},
        },
    }
    import app.services.enrichment as enrichment

    monkeypatch.setattr(enrichment, "lookup_aerodatabox_flight", lambda segment: provider_flight)

    segment = Segment(
        mode="flight",
        dep_airport="IAH",
        arr_airport="LAX",
        dep_time=datetime(2025, 1, 10, 12, 5),
        arr_time=datetime(2025, 1, 10, 15, 35),
        airline="UA",
        flight_number="UA1234",
        meta_json={"source": "email", "confidence": 92},
    )

    changed, _ = enrich_segment(segment, include_provider_lookup=True)

    schedule = segment.meta_json["enrichment"]["schedule"]
    assert changed
    assert segment.dep_time == datetime(2025, 1, 10, 12, 5)
    assert segment.arr_time == datetime(2025, 1, 10, 15, 35)
    assert schedule["applied_to_segment"] is False


def test_provider_lookup_is_skipped_when_schedule_and_aircraft_already_saved(monkeypatch):
    monkeypatch.setenv("AERODATABOX_RAPIDAPI_KEY", "test-key")

    def fail_lookup(segment):
        raise AssertionError("provider lookup should not be called")

    import app.services.enrichment as enrichment

    monkeypatch.setattr(enrichment, "lookup_aerodatabox_flight", fail_lookup)

    segment = Segment(
        mode="flight",
        dep_airport="IAH",
        arr_airport="LAX",
        dep_time=datetime(2025, 1, 10, 12, 5),
        arr_time=datetime(2025, 1, 10, 15, 35),
        airline="UA",
        flight_number="UA1234",
        meta_json={
            "source": "email",
            "confidence": 95,
            "enrichment": {
                "schedule": {
                    "departure": {"airport": "IAH", "best_utc": "2025-01-10T12:05:00+00:00"},
                    "arrival": {"airport": "LAX", "best_utc": "2025-01-10T15:35:00+00:00"},
                },
                "aircraft": {"model": "Boeing 737 MAX 9", "source": "aerodatabox"},
            },
        },
    )

    enrich_segment(segment, include_provider_lookup=True)

    assert "flight_detail_lookup" not in segment.meta_json["enrichment"]


def test_negative_provider_lookup_cache_prevents_repeat_calls(monkeypatch):
    monkeypatch.setenv("AERODATABOX_RAPIDAPI_KEY", "test-key")

    def fail_lookup(segment):
        raise AssertionError("negative cache should prevent provider lookup")

    import app.services.enrichment as enrichment

    monkeypatch.setattr(enrichment, "lookup_aerodatabox_flight", fail_lookup)

    segment = Segment(
        mode="flight",
        dep_airport="IAH",
        arr_airport="LAX",
        dep_time=datetime(2025, 1, 10, 12, 0),
        arr_time=datetime(2025, 1, 10, 12, 5),
        airline="UA",
        flight_number="UA1234",
        meta_json={
            "source": "parser",
            "confidence": 30,
            "enrichment": {
                "flight_detail_lookup": {
                    "provider": "aerodatabox",
                    "lookup_key": "UA1234|2025-01-10|IAH|LAX",
                    "found": False,
                    "looked_up_at": datetime.now(timezone.utc).isoformat(),
                    "negative_cache_days": 90,
                }
            },
        },
    )

    enrich_segment(segment, include_provider_lookup=True)

    assert segment.meta_json["enrichment"]["flight_detail_lookup"]["found"] is False
