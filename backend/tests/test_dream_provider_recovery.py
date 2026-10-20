"""Provider outages recover after the fast budget; missing source data does not loop."""
import asyncio
from datetime import timedelta

import httpx
import pytest

from app.models import DreamEnrichmentJob, DreamItem, DreamLocation
from app.services import dream_parser
from app.services.dream_enrichment import (
    EnrichmentUnavailable, LEASE_SECONDS, cancel_enrichment, claim_enrichment,
    enrichment_recovery, read_source, resolve_enrichment_job,
)
from app.services.dream_locations import claim_job, due_jobs, location_recovery, resolve_location_job
from app.services.google_dream_place_search import GooglePlacesUnavailableError
from app.tasks.dream_enrichment_tasks import dispatch_pending_enrichment
from test_dream_enrichment import NOW, enqueue, result, run
from test_dream_locations import CANDIDATE, add_item, enqueue as enqueue_location, sessions


def unavailable(_):
    raise EnrichmentUnavailable("Garden Cafe in Madrid, Spain", {"caption": "public", "error": "secret"},
                                provider_reason="billing")


def test_sorting_outage_probes_automatically_with_capped_cooldown_and_no_new_fast_burst(sessions, monkeypatch):
    monkeypatch.setenv("DREAM_ENRICHMENT_MAX_ATTEMPTS", "2")
    add_item(sessions)
    job_id, _ = enqueue(sessions)
    assert run(sessions, job_id, unavailable) == "queued"
    exhausted = NOW + timedelta(seconds=31)
    assert run(sessions, job_id, unavailable, exhausted) == "queued"
    with sessions() as db:
        item = db.get(DreamItem, 1)
        recovery = enrichment_recovery(item)
        assert recovery["state"] == "waiting" and recovery["cycle"] == 1
        assert item.enrichment.attempts == 2
        assert item.summary == "Keep my notes" and item.tags_json == ["favorite"]
        assert "secret" not in str(item.raw_metadata_json)
    dispatched = []
    dispatch_pending_enrichment(session_factory=sessions, publish=dispatched.append,
                                now=exhausted + timedelta(minutes=14))
    assert dispatched == []
    probe = exhausted + timedelta(minutes=15)
    dispatch_pending_enrichment(session_factory=sessions, publish=dispatched.append, now=probe)
    assert dispatched == [job_id]
    assert run(sessions, job_id, unavailable, probe) == "queued"
    with sessions() as db:
        item = db.get(DreamItem, 1)
        assert enrichment_recovery(item)["cycle"] == 2
        assert item.enrichment.attempts == 3  # One probe, not a reset to zero.
        assert item.enrichment.next_attempt_at == (probe + timedelta(hours=1)).replace(tzinfo=None)
    probe += timedelta(hours=1)
    assert run(sessions, job_id, unavailable, probe) == "queued"
    with sessions() as db:
        item = db.get(DreamItem, 1)
        assert enrichment_recovery(item)["cycle"] == 3
        assert item.enrichment.next_attempt_at == (probe + timedelta(hours=6)).replace(tzinfo=None)
    probe += timedelta(hours=6)
    assert run(sessions, job_id, unavailable, probe) == "queued"
    with sessions() as db:
        assert enrichment_recovery(db.get(DreamItem, 1))["cycle"] == 3
    assert run(sessions, job_id, now=probe + timedelta(hours=6)) == "completed"
    with sessions() as db:
        item = db.get(DreamItem, 1)
        assert enrichment_recovery(item) is None
        assert "dream_enrichment_recovery" not in item.raw_metadata_json
        assert item.summary == "Keep my notes" and item.tags_json == ["favorite"]
        assert item.enrichment.attempts == 6
        assert db.query(DreamItem).count() == 1


@pytest.mark.parametrize("change", ["edit", "new_generation", "delete", "crash"])
def test_deferred_sorting_still_protects_user_changes_and_bounds_worker_crashes(sessions, monkeypatch, change):
    monkeypatch.setenv("DREAM_ENRICHMENT_MAX_ATTEMPTS", "1")
    add_item(sessions)
    job_id, _ = enqueue(sessions)
    assert run(sessions, job_id, unavailable) == "queued"
    with sessions() as db:
        item = db.get(DreamItem, 1)
        if change == "edit":
            item.summary = "Edited during outage"
            cancel_enrichment(db, item, user_edited=True)
        elif change == "new_generation":
            item.caption = "New caption"
            from app.services.dream_enrichment import enqueue_enrichment
            enqueue_enrichment(db, item, force=True, now=NOW)
        elif change == "delete":
            db.delete(item)
        else:
            assert claim_enrichment(db, job_id, now=NOW + timedelta(minutes=15))
        db.commit()
        if change == "crash":
            expired = NOW + timedelta(minutes=15, seconds=LEASE_SECONDS + 1)
            assert claim_enrichment(db, job_id, now=expired) is None
            db.commit()
            item = db.get(DreamItem, 1)
            assert enrichment_recovery(item)["lost_leases"] == 1
            assert item.enrichment.status == "queued"
            assert run(sessions, job_id, now=expired + timedelta(hours=1)) == "completed"
        elif change != "delete":
            assert enrichment_recovery(item) is None
            assert "dream_enrichment_recovery" not in item.raw_metadata_json
        else:
            assert db.get(DreamEnrichmentJob, job_id) is None


