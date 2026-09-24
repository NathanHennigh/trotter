"""Durable location enrichment. Provider work never runs inside an item transaction."""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, unquote, urlencode, urlparse

from sqlalchemy import and_, or_, update
from sqlalchemy.orm import Session

from ..models import DreamItem, DreamLocation, User

IDENTITY_FIELDS = ("place_name", "city", "country", "region_or_neighborhood", "category")
ACTIVE = {"queued", "running"}


def utcnow():
    return datetime.now(timezone.utc)


def aware(value):
    return value.replace(tzinfo=timezone.utc) if value and value.tzinfo is None else value


def setting(name, default, maximum):
    try:
        return max(1, min(maximum, int(os.getenv(name, str(default)))))
    except ValueError:
        return default


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def fingerprint(item):
    return digest({field: " ".join(str(getattr(item, field) or "").casefold().split()) for field in IDENTITY_FIELDS})


def pin_fingerprint(item):
    raw = getattr(item, "raw_metadata_json", None)
    raw = raw if isinstance(raw, dict) else {}
    return digest([item.google_maps_url, item.google_place_id, raw.get("place_match")])


def checked_coordinates(lat, lon, precision="place"):
    if isinstance(lat, bool) or isinstance(lon, bool):
        return None, None, None
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        return None, None, None
    if not math.isfinite(lat) or not math.isfinite(lon) or abs(lat) > 85.05112878 or abs(lon) > 180:
        return None, None, None
    return lat, lon, precision


def explicit_pin(item):
    url = item.google_maps_url or ""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return None, None, None
    match = re.search(r"!3d(-?\d+(?:\.\d+)?)!4d(-?\d+(?:\.\d+)?)", unquote(url))
    query = parse_qs(parsed.query)
    value = (query.get("query") or query.get("q") or [""])[0]
    match = match or re.fullmatch(r"\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*", value)
    pin = checked_coordinates(match[1], match[2]) if match else (None, None, None)
    # Historical provider-created coordinate links are not manual user evidence.
    raw = getattr(item, "raw_metadata_json", None)
    raw = raw if isinstance(raw, dict) else {}
    evidence = (raw.get("place_match") or {}).get("raw") if isinstance(raw.get("place_match"), dict) else None
    location = evidence.get("location") if isinstance(evidence, dict) else None
    if isinstance(location, dict) and pin[:2] == checked_coordinates(location.get("latitude"), location.get("longitude"))[:2]:
        return None, None, None
    return pin


def legacy_coordinates(item):
    pin = explicit_pin(item)
    if pin[0] is not None:
        return pin
    raw = item.raw_metadata_json if isinstance(item.raw_metadata_json, dict) else {}
    match = raw.get("place_match")
    evidence = match.get("raw") if isinstance(match, dict) else None
    if not isinstance(evidence, dict):
        return None, None, None
    location = evidence.get("location")
    if isinstance(location, dict):
        # No trustworthy retrieval time exists for legacy Google content.
        return None, None, None
    properties, geometry = evidence.get("properties") or {}, evidence.get("geometry") or {}
    if not isinstance(properties, dict) or not isinstance(geometry, dict):
        return None, None, None
    kind = properties.get("result_type")
    if kind not in {"amenity", "building", "street", "suburb", "district", "neighbourhood"}:
        return None, None, None
    precision = "area" if kind in {"street", "suburb", "district", "neighbourhood"} else "place"
    coordinates = geometry.get("coordinates")
    if geometry.get("type") == "Point" and isinstance(coordinates, list) and len(coordinates) >= 2:
        return checked_coordinates(coordinates[1], coordinates[0], precision)
    return checked_coordinates(properties.get("lat"), properties.get("lon"), precision)


def current_resolution(item):
    row = getattr(item, "location", None)
    return row if row and row.user_id == item.user_id and row.fingerprint == fingerprint(item) and row.pin_fingerprint == pin_fingerprint(item) else None


