"""Google content lifetime and ownership tests: synthetic DB, cache and provider only."""
import asyncio
import copy
import json
from datetime import timedelta

import pytest

from app.models import DreamItem, DreamLocation, DreamGoogleIdentity
from app.services import dream_locations as locations
from app.services import google_location_lifecycle as google
from test_dream_locations import sessions, add_item, enqueue, snapshot, NOW

CANDIDATE = {"id": "google-place-a", "name": "Provider-only display name", "address": "Provider-only address",
             "latitude": 40.4, "longitude": -3.7, "google_maps_url": "https://www.google.com/maps/?q=40.4,-3.7",
             "provider": "google_places", "attributions": [{"display_name": "Provider attribution", "uri": "https://example.invalid"}]}


class Cache:
    def __init__(self):
        self.values, self.writes = {}, []
    def set(self, key, value, *, ex):
        self.values[key] = value
        self.writes.append((key, json.loads(value), ex))
        return True
    def get(self, key):
        return self.values.get(key)


@pytest.fixture(autouse=True)
def isolated_cache(monkeypatch):
    cache = Cache()
    monkeypatch.setattr(google, "cache_client", lambda: cache)
    monkeypatch.setattr(google, "_cache_outage_until", 0)
    monkeypatch.setattr(locations, "utcnow", lambda: NOW)
    monkeypatch.setenv("GOOGLE_PLACES_API_KEY", "")
    return cache


def resolve(sessions, job_id, status="resolved", *, candidates=None, now=NOW):
    async def resolver(*_):
        return {"provider": "google_places", "status": status,
                "candidates": copy.deepcopy([CANDIDATE] if candidates is None else candidates)}
    return asyncio.run(locations.resolve_location_job(job_id, session_factory=sessions, resolver=resolver, now=now))


def legacy_review(sessions, job_id, *, candidate_ids=None):
    """Seed the old approval state without passing through the new worker."""
    with sessions() as db:
        row = db.get(DreamLocation, job_id)
        row.status, row.provider = "needs_review", "google_places"
        row.message = "Choose the place that matches your save."
        row.next_attempt_at = None
        identity = google.ensure_identity(db, row)
        identity.place_fingerprint = google.source_place_fingerprint(row.item)
        identity.candidate_place_ids = candidate_ids or [CANDIDATE["id"]]
        db.commit()


def test_google_payload_is_never_stored_in_db_or_history_and_coordinate_cache_is_bounded(sessions, isolated_cache):
    add_item(sessions)
    before = snapshot(sessions)
    job_id, _ = enqueue(sessions)
    assert resolve(sessions, job_id) == "resolved"
    assert snapshot(sessions) == before
    with sessions() as db:
        row = db.get(DreamLocation, job_id)
        locations.archive_resolution(row, "synthetic_audit", NOW)
        db.commit()
        assert row.google_identity.selected_place_id == CANDIDATE["id"]
        assert row.latitude is row.longitude is row.address is row.google_maps_url is None
        assert row.candidates == []
        values = repr(db.connection().exec_driver_sql('SELECT * FROM dream_locations').all())
        assert "Provider-only" not in values and "40.4" not in values and "-3.7" not in values
        assert "attributions" not in values and "google-place-a" in values
        assert locations.location_coordinates(db.get(DreamItem, 1)) == (40.4, -3.7, "place")
    assert len(isolated_cache.writes) == 1
    _, payload, ttl = isolated_cache.writes[0]
    assert set(payload) == {"latitude", "longitude", "expires_at"}
    assert ttl == 29 * 24 * 60 * 60


