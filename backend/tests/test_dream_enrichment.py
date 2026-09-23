"""Synthetic queue, concurrency and API contract tests; no live provider or broker."""
from datetime import datetime, timedelta, timezone

import pytest

from app.models import DreamEnrichmentJob, DreamItem
from app.services.dream_enrichment import (
    LEASE_SECONDS, cancel_enrichment, claim_enrichment,
    discover_enrichment, enqueue_enrichment, resolve_enrichment_job,
)
from app.services.dream_parser import DreamParseItem, DreamParseResponse
from app.tasks.dream_enrichment_tasks import dispatch_pending_enrichment
from test_dream_locations import sessions, add_item
from test_dreams import client, test_db, test_user

NOW = datetime(2026, 9, 23, 12, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def no_notifications(monkeypatch):
    monkeypatch.setattr("app.routers.dreams.notify_enrichment", lambda _: None)


def enqueue(sessions, item_id=1, **kwargs):
    with sessions() as db:
        row, added = enqueue_enrichment(db, db.get(DreamItem, item_id), now=NOW, **kwargs)
        db.commit()
        return row.id if row else None, added


def result():
    return {"caption": "Garden Cafe in Madrid, Spain", "metadata": {}, "parsed": DreamParseResponse(
        items=[DreamParseItem(place_name="Garden Cafe", city="Madrid", country="Spain", category="cafe",
                              summary="A garden cafe.", confidence=0.95, needs_review=False)], model="synthetic",
        raw={"error": "must never persist synthetic-secret"})}


def run(sessions, job_id, reader=None, now=NOW):
    return resolve_enrichment_job(job_id, session_factory=sessions, reader=reader or (lambda _: result()), now=now)


def test_share_and_batch_ack_without_provider_and_keep_durable_owner_jobs(client, test_db, test_user, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Capture must not call providers")
    monkeypatch.setattr("app.routers.dreams.fetch_instagram_metadata", forbidden)
    monkeypatch.setattr("app.routers.dreams.parse_caption_with_fallback_model", forbidden)
    monkeypatch.setattr("app.routers.dreams.cache_thumbnail", forbidden)
    source = "https://instagram.com/reel/quick"
    first = client.post("/dreams/share", json={"source_url": source}).json()
    assert first["status"] == "processing"
    duplicate = client.post("/dreams/share", json={"source_url": source + "/?igsh=tracking"}).json()
    assert duplicate["duplicate"] and duplicate["dream_item_id"] == first["dream_item_id"]
    response = client.post("/dreams/import-instagram-batch", json={"source_urls": [source, source + "-other"]})
    assert response.status_code == 200 and response.json()["duplicates"] == 1
    assert test_db.query(DreamItem).count() == test_db.query(DreamEnrichmentJob).count() == 2
    assert all(row.user_id == test_user.id and row.status == "queued" for row in test_db.query(DreamEnrichmentJob))
    assert client.get("/dreams").json()[0]["processing_count"] == 2


def test_partial_batch_keeps_already_captured_links(client, test_db, test_user, monkeypatch):
    from app.routers import dreams
    capture = dreams.capture_dream
    def interrupted(db, payload, user_id):
        if payload.source_url.endswith("second"):
            raise RuntimeError("Synthetic interrupted request")
        return capture(db, payload, user_id)
    monkeypatch.setattr(dreams, "capture_dream", interrupted)
    with pytest.raises(RuntimeError, match="Synthetic interrupted"):
        client.post("/dreams/import-instagram-batch", json={"source_urls": [
            "https://instagram.com/reel/first", "https://instagram.com/reel/second"]})
    assert test_db.query(DreamItem).one().source_url.endswith("first")
    assert test_db.query(DreamEnrichmentJob).one().status == "queued"


def test_sort_is_atomic_owner_scoped_idempotent_and_cannot_overwrite_edits(client, test_db, test_user):
    item_id = client.post("/dreams/share", json={"source_url": "https://instagram.com/reel/sort"}).json()["dream_item_id"]
    assert client.post("/dreams/sort", json={"item_ids": [item_id, 99999]}).status_code == 404
    job = test_db.query(DreamEnrichmentJob).one()
    assert job.generation == 1
    response = client.post("/dreams/sort", json={"item_ids": [item_id, item_id]}).json()
    assert response == {"queued": 0, "processing": 1, "item_ids": [item_id], "skipped": 0}
    edited = client.post(f"/dream-items/{item_id}/review", json={"decision": "needs_review", "edits": {"summary": "My private notes"}})
    assert edited.status_code == 200 and edited.json()["status"] == "needs_review"
    response = client.post("/dreams/sort", json={"item_ids": [item_id]}).json()
    assert response["skipped"] == 1 and response["processing"] == 0
    test_db.expire_all()
    assert test_db.query(DreamEnrichmentJob).one().status == "cancelled"
    assert test_db.query(DreamItem).one().summary == "My private notes"


def test_worker_releases_every_transaction_before_provider_and_preserves_source_notes(sessions):
    add_item(sessions)
    job_id, added = enqueue(sessions)
    tracked = []
    def factory():
        db = sessions()
        tracked.append(db)
        return db
    def reader(claim):
        assert all(not db.in_transaction() for db in tracked)
        response = result()
        response["parsed"].items.append(DreamParseItem(place_name="Second Cafe", summary="Second item", needs_review=True))
        return response
    assert added
    assert resolve_enrichment_job(job_id, session_factory=factory, reader=reader, now=NOW) == "completed"
    assert run(sessions, job_id) == "skipped"
    with sessions() as db:
        item = db.get(DreamItem, 1)
        assert item.status == "parsed" and item.summary == "Keep my notes"
        assert item.tags_json == ["favorite"]
        assert item.raw_metadata_json["source"] == {"untouched": True}
        assert len(item.raw_metadata_json["parser_raw"]["items"]) == 2
        assert "synthetic-secret" not in str(item.raw_metadata_json)
        assert item.location.status == "queued"


@pytest.mark.parametrize("change", ["edit", "raw_edit", "delete", "new_generation", "new_lease"])
def test_late_results_never_replace_new_user_state(sessions, change):
    add_item(sessions)
    job_id, _ = enqueue(sessions)
    def reader(_):
        with sessions() as db:
            item = db.get(DreamItem, 1)
            if change == "delete":
                db.delete(item)
            elif change == "new_lease":
                assert claim_enrichment(db, job_id, now=NOW + timedelta(seconds=LEASE_SECONDS + 1))
            else:
                item.summary = "New user note"
                if change == "edit":
                    cancel_enrichment(db, item, user_edited=True, now=NOW)
                    item.status = "confirmed"
                elif change == "new_generation":
                    enqueue_enrichment(db, item, force=True, now=NOW)
            db.commit()
        return result()
    assert run(sessions, job_id, reader) == "superseded"
    with sessions() as db:
        if change == "delete":
            assert db.get(DreamItem, 1) is None and db.get(DreamEnrichmentJob, job_id) is None
        elif change != "new_lease":
            assert db.get(DreamItem, 1).summary == "New user note"


def test_lost_broker_notification_recovers_and_discovery_moves_in_bounded_batches(sessions):
    for item_id in range(1, 5):
        add_item(sessions, item_id=item_id, place_name=None, city=None, country=None)
    add_item(sessions, item_id=5, status="confirmed", place_name=None, city=None, country=None)
    add_item(sessions, item_id=6, status="processing", place_name=None, city=None, country=None,
             raw_metadata_json={"dream_user_edited": True})
    with sessions() as db:
        assert discover_enrichment(db, limit=2, now=NOW) == 2
        db.commit()
        assert discover_enrichment(db, limit=2, now=NOW) == 2
        db.commit()
        assert discover_enrichment(db, limit=2, now=NOW) == 0
        db.commit()
        assert db.get(DreamItem, 5).enrichment is None
        assert db.get(DreamItem, 6).enrichment.status == "cancelled"
        assert db.get(DreamItem, 6).status != "processing"
    def failure(_):
        raise RuntimeError("redis://do-not-store-secret")
    assert dispatch_pending_enrichment(session_factory=sessions, publish=failure, now=NOW)["dispatched"] == 0
    sent = []
    assert dispatch_pending_enrichment(session_factory=sessions, publish=sent.append, now=NOW + timedelta(seconds=31))["dispatched"] == 4
    assert len(set(sent)) == 4


def test_discovery_repairs_missing_country_once_without_starving_protected_rows(sessions):
    add_item(sessions, item_id=1, status="parsed", place_name="Tropea", city=None, country=None,
             caption="Tropea, Italy. A coastal town to save.", raw_metadata_json={"dream_user_edited": True})
    add_item(sessions, item_id=2, status="parsed", place_name="Tropea", city=None, country=None,
             caption="Tropea, Italy. A coastal town to save.", google_maps_url="https://maps.google.com/?q=38.67,15.9")
    add_item(sessions, item_id=3, status="parsed", place_name="Tropea", city=None, country=None,
             caption="Tropea, Italy. A coastal town to save.")
    add_item(sessions, item_id=4, status="confirmed", place_name="Tropea", city=None, country=None)
    add_item(sessions, item_id=5, status="parsed", country="Spain")
    with sessions() as db:
        assert discover_enrichment(db, limit=2, now=NOW) == 0
        db.commit()
        assert [db.get(DreamItem, item_id).enrichment.status for item_id in (1, 2)] == ["cancelled", "cancelled"]
        assert discover_enrichment(db, limit=2, now=NOW) == 1
        db.commit()
        job_id = db.get(DreamItem, 3).enrichment.id
        assert db.get(DreamItem, 4).enrichment is None
        assert db.get(DreamItem, 5).enrichment is None
    def reader(claim):
        return {"caption": claim["caption"], "metadata": {}, "parsed": DreamParseResponse(
            items=[DreamParseItem(place_name="Tropea", country=None, summary="A coastal town", needs_review=False)],
            model="synthetic")}
    assert run(sessions, job_id, reader) == "completed"
    with sessions() as db:
        assert db.get(DreamItem, 3).country == "Italy"
        assert db.get(DreamItem, 3).dream.title == "Italy"
        # A completed marker prevents another automatic pass, even if no country
        # could be extracted or old code later removes it again.
        db.get(DreamItem, 3).country = None
        db.commit()
        assert discover_enrichment(db, now=NOW) == 0


def test_repeated_worker_loss_terminates_processing_and_explicit_retry_restarts(sessions, monkeypatch):
    monkeypatch.setenv("DREAM_ENRICHMENT_MAX_ATTEMPTS", "2")
    add_item(sessions)
    job_id, _ = enqueue(sessions)
    with sessions() as db:
        first = claim_enrichment(db, job_id, now=NOW)
        db.commit()
        assert claim_enrichment(db, job_id, now=NOW + timedelta(seconds=1)) is None
        second = claim_enrichment(db, job_id, now=NOW + timedelta(seconds=LEASE_SECONDS + 1))
        db.commit()
        assert second["token"] != first["token"]
        assert claim_enrichment(db, job_id, now=NOW + timedelta(seconds=2 * LEASE_SECONDS + 2)) is None
        db.commit()
        assert db.get(DreamEnrichmentJob, job_id).status == "failed"
        assert db.get(DreamItem, 1).status == "needs_review"
    assert enqueue(sessions, force=True) == (job_id, True)
    assert run(sessions, job_id) == "completed"


def test_metadata_failure_retries_then_finishes_without_secret_payloads(sessions, monkeypatch):
    monkeypatch.setenv("DREAM_ENRICHMENT_MAX_ATTEMPTS", "2")
    add_item(sessions)
    job_id, _ = enqueue(sessions)
    def reader(_):
        raise RuntimeError("provider-url-and-secret")
    assert run(sessions, job_id, reader) == "queued"
    assert run(sessions, job_id, reader, NOW + timedelta(seconds=29)) == "skipped"
    assert run(sessions, job_id, reader, NOW + timedelta(seconds=31)) == "failed"
    with sessions() as db:
        item, job = db.get(DreamItem, 1), db.get(DreamEnrichmentJob, job_id)
        assert item.status == "needs_review" and item.summary == "Keep my notes"
        assert job.next_attempt_at is None and job.lease_token is None
        assert "secret" not in str(job.message) + str(item.raw_metadata_json)


def test_confirmed_and_manually_pinned_saves_are_not_reparsed(sessions):
    add_item(sessions, status="confirmed")
    add_item(sessions, item_id=2, google_maps_url="https://maps.google.com/?q=1.3,103.8")
    assert enqueue(sessions, force=True) == (None, False)
    assert enqueue(sessions, item_id=2, force=True) == (None, False)


def test_tasks_have_dedicated_queue_recovery_and_limits():
    from app.celery_app import celery_app
    from app.tasks.dream_enrichment_tasks import process_dream_enrichment
    assert celery_app.conf.task_routes["app.tasks.dream_enrichment_tasks.*"]["queue"] == "dream_enrichment"
    assert celery_app.conf.beat_schedule["dream-enrichment-discovery"]["schedule"] == 10
    assert process_dream_enrichment.time_limit < LEASE_SECONDS


@pytest.mark.parametrize("caption,city,model_country,expected", [
    ("Tropea in Italy. Save this beach for later.", None, None, "Italy"),
    ("Our favorite places in Italy and France.", None, None, None),
    ("This beautiful beach is not Italy.", None, None, None),
    ("Looking back at Italy before our next trip.", "Madrid", None, None),
    ("A trip from Spain to Italy.", None, "Spain", "Spain"),
])
def test_only_unambiguous_explicit_country_fills_missing_model_field(sessions, caption, city, model_country, expected):
    add_item(sessions, place_name=None, city=None, country=None)
    job_id, _ = enqueue(sessions)
    def reader(_):
        return {"caption": caption, "metadata": {}, "parsed": DreamParseResponse(
            items=[DreamParseItem(place_name="Tropea", city=city, country=model_country,
                                  summary="A coastal save.", confidence=0.8, needs_review=True)], model="synthetic")}
    assert run(sessions, job_id, reader) == "completed"
    with sessions() as db:
        item = db.get(DreamItem, 1)
        assert item.country == expected and item.city == city
        assert item.raw_metadata_json["parser_raw"]["items"][0]["country"] == expected
        if expected:
            assert item.dream.title == expected
