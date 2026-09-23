"""Durable Dreams sorting with short DB transactions and bounded recovery."""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import timedelta

from sqlalchemy import and_, or_, update
from sqlalchemy.orm import Session

from ..models import DreamEnrichmentJob, DreamItem, User
from .dream_locations import aware, enqueue_location, explicit_pin, setting, utcnow

ACTIVE = {"queued", "running"}
LEASE_SECONDS = 300
FAILURE_MESSAGE = "We could not read this save yet. You can retry or add its details."
PROTECTED_FIELDS = (
    "source_url", "source_platform", "caption", "dream_id", "category", "place_name", "city",
    "country", "region_or_neighborhood", "summary", "tags_json", "confidence", "needs_review",
    "needs_google_places_lookup", "google_place_id", "google_maps_url",
)


def fingerprint(item):
    values = {name: getattr(item, name) for name in PROTECTED_FIELDS}
    values["shared_text"] = (item.raw_metadata_json or {}).get("shared_text")
    values["user_edited"] = (item.raw_metadata_json or {}).get("dream_user_edited")
    return hashlib.sha256(json.dumps(values, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def enqueue_enrichment(db: Session, item: DreamItem, *, force=False, now=None):
    """Caller holds the item lock. The job and processing state commit together."""
    now = now or utcnow()
    has_chosen_location = bool(item.location and (
        item.location.status == "manual" or (item.location.google_identity and item.location.google_identity.confirmed_place_id)))
    if item.status == "confirmed" or (item.raw_metadata_json or {}).get("dream_user_edited") or has_chosen_location or explicit_pin(item)[0] is not None:
        cancel_enrichment(db, item, now=now)
        return None, False
    row = db.query(DreamEnrichmentJob).filter_by(item_id=item.id, user_id=item.user_id).with_for_update().first()
    identity = fingerprint(item)
    if row and row.fingerprint == identity and (row.status in ACTIVE or not force):
        return row, False
    if not row:
        row = DreamEnrichmentJob(item_id=item.id, user_id=item.user_id, generation=0, created_at=now)
        db.add(row)
        item.enrichment = row
    row.generation += 1
    row.fingerprint, row.status, row.attempts = identity, "queued", 0
    row.lease_token = row.lease_expires_at = row.last_dispatched_at = None
    row.next_attempt_at = row.updated_at = now
    row.message = "Sorting this save in the background."
    item.status = "processing"
    item.updated_at = now
    db.flush()
    return row, True


def cancel_enrichment(db: Session, item: DreamItem, *, user_edited=False, now=None):
    now = now or utcnow()
    if user_edited:
        item.raw_metadata_json = {**(item.raw_metadata_json or {}), "dream_user_edited": True}
    row = db.query(DreamEnrichmentJob).filter_by(item_id=item.id, user_id=item.user_id).with_for_update().first()
    if row and row.status in ACTIVE:
        row.generation += 1
        row.status, row.message = "cancelled", "Your edits are saved."
        row.next_attempt_at = row.lease_token = row.lease_expires_at = None
        row.updated_at = now
    if item.status == "processing":
        item.status = "needs_review" if item.needs_review else "parsed"


def discover_enrichment(db: Session, *, limit=25, now=None):
    """One pass per legacy save, bounded by missing job rows. Never replay confirmed work."""
    now = now or utcnow()
    query = db.query(DreamItem).outerjoin(DreamEnrichmentJob, DreamEnrichmentJob.item_id == DreamItem.id).filter(
        DreamEnrichmentJob.id.is_(None),
        DreamItem.source_platform == "instagram",
        or_(
            DreamItem.status.in_(["processing", "created"]),
            and_(DreamItem.status.in_(["needs_review", "failed"]),
                 or_(DreamItem.place_name.is_(None), DreamItem.place_name == ""),
                 or_(DreamItem.city.is_(None), DreamItem.city == ""),
                 or_(DreamItem.country.is_(None), DreamItem.country == "")),
            # Earlier parsers sometimes kept a place while dropping an explicit
            # country, leaving an otherwise parsed save on an unsorted board.
            and_(DreamItem.status == "parsed",
                 or_(DreamItem.country.is_(None), DreamItem.country == "")),
        ),
    )
    # All reviewed items get a cancelled marker, so protected older rows cannot
    # starve discovery of later IDs across scheduler ticks.
    items = query.order_by(DreamItem.id).limit(limit).with_for_update(of=DreamItem, skip_locked=True).all()
    count = 0
    for item in items:
        row, added = enqueue_enrichment(db, item, now=now)
        if row is None:
            if item.status in {"created", "processing"}:
                item.status = "needs_review" if item.needs_review else "parsed"
            db.add(DreamEnrichmentJob(item_id=item.id, user_id=item.user_id, fingerprint=fingerprint(item),
                                      generation=1, status="cancelled", attempts=0, created_at=now,
                                      updated_at=now, message="Your edits are saved."))
        count += int(added)
    db.flush()
    return count


def due_enrichment_jobs(db: Session, *, now=None, limit=25):
    now = now or utcnow()
    return db.query(DreamEnrichmentJob).filter(or_(
        (DreamEnrichmentJob.status == "queued") & (DreamEnrichmentJob.next_attempt_at <= now),
        (DreamEnrichmentJob.status == "running") & (DreamEnrichmentJob.lease_expires_at <= now),
    )).filter(or_(DreamEnrichmentJob.last_dispatched_at.is_(None),
                  DreamEnrichmentJob.last_dispatched_at <= now - timedelta(seconds=30))).order_by(
        DreamEnrichmentJob.id).limit(limit).all()


def _finish_failed(item, row, now):
    row.status, row.message = "failed", FAILURE_MESSAGE
    row.next_attempt_at = row.lease_token = row.lease_expires_at = None
    row.updated_at = now
    item.status, item.needs_review, item.updated_at = "needs_review", True, now


def claim_enrichment(db: Session, job_id: int, *, now=None):
    now = now or utcnow()
    row = db.get(DreamEnrichmentJob, job_id)
    if not row:
        return None
    item = db.query(DreamItem).filter_by(id=row.item_id, user_id=row.user_id).with_for_update().first()
    if not item:
        return None
    db.refresh(row)
    if row.status not in ACTIVE:
        return None
    if item.status != "processing" or fingerprint(item) != row.fingerprint:
        cancel_enrichment(db, item, now=now)
        return None
    due = row.status == "queued" and row.next_attempt_at and aware(row.next_attempt_at) <= now
    expired = row.status == "running" and row.lease_expires_at and aware(row.lease_expires_at) <= now
    if not due and not expired:
        return None
    if row.attempts >= setting("DREAM_ENRICHMENT_MAX_ATTEMPTS", 3, 5):
        _finish_failed(item, row, now)
        return None
    token = str(uuid.uuid4())
    changed = db.execute(update(DreamEnrichmentJob).where(
        DreamEnrichmentJob.id == row.id, DreamEnrichmentJob.generation == row.generation,
        DreamEnrichmentJob.status == row.status,
        DreamEnrichmentJob.lease_token == row.lease_token if row.lease_token else DreamEnrichmentJob.lease_token.is_(None),
    ).values(status="running", lease_token=token, lease_expires_at=now + timedelta(seconds=LEASE_SECONDS),
             attempts=row.attempts + 1, updated_at=now), execution_options={"synchronize_session": False}).rowcount
    if not changed:
        return None
    return {"job_id": row.id, "item_id": item.id, "user_id": item.user_id,
            "generation": row.generation, "token": token, "fingerprint": row.fingerprint,
            "source_url": item.source_url, "caption": item.caption,
            "shared_text": (item.raw_metadata_json or {}).get("shared_text")}


class EnrichmentUnavailable(Exception):
    def __init__(self, caption=None, metadata=None):
        super().__init__(FAILURE_MESSAGE)
        self.caption, self.metadata = caption, metadata or {}


def read_source(claim):
    """Network work only: no Session, ORM object, or database connection crosses here."""
    from ..routers import dreams
    caption = dreams.usable_caption_text(claim["caption"]) or dreams.usable_caption_text(claim["shared_text"])
    metadata = {}
    try:
        caption, metadata = dreams.resolve_caption_for_parse(claim["source_url"], caption)
        parsed = dreams.parse_caption_with_fallback_model(caption, claim["source_url"])
    except Exception as exc:
        raise EnrichmentUnavailable(caption, metadata) from exc
    if metadata.get("thumbnail_url"):
        try:
            dreams.cache_thumbnail(claim["item_id"], metadata["thumbnail_url"])
        except Exception:
            pass  # Thumbnail reads may retry independently after the save is sorted.
    return {"caption": caption, "metadata": metadata, "parsed": parsed}


def _apply_result(db, item, result):
    from ..routers import dreams
    previous_caption = item.caption
    old_summary = item.summary
    generated_summaries = {item.source_url, "Saved from Instagram", "Saved Instagram link",
                           dreams.summarize(previous_caption or ""),
                           dreams.summarize((item.raw_metadata_json or {}).get("shared_text") or "")}
    old_tags = list(item.tags_json or [])
    item.caption = result["caption"] or item.caption
    parsed = result["parsed"]
    # A missing model field must not discard one explicit, uncontested country.
    # Never infer a city, resolve a multi-country caption, or replace AI evidence.
    caption = item.caption or ""
    named_countries = [country for country in dreams.KNOWN_COUNTRIES
                       if re.search(rf"\b{re.escape(country)}\b", caption, re.IGNORECASE)]
    if len(named_countries) == 1:
        country = named_countries[0]
        negated = re.search(rf"\b(?:not|outside|unlike|instead of|rather than|away from)\s+{re.escape(country)}\b", caption, re.IGNORECASE)
        if not negated:
            items = []
            for entry in parsed.items:
                known_city = dreams.KNOWN_CITIES.get((entry.city or "").strip().casefold())
                if not entry.country and (not known_city or known_city[1] == country):
                    entry = entry.model_copy(update={"country": country})
                items.append(entry)
            parsed = parsed.model_copy(update={"items": items})
    # Provider raw output can contain request errors and secrets. Only persist
    # public Instagram metadata and the parser identity, never exception strings.
    metadata = {key: value for key, value in result.get("metadata", {}).items() if key != "error"}
    item.raw_metadata_json = {**(item.raw_metadata_json or {}),
                              "parser_provider": parsed.provider, "parser_model": parsed.model,
                              "parser_raw": {"items": [entry.model_dump() for entry in parsed.items]}}
    if metadata:
        item.raw_metadata_json = {**item.raw_metadata_json, "instagram_metadata": metadata}
    dreams.apply_parsed_item_to_dream_item(db, item, parsed.items[0], item.user_id)
    if old_summary and old_summary not in generated_summaries:
        item.summary = old_summary
    item.tags_json = list(dict.fromkeys([*old_tags, *(item.tags_json or [])]))
    if item.place_name and not item.google_maps_url:
        item.google_maps_url = dreams.build_google_maps_search_url(
            item.place_name, item.city, item.country, item.region_or_neighborhood)
    enqueue_location(db, item)


def resolve_enrichment_job(job_id, *, session_factory=None, reader=None, now=None):
    from ..db import SessionLocal
    session_factory, reader = session_factory or SessionLocal, reader or read_source
    with session_factory() as db:
        claim = claim_enrichment(db, job_id, now=now)
        db.commit()
    if not claim:
        return "skipped"
    failure = None
    try:
        result = reader(claim)
        if not result["parsed"].items:
            raise EnrichmentUnavailable()
    except Exception as exc:
        failure = exc if isinstance(exc, EnrichmentUnavailable) else EnrichmentUnavailable()
    finished = now or utcnow()
    with session_factory() as db:
        # Match capture's owner-before-item order, including destination creation.
        db.query(User).filter_by(id=claim["user_id"]).with_for_update(key_share=True).first()
        item = db.query(DreamItem).filter_by(id=claim["item_id"], user_id=claim["user_id"]).with_for_update().first()
        row = db.query(DreamEnrichmentJob).filter_by(id=job_id, user_id=claim["user_id"]).with_for_update().first()
        if not item or not row or row.lease_token != claim["token"] or row.generation != claim["generation"]:
            return "superseded"
        if item.status != "processing" or fingerprint(item) != claim["fingerprint"]:
            cancel_enrichment(db, item, now=finished)
            db.commit()
            return "superseded"
        row.lease_token = row.lease_expires_at = None
        row.updated_at = finished
        row.next_attempt_at = None
        if failure:
            if row.attempts < setting("DREAM_ENRICHMENT_MAX_ATTEMPTS", 3, 5):
                row.status = "queued"
                row.next_attempt_at = finished + timedelta(seconds=30 * 2 ** (row.attempts - 1))
                row.message = "This save is taking longer to read. We will retry automatically."
            else:
                # Preserve a useful deterministic draft after all model retries.
                if failure.caption:
                    from ..routers.dreams import deterministic_caption_fallback
                    _apply_result(db, item, {"caption": failure.caption, "metadata": failure.metadata,
                                           "parsed": deterministic_caption_fallback(failure.caption, item.source_url, error=FAILURE_MESSAGE)})
                _finish_failed(item, row, finished)
        else:
            _apply_result(db, item, result)
            row.status, row.message = "completed", "Saved to Dreams."
        db.commit()
        return row.status