def test_area_precision_survives_cache_read_and_expiry_without_storing_google_content(sessions, isolated_cache):
    add_item(sessions,place_name="Tropea",city=None,country="Italy",category="unknown")
    before=snapshot(sessions)
    job_id,_=enqueue(sessions)
    assert resolve(sessions,job_id,candidates=[{**CANDIDATE,"precision":"area"}]) == "resolved"
    with sessions() as db:
        item=db.get(DreamItem,1)
        assert locations.location_coordinates(item) == (40.4,-3.7,"area")
        assert item.location.coordinate_precision == "area"
        assert item.location.message == "Area found on Google Maps."
        item.location.google_identity.coordinates_expires_at=NOW-timedelta(seconds=1)
        assert locations.location_coordinates(item) == (None,None,None)
    assert snapshot(sessions) == before
    assert set(isolated_cache.writes[0][1]) == {"latitude","longitude","expires_at"}


def test_area_precision_is_invalidated_when_saved_place_identity_changes(sessions):
    add_item(sessions)
    job_id,_=enqueue(sessions)
    assert resolve(sessions,job_id,candidates=[{**CANDIDATE,"precision":"area"}]) == "resolved"
    with sessions() as db:
        item=db.get(DreamItem,1)
        item.place_name="A different place"
        locations.enqueue_location(db,item,now=NOW)
        assert item.location.coordinate_precision is None
        assert locations.location_coordinates(item) == (None,None,None)


@pytest.mark.parametrize("precision", ["area", "place"])
def test_live_details_preserve_precision_and_fetch_outside_database_transaction(sessions, isolated_cache, monkeypatch, precision):
    from app.services import google_dream_place_search as provider
    add_item(sessions)
    job_id, _ = enqueue(sessions)
    candidate = {**CANDIDATE, "precision": precision}
    assert resolve(sessions, job_id, candidates=[candidate]) == "resolved"
    before = snapshot(sessions)
    cached_before = copy.deepcopy(isolated_cache.values)
    calls = []
    with sessions() as db:
        async def details(identity, *, allow_area=False):
            assert not db.in_transaction(), "The Google request must not reopen the rolled-back transaction"
            calls.append((identity, allow_area))
            return provider.GoogleCandidate(**candidate)
        monkeypatch.setattr(provider, "fetch_google_place_details", details)
        result = asyncio.run(google.live_google_details(db, 1, 1))
        assert result["coordinate_precision"] == precision
        assert result["location_candidates"][0]["precision"] == precision
        assert result["location_place_id"] == CANDIDATE["id"]
        assert db.get(DreamLocation, job_id).coordinate_precision == precision
    assert calls == [(CANDIDATE["id"], precision == "area")]
    assert isolated_cache.values == cached_before
    assert snapshot(sessions) == before


def test_area_confirmation_captures_precision_before_rollback_and_preserves_area(sessions, monkeypatch):
    from app.services import google_dream_place_search as provider
    add_item(sessions)
    job_id, _ = enqueue(sessions)
    legacy_review(sessions, job_id)
    with sessions() as db:
        db.get(DreamLocation, job_id).coordinate_precision = "area"
        db.commit()
    calls = []
    with sessions() as db:
        async def details(identity, *, allow_area=False):
            assert not db.in_transaction(), "Reading an expired ORM attribute must not restart a transaction before Google"
            calls.append((identity, allow_area))
            return provider.GoogleCandidate(**{**CANDIDATE, "precision": "area"})
        monkeypatch.setattr(provider, "fetch_google_place_details", details)
        item = asyncio.run(google.confirm_google_candidate(db, 1, 1, CANDIDATE["id"]))
        db.commit()
        assert item.location.status == "manual"
        assert item.location.coordinate_precision == "area"
        assert locations.location_coordinates(item) == (40.4, -3.7, "area")
        assert item.location.google_identity.confirmed_place_id == CANDIDATE["id"]
    assert calls == [(CANDIDATE["id"], True)]


