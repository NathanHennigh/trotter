"""Rule upgrades recover real misses once; no live providers or production data."""
import asyncio
from datetime import timedelta

import pytest
from sqlalchemy import event, insert

from app.models import DreamGoogleIdentity, DreamItem, DreamLocation
from app.services import dream_locations as locations
from app.tasks.dream_location_tasks import dispatch_pending_locations
from test_dream_locations import NOW, add_item, enqueue, sessions, snapshot


def terminal(sessions, item_id=1, *, version=0, status="not_found", **fields):
    add_item(sessions, item_id=item_id, **fields)
    job_id, _ = enqueue(sessions, item_id)
    with sessions() as db:
        row = db.get(DreamLocation, job_id)
        row.status, row.provider = status, "google_places"
        row.matcher_version, row.attempts = version, 5
        row.next_attempt_at = None
        db.commit()
    return job_id


def upgrade(sessions, **kwargs):
    with sessions() as db:
        result = locations.queue_matcher_upgrades(db, now=NOW, **kwargs)
        db.commit()
        return result


async def miss(*_):
    return {"status": "not_found", "provider": "google_places", "candidates": []}


def resolve(sessions, job_id, *, resolver=miss, now=NOW):
    return asyncio.run(locations.resolve_location_job(job_id, session_factory=sessions, resolver=resolver, now=now))


def test_old_miss_gets_one_new_generation_then_stops_without_changing_saved_content(sessions):
    job = terminal(sessions, personal_note="My private note")
    before = snapshot(sessions)
    assert upgrade(sessions) == {"queued": 1, "checked": 1}
    assert upgrade(sessions) == {"queued": 0, "checked": 0}
    with sessions() as db:
        row = db.get(DreamLocation, job)
        assert row.generation == 2 and row.attempts == 0 and row.matcher_version == 0
        assert row.history[-1]["reason"] == "matcher_upgrade"
    assert resolve(sessions, job) == "not_found"
    with sessions() as db:
        row = db.get(DreamLocation, job)
        assert row.matcher_version == locations.MATCHER_VERSION and row.attempts == 1
    for day in (1, 30, 90):
        assert dispatch_pending_locations(session_factory=sessions, publish=lambda _: pytest.fail("Repeated lookup"), now=NOW + timedelta(days=day))["queued"] == 0
    assert snapshot(sessions) == before


def test_next_version_retries_once_and_explicit_retry_after_rollback_gets_new_generation(sessions, monkeypatch):
    job = terminal(sessions, version=locations.MATCHER_VERSION)
    assert upgrade(sessions)["queued"] == 0
    monkeypatch.setattr(locations, "MATCHER_VERSION", 2)
    assert upgrade(sessions)["queued"] == 1
    assert resolve(sessions, job) == "not_found"
    assert upgrade(sessions)["queued"] == 0
    monkeypatch.setattr(locations, "MATCHER_VERSION", 1)
    assert upgrade(sessions)["queued"] == 0
    with sessions() as db:
        item = db.get(DreamItem, 1)
        locations.enqueue_location(db, item, force=True, now=NOW)
        db.commit()
    assert resolve(sessions, job) == "not_found"
    with sessions() as db:
        row = db.get(DreamLocation, job)
        assert row.matcher_version == 1 and row.matcher_generation == row.generation
        assert any(entry.get("matcher_version") == 2 for entry in row.history)
    monkeypatch.setattr(locations, "MATCHER_VERSION", 2)
    assert upgrade(sessions)["queued"] == 1
    assert resolve(sessions, job) == "not_found"


@pytest.mark.parametrize("fields", [
    {"place_name": None},
    {"place_name": "Deluxe room with view", "caption": "Deluxe room with view #fyp"},
    {"place_name": "Lake Atitlan", "category": "hotel", "caption": "Comment LINK for this stay in Lake Atitlan."},
    {"place_name": "Taghazout", "category": "hotel", "city": None, "country": "Morocco",
     "caption": "A beautiful hideaway in Taghazout Morocco. Comment Taghazout for the booking link."},
    {"country": None}, {"country": "Unknown"}, {"country": "---"},
])
def test_source_only_or_missing_country_is_screened_without_provider_work(sessions, fields):
    job = terminal(sessions, **fields)
    before = snapshot(sessions)
    assert upgrade(sessions) == {"queued": 0, "checked": 1}
    assert upgrade(sessions) == {"queued": 0, "checked": 0}
    with sessions() as db:
        row = db.get(DreamLocation, job)
        assert row.matcher_version == locations.MATCHER_VERSION
        assert row.status == "not_found" and row.generation == 1 and row.attempts == 5
    assert snapshot(sessions) == before


