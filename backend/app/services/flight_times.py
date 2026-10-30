"""Convert printed airport-local clocks once, retaining their interpretation.

This module reads the installed airportsdata database only. It never fetches
metadata or adjusts an existing database row without reparsing source evidence.
"""
from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


@lru_cache(maxsize=1)
def _airport_zones():
    import airportsdata
    return {code: row.get("tz") for code, row in airportsdata.load("IATA").items()}


@lru_cache(maxsize=1024)
def _zone(airport):
    name = _airport_zones().get(str(airport or "").upper())
    if not name:
        return None
    try:
        return ZoneInfo(name)
    except (ValueError, ZoneInfoNotFoundError):
        return None


def _endpoint(value, airport, basis):
    info = {"basis": basis, "original": value.isoformat() if isinstance(value, datetime) else None,
            "airport": airport, "timezone": None, "local": None, "utc": None}
    if not isinstance(value, datetime):
        return None, info, "missing_flight_time"
    zone = _zone(airport)
    if basis == "absolute" and value.tzinfo is not None:
        absolute = value.astimezone(timezone.utc)
        local = value.astimezone(zone) if zone else value
        info.update(timezone=str(zone or value.tzinfo), local=local.replace(tzinfo=None).isoformat(), utc=absolute.isoformat())
        return absolute, info, None
    # Legacy shape helpers label wall clocks UTC while parsing dates. That tag
    # is not an offset supplied by the receipt; airport_local marks this fact.
    wall = value.replace(tzinfo=None)
    info["local"] = wall.isoformat()
    if zone is None:
        return None, info, "unknown_airport_timezone"
    info["timezone"] = str(zone)
    candidates = set()
    for fold in (0, 1):
        possible = wall.replace(tzinfo=zone, fold=fold).astimezone(timezone.utc)
        if possible.astimezone(zone).replace(tzinfo=None) == wall:
            candidates.add(possible)
    if len(candidates) != 1:
        return None, info, "ambiguous_local_time" if candidates else "nonexistent_local_time"
    absolute = candidates.pop()
    info["utc"] = absolute.isoformat()
    return absolute, info, None


def normalize_flight_times(flight):
    """Normalize a newly parsed flight, or hold ambiguous facts for review."""
    previous = getattr(flight, "time_provenance", None) or {}
    if previous.get("version") == 1 and previous.get("status") == "normalized":
        return
    dep, dep_info, dep_error = _endpoint(flight.dep_time, flight.dep_airport,
        previous.get("departure", {}).get("basis", "airport_local"))
    arr, arr_info, arr_error = _endpoint(flight.arr_time, flight.arr_airport,
        previous.get("arrival", {}).get("basis", "airport_local"))
    error = dep_error or arr_error
    if not error and (arr <= dep or (arr - dep).total_seconds() > 48 * 3600):
        error = "inconsistent_flight_times"
    flight.time_provenance = {"version": 1, "status": "needs_review" if error else "normalized",
        "departure_local_date": dep_info["local"][:10] if dep_info["local"] else None,
        "departure": dep_info, "arrival": arr_info}
    if error:
        flight.time_provenance["reason"] = error
        flight.force_review = True
        return
    flight.dep_time, flight.arr_time = dep, arr
