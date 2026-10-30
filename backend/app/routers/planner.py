"""Authenticated collaborative trips and explicit draft generation."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import re
import secrets
from typing import Annotated, Literal
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator
from sqlalchemy.orm import Session, selectinload

from ..db import get_db
from ..models import DreamItem, DreamSourcePost, Segment, Trip, User
from ..planner_models import (PlannerContribution, PlannerIdea, PlannerInvite,
    PlannerJob, PlannerMember, PlannerRevision, PlannerSourceShare, PlannerTrip, PlannerVote)
from ..services import planner as service
from ..services import planner_matching as matching
from .auth import get_current_user

router = APIRouter(prefix="/planner", tags=["planner"])
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
RequestId = Annotated[str, StringConstraints(min_length=8, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")]
DateText = Annotated[str, StringConstraints(pattern=r"^\d{4}-\d{2}-\d{2}$")]
Pace = Literal["relaxed", "balanced", "packed"]
Transport = Literal["walk", "drive", "transit"]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TripTransportInput(Input):
    transport_modes: list[Transport] | None = Field(default=None, min_length=1, max_length=3)

    @field_validator("transport_modes")
    @classmethod
    def unique_transport_modes(cls, value):
        if value is None or len(value) != len(set(value)):
            raise ValueError("Choose one or more different ways to get around.")
        return value


class CreateTrip(TripTransportInput):
    title: ShortText
    destination: ShortText
    start_date: DateText
    end_date: DateText
    timezone: str = Field(default="UTC", max_length=64)
    pace: Pace = "balanced"
    transport: Transport = "walk"
    client_request_id: RequestId
    dream_item_ids: list[str] = Field(default_factory=list, max_length=200)
    match_scope_id: str | None = Field(default=None, min_length=64, max_length=64)


class EditTrip(TripTransportInput):
    expected_version: int = Field(ge=1)
    title: ShortText | None = None
    destination: ShortText | None = None
    start_date: DateText | None = None
    end_date: DateText | None = None
    timezone: str | None = Field(default=None, max_length=64)
    pace: Pace | None = None
    transport: Transport | None = None
    match_scope_id: str | None = Field(default=None, min_length=64, max_length=64)


class ImportMatching(Input):
    scope_id: str = Field(min_length=64, max_length=64)
    all: bool = False
    dream_item_ids: list[str] = Field(default_factory=list, max_length=200)


class DreamSharing(Input):
    scope_id: str = Field(min_length=64, max_length=64)
    enabled: bool


class ImportIdeas(Input):
    dream_item_ids: list[str] = Field(min_length=1, max_length=200)


class AddIdea(Input):
    title: ShortText
    category: str = Field(default="place", max_length=32)
    city: str | None = Field(default=None, max_length=128)
    country: str | None = Field(default=None, max_length=128)
    source_url: str | None = Field(default=None, max_length=2048)
    latitude: float | None = Field(default=None, ge=-90, le=90, allow_inf_nan=False)
    longitude: float | None = Field(default=None, ge=-180, le=180, allow_inf_nan=False)
    duration_minutes: int = Field(default=60, ge=5, le=720)
    client_request_id: RequestId


class EditIdea(Input):
    duration_minutes: int | None = Field(default=None, ge=5, le=720)
    must_do: bool | None = None
    title: ShortText | None = None
    city: str | None = Field(default=None, max_length=128)
    country: str | None = Field(default=None, max_length=128)


class AddSource(Input):
    source_url: str = Field(min_length=10, max_length=2048)
    shared_text: str | None = Field(default=None, max_length=20000)
    client_request_id: RequestId


class Vote(Input):
    value: Literal[-1, 0, 1]


class Generate(Input):
    expected_version: int = Field(ge=1)
    client_request_id: RequestId
    day: DateText | None = None
    pace: Pace | None = None
    mode: Literal["ai", "rules"] = "ai"


class Version(Input):
    expected_version: int = Field(ge=1)


class EditPlan(Version):
    plan: dict


class RevisionAction(Version):
    revision_id: str = Field(min_length=1, max_length=36)


class InviteInput(Input):
    role: Literal["editor", "contributor"] = "contributor"
    label: str | None = Field(default=None, max_length=100)
    recipient_email: str | None = Field(default=None, max_length=255)
    client_request_id: RequestId


class RoleInput(Input):
    role: Literal["editor", "contributor"]


class TokenInput(Input):
    token: str = Field(min_length=32, max_length=150)


class ImportBookings(Version):
    segment_ids: list[str] = Field(min_length=1, max_length=50)


def changed(db, trip, user):
    db.flush()
    output = service.detail(db, trip, user.id)
    db.commit()
    return output


def lock_user(db, user):
    db.query(User).filter_by(id=user.id).with_for_update().one()


@router.get("/dreams/destinations")
def dream_destinations(response: Response, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    response.headers["Cache-Control"] = "private, no-store"
    return {"destinations": matching.destinations(db, user.id)}


@router.get("/trips")
def list_trips(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = (db.query(PlannerTrip).join(PlannerMember, PlannerMember.trip_id == PlannerTrip.id)
            .filter(PlannerMember.user_id == user.id, PlannerMember.removed_at.is_(None)).order_by(PlannerTrip.updated_at.desc()).limit(100).all())
    return {"trips": [service.summary(db, trip, user.id) for trip in rows]}


@router.post("/trips", status_code=201)
def create_trip(values: CreateTrip, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    lock_user(db, user)
    data = values.model_dump()
    if data.get("transport_modes") is None:
        data.pop("transport_modes", None)  # Older clients retain their original idempotency fingerprint.
    if data.get("match_scope_id") is None:
        data.pop("match_scope_id", None)  # Preserve pre-migration request fingerprints on retries.
    fingerprint = service.digest(data)
    old = db.query(PlannerTrip).filter_by(owner_id=user.id, client_request_id=values.client_request_id).first()
    if old:
        if old.request_hash != fingerprint:
            raise HTTPException(409, "This request was already used for another trip.")
        return service.detail(db, old, user.id)
    service.validate_settings(data)
    data["transport_modes"] = data.get("transport_modes") or [data["transport"]]
    data["transport"] = data["transport_modes"][0]
    if db.query(PlannerTrip).filter_by(owner_id=user.id).count() >= 100:
        raise HTTPException(422, "You've reached the 100-trip planning limit.")
    trip = PlannerTrip(owner_id=user.id, request_hash=fingerprint,
        **{k: v for k, v in data.items() if k not in {"dream_item_ids", "match_scope_id"}})
    trip.match_country_key, trip.match_city_key = matching.resolve_scope(db, user.id, values.match_scope_id)
    db.add(trip)
    db.flush()
    db.add(PlannerMember(trip_id=trip.id, user_id=user.id, role="owner"))
    db.flush()
    service.import_dreams(db, trip, user.id, values.dream_item_ids)
    return changed(db, trip, user)


@router.get("/trips/{trip_id}")
def get_trip(trip_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    trip, _ = service.member_trip(db, trip_id, user.id, lock=True)
    service.reconcile_sources(db, trip)
    matching.reconcile_matching(db, trip, user_id=user.id)
    return changed(db, trip, user)


@router.patch("/trips/{trip_id}")
def edit_trip(trip_id: str, values: EditTrip, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from copy import deepcopy
    from datetime import date
    trip, _ = service.member_trip(db, trip_id, user.id, edit=True, lock=True)
    service.check_version(trip, values.expected_version)
    edits = values.model_dump(exclude_none=True, exclude={"expected_version", "match_scope_id"})
    if "transport_modes" in edits:
        edits["transport"] = edits["transport_modes"][0]
    elif "transport" in edits:
        edits["transport_modes"] = [edits["transport"]]
    if "match_scope_id" in values.model_fields_set:
        matching.set_scope(db, trip, user.id, values.match_scope_id)
    settings = {field: edits.get(field, getattr(trip, field)) for field in
                ("start_date", "end_date", "timezone", "pace", "transport")}
    service.validate_settings(settings)
    plan = None
    if trip.accepted_revision_id:
        plan = db.get(PlannerRevision, trip.accepted_revision_id).plan
        if any((day["stops"] or (day.get("stay") or {}).get("status") == "selected")
               and not settings["start_date"] <= day["date"] <= settings["end_date"] for day in plan["days"]):
            raise HTTPException(422, "Move or remove stops and selected stays outside the new dates before shortening this trip.")
    dates_changed = settings["start_date"] != trip.start_date or settings["end_date"] != trip.end_date
    for name, value in edits.items():
        setattr(trip, name, value)
    trip.draft_revision_id = None
    if dates_changed and plan is not None:
        plan = deepcopy(plan)
        old_days = {day["date"]: day for day in plan["days"]}
        start, end = date.fromisoformat(trip.start_date), date.fromisoformat(trip.end_date)
        dates = [(start + timedelta(days=i)).isoformat() for i in range((end-start).days + 1)]
        plan["days"] = [old_days.get(day, {"date": day, "stops": []}) for day in dates]
        service.save_revision(db, trip, user.id, plan, source="settings", expected_version=values.expected_version)
    else:
        service.bump_version(db, trip, values.expected_version)
    return changed(db, trip, user)


@router.delete("/trips/{trip_id}")
def delete_trip(trip_id: str, expected_version: int = Query(ge=1), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    trip, _ = service.member_trip(db, trip_id, user.id, owner=True, lock=True)
    service.check_version(trip, expected_version)
    db.delete(trip)
    db.commit()
    return {"id": trip_id, "deleted": True}


@router.post("/trips/{trip_id}/ideas/import")
def import_ideas(trip_id: str, values: ImportIdeas, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    trip, _ = service.member_trip(db, trip_id, user.id, lock=True)
    service.import_dreams(db, trip, user.id, values.dream_item_ids)
    return changed(db, trip, user)


@router.get("/trips/{trip_id}/dream-suggestions")
def dream_suggestions(trip_id: str, response: Response, limit: int = Query(default=20, ge=1, le=100),
                      cursor: int | None = Query(default=None, ge=1),
                      db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    trip, member = service.member_trip(db, trip_id, user.id, lock=True)
    matching.reconcile_matching(db, trip, user_id=user.id)
    output = matching.suggestions(db, trip, member, limit=limit, cursor=cursor)
    db.commit()
    response.headers["Cache-Control"] = "private, no-store"
    return output


@router.post("/trips/{trip_id}/dream-suggestions/import")
def import_matching(trip_id: str, values: ImportMatching,
                    db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if values.all == bool(values.dream_item_ids):
        raise HTTPException(422, "Share all matching saves or choose individual saves.")
    trip, _ = service.member_trip(db, trip_id, user.id, lock=True)
    matching.import_suggestions(db, trip, user.id, values.scope_id, all_items=values.all, item_ids=values.dream_item_ids)
    return changed(db, trip, user)


@router.put("/trips/{trip_id}/dream-sharing")
def dream_sharing(trip_id: str, values: DreamSharing,
                  db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    trip, member = service.member_trip(db, trip_id, user.id, lock=True)
    matching.set_sharing(trip, member, values.scope_id, values.enabled)
    return changed(db, trip, user)


@router.post("/trips/{trip_id}/ideas")
def add_idea(trip_id: str, values: AddIdea, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    trip, _ = service.member_trip(db, trip_id, user.id, lock=True)
    key = service.digest(["manual", user.id, values.client_request_id])
    old = db.query(PlannerIdea).filter_by(trip_id=trip_id, identity_key=key).first()
    data = values.model_dump(exclude={"client_request_id"})
    data["source_url"] = service.safe_url(values.source_url)
    if (data["latitude"] is None) != (data["longitude"] is None):
        raise HTTPException(422, "Provide both latitude and longitude.")
    if old:
        if any(getattr(old, k) != v for k, v in data.items()):
            raise HTTPException(409, "This request was already used for another place.")
        return service.detail(db, trip, user.id)
    service.check_idea_capacity(db, trip)
    idea = PlannerIdea(trip_id=trip.id, created_by=user.id, identity_key=key, user_edited=True, **data)
    db.add(idea)
    db.flush()
    db.add(PlannerContribution(trip_id=trip.id, idea_id=idea.id, user_id=user.id,
        identity_key=f"manual:{values.client_request_id}", source_url=values.source_url))
    trip.updated_at = service.now()
    return changed(db, trip, user)


@router.post("/trips/{trip_id}/sources")
def add_source(trip_id: str, values: AddSource, background_tasks: BackgroundTasks,
               db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from .dreams import ShareDreamRequest, capture_dream, normalize_source_url
    from ..tasks.dream_enrichment_tasks import notify_enrichment
    lock_user(db, user)
    trip, _ = service.member_trip(db, trip_id, user.id, lock=True)
    source_url = normalize_source_url(values.source_url)
    share = db.query(PlannerSourceShare).filter_by(trip_id=trip.id, user_id=user.id, source_key=service.digest(source_url)).first()
    if share is None:
        if db.query(PlannerSourceShare).filter_by(trip_id=trip.id).count() >= 200:
            raise HTTPException(422, "This trip already has 200 shared reels. Add individual saved places instead.")
        share = PlannerSourceShare(trip_id=trip.id, user_id=user.id, source_url=source_url, source_key=service.digest(source_url))
        db.add(share)
    item, _, job = capture_dream(db, ShareDreamRequest(source_url=source_url, shared_text=values.shared_text), user.id)
    db.flush()
    service.reconcile_sources(db, trip)
    trip.updated_at = service.now()
    job_id = job.id if job else None
    result = changed(db, trip, user)
    if job_id:
        background_tasks.add_task(notify_enrichment, [job_id])
    return result


@router.patch("/trips/{trip_id}/ideas/{idea_id}")
def edit_idea(trip_id: str, idea_id: str, values: EditIdea, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    trip, member = service.member_trip(db, trip_id, user.id, lock=True)
    idea = service.active_idea(db, trip_id, idea_id)
    if member.role == "contributor" and idea.created_by != user.id:
        raise HTTPException(403, "Only the place's contributor or an editor can change it.")
    for key, value in values.model_dump(exclude_unset=True).items():
        if value is None and key in {"duration_minutes", "must_do", "title"}:
            raise HTTPException(422, "This field cannot be empty.")
        setattr(idea, key, value)
    if any(key in values.model_fields_set for key in ("title", "city", "country")):
        idea.user_edited = True
    if values.title:
        idea.status = "ready"
    trip.updated_at = service.now()
    return changed(db, trip, user)


@router.delete("/trips/{trip_id}/ideas/{idea_id}")
def delete_idea(trip_id: str, idea_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    trip, member = service.member_trip(db, trip_id, user.id, lock=True)
    idea = service.active_idea(db, trip_id, idea_id)
    if member.role == "contributor" and idea.created_by != user.id:
        raise HTTPException(403, "Only the place's contributor or an editor can remove it.")
    if trip.accepted_revision_id:
        plan = db.get(PlannerRevision, trip.accepted_revision_id).plan
        if idea.id in service.plan_idea_ids(plan):
            raise HTTPException(409, "Remove this place or stay from the plan first.")
    idea.deleted_at = service.now()
    trip.updated_at = service.now()
    return changed(db, trip, user)


@router.put("/trips/{trip_id}/ideas/{idea_id}/vote")
def vote(trip_id: str, idea_id: str, values: Vote, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    trip, _ = service.member_trip(db, trip_id, user.id, lock=True)
    service.active_idea(db, trip_id, idea_id)
    row = db.get(PlannerVote, (idea_id, user.id))
    if values.value == 0:
        if row:
            db.delete(row)
    elif row:
        row.value = values.value
    else:
        db.add(PlannerVote(idea_id=idea_id, user_id=user.id, value=values.value))
    trip.updated_at = service.now()
    return changed(db, trip, user)


@router.get("/trips/{trip_id}/ideas/{idea_id}/thumbnail")
def thumbnail(trip_id: str, idea_id: str, width: int | None = Query(default=240),
              db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from .dreams import dream_thumbnail_response
    service.member_trip(db, trip_id, user.id)
    service.active_idea(db, trip_id, idea_id)
    item = (db.query(DreamItem).join(PlannerContribution, PlannerContribution.dream_item_id == DreamItem.id)
        .filter(PlannerContribution.trip_id == trip_id, PlannerContribution.idea_id == idea_id,
                PlannerContribution.user_id == DreamItem.user_id)
        .options(selectinload(DreamItem.source_post).selectinload(DreamSourcePost.items)).first())
    if not item:
        raise HTTPException(404, "This place has no saved photo.")
    author = db.get(User, item.user_id)
    result = dream_thumbnail_response(item, db, author, width)
    # A revoked member must not keep a long-lived HTTP cache of group-only images.
    result.headers["Cache-Control"] = "private, no-cache"
    return result


@router.post("/trips/{trip_id}/generate", status_code=202)
def generate(trip_id: str, values: Generate, background_tasks: BackgroundTasks,
             db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    lock_user(db, user)
    trip, _ = service.member_trip(db, trip_id, user.id, edit=True, lock=True)
    service.reconcile_sources(db, trip)
    job = service.enqueue_plan(db, trip, user, values.model_dump())
    output = service.job_out(job)
    job_id, queued = job.id, job.status == "queued"
    db.commit()
    if queued:
        background_tasks.add_task(service.notify_jobs, [job_id])
    return output


@router.get("/trips/{trip_id}/jobs/{job_id}")
def get_job(trip_id: str, job_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    service.member_trip(db, trip_id, user.id)
    row = db.query(PlannerJob).filter_by(id=job_id, trip_id=trip_id).first()
    if not row:
        raise HTTPException(404, "Planning request not found.")
    return service.job_out(row)


@router.put("/trips/{trip_id}/plan")
def edit_plan(trip_id: str, values: EditPlan, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    trip, _ = service.member_trip(db, trip_id, user.id, edit=True, lock=True)
    service.save_revision(db, trip, user.id, values.plan, expected_version=values.expected_version)
    return changed(db, trip, user)


@router.post("/trips/{trip_id}/draft/accept")
def accept_draft(trip_id: str, values: RevisionAction, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    trip, _ = service.member_trip(db, trip_id, user.id, edit=True, lock=True)
    service.check_version(trip, values.expected_version)
    row = db.query(PlannerRevision).filter_by(id=values.revision_id, trip_id=trip.id).first()
    if row is None or trip.draft_revision_id != row.id:
        raise HTTPException(409, "That draft is no longer current. Review the latest draft.")
    service.check_version(trip, row.base_version)
    service.save_revision(db, trip, user.id, row.plan, source=row.source, expected_version=values.expected_version)
    return changed(db, trip, user)


@router.delete("/trips/{trip_id}/draft")
def dismiss_draft(trip_id: str, values: Version, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    trip, _ = service.member_trip(db, trip_id, user.id, edit=True, lock=True)
    service.check_version(trip, values.expected_version)
    trip.draft_revision_id = None
    trip.updated_at = service.now()
    return changed(db, trip, user)


@router.get("/trips/{trip_id}/history")
def history(trip_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    service.member_trip(db, trip_id, user.id)
    rows = (db.query(PlannerRevision).filter(PlannerRevision.trip_id == trip_id, PlannerRevision.accepted_at.is_not(None))
            .order_by(PlannerRevision.accepted_at.desc(), PlannerRevision.id.desc()).limit(30).all())
    return {"revisions": [service.revision_out(row) for row in rows]}


@router.post("/trips/{trip_id}/restore")
def restore(trip_id: str, values: RevisionAction, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    trip, _ = service.member_trip(db, trip_id, user.id, edit=True, lock=True)
    row = db.query(PlannerRevision).filter_by(id=values.revision_id, trip_id=trip_id).first()
    if not row or row.accepted_at is None:
        raise HTTPException(404, "Previous plan not found.")
    service.save_revision(db, trip, user.id, row.plan, source="restore", expected_version=values.expected_version)
    return changed(db, trip, user)


@router.post("/trips/{trip_id}/invites")
def create_invite(trip_id: str, values: InviteInput, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from ..crypto import encrypt_refresh_token
    trip, _ = service.member_trip(db, trip_id, user.id, owner=True, lock=True)
    fingerprint = service.digest(values.model_dump())
    old = db.query(PlannerInvite).filter_by(trip_id=trip_id, client_request_id=values.client_request_id).first()
    if old:
        if old.request_hash != fingerprint:
            raise HTTPException(409, "This request was already used for another invitation.")
        service.require_active_invite(old)
        return service.invite_link(old)
    if db.query(PlannerInvite).filter(PlannerInvite.trip_id == trip_id, PlannerInvite.created_at >= service.now() - timedelta(days=1)).count() >= 30:
        raise HTTPException(429, "You've created many invitations today. Reuse an active link or try again tomorrow.")
    email = values.recipient_email.strip().casefold() if values.recipient_email else None
    if email and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        raise HTTPException(422, "Enter a valid invitation email address.")
    token = secrets.token_urlsafe(32)
    row = PlannerInvite(trip_id=trip.id, created_by=user.id, client_request_id=values.client_request_id,
        request_hash=fingerprint, token_hash=hashlib.sha256(token.encode()).hexdigest(), token_encrypted=encrypt_refresh_token(token),
        role=values.role, label=values.label, recipient_email=email, max_uses=1 if email else 25,
        expires_at=service.now() + timedelta(days=14))
    db.add(row)
    db.flush()
    result = service.invite_link(row)
    db.commit()
    return result


@router.delete("/trips/{trip_id}/invites/{invite_id}")
def revoke_invite(trip_id: str, invite_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    trip, _ = service.member_trip(db, trip_id, user.id, owner=True, lock=True)
    row = db.query(PlannerInvite).filter_by(id=invite_id, trip_id=trip_id).with_for_update().first()
    if row is None:
        raise HTTPException(404, "Invitation not found.")
    row.revoked_at = row.revoked_at or service.now()
    return changed(db, trip, user)


@router.post("/invites/resolve")
def resolve_invite(values: TokenInput, response: Response, db: Session = Depends(get_db)):
    response.headers["Cache-Control"] = "no-store"
    return service.invite_preview(db, values.token)


@router.post("/invites/accept")
def join_invite(values: TokenInput, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    trip = service.accept_invite(db, values.token, user)
    return changed(db, trip, user)


# Legacy path aliases remain for callers already using the original contract.
@router.get("/invites/{token}", include_in_schema=False)
def preview_invite_alias(token: str, response: Response, db: Session = Depends(get_db)):
    response.headers["Cache-Control"] = "no-store"
    return service.invite_preview(db, token)


@router.post("/invites/{token}/accept", include_in_schema=False)
def accept_invite_alias(token: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    trip = service.accept_invite(db, token, user)
    return changed(db, trip, user)


@router.patch("/trips/{trip_id}/members/{user_id}")
def change_role(trip_id: str, user_id: int, values: RoleInput, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    trip, _ = service.member_trip(db, trip_id, user.id, owner=True, lock=True)
    member = db.get(PlannerMember, (trip_id, user_id))
    if member is None or member.removed_at:
        raise HTTPException(404, "Traveller not found.")
    if member.role == "owner":
        raise HTTPException(422, "The organiser's role cannot be changed here.")
    member.role = values.role
    trip.updated_at = service.now()
    return changed(db, trip, user)


@router.delete("/trips/{trip_id}/members/{user_id}")
def remove_member(trip_id: str, user_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    trip, member = service.member_trip(db, trip_id, user.id, lock=True)
    if member.role != "owner" and user_id != user.id:
        raise HTTPException(403, "Only the organiser can remove another traveller.")
    target = db.get(PlannerMember, (trip_id, user_id))
    if target is None or target.removed_at:
        raise HTTPException(404, "Traveller not found.")
    if target.role == "owner":
        raise HTTPException(422, "The organiser cannot leave their own trip.")
    idea_ids = db.query(PlannerIdea.id).filter_by(trip_id=trip_id)
    db.query(PlannerVote).filter(PlannerVote.user_id == user_id, PlannerVote.idea_id.in_(idea_ids)).delete(synchronize_session=False)
    target.removed_at = service.now()
    matching.disable(target)
    trip.updated_at = service.now()
    if user_id == user.id:
        db.commit()
        return {"left": True, "trip_id": trip_id}
    return changed(db, trip, user)


def booking_choices(db, trip, user):
    rows = db.query(Segment).join(Trip, Segment.trip_id == Trip.id).filter(Trip.user_id == user.id).all()
    tz = ZoneInfo(trip.timezone)
    choices = []
    for row in rows:
        start = service.aware(row.dep_time).astimezone(tz)
        end = service.aware(row.arr_time).astimezone(tz)
        if trip.start_date <= start.date().isoformat() <= trip.end_date:
            choices.append({"segment_id": str(row.id), "title": f"Flight {row.dep_airport} to {row.arr_airport}",
                "date": start.date().isoformat(), "start_time": start.strftime("%H:%M"),
                "duration_minutes": max(5, round((service.aware(row.arr_time).astimezone(timezone.utc) -
                    service.aware(row.dep_time).astimezone(timezone.utc)).total_seconds()/60)), "flight_number": row.flight_number})
    return sorted(choices, key=lambda r: (r["date"], r["start_time"]))[:50]


@router.get("/trips/{trip_id}/bookings")
def get_bookings(trip_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    trip, _ = service.member_trip(db, trip_id, user.id, edit=True)
    return {"bookings": booking_choices(db, trip, user)}


@router.post("/trips/{trip_id}/bookings/import")
def import_bookings(trip_id: str, values: ImportBookings, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from copy import deepcopy
    from datetime import date
    trip, _ = service.member_trip(db, trip_id, user.id, edit=True, lock=True)
    choices = {i["segment_id"]: i for i in booking_choices(db, trip, user)}
    if not set(values.segment_ids) <= choices.keys():
        raise HTTPException(404, "A selected booking is not available in this trip's dates.")
    accepted = db.get(PlannerRevision, trip.accepted_revision_id) if trip.accepted_revision_id else None
    plan = deepcopy(accepted.plan) if accepted else {"days": [], "warnings": [], "unplaced_idea_ids": []}
    start = date.fromisoformat(trip.start_date)
    days = {day["date"]: day for day in plan["days"]}
    for i in range((date.fromisoformat(trip.end_date) - start).days + 1):
        day = (start + timedelta(days=i)).isoformat()
        days.setdefault(day, {"date": day, "stops": []})
    existing_ids = {s["id"] for day in days.values() for s in day["stops"]}
    for segment_id in dict.fromkeys(values.segment_ids):
        booking = choices[segment_id]
        # Stable identity is a snapshot of explicitly shared facts, not a FK to rebuilt flight groups.
        stop_id = "booking-" + service.digest([user.id, booking["title"], booking["date"], booking["start_time"], booking["flight_number"]])[:24]
        if stop_id in existing_ids:
            continue
        days[booking["date"]]["stops"].append({"id": stop_id, "title": booking["title"],
            "start_time": booking["start_time"], "duration_minutes": booking["duration_minutes"],
            "locked": True, "kind": "booking", "notes": booking["flight_number"] or ""})
    plan["days"] = sorted(days.values(), key=lambda d: d["date"])
    for day in plan["days"]:
        day["stops"].sort(key=lambda s: s["start_time"])
    service.save_revision(db, trip, user.id, plan, expected_version=values.expected_version)
    return changed(db, trip, user)