@pytest.mark.parametrize("refresh_path", ["missing_cache", "expired_enqueue"])
def test_area_refresh_retains_precision_and_fetches_the_existing_area_identity(sessions, isolated_cache, monkeypatch, refresh_path):
    from app.services import google_dream_place_search as provider
    add_item(sessions)
    job_id, _ = enqueue(sessions)
    candidate = {**CANDIDATE, "precision": "area"}
    assert resolve(sessions, job_id, candidates=[candidate]) == "resolved"
    before = snapshot(sessions)
    refreshed_at = NOW + (timedelta(minutes=6) if refresh_path == "missing_cache" else timedelta(days=29))
    with sessions() as db:
        if refresh_path == "missing_cache":
            isolated_cache.values.clear()
            assert google.queue_google_refreshes(db, now=refreshed_at, limit=10) == 1
        else:
            item = db.get(DreamItem, 1)
            row, queued = locations.enqueue_location(db, item, now=refreshed_at)
            assert queued
        row = db.get(DreamLocation, job_id)
        assert row.coordinate_precision == "area", "Refreshing the same Google identity must preserve area precision"
        assert row.google_identity.selected_place_id == CANDIDATE["id"]
        db.commit()
    calls = []
    async def details(identity, *, allow_area=False):
        calls.append((identity, allow_area))
        # A geographic Google result is intentionally unavailable to exact-venue requests.
        return provider.GoogleCandidate(**candidate) if allow_area else None
    monkeypatch.setattr(provider, "fetch_google_place_details", details)
    assert asyncio.run(locations.resolve_location_job(job_id, session_factory=sessions, now=refreshed_at)) == "resolved"
    assert calls == [(CANDIDATE["id"], True)]
    with sessions() as db:
        item = db.get(DreamItem, 1)
        assert item.location.coordinate_precision == "area"
        assert locations.location_coordinates(item) == (40.4, -3.7, "area")
    assert snapshot(sessions) == before


@pytest.mark.parametrize("provider_status", ["resolved", "needs_review"])
def test_google_match_populates_map_without_claiming_user_approval(sessions, provider_status):
    add_item(sessions)
    before = snapshot(sessions)
    job_id, _ = enqueue(sessions)
    assert resolve(sessions, job_id, provider_status) == "resolved"
    with sessions() as db:
        item = db.get(DreamItem, 1)
        fields = locations.public_location(item)
        assert locations.location_coordinates(item) == (40.4, -3.7, "place")
        assert fields["location_status"] == "resolved"
        assert fields["location_place_id"] == CANDIDATE["id"]
        assert fields["location_user_confirmed"] is False
        assert item.location.google_identity.confirmed_place_id is None
        assert "query_place_id=google-place-a" in locations.location_maps_url(item)
        assert fields["location_message"] == "Location found on Google Maps."
    assert snapshot(sessions) == before


def test_legacy_multiple_provider_candidates_use_first_match_without_approval(sessions):
    add_item(sessions)
    job_id, _ = enqueue(sessions)
    candidates = [{**CANDIDATE, "id": "z-relevant-place"}, {**CANDIDATE, "id": "a-other-branch"}]
    assert resolve(sessions, job_id, "needs_review", candidates=candidates) == "resolved"
    with sessions() as db:
        item = db.get(DreamItem, 1)
        assert item.location.google_identity.selected_place_id == "z-relevant-place"
        assert locations.public_location(item)["location_user_confirmed"] is False


