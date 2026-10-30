"""Preserve airport-local API clocks while normalized storage remains UTC.

Legacy rows have no reliable time basis, so their existing representation stays
unchanged. Never reinterpret those rows by guessing an airport offset.
"""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def endpoint_local_time(value, metadata, endpoint, airport=None):
    if not isinstance(value, datetime):
        return value
    provenance = (metadata or {}).get("time_provenance") or {}
    if provenance.get("version") != 1 or provenance.get("status") != "normalized":
        return value
    detail = provenance.get(endpoint) or {}
    if airport and detail.get("airport") != airport:
        return value
    try:
        source_instant = datetime.fromisoformat(detail["utc"].replace("Z", "+00:00"))
        if utc(source_instant) != utc(value):
            return value  # An unrelated later edit must not use stale provenance.
        return utc(value).astimezone(ZoneInfo(detail["timezone"]))
    except (KeyError, TypeError, ValueError, ZoneInfoNotFoundError):
        return value


def segment_local_date(segment, endpoint="departure"):
    value = segment.dep_time if endpoint == "departure" else segment.arr_time
    airport = segment.dep_airport if endpoint == "departure" else segment.arr_airport
    local = endpoint_local_time(value, segment.meta_json, endpoint, airport)
    return local.date().isoformat()
