"""Bounded source-only research, followed by independent Google verification."""
from __future__ import annotations

import asyncio
from dataclasses import asdict

from .dream_location_research import plan_location_queries, source_area_intent

INITIAL_SECONDS = 30
RESEARCH_SECONDS = 15
RETRY_SECONDS = 12
TOTAL_SECONDS = 75
MAX_REVISED_SEARCHES = 2


def area_search_name(place_name, city, region, category, source_caption):
    if place_name and source_area_intent(place_name=place_name, city=city, region_or_neighborhood=region,
                          category=category, source_caption=source_caption):
        return place_name
    if not place_name:
        for value in (city, region):
            if value and source_area_intent(place_name=None, city=value, category=category, source_caption=source_caption):
                return value
    return None


def _payload(result):
    return result.model_dump() if hasattr(result, "model_dump") else result


async def lookup_dream_location(place_name, city, country, region, category, *, source_caption=None,
                                protected=False, searcher=None, planner=None):
    """At most one AI request and two revised searches; never invent a pin.

    Google responses remain local to the matcher. The planner receives only
    original source fields. Its evidence-validated proposals are checked by
    Google just like the first search; an ambiguous result stays unresolved.
    """
    from .google_dream_place_search import search_google_dream_place
    searcher, planner = searcher or search_google_dream_place, planner or plan_location_queries
    area_name = area_search_name(place_name, city, region, category, source_caption)
    fields = dict(place_name=place_name, city=city, country=country,
                  region_or_neighborhood=region, category=category)
    async with asyncio.timeout(TOTAL_SECONDS):
        async with asyncio.timeout(INITIAL_SECONDS):
            result = _payload(await searcher(area_name or place_name, city, country, region, category,
                                            source_caption=source_caption, allow_area=bool(area_name)))
        if result.get("status") != "not_found" or protected or not source_caption:
            return result
        try:
            async with asyncio.timeout(RESEARCH_SECONDS):
                plans = await planner(**fields, source_caption=source_caption, protected=protected)
        except Exception:
            # Optional query planning cannot break ordinary Google lookup.
            return result
        attempts = []
        initial = (area_name or place_name, city, country, region, category, bool(area_name))
        seen = {initial}
        for plan in plans[:MAX_REVISED_SEARCHES]:
            inputs = (plan.place_name, plan.city, plan.country, plan.region, plan.category, plan.allow_area)
            if inputs in seen:
                continue
            seen.add(inputs)
            attempts.append(asdict(plan))
            async with asyncio.timeout(RETRY_SECONDS):
                revised = _payload(await searcher(*inputs[:5], source_caption=source_caption, allow_area=inputs[5]))
            if revised.get("status") == "resolved":
                return {**revised, "_research": {"queries": attempts, "matched": asdict(plan)}}
            if revised.get("status") != "not_found":
                return revised
        return {**result, "_research": {"queries": attempts, "matched": None}} if attempts else result