def test_small_batches_progress_past_inspiration_and_cross_account_items(sessions):
    terminal(sessions, 1, place_name="Deluxe room with view")
    terminal(sessions, 2)
    terminal(sessions, 3, user_id=2)
    assert upgrade(sessions, limit=2) == {"queued": 1, "checked": 2}
    assert upgrade(sessions, limit=2) == {"queued": 1, "checked": 1}
    assert upgrade(sessions, limit=2) == {"queued": 0, "checked": 0}
    with sessions() as db:
        assert [row.item_id for row in db.query(DreamLocation).filter_by(status="queued").order_by(DreamLocation.id)] == [2, 3]


@pytest.mark.parametrize("status", ["manual", "resolved", "queued", "running", "blocked", "needs_review"])
def test_existing_choices_active_work_and_outage_cooldown_are_not_restarted(sessions, status):
    job = terminal(sessions, status=status)
    with sessions() as db:
        before = db.connection().exec_driver_sql("SELECT * FROM dream_locations").all()
    assert upgrade(sessions) == {"queued": 0, "checked": 0}
    with sessions() as db:
        assert db.connection().exec_driver_sql("SELECT * FROM dream_locations").all() == before


@pytest.mark.parametrize("identity", ["selected_place_id", "confirmed_place_id"])
def test_failed_refresh_never_rematches_a_retained_selected_or_confirmed_id(sessions, identity):
    job = terminal(sessions, status="failed")
    with sessions() as db:
        db.add(DreamGoogleIdentity(location_id=job, **{identity: "retained-id"}))
        db.commit()
    assert upgrade(sessions) == {"queued": 0, "checked": 0}
    with sessions() as db:
        assert getattr(db.get(DreamLocation, job).google_identity, identity) == "retained-id"


def test_new_manual_pin_wins_over_stale_failed_row(sessions):
    job = terminal(sessions, status="failed")
    with sessions() as db:
        db.get(DreamItem, 1).google_maps_url = "https://maps.google.com/?q=1.3,103.8"
        db.commit()
    assert upgrade(sessions)["queued"] == 0
    with sessions() as db:
        assert locations.location_coordinates(db.get(DreamItem, 1)) == (1.3, 103.8, "place")
        assert db.get(DreamLocation, job).generation == 1


def test_user_confirmed_text_keeps_protection_when_missing_pin_is_retried(sessions):
    job = terminal(sessions, status="not_found")
    with sessions() as db:
        db.get(DreamItem, 1).status = "confirmed"
        db.commit()
    before = snapshot(sessions)
    assert upgrade(sessions)["queued"] == 1
    with sessions() as db:
        claim = locations.claim_job(db, job, now=NOW)
        db.commit()
        assert claim["protected_fields"] is True
    assert snapshot(sessions) == before


def test_aborted_reservation_remains_eligible_and_duplicate_claim_has_one_version(sessions):
    job = terminal(sessions)
    with sessions() as db:
        assert locations.queue_matcher_upgrades(db, now=NOW)["queued"] == 1
        db.rollback()
    assert upgrade(sessions)["queued"] == 1
    with sessions() as db:
        assert locations.claim_job(db, job, now=NOW)
        db.commit()
        assert locations.claim_job(db, job, now=NOW) is None
        assert db.get(DreamLocation, job).matcher_version == 0
        assert db.get(DreamLocation, job).matcher_retry_version == locations.MATCHER_VERSION


def test_upgraded_failure_still_obeys_attempt_budget(sessions, monkeypatch):
    monkeypatch.setenv("DREAM_LOCATION_MAX_ATTEMPTS", "2")
    job = terminal(sessions, status="failed")
    assert upgrade(sessions)["queued"] == 1
    async def broken(*_):
        raise ValueError("Synthetic malformed response")
    assert resolve(sessions, job, resolver=broken) == "queued"
    assert resolve(sessions, job, resolver=broken, now=NOW + timedelta(seconds=61)) == "failed"
    assert upgrade(sessions)["queued"] == 0
    with sessions() as db:
        assert db.get(DreamLocation, job).attempts == 2