def test_legacy_review_backfill_revalidates_current_inputs_once_and_preserves_saves(sessions):
    from app.tasks.dream_location_tasks import dispatch_pending_locations
    for item_id in (1, 2):
        add_item(sessions, item_id=item_id)
        job_id, _ = enqueue(sessions, item_id)
        legacy_review(sessions, job_id)
    add_item(sessions, item_id=3, google_maps_url="https://maps.google.com/?q=1.3,103.8")
    enqueue(sessions, 3)
    before = snapshot(sessions)
    sent = []
    result = dispatch_pending_locations(session_factory=sessions, publish=sent.append, now=NOW)
    assert result["queued"] == 2 and result["dispatched"] == 2
    assert dispatch_pending_locations(session_factory=sessions, publish=sent.append, now=NOW)["queued"] == 0
    for job_id in sent:
        # Fresh search is used, rather than assuming an old candidate is still
        # valid or fetching the first historical ID without its search context.
        with sessions() as db:
            row = db.get(DreamLocation, job_id)
            assert row.status == "queued" and row.generation == 2
            assert row.google_identity.selected_place_id is None
            assert row.history[-1]["candidate_place_ids"] == [CANDIDATE["id"]]
        assert resolve(sessions, job_id) == "resolved"
    assert dispatch_pending_locations(session_factory=sessions, publish=sent.append, now=NOW)["queued"] == 0
    with sessions() as db:
        assert locations.location_coordinates(db.get(DreamItem, 3)) == (1.3, 103.8, "place")
        assert db.query(DreamLocation).count() == 3
    assert snapshot(sessions) == before


def test_review_backfill_is_bounded_and_stale_candidates_cannot_invent_a_pin(sessions):
    for item_id in range(1, 4):
        add_item(sessions, item_id=item_id)
        job_id, _ = enqueue(sessions, item_id)
        legacy_review(sessions, job_id)
    with sessions() as db:
        assert google.queue_pending_google_matches(db, now=NOW, limit=2) == 2
        db.commit()
        assert google.queue_pending_google_matches(db, now=NOW, limit=2) == 1
        db.commit()
        assert google.queue_pending_google_matches(db, now=NOW, limit=2) == 0
    assert resolve(sessions, 1, "needs_review", candidates=[]) == "not_found"
    with sessions() as db:
        item = db.get(DreamItem, 1)
        assert item.location.google_identity.selected_place_id is None
        assert locations.location_coordinates(item) == (None, None, None)
        assert google.queue_pending_google_matches(db, now=NOW, limit=2) == 0


def test_automatic_google_match_yields_to_manual_correction_and_rejects_stale_search(sessions):
    add_item(sessions)
    job_id, _ = enqueue(sessions)
    resolve(sessions, job_id)
    with sessions() as db:
        item = db.get(DreamItem, 1)
        item.place_name = "Different Venue"
        locations.enqueue_location(db, item, now=NOW)
        db.commit()
        assert item.location.google_identity.selected_place_id is None
    async def delayed_match(*_):
        with sessions() as editing:
            item = editing.get(DreamItem, 1)
            item.google_maps_url = "https://maps.google.com/?q=1.3,103.8"
            locations.enqueue_location(editing, item, now=NOW)
            editing.commit()
        return {"provider": "google_places", "status": "resolved", "candidates": [CANDIDATE]}
    assert asyncio.run(locations.resolve_location_job(job_id, session_factory=sessions, resolver=delayed_match, now=NOW)) == "superseded"
    with sessions() as db:
        assert locations.location_coordinates(db.get(DreamItem, 1)) == (1.3, 103.8, "place")


def test_expiry_hides_every_coordinate_path_even_if_redis_retains_old_value(sessions, monkeypatch):
    add_item(sessions)
    job_id, _ = enqueue(sessions)
    resolve(sessions, job_id)
    monkeypatch.setattr(locations, "utcnow", lambda: NOW + timedelta(days=29))
    with sessions() as db:
        item = db.get(DreamItem, 1)
        item.location.latitude, item.location.longitude = 40.4, -3.7  # Defense against an old writer.
        assert locations.location_coordinates(item) == (None, None, None)
        public = locations.public_location(item)
        assert public["location_status"] == "queued"
        assert public["location_address"] is None and public["location_candidates"] == []
        assert public["location_place_id"] == "google-place-a"
        assert public["location_expires_at"] is not None
        url = locations.location_maps_url(item)
        assert "query_place_id=google-place-a" in url and "40.4" not in url


