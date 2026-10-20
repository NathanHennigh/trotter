"""Public source context and retry contracts; no external provider calls."""
from datetime import datetime, timedelta, timezone

import pytest

from app.models import DreamItem, DreamLocation
from app.routers.dreams import dream_item_out
from app.services.dream_enrichment import enqueue_enrichment
from app.services.dream_locations import fingerprint, pin_fingerprint
from test_dream_locations import sessions, add_item


NOW = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)


@pytest.mark.parametrize("caption,name,state,reason", [
    ("A hidden Airbnb in Morocco. Comment LINK for the address.", None, "source_details", "creator_link_required"),
    ("A beautiful stay in Morocco.", None, "source_details", "identity_not_shared"),
    ("My Morocco itinerary for a week.", None, "source_details", "broad_guide"),
    ("Serenya in Morocco.", "Serenya", "unresolved", "named_unresolved"),
])
def test_country_is_preserved_without_misleading_errors(sessions, caption, name, state, reason):
    add_item(sessions, caption=caption, place_name=name, country="Morocco", city=None,
             category="hotel", status="parsed")
    with sessions() as db:
        item = db.get(DreamItem, 1)
        before = (item.country, item.caption, item.summary, item.raw_metadata_json.copy())
        output = dream_item_out(item)
        assert (output.location_state, output.location_reason) == (state, reason)
        assert output.country == "Morocco" and output.sorting_state == "sorted"
        assert output.latitude is None and output.longitude is None
        assert output.processing_retry_at is None and output.location_retry_at is None
        assert before == (item.country, item.caption, item.summary, item.raw_metadata_json)
        assert not db.dirty


def test_enrichment_retry_exposes_only_current_future_schedule(sessions, monkeypatch):
    monkeypatch.setattr("app.services.dream_locations.utcnow", lambda: NOW)
    add_item(sessions, status="parsed")
    with sessions() as db:
        item = db.get(DreamItem, 1)
        row, _ = enqueue_enrichment(db, item, now=NOW)
        row.next_attempt_at = NOW + timedelta(minutes=15)
        item.raw_metadata_json = {**item.raw_metadata_json, "dream_enrichment_recovery": {
            "generation": row.generation, "reason": "billing", "cycle": 1,
            "state": "waiting", "retry_at": row.next_attempt_at.isoformat(),
        }}
        output = dream_item_out(item)
        assert output.processing_retry_at == row.next_attempt_at
        assert output.location_reason == "provider_unavailable"
        assert output.location_state == "unavailable"
        assert output.country == "Spain"
        # Once the worker takes over, overdue/old metadata must not promise
        # another scheduled retry. It is active processing again.
        row.next_attempt_at = NOW - timedelta(seconds=1)
        output = dream_item_out(item)
        assert output.processing_retry_at is None
        assert output.location_state == "processing"
        row.next_attempt_at = NOW + timedelta(minutes=15)
        row.generation += 1
        assert dream_item_out(item).processing_retry_at is None
        row.generation -= 1
        item.raw_metadata_json = {**item.raw_metadata_json, "dream_user_edited": True}
        assert dream_item_out(item).processing_retry_at is None


def test_location_schedule_does_not_leak_into_manual_or_new_generation(sessions, monkeypatch):
    monkeypatch.setattr("app.services.dream_locations.utcnow", lambda: NOW)
    add_item(sessions, status="parsed")
    with sessions() as db:
        item = db.get(DreamItem, 1)
        row = DreamLocation(item_id=item.id, user_id=item.user_id, fingerprint=fingerprint(item), pin_fingerprint=pin_fingerprint(item),
                            generation=1, status="blocked", next_attempt_at=NOW + timedelta(hours=1),
                            history=[{"reason": "provider_recovery", "failure_kind": "rate_limited",
                                      "generation": 1, "cycle": 2, "state": "waiting"}])
        item.location = row
        db.add(row)
        db.flush()
        output = dream_item_out(item)
        assert output.location_retry_at == row.next_attempt_at
        assert output.location_state == "unavailable" and "automatically" in output.location_hint
        item.place_name = "Changed by the user"
        assert dream_item_out(item).location_retry_at is None
        item.place_name = "Garden Cafe"
        row.generation += 1
        assert dream_item_out(item).location_retry_at is None
        row.generation -= 1
        row.status = "manual"
        row.latitude, row.longitude, row.coordinate_precision = 40.4, -3.7, "place"
        output = dream_item_out(item)
        assert output.location_retry_at is None
        assert output.location_state == "place"


def test_fast_retry_is_not_a_deferred_provider_outage(sessions, monkeypatch):
    monkeypatch.setattr("app.services.dream_locations.utcnow", lambda: NOW)
    add_item(sessions, status="parsed")
    with sessions() as db:
        item = db.get(DreamItem, 1)
        row, _ = enqueue_enrichment(db, item, now=NOW)
        row.next_attempt_at = NOW + timedelta(seconds=60)
        output = dream_item_out(item)
        assert output.processing_retry_at is None
        assert output.location_state == "processing"
