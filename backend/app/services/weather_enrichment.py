"""Weather enrichment for flight departure and arrival events."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Optional

import httpx

from .airport_data import AirportInfo, get_airport

logger = logging.getLogger(__name__)

OPEN_METEO_ARCHIVE_URL = os.getenv(
    "TROTTER_OPEN_METEO_ARCHIVE_URL",
    "https://archive-api.open-meteo.com/v1/archive",
)
HTTP_TIMEOUT_SECONDS = float(os.getenv("TROTTER_ENRICHMENT_HTTP_TIMEOUT", "6"))
HOURLY_FIELDS = (
    "temperature_2m",
    "apparent_temperature",
    "precipitation",
    "rain",
    "snowfall",
    "weather_code",
    "cloud_cover",
    "wind_speed_10m",
    "wind_gusts_10m",
)


def historical_weather_for_airport_event(
    airport_code: str,
    event_time: datetime,
) -> Optional[dict]:
    """Fetch nearest-hour historical weather for an airport event.

    Open-Meteo's archive is a reanalysis model, not the exact METAR the pilot
    saw, so we store the confidence plainly in metadata.
    """
    airport = get_airport(airport_code)
    if not airport:
        return None

    event_time = _as_utc(event_time)
    today_utc = datetime.now(timezone.utc).date()
    if event_time.date() >= today_utc:
        return None

    try:
        data = _fetch_open_meteo(airport, event_time)
        hourly = data.get("hourly") or {}
        times = hourly.get("time") or []
        if not times:
            return None
        index = _nearest_hour_index(times, event_time)
        values = {field: _value_at(hourly.get(field), index) for field in HOURLY_FIELDS}
        summary = _weather_summary(values)
        return {
            "provider": "open-meteo",
            "provider_url": "https://open-meteo.com/",
            "confidence": "nearest_hour_reanalysis",
            "airport": airport.iata_code,
            "observed_at": times[index],
            "summary": summary,
            "severity_score": _severity_score(values),
            "temperature_f": values["temperature_2m"],
            "apparent_temperature_f": values["apparent_temperature"],
            "precipitation_in": values["precipitation"],
            "rain_in": values["rain"],
            "snowfall_in": values["snowfall"],
            "weather_code": values["weather_code"],
            "cloud_cover_pct": values["cloud_cover"],
            "wind_speed_mph": values["wind_speed_10m"],
            "wind_gust_mph": values["wind_gusts_10m"],
        }
    except Exception as exc:
        logger.info("Weather enrichment skipped for %s at %s: %s", airport_code, event_time, exc)
        return None


def _fetch_open_meteo(airport: AirportInfo, event_time: datetime) -> dict:
    params = {
        "latitude": airport.latitude,
        "longitude": airport.longitude,
        "start_date": event_time.date().isoformat(),
        "end_date": event_time.date().isoformat(),
        "hourly": ",".join(HOURLY_FIELDS),
        "temperature_unit": "fahrenheit",
        "wind_speed_unit": "mph",
        "precipitation_unit": "inch",
        "timezone": "UTC",
    }
    headers = {"User-Agent": "Trotter/1.0 weather-enrichment"}
    with httpx.Client(timeout=HTTP_TIMEOUT_SECONDS, headers=headers) as client:
        response = client.get(OPEN_METEO_ARCHIVE_URL, params=params)
        response.raise_for_status()
        return response.json()


def _nearest_hour_index(times: list[str], event_time: datetime) -> int:
    def delta(index: int) -> float:
        candidate = datetime.fromisoformat(times[index]).replace(tzinfo=timezone.utc)
        return abs((candidate - event_time).total_seconds())

    return min(range(len(times)), key=delta)


def _value_at(values, index: int):
    if not isinstance(values, list) or index >= len(values):
        return None
    return values[index]


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _weather_summary(values: dict) -> str:
    code = values.get("weather_code")
    if code in {95, 96, 99}:
        return "Thunderstorms"
    if code in {71, 73, 75, 77, 85, 86}:
        return "Snow"
    if code in {51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82}:
        return "Rain"
    if code in {45, 48}:
        return "Fog"
    if code in {1, 2, 3}:
        return "Clouds"
    if code == 0:
        return "Clear"
    return "Weather"


def _severity_score(values: dict) -> float:
    precipitation = float(values.get("precipitation") or 0)
    snowfall = float(values.get("snowfall") or 0)
    gust = float(values.get("wind_gusts_10m") or 0)
    cloud = float(values.get("cloud_cover") or 0)
    code = values.get("weather_code")
    code_bonus = 0.0
    if code in {95, 96, 99}:
        code_bonus = 45.0
    elif code in {65, 67, 75, 82, 86}:
        code_bonus = 30.0
    elif code in {45, 48, 61, 63, 71, 73, 80, 81}:
        code_bonus = 18.0
    return round(gust + precipitation * 80 + snowfall * 50 + cloud * 0.08 + code_bonus, 1)