def test_missing_cache_is_hidden_and_recovered_without_new_name_search(sessions, isolated_cache, monkeypatch):
    from app.services import google_dream_place_search as provider
    add_item(sessions)
    job_id, _ = enqueue(sessions)
    resolve(sessions, job_id)
    isolated_cache.values.clear()
    with sessions() as db:
        assert locations.location_coordinates(db.get(DreamItem, 1))[0] is None
        assert google.queue_google_refreshes(db, now=NOW + timedelta(minutes=6), limit=10) == 1
        db.commit()
    calls = []
    async def details(identity, *, allow_area=False):
        assert allow_area is False
        calls.append(identity)
        return provider.GoogleCandidate(**CANDIDATE)
    monkeypatch.setattr(provider, "fetch_google_place_details", details)
    assert asyncio.run(locations.resolve_location_job(job_id, session_factory=sessions, now=NOW + timedelta(minutes=6))) == "resolved"
    assert calls == ["google-place-a"]


def test_fresh_details_are_transient_owner_scoped_and_do_not_mutate_cache_or_rows(sessions, isolated_cache):
    add_item(sessions)
    job_id, _ = enqueue(sessions)
    legacy_review(sessions, job_id)
    before = snapshot(sessions)
    async def fetch(identity):
        assert identity == "google-place-a"
        return copy.deepcopy(CANDIDATE)
    with sessions() as db:
        assert db.get(DreamLocation, job_id).message == "Choose the place that matches your save."
        with pytest.raises(LookupError):
            asyncio.run(google.live_google_details(db, 1, 2, fetcher=fetch))
        details = asyncio.run(google.live_google_details(db, 1, 1, fetcher=fetch))
        assert details["location_candidates"][0]["name"] == "Provider-only display name"
        assert details["location_attributions"] == CANDIDATE["attributions"]
        assert details["location_expires_at"] == NOW + timedelta(days=29)
        assert db.get(DreamLocation, job_id).candidates == []
    assert snapshot(sessions) == before and not isolated_cache.writes


def test_long_provider_identity_is_retained_without_truncation(sessions):
    add_item(sessions)
    job_id, _ = enqueue(sessions)
    candidate = {**CANDIDATE, "id": "G" * 4096}
    assert resolve(sessions, job_id, candidates=[candidate]) == "resolved"
    with sessions() as db:
        assert db.get(DreamLocation, job_id).google_identity.selected_place_id == candidate["id"]


def test_google_confirmation_preserves_category_edits_but_invalidates_place_identity(sessions):
    add_item(sessions)
    job_id, _ = enqueue(sessions)
    legacy_review(sessions, job_id)
    async def fetch(_):
        return copy.deepcopy(CANDIDATE)
    with sessions() as db:
        item = asyncio.run(google.confirm_google_candidate(db, 1, 1, "google-place-a", fetcher=fetch))
        db.commit()
        assert item.location.status == "manual"
        assert item.location.google_identity.confirmed_place_id == "google-place-a"
        assert "Provider-only" not in repr(item.location.history)
        item.category = "restaurant"
        locations.enqueue_location(db, item, now=NOW + timedelta(hours=1))
        db.commit()
        assert item.location.google_identity.confirmed_place_id == "google-place-a"
        assert item.location.google_identity.selected_place_id == "google-place-a"
        assert item.location.status == "queued"
        assert locations.location_coordinates(item)[0] is None
        item.place_name = "Different venue"
        locations.enqueue_location(db, item, now=NOW + timedelta(hours=2))
        db.commit()
        assert item.location.google_identity.confirmed_place_id is None
        assert item.location.google_identity.selected_place_id is None
        assert any(entry.get("confirmed_place_id") == "google-place-a" for entry in item.location.history)


