"""Synthetic durability tests. No external providers, accounts, or live databases."""
import asyncio
import copy
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, Dream, DreamItem, DreamLocation, User
from app.services.dream_locations import (
    claim_job, confirm_candidate, due_jobs, enqueue_location, fingerprint,
    location_coordinates, location_maps_url, public_location, queue_missing, resolve_location_job,
)
from app.tasks.dream_location_tasks import dispatch_pending_locations

NOW = datetime(2026, 9, 14, 12, tzinfo=timezone.utc)
CANDIDATE = {"id": "place-a", "name": "Garden Cafe", "address": "12 Garden Road, Madrid, Spain",
             "latitude": 40.4, "longitude": -3.7, "google_maps_url": "https://example.invalid/untrusted",
             "provider": "geoapify", "score": 1.0}


@pytest.fixture
def sessions(monkeypatch):
    monkeypatch.setenv("GEOAPIFY_API_KEY", "")
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False)
    with factory() as db:
        db.add_all([User(id=1, email="owner@example.invalid"), User(id=2, email="other@example.invalid")])
        db.add_all([Dream(id=1, user_id=1, title="Spain"), Dream(id=2, user_id=2, title="Private")])
        db.commit()
    yield factory
    engine.dispose()


def add_item(sessions, *, item_id=1, user_id=1, **overrides):
    fields = dict(id=item_id, user_id=user_id, dream_id=user_id,
                  source_url=f"https://example.invalid/save/{item_id}", caption="Keep the original caption",
                  place_name="Garden Cafe", city="Madrid", country="Spain", category="cafe",
                  summary="Keep my notes", tags_json=["favorite"], needs_google_places_lookup=False,
                  raw_metadata_json={"source": {"untouched": True}})
    fields.update(overrides)
    with sessions() as db:
        db.add(DreamItem(**fields))
        db.commit()


def enqueue(sessions, item_id=1, **kwargs):
    with sessions() as db:
        row, added = enqueue_location(db, db.get(DreamItem, item_id), now=NOW, **kwargs)
        db.commit()
        return row.id, added


def snapshot(sessions):
    with sessions() as db:
        return {table: db.connection().exec_driver_sql(f'SELECT * FROM "{table}" ORDER BY id').all()
                for table in ("dream_items", "dreams", "users")}


def run_job(sessions, job_id, status="resolved", candidates=None, now=NOW, callback=None):
    async def resolver(*inputs):
        assert inputs == ("Garden Cafe", "Madrid", "Spain", None, "cafe")
        if callback:
            callback()
        return {"status": status, "candidates": copy.deepcopy(candidates if candidates is not None else [CANDIDATE])}
    return asyncio.run(resolve_location_job(job_id, session_factory=sessions, resolver=resolver, now=now))


def test_lookup_and_duplicate_delivery_preserve_all_original_rows(sessions):
    add_item(sessions)
    before = snapshot(sessions)
    job_id, added = enqueue(sessions)
    assert added and enqueue(sessions) == (job_id, False)
    assert run_job(sessions, job_id) == "resolved"
    assert run_job(sessions, job_id) == "skipped"
    assert snapshot(sessions) == before
    with sessions() as db:
        item = db.get(DreamItem, 1)
        assert location_coordinates(item) == (40.4, -3.7, "place")
        assert location_maps_url(item) == "https://www.google.com/maps/search/?api=1&query=40.4,-3.7"
        assert public_location(item)["location_address"].startswith("12 Garden")
        assert db.query(DreamLocation).count() == 1


def test_backfill_covers_false_legacy_flag_and_preserves_manual_and_unnamed_saves(sessions):
    add_item(sessions)
    add_item(sessions, item_id=2, google_maps_url="https://maps.google.com/?q=48.85,2.35")
    add_item(sessions, item_id=3, place_name=None)
    add_item(sessions, item_id=4, user_id=2)
    before = snapshot(sessions)
    with sessions() as db:
        result = queue_missing(db, user_id=1, only_undiscovered=True)
        db.commit()
        assert result["queued"] == 1 and result["checked"] == 2
        assert db.query(DreamLocation).count() == 2
        assert db.get(DreamItem, 2).location.status == "manual"
        assert db.get(DreamItem, 3).location is None
        assert db.get(DreamItem, 4).location is None
        assert queue_missing(db, user_id=1, only_undiscovered=True)["checked"] == 0
    assert snapshot(sessions) == before


