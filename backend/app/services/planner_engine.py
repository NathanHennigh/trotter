"""Automatic itinerary composition with deterministic scheduling and validation.

This bounded constructive scheduler deliberately makes no global-optimum claim.
AI selects a shortlist, day grouping and visit order; Python independently owns
the calendar, routes, opening windows, locked commitments and persisted shape.
All public validation is pure and safe to call from ordinary editor endpoints.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import math
import re
import time
from typing import Any
from uuid import NAMESPACE_URL, uuid5
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import planner_ai
from .planner_facts import FactSet, bounded_int, collect_facts, collect_display_facts, coordinates, distance_km


MAX_IDEAS = 200
PACE = {"relaxed": (3, 9 * 60, 18 * 60, 25),
        "balanced": (4, 9 * 60, 20 * 60, 20),
        "packed": (6, 8 * 60 + 30, 21 * 60, 15)}
FOOD = {"food", "restaurant", "dining", "cafe", "coffee", "bakery", "bar"}
MEALS = {"food", "restaurant", "dining"}
STAYS = {"stay", "hotel", "accommodation", "lodging"}
EMPTY_DAY_NOTE = "No saved activities fit this day yet. Add ideas, or keep the time open."
EXCLUSION_CODES = {"needs_location", "processing", "closed", "opening_hours", "transport_required",
                   "travel_unverified", "low_interest", "duplicate", "no_fit"}


def trip_dates(trip: dict) -> list[str]:
    try:
        start, end = date.fromisoformat(trip["start_date"]), date.fromisoformat(trip["end_date"])
    except (KeyError, TypeError, ValueError):
        raise ValueError("Choose valid start and end dates for this trip.") from None
    count = (end - start).days + 1
    if not 1 <= count <= 31:
        raise ValueError("Plan between 1 and 31 days at a time.")
    try:
        ZoneInfo(trip.get("timezone") or "UTC")
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        raise ValueError("Choose a valid timezone for this trip.") from None
    if trip.get("pace", "balanced") not in PACE or trip.get("transport", "walk") not in {"walk", "drive", "transit"}:
        raise ValueError("Choose a valid pace and travel mode.")
    modes = trip.get("transport_modes")
    if modes is not None and (not isinstance(modes, list) or not modes or len(modes) > 3
                              or any(mode not in {"walk", "drive", "transit"} for mode in modes)
                              or len(set(modes)) != len(modes)):
        raise ValueError("Choose one or more distinct travel modes.")
    return [(start + timedelta(days=i)).isoformat() for i in range(count)]


def minutes(value: Any) -> int:
    if not isinstance(value, str) or not re.fullmatch(r"\d{2}:\d{2}", value):
        raise ValueError("Use a valid local time, such as 09:30.")
    h, m = map(int, value.split(":"))
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise ValueError("Use a valid local time, such as 09:30.")
    return h * 60 + m


def clock(value: int) -> str:
    return f"{value // 60:02d}:{value % 60:02d}"


def _local_start(day: str, start: int, timezone_name: str) -> datetime:
    naive = datetime.combine(date.fromisoformat(day), datetime.min.time()) + timedelta(minutes=start)
    local = naive.replace(tzinfo=ZoneInfo(timezone_name))
    if local.astimezone(timezone.utc).astimezone(local.tzinfo).replace(tzinfo=None) != naive:
        raise ValueError("This local time does not exist because the clocks change. Choose another time.")
    return local


def _ending_minute(stop: dict, day: str, timezone_name: str) -> int:
    start = _local_start(day, minutes(stop["start_time"]), timezone_name)
    end = (start.astimezone(timezone.utc) + timedelta(minutes=stop["duration_minutes"])).astimezone(start.tzinfo)
    return (end.date() - date.fromisoformat(day)).days * 1440 + end.hour * 60 + end.minute


def _text(value: Any, limit: int = 255) -> str:
    return " ".join(value.split())[:limit] if isinstance(value, str) else ""


def _integer(value: Any, low: int, high: int, message: str) -> int:
    if type(value) is not int or not low <= value <= high:
        raise ValueError(message)
    return value


def _locked(stop: dict) -> bool:
    return (bool(stop.get("locked")) or stop.get("kind") == "booking"
            or stop.get("kind") == "break" and (stop.get("user_created") or not stop.get("generated")))


def _validated_stay(raw: Any, ideas: dict) -> dict:
    if not isinstance(raw, dict) or raw.get("status") not in {"needed", "suggested", "selected", "not_needed"}:
        raise ValueError("Choose a saved stay or mark accommodation as needed.")
    result = {"status": raw["status"]}
    if raw["status"] in {"selected", "suggested"}:
        idea_id = str(raw.get("idea_id") or "")
        if idea_id not in ideas:
            raise ValueError("This accommodation is no longer in the trip. Choose another saved stay.")
        if _category(ideas[idea_id]) not in STAYS:
            raise ValueError("Choose an accommodation save for this overnight stay.")
        result["idea_id"] = idea_id
    for key in ("city", "reason"):
        value = _text(raw.get(key), 128 if key == "city" else 255)
        if value:
            result[key] = value
    return result


def validate_plan(plan: dict, payload: dict, *, preserve_locked: bool = False) -> dict:
    """Normalize an editable plan or raise a user-safe ValueError; no I/O.

    Duration and overlap validation include overnight booked commitments.
    When generating, locked stops must retain every persisted user field.
    Unknown opening/travel facts are warnings, not purported verified data.
    """
    dates = trip_dates(payload.get("trip") or {})
    ideas = {str(item["id"]): item for item in payload.get("ideas", []) if isinstance(item, dict) and "id" in item}
    if not isinstance(plan, dict) or not isinstance(plan.get("days"), list) or len(plan["days"]) > 31:
        raise ValueError("The itinerary needs a valid list of days.")
    days: dict[str, list[dict]] = {}
    day_details: dict[str, dict] = {}
    stop_ids, used_ideas, stay_ideas, absolute = set(), set(), set(), []
    timezone_name = payload["trip"].get("timezone") or "UTC"
    clocks_change = False
    for day in plan["days"]:
        if not isinstance(day, dict) or day.get("date") not in dates or day["date"] in days:
            raise ValueError("Each itinerary day must appear once within the trip dates.")
        if not isinstance(day.get("stops"), list) or len(day["stops"]) > 50:
            raise ValueError("A day can contain at most 50 stops.")
        local = []
        day_details[day["date"]] = {}
        if "stay" in day:
            day_details[day["date"]]["stay"] = _validated_stay(day["stay"], ideas)
            if day_details[day["date"]]["stay"].get("idea_id"):
                stay_ideas.add(day_details[day["date"]]["stay"]["idea_id"])
        if _text(day.get("planning_note"), 500):
            day_details[day["date"]]["planning_note"] = _text(day["planning_note"], 500)
        for stop in day["stops"]:
            if not isinstance(stop, dict):
                raise ValueError("Each stop must contain valid details.")
            identifier = stop.get("id")
            if not isinstance(identifier, str) or not 1 <= len(identifier) <= 100 or identifier in stop_ids:
                raise ValueError("Each stop needs its own unique identifier.")
            stop_ids.add(identifier)
            kind = stop.get("kind", "place")
            if kind not in {"place", "booking", "break"}:
                raise ValueError("Choose a place, booking or break for this stop.")
            idea_id = stop.get("idea_id")
            if idea_id is not None:
                idea_id = str(idea_id)
                if idea_id not in ideas:
                    raise ValueError("One of these places is no longer in this trip. Refresh the plan.")
                if idea_id in used_ideas:
                    raise ValueError("A saved place can appear only once in this itinerary.")
                used_ideas.add(idea_id)
            elif kind == "place":
                raise ValueError("Add the place to Ideas before putting it in the itinerary.")
            start = minutes(stop.get("start_time"))
            duration = _integer(stop.get("duration_minutes"), 5, 2880 if kind == "booking" else 1440,
                                "Choose a valid visit duration of at least five minutes.")
            local_start = _local_start(day["date"], start, timezone_name)
            local_end = (local_start.astimezone(timezone.utc) + timedelta(minutes=duration)).astimezone(local_start.tzinfo)
            clocks_change |= (local_start.utcoffset() != local_start.replace(fold=1).utcoffset()
                              or local_start.utcoffset() != local_end.utcoffset())
            if _ending_minute(stop, day["date"], timezone_name) > 1440 and kind != "booking":
                raise ValueError("Move this stop earlier or shorten it so it finishes within the day.")
            title = _text(stop.get("title"))
            if not title:
                raise ValueError("Give every stop a name.")
            if type(stop.get("locked", False)) is not bool:
                raise ValueError("Choose whether this stop is locked.")
            normalized: dict[str, Any] = {"id": identifier, "title": title, "start_time": clock(start),
                                          "duration_minutes": duration, "locked": stop.get("locked", False), "kind": kind}
            for flag in ("user_created", "generated", "travel_blocked"):
                if flag in stop:
                    if type(stop[flag]) is not bool:
                        raise ValueError("Choose valid stop details.")
                    normalized[flag] = stop[flag]
            if idea_id is not None:
                normalized["idea_id"] = idea_id
                # A model or stale client cannot silently rename the selected venue.
                normalized["title"] = _text(ideas[idea_id].get("title")) or title
            if stop.get("notes"):
                normalized["notes"] = _text(stop["notes"], 1000)
            if stop.get("travel_source") in {"google", "estimate", "unknown"}:
                normalized["travel_source"] = stop["travel_source"]
            if stop.get("travel_minutes") is not None:
                normalized["travel_minutes"] = _integer(stop["travel_minutes"], 0, 10080, "Travel time is invalid.")
                normalized.setdefault("travel_source", "estimate")
            if stop.get("travel_mode") in {"walk", "drive", "transit"}:
                normalized["travel_mode"] = stop["travel_mode"]
            if isinstance(stop.get("travel_from_stop_id"), str) and len(stop["travel_from_stop_id"]) <= 100:
                normalized["travel_from_stop_id"] = stop["travel_from_stop_id"]
            local.append(normalized)
            absolute.append((local_start.timestamp() / 60, local_start.timestamp() / 60 + duration, normalized))
        days[day["date"]] = sorted(local, key=lambda s: (s["start_time"], s["id"]))
        if (day_details[day["date"]].get("planning_note") == EMPTY_DAY_NOTE
                and any(stop.get("idea_id") and stop["kind"] != "break" for stop in local)):
            day_details[day["date"]].pop("planning_note", None)
    absolute.sort(key=lambda part: (part[0], part[2]["id"]))
    for left, right in zip(absolute, absolute[1:]):
        if left[1] > right[0]:
            raise ValueError("Two stops overlap. Move or shorten one before saving.")
    if preserve_locked:
        proposed = {stop["id"]: (day, stop) for day, stops in days.items() for stop in stops}
        for old_day in (payload.get("existing_plan") or {}).get("days", []):
            for old_stop in old_day.get("stops", []):
                if not _locked(old_stop):
                    continue
                found = proposed.get(old_stop["id"])
                if not found or found[0] != old_day["date"]:
                    raise ValueError("A locked booking or stop would move. Unlock it before reworking the plan.")
                for key in ("idea_id", "start_time", "duration_minutes", "kind", "locked", "notes", "user_created", "generated"):
                    if found[1].get(key) != old_stop.get(key):
                        raise ValueError("A locked booking or stop would change. Unlock it before reworking the plan.")
    warnings = []
    for warning in plan.get("warnings", []) if isinstance(plan.get("warnings", []), list) else []:
        clean = _text(warning, 500)
        if (clean and clean not in warnings and not re.match(r"^\d+ ideas? remain(?:s)? in Ideas;", clean)
                and not clean.startswith("Stay options remain in Ideas.")):
            warnings.append(clean)
    if clocks_change:
        warnings.append("Clocks change around a booking or visit. Confirm local booking times, especially any repeated hour.")
    unplaced = [idea_id for idea_id in ideas if idea_id not in used_ideas | stay_ideas]
    result = {"days": [{"date": day, "stops": days.get(day, []), **day_details.get(day, {})} for day in dates],
              "warnings": warnings[:30], "unplaced_idea_ids": unplaced}
    if "unplaced_reasons" in plan:
        # Derived metadata cannot introduce foreign IDs, free-form provider
        # content, or reasons for places already added through the editor.
        raw = plan["unplaced_reasons"] if isinstance(plan["unplaced_reasons"], dict) else {}
        reasons = {}
        for idea_id in unplaced:
            reason = raw.get(idea_id)
            if (_category(ideas[idea_id]) in STAYS or not isinstance(reason, dict)
                    or not isinstance(reason.get("code"), str) or reason["code"] not in EXCLUSION_CODES):
                continue
            code = reason["code"]
            if code == "needs_location" and (coordinates(ideas[idea_id]) or _text(ideas[idea_id].get("city"))) and ideas[idea_id].get("title"):
                continue
            if code == "processing" and ideas[idea_id].get("status") != "processing":
                continue
            if code == "low_interest" and (ideas[idea_id].get("score", 0) >= 0 or ideas[idea_id].get("must_do")):
                continue
            clean_reason = {"code": code}
            if code == "transport_required":
                mode = reason.get("transport_mode")
                current_modes = payload["trip"].get("transport_modes") or [payload["trip"].get("transport", "walk")]
                if not isinstance(mode, str) or mode not in {"walk", "drive", "transit"} or current_modes != [mode]:
                    continue
                clean_reason["transport_mode"] = mode
            reasons[idea_id] = clean_reason
        result["unplaced_reasons"] = reasons
    return result


def plan_for_storage(plan: dict) -> dict:
    """Keep app decisions, not transient provider route content, in history."""
    result = deepcopy(plan)
    for day in result.get("days", []):
        for stop in day.get("stops", []):
            if stop.get("travel_source") == "google":
                stop.pop("travel_minutes", None)
    return result


def _refresh_travel(plan: dict, facts: FactSet, *, only_day: str | None = None) -> dict:
    """Display only independent app estimates for consecutive physical stops."""
    result = deepcopy(plan)
    estimates = FactSet(facts.ideas, facts.transport, transport_modes=list(facts.modes))
    estimates.blocked_routes = set(facts.blocked_routes)
    for day in result.get("days", []):
        if only_day and day["date"] != only_day:
            continue
        previous, previous_place = None, None
        for stop in day.get("stops", []):
            prior_leg = {key: stop.get(key) for key in ("travel_blocked", "travel_from_stop_id", "travel_mode")}
            for key in ("travel_minutes", "travel_source", "travel_from_stop_id", "travel_mode", "travel_blocked"):
                stop.pop(key, None)
            if stop.get("kind") == "break":
                continue
            if stop.get("kind") == "booking" and str(stop.get("idea_id")) not in estimates.ideas:
                # A flight/reservation without a shared location is not a pin.
                previous, previous_place = None, None
                continue
            current = _stop_idea(stop, estimates)
            if current is None:
                continue  # A text/rest break has no invented physical location.
            if previous is not None:
                pair = (str(previous_place.get("id", "")), str(current.get("id", "")))
                if (prior_leg["travel_blocked"] and prior_leg["travel_from_stop_id"] == previous["id"]
                        and prior_leg["travel_mode"] == estimates.mode_for(previous_place, current)):
                    estimates.blocked_routes.add(pair)
                duration, source = estimates.travel(previous_place, current)
                stop.update(travel_from_stop_id=previous["id"], travel_mode=estimates.mode_for(previous_place, current),
                            travel_source=source)
                if duration is not None:
                    stop["travel_minutes"] = duration
                if pair in estimates.blocked_routes:
                    stop["travel_blocked"] = True
            previous, previous_place = stop, current
    return result


def refresh_plan_travel(plan: dict, payload: dict) -> dict:
    """Recompute display legs after edits/reads; no AI or paid provider calls.

    Uses only manual coordinates and the existing ephemeral coordinate cache.
    It never mutates an ORM plan, fetches hours/routes or infers a missing pin.
    """
    trip_dates(payload["trip"])
    facts = collect_display_facts(payload)
    return _refresh_travel(plan, facts)


def _category(idea: dict) -> str:
    category = str(idea.get("category") or "unknown").lower()
    if category in MEALS and re.search(r"\b(coffee|cafe|café|bakery)\b", str(idea.get("title") or ""), re.IGNORECASE):
        return "cafe"
    return category


def _duration(idea: dict) -> int:
    requested = idea.get("_requested_duration_minutes")
    if type(requested) is int and 5 <= requested <= 1440:
        return requested
    default = 60 if _category(idea) in FOOD else 30 if _category(idea) in STAYS else 90
    value = idea.get("duration_minutes")
    return value if type(value) is int and 5 <= value <= 720 else default


def _votes(idea: dict) -> list[str]:
    return [str(vote["user_id"]) for vote in idea.get("votes", [])
            if isinstance(vote, dict) and vote.get("value") == 1 and "user_id" in vote]


def _score(idea: dict, satisfaction: Counter, categories: Counter) -> float:
    value = idea.get("score", 0)
    value = value if type(value) in {int, float} and math.isfinite(value) else 0
    return (10000 if idea.get("must_do") else 0) + value * 12 + sum(
        12 / (1 + satisfaction[user]) for user in _votes(idea)
    ) + 4 / (1 + categories[_category(idea)])


def _same_area(left: dict | None, right: dict | None, transport: str) -> bool:
    if not left or not right:
        return True
    from .planner_geography import geography
    country_a, a = geography(left.get("country"), left.get("city"))
    country_b, b = geography(right.get("country"), right.get("city"))
    if country_a and country_b and country_a != country_b:
        return False
    distance = distance_km(left, right)
    if distance is not None:
        return distance <= (15 if transport == "walk" else 50)
    # Unknown geography is not evidence that two venues share a city.
    return bool(a and b and a == b)


def _nonlocal_transfer(left: dict | None, right: dict | None, transport: str) -> bool:
    # An unlocated booking is a time constraint, not proof of a different city.
    return bool(left and right and (coordinates(left) or _text(left.get("city")))
                and (coordinates(right) or _text(right.get("city")))
                and not _same_area(left, right, transport))


def _known_location_context(known: dict | None, current: dict | None) -> dict | None:
    """Keep geographic evidence across same-city uncertainty, never invent a pin."""
    if not current:
        return known
    if coordinates(current):
        return current
    from .planner_geography import geography
    area = geography(current.get("country"), current.get("city"))
    if known and area[1] and area == geography(known.get("country"), known.get("city")):
        return known
    return None  # An unlocated journey or changed city resets the geographic base.


def _windows(idea: dict, day: str, begin: int, end: int) -> list[tuple[int, int]]:
    supplied = idea.get("opening_windows")
    if isinstance(supplied, dict) and day in supplied:
        entries = supplied[day]
        if not isinstance(entries, list):
            return []
        windows = []
        for entry in entries:
            if not isinstance(entry, (list, tuple)) or len(entry) != 2:
                continue
            a, b = entry
            try:
                a = minutes(a) if isinstance(a, str) else a
                b = 1440 if b == "24:00" else minutes(b) if isinstance(b, str) else b
            except ValueError:
                continue
            if type(a) is int and type(b) is int and 0 <= a < b <= 1440:
                windows.append((max(a, begin), min(b, end)))
        return [(a, b) for a, b in windows if b > a]
    return [(begin, end)]


def _identity(idea: dict) -> tuple | None:
    if idea.get("google_place_id"):
        return "google", str(idea["google_place_id"])
    # A name alone is never enough to merge venues. Exact manually supplied
    # coordinates plus exact name are a conservative cross-source identity.
    coords = coordinates(idea)
    if coords and _text(idea.get("title")):
        return "coordinates", _text(idea["title"]).casefold(), round(coords[0], 5), round(coords[1], 5)
    return None


def _normalize_ideas(raw: list) -> list[dict]:
    if not isinstance(raw, list) or len(raw) > MAX_IDEAS:
        raise ValueError(f"Choose at most {MAX_IDEAS} ideas for this planning pass.")
    result, ids = [], set()
    for item in raw:
        if not isinstance(item, dict) or not str(item.get("id") or "") or str(item["id"]) in ids:
            raise ValueError("The trip contains an invalid or repeated idea.")
        copied = dict(item)
        copied["id"] = str(copied["id"])
        copied["title"] = _text(copied.get("title"))
        if not copied["title"]:
            copied["status"] = "needs_details"
        ids.add(copied["id"])
        result.append(copied)
    return result


def _available(idea: dict) -> bool:
    if idea.get("closed") or idea.get("status") == "processing" or not idea.get("title"):
        return False
    if not (coordinates(idea) or _text(idea.get("city"))):
        return False
    # A saved hotel is a lodging choice, not an hour-long tourist attraction.
    # It enters the day schedule only through an explicit manual placement.
    if _category(idea) in STAYS and not idea.get("schedule_as_visit"):
        return False
    return True


def _brief(payload: dict, facts: FactSet, dates: list[str], available: list[dict], occupied: set[str]) -> dict:
    candidates = [idea for idea in available if idea["id"] not in occupied]
    candidates.sort(key=lambda idea: (-_score(idea, Counter(), Counter()), idea["id"]))
    candidates = candidates[:100]
    brief_ideas = []
    for idea in candidates:
        clean = {key: idea[key] for key in ("id", "title", "category", "city", "country", "latitude", "longitude", "score", "must_do")
                 if idea.get(key) is not None}
        clean["duration_minutes"] = _duration(idea)
        clean["supporters"] = _votes(idea)
        if isinstance(idea.get("opening_windows"), dict):
            clean["opening_windows"] = {day: idea["opening_windows"][day] for day in dates if day in idea["opening_windows"]}
        brief_ideas.append(clean)
    return {"destination": _text(payload["trip"].get("destination")), "dates": dates,
            "pace": payload.get("pace") or payload["trip"].get("pace", "balanced"),
            "transport": facts.transport, "transport_modes": facts.modes, "ideas": brief_ideas,
            "locked_stops": [{"date": day["date"], "idea_id": stop.get("idea_id"), "title": stop["title"],
                              "start_time": stop["start_time"], "duration_minutes": stop["duration_minutes"]}
                             for day in (payload.get("existing_plan") or {}).get("days", [])
                             if day["date"] in dates for stop in day["stops"] if _locked(stop)]}


def _stop_idea(stop: dict | None, facts: FactSet) -> dict | None:
    if not stop:
        return None
    known = facts.ideas.get(str(stop.get("idea_id")))
    if known:
        return known
    if stop.get("kind") == "booking":
        return {"id": "booking:" + stop["id"], "title": stop["title"]}
    return None


def _slot(idea: dict, day: str, stops: list[dict], facts: FactSet, begin: int, end: int,
          padding: int, prior_day: dict | None, carry_until: int, timezone_name: str,
          next_commitment: tuple[str, dict] | None, *, live_routes: bool = True) -> tuple[int, int | None, str | None] | None:
    duration = _duration(idea)
    ordered = sorted(stops, key=lambda stop: minutes(stop["start_time"]))
    # Fixed commitments may start before the ordinary day or continue overnight.
    intervals = []
    cursor, previous = max(begin, carry_until), None
    for stop in ordered:
        low, high = minutes(stop["start_time"]), _ending_minute(stop, day, timezone_name)
        if low > cursor:
            intervals.append((cursor, min(low, end), previous, stop))
        if high > cursor:
            cursor, previous = high, stop
    if cursor < end:
        intervals.append((cursor, end, previous, None))
    known_windows = _windows(idea, day, begin, end)
    candidates = []
    category = _category(idea)
    for left, right, previous, following in intervals:
        prev_idea = _stop_idea(previous, facts)
        if previous is not None and prev_idea is None:
            previous_start = minutes(previous["start_time"])
            prev_idea = next((_stop_idea(stop, facts) for stop in reversed(ordered)
                              if minutes(stop["start_time"]) < previous_start and _stop_idea(stop, facts)), None)
        if previous is None and prior_day and not _same_area(prior_day, idea, facts.area_mode):
            prev_idea = prior_day
        next_idea = _stop_idea(following, facts)
        if following is not None and next_idea is None:
            following_start = minutes(following["start_time"])
            next_idea = next((_stop_idea(stop, facts) for stop in ordered
                              if minutes(stop["start_time"]) > following_start and _stop_idea(stop, facts)), None)
        before, source = facts.travel(prev_idea, idea)
        after, _ = facts.travel(idea, next_idea)
        before_buffer = before if before is not None else 30
        after_buffer = after if after is not None else 30
        if prev_idea and before_buffer > (120 if facts.area_mode == "walk" else 360):
            continue
        left += before_buffer + (padding if previous else 0)
        if following:
            right -= after_buffer + padding
        for opening, closing in known_windows:
            low, high = max(left, opening), min(right, closing)
            if low + duration > high:
                continue
            # Meal/stay preferences are soft and never override opening hours.
            preferred = low
            penalty = 0
            if category in MEALS or category == "bar":
                meal_windows = [(17 * 60, 21 * 60)] if category == "bar" else [(11 * 60 + 30, 15 * 60), (17 * 60 + 30, 21 * 60)]
                targets = [max(low, opening, 18 * 60 if opening >= 17 * 60 and low <= 18 * 60 and 18 * 60 + duration <= min(high, closing) else 12 * 60 if opening < 17 * 60 and low <= 12 * 60 and 12 * 60 + duration <= min(high, closing) else opening)
                           for opening, closing in meal_windows
                           if max(low, opening) + duration <= min(high, closing)]
                if targets:
                    preferred = targets[0]
                else:
                    continue
            elif category in STAYS and low < 15 * 60 <= high - duration:
                preferred = 15 * 60
            candidates.append((preferred + penalty, preferred, previous, following, prev_idea, next_idea, source))
    # Use live routing only for a selected feasible gap, never every scoring pair.
    for _, chosen, previous, following, prev_idea, next_idea, _ in sorted(candidates, key=lambda part: part[0]):
        before, source = facts.travel(prev_idea, idea, live=live_routes)
        after, _ = facts.travel(idea, next_idea, live=live_routes)
        if ((before is None and _nonlocal_transfer(prev_idea, idea, facts.area_mode)
             and (live_routes or not facts.can_query_route(prev_idea, idea)))
                or (after is None and _nonlocal_transfer(idea, next_idea, facts.area_mode)
                    and (live_routes or not facts.can_query_route(idea, next_idea)))):
            if live_routes and "Some city-to-city journeys could not be verified; those ideas remain unscheduled." not in facts.warnings:
                facts.warnings.append("Some city-to-city journeys could not be verified; those ideas remain unscheduled.")
            continue
        if ((prev_idea and (str(prev_idea["id"]), idea["id"]) in facts.blocked_routes)
                or (next_idea and (idea["id"], str(next_idea["id"])) in facts.blocked_routes)):
            continue
        base = max(begin, carry_until) if previous is None else _ending_minute(previous, day, timezone_name) + padding
        chosen = max(chosen, base + (before if before is not None else 30 if prev_idea else 0))
        limit = end if following is None else minutes(following["start_time"]) - padding - (after if after is not None else 30)
        if before is not None and prev_idea and before > (120 if facts.area_mode == "walk" else 360):
            continue
        for opening, closing in known_windows:
            actual = max(chosen, opening)
            if actual + duration <= min(limit, closing):
                # Reworking today must not strand the group away from a fixed
                # commitment tomorrow. A booked journey with unknown endpoints
                # remains a time anchor rather than an invented route.
                future_place = _stop_idea(next_commitment[1], facts) if next_commitment else None
                if next_idea is None and _nonlocal_transfer(idea, future_place, facts.area_mode):
                    transfer, transfer_source = facts.travel(idea, future_place, live=live_routes)
                    if transfer is None and not live_routes and facts.can_query_route(idea, future_place):
                        # Keep a potentially routable candidate in the calendar.
                        # Actual placement must obtain and validate the route.
                        transfer = 0
                    if transfer is None:
                        if live_routes:
                            facts.warnings.append("Some city-to-city journeys could not be verified; those ideas remain unscheduled.")
                        continue
                    finish = _local_start(day, actual, timezone_name).timestamp() / 60 + duration
                    deadline = _local_start(next_commitment[0], minutes(next_commitment[1]["start_time"]), timezone_name).timestamp() / 60
                    later_breaks = sum(stop["duration_minutes"] for stop in stops
                                       if stop["kind"] == "break" and minutes(stop["start_time"]) >= actual + duration)
                    if (transfer > (120 if facts.area_mode == "walk" else 360)
                            or transfer + padding > deadline - finish - later_breaks):
                        continue
                    if live_routes and transfer_source == "estimate":
                        facts.warnings.append("Travel to a fixed commitment uses an estimated buffer; confirm the route.")
                return actual, before if prev_idea else None, source if prev_idea else None
    return None


def _schedule(payload: dict, facts: FactSet, dates: list[str], proposal: dict | None) -> dict:
    existing = payload.get("existing_plan") or {"days": []}
    target = payload.get("day")
    fixed_days = {day["date"]: deepcopy(day["stops"]) for day in existing["days"] if target and day["date"] != target}
    days = {day: fixed_days.get(day, []) for day in dates}
    for old_day in existing["days"]:
        if old_day["date"] not in fixed_days:
            days[old_day["date"]] = [deepcopy(stop) for stop in old_day["stops"] if _locked(stop)]
    used = {str(stop["idea_id"]) for stops in days.values() for stop in stops if stop.get("idea_id")}
    identity_used = {_identity(facts.ideas[key]) for key in used if key in facts.ideas}
    identity_used.discard(None)
    old_ids = {str(stop["idea_id"]): stop["id"] for day in existing["days"] for stop in day["stops"] if stop.get("idea_id")}
    old_details = {str(stop["idea_id"]): stop for day in existing["days"] for stop in day["stops"] if stop.get("idea_id")}
    offered = {day["date"]: day["idea_ids"] for day in (proposal or {}).get("days", [])}
    # AI choices are preferences, not a wall around the candidate pool. Other
    # eligible saves remain available when a shortlist cannot cover the trip.
    available = [idea for idea in facts.ideas.values() if _available(idea)
                 and (idea.get("must_do") or idea.get("score", 0) >= 0)]
    satisfaction = Counter(user for key in used if key in facts.ideas for user in _votes(facts.ideas[key]))
    warnings = list(facts.warnings)
    exclusion_evidence: dict[str, set[str]] = {}
    timezone_name = payload["trip"].get("timezone") or "UTC"
    pace = payload.get("pace") or payload["trip"].get("pace", "balanced")
    pace_cap, begin, end, padding = PACE[pace]
    # One bounded, provider-free calendar check per idea/date. Counting raw
    # IDs overfilled early days with duplicates, closed venues and impossible
    # visits. These dates reflect actual gaps around preserved commitments.
    feasible_dates = {idea["id"]: set() for idea in available}
    fixed_anchors = {}
    for future_index, future in enumerate(dates):
        fixed_anchors[future] = next((_stop_idea(stop, facts) for stop in days[future]
                                      if _stop_idea(stop, facts) and (coordinates(_stop_idea(stop, facts))
                                      or _text(_stop_idea(stop, facts).get("city")))), None)
        if future in fixed_days or sum(stop["kind"] != "break" for stop in days[future]) >= pace_cap:
            continue
        future_carry = max([0] + [(past_index - future_index) * 1440 + _ending_minute(stop, past, timezone_name)
                                 for past_index, past in enumerate(dates[:future_index]) for stop in days[past]])
        future_commitment = next(((later, stop) for later in dates[future_index + 1:] for stop in days[later]
                                  if _stop_idea(stop, facts)), None)
        for idea in available:
            if (idea["id"] not in used and _same_area(fixed_anchors[future], idea, facts.area_mode)
                    and _slot(idea, future, days[future], facts, begin, end, padding, None,
                              future_carry, timezone_name, future_commitment, live_routes=False) is not None):
                feasible_dates[idea["id"]].add(future)
    prior, known_prior = None, None
    for index, day in enumerate(dates):
        if day in fixed_days:
            for stop in days[day]:
                physical = _stop_idea(stop, facts)
                if physical:
                    prior, known_prior = physical, _known_location_context(known_prior, physical)
            continue
        cap = pace_cap
        anchor = fixed_anchors[day]
        rejected: set[str] = set()
        urgent_ids: set[str] = set()
        remaining_options: dict[str, set[str]] = {}
        def day_allowance(prospective_context: dict | None = None) -> int:
            nonlocal urgent_ids, remaining_options
            urgent_ids = set()
            remaining_options = {}
            if available:
                remaining = [idea for idea in available if idea["id"] not in used
                             and (_identity(idea) is None or _identity(idea) not in identity_used)]
                remaining_days = [value for value in dates[index:] if value not in fixed_days]
                unique_dates: dict[tuple, set[str]] = {}
                for idea in remaining:
                    possible = feasible_dates[idea["id"]].intersection(remaining_days)
                    if idea["id"] in rejected:
                        possible.discard(day)
                    context = prospective_context or _known_location_context(known_prior, anchor) or anchor or prior
                    known_blocked = bool(context and (str(context.get("id", "")), idea["id"]) in facts.blocked_routes)
                    if known_blocked or _nonlocal_transfer(context, idea, facts.area_mode):
                        transfer, _ = facts.travel(context, idea)  # Never a paid lookahead.
                        if ((transfer is None and not facts.can_query_route(context, idea))
                                or (transfer is not None and transfer > (120 if facts.area_mode == "walk" else 360))):
                            exclusion_evidence.setdefault(idea["id"], set()).add("transport_required" if transfer is not None else "travel_unverified")
                            # A fixed located commitment may establish a later base;
                            # otherwise this journey cannot inflate today's quota.
                            possible = {future for future in possible if fixed_anchors[future]
                                        and (not known_blocked or fixed_anchors[future].get("id") != context.get("id"))
                                        and _same_area(fixed_anchors[future], idea, facts.area_mode)}
                            warning = ("Some city-to-city journeys could not be verified; those ideas remain unscheduled." if transfer is None else
                                       "Some city-to-city journeys need more travel time or another transport mode; those ideas remain unscheduled.")
                            if warning not in facts.warnings:
                                facts.warnings.append(warning)
                    remaining_options[idea["id"]] = possible
                    if possible == {day}:
                        urgent_ids.add(idea["id"])
                    identity = _identity(idea) or ("idea", idea["id"])
                    unique_dates.setdefault(identity, set()).update(possible)
                fixed_count = sum(stop["kind"] != "break" for stop in days[day])
                # Scarce opening dates receive their fair share now; flexible saves
                # are spread over the dates they can really use. Duplicate aliases
                # contribute once, and zero-fit items contribute nothing.
                today_load = sum(1 / len(possible) for possible in unique_dates.values() if day in possible)
                viable = [possible for possible in unique_dates.values() if possible]
                future_days_to_cover = {future for possible in viable for future in possible if future != day
                                        and not any(stop["kind"] != "break" for stop in days[future])}
                today_minimum = int(not fixed_count and today_load > 0)
                reserve = min(len(future_days_to_cover), max(0, len(viable) - today_minimum))
                coverage_cap = max(sum(possible == {day} for possible in viable), len(viable) - reserve)
                return min(pace_cap, fixed_count + min(math.ceil(today_load - 1e-9), coverage_cap))
            return pace_cap
        cap = day_allowance()
        categories = Counter(_category(facts.ideas[stop["idea_id"]]) for stop in days[day] if stop.get("idea_id") in facts.ideas)
        carry = 0
        for previous_index, previous_day in enumerate(dates[:index]):
            for stop in days[previous_day]:
                carry = max(carry, (previous_index - index) * 1440 + _ending_minute(stop, previous_day, timezone_name))
        next_commitment = next(((future, stop) for future in dates[index + 1:] for stop in days[future]
                                if _stop_idea(stop, facts)), None)
        while sum(stop["kind"] != "break" for stop in days[day]) < cap:
            candidates = [idea for idea in available if idea["id"] not in used and idea["id"] not in rejected
                          and (_identity(idea) is None or _identity(idea) not in identity_used)
                          and (idea.get("must_do") or _category(idea) not in MEALS
                               or sum(categories[key] for key in MEALS) < 2)
                          and _same_area(anchor, idea, facts.area_mode)]
            if not candidates:
                break
            context = _known_location_context(known_prior, anchor) or anchor or prior
            base_coverage = {}
            if not coordinates(context or {}):
                # Choosing the first known point must not strand the rest of
                # the trip merely because an earlier pin was unknown. Compare
                # cached reachable venue counts; no routing request is made.
                remaining = [item for item in available if item["id"] not in used
                             and remaining_options.get(item["id"])]
                coverage_limit = sum(not any(stop["kind"] != "break" for stop in days[future])
                                     for future in dates[index:] if future not in fixed_days)
                for candidate in candidates:
                    if not coordinates(candidate):
                        continue
                    reachable = set()
                    for other in remaining:
                        duration, _ = facts.travel(candidate, other)
                        if ((duration is not None and duration <= (120 if facts.area_mode == "walk" else 360))
                                or (duration is None and _same_area(candidate, other, facts.area_mode))):
                            reachable.add(_identity(other) or ("idea", other["id"]))
                    base_coverage[candidate["id"]] = min(coverage_limit, len(reachable))
                best_coverage = max(base_coverage.values(), default=0)
                for candidate in candidates:
                    if not coordinates(candidate):
                        base_coverage[candidate["id"]] = best_coverage
            def rank(idea: dict) -> tuple:
                score = _score(idea, satisfaction, categories)
                options = remaining_options.get(idea["id"], set())
                ordered = offered.get(day, [])
                if idea["id"] in ordered:
                    score += 200 - ordered.index(idea["id"])
                elif proposal and not idea.get("must_do"):
                    # Preserve the model's day preference where possible, but
                    # permit remaining choices to cover later days safely.
                    if any(idea["id"] in offered.get(future, []) for future in dates[index + 1:]):
                        score -= 200
                if anchor:
                    km = distance_km(anchor, idea)
                    score -= min(km or 0, 100) * 2
                elif prior and _same_area(prior, idea, facts.area_mode):
                    score += 8
                # A flexible must-do can wait; a scarce opening date cannot.
                # Within equal date flexibility, must-dos/votes/AI order decide.
                return base_coverage.get(idea["id"], 0), int(idea["id"] in urgent_ids), -len(options) if day in options else -1000, score, idea["id"]
            candidates.sort(key=rank, reverse=True)
            idea = candidates[0]
            if coordinates(idea) and not coordinates(context or {}):
                cap = min(cap, day_allowance(idea))
                if sum(stop["kind"] != "break" for stop in days[day]) >= cap:
                    break
            fit = _slot(idea, day, days[day], facts, begin, end, padding, prior, carry, timezone_name, next_commitment)
            if fit is None:
                rejected.add(idea["id"])
                if any(right == idea["id"] for _, right in facts.blocked_routes):
                    exclusion_evidence.setdefault(idea["id"], set()).add("travel_unverified")
                cap = min(cap, day_allowance())
                continue
            start, travel, source = fit
            identifier = old_ids.get(idea["id"]) or str(uuid5(NAMESPACE_URL, f"trotter:{payload['trip'].get('id', '')}:{idea['id']}"))
            stop = {"id": identifier, "idea_id": idea["id"], "title": idea["title"], "start_time": clock(start),
                    "duration_minutes": _duration(idea), "locked": False, "kind": "place"}
            if old_details.get(idea["id"], {}).get("notes"):
                stop["notes"] = old_details[idea["id"]]["notes"]
            if source:
                stop["travel_source"] = source
            if travel is not None:
                stop["travel_minutes"] = travel
            if _category(idea) in STAYS and not stop.get("notes"):
                stop["notes"] = "Accommodation idea to review; this is not a confirmed booking."
            days[day].append(stop)
            days[day].sort(key=lambda item: (item["start_time"], item["id"]))
            used.add(idea["id"])
            identity = _identity(idea)
            if identity:
                identity_used.add(identity)
            satisfaction.update(_votes(idea))
            categories[_category(idea)] += 1
            if anchor is None or (not coordinates(anchor) and coordinates(idea)):
                anchor = idea
            # A newly known anchor or rejected route can invalidate an optimistic
            # quota. Re-reserve future days before spending another slot today.
            cap = min(cap, day_allowance())
        # A meal break is a real empty interval, never an invented restaurant.
        food_near_lunch = any(_category(_stop_idea(stop, facts) or {}) in MEALS and 11 * 60 <= minutes(stop["start_time"]) <= 14 * 60 for stop in days[day])
        if days[day] and not food_near_lunch:
            first_location = next((_stop_idea(item, facts) for item in days[day] if _stop_idea(item, facts)), None)
            arrival = begin
            if prior and first_location and not _same_area(prior, first_location, facts.area_mode):
                transfer, _ = facts.travel(prior, first_location)
                arrival += transfer if transfer is not None else 30
            for lunch in range(12 * 60, 14 * 60 + 1, 15):
                if lunch < max(carry, arrival) or any(lunch < _ending_minute(stop, day, timezone_name) + 15 and lunch + 45 > minutes(stop["start_time"]) - 15 for stop in days[day]):
                    continue
                before_lunch = next((stop for stop in reversed(days[day]) if _ending_minute(stop, day, timezone_name) <= lunch
                                     and _stop_idea(stop, facts)), None)
                after_lunch = next((stop for stop in days[day] if minutes(stop["start_time"]) >= lunch + 45
                                    and _stop_idea(stop, facts)), None)
                if before_lunch and after_lunch:
                    transfer, _ = facts.travel(_stop_idea(before_lunch, facts), _stop_idea(after_lunch, facts))
                    if lunch + 45 + (transfer if transfer is not None else 30) + padding > minutes(after_lunch["start_time"]):
                        continue
                days[day].append({"id": str(uuid5(NAMESPACE_URL, f"trotter:{payload['trip'].get('id', '')}:{day}:lunch")),
                                  "title": "Lunch & a little downtime", "start_time": clock(lunch),
                                  "duration_minutes": 45, "locked": False, "kind": "break", "generated": True})
                break
        days[day].sort(key=lambda item: (item["start_time"], item["id"]))
        # Inserting an earlier stop changes the following leg. Recompute its
        # display facts from the final ordering; never leave a stale duration.
        first_place = next((_stop_idea(item, facts) for item in days[day] if _stop_idea(item, facts)), None)
        previous_place = prior if prior and first_place and not _same_area(prior, first_place, facts.area_mode) else None
        for item in days[day]:
            current_place = _stop_idea(item, facts)
            if not current_place:
                continue
            if not _locked(item):
                item.pop("travel_minutes", None)
                item.pop("travel_source", None)
                if previous_place:
                    travel, source = facts.travel(previous_place, current_place)
                    item["travel_source"] = source
                    if travel is not None:
                        item["travel_minutes"] = travel
            previous_place = current_place
        for stop in days[day]:
            physical = _stop_idea(stop, facts)
            if physical:
                prior, known_prior = physical, _known_location_context(known_prior, physical)
    unplaced = [idea_id for idea_id in facts.ideas if idea_id not in used]
    required = [facts.ideas[key]["title"] for key in unplaced if facts.ideas[key].get("must_do") and _category(facts.ideas[key]) not in STAYS]
    if required:
        warnings.append("These must-dos need more time or different dates: " + ", ".join(required[:5]) + ".")
    if any(_category(facts.ideas[key]) not in STAYS and not (coordinates(facts.ideas[key]) or _text(facts.ideas[key].get("city"))) for key in unplaced):
        warnings.append("Some ideas need a confirmed city or location before they can be scheduled.")
    planned_ideas = [facts.ideas[key] for key in used if key in facts.ideas]
    if any(not isinstance(facts.ideas[item["idea_id"]].get("opening_windows"), dict)
           or day not in facts.ideas[item["idea_id"]]["opening_windows"]
           for day, stops in days.items() for item in stops if item.get("idea_id") in facts.ideas):
        warnings.append("Opening hours are not known for every stop. Confirm them before travelling.")
    if any(stop.get("travel_source") == "estimate" for stops in days.values() for stop in stops):
        warnings.append("Some travel buffers are rough estimates, not verified routes.")
    if any(stop.get("travel_source") == "unknown" for stops in days.values() for stop in stops if stop.get("idea_id")):
        warnings.append("Some transfers are unverified. Check transport before confirming the itinerary.")
    if any(idea.get("hours_source") == "google" for idea in planned_ideas):
        warnings.append("Published opening hours can change; check again closer to your trip.")
    output_days = []
    for day in dates:
        original = next((entry for entry in existing["days"] if entry["date"] == day), {})
        entry = {**deepcopy(original), "date": day, "stops": days[day]}
        if day not in fixed_days:
            entry.pop("planning_note", None)
            if not any(stop.get("idea_id") for stop in days[day]):
                entry["planning_note"] = EMPTY_DAY_NOTE
        output_days.append(entry)
    return {"days": output_days,
            "warnings": list(dict.fromkeys(warnings + facts.warnings))[:30], "unplaced_idea_ids": unplaced,
            "unplaced_reasons": _exclusion_reasons(payload, facts, dates, used, exclusion_evidence)}


def _exclusion_reasons(payload: dict, facts: FactSet, dates: list[str], used: set[str], evidence: dict[str, set[str]]) -> dict:
    """Persist bounded planning decisions, not provider response text or facts."""
    reasons = {}
    identities = {_identity(facts.ideas[key]) for key in used if key in facts.ideas}
    known_planned = [facts.ideas[key] for key in used if key in facts.ideas and coordinates(facts.ideas[key])
                     and _category(facts.ideas[key]) not in STAYS]
    originals = {str(idea["id"]): idea for idea in payload.get("ideas", [])}
    _, begin, end, _ = PACE[payload.get("pace") or payload["trip"].get("pace", "balanced")]
    for key, idea in facts.ideas.items():
        if key in used or _category(idea) in STAYS:
            continue
        code, mode = "no_fit", None
        if idea.get("status") == "processing":
            code = "processing"
        elif not idea.get("title") or not (coordinates(idea) or _text(idea.get("city"))):
            code = "needs_location"
        elif originals.get(key, {}).get("closed"):
            code = "closed"  # Manual supplied flag only; no stored Google business status.
        elif idea.get("score", 0) < 0 and not idea.get("must_do"):
            code = "low_interest"
        elif _identity(idea) is not None and _identity(idea) in identities:
            code = "duplicate"
        elif (isinstance(idea.get("opening_windows"), dict) and all(day in idea["opening_windows"] for day in dates)
              and not any(b - a >= _duration(idea) for day in dates for a, b in _windows(idea, day, begin, end))):
            code = "opening_hours"
        elif "transport_required" in evidence.get(key, set()) and coordinates(idea) and known_planned and len(facts.modes) == 1:
            journeys = [facts.travel(origin, idea)[0] for origin in known_planned]
            if all(value is not None and value > (120 if facts.area_mode == "walk" else 360) for value in journeys):
                code, mode = "transport_required", facts.modes[0]
        elif "travel_unverified" in evidence.get(key, set()):
            code = "travel_unverified"
        reasons[key] = {"code": code, **({"transport_mode": mode} if mode else {})}
    return reasons


def _stay_is_near(stay: dict, anchor: dict, facts: FactSet) -> bool:
    from .planner_geography import geography
    a, city_a = geography(stay.get("country"), stay.get("city"))
    b, city_b = geography(anchor.get("country"), anchor.get("city"))
    if a and b and a != b:
        return False
    distance = distance_km(stay, anchor)
    if distance is not None:
        return distance <= (5 if facts.area_mode == "walk" else 20)
    return False  # A shared city label does not establish a nearby physical stay.


def _suggest_stays(plan: dict, payload: dict, facts: FactSet) -> dict:
    """Recommend only saved accommodation with evidence of a sensible base."""
    result = deepcopy(plan)
    hotels = [idea for idea in facts.ideas.values() if _category(idea) in STAYS and idea.get("title")
              and not idea.get("closed") and (idea.get("score", 0) >= 0 or idea.get("schedule_as_visit"))]
    prior_anchor, prior_stay, location_uncertain = None, None, False
    for index, day in enumerate(result["days"]):
        if payload.get("day") and day["date"] != payload["day"]:
            known = [_stop_idea(stop, facts) for stop in day["stops"] if _stop_idea(stop, facts)]
            if known:
                last = known[-1]
                prior_anchor = last if coordinates(last) or _text(last.get("city")) else None
                location_uncertain = prior_anchor is None
            prior_stay = (day.get("stay") or {}).get("idea_id") or prior_stay
            continue
        current = day.get("stay") or {}
        physical = [_stop_idea(stop, facts) for stop in day["stops"] if _stop_idea(stop, facts)]
        if physical:
            last = physical[-1]
            anchor = last if coordinates(last) or _text(last.get("city")) else None
            location_uncertain = anchor is None
        else:
            anchor = prior_anchor
        activity_anchor = anchor
        if current.get("status") == "selected" and not anchor and not location_uncertain:
            anchor = facts.ideas.get(current.get("idea_id"))
        if anchor is None and not location_uncertain:
            anchor = next((_stop_idea(stop, facts) for later in result["days"][index + 1:] for stop in later["stops"]
                           if _stop_idea(stop, facts) and (coordinates(_stop_idea(stop, facts)) or _text(_stop_idea(stop, facts).get("city")))), None)
        if current.get("status") in {"selected", "not_needed"}:
            prior_stay = current.get("idea_id") or prior_stay
            if current.get("status") == "selected":
                selected = facts.ideas[current["idea_id"]]
                if activity_anchor and distance_km(selected, activity_anchor) is None:
                    reason = "The distance to your selected stay is unknown. Confirm its location and the transfer."
                elif activity_anchor and not _stay_is_near(selected, activity_anchor, facts):
                    reason = "Your selected stay is away from this day's plans. Check the transfer before confirming."
                elif location_uncertain:
                    reason = "The location after your booking is unknown. Check the transfer to your selected stay."
                else:
                    reason = "Your chosen saved accommodation; check availability."
                day["stay"]["reason"] = reason
                if "transfer" in reason:
                    result.setdefault("warnings", []).append(f"{day['date']}: {reason}")
        elif index == len(result["days"]) - 1:
            day["stay"] = {"status": "not_needed"}
        else:
            chosen = next((facts.ideas[stop["idea_id"]] for stop in reversed(day["stops"])
                           if stop.get("idea_id") in facts.ideas and _category(facts.ideas[stop["idea_id"]]) in STAYS), None)
            reasonable = [hotel for hotel in hotels if anchor and _stay_is_near(hotel, anchor, facts)]
            reasonable.sort(key=lambda hotel: (0 if hotel["id"] == prior_stay else 1,
                                               0 if hotel.get("must_do") else 1,
                                               distance_km(hotel, anchor) if distance_km(hotel, anchor) is not None else 100,
                                               -float(hotel.get("score", 0)), hotel["id"]))
            suggestion = chosen or (reasonable[0] if reasonable else None)
            city = _text((anchor or {}).get("city"), 128)
            if suggestion:
                near = distance_km(suggestion, anchor) if anchor else None
                day["stay"] = {"status": "selected" if chosen else "suggested", "idea_id": suggestion["id"],
                               "reason": "Your chosen saved accommodation." if chosen else
                                         "Saved near this day's plans; check availability." if near is not None else
                                         "Saved in this city; confirm its location and availability."}
                prior_stay = suggestion["id"]
            else:
                day["stay"] = {"status": "needed", "reason": "No saved stay has a known location close enough to these plans." if anchor else
                               "Add a saved stay once you choose where to spend the night."}
            if city:
                day["stay"]["city"] = city
        prior_anchor = anchor
    # Stays belong to the plan even though they are not sightseeing stops.
    used = {stop["idea_id"] for day in result["days"] for stop in day["stops"] if stop.get("idea_id")}
    used.update(day["stay"]["idea_id"] for day in result["days"] if (day.get("stay") or {}).get("idea_id"))
    unplaced = [key for key in facts.ideas if key not in used]
    warnings = [warning for warning in result.get("warnings", [])
                if not re.match(r"^\d+ ideas? remain(?:s)? in Ideas;", warning)
                and not warning.startswith("Stay options remain in Ideas.")
                and not warning.startswith("These must-dos need more time or different dates:")]
    required = [facts.ideas[key]["title"] for key in unplaced if facts.ideas[key].get("must_do") and _category(facts.ideas[key]) not in STAYS]
    if required:
        warnings.append("These must-dos need more time or different dates: " + ", ".join(required[:5]) + ".")
    result["unplaced_idea_ids"] = unplaced
    result["warnings"] = list(dict.fromkeys(warnings))[:30]
    return result


def generate_plan(payload: dict, *, use_ai: bool = True) -> dict:
    """Generate an uncommitted draft, with a deterministic fallback and usage."""
    if not isinstance(payload, dict):
        raise ValueError("The trip details could not be read.")
    payload = deepcopy(payload)
    dates = trip_dates(payload.get("trip") or {})
    if payload.get("day") and payload["day"] not in dates:
        raise ValueError("Choose a day within the trip dates.")
    if payload.get("pace") and payload["pace"] not in PACE:
        raise ValueError("Choose a valid pace for this day.")
    payload["ideas"] = _normalize_ideas(payload.get("ideas", []))
    if payload.get("existing_plan"):
        payload["existing_plan"] = validate_plan(payload["existing_plan"], payload)
        explicitly_placed = {str(stop["idea_id"]) for day in payload["existing_plan"]["days"]
                             for stop in day["stops"] if stop.get("idea_id")}
        existing_details = {str(stop["idea_id"]): stop for day in payload["existing_plan"]["days"]
                            for stop in day["stops"] if stop.get("idea_id")}
        for idea in payload["ideas"]:
            if idea["id"] in existing_details:
                idea["_requested_duration_minutes"] = existing_details[idea["id"]]["duration_minutes"]
            if idea["id"] in explicitly_placed and _category(idea) in STAYS:
                idea["schedule_as_visit"] = True
                idea["must_do"] = True
    facts = collect_facts(payload, dates)
    available = [idea for idea in facts.ideas.values() if _available(idea)]
    target_dates = [payload["day"]] if payload.get("day") else dates
    occupied = {str(stop["idea_id"]) for day in (payload.get("existing_plan") or {}).get("days", [])
                for stop in day["stops"] if stop.get("idea_id") and (_locked(stop) or day["date"] not in target_dates)}
    proposal, source = None, "rules"
    usage: dict[str, Any] = {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0}
    if use_ai and any(idea["id"] not in occupied for idea in available):
        try:
            proposal, usage = planner_ai.compose(_brief(payload, facts, target_dates, available, occupied))
            source = "ai"
        except planner_ai.PlannerAIError as exc:
            usage = exc.usage
            facts.warnings.append(str(exc))
    facts.route_deadline = time.monotonic() + bounded_int("PLANNER_ROUTE_TIMEOUT_SECONDS", 20, 1, 45)
    plan = _schedule(payload, facts, dates, proposal)
    if proposal and not any(stop.get("idea_id") not in occupied for day in plan["days"] for stop in day["stops"] if stop.get("idea_id")):
        facts.warnings.append("The proposed selection could not fit safely. A schedule was created from your saves.")
        plan, source = _schedule(payload, facts, dates, None), "rules"
    plan = _suggest_stays(plan, payload, facts)
    plan = _refresh_travel(plan, facts, only_day=payload.get("day"))
    plan = validate_plan(plan, payload, preserve_locked=True)
    return {"plan": plan, "source": source, "usage": usage}