def location_coordinates(item):
    manual = explicit_pin(item)
    if manual[0] is not None:
        return manual
    row = current_resolution(item)
    if row and row.provider == "google_places":
        from .google_location_lifecycle import cached_coordinates
        return cached_coordinates(row) if row.status in {"resolved", "manual", "queued", "running", "failed", "blocked"} else (None, None, None)
    if row and row.status in {"resolved", "manual"}:
        if row.provider == "saved_evidence":
            return legacy_coordinates(item)
        return checked_coordinates(row.latitude, row.longitude)
    return legacy_coordinates(item)


def public_location(item):
    row = current_resolution(item)
    result = {
        "location_status": row.status if row else "manual" if explicit_pin(item)[0] is not None else None,
        "location_address": row.address if row else None,
        "location_provider": row.provider if row else None,
        "location_candidates": row.candidates if row and row.status == "needs_review" else [],
        "location_message": row.message if row else None,
        "location_checked_at": row.checked_at if row else None,
    }
    if row and row.provider == "google_places":
        from .google_location_lifecycle import google_public_fields
        result.update(google_public_fields(row))
    return result


def location_maps_url(item):
    if explicit_pin(item)[0] is not None:
        return item.google_maps_url
    row = current_resolution(item)
    if row and row.provider == "google_places":
        from .google_location_lifecycle import place_maps_url
        identity = row.google_identity
        if identity and identity.selected_place_id:
            return place_maps_url(item, identity.selected_place_id)
    if row and row.status in {"resolved", "manual"} and row.google_maps_url:
        return row.google_maps_url
    raw = item.raw_metadata_json if isinstance(item.raw_metadata_json, dict) else {}
    match = raw.get("place_match")
    google_legacy = isinstance(match, dict) and isinstance(match.get("raw"), dict) and isinstance(match["raw"].get("location"), dict)
    if item.google_maps_url and not google_legacy:
        return item.google_maps_url
    if not (item.place_name or "").strip():
        return None
    query = " ".join(" ".join(str(value or "").split()) for value in (item.place_name, item.city, item.country) if str(value or "").strip())
    # A numeric-looking name is still a search, never evidence of an exact pin.
    if re.fullmatch(r"-?\d+(?:\.\d+)?\s*,\s*-?\d+(?:\.\d+)?", query):
        query = "place " + query
    return "https://www.google.com/maps/search/?" + urlencode({"api": "1", "query": query})


def archive_resolution(row, reason, now):
    entry = {
        "reason": reason, "at": now.isoformat(), "fingerprint": row.fingerprint,
        "generation": row.generation, "status": row.status, "provider": row.provider,
        "address": row.address, "latitude": row.latitude, "longitude": row.longitude,
        "google_maps_url": row.google_maps_url, "candidates": row.candidates,
    }
    if row.provider == "google_places":
        from .google_location_lifecycle import ids_history
        entry = {key: entry[key] for key in ("reason", "at", "fingerprint", "generation", "status", "provider")}
        entry.update(ids_history(row))
    row.history = [*(row.history or []), entry]