def test_discovery_advances_in_bounded_batches_and_lost_publish_recovers(sessions):
    for item_id in range(1, 4):
        add_item(sessions, item_id=item_id)
    with sessions() as db:
        assert queue_missing(db, limit=2, only_undiscovered=True, now=NOW)["queued"] == 2
        db.commit()
        assert queue_missing(db, limit=2, only_undiscovered=True, now=NOW)["queued"] == 1
        db.commit()
    def unavailable(_):
        raise RuntimeError("redacted broker failure")
    assert dispatch_pending_locations(session_factory=sessions, publish=unavailable, now=NOW)["dispatched"] == 0
    sent = []
    assert dispatch_pending_locations(session_factory=sessions, publish=sent.append, now=NOW + timedelta(seconds=61))["dispatched"] == 3
    assert len(set(sent)) == 3


def test_duplicate_claim_and_abandoned_lease_recovery(sessions):
    add_item(sessions)
    job_id, _ = enqueue(sessions)
    with sessions() as db:
        first = claim_job(db, job_id, now=NOW)
        db.commit()
        assert first
        assert claim_job(db, job_id, now=NOW + timedelta(seconds=1)) is None
        second = claim_job(db, job_id, now=NOW + timedelta(seconds=121))
        db.commit()
        assert second["token"] != first["token"]
        assert db.get(DreamLocation, job_id).attempts == 2


@pytest.mark.parametrize("change", ["identity", "manual_pin", "deletion", "replacement_lease"])
def test_inflight_result_cannot_overwrite_newer_user_state(sessions, change):
    add_item(sessions)
    job_id, _ = enqueue(sessions)
    def edit():
        with sessions() as db:
            item = db.get(DreamItem, 1)
            if change == "identity":
                item.place_name = "Different Museum"
                enqueue_location(db, item, now=NOW)
            elif change == "manual_pin":
                item.google_maps_url = "https://maps.google.com/?query=1.3,103.8"
                enqueue_location(db, item, now=NOW)
            elif change == "deletion":
                db.delete(item)
            else:
                claim_job(db, job_id, now=NOW + timedelta(seconds=121))
            db.commit()
    assert run_job(sessions, job_id, callback=edit) == "superseded"
    with sessions() as db:
        item = db.get(DreamItem, 1)
        if change == "deletion":
            assert item is None and db.get(DreamLocation, job_id) is None
        elif change == "manual_pin":
            assert location_coordinates(item) == (1.3, 103.8, "place")
        else:
            assert location_coordinates(item)[0] is None


def test_direct_input_edit_is_detected_before_claim_and_after_provider(sessions):
    add_item(sessions)
    job_id, _ = enqueue(sessions)
    def raw_edit():
        with sessions() as db:
            db.get(DreamItem, 1).city = "Barcelona"
            db.commit()
    assert run_job(sessions, job_id, callback=raw_edit) == "superseded"
    with sessions() as db:
        row = db.get(DreamLocation, job_id)
        assert row.status == "queued" and row.generation == 2
        db.get(DreamItem, 1).city = "Valencia"
        db.commit()
        assert claim_job(db, job_id, now=NOW) is None
        db.commit()
        assert db.get(DreamLocation, job_id).generation == 3


def test_source_alias_changes_retry_unresolved_jobs_and_fence_old_provider_results(sessions):
    add_item(sessions, caption="Garden Cafe (Café Jardín)")
    job_id, _ = enqueue(sessions)
    assert run_job(sessions, job_id, status="not_found", candidates=[]) == "not_found"
    with sessions() as db:
        item = db.get(DreamItem, 1)
        item.caption = "Garden Cafe (Café Nuevo)"
        row, added = enqueue_location(db, item, now=NOW)
        assert added and row.generation == 2
        db.commit()
    def alter_alias():
        with sessions() as db:
            db.get(DreamItem, 1).caption = "Garden Cafe (Café Tercero)"
            db.commit()
    assert run_job(sessions, job_id, callback=alter_alias) == "superseded"
    with sessions() as db:
        item = db.get(DreamItem, 1)
        assert item.location.status == "queued" and item.location.generation == 3
        assert location_coordinates(item)[0] is None


