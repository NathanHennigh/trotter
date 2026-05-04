"""Segment enrichment orchestration."""

from __future__ import annotations

import logging
import os
from typing import Optional

from sqlalchemy.orm import Session

from ..models import Segment, Trip
from .aircraft_enrichment import (
    enrich_aircraft,
    enrich_schedule,
    flight_detail_lookup_meta,
    lookup_aerodatabox_flight,
    should_lookup_provider_flight,
)
from .airport_data import get_airport_json
from .weather_enrichment import historical_weather_for_airport_event

logger = logging.getLogger(__name__)

DEFAULT_MAX_WEATHER_PER_RUN = int(os.getenv("TROTTER_WEATHER_ENRICH_MAX_PER_RUN", "80"))
DEFAULT_MAX_PROVIDER_LOOKUPS_PER_RUN = int(os.getenv("AERODATABOX_MAX_LOOKUPS_PER_SYNC", "60"))


def enrich_user_segments(
    db: Session,
    user_id: int,
    *,
    include_weather: bool = False,
    include_provider_lookup: bool = True,
    max_weather_segments: Optional[int] = DEFAULT_MAX_WEATHER_PER_RUN,
    max_provider_lookups: Optional[int] = DEFAULT_MAX_PROVIDER_LOOKUPS_PER_RUN,
) -> int:
    """Enrich saved flight segments for a user.

    Returns the number of segment rows whose metadata changed.
    """
    segments = (
        db.query(Segment)
        .join(Trip, Segment.trip_id == Trip.id)
        .filter(Trip.user_id == user_id)
        .order_by(Segment.dep_time.asc(), Segment.id.asc())
        .all()
    )
    updated = 0
    weather_attempts = 0
    provider_attempts = 0
    for segment in segments:
        allow_weather = include_weather and (
            max_weather_segments is None or weather_attempts < max_weather_segments
        )
        segment_meta = dict(segment.meta_json or {})
        enrichment = dict(segment_meta.get("enrichment") or {})
        provider_needed = should_lookup_provider_flight(segment, enrichment)
        allow_provider = include_provider_lookup and provider_needed and (
            max_provider_lookups is None or provider_attempts < max_provider_lookups
        )
        changed, attempted_weather = enrich_segment(
            segment,
            include_weather=allow_weather,
            include_provider_lookup=allow_provider,
        )
        if attempted_weather:
            weather_attempts += 1
        if allow_provider:
            provider_attempts += 1
        if changed:
            updated += 1
    if updated:
        db.commit()
    return updated


def enrich_segment(
    segment: Segment,
    *,
    include_weather: bool = False,
    include_provider_lookup: bool = False,
) -> tuple[bool, bool]:
    meta = dict(segment.meta_json or {})
    enrichment = dict(meta.get("enrichment") or {})
    changed = False
    attempted_weather = False

    airports = dict(enrichment.get("airports") or {})
    dep_airport = get_airport_json(segment.dep_airport)
    arr_airport = get_airport_json(segment.arr_airport)
    if dep_airport and airports.get("departure") != dep_airport:
        airports["departure"] = dep_airport
        changed = True
    if arr_airport and airports.get("arrival") != arr_airport:
        airports["arrival"] = arr_airport
        changed = True
    if airports:
        enrichment["airports"] = airports

    provider_flight = None
    if include_provider_lookup and should_lookup_provider_flight(segment, enrichment):
        provider_flight = lookup_aerodatabox_flight(segment)
        lookup_meta = flight_detail_lookup_meta(segment, provider_flight)
        if enrichment.get("flight_detail_lookup") != lookup_meta:
            enrichment["flight_detail_lookup"] = lookup_meta
            changed = True

    schedule, schedule_changed = enrich_schedule(
        segment,
        enrichment.get("schedule"),
        provider_flight=provider_flight,
        apply_to_segment=include_provider_lookup,
    )
    if schedule:
        enrichment["schedule"] = schedule
    if schedule_changed:
        changed = True

    aircraft, aircraft_changed = enrich_aircraft(
        segment,
        enrichment.get("aircraft"),
        provider_flight=provider_flight,
        allow_provider_lookup=False,
        allow_faa_lookup=include_provider_lookup,
    )
    if aircraft:
        enrichment["aircraft"] = aircraft
    if aircraft_changed:
        changed = True

    weather = dict(enrichment.get("weather") or {})
    if include_weather and ("departure" not in weather or "arrival" not in weather):
        attempted_weather = True
        if "departure" not in weather:
            dep_weather = historical_weather_for_airport_event(segment.dep_airport, segment.dep_time)
            if dep_weather:
                weather["departure"] = dep_weather
                changed = True
        if "arrival" not in weather:
            arr_weather = historical_weather_for_airport_event(segment.arr_airport, segment.arr_time)
            if arr_weather:
                weather["arrival"] = arr_weather
                changed = True
        if weather:
            enrichment["weather"] = weather

    if enrichment:
        meta["enrichment"] = enrichment
    if changed:
        segment.meta_json = meta
    return changed, attempted_weather
