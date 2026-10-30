"""Shared planning domain: ownership, immutable revisions and explicit sharing."""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import os
import re
import secrets
from urllib.parse import quote, urlparse
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

from ..models import DreamItem, DreamSourcePost, User
from ..planner_models import (PlannerContribution, PlannerIdea, PlannerInvite,
    PlannerInviteAcceptance, PlannerJob, PlannerMember, PlannerRevision,
    PlannerSourceShare, PlannerTrip, PlannerVote)

MAX_IDEAS = 200
MAX_MEMBERS = 50


def now():
    return datetime.now(timezone.utc)


def aware(value):
    return value.replace(tzinfo=timezone.utc) if value and value.tzinfo is None else value


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str, ensure_ascii=False).encode()).hexdigest()


def normalized(value):
    return " ".join(str(value or "").casefold().split())


def setting(name, default, maximum):
    try:
        return max(1, min(maximum, int(os.getenv(name, str(default)))))
    except ValueError:
        return default


def validate_settings(values):
    try:
        start, end = date.fromisoformat(values["start_date"]), date.fromisoformat(values["end_date"])
        ZoneInfo(values["timezone"])
    except (ValueError, KeyError, ZoneInfoNotFoundError):
        raise HTTPException(422, "Choose valid dates and a destination time zone.")
    if not 0 <= (end - start).days < 31:
        raise HTTPException(422, "A trip must last between 1 and 31 days.")
    if values["pace"] not in {"relaxed", "balanced", "packed"} or values["transport"] not in {"walk", "drive", "transit"}:
        raise HTTPException(422, "Choose a valid pace and transport option.")


