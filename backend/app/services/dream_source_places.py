"""Idempotent source-to-place reconciliation, without provider requests."""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata

from sqlalchemy.orm import Session

from ..models import DreamItem, DreamSourcePost, User
from .dream_locations import enqueue_location


def normalized(value):
    value = unicodedata.normalize("NFKD", str(value or "")).casefold()
    return " ".join(re.sub(r"[^\w\s]", " ", "".join(c for c in value if not unicodedata.combining(c))).split())


COUNTRY_ALIASES = {
    "ma": "morocco", "morocco": "morocco",
    "vn": "vietnam", "viet nam": "vietnam", "vietnam": "vietnam",
    "us": "united states", "usa": "united states", "united states": "united states",
    "united states of america": "united states",
    "uk": "united kingdom", "gb": "united kingdom", "united kingdom": "united kingdom",
    "ae": "united arab emirates", "uae": "united arab emirates", "united arab emirates": "united arab emirates",
}
CITY_ALIASES = {
    ("morocco", "marrakech"): "marrakesh",
    ("morocco", "marrakesh"): "marrakesh",
    ("vietnam", "ha noi"): "hanoi",
    ("vietnam", "hanoi"): "hanoi",
}


def identity_parts(place):
    # Category/summary are interpretation, not identity. Region distinguishes
    # explicitly named branches within a city without relying on model order.
    parts = [normalized(getattr(place, field, None)) for field in ("place_name", "city", "country", "region_or_neighborhood")]
    parts[2] = COUNTRY_ALIASES.get(parts[2], parts[2])
    parts[1] = CITY_ALIASES.get((parts[2], parts[1]), parts[1])
    return parts


def place_key(place):
    parts = identity_parts(place)
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False).encode()).hexdigest()


def source_alias_keys(place, caption):
    """Alternative names retain this exact place's geography and branch."""
    from .dream_place_aliases import source_place_aliases
    parts = identity_parts(place)
    return {hashlib.sha256(json.dumps([normalized(alias), *parts[1:]], ensure_ascii=False).encode()).hexdigest()
            for alias in source_place_aliases(place.place_name, caption)}


def provisional_draft(item):
    raw = item.raw_metadata_json or {}
    return bool("shared_text" in raw
                and not any(raw.get(field) for field in ("parser_raw", "parser_model", "parser_provider", "source_extracted_key"))
                and not raw.get("dream_user_edited") and item.status != "confirmed")


def legacy_extracted_key(item):
    """Read the first historically extracted place only from that saved result.

    This supplies the original identity for a manually renamed legacy card,
    without assuming the first place in a *new* parse is the existing card.
    """
    raw = item.raw_metadata_json or {}
    if raw.get("source_extracted_key"):
        return raw["source_extracted_key"]
    values = raw.get("parser_raw", {}).get("items") if isinstance(raw.get("parser_raw"), dict) else None
    if item.source_place_key == "primary" and isinstance(values, list) and values and isinstance(values[0], dict):
        from .dream_parser import DreamParseItem
        entry = DreamParseItem.model_validate(values[0])
        if entry.place_name:
            return place_key(entry)
    return place_key(item) if item.place_name and not provisional_draft(item) else None


def ensure_source(db: Session, item: DreamItem):
    source = item.source_post
    if source is None:
        source = db.query(DreamSourcePost).filter_by(user_id=item.user_id, source_url=item.source_url).first()
        if source is None:
            source = DreamSourcePost(user_id=item.user_id, source_url=item.source_url,
                source_platform=item.source_platform, caption=item.caption,
                raw_metadata_json=dict(item.raw_metadata_json or {}), created_at=item.created_at)
            db.add(source)
            db.flush()
        item.source_post = source
        item.source_post_id = source.id
        db.flush()
    return source


def source_fields(item):
    source = item.source_post
    return {"source_post_id": source.id if source else None,
            "source_place_count": len(source.items) if source else 1,
            "source_place_index": item.source_place_index}


def remember_removed_place(db, item):
    from .dream_place_aliases import caption_for_place
    source = ensure_source(db, item)
    raw = item.raw_metadata_json or {}
    removed = set(source.removed_place_keys or [])
    removed.add(place_key(item))
    removed.add(raw.get("source_extracted_key") or place_key(item))
    removed.update(source_alias_keys(item, caption_for_place(item)))
    if item.source_place_key != "primary":
        removed.add(item.source_place_key)
    source.removed_place_keys = sorted(removed)