def test_source_alias_does_not_invalidate_a_resolved_or_manual_pin(sessions):
    add_item(sessions)
    job_id, _ = enqueue(sessions)
    assert run_job(sessions, job_id) == "resolved"
    with sessions() as db:
        item = db.get(DreamItem, 1)
        item.caption = "Garden Cafe (Café Jardín)"
        assert enqueue_location(db, item, now=NOW)[1] is False
        db.commit()
        assert location_coordinates(item) == (40.4, -3.7, "place")
        item.google_maps_url = "https://maps.google.com/?q=20,30"
        enqueue_location(db, item, now=NOW)
        db.commit()
        item.caption = "Garden Cafe (Café Nuevo)"
        assert enqueue_location(db, item, now=NOW)[1] is False
        db.commit()
        assert location_coordinates(item) == (20.0, 30.0, "place")


def test_google_worker_receives_only_retained_caption_alias_evidence(sessions, monkeypatch):
    from app.services import google_dream_place_search
    add_item(sessions, caption="Garden Cafe (Café Jardín)")
    job_id, _ = enqueue(sessions)
    calls = []
    async def google(*inputs, source_caption=None):
        calls.append((inputs, source_caption))
        return {"status": "not_found", "provider": "google_places", "candidates": []}
    monkeypatch.setattr(google_dream_place_search, "search_google_dream_place", google)
    assert asyncio.run(resolve_location_job(job_id, session_factory=sessions, now=NOW)) == "not_found"
    assert calls == [(("Garden Cafe", "Madrid", "Spain", None, "cafe"), "Garden Cafe (Café Jardín)")]


def test_manual_candidate_survives_retry_notes_and_status_but_identity_invalidates(sessions):
    add_item(sessions)
    job_id, _ = enqueue(sessions)
    assert run_job(sessions, job_id, "needs_review") == "needs_review"
    with sessions() as db:
        item = db.get(DreamItem, 1)
        with pytest.raises(ValueError, match="does not belong"):
            confirm_candidate(db, item, "other-item-candidate")
        confirm_candidate(db, item, "place-a")
        db.commit()
        item.summary = "New notes"
        item.tags_json = ["weekend"]
        item.status = "confirmed"
        assert enqueue_location(db, item, force=True, now=NOW)[1] is False
        db.commit()
        assert item.location.status == "manual"
        assert location_coordinates(item)[0] == 40.4
        item.place_name = "Different place"
        enqueue_location(db, item, now=NOW)
        db.commit()
        assert location_coordinates(item)[0] is None
        assert item.location.status == "queued"
        assert item.location.history[-1]["latitude"] == 40.4
        with pytest.raises(ValueError, match="no longer current"):
            confirm_candidate(db, item, "place-a")


def test_explicit_pin_and_legacy_area_keep_authority_and_precision(sessions):
    add_item(sessions, google_maps_url="https://maps.google.com/?q=1,2")
    add_item(sessions, item_id=2, raw_metadata_json={"place_match": {"raw": {
        "properties": {"result_type": "suburb"}, "geometry": {"type": "Point", "coordinates": [-3.7, 40.4]}}}})
    first, _ = enqueue(sessions)
    second, _ = enqueue(sessions, 2)
    assert run_job(sessions, first) == "skipped"
    assert run_job(sessions, second) == "skipped"
    with sessions() as db:
        assert location_coordinates(db.get(DreamItem, 1)) == (1, 2, "place")
        assert location_coordinates(db.get(DreamItem, 2)) == (40.4, -3.7, "area")