def test_new_work_takes_capacity_before_historical_retries(sessions, monkeypatch):
    monkeypatch.setenv("DREAM_LOCATION_BATCH_SIZE", "2")
    job = terminal(sessions)
    add_item(sessions, item_id=2)
    add_item(sessions, item_id=3)
    sent = []
    result = dispatch_pending_locations(session_factory=sessions, publish=sent.append, now=NOW)
    assert result["queued"] == 2 and len(sent) == 2 and job not in sent
    with sessions() as db:
        assert db.get(DreamLocation, job).status == "not_found"
    # Repeated scheduler ticks while the queue is saturated do not admit more
    # historical work, even if delivery is lost or a lookup takes a long time.
    for minute in range(1, 11):
        assert dispatch_pending_locations(session_factory=sessions, publish=lambda _: None,
            now=NOW + timedelta(minutes=minute))["queued"] == 0
        with sessions() as db:
            assert db.get(DreamLocation, job).generation == 1
            assert db.query(DreamLocation).filter_by(status="queued").count() == 2
    for active in sent:
        assert resolve(sessions, active) == "not_found"
    assert dispatch_pending_locations(session_factory=sessions, publish=sent.append, now=NOW + timedelta(seconds=61))["queued"] == 1
    assert sent[-1] == job


def test_new_source_context_after_screening_uses_normal_edit_path(sessions):
    job = terminal(sessions, country=None)
    assert upgrade(sessions)["queued"] == 0
    with sessions() as db:
        item = db.get(DreamItem, 1)
        item.country = "Spain"
        _, queued = locations.enqueue_location(db, item, now=NOW)
        db.commit()
        assert queued and item.location.generation == 2
    assert resolve(sessions, job) == "not_found"


def test_recovery_selection_uses_partial_index_instead_of_scanning_history(sessions):
    terminal(sessions)
    engine = sessions.kw["bind"]
    # Representative distribution after most historical work was screened;
    # a one-row toy database reasonably prefers the existing status index.
    with engine.begin() as connection:
        connection.execute(insert(DreamItem), [dict(id=number, user_id=1, dream_id=1,
            source_url=f"https://example.invalid/{number}") for number in range(2, 1002)])
        connection.execute(insert(DreamLocation), [dict(id=number, item_id=number, user_id=1,
            fingerprint="source", pin_fingerprint="pin", status="not_found", matcher_version=locations.MATCHER_VERSION, matcher_generation=1)
            for number in range(2, 1002)])
        connection.exec_driver_sql("ANALYZE")
    statements = []
    def capture(_connection, _cursor, statement, parameters, _context, _many):
        if "JOIN dream_locations" in statement and "matcher_generation =" in statement:
            statements.append((statement, parameters))
    event.listen(engine, "before_cursor_execute", capture)
    try:
        assert upgrade(sessions)["queued"] == 1
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert len(statements) == 1
    with engine.connect() as connection:
        plan = connection.exec_driver_sql("EXPLAIN QUERY PLAN " + statements[0][0], statements[0][1]).all()
    assert "ix_dream_locations_matcher_recovery" in repr(plan)


def test_prefeature_worker_cannot_make_abandoned_new_claim_look_completed(sessions, monkeypatch):
    job = terminal(sessions, version=1)
    monkeypatch.setattr(locations, "MATCHER_VERSION", 2)
    assert upgrade(sessions)["queued"] == 1
    with sessions() as db:
        assert locations.claim_job(db, job, now=NOW)
        db.commit()
        assert db.get(DreamLocation, job).matcher_version == 0
    # Simulate the real pre-0016 image: it neither checks nor writes either
    # version column, and can finish an expired lease after app rollback.
    with sessions() as db:
        row = db.get(DreamLocation, job)
        row.status, row.next_attempt_at = "not_found", None
        row.lease_token = row.lease_expires_at = None
        row.attempts += 1
        db.commit()
    assert upgrade(sessions)["queued"] == 1
    assert resolve(sessions, job) == "not_found"
    assert upgrade(sessions)["queued"] == 0


def test_older_version_worker_leaves_new_reservation_for_new_worker(sessions, monkeypatch):
    job = terminal(sessions, version=1)
    monkeypatch.setattr(locations, "MATCHER_VERSION", 2)
    assert upgrade(sessions)["queued"] == 1
    with sessions() as db:
        assert locations.claim_job(db, job, now=NOW)
        db.commit()
    monkeypatch.setattr(locations, "MATCHER_VERSION", 1)
    assert resolve(sessions, job, now=NOW + timedelta(seconds=121)) == "skipped"
    monkeypatch.setattr(locations, "MATCHER_VERSION", 2)
    assert resolve(sessions, job, now=NOW + timedelta(seconds=121)) == "not_found"
    assert upgrade(sessions)["queued"] == 0


