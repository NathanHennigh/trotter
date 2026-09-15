"""IDs are durable; only coordinates are cached, with a strict 29-day Redis TTL.

Google display names, addresses and attribution are obtained on demand, returned
with no-store, and never written to ORM rows, history, logs or Redis.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from functools import lru_cache
from datetime import timedelta
from urllib.parse import urlencode

from redis import Redis
from ..models import DreamGoogleIdentity, DreamItem, DreamLocation

PROVIDER = "google_places"
CACHE_SECONDS = 29 * 24 * 60 * 60
_cache_outage_until = 0.0


def source_place_fingerprint(item):
    from .dream_locations import digest
    return digest({field: " ".join(str(getattr(item, field) or "").casefold().split())
                   for field in ("place_name", "city", "country", "region_or_neighborhood")})


@lru_cache(maxsize=2)
def _pooled_cache_client(url):
    return Redis.from_url(url, socket_connect_timeout=0.3, socket_timeout=0.3,
                          retry_on_timeout=False, decode_responses=True, max_connections=20)


def cache_client():
    url = os.getenv("GOOGLE_PLACES_CACHE_URL", "").strip()
    if not url:
        raise RuntimeError("A nonpersistent Google coordinates cache is not configured.")
    return _pooled_cache_client(url)


def coordinate_key(row, place_id):
    from .dream_locations import digest
    return "dream-google-coordinates:" + digest([row.user_id, row.id, row.generation, place_id])


def cache_coordinates(row, candidate, now):
    from .dream_locations import checked_coordinates
    coordinates = checked_coordinates(candidate.get("latitude"), candidate.get("longitude"))
    if coordinates[0] is None:
        raise ValueError("Invalid place coordinates")
    expires = now + timedelta(seconds=CACHE_SECONDS)
    # Strict allowlist: no names, addresses, URLs, attribution, types or raw data.
    payload = {"latitude": coordinates[0], "longitude": coordinates[1], "expires_at": expires.isoformat()}
    cache_client().set(coordinate_key(row, candidate["id"]), json.dumps(payload), ex=CACHE_SECONDS)
    return expires


def cached_coordinates(row, *, now=None):
    global _cache_outage_until
    from .dream_locations import aware, checked_coordinates, utcnow
    from datetime import datetime
    now = now or utcnow()
    identity = getattr(row, "google_identity", None)
    if not identity or not identity.selected_place_id or not identity.coordinates_expires_at or aware(identity.coordinates_expires_at) <= now:
        return None, None, None
    if time.monotonic() < _cache_outage_until:
        return None, None, None
    try:
        encoded = cache_client().get(coordinate_key(row, identity.selected_place_id))
    except Exception:
        _cache_outage_until = time.monotonic() + 5
        return None, None, None
    try:
        payload = json.loads(encoded or "null")
        if not isinstance(payload, dict) or aware(datetime.fromisoformat(payload["expires_at"])) <= now:
            return None, None, None
        return checked_coordinates(payload.get("latitude"), payload.get("longitude"))
    except Exception:
        # Redis failures, missing/expired keys and malformed values never leak old pins.
        return None, None, None


def ensure_identity(db, row):
    identity = getattr(row, "google_identity", None)
    if identity is None:
        identity = DreamGoogleIdentity(location_id=row.id, candidate_place_ids=[])
        db.add(identity)
        row.google_identity = identity
    return identity


def ids_history(row):
    identity = getattr(row, "google_identity", None)
    return {"selected_place_id": identity.selected_place_id if identity else None,
            "confirmed_place_id": identity.confirmed_place_id if identity else None,
            "candidate_place_ids": list(identity.candidate_place_ids or []) if identity else []}


def clear_google_payload(row):
    row.address = row.latitude = row.longitude = row.google_maps_url = None
    row.candidates = []


def apply_google_result(db, row, result, now):
    identity = ensure_identity(db, row)
    identity.place_fingerprint = source_place_fingerprint(row.item)
    candidates = result.get("candidates", [])
    clear_google_payload(row)
    row.provider = PROVIDER
    if result["status"] == "blocked":
        return
    identity.candidate_place_ids = list(dict.fromkeys(candidate["id"] for candidate in candidates))[:5]
    identity.coordinates_expires_at = None
    identity.refresh_after = None
    if result["status"] == "resolved" and len(candidates) == 1:
        candidate = candidates[0]
        if identity.confirmed_place_id and candidate["id"] != identity.confirmed_place_id:
            raise ValueError("A confirmed place cannot be rebound")
        identity.selected_place_id = candidate["id"]
        identity.coordinates_expires_at = cache_coordinates(row, candidate, now)
        identity.refresh_after = now + timedelta(minutes=5)
        if identity.confirmed_place_id:
            row.status = "manual"
            row.message = "Location confirmed by you."
        else:
            row.status = "resolved"
            row.message = "Location found on Google Maps."
    elif not identity.confirmed_place_id:
        identity.selected_place_id = None


def google_public_fields(row):
    from .dream_locations import aware, utcnow
    identity = getattr(row, "google_identity", None)
    expires = identity.coordinates_expires_at if identity else None
    expired = bool(identity and identity.selected_place_id and (not expires or aware(expires) <= utcnow()))
    return {
        "location_place_id": identity.selected_place_id if identity else None,
        "location_candidate_ids": list(identity.candidate_place_ids or []) if identity else [],
        "location_expires_at": expires,
        "location_user_confirmed": bool(identity and identity.confirmed_place_id),
        "location_address": None, "location_candidates": [],
        "location_status": "queued" if expired and row.status in {"resolved", "manual"} else row.status,
        "location_message": "Refreshing this place's map location." if expired and row.status in {"resolved", "manual"} else row.message,
    }


def place_maps_url(item, place_id):
    # A display query is never a coordinate fallback, including for old clients.
    return "https://www.google.com/maps/search/?" + urlencode({"api": "1", "query": "place " + (item.place_name or ""), "query_place_id": place_id})


def queue_pending_google_matches(db, *, now, limit):
    """Resume old approval-gated saves using fresh provider evidence.

    No cached display payload is promoted. The ordinary durable worker searches
    current item inputs, validates Google results and caches fresh coordinates.
    A result leaves needs_review permanently, so this is bounded and idempotent
    across dispatcher ticks without a schema or destructive data migration.
    """
    from .dream_locations import enqueue_location
    items = db.query(DreamItem).join(
        DreamLocation,
        (DreamLocation.item_id == DreamItem.id) & (DreamLocation.user_id == DreamItem.user_id),
    ).join(DreamGoogleIdentity).filter(
        DreamLocation.provider == PROVIDER,
        DreamLocation.status == "needs_review",
        DreamGoogleIdentity.confirmed_place_id.is_(None),
    ).order_by(DreamItem.id).limit(limit).with_for_update(of=DreamItem, skip_locked=True).populate_existing().all()
    queued = 0
    for item in items:
        # enqueue_location also locks/rechecks the row and preserves a newer
        # manual pin if the item was edited while this batch was being selected.
        row = db.query(DreamLocation).filter_by(item_id=item.id, user_id=item.user_id).with_for_update().populate_existing().first()
        if not row or row.status != "needs_review" or row.provider != PROVIDER:
            continue
        if row.google_identity and row.google_identity.confirmed_place_id:
            continue
        _, added = enqueue_location(db, item, force=True, now=now)
        queued += added
    return queued


def queue_google_refreshes(db, *, now, limit):
    from .dream_locations import archive_resolution, explicit_pin
    rows = db.query(DreamLocation).join(DreamGoogleIdentity).filter(
        DreamGoogleIdentity.refresh_after <= now,
        DreamLocation.status.in_(["resolved", "manual"]),
    ).order_by(DreamLocation.id).limit(limit).all()
    queued = 0
    for row in rows:
        item = db.query(DreamItem).filter_by(id=row.item_id, user_id=row.user_id).with_for_update().first()
        if not item or explicit_pin(item)[0] is not None:
            continue
        db.refresh(row)
        if row.status not in {"resolved", "manual"}:
            continue
        from .dream_locations import aware
        if row.google_identity.coordinates_expires_at and aware(row.google_identity.coordinates_expires_at) > now + timedelta(days=1) and cached_coordinates(row, now=now)[0] is not None:
            row.google_identity.refresh_after = now + timedelta(minutes=5)
            continue
        archive_resolution(row, "google_coordinate_refresh", now)
        row.status, row.next_attempt_at, row.attempts = "queued", now, 0
        row.lease_token = row.lease_expires_at = row.last_dispatched_at = None
        row.google_identity.refresh_after = None
        queued += 1
    return queued


def google_snapshot(db, item_id, user_id):
    from .dream_locations import current_resolution
    item = db.query(DreamItem).filter_by(id=item_id, user_id=user_id).first()
    if not item:
        raise LookupError("Saved place not found")
    row = current_resolution(item)
    if not row or row.provider != PROVIDER or not row.google_identity:
        return item, row, []
    identity = row.google_identity
    ids = [identity.selected_place_id] if row.status in {"resolved", "manual"} and identity.selected_place_id else list(identity.candidate_place_ids or [])[:5]
    return item, row, ids


async def live_google_details(db, item_id, user_id, *, fetcher=None):
    from .google_dream_place_search import fetch_google_place_details, GooglePlacesBlockedError
    from .dream_place_search import RetryableDreamPlaceLookupError
    from .dream_locations import fingerprint, pin_fingerprint, utcnow
    item, row, ids = google_snapshot(db, item_id, user_id)
    expected = (fingerprint(item), pin_fingerprint(item), row.generation if row else None)
    status = row.status if row else None
    selected = row.google_identity.selected_place_id if row and row.google_identity else None
    db.rollback()  # No provider call while holding database locks or a transaction.
    candidates, message = [], None
    try:
        async with asyncio.timeout(18):
            for identity in ids:
                candidate = await (fetcher or fetch_google_place_details)(identity)
                if candidate is not None:
                    candidate = candidate.model_dump() if hasattr(candidate, "model_dump") else candidate
                    if candidate.get("id") == identity:
                        candidates.append(candidate)
    except (GooglePlacesBlockedError, RetryableDreamPlaceLookupError, TimeoutError):
        raise RetryableDreamPlaceLookupError("Place details are temporarily unavailable. You can retry.") from None
    item, row, current_ids = google_snapshot(db, item_id, user_id)
    if expected != (fingerprint(item), pin_fingerprint(item), row.generation if row else None) or ids != current_ids:
        raise ValueError("This place changed. Open its details again.")
    status = row.status if row else None
    selected = row.google_identity.selected_place_id if row and row.google_identity else None
    address = next((candidate.get("address") for candidate in candidates if candidate["id"] == selected), None)
    attributions = [entry for candidate in candidates for entry in candidate.get("attributions", [])]
    return {"location_provider": PROVIDER, "location_place_id": selected, "location_status": status,
            "location_address": address, "location_candidates": candidates,
            "location_expires_at": utcnow() + timedelta(seconds=CACHE_SECONDS) if candidates else None,
            "location_attributions": attributions, "location_message": message}


async def confirm_google_candidate(db, item_id, user_id, candidate_id, *, fetcher=None):
    from .google_dream_place_search import fetch_google_place_details
    from .dream_locations import archive_resolution, fingerprint, pin_fingerprint, utcnow
    item, row, ids = google_snapshot(db, item_id, user_id)
    if not row or row.status != "needs_review" or candidate_id not in ids:
        raise ValueError("This location choice is no longer current.")
    expected = (row.generation, fingerprint(item), pin_fingerprint(item))
    db.rollback()
    candidate = await (fetcher or fetch_google_place_details)(candidate_id)
    if candidate is None:
        raise ValueError("This location is no longer available. Find the place again.")
    candidate = candidate.model_dump() if hasattr(candidate, "model_dump") else candidate
    if candidate.get("id") != candidate_id:
        raise ValueError("The location identity changed. Find the place again.")
    item = db.query(DreamItem).filter_by(id=item_id, user_id=user_id).with_for_update().first()
    if not item:
        raise LookupError("Saved place not found")
    row = db.query(DreamLocation).filter_by(item_id=item_id, user_id=user_id).with_for_update().first()
    if not row or row.status != "needs_review" or expected != (row.generation, fingerprint(item), pin_fingerprint(item)) or candidate_id not in row.google_identity.candidate_place_ids:
        raise ValueError("This location choice is no longer current.")
    now = utcnow()
    archive_resolution(row, "user_confirmed_google_place_id", now)
    row.google_identity.confirmed_place_id = candidate_id
    row.status = "manual"
    try:
        apply_google_result(db, row, {"status": "resolved", "candidates": [candidate]}, now)
    except Exception:
        from .dream_place_search import RetryableDreamPlaceLookupError
        raise RetryableDreamPlaceLookupError("The location cache is temporarily unavailable.") from None
    row.lease_token = row.lease_expires_at = row.next_attempt_at = None
    row.updated_at = row.checked_at = now
    return item