def test_retry_backoff_is_bounded_and_error_copy_has_no_secrets(sessions, monkeypatch):
    monkeypatch.setenv("DREAM_LOCATION_MAX_ATTEMPTS", "2")
    add_item(sessions)
    job_id, _ = enqueue(sessions)
    async def failure(*_):
        raise RuntimeError("https://provider.invalid/?apiKey=SECRET")
    assert asyncio.run(resolve_location_job(job_id, session_factory=sessions, resolver=failure, now=NOW)) == "queued"
    with sessions() as db:
        row = db.get(DreamLocation, job_id)
        assert "SECRET" not in row.message
        assert due_jobs(db, now=NOW + timedelta(seconds=59)) == []
    assert asyncio.run(resolve_location_job(job_id, session_factory=sessions, resolver=failure, now=NOW + timedelta(seconds=61))) == "failed"
    assert enqueue(sessions, force=True)[1]
    with sessions() as db:
        assert db.get(DreamLocation, job_id).attempts == 0


@pytest.mark.parametrize("status", ["blocked", "not_found", "needs_review"])
def test_no_match_or_configuration_problem_retains_save_without_fake_pin(sessions, status):
    add_item(sessions)
    before = snapshot(sessions)
    job_id, _ = enqueue(sessions)
    # Empty Google results no longer stop at an approval step.
    assert run_job(sessions, job_id, status, []) == ("not_found" if status == "needs_review" else status)
    assert snapshot(sessions) == before
    with sessions() as db:
        item = db.get(DreamItem, 1)
        assert location_coordinates(item)[0] is None
        assert bool(item.location.next_attempt_at) == (status == "blocked")


@pytest.fixture
def api(sessions):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.db import get_db
    from app.routers.auth import get_current_user
    def database():
        with sessions() as db:
            yield db
    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_current_user] = lambda: User(id=1, email="owner@example.invalid")
    yield TestClient(app)
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_current_user, None)


def test_authenticated_reads_do_not_create_jobs_or_contact_provider(api, sessions):
    add_item(sessions)
    before = snapshot(sessions)
    for url in ("/dream-items", "/dreams/1/items"):
        response = api.get(url)
        assert response.status_code == 200
        assert response.json()[0]["location_status"] is None
        assert response.json()[0]["location_candidates"] == []
    with sessions() as db:
        assert db.query(DreamLocation).count() == 0
    assert snapshot(sessions) == before


def test_owner_scoped_retry_batch_and_cross_owner_404_are_atomic(api, sessions):
    add_item(sessions)
    add_item(sessions, item_id=2)
    add_item(sessions, item_id=3, user_id=2)
    assert api.post("/dream-items/3/locate").status_code == 404
    assert api.post("/dream-items/3/location-confirm", json={"candidate_id": "private"}).status_code == 404
    assert api.post("/dreams/locate-missing", json={"item_ids": [1, 3]}).status_code == 404
    with sessions() as db:
        assert db.query(DreamLocation).count() == 0
    response = api.post("/dreams/locate-missing", json={"item_ids": [2]})
    assert response.status_code == 200
    assert response.json()["queued"] == 1
    assert [item["id"] for item in response.json()["items"]] == [2]
    assert response.json()["items"][0]["location_status"] == "queued"
    assert api.post("/dream-items/2/locate").json()["location_status"] == "queued"
    assert api.post("/dreams/locate-missing", json={}).json()["queued"] == 1
    with sessions() as db:
        assert db.query(DreamLocation).count() == 2
        assert db.get(DreamItem, 3).location is None