@pytest.mark.parametrize("error,reason", [
    (dream_parser.DreamParserUnavailableError("Provider billing secret", "billing"), "billing"),
    (dream_parser.DreamParserError("Malformed model output secret"), None),
    (dream_parser.DreamParserConfigurationError("Invalid output schema secret"), None),
])
def test_source_reader_preserves_caption_and_classifies_only_verified_availability(monkeypatch, error, reason):
    from app.routers import dreams
    monkeypatch.setattr(dreams, "resolve_caption_for_parse", lambda *_: ("Garden Cafe in Spain", {"caption": "public"}))
    def failed(*_):
        raise error
    monkeypatch.setattr(dreams, "parse_caption_with_fallback_model", failed)
    with pytest.raises(EnrichmentUnavailable) as caught:
        read_source({"caption": None, "shared_text": None, "source_url": "https://instagram.com/reel/one", "item_id": 1})
    assert caught.value.provider_reason == reason
    assert caught.value.caption == "Garden Cafe in Spain"
    assert "secret" not in str(caught.value)


@pytest.mark.parametrize("status,reason", [(401, "configuration"), (402, "billing"), (403, "configuration"),
                                          (429, "rate_limited"), (503, "provider"), (400, None), (422, None)])
def test_parser_uses_typed_provider_availability_without_response_content(monkeypatch, status, reason):
    monkeypatch.setattr(httpx, "post", lambda url, **_: httpx.Response(status, text="provider-secret", request=httpx.Request("POST", url)))
    with pytest.raises(dream_parser.DreamParserError) as caught:
        dream_parser._venice_chat({}, base_url="https://example.invalid", api_key="secret-key", timeout=1, max_attempts=1)
    assert isinstance(caught.value, dream_parser.DreamParserUnavailableError) is bool(reason)
    assert getattr(caught.value, "reason", None) == reason
    assert "secret" not in str(caught.value)


def test_location_research_outage_recovers_after_fast_attempts_without_rewriting_save(sessions, monkeypatch):
    monkeypatch.setenv("DREAM_LOCATION_MAX_ATTEMPTS", "2")
    add_item(sessions)
    job_id, _ = enqueue_location(sessions)
    async def failed(*_):
        return {"status": "not_found", "provider": "google_places", "candidates": [],
                "_research": {"outcome": "unavailable", "queries": [], "matched": None, "failure_kind": "billing"}}
    def attempt(now, resolver=failed):
        return asyncio.run(resolve_location_job(job_id, session_factory=sessions, resolver=resolver, now=now))
    assert attempt(NOW) == "queued"
    exhausted = NOW + timedelta(seconds=61)
    assert attempt(exhausted) == "blocked"
    with sessions() as db:
        item = db.get(DreamItem, 1)
        assert item.summary == "Keep my notes" and item.place_name == "Garden Cafe"
        assert item.raw_metadata_json == {"source": {"untouched": True}}
        recovery = location_recovery(item.location)
        assert recovery["reason"] == "billing" and recovery["cycle"] == 1
        assert due_jobs(db, now=exhausted + timedelta(minutes=14)) == []
        assert [row.id for row in due_jobs(db, now=exhausted + timedelta(minutes=15))] == [job_id]
    probe = exhausted + timedelta(minutes=15)
    assert attempt(probe) == "blocked"
    with sessions() as db:
        row = db.get(DreamLocation, job_id)
        assert row.attempts == 3 and location_recovery(row)["cycle"] == 2
        assert len([entry for entry in row.history if entry.get("reason") == "provider_recovery"]) == 1
    async def found(*_):
        return {"status": "resolved", "provider": "geoapify", "candidates": [dict(CANDIDATE)]}
    assert attempt(probe + timedelta(hours=1), found) == "resolved"
    with sessions() as db:
        row = db.get(DreamLocation, job_id)
        assert location_recovery(row) is None
        assert row.next_attempt_at is None
        assert db.query(DreamItem).count() == 1