def enqueue_location(db: Session, item: DreamItem, *, force=False, supersede=False, now=None):
    """Call while holding the item's row lock; same transaction as a user edit."""
    now = now or utcnow()
    row = db.query(DreamLocation).filter_by(item_id=item.id, user_id=item.user_id).with_for_update().first()
    identity, pin = fingerprint(item), pin_fingerprint(item)
    changed = row is not None and (row.fingerprint != identity or row.pin_fingerprint != pin)
    from .dream_place_aliases import caption_for_place, source_place_aliases
    caption = caption_for_place(item)
    aliases = source_place_aliases(item.place_name, caption)
    source_identity = digest(caption)
    previous_source_identity = next((entry["source_evidence_fingerprint"] for entry in reversed(row.history or [])
                                     if "source_evidence_fingerprint" in entry), None) if row else None
    source_changed = bool(row and row.status not in {"resolved", "manual"} and source_identity != previous_source_identity)
    alias_identity = digest(aliases)
    raw = item.raw_metadata_json or {}
    previous_alias_identity = raw.get("location_alias_fingerprint")
    alias_changed = bool(row and row.status not in {"resolved", "manual"}
                         and (aliases or previous_alias_identity)
                         and alias_identity != previous_alias_identity)
    changed = changed or alias_changed or source_changed
    # This is derived only from the retained user caption, never Google data.
    # Adding/removing an alias retries unresolved saves without disturbing pins.
    if aliases or previous_alias_identity:
        item.raw_metadata_json = {**raw, "location_alias_fingerprint": alias_identity}
    google = row.google_identity if row and row.provider == "google_places" else None
    google_expired = bool(google and google.selected_place_id and (not google.coordinates_expires_at or aware(google.coordinates_expires_at) <= now))
    from .google_location_lifecycle import source_place_fingerprint
    preserve_google_choice = bool(google and google.confirmed_place_id and row.pin_fingerprint == pin
                                  and google.place_fingerprint == source_place_fingerprint(item))
    if row and not changed and not force and not google_expired:
        return row, False
    if row and not changed and force and not supersede and row.status in ACTIVE | {"manual", "resolved"} and not google_expired:
        return row, False
    if row:
        if source_changed:
            row.history = [*(row.history or []), {"reason": "source_lookup_context", "at": now.isoformat(),
                           "source_evidence_fingerprint": source_identity}]
        archive_resolution(row, "location_inputs_changed" if changed else "requested_retry", now)
        row.generation += 1
    else:
        row = DreamLocation(item_id=item.id, user_id=item.user_id, fingerprint=identity,
                            pin_fingerprint=pin, generation=1, created_at=now)
        db.add(row)
        item.location = row
        row.history = [{"reason": "source_lookup_context", "at": now.isoformat(), "source_evidence_fingerprint": source_identity}]
    row.fingerprint, row.pin_fingerprint = identity, pin
    row.attempts, row.lease_token, row.lease_expires_at = 0, None, None
    row.provider, row.address, row.latitude, row.longitude, row.google_maps_url = None, None, None, None, None
    row.coordinate_precision = row.coordinate_precision if google and google.selected_place_id and (not changed or preserve_google_choice) else None
    row.candidates, row.message, row.checked_at, row.last_dispatched_at = [], None, None, None
    row.updated_at = now
    if google:
        if changed and not preserve_google_choice:
            google.selected_place_id = google.confirmed_place_id = None
            google.candidate_place_ids = []
        google.coordinates_expires_at = google.refresh_after = None
        row.provider = "google_places"
    saved = legacy_coordinates(item)
    if saved[0] is not None:
        row.status = "manual" if explicit_pin(item)[0] is not None else "resolved"
        row.latitude, row.longitude = saved[:2]
        row.provider = "manual" if row.status == "manual" else "saved_evidence"
        row.google_maps_url, row.checked_at, row.next_attempt_at = item.google_maps_url, now, None
        row.message = "Your saved pin is preserved."
    elif not (item.place_name or "").strip() and not area_name_for_item(item):
        row.status, row.next_attempt_at = "not_found", None
        row.message = "Add a place name to find its location."
    else:
        row.status, row.next_attempt_at = "queued", now
        row.message = "Finding this place in the background."
    db.flush()
    return row, row.status == "queued"


def area_name_for_item(item):
    from .dream_location_lookup import area_search_name
    from .dream_place_aliases import caption_for_place
    return area_search_name(item.place_name, item.city, item.region_or_neighborhood, item.category, caption_for_place(item))


def queue_missing(db: Session, *, user_id=None, limit=100, only_undiscovered=False, after_id=0, now=None):
    query = db.query(DreamItem).filter(or_(
        and_(DreamItem.place_name.isnot(None), DreamItem.place_name != ""),
        and_(or_(DreamItem.category.is_(None), DreamItem.category.in_(["", "unknown", "nature", "attraction"])),
             or_(DreamItem.city.isnot(None), DreamItem.region_or_neighborhood.isnot(None))),
    ), DreamItem.id > after_id)
    if user_id is not None:
        query = query.filter(DreamItem.user_id == user_id)
    if only_undiscovered:
        query = query.outerjoin(DreamLocation, DreamLocation.item_id == DreamItem.id).filter(DreamLocation.id.is_(None))
    # Lock by stable item order, matching review and worker commit lock order.
    items = query.order_by(DreamItem.id).limit(limit).with_for_update(of=DreamItem, skip_locked=True).all()
    queued = 0
    for item in items:
        _, added = enqueue_location(db, item, now=now)
        queued += added
    return {"queued": queued, "checked": len(items), "last_id": items[-1].id if items else after_id}