def test_historical_reservation_yields_to_new_save_in_dispatch_order(sessions, monkeypatch):
    monkeypatch.setenv("DREAM_LOCATION_BATCH_SIZE", "1")
    historical = terminal(sessions)
    assert upgrade(sessions)["queued"] == 1
    add_item(sessions, item_id=2)
    sent = []
    dispatch_pending_locations(session_factory=sessions, publish=sent.append, now=NOW)
    with sessions() as db:
        fresh = db.get(DreamItem, 2).location.id
    assert sent == [fresh] and historical not in sent


def test_unflushed_coordinate_refresh_occupies_capacity_before_upgrade(sessions, monkeypatch):
    monkeypatch.setenv("DREAM_LOCATION_BATCH_SIZE", "1")
    historical = terminal(sessions)
    refreshing = terminal(sessions, item_id=2, status="resolved", version=locations.MATCHER_VERSION)
    with sessions() as db:
        db.add(DreamGoogleIdentity(location_id=refreshing, selected_place_id="retained-id", refresh_after=NOW))
        db.commit()
    sent = []
    result = dispatch_pending_locations(session_factory=sessions, publish=sent.append, now=NOW)
    assert result["queued"] == 1 and sent == [refreshing]
    with sessions() as db:
        assert db.get(DreamLocation, historical).status == "not_found"


def test_exhausted_abandoned_upgrade_stops_instead_of_starting_another_generation(sessions, monkeypatch):
    monkeypatch.setenv("DREAM_LOCATION_MAX_ATTEMPTS", "1")
    job = terminal(sessions)
    assert upgrade(sessions)["queued"] == 1
    with sessions() as db:
        assert locations.claim_job(db, job, now=NOW)
        db.commit()
        assert locations.claim_job(db, job, now=NOW + timedelta(seconds=121)) is None
        db.commit()
        assert db.get(DreamLocation, job).status == "failed"
    assert upgrade(sessions)["queued"] == 0


def test_prefeature_edit_cannot_carry_completed_version_to_new_inputs(sessions):
    job = terminal(sessions, version=locations.MATCHER_VERSION)
    assert upgrade(sessions)["queued"] == 0
    # An actual old image increments generation/fingerprints but knows nothing
    # about the new version fields; source edits must invalidate their meaning.
    with sessions() as db:
        item = db.get(DreamItem, 1)
        item.place_name = "Edited Garden Cafe"
        row = item.location
        row.generation += 1
        row.fingerprint = locations.fingerprint(item)
        row.status, row.next_attempt_at = "not_found", None
        db.commit()
        assert row.matcher_version == locations.MATCHER_VERSION
        assert row.matcher_generation != row.generation
    assert upgrade(sessions)["queued"] == 1
    assert resolve(sessions, job) == "not_found"
    assert upgrade(sessions)["queued"] == 0


def test_historical_completion_clears_priority_for_future_coordinate_refresh(sessions):
    job = terminal(sessions)
    assert upgrade(sessions)["queued"] == 1
    assert resolve(sessions, job) == "not_found"
    with sessions() as db:
        row = db.get(DreamLocation, job)
        assert row.matcher_retry_version == 0
        row.status = "resolved"
        db.add(DreamGoogleIdentity(location_id=job, selected_place_id="retained-id", refresh_after=NOW)) if not row.google_identity else None
        if row.google_identity:
            row.google_identity.selected_place_id = "retained-id"
            row.google_identity.refresh_after = NOW
        db.commit()
    sent = []
    dispatch_pending_locations(session_factory=sessions, publish=sent.append, now=NOW)
    with sessions() as db:
        assert db.get(DreamLocation, job).matcher_retry_version == 0
    assert sent == [job]


def test_ordinary_selected_id_refresh_still_runs_after_version_rollback(sessions, monkeypatch):
    job = terminal(sessions, status="resolved", version=2)
    with sessions() as db:
        db.add(DreamGoogleIdentity(location_id=job, selected_place_id="retained-id", refresh_after=NOW))
        db.commit()
    monkeypatch.setattr(locations, "MATCHER_VERSION", 1)
    sent = []
    result = dispatch_pending_locations(session_factory=sessions, publish=sent.append, now=NOW)
    assert result["queued"] == 1 and sent == [job]
    # A terminal unavailable-place response on the older image must identify
    # its actual executing version, so newer matching can recover it later.
    assert resolve(sessions, job) == "not_found"
    with sessions() as db:
        row = db.get(DreamLocation, job)
        assert row.matcher_version == 1 and row.matcher_retry_version == 0
        assert row.google_identity.selected_place_id is None
        assert any(entry.get("matcher_version") == 2 for entry in row.history)
    monkeypatch.setattr(locations, "MATCHER_VERSION", 2)
    assert upgrade(sessions)["queued"] == 1