def test_google_outage_is_not_confused_with_bad_response_or_forever_retried_worker_crash(sessions, monkeypatch):
    monkeypatch.setenv("DREAM_LOCATION_MAX_ATTEMPTS", "1")
    add_item(sessions)
    job_id, _ = enqueue_location(sessions)
    async def offline(*_):
        raise GooglePlacesUnavailableError("network")
    assert asyncio.run(resolve_location_job(job_id, session_factory=sessions, resolver=offline, now=NOW)) == "blocked"
    with sessions() as db:
        assert claim_job(db, job_id, now=NOW + timedelta(minutes=15))
        db.commit()
        assert claim_job(db, job_id, now=NOW + timedelta(minutes=18)) is None
        db.commit()
        row = db.get(DreamLocation, job_id)
        assert row.status == "blocked" and location_recovery(row)["lost_leases"] == 1
        # More restarts are bounded instead of preserving a broken worker loop.
        for index in range(3):
            due = row.next_attempt_at.replace(tzinfo=NOW.tzinfo)
            assert claim_job(db, job_id, now=due)
            db.commit()
            assert claim_job(db, job_id, now=due + timedelta(minutes=3)) is None
            db.commit()
            db.refresh(row)
        assert row.status == "failed" and location_recovery(row) is None


def test_repeated_deferred_sorting_worker_loss_still_terminates(sessions, monkeypatch):
    monkeypatch.setenv("DREAM_ENRICHMENT_MAX_ATTEMPTS", "1")
    add_item(sessions)
    job_id, _ = enqueue(sessions)
    assert run(sessions, job_id, unavailable) == "queued"
    with sessions() as db:
        row = db.get(DreamEnrichmentJob, job_id)
        for _ in range(4):
            due = row.next_attempt_at.replace(tzinfo=NOW.tzinfo)
            assert claim_enrichment(db, job_id, now=due)
            db.commit()
            assert claim_enrichment(db, job_id, now=due + timedelta(seconds=LEASE_SECONDS + 1)) is None
            db.commit()
            db.refresh(row)
        assert row.status == "failed" and enrichment_recovery(db.get(DreamItem, 1)) is None


def test_bad_location_response_still_stops_at_fast_attempt_budget(sessions, monkeypatch):
    from app.services.dream_place_search import RetryableDreamPlaceLookupError
    monkeypatch.setenv("DREAM_LOCATION_MAX_ATTEMPTS", "1")
    add_item(sessions)
    job_id, _ = enqueue_location(sessions)
    async def malformed(*_):
        raise RetryableDreamPlaceLookupError("invalid response")
    assert asyncio.run(resolve_location_job(job_id, session_factory=sessions, resolver=malformed, now=NOW)) == "failed"
    with sessions() as db:
        row = db.get(DreamLocation, job_id)
        assert location_recovery(row) is None and row.next_attempt_at is None


@pytest.mark.parametrize("error", [dream_parser.DreamParserUnavailableError("temporarily unavailable", "billing"),
                                  dream_parser.DreamParserTruncatedError("length")])
def test_incomplete_completeness_check_does_not_silently_finish_partial_source(monkeypatch, error):
    from test_dream_parser import MULTI_CAPTION, multi_result
    partial = multi_result()
    calls = []
    def failure(*args, **kwargs):
        calls.append(1)
        raise error
    monkeypatch.setattr(dream_parser, "_request_missing_places", failure)
    with pytest.raises(type(error)):
        dream_parser.complete_missing_places(partial, MULTI_CAPTION, provider="venice", model="test")
    assert calls == [1] and len(partial.items) == 4