def test_candidate_confirmation_uses_current_item_evidence_and_returns_compatible_fields(api, sessions):
    add_item(sessions)
    add_item(sessions, item_id=2)
    job_id, _ = enqueue(sessions)
    candidate = {**CANDIDATE, "id": "c" * 512}
    assert run_job(sessions, job_id, "needs_review", [candidate]) == "needs_review"
    response = api.get("/dream-items").json()
    first = next(item for item in response if item["id"] == 1)
    assert set(first["location_candidates"][0]) == {"id", "name", "address", "latitude", "longitude", "google_maps_url", "attributions"}
    assert api.post("/dream-items/2/location-confirm", json={"candidate_id": candidate["id"]}).status_code == 422
    response = api.post("/dream-items/1/location-confirm", json={"candidate_id": candidate["id"]})
    assert response.status_code == 200
    assert response.json()["location_status"] == "manual"
    assert response.json()["latitude"] == 40.4
    assert response.json()["location_address"].startswith("12 Garden")
    assert response.json()["place_name"] == "Garden Cafe"
    response = api.post("/dream-items/1/review", json={"edits": {"summary": "Only new notes"}})
    assert response.json()["location_status"] == "manual"
    assert response.json()["latitude"] == 40.4
    response = api.post("/dream-items/1/review", json={"edits": {"place_name": "New Museum"}})
    assert response.json()["location_status"] == "queued"
    assert response.json()["latitude"] is None


def test_review_new_manual_pin_wins_then_explicit_clear_queues_again(api, sessions):
    add_item(sessions)
    job_id, _ = enqueue(sessions)
    run_job(sessions, job_id)
    response = api.post("/dream-items/1/review", json={"edits": {"google_maps_url": "https://maps.google.com/?q=1.3,103.8"}})
    assert response.json()["location_status"] == "manual"
    assert response.json()["latitude"] == 1.3
    response = api.post("/dream-items/1/review", json={"edits": {"google_maps_url": None}})
    assert response.json()["location_status"] == "queued"
    assert response.json()["latitude"] is None


def test_location_tasks_are_routed_away_from_default_import_queue():
    from app.celery_app import celery_app
    route = celery_app.amqp.router.route({}, "app.tasks.dream_location_tasks.resolve_dream_location")
    assert route["queue"].name == "dream_locations"
    discovery = celery_app.amqp.router.route({}, "app.tasks.dream_location_tasks.discover_dream_locations")
    assert discovery["queue"].name == "dream_locations"
    assert celery_app.amqp.router.route({}, "app.tasks.import_tasks.run_gmail_import")["queue"].name == "celery"


def test_missing_map_link_is_a_pure_encoded_name_search_without_saved_pin(sessions):
    from urllib.parse import parse_qs, urlparse
    add_item(sessions, place_name="Cafe & Garden #2")
    before = snapshot(sessions)
    with sessions() as db:
        item = db.get(DreamItem, 1)
        link = location_maps_url(item)
        assert urlparse(link).netloc == "www.google.com"
        assert parse_qs(urlparse(link).query) == {"api": ["1"], "query": ["Cafe & Garden #2 Madrid Spain"]}
        assert location_coordinates(item) == (None, None, None)
        assert item.google_maps_url is None and item.location is None
    assert snapshot(sessions) == before


@pytest.mark.parametrize("saved_url", ["https://maps.google.com/?q=1.3,103.8", "https://maps.google.com/?cid=existing", "https://www.google.com/maps/search/?query=Original+name"])
def test_existing_map_links_win_over_generated_text_search(sessions, saved_url):
    add_item(sessions, google_maps_url=saved_url)
    with sessions() as db:
        assert location_maps_url(db.get(DreamItem, 1)) == saved_url


def test_coordinate_shaped_name_search_never_becomes_manual_coordinate_evidence(sessions):
    from types import SimpleNamespace
    from urllib.parse import parse_qs, urlparse
    from app.services.dream_locations import explicit_pin
    add_item(sessions, place_name="40.4, -3.7", city=None, country=None)
    with sessions() as db:
        item = db.get(DreamItem, 1)
        link = location_maps_url(item)
        assert parse_qs(urlparse(link).query)["query"] == ["place 40.4, -3.7"]
        assert explicit_pin(SimpleNamespace(google_maps_url=link)) == (None, None, None)
        assert location_coordinates(item) == (None, None, None)


@pytest.mark.parametrize("name", [None, "", "  "])
def test_unnamed_item_does_not_get_a_city_only_map_search(sessions, name):
    add_item(sessions, place_name=name)
    with sessions() as db:
        assert location_maps_url(db.get(DreamItem, 1)) is None