def claim_job(db: Session, job_id: int, *, now=None):
    now = now or utcnow()
    row = db.get(DreamLocation, job_id)
    if not row:
        return None
    item = db.query(DreamItem).filter_by(id=row.item_id, user_id=row.user_id).with_for_update().first()
    if not item:
        return None
    db.refresh(row)
    if row.fingerprint != fingerprint(item) or row.pin_fingerprint != pin_fingerprint(item):
        enqueue_location(db, item, now=now)
        return None
    if legacy_coordinates(item)[0] is not None:
        return None
    due = row.status in {"queued", "blocked"} and (row.next_attempt_at is not None and aware(row.next_attempt_at) <= now)
    abandoned = row.status == "running" and row.lease_expires_at and aware(row.lease_expires_at) <= now
    if not due and not abandoned:
        return None
    if row.attempts >= setting("DREAM_LOCATION_MAX_ATTEMPTS", 5, 10):
        row.status, row.next_attempt_at, row.lease_token = "failed", None, None
        row.message = "Location lookup could not finish. You can retry."
        return None
    token = str(uuid.uuid4())
    changed = db.execute(update(DreamLocation).where(
        DreamLocation.id == row.id, DreamLocation.generation == row.generation,
        DreamLocation.status == row.status,
        DreamLocation.lease_token == row.lease_token if row.lease_token else DreamLocation.lease_token.is_(None),
    ).values(status="running", lease_token=token, lease_expires_at=now + timedelta(seconds=120),
             attempts=row.attempts + 1, updated_at=now), execution_options={"synchronize_session": False}).rowcount
    if not changed:
        return None
    from .dream_place_aliases import caption_for_place
    return {"job_id": row.id, "item_id": item.id, "user_id": item.user_id, "token": token,
            "fingerprint": row.fingerprint, "pin_fingerprint": row.pin_fingerprint,
            "inputs": [item.place_name, item.city, item.country, item.region_or_neighborhood, item.category],
            "source_caption": caption_for_place(item),
            "protected_fields": bool(item.status == "confirmed" or (item.raw_metadata_json or {}).get("dream_user_edited")),
            "coordinate_precision": row.coordinate_precision,
            "google_place_id": row.google_identity.selected_place_id if row.provider == "google_places" and row.google_identity else None}


def apply_candidate(row, candidate):
    row.address = candidate.get("address")
    row.latitude, row.longitude = candidate["latitude"], candidate["longitude"]
    row.google_maps_url, row.provider = candidate["google_maps_url"], candidate.get("provider", "geoapify")