def reconcile_places(db: Session, anchor: DreamItem, parsed, *, preserve_anchor=False, preserve_existing=False, anchor_is_draft=False):
    """Never delete unmatched places, overwrite reviewed fields, or revive removals.

    The caller serializes the owner before the item. Existing item IDs survive
    parser reordering; each newly found place receives its own location job.
    """
    from ..routers import dreams
    from .dream_enrichment import enrichment_is_protected
    from .dream_place_aliases import caption_for_place, source_place_aliases

    # All public mutations and the worker use owner -> items -> job/location.
    # Lock every sibling before inspecting edit/pin protection. Refresh existing
    # identity-map objects so a committed edit cannot be read from stale memory.
    db.query(User).filter_by(id=anchor.user_id).with_for_update(key_share=True).first()
    source = ensure_source(db, anchor)
    source.caption = anchor.caption or source.caption
    source.raw_metadata_json = dict(anchor.raw_metadata_json or {})
    db.flush()
    existing = db.query(DreamItem).filter_by(user_id=anchor.user_id, source_post_id=source.id).order_by(
        DreamItem.id).with_for_update().populate_existing().all()
    existing_ids = {item.id for item in existing}
    by_key = {}
    for item in existing:
        key = None if item is anchor and anchor_is_draft else legacy_extracted_key(item)
        if key:
            by_key[key] = item
        by_key.setdefault(place_key(item), item)
        if item.source_place_key != "primary":
            by_key.setdefault(item.source_place_key, item)
    removed = set(source.removed_place_keys or [])
    entries = []
    seen = set()
    named = [entry for entry in parsed.items if (entry.place_name or "").strip()]
    candidates = named or (parsed.items[:1] if not any(item.place_name for item in existing) else [])
    # A model may return both names in `English name (local name)`. Prefer the
    # primary source name when the pair names the same exact branch. Ambiguous
    # shared aliases and different geography cannot collapse distinct venues.
    alias_owners = {}
    for entry in candidates:
        for alias_key in source_alias_keys(entry, source.caption):
            alias_owners.setdefault(alias_key, set()).add(place_key(entry))
    duplicate_aliases = set()
    for entry in candidates:
        key = place_key(entry)
        owners = alias_owners.get(key, set())
        if len(owners) == 1 and key not in owners and not owners & duplicate_aliases:
            duplicate_aliases.add(key)
    for entry in candidates:
        key = place_key(entry)
        aliases = source_alias_keys(entry, source.caption)
        if key in seen or key in removed or aliases & removed:
            continue
        if key in duplicate_aliases:
            continue
        seen.add(key)
        entries.append((key, entry))
    # Adding a previously missing country/city is refinement, not another
    # venue. Match only when both directions are unique; never merge multiple
    # same-name branches based on incomplete geography.
    compatible = {}
    for key, entry in entries:
        if key in by_key:
            continue
        wanted = identity_parts(entry)
        possible = []
        for item in existing:
            actual = identity_parts(item)
            names = {actual[0], *(normalized(alias) for alias in source_place_aliases(item.place_name, caption_for_place(item)))}
            if actual[0] and wanted[0] in names and all(not a or not b or a == b for a, b in zip(actual[1:], wanted[1:])):
                possible.append(item)
        if len(possible) == 1:
            compatible[key] = possible[0]
    for key, item in compatible.items():
        if sum(candidate.id == item.id for candidate in compatible.values()) == 1 and not any(
            by_key.get(other_key) is item for other_key, _ in entries if other_key != key):
            by_key[key] = item
    # Only a blank draft can be assigned by position. A named historical card
    # must match its saved identity even when the new parse changes ordering.
    matched_ids = {by_key[key].id for key, _ in entries if key in by_key}
    unassigned_anchor = (not anchor.place_name or anchor_is_draft or provisional_draft(anchor)) and anchor.id not in matched_ids and not enrichment_is_protected(anchor)
    assigned = set()
    added = 0
    touched = []
    for index, (key, entry) in enumerate(entries):
        item = by_key.get(key)
        if item is None and index == 0 and unassigned_anchor:
            item = anchor
        if item is None:
            item = DreamItem(user_id=anchor.user_id, dream_id=anchor.dream_id,
                source_post_id=source.id, source_place_key=key, source_place_index=index,
                source_platform=anchor.source_platform, source_url=anchor.source_url,
                caption=anchor.caption, created_at=anchor.created_at,
                raw_metadata_json={"source_extracted_key": key,
                    **({"instagram_metadata": (anchor.raw_metadata_json or {})["instagram_metadata"]}
                       if (anchor.raw_metadata_json or {}).get("instagram_metadata") else {})})
            db.add(item)
            db.flush()
            added += 1
        if item.id in assigned:
            continue
        assigned.add(item.id)
        # Record the original extracted key even for protected legacy rows, so
        # a subsequent rename still refers to the same source place.
        item.raw_metadata_json = {**(item.raw_metadata_json or {}), "source_extracted_key": key}
        item.source_place_index = index
        protected = enrichment_is_protected(item) or (item is anchor and preserve_anchor) or (preserve_existing and item.id in existing_ids)
        if not protected:
            old_summary, old_tags = item.summary, list(item.tags_json or [])
            old_caption = item.caption
            old_auto_summary = (item.raw_metadata_json or {}).get("source_generated_summary")
            old_identity = place_key(item)
            aliases = {normalized(alias) for alias in source_place_aliases(item.place_name, caption_for_place(item))}
            if normalized(entry.place_name) in aliases:
                # Local aliases aid lookup; reparsing must not rename an
                # existing English card or split it into translated duplicates.
                entry = entry.model_copy(update={"place_name": item.place_name})
            if normalized(item.place_name) == normalized(entry.place_name):
                # Equivalent spelling should not move an existing card from
                # its country board or invalidate an already accurate pin.
                old_parts, new_parts = identity_parts(item), identity_parts(entry)
                entry = entry.model_copy(update={field: getattr(item, field)
                    for offset, field in enumerate(("city", "country", "region_or_neighborhood"), 1)
                    if getattr(item, field) and (not new_parts[offset] or old_parts[offset] == new_parts[offset])})
            generated = {None, "Saved from Instagram", "Saved Instagram link", item.source_url,
                         dreams.summarize(old_caption or ""), old_auto_summary}
            dreams.apply_parsed_item_to_dream_item(db, item, entry, item.user_id)
            if old_summary and old_summary not in generated:
                item.summary = old_summary
            item.tags_json = list(dict.fromkeys([*old_tags, *(item.tags_json or [])]))
            item.raw_metadata_json = {**(item.raw_metadata_json or {}), "source_generated_summary": entry.summary}
            if old_identity != place_key(entry):
                item.google_place_id = None
                item.google_maps_url = None
            if item.place_name and not item.google_maps_url:
                item.google_maps_url = dreams.build_google_maps_search_url(
                    item.place_name, item.city, item.country, item.region_or_neighborhood)
            db.flush()
            enqueue_location(db, item)
        touched.append(item)
    db.flush()
    db.expire(source, ["items"])
    return {"added": added, "place_ids": [item.id for item in touched], "source_post_id": source.id}