def safe_url(value):
    if value is None:
        return None
    parsed = urlparse(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise HTTPException(422, "Use a complete http or https link.")
    return value.strip()[:2048]


def member_trip(db: Session, trip_id: str, user_id: int, *, edit=False, owner=False, lock=False):
    query = db.query(PlannerTrip).filter_by(id=trip_id)
    if lock:
        query = query.with_for_update()
    trip = query.first()
    member = db.get(PlannerMember, (trip_id, user_id)) if trip else None
    if not trip or not member or member.removed_at:
        raise HTTPException(404, "Trip not found or you no longer have access.")
    if owner and member.role != "owner":
        raise HTTPException(403, "Only the organiser can change people's access.")
    if edit and member.role not in {"owner", "editor"}:
        raise HTTPException(403, "You can add ideas and vote. Ask the organiser for editing access.")
    return trip, member


def check_version(trip, expected):
    if trip.version != expected:
        raise HTTPException(409, "This plan changed on another device. Review the latest version before saving.")


def bump_version(db, trip, expected):
    # The conditional write also protects SQLite/dev deployments, where row locks are ignored.
    db.flush()
    count = db.query(PlannerTrip).filter_by(id=trip.id, version=expected).update(
        {PlannerTrip.version: expected + 1, PlannerTrip.updated_at: now()}, synchronize_session=False)
    if count != 1:
        raise HTTPException(409, "This plan changed on another device. Review the latest version before saving.")
    db.expire(trip)
    db.refresh(trip)


def active_idea(db, trip_id, idea_id):
    idea = db.query(PlannerIdea).filter_by(id=idea_id, trip_id=trip_id, deleted_at=None).first()
    if not idea:
        raise HTTPException(404, "Place not found in this trip.")
    return idea


def revision_out(row):
    return None if row is None else {"id": row.id, "plan": row.plan, "source": row.source,
        "created_at": row.created_at, "base_version": row.base_version}


def job_out(row):
    return None if row is None else {"id": row.id, "status": row.status, "message": row.message,
                                   "revision_id": row.revision_id}


def invite_status(row):
    if row.revoked_at:
        return "revoked"
    if aware(row.expires_at) <= now():
        return "expired"
    if row.uses >= row.max_uses:
        return "accepted" if row.recipient_email else "used"
    return "pending"


def invite_out(row):
    return {"id": row.id, "label": row.label, "role": row.role, "expires_at": row.expires_at,
            "status": invite_status(row), "uses": row.uses}


def idea_list(db, trip, user_id, *, include_votes=False):
    ideas = db.query(PlannerIdea).filter_by(trip_id=trip.id, deleted_at=None).order_by(PlannerIdea.created_at, PlannerIdea.id).all()
    ids = [row.id for row in ideas]
    contributions = defaultdict(list)
    users = {}
    for con, user in (db.query(PlannerContribution, User).outerjoin(User, User.id == PlannerContribution.user_id)
                      .filter(PlannerContribution.trip_id == trip.id).all()):
        contributions[con.idea_id].append(con)
        users[con.user_id] = user.name or "Traveller" if user else "Traveller"
    votes = defaultdict(list)
    for vote in db.query(PlannerVote).filter(PlannerVote.idea_id.in_(ids)).all() if ids else []:
        votes[vote.idea_id].append(vote)
    result = []
    for row in ideas:
        source_cons = contributions[row.id]
        contributor_ids = list(dict.fromkeys(con.user_id for con in source_cons if con.user_id is not None))
        item = {"id": row.id, "title": row.title, "category": row.category, "city": row.city,
            "country": row.country, "region_or_neighborhood": row.region_or_neighborhood,
            "source_url": row.source_url, "google_place_id": row.google_place_id,
            "latitude": row.latitude, "longitude": row.longitude, "duration_minutes": row.duration_minutes,
            "must_do": row.must_do, "score": sum(v.value for v in votes[row.id]),
            "my_vote": next((v.value for v in votes[row.id] if v.user_id == user_id), 0),
            "contributors": [{"user_id": str(i), "name": users.get(i, "Traveller")} for i in contributor_ids],
            "source_count": len(set(con.source_url or con.identity_key for con in source_cons)),
            "created_by": str(row.created_by) if row.created_by else None, "status": row.status,
            "image_url": f"/planner/trips/{trip.id}/ideas/{row.id}/thumbnail" if any(con.dream_item_id for con in source_cons) else None}
        if include_votes:
            item["votes"] = [{"user_id": str(v.user_id), "value": v.value} for v in votes[row.id]]
        result.append(item)
    return result


def summary(db, trip, user_id, ideas=None):
    from .planner_matching import scope, sharing
    member = db.get(PlannerMember, (trip.id, user_id))
    ideas = ideas if ideas is not None else idea_list(db, trip, user_id)
    return {"id": trip.id, "title": trip.title, "destination": trip.destination,
        "start_date": trip.start_date, "end_date": trip.end_date, "timezone": trip.timezone,
        "pace": trip.pace, "transport": trip.transport, "transport_modes": trip.transport_modes or [trip.transport], "role": member.role,
        "version": trip.version, "member_count": db.query(PlannerMember).filter_by(trip_id=trip.id, removed_at=None).count(),
        "idea_count": len(ideas), "cover_image_url": next((i["image_url"] for i in ideas if i.get("image_url")), None),
        "updated_at": trip.updated_at, "match_scope": scope(trip), "dream_sharing": sharing(trip, member)}


def detail(db, trip, user_id):
    from .planner_engine import refresh_plan_travel
    ideas = idea_list(db, trip, user_id)
    member = db.get(PlannerMember, (trip.id, user_id))
    people = (db.query(PlannerMember, User).join(User, PlannerMember.user_id == User.id)
              .filter(PlannerMember.trip_id == trip.id, PlannerMember.removed_at.is_(None)).order_by(PlannerMember.joined_at).all())
    accepted = db.get(PlannerRevision, trip.accepted_revision_id) if trip.accepted_revision_id else None
    draft = db.get(PlannerRevision, trip.draft_revision_id) if trip.draft_revision_id else None
    job = db.query(PlannerJob).filter_by(trip_id=trip.id).order_by(PlannerJob.created_at.desc(), PlannerJob.id.desc()).first()
    invites = db.query(PlannerInvite).filter_by(trip_id=trip.id).order_by(PlannerInvite.created_at.desc()).limit(100).all() if member.role == "owner" else []
    display_payload = {"trip": planning_trip(trip), "ideas": ideas}
    displayed_plan = refresh_plan_travel(accepted.plan, display_payload) if accepted else None
    displayed_draft = revision_out(draft)
    if displayed_draft:
        displayed_draft["plan"] = refresh_plan_travel(draft.plan, display_payload)
    return {**summary(db, trip, user_id, ideas), "ideas": ideas,
        "members": [{"user_id": str(m.user_id), "name": u.name or "Traveller", "role": m.role} for m, u in people],
        "invites": [invite_out(row) for row in invites], "plan": displayed_plan,
        "draft": displayed_draft, "generation": job_out(job)}


def check_idea_capacity(db, trip):
    if db.query(PlannerIdea).filter_by(trip_id=trip.id, deleted_at=None).count() >= MAX_IDEAS:
        raise HTTPException(422, "This trip has 200 ideas. Remove a few before adding more.")


def shared_identity(item):
    from .planner_geography import geography
    from .dream_source_places import normalized as canonical_name
    location = item.location
    identity = location.google_identity if location else None
    place_id = ((identity.confirmed_place_id or identity.selected_place_id) if identity else None) or item.google_place_id
    if place_id:
        return digest(["google", place_id]), place_id
    # A title without reliable geography cannot safely merge two people's saves.
    if item.place_name and item.city and item.country:
        country, city = geography(item.country, item.city)
        return digest(["named", canonical_name(item.place_name), city, country, canonical_name(item.region_or_neighborhood) or None]), None
    return digest(["dream", item.user_id, item.id]), None


def plan_idea_ids(plan):
    ids = set()
    for day in plan.get("days", []):
        ids.update(stop.get("idea_id") for stop in day.get("stops", []) if stop.get("idea_id"))
        stay = day.get("stay")
        if isinstance(stay, dict) and stay.get("idea_id"):
            ids.add(stay["idea_id"])
    return ids


def plan_references(db, trip):
    ids = set()
    for revision_id in (trip.accepted_revision_id, trip.draft_revision_id):
        revision = db.get(PlannerRevision, revision_id) if revision_id else None
        if revision:
            ids.update(plan_idea_ids(revision.plan))
    return ids


def promote_identity(db, trip, idea, key, place_id):
    """Resolve late source identity without changing accepted itinerary references."""
    if idea.deleted_at:
        return idea
    idea.google_place_id = place_id or idea.google_place_id
    if idea.identity_key == key:
        return idea
    target = db.query(PlannerIdea).filter_by(trip_id=trip.id, identity_key=key).first()
    if target is None:
        idea.identity_key = key
        return idea
    references = plan_references(db, trip)
    if target.deleted_at and (idea.id in references or idea.user_edited):
        # Someone deliberately placed/edited the alias after the earlier removal.
        # Keep that current decision intact; never rewrite accepted itinerary IDs.
        return idea
    if idea.id in references and target.id in references:
        return idea
    canonical, removed = (idea, target) if idea.id in references else (target, idea)
    # Retain each traveller's existing canonical vote when they voted on both copies.
    for vote in db.query(PlannerVote).filter_by(idea_id=removed.id).all():
        if db.get(PlannerVote, (canonical.id, vote.user_id)) is None:
            db.add(PlannerVote(idea_id=canonical.id, user_id=vote.user_id, value=vote.value))
        db.delete(vote)
    db.query(PlannerContribution).filter_by(idea_id=removed.id).update(
        {PlannerContribution.idea_id: canonical.id}, synchronize_session="fetch")
    canonical.must_do = canonical.must_do or removed.must_do
    canonical.google_place_id = place_id or canonical.google_place_id
    removed.deleted_at, removed.merged_into_id = now(), canonical.id
    removed.identity_key = digest(["merged", removed.id])
    db.flush()
    canonical.identity_key = key
    db.flush()
    return canonical


def import_dream_item(db, trip, user_id, item, *, explicit=True):
    from .planner_geography import place_match_key
    if item.user_id != user_id:
        raise HTTPException(404, "A selected save is no longer available.")
    manual_coordinates = (None, None)
    if item.location and item.location.status == "manual" and item.location.provider != "google_places":
        from .dream_locations import checked_coordinates
        latitude, longitude, _ = checked_coordinates(item.location.latitude, item.location.longitude)
        manual_coordinates = (latitude, longitude)
    con = db.query(PlannerContribution).filter_by(trip_id=trip.id, user_id=user_id, identity_key=f"dream:{item.id}").first()
    if con:
        idea = db.get(PlannerIdea, con.idea_id)
        if explicit and idea.deleted_at:
            check_idea_capacity(db, trip)
            idea.deleted_at = None
        # Shared fields can finish parsing, but later edits to personal Dreams do not overwrite group edits.
        if idea.status != "ready" and not idea.user_edited and item.place_name:
            idea.title, idea.city, idea.country, idea.category = item.place_name, item.city, item.country, item.category
            idea.status = "ready"
            _, place_id = shared_identity(item)
            idea.google_place_id = place_id
            idea.latitude, idea.longitude = manual_coordinates
        if not idea.user_edited:
            for field in ("city", "country", "region_or_neighborhood"):
                if not getattr(idea, field) and getattr(item, field):
                    setattr(idea, field, getattr(item, field))
        same_identity = (place_match_key(idea.title, idea.country, idea.city, idea.region_or_neighborhood) == item.planner_place_key
                         if item.planner_place_key else all(normalized(getattr(idea, shared)) == normalized(getattr(item, source))
                         for shared, source in (("title", "place_name"), ("city", "city"), ("country", "country"))))
        if same_identity and not idea.user_edited and not idea.deleted_at:
            key, place_id = shared_identity(item)
            idea = promote_identity(db, trip, idea, key, place_id)
            if manual_coordinates[0] is not None:
                idea.latitude, idea.longitude = manual_coordinates
        return idea
    key, place_id = shared_identity(item)
    idea = db.query(PlannerIdea).filter_by(trip_id=trip.id, identity_key=key).first()
    if idea is None and item.planner_place_key:
        # Existing named ideas may predate canonical geography, or gain a provider
        # identity later. Never merge conflicting confirmed provider locations.
        candidates = db.query(PlannerIdea).filter_by(trip_id=trip.id, dream_match_key=item.planner_place_key, merged_into_id=None)
        candidates = candidates.filter(PlannerIdea.google_place_id.is_(None)) if not place_id else candidates.filter(
            (PlannerIdea.google_place_id.is_(None)) | (PlannerIdea.google_place_id == place_id))
        idea = candidates.order_by(PlannerIdea.created_at).first()
        if idea and not idea.deleted_at:
            idea = promote_identity(db, trip, idea, key, place_id)
    if idea is None:
        check_idea_capacity(db, trip)
        idea = PlannerIdea(trip_id=trip.id, identity_key=key, created_by=user_id,
            title=item.place_name or "Saved reel", category=item.category or "place", city=item.city,
            country=item.country, region_or_neighborhood=item.region_or_neighborhood, source_url=item.source_url, google_place_id=place_id,
            latitude=manual_coordinates[0], longitude=manual_coordinates[1],
            status="ready" if item.place_name else "processing" if item.status in {"created", "processing"} else "needs_details",
            duration_minutes=90 if item.category in {"restaurant", "food", "cafe"} else 60)
        db.add(idea)
        db.flush()
    elif explicit and idea.deleted_at:
        check_idea_capacity(db, trip)
        idea.deleted_at = None
    db.add(PlannerContribution(trip_id=trip.id, idea_id=idea.id, user_id=user_id,
        identity_key=f"dream:{item.id}", dream_item_id=item.id, source_url=item.source_url))
    trip.updated_at = now()
    db.flush()
    return idea


def import_dreams(db, trip, user_id, item_ids):
    try:
        ids = list(dict.fromkeys(int(i) for i in item_ids))
    except (ValueError, TypeError):
        raise HTTPException(422, "Choose saved places that have finished uploading.")
    if len(ids) > MAX_IDEAS:
        raise HTTPException(422, "Choose up to 200 saves at once.")
    rows = db.query(DreamItem).filter(DreamItem.id.in_(ids), DreamItem.user_id == user_id).all()
    if len(rows) != len(ids):
        raise HTTPException(404, "A selected save is no longer available.")
    for row in rows:
        import_dream_item(db, trip, user_id, row)


def reconcile_sources(db, trip):
    """A durable association includes every eventual extracted sibling, never unrelated Dreams."""
    shares = db.query(PlannerSourceShare).filter_by(trip_id=trip.id).all()
    for share in shares:
        share.last_synced_at = now()
        member = db.get(PlannerMember, (trip.id, share.user_id))
        if not member or member.removed_at:
            continue
        rows = db.query(DreamItem).filter_by(user_id=share.user_id, source_url=share.source_url).order_by(DreamItem.id).all()
        for row in rows:
            try:
                import_dream_item(db, trip, share.user_id, row, explicit=False)
            except HTTPException as exc:
                if exc.status_code == 422:
                    break
                raise


def planning_trip(trip):
    value = {field: getattr(trip, field) for field in
             ("id", "title", "destination", "start_date", "end_date", "timezone", "pace", "transport")}
    value["transport_modes"] = trip.transport_modes or [trip.transport]
    return value


def engine_payload(db, trip, user_id):
    accepted = db.get(PlannerRevision, trip.accepted_revision_id) if trip.accepted_revision_id else None
    return {"trip": planning_trip(trip),
            "ideas": idea_list(db, trip, user_id, include_votes=True), "existing_plan": deepcopy(accepted.plan) if accepted else None}


def save_revision(db, trip, user_id, plan, *, source="manual", accepted=True, expected_version=None):
    from .planner_engine import plan_for_storage, refresh_plan_travel, validate_plan
    payload = engine_payload(db, trip, user_id)
    plan = deepcopy(plan)
    aliases = {row.id: row.merged_into_id for row in db.query(PlannerIdea)
               .filter(PlannerIdea.trip_id == trip.id, PlannerIdea.merged_into_id.is_not(None)).all()}
    for day in plan.get("days", []) if isinstance(plan, dict) else []:
        nodes = [*day.get("stops", []), day.get("stay")] if isinstance(day, dict) else []
        for stop in nodes:
            if not isinstance(stop, dict):
                continue
            seen = set()
            while stop.get("idea_id") in aliases and stop["idea_id"] not in seen:
                seen.add(stop["idea_id"])
                stop["idea_id"] = aliases[stop["idea_id"]]
    if isinstance(plan, dict) and isinstance(plan.get("unplaced_idea_ids"), list):
        resolved = []
        for identifier in plan["unplaced_idea_ids"]:
            seen = set()
            while isinstance(identifier, str) and identifier in aliases and identifier not in seen:
                seen.add(identifier)
                identifier = aliases[identifier]
            if identifier not in resolved:
                resolved.append(identifier)
        plan["unplaced_idea_ids"] = resolved
    try:
        validated = validate_plan(plan, payload, preserve_locked=False)
        clean = plan_for_storage(refresh_plan_travel(validated, payload))
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    expected_version = trip.version if expected_version is None else expected_version
    check_version(trip, expected_version)
    row = PlannerRevision(trip_id=trip.id, created_by=user_id, base_version=expected_version,
                          source=source, plan=clean, accepted_at=now() if accepted else None)
    db.add(row)
    db.flush()
    if accepted:
        bump_version(db, trip, expected_version)
        trip.accepted_revision_id = row.id
        trip.draft_revision_id = None
    else:
        trip.draft_revision_id = row.id
        trip.updated_at = now()
    db.flush()
    return row


def lookup_invite(db, token, *, lock=False):
    if not isinstance(token, str) or not 32 <= len(token) <= 150:
        raise HTTPException(404, "This invitation could not be found.")
    query = db.query(PlannerInvite).filter_by(token_hash=hashlib.sha256(token.encode()).hexdigest())
    if lock:
        query = query.with_for_update()
    row = query.first()
    if not row:
        raise HTTPException(404, "This invitation could not be found.")
    return row


def require_active_invite(row):
    if invite_status(row) != "pending":
        raise HTTPException(410, "This invite link is no longer active. Ask the organiser for a new invitation.")


def invite_preview(db, token):
    row = lookup_invite(db, token)
    require_active_invite(row)
    trip = db.get(PlannerTrip, row.trip_id)
    user = db.get(User, row.created_by) if row.created_by else None
    return {"trip": {"id": trip.id, "title": trip.title, "destination": trip.destination,
                     "start_date": trip.start_date, "end_date": trip.end_date, "cover_image_url": None},
            "inviter_name": user.name or "A traveller" if user else "A traveller", "role": row.role,
            "member_count": db.query(PlannerMember).filter_by(trip_id=trip.id, removed_at=None).count(), "status": "pending"}


def invite_link(row):
    from ..crypto import decrypt_refresh_token
    token = decrypt_refresh_token(row.token_encrypted)
    base = (os.getenv("TROTTER_API_URL") or os.getenv("BACKEND_URL") or "http://localhost:8000").rstrip("/")
    return {"invite": invite_out(row), "token": token, "share_url": f"{base}/planner/open#token={quote(token)}"}


def accept_invite(db, token, user):
    from .auth_identities import verified_emails
    row = lookup_invite(db, token)
    # Lock order is trip -> invite consistently with owner-side revocation.
    trip = db.query(PlannerTrip).filter_by(id=row.trip_id).with_for_update().one()
    db.refresh(row, with_for_update=True)
    existing = db.get(PlannerMember, (trip.id, user.id))
    if existing and not existing.removed_at:
        return trip
    require_active_invite(row)
    if (db.get(PlannerInviteAcceptance, (row.id, user.id)) or
            existing and aware(row.created_at) <= aware(existing.removed_at)):
        raise HTTPException(410, "Your access to this trip ended. Ask for a new invitation.")
    if row.recipient_email and normalized(row.recipient_email) not in verified_emails(db, user):
        raise HTTPException(403, "This invitation belongs to another email address. Sign in with the invited account.")
    if db.query(PlannerMember).filter_by(trip_id=trip.id, removed_at=None).count() >= MAX_MEMBERS:
        raise HTTPException(422, "This trip has reached its 50-traveller limit.")
    row.uses += 1
    if existing:
        existing.removed_at, existing.role, existing.joined_at = None, row.role, now()
    else:
        db.add(PlannerMember(trip_id=trip.id, user_id=user.id, role=row.role))
    db.add(PlannerInviteAcceptance(invite_id=row.id, user_id=user.id))
    trip.updated_at = now()
    db.flush()
    return trip


def enqueue_plan(db, trip, user, values):
    expected = values["expected_version"]
    request_hash = digest({"trip_id": trip.id, **values})
    old = db.query(PlannerJob).filter_by(user_id=user.id, client_request_id=values["client_request_id"]).first()
    if old:
        if old.request_hash != request_hash:
            raise HTTPException(409, "This request was already used for a different plan.")
        return old
    check_version(trip, expected)
    running = db.query(PlannerJob).filter(PlannerJob.trip_id == trip.id, PlannerJob.status.in_(["queued", "running"])).first()
    if running:
        raise HTTPException(409, "A draft is already being prepared for this trip.")
    recent = db.query(PlannerJob).filter(PlannerJob.user_id == user.id, PlannerJob.created_at >= now() - timedelta(days=1)).count()
    if recent >= setting("PLANNER_DAILY_GENERATION_LIMIT", 20, 100):
        raise HTTPException(429, "You've reached today's planning limit. You can still edit your trip directly.")
    spend = sum(float((row.usage_json or {}).get("cost_usd", (row.usage_json or {}).get("reserved_usd", 0)) or 0) for row in
                db.query(PlannerJob).filter(PlannerJob.user_id == user.id, PlannerJob.created_at >= now() - timedelta(days=1)).all())
    try:
        budget = max(0.01, min(10, float(os.getenv("PLANNER_DAILY_BUDGET_USD", "1"))))
    except ValueError:
        budget = 1.0
    use_ai = values.get("mode", "ai") == "ai"
    try:
        reserve = max(0.01, min(1, float(os.getenv("PLANNER_MAX_JOB_COST_USD", "0.15")))) if use_ai else 0
    except ValueError:
        reserve = 0.15 if use_ai else 0
    if use_ai and spend + reserve > budget:
        raise HTTPException(429, "Today's automatic planning budget is used. You can still edit your trip directly.")
    day = values.get("day")
    if day and not trip.start_date <= day <= trip.end_date:
        raise HTTPException(422, "Choose a day within this trip.")
    data = {"day": day, "pace": values.get("pace")}
    row = PlannerJob(trip_id=trip.id, user_id=user.id, client_request_id=values["client_request_id"],
        request_hash=request_hash, base_version=trip.version, input_json=data,
        use_ai=use_ai, usage_json={"reserved_usd": reserve}, status="queued", message="Preparing your draft.")
    db.add(row)
    db.flush()
    return row


def notify_jobs(job_ids):
    from ..tasks.planner_tasks import generate_trip_plan
    for job_id in job_ids:
        try:
            generate_trip_plan.apply_async(args=[job_id], retry=False)
        except Exception:
            # The durable periodic discovery pass will dispatch this queued job later.
            pass


def process_job(job_id, *, session_factory=None):
    from ..db import SessionLocal
    from .planner_engine import generate_plan, plan_for_storage, validate_plan
    factory = session_factory or SessionLocal
    lease = str(uuid4())
    with factory() as db:
        claimed = db.query(PlannerJob).filter_by(id=job_id, status="queued").update(
            {PlannerJob.status: "running", PlannerJob.lease_token: lease, PlannerJob.started_at: now(),
             PlannerJob.message: "Arranging your days."}, synchronize_session=False)
        if claimed != 1:
            db.rollback()
            return
        job = db.get(PlannerJob, job_id)
        try:
            trip, _ = member_trip(db, job.trip_id, job.user_id, edit=True, lock=True)
            check_version(trip, job.base_version)
            reconcile_sources(db, trip)
            payload = engine_payload(db, trip, job.user_id)
            payload.update({k: v for k, v in (job.input_json or {}).items() if v is not None})
            use_ai = job.use_ai
        except HTTPException as exc:
            job.status, job.message, job.finished_at = "failed", str(exc.detail), now()
            db.commit()
            return
        db.commit()
    # Provider work must not hold a database lock, and duplicate deliveries cannot enter here.
    result = None
    error = None
    try:
        result = generate_plan(payload, use_ai=use_ai)
    except Exception:
        error = "The draft could not be completed. Your saved plan is unchanged. Try again or edit it directly."
    with factory() as db:
        job = db.query(PlannerJob).filter_by(id=job_id, status="running", lease_token=lease).with_for_update().first()
        if job is None:
            return
        if result:
            usage = result.get("usage") or {}
            job.usage_json = {**(job.usage_json or {}), **{k: usage[k] for k in (
                "input_tokens", "output_tokens", "cost_usd", "model", "estimated", "finish_reason",
                "visible_chars", "reasoning_chars", "validation_error") if k in usage}}
        try:
            trip, _ = member_trip(db, job.trip_id, job.user_id, edit=True, lock=True)
            check_version(trip, job.base_version)
            if error:
                raise ValueError(error)
            # The candidate set may have changed during generation. Revalidate before storing.
            current_payload = engine_payload(db, trip, job.user_id)
            clean = plan_for_storage(validate_plan(result["plan"], current_payload, preserve_locked=True))
            revision = PlannerRevision(trip_id=trip.id, created_by=job.user_id, base_version=trip.version,
                plan=clean, source="ai" if result.get("source") == "ai" else "rules")
            db.add(revision)
            db.flush()
            trip.draft_revision_id = revision.id
            trip.updated_at = now()
            job.revision_id, job.status, job.message = revision.id, "completed", "Your draft is ready to review."
        except (ValueError, HTTPException) as exc:
            job.status = "failed"
            job.message = str(exc.detail if isinstance(exc, HTTPException) else exc)[:255]
        job.finished_at = now()
        db.commit()


def discover_jobs(*, session_factory=None):
    from .planner_matching import reconcile_matching
    from ..db import SessionLocal
    factory = session_factory or SessionLocal
    with factory() as db:
        # A lost worker may have already consumed credits. Never automatically repeat its AI call.
        db.query(PlannerJob).filter(PlannerJob.status == "running", PlannerJob.started_at < now() - timedelta(minutes=10)).update(
            {PlannerJob.status: "failed", PlannerJob.finished_at: now(),
             PlannerJob.message: "Planning was interrupted. Your saved plan is unchanged; you can request a new draft."}, synchronize_session=False)
        rows = db.query(PlannerJob).filter(PlannerJob.status == "queued").order_by(PlannerJob.created_at).limit(40).all()
        ids = [r.id for r in rows if r.dispatched_at is None or aware(r.dispatched_at) < now() - timedelta(seconds=60)]
        for row in rows:
            if row.id in ids:
                row.dispatched_at = now()
        # Finish incoming reel associations even if nobody has the trip open.
        source_trip_ids = list(dict.fromkeys(i[0] for i in db.query(PlannerSourceShare.trip_id)
            .order_by(PlannerSourceShare.last_synced_at.asc().nullsfirst(), PlannerSourceShare.id).limit(50).all()))
        for trip_id in source_trip_ids:
            trip = db.query(PlannerTrip).filter_by(id=trip_id).with_for_update(skip_locked=True).first()
            if trip:
                reconcile_sources(db, trip)
        # Fair per-member batches keep new and late-categorized saves moving even when nobody opens the app.
        pending = (db.query(PlannerMember.trip_id, PlannerMember.user_id)
            .join(PlannerTrip, PlannerTrip.id == PlannerMember.trip_id)
            .filter(PlannerMember.dream_auto_share.is_(True), PlannerMember.removed_at.is_(None))
            .filter(PlannerTrip.end_date >= (now() - timedelta(days=1)).date().isoformat())
            .order_by(PlannerMember.dream_last_synced_at.asc().nullsfirst(), PlannerMember.trip_id, PlannerMember.user_id)
            .limit(50).all())
        for trip_id, user_id in pending:
            trip = db.query(PlannerTrip).filter_by(id=trip_id).with_for_update(skip_locked=True).first()
            if trip:
                reconcile_matching(db, trip, user_id=user_id, limit=10)
        db.commit()
    notify_jobs(ids)
    return len(ids)