async def resolve_location_job(job_id, *, session_factory=None, resolver=None, now=None):
    from ..db import SessionLocal
    from .dream_place_search import RetryableDreamPlaceLookupError
    from .google_dream_place_search import search_google_dream_place, fetch_google_place_details, GooglePlacesBlockedError
    session_factory, resolver = session_factory or SessionLocal, resolver or search_google_dream_place
    with session_factory() as db:
        claim = claim_job(db, job_id, now=now)
        db.commit()
    if not claim:
        return "skipped"
    retryable = False
    try:
        if claim.get("google_place_id") and resolver is search_google_dream_place:
            refreshed = await fetch_google_place_details(claim["google_place_id"], allow_area=claim.get("coordinate_precision") == "area")
            result = {"status": "resolved" if refreshed else "not_found", "provider": "google_places", "candidates": [refreshed.model_dump()] if refreshed else []}
        elif resolver is search_google_dream_place:
            from .dream_location_lookup import lookup_dream_location
            result = await lookup_dream_location(*claim["inputs"], source_caption=claim.get("source_caption"),
                                                protected=claim.get("protected_fields", False))
        else:
            result = await resolver(*claim["inputs"])
        result = result.model_dump() if hasattr(result, "model_dump") else result
        if result.get("status") not in {"resolved", "needs_review", "not_found", "blocked"}:
            raise ValueError("Invalid provider status")
        candidates = result.get("candidates", [])
        result["provider"] = result.get("provider") or (candidates[0].get("provider") if candidates else None) or "google_places"
        if not isinstance(candidates, list) or len(candidates) > 10:
            raise ValueError("Invalid candidate list")
        for candidate in candidates:
            if not candidate.get("id") or not candidate.get("name") or checked_coordinates(candidate.get("latitude"), candidate.get("longitude"))[0] is None:
                raise ValueError("Invalid location candidate")
            # Links are derived from validated coordinates, never provider-supplied arbitrary URLs.
            candidate["google_maps_url"] = f"https://www.google.com/maps/search/?api=1&query={candidate['latitude']},{candidate['longitude']}"
        # Older providers/workers returned usable Google matches for approval.
        # A background match now populates the map directly; it is still an
        # automatic result, never evidence that the user confirmed a place.
        if result["provider"] == "google_places" and result["status"] == "needs_review":
            result["status"] = "resolved" if candidates else "not_found"
            candidates = result["candidates"] = candidates[:1]
        if result["status"] == "resolved" and len(candidates) != 1:
            raise ValueError("Resolved location requires one candidate")
    except RetryableDreamPlaceLookupError:
        retryable, result = True, None
    except GooglePlacesBlockedError:
        result = {"status": "blocked", "provider": "google_places", "candidates": []}
    except Exception:
        # Do not persist exception URLs, credentials, request headers or payloads.
        retryable, result = True, None
    finished = now or utcnow()
    with session_factory() as db:
        db.query(User).filter_by(id=claim["user_id"]).with_for_update().first()
        item = db.query(DreamItem).filter_by(id=claim["item_id"], user_id=claim["user_id"]).with_for_update().first()
        row = db.query(DreamLocation).filter_by(id=job_id, user_id=claim["user_id"]).with_for_update().first()
        if not item or not row or row.lease_token != claim["token"]:
            return "superseded"
        from .dream_place_aliases import caption_for_place, source_place_aliases
        alias_changed = source_place_aliases(item.place_name, caption_for_place(item)) != source_place_aliases(
            claim["inputs"][0], claim.get("source_caption"))
        caption_changed = caption_for_place(item) != claim.get("source_caption")
        protection_changed = bool(item.status == "confirmed" or (item.raw_metadata_json or {}).get("dream_user_edited")) != claim.get("protected_fields", False)
        if fingerprint(item) != claim["fingerprint"] or pin_fingerprint(item) != claim["pin_fingerprint"] or alias_changed or caption_changed or protection_changed:
            enqueue_location(db, item, force=alias_changed or caption_changed or protection_changed, supersede=True, now=finished)
            db.commit()
            return "superseded"
        row.lease_token, row.lease_expires_at = None, None
        row.updated_at, row.checked_at = finished, finished
        row.next_attempt_at = None
        if retryable:
            if row.attempts < setting("DREAM_LOCATION_MAX_ATTEMPTS", 5, 10):
                row.status, row.next_attempt_at = "queued", finished + timedelta(seconds=min(3600, 60 * 2 ** (row.attempts - 1)))
                row.message = "The location service is temporarily unavailable. We will retry."
            else:
                row.status, row.message = "failed", "Location lookup could not finish. You can retry."
        else:
            research = result.get("_research") if result.get("provider") == "google_places" else None
            if research and not claim.get("protected_fields"):
                # Only original source evidence and query inputs, never Google
                # result content, enter the durable audit trail.
                row.history = [*(row.history or []), {"reason": "source_location_research", "at": finished.isoformat(),
                               "queries": research["queries"], "matched": bool(research.get("matched"))}]
                if result["status"] == "resolved" and research.get("matched"):
                    apply_researched_context(db, item, row, research["matched"], finished)
            row.status = result["status"]
            row.candidates = result.get("candidates", []) if result["provider"] != "google_places" else []
            row.provider = result["provider"]
            row.message = {
                "resolved": "Location found.", "needs_review": "Choose the place that matches your save.",
                "not_found": "No reliable match yet. Check the place name or add a pin.",
                "blocked": "Location lookup is temporarily unavailable.",
            }.get(row.status, "Location lookup could not finish. You can retry.")
            if row.status == "needs_review" and not result.get("candidates"):
                row.message = "Add a more specific place name, city, or country to find its location."
            if row.provider == "google_places":
                from .google_location_lifecycle import apply_google_result
                try:
                    apply_google_result(db, row, result, finished)
                except Exception:
                    row.status = "queued" if row.attempts < setting("DREAM_LOCATION_MAX_ATTEMPTS", 5, 10) else "failed"
                    row.next_attempt_at = finished + timedelta(minutes=1) if row.status == "queued" else None
                    row.message = "The location cache is temporarily unavailable. We will retry."
            elif row.status == "resolved" and len(row.candidates) == 1:
                apply_candidate(row, row.candidates[0])
            if row.status == "blocked":
                row.next_attempt_at = finished + timedelta(hours=6)
                row.attempts = 0
        db.commit()
        return row.status


