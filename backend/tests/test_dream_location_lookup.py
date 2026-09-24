"""Budget, verification and edit-safety tests; no external requests."""
import asyncio
from dataclasses import asdict

import pytest

from app.services import dream_location_lookup as lookup
from app.services.dream_location_research import LocationQueryProposal
from app.services.dream_locations import resolve_location_job, queue_missing, location_coordinates, enqueue_location
from app.models import DreamItem
from test_dream_locations import sessions, add_item, enqueue, NOW
from test_google_location_lifecycle import isolated_cache, CANDIDATE

NOT_FOUND = {"status": "not_found", "provider": "google_places", "candidates": []}
FOUND = {"status": "resolved", "provider": "google_places", "candidates": [CANDIDATE]}


def proposal(**changes):
    return LocationQueryProposal(**{**dict(place_name="Garden Cafe", city=None, country="Spain",
        region_or_neighborhood=None, category="cafe", intent="place",
        evidence={"city": {"source": "removed", "quote": None}}, dropped_fields=("city",)), **changes})


def run(searcher, planner, **kwargs):
    return asyncio.run(lookup.lookup_dream_location("Garden Cafe", "Madrid", "Spain", None, "cafe",
        source_caption="Garden Cafe, Spain", searcher=searcher, planner=planner, **kwargs))


@pytest.mark.parametrize("status,protected", [("resolved", False), ("blocked", False), ("not_found", True)])
def test_success_blocked_and_protected_saves_do_not_call_ai(status, protected):
    async def search(*args, **kwargs):
        return {**NOT_FOUND, "status": status}
    async def forbidden(**kwargs):
        pytest.fail("AI must not run")
    assert run(search, forbidden, protected=protected)["status"] == status


def test_source_only_plan_is_verified_and_only_its_successful_query_is_returned():
    calls = []
    async def search(*args, **kwargs):
        calls.append((args, kwargs))
        return NOT_FOUND if len(calls) == 1 else FOUND
    async def planner(**kwargs):
        assert set(kwargs) == {"place_name", "city", "country", "region_or_neighborhood", "category", "source_caption", "protected"}
        assert "Provider-only" not in repr(kwargs)
        return [proposal()]
    result = run(search, planner)
    assert result["status"] == "resolved"
    assert calls[1][0] == ("Garden Cafe", None, "Spain", None, "cafe")
    assert result["_research"]["matched"]["dropped_fields"] == ("city",)


def test_at_most_two_revised_google_searches_even_if_planner_returns_more():
    calls = []
    async def search(*args, **kwargs):
        calls.append(args)
        return NOT_FOUND
    async def planner(**kwargs):
        return [proposal(city=f"test {index}") for index in range(8)]
    result = run(search, planner)
    assert len(calls) == 3 and result["status"] == "not_found"
    assert len(result["_research"]["queries"]) == 2


@pytest.mark.parametrize("failure", [ValueError("bad model output"), TimeoutError()])
def test_optional_ai_failure_preserves_normal_not_found(failure):
    async def search(*args, **kwargs):
        return NOT_FOUND
    async def planner(**kwargs):
        raise failure
    result = run(search, planner)
    assert {key: result[key] for key in NOT_FOUND} == NOT_FOUND
    assert result["_research"]["outcome"] == "unavailable"


def test_initial_area_mode_keeps_named_lake_from_becoming_exact_venue():
    async def search(*args, **kwargs):
        assert args[:3] == ("Lake Atitlan", None, "Guatemala") and kwargs["allow_area"] is True
        return FOUND
    result = asyncio.run(lookup.lookup_dream_location("Lake Atitlan", "San Marcos", "Guatemala", None, "nature",
                         source_caption="Explore Lake Atitlan, Guatemala, from San Marcos", searcher=search))
    assert result["status"] == "resolved"


def test_blank_name_uses_supported_region_instead_of_unrelated_saved_city():
    assert lookup.area_search_name(None, "Sa Pa", "Ta Xua", "unknown", "Explore Ta Xua, a mountain region.") == "Ta Xua"