def test_completeness_outage_preserves_existing_pin_then_finishes_missing_places(sessions, monkeypatch):
    from app.routers import dreams
    from app.services.dream_enrichment import enqueue_enrichment
    from app.services.dream_parser import DreamParseItem, DreamParseResponse
    from test_dream_parser import MULTI_CAPTION, multi_result
    monkeypatch.setenv("DREAM_ENRICHMENT_MAX_ATTEMPTS", "1")
    add_item(sessions, caption=MULTI_CAPTION, place_name="Dolphin Rock", city="Ta Xua", country="Vietnam", category="attraction",
             google_maps_url=dreams.build_google_maps_search_url("Dolphin Rock", "Ta Xua", "Vietnam"))
    location_id, _ = enqueue_location(sessions)
    async def known(*_):
        return {"status": "resolved", "provider": "geoapify", "candidates": [dict(CANDIDATE)]}
    assert asyncio.run(resolve_location_job(location_id, session_factory=sessions, resolver=known, now=NOW)) == "resolved"
    with sessions() as db:
        item = db.get(DreamItem, 1)
        row, _ = enqueue_enrichment(db, item, force=True, now=NOW)
        job_id = row.id
        db.commit()
    monkeypatch.setattr(dreams, "resolve_caption_for_parse", lambda *_: (MULTI_CAPTION, {}))
    monkeypatch.setattr(dream_parser, "parse_caption", lambda *args, **kwargs: multi_result())
    def offline(*args, **kwargs):
        raise dream_parser.DreamParserUnavailableError("out of credits", "billing")
    monkeypatch.setattr(dream_parser, "_request_missing_places", offline)
    assert resolve_enrichment_job(job_id, session_factory=sessions, now=NOW) == "queued"
    with sessions() as db:
        item = db.get(DreamItem, 1)
        assert item.place_name == "Dolphin Rock" and item.summary == "Keep my notes"
        assert item.location.status == "resolved" and item.location.latitude == CANDIDATE["latitude"]
        assert db.query(DreamItem).count() == 1
        assert enrichment_recovery(item)["state"] == "waiting"
    from test_dream_parser import completion_item
    monkeypatch.setattr(dream_parser, "_request_missing_places", lambda *args, **kwargs: {"items": [completion_item()]})
    assert resolve_enrichment_job(job_id, session_factory=sessions, now=NOW + timedelta(minutes=15)) == "completed"
    with sessions() as db:
        item = db.get(DreamItem, 1)
        assert item.place_name == "Dolphin Rock" and item.location.status == "resolved"
        assert db.query(DreamItem).count() == 5
        assert enrichment_recovery(item) is None


def test_recovery_helper_ignores_superseded_source_generation(sessions, monkeypatch):
    monkeypatch.setenv("DREAM_ENRICHMENT_MAX_ATTEMPTS", "1")
    add_item(sessions)
    job_id, _ = enqueue(sessions)
    assert run(sessions, job_id, unavailable) == "queued"
    with sessions() as db:
        item = db.get(DreamItem, 1)
        assert enrichment_recovery(item)
        item.source_post.generation += 1
        assert enrichment_recovery(item) is None


def test_explicit_retry_can_resume_waiting_recovery_without_duplicate_share_restarting_it(sessions, monkeypatch):
    monkeypatch.setenv("DREAM_ENRICHMENT_MAX_ATTEMPTS", "1")
    add_item(sessions)
    job_id, _ = enqueue(sessions)
    assert run(sessions, job_id, unavailable) == "queued"
    assert enqueue(sessions) == (job_id, False)
    assert enqueue(sessions, force=True) == (job_id, True)
    with sessions() as db:
        item = db.get(DreamItem, 1)
        assert item.enrichment.generation == 2 and item.enrichment.attempts == 0
        assert enrichment_recovery(item) is None
        assert "dream_enrichment_recovery" not in item.raw_metadata_json
    assert run(sessions, job_id) == "completed"


@pytest.mark.parametrize("status,reason", [(400, None), (404, None), (422, None),
    (401, "configuration"), (402, "billing"), (403, "configuration"), (408, "provider"),
    (429, "rate_limited"), (503, "provider")])
def test_query_planning_only_verified_availability_defers_not_invalid_requests(monkeypatch, status, reason):
    from app.services.dream_location_research import LocationResearchUnavailable
    from test_dream_location_research import plan, provider
    calls, _ = provider(monkeypatch, status=status, body={"error": "private provider details"})
    if reason:
        with pytest.raises(LocationResearchUnavailable) as caught:
            plan()
        assert caught.value.reason == reason and "private" not in str(caught.value)
    else:
        assert plan() == []
    assert len(calls) == 1


@pytest.mark.parametrize("error,availability", [
    (httpx.InvalidURL("bad-url-secret"), False),
    (httpx.UnsupportedProtocol("invalid-scheme-secret"), False),
    (httpx.LocalProtocolError("invalid-header-secret"), False),
    (httpx.HTTPError("unclassified-error-secret"), False),
    (httpx.ConnectError("network-secret"), True),
    (httpx.ReadTimeout("timeout-secret"), True),
    (httpx.RemoteProtocolError("remote-secret"), True),
])
def test_query_planning_does_not_retry_invalid_urls_or_local_configuration_as_network(monkeypatch, error, availability):
    from app.services.dream_location_research import LocationResearchUnavailable
    from test_dream_location_research import plan, provider
    calls, _ = provider(monkeypatch, error=error)
    if availability:
        with pytest.raises(LocationResearchUnavailable) as caught:
            plan()
        assert caught.value.reason == "timeout_or_network"
        assert "secret" not in str(caught.value)
    else:
        assert plan() == []
    assert len(calls) == 1