def expand_saved_sources(db: Session, *, user_id=None, item_ids=None, limit=100):
    """Explicit backfill using validated cached parser output, with no network.

    Idempotent and additive: existing cards (including their notes and pins) are
    untouched apart from source linkage; only missing distinct places are added.
    """
    from .dream_parser import DreamParseItem, DreamParseResponse
    query = db.query(DreamItem).filter(DreamItem.source_place_key == "primary")
    if user_id is not None:
        query = query.filter(DreamItem.user_id == user_id)
    if item_ids is not None:
        query = query.filter(DreamItem.id.in_(item_ids))
    rows = query.with_entities(DreamItem.id, DreamItem.user_id).order_by(DreamItem.user_id, DreamItem.id).limit(max(1, min(limit, 1000))).all()
    report = []
    for item_id, owner_id in rows:
        db.query(User).filter_by(id=owner_id).with_for_update(key_share=True).first()
        item = db.query(DreamItem).filter_by(id=item_id, user_id=owner_id).with_for_update().populate_existing().first()
        if item is None:
            continue
        raw = (item.raw_metadata_json or {}).get("parser_raw")
        values = raw.get("items") if isinstance(raw, dict) else None
        if not isinstance(values, list) or len(values) < 2:
            continue
        try:
            parsed = DreamParseResponse(items=[DreamParseItem.model_validate(value) for value in values[:25]],
                                       provider="saved", model="saved")
        except Exception:
            continue
        if item.enrichment and item.enrichment.status in {"queued", "running"}:
            continue
        report.append({"item_id": item.id, **reconcile_places(db, item, parsed, preserve_anchor=True, preserve_existing=True)})
    return report