def test_area_keeps_concrete_region_but_not_cardinal_country_as_parent_locality():
    assert lookup.area_region_constraint("Northern Vietnam", "Vietnam") is None
    assert lookup.area_region_constraint("Son La", "Vietnam") == "Son La"
    assert lookup.area_region_constraint("Northern Ireland", "United Kingdom") == "Northern Ireland"
    assert lookup.area_region_constraint("Central Java", "Indonesia") == "Central Java"


def test_new_caption_evidence_restarts_unresolved_area_lookup(sessions):
    add_item(sessions, place_name=None, city="Tropea", country="Italy", category="unknown", caption="Some old text")
    enqueue(sessions)
    with sessions() as db:
        item = db.get(DreamItem, 1)
        assert item.location.status == "not_found"
        item.caption = "Explore Tropea, Italy."
        row, queued = enqueue_location(db, item, now=NOW)
        assert queued and row.status == "queued" and row.generation == 2
        assert enqueue_location(db, item, now=NOW)[1] is False


def test_google_timeout_remains_retryable_and_cancels_inflight_work(monkeypatch):
    monkeypatch.setattr(lookup, "INITIAL_SECONDS", 0.01)
    cancelled = []
    async def search(*args, **kwargs):
        try:
            await asyncio.sleep(2)
        finally:
            cancelled.append(True)
    with pytest.raises(TimeoutError):
        run(search, None)
    assert cancelled == [True]


def test_discovery_enqueues_source_backed_nameless_area_but_not_unnamed_hotel(sessions):
    add_item(sessions, place_name=None, city="Tropea", country="Italy", category="unknown", caption="Explore Tropea, Italy.")
    add_item(sessions, item_id=2, place_name=None, city="Tropea", country="Italy", category="hotel", caption="An unnamed hotel in Tropea.")
    with sessions() as db:
        result = queue_missing(db, user_id=1, only_undiscovered=True, now=NOW)
        db.commit()
        assert result["queued"] == 1 and result["checked"] == 1
        assert db.get(DreamItem, 1).location.status == "queued"
        assert db.get(DreamItem, 2).location is None


def test_success_corrects_only_derived_context_and_preserves_original_save(sessions, isolated_cache, monkeypatch):
    add_item(sessions, caption="Garden Cafe, Spain")
    job, _ = enqueue(sessions)
    async def researched(*args, **kwargs):
        assert kwargs["protected"] is False
        return {**FOUND, "_research": {"queries": [asdict(proposal())], "matched": asdict(proposal())}}
    monkeypatch.setattr(lookup, "lookup_dream_location", researched)
    assert asyncio.run(resolve_location_job(job, session_factory=sessions, now=NOW)) == "resolved"
    with sessions() as db:
        item = db.get(DreamItem, 1)
        assert item.city is None and item.country == "Spain" and item.place_name == "Garden Cafe"
        assert item.caption == "Garden Cafe, Spain" and item.summary == "Keep my notes"
        assert item.source_url == "https://example.invalid/save/1" and item.tags_json == ["favorite"]
        assert item.raw_metadata_json["dream_location_repairs"][0]["changes"]["city"]["before"] == "Madrid"
        assert location_coordinates(item) == (40.4, -3.7, "place")


def test_user_edit_protection_added_during_research_supersedes_match(sessions, isolated_cache, monkeypatch):
    add_item(sessions, caption="Garden Cafe, Spain")
    job, _ = enqueue(sessions)
    async def researched(*args, **kwargs):
        with sessions() as db:
            item = db.get(DreamItem, 1)
            item.raw_metadata_json = {**item.raw_metadata_json, "dream_user_edited": True}
            db.commit()
        return {**FOUND, "_research": {"queries": [asdict(proposal())], "matched": asdict(proposal())}}
    monkeypatch.setattr(lookup, "lookup_dream_location", researched)
    assert asyncio.run(resolve_location_job(job, session_factory=sessions, now=NOW)) == "superseded"
    with sessions() as db:
        item = db.get(DreamItem, 1)
        assert item.city == "Madrid" and item.location.status == "queued"
        assert location_coordinates(item) == (None, None, None)
