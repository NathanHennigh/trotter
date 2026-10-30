"""Transient, bounded factual inputs for itinerary generation.

Place hours and route responses live only for this generation. Coordinates
alone may use the existing isolated, nonpersistent Redis cache for six hours.
No provider names, addresses, raw responses or attribution are persisted here.
The planner stores its own chosen visit times; direct Google route durations
are removed by ``planner_engine.plan_for_storage`` before revision persistence.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
import math
import hashlib
import json
import os
from pathlib import Path
import time
from typing import Any
from urllib.parse import quote

import httpx


COORDINATE_CACHE_SECONDS = 6 * 60 * 60


def _coordinate_cache():
    from .google_location_lifecycle import cache_client
    return cache_client()  # Deliberately no fallback to persistent broker Redis.


def _coordinate_key(place_id: str) -> str:
    return "planner-coordinates:v1:" + hashlib.sha256(place_id.encode()).hexdigest()


def _read_coordinate_cache(ideas: list[dict]) -> tuple[Any, dict[str, dict]]:
    ids = list(dict.fromkeys(value for idea in ideas if (value := _place_id(idea.get("google_place_id")))))
    if not ids:
        return None, {}
    try:
        cache = _coordinate_cache()
        entries = cache.mget([_coordinate_key(place_id) for place_id in ids])
        if not isinstance(entries, (list, tuple)) or len(entries) != len(ids):
            return cache, {}
    except Exception:
        return None, {}
    found = {}
    for place_id, encoded in zip(ids, entries):
        try:
            raw = json.loads(encoded or "null")
            if not isinstance(raw, dict) or set(raw) != {"place_id", "latitude", "longitude", "expires_at"}:
                continue
            expiry = raw["expires_at"]
            if type(expiry) not in {int, float} or not time.time() < expiry <= time.time() + COORDINATE_CACHE_SECONDS + 60:
                continue
            coords = coordinates(raw)
            if raw["place_id"] == place_id and coords:
                found[place_id] = {"latitude": coords[0], "longitude": coords[1]}
        except (ValueError, TypeError):
            continue
    return cache, found


def _write_coordinate_cache(cache: Any, ideas: dict[str, dict], found: dict[str, dict]) -> None:
    if cache is None:
        return
    try:
        pipeline = cache.pipeline(transaction=False)
        written = set()
        for idea_id, fact in found.items():
            place_id, coords = _place_id(ideas[idea_id].get("google_place_id")), coordinates(fact)
            if not place_id or not coords or place_id in written:
                continue
            written.add(place_id)
            raw = {"place_id": place_id, "latitude": coords[0], "longitude": coords[1],
                   "expires_at": time.time() + COORDINATE_CACHE_SECONDS}
            pipeline.set(_coordinate_key(place_id), json.dumps(raw, allow_nan=False), ex=COORDINATE_CACHE_SECONDS)
        if written:
            pipeline.execute()
    except Exception:
        # Cache failure affects reuse only; no SQL or file cache is substituted.
        pass


def bounded_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (ValueError, TypeError):
        value = default
    return max(minimum, min(maximum, value))


def enabled(name: str, default: bool = True) -> bool:
    return os.getenv(name, str(default)).strip().lower() not in {"0", "false", "off", "no"}


def secret(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value and os.getenv(name + "_FILE"):
        try:
            value = Path(os.environ[name + "_FILE"]).read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError):
            return ""
    if len(value) > 1024 or any(ord(char) < 32 or ord(char) > 126 for char in value):
        return ""
    return value


def coordinates(idea: dict) -> tuple[float, float] | None:
    try:
        lat, lon = float(idea["latitude"]), float(idea["longitude"])
    except (KeyError, ValueError, TypeError):
        return None
    if math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180:
        return lat, lon
    return None


def distance_km(a: dict, b: dict) -> float | None:
    left, right = coordinates(a), coordinates(b)
    if left is None or right is None:
        return None
    lat1, lat2 = math.radians(left[0]), math.radians(right[0])
    dlat, dlon = lat2 - lat1, math.radians(right[1] - left[1])
    hav = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6371.0088 * 2 * math.asin(math.sqrt(max(0, min(1, hav))))


def _place_id(value: Any) -> str | None:
    if isinstance(value, str) and 1 <= len(value) <= 512 and all(
        char.isascii() and (char.isalnum() or char in "_-") for char in value
    ):
        return value
    return None


def _clock(value: Any) -> int | None:
    if not isinstance(value, dict):
        return None
    hour, minute = value.get("hour", 0), value.get("minute", 0)
    if type(hour) is int and type(minute) is int and 0 <= hour <= 23 and 0 <= minute <= 59:
        return hour * 60 + minute
    return None


def opening_windows(hours: dict, dates: list[str], *, dated: bool = False) -> dict[str, list[list[int]]]:
    """Convert provider periods to destination-local windows, including overnight.

    An absent periods field is unknown. Explicit empty periods means closed.
    Current hours are only applied to explicit dated periods, never extrapolated
    into future weeks. Regular weekly hours can be used as a provisional guide.
    """
    periods = hours.get("periods") if isinstance(hours, dict) else None
    if not isinstance(periods, list):
        return {}
    if not periods:
        return {} if dated else {day: [] for day in dates}
    result: dict[str, list[list[int]]] = {}
    for day in dates:
        target = date.fromisoformat(day)
        windows: list[list[int]] = []
        known = not dated
        for period in periods:
            if not isinstance(period, dict):
                continue
            opening, closing = period.get("open"), period.get("close")
            if not isinstance(opening, dict):
                continue
            start = _clock(opening)
            if start is None:
                continue
            if closing is None and opening.get("day") == 0 and start == 0 and not dated:
                windows.append([0, 1440])
                continue
            if not isinstance(closing, dict):
                continue
            finish = _clock(closing)
            if finish is None:
                continue
            if dated:
                try:
                    od, cd = opening["date"], closing["date"]
                    open_date = date(int(od["year"]), int(od["month"]), int(od["day"]))
                    close_date = date(int(cd["year"]), int(cd["month"]), int(cd["day"]))
                except (KeyError, ValueError, TypeError):
                    continue
                if open_date <= target <= close_date:
                    known = True
                    low = start if target == open_date else 0
                    high = finish if target == close_date else 1440
                    if high > low:
                        windows.append([low, high])
            else:
                od, cd = opening.get("day"), closing.get("day")
                if type(od) is not int or type(cd) is not int or not (0 <= od < 7 and 0 <= cd < 7):
                    continue
                weekday = (target.weekday() + 1) % 7
                duration_days = (cd - od) % 7
                if duration_days == 0 and finish <= start:
                    duration_days = 1
                since_open = (weekday - od) % 7
                if since_open <= duration_days:
                    low = start if since_open == 0 else 0
                    high = finish if since_open == duration_days else 1440
                    if high > low:
                        windows.append([low, high])
        if known:
            result[day] = sorted(windows)
    return result


async def _live_places(ideas: list[dict], dates: list[str], key: str) -> tuple[dict, list[str]]:
    facts: dict[str, dict] = {}
    warnings: list[str] = []
    limit = bounded_int("PLANNER_PLACE_LOOKUP_LIMIT", 10, 0, 60)
    # Saved stay options share the existing request cap, using a small reserve
    # for coordinates only. They never trigger hotel search or hours lookups.
    groups: dict[str, list[dict]] = {}
    for idea in ideas:
        place_id = _place_id(idea.get("google_place_id"))
        if place_id:
            groups.setdefault(place_id, []).append(idea)
    def is_visit(idea: dict) -> bool:
        return (str(idea.get("category") or "").lower() not in {"stay", "hotel", "accommodation", "lodging"}
                or bool(idea.get("schedule_as_visit")))
    visit_groups = [group for group in groups.values() if any(is_visit(idea) for idea in group)]
    stay_groups = [group for group in groups.values() if not any(is_visit(idea) for idea in group)
                   and not any(coordinates(idea) for idea in group)
                   and any(not idea.get("closed") and idea.get("score", 0) >= 0 for idea in group)]
    from .planner_geography import geography
    activity_areas = {geography(idea.get("country"), idea.get("city")) for idea in ideas if is_visit(idea)}
    stay_groups.sort(key=lambda group: (
        geography(group[0].get("country"), group[0].get("city")) not in activity_areas,
        not any(idea.get("must_do") for idea in group), -max(idea.get("score", 0) for idea in group),
        group[0]["google_place_id"],
    ))
    # At the default cap of 10, up to 3 saved stays and at least 7 visits.
    # Very small configured caps (<3) rely on cached/manual hotel coordinates.
    stay_targets = [group[0] for group in stay_groups[:min(3, limit // 3)]] if activity_areas else []
    coordinate_only_ids = {idea["google_place_id"] for idea in stay_targets}
    targets = [group[0] for group in visit_groups[:max(0, limit - len(stay_targets))]] + stay_targets
    if not targets:
        return facts, warnings
    semaphore = asyncio.Semaphore(5)
    async with httpx.AsyncClient(timeout=5.0, follow_redirects=False) as client:
        async def read(idea: dict) -> None:
            async with semaphore:
                try:
                    response = await client.get(
                        "https://places.googleapis.com/v1/places/" + quote(idea["google_place_id"], safe=""),
                        headers={"X-Goog-Api-Key": key, "X-Goog-FieldMask":
                                 "id,location" if idea["google_place_id"] in coordinate_only_ids else
                                 "id,location,regularOpeningHours,currentOpeningHours,businessStatus,utcOffsetMinutes"},
                    )
                    if response.status_code != 200:
                        return
                    raw = response.json()
                    if not isinstance(raw, dict) or raw.get("id") != idea["google_place_id"]:
                        return
                    fact: dict[str, Any] = {}
                    coords = coordinates(raw.get("location") or {})
                    if coords:
                        fact["latitude"], fact["longitude"] = coords
                    if idea["google_place_id"] in coordinate_only_ids:
                        for sibling in groups[idea["google_place_id"]]:
                            facts[str(sibling["id"])] = dict(fact)
                        return
                    fact["closed"] = raw.get("businessStatus") in {"CLOSED_PERMANENTLY", "CLOSED_TEMPORARILY"}
                    windows = opening_windows(raw.get("regularOpeningHours") or {}, dates)
                    current_hours = raw.get("currentOpeningHours") or {}
                    current = opening_windows(current_hours, dates, dated=True)
                    offset = raw.get("utcOffsetMinutes")
                    if type(offset) is int and -840 <= offset <= 840 and isinstance(current_hours.get("periods"), list):
                        today = (datetime.now(timezone.utc) + timedelta(minutes=offset)).date()
                        for day in dates:
                            if today <= date.fromisoformat(day) < today + timedelta(days=7):
                                # A closed holiday has no current period. Do not
                                # accidentally resurrect its regular weekly hours.
                                current.setdefault(day, [])
                    windows.update(current)
                    if windows:
                        fact["opening_windows"] = windows
                        fact["hours_source"] = "google"
                    for sibling in groups[idea["google_place_id"]]:
                        facts[str(sibling["id"])] = dict(fact)
                except (httpx.HTTPError, ValueError, TypeError, KeyError):
                    return
        try:
            await asyncio.wait_for(asyncio.gather(*(read(idea) for idea in targets)), timeout=15)
        except asyncio.TimeoutError:
            warnings.append("Some opening hours could not be checked. Confirm them before travelling.")
    if any(str(idea["id"]) not in facts for idea in targets):
        warnings.append("Some place details are unavailable; those stops need a quick check.")
    if len(visit_groups) + len(stay_groups) > len(targets):
        warnings.append("Only a bounded set of place details was checked for this draft.")
    return facts, warnings


@dataclass
class FactSet:
    ideas: dict[str, dict]
    transport: str
    routes: dict[tuple[str, str], tuple[int | None, str]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    route_key: str = ""
    route_calls: int = 0
    route_limit: int = 12
    route_deadline: float = 0
    blocked_routes: set[tuple[str, str]] = field(default_factory=set)
    transport_modes: list[str] = field(default_factory=list)
    route_modes: dict[tuple[str, str], str] = field(default_factory=dict)

    @property
    def modes(self) -> list[str]:
        return self.transport_modes or [self.transport]

    @property
    def area_mode(self) -> str:
        return "drive" if "drive" in self.modes else "transit" if "transit" in self.modes else "walk"

    def mode_for(self, left: dict | None, right: dict | None) -> str:
        pair = (str((left or {}).get("id", "")), str((right or {}).get("id", "")))
        if pair in self.route_modes and self.route_modes[pair] in self.modes:
            return self.route_modes[pair]
        km = distance_km(left, right) if left and right else None
        if "walk" in self.modes and km is not None and km <= 2:
            return "walk"
        return "drive" if "drive" in self.modes else "transit" if "transit" in self.modes else "walk"

    def can_query_route(self, left: dict | None, right: dict | None) -> bool:
        """Whether an unknown leg can still receive a bounded factual check."""
        if not left or not right or not self.route_key or self.route_calls >= self.route_limit or time.monotonic() >= self.route_deadline:
            return False
        if (str(left.get("id", "")), str(right.get("id", ""))) in self.blocked_routes or self.mode_for(left, right) == "transit":
            return False
        return all(coordinates(idea) or _place_id(idea.get("google_place_id")) for idea in (left, right))

    def travel(self, left: dict | None, right: dict | None, *, live: bool = False) -> tuple[int | None, str]:
        if not left or not right:
            return 0, "estimate"
        a, b = str(left.get("id", "")), str(right.get("id", ""))
        if a and a == b:
            return 0, "estimate"
        if (a, b) in self.blocked_routes:
            return None, "unknown"
        if (a, b) in self.routes:
            return self.routes[a, b]
        if live and self.route_key and self.route_calls < self.route_limit and time.monotonic() < self.route_deadline:
            actual = self._google_route(left, right)
            if actual is not None:
                self.routes[a, b] = actual
                return actual
        km = distance_km(left, right)
        mode = self.mode_for(left, right)
        if km is None or mode == "transit":
            return None, "unknown"
        # Straight-line distances are not routes. Explicitly labelled estimates
        # are acceptable for drafts; never manufacture a transit connection.
        if mode == "walk":
            minutes = math.ceil(km * 1.35 / 4.5 * 60)
        else:
            speed = 30 if km < 15 else 55
            minutes = math.ceil(km * 1.4 / speed * 60 + 5)
        return max(5, minutes), "estimate"

    def _google_route(self, left: dict, right: dict) -> tuple[int | None, str] | None:
        # Transit durations depend on a particular departure date and time. The
        # constructive draft can still move these stops while fitting a day, so
        # a request without that context would silently use today's timetable.
        # Keep the transfer explicitly unverified until timetable-aware routing
        # can check the final departure time and provider's supported date range.
        mode = self.mode_for(left, right)
        if mode == "transit":
            return None

        def waypoint(idea: dict) -> dict | None:
            place_id = _place_id(idea.get("google_place_id"))
            if place_id:
                return {"placeId": place_id}
            coords = coordinates(idea)
            return {"location": {"latLng": {"latitude": coords[0], "longitude": coords[1]}}} if coords else None
        origin, destination = waypoint(left), waypoint(right)
        if not origin or not destination:
            return None
        self.route_calls += 1
        try:
            response = httpx.post(
                "https://routes.googleapis.com/directions/v2:computeRoutes",
                headers={"X-Goog-Api-Key": self.route_key, "X-Goog-FieldMask": "routes.duration"},
                json={"origin": origin, "destination": destination,
                      "travelMode": {"walk": "WALK", "drive": "DRIVE", "transit": "TRANSIT"}[mode]},
                timeout=max(.1, min(4.0, self.route_deadline - time.monotonic())),
                follow_redirects=False,
            )
            if response.status_code in {401, 403, 429}:
                self.route_key = ""  # A broken service must not cause 20 identical calls.
            if response.status_code != 200:
                return None
            raw = response.json()
            if not isinstance(raw, dict) or not isinstance(raw.get("routes"), list):
                return None
            if not raw["routes"]:
                self.blocked_routes.add((str(left.get("id", "")), str(right.get("id", ""))))
                return None, "unknown"
            duration = raw["routes"][0].get("duration", "")
            seconds = float(duration[:-1]) if isinstance(duration, str) and duration.endswith("s") else math.nan
            if math.isfinite(seconds) and 0 <= seconds <= 7 * 86400:
                return math.ceil(seconds / 60), "google"
        except (httpx.HTTPError, ValueError, TypeError, KeyError, IndexError):
            pass
        return None


def collect_display_facts(payload: dict) -> FactSet:
    """Manual coordinates/volatile cache only. No provider requests or keys."""
    ideas = {str(idea["id"]): dict(idea) for idea in payload.get("ideas", [])}
    trip = payload["trip"]
    facts = FactSet(ideas, trip.get("transport", "walk"),
                    transport_modes=list(trip.get("transport_modes") or [trip.get("transport", "walk")]))
    if enabled("PLANNER_FACTS_ENABLED"):
        _, cached = _read_coordinate_cache(list(ideas.values()))
        for idea in ideas.values():
            if not coordinates(idea) and idea.get("google_place_id") in cached:
                idea.update(cached[idea["google_place_id"]])
    return facts


def collect_facts(payload: dict, dates: list[str], *, live: bool = True) -> FactSet:
    ideas = {str(idea["id"]): dict(idea) for idea in payload.get("ideas", [])}
    trip = payload["trip"]
    facts = FactSet(ideas, trip.get("transport", "walk"))
    facts.transport_modes = list(trip.get("transport_modes") or [facts.transport])
    for item in payload.get("routes", []):
        if not isinstance(item, dict):
            continue
        a, b, minutes = str(item.get("from_id", "")), str(item.get("to_id", "")), item.get("minutes")
        if a in ideas and b in ideas and type(minutes) in {int, float} and math.isfinite(minutes) and 0 <= minutes <= 10080:
            facts.routes[a, b] = (math.ceil(minutes), item.get("source") if item.get("source") in {"google", "estimate"} else "estimate")
            if item.get("mode") in facts.modes:
                facts.route_modes[a, b] = item["mode"]
    if enabled("PLANNER_FACTS_ENABLED"):
        cache, cached = _read_coordinate_cache(list(ideas.values()))
        manual_coords = {idea_id: coordinates(idea) for idea_id, idea in ideas.items()}
        for idea in ideas.values():
            if not coordinates(idea) and idea.get("google_place_id") in cached:
                idea.update(cached[idea["google_place_id"]])
        key = secret("GOOGLE_PLACES_API_KEY")
        if key and live:
            found, warnings = asyncio.run(_live_places(list(ideas.values()), dates, key))
            _write_coordinate_cache(cache, ideas, found)
            facts.warnings.extend(warnings)
            for idea_id, live in found.items():
                # User-supplied scheduling windows win over general provider hours.
                user_hours = ideas[idea_id].get("opening_windows")
                ideas[idea_id].update(live)
                if manual_coords[idea_id]:
                    ideas[idea_id]["latitude"], ideas[idea_id]["longitude"] = manual_coords[idea_id]
                if isinstance(user_hours, dict):
                    ideas[idea_id]["opening_windows"] = {**live.get("opening_windows", {}), **user_hours}
        if live:
            facts.route_key = secret("GOOGLE_ROUTES_API_KEY") or key
    facts.route_limit = bounded_int("PLANNER_ROUTE_LOOKUP_LIMIT", 12, 0, 60)
    facts.route_deadline = time.monotonic() + bounded_int("PLANNER_ROUTE_TIMEOUT_SECONDS", 20, 1, 45)
    return facts