def test_manual_coordinate_edit_supersedes_google_choice_and_cache(sessions):
    add_item(sessions)
    job_id, _ = enqueue(sessions)
    resolve(sessions, job_id)
    with sessions() as db:
        item = db.get(DreamItem, 1)
        item.google_maps_url = "https://www.google.com/maps/?q=1.3,103.8"
        locations.enqueue_location(db, item, now=NOW)
        db.commit()
        assert locations.location_coordinates(item) == (1.3, 103.8, "place")
        assert item.location.google_identity.confirmed_place_id is None
        assert item.location.google_identity.selected_place_id is None


def test_confirmation_requires_current_id_and_rejects_inflight_user_edits(sessions):
    add_item(sessions)
    job_id, _ = enqueue(sessions)
    legacy_review(sessions, job_id)
    async def wrong(_):
        raise AssertionError("An unrelated candidate must not call the provider")
    with sessions() as db, pytest.raises(ValueError):
        asyncio.run(google.confirm_google_candidate(db, 1, 1, "other-place", fetcher=wrong))
    async def changed(_):
        with sessions() as editing:
            item = editing.get(DreamItem, 1)
            item.google_maps_url = "https://www.google.com/maps/?q=1.3,103.8"
            editing.commit()
        return copy.deepcopy(CANDIDATE)
    with sessions() as db, pytest.raises(ValueError):
        asyncio.run(google.confirm_google_candidate(db, 1, 1, "google-place-a", fetcher=changed))


def test_old_google_payload_and_generated_url_never_leak_stale_coordinates(sessions):
    add_item(sessions, google_place_id="old-place", google_maps_url="https://www.google.com/maps/?q=40.4,-3.7",
             raw_metadata_json={"place_match": {"raw": {"location": {"latitude": 40.4, "longitude": -3.7}}}})
    before = snapshot(sessions)
    with sessions() as db:
        item = db.get(DreamItem, 1)
        assert locations.location_coordinates(item)[0] is None
        assert "40.4" not in locations.location_maps_url(item)
    assert snapshot(sessions) == before


def test_google_cache_outage_never_saves_payload_or_loses_original_item(sessions, isolated_cache):
    add_item(sessions)
    before = snapshot(sessions)
    job_id, _ = enqueue(sessions)
    def fail(*_, **__):
        raise RuntimeError("private cache URL must not escape")
    isolated_cache.set = fail
    assert resolve(sessions, job_id) == "queued"
    with sessions() as db:
        row = db.get(DreamLocation, job_id)
        assert row.address is None and row.candidates == []
        assert "private" not in row.message
        assert locations.location_coordinates(db.get(DreamItem, 1))[0] is None
    assert snapshot(sessions) == before


def test_many_serialized_points_share_one_short_cache_failure(sessions, isolated_cache):
    add_item(sessions)
    job_id, _ = enqueue(sessions)
    resolve(sessions, job_id)
    calls = []
    def unavailable(_):
        calls.append(1)
        raise OSError("Synthetic Redis timeout")
    isolated_cache.get = unavailable
    with sessions() as db:
        item = db.get(DreamItem, 1)
        for _ in range(100):
            assert locations.location_coordinates(item)[0] is None
    assert len(calls) == 1


def test_fresh_details_reports_concurrent_confirmation_current_state(sessions):
    add_item(sessions)
    job_id, _ = enqueue(sessions)
    legacy_review(sessions, job_id)
    async def confirm_during_fetch(_):
        with sessions() as editing:
            row = editing.get(DreamLocation, job_id)
            row.status = "manual"
            row.google_identity.selected_place_id = CANDIDATE["id"]
            row.google_identity.confirmed_place_id = CANDIDATE["id"]
            editing.commit()
        return copy.deepcopy(CANDIDATE)
    with sessions() as db:
        details = asyncio.run(google.live_google_details(db, 1, 1, fetcher=confirm_during_fetch))
        assert details["location_status"] == "manual"
        assert details["location_place_id"] == CANDIDATE["id"]
        assert details["location_address"] == CANDIDATE["address"]