def apply_researched_context(db, item, row, plan, now):
    """Correct only derived geographic hints after a source-backed match."""
    changes = {}
    for field in ("city", "country", "region_or_neighborhood"):
        old, new = getattr(item, field), plan[field]
        evidence = plan.get("evidence", {}).get(field, {})
        if old != new and evidence.get("source") in {"caption", "removed"}:
            changes[field] = {"before": old, "after": new, "evidence": evidence}
            setattr(item, field, new)
    if not changes:
        return
    raw = item.raw_metadata_json or {}
    item.raw_metadata_json = {**raw, "dream_location_repairs": [*(raw.get("dream_location_repairs") or []),
                              {"at": now.isoformat(), "changes": changes}]}
    from ..routers.dreams import dream_group_location, get_or_create_dream
    city, country, region = dream_group_location(item.city, item.country, item.region_or_neighborhood)
    item.dream_id = get_or_create_dream(db, item.user_id, city, country, region).id
    row.fingerprint, row.pin_fingerprint = fingerprint(item), pin_fingerprint(item)


def confirm_candidate(db: Session, item: DreamItem, candidate_id: str):
    row = db.query(DreamLocation).filter_by(item_id=item.id, user_id=item.user_id).with_for_update().first()
    if not row or row.status != "needs_review" or row.fingerprint != fingerprint(item) or row.pin_fingerprint != pin_fingerprint(item):
        raise ValueError("This location choice is no longer current. Find the place again.")
    if row.provider == "google_places":
        raise ValueError("Google choices require fresh place details before confirmation.")
    candidate = next((candidate for candidate in row.candidates if candidate.get("id") == candidate_id), None)
    if not candidate:
        raise ValueError("This location choice does not belong to this saved place.")
    archive_resolution(row, "user_confirmed_candidate", utcnow())
    apply_candidate(row, candidate)
    row.status, row.message, row.next_attempt_at = "manual", "Location confirmed by you.", None
    row.lease_token, row.lease_expires_at = None, None
    row.updated_at = row.checked_at = utcnow()
    return row


def due_jobs(db: Session, *, now=None, limit=100):
    now = now or utcnow()
    return db.query(DreamLocation).filter(or_(
        DreamLocation.status.in_(["queued", "blocked"]) & (DreamLocation.next_attempt_at <= now),
        (DreamLocation.status == "running") & (DreamLocation.lease_expires_at <= now),
    )).filter(or_(DreamLocation.last_dispatched_at.is_(None), DreamLocation.last_dispatched_at <= now - timedelta(seconds=60))).order_by(DreamLocation.id).limit(limit).all()
