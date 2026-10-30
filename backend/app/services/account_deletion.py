"""Account erasure: private data is removed, shared places lose attribution.

Owned shared trips are deleted rather than silently assigning ownership to a
friend. The app confirms that consequence before reauthenticating the owner.
"""
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
import httpx
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.orm import Session

from ..crypto import decrypt_refresh_token
from ..models import (Account, AccountErasureCleanup, AuthIdentity, BookingObservation,
                      DreamItem, FlightShare, TravelInboxEvidence, User)
from ..planner_models import (PlannerContribution, PlannerInvite, PlannerJob,
                              PlannerMember, PlannerRevision, PlannerTrip)
from . import apple_auth
from .auth_identities import verified_emails
from .dream_thumbnail_cache import thumbnail_cache_dir


def preview(db: Session, user_id: int) -> dict:
    owned = select(PlannerTrip.id).where(PlannerTrip.owner_id == user_id)
    shared = db.query(PlannerMember.trip_id).filter(PlannerMember.trip_id.in_(owned),
        PlannerMember.user_id != user_id, PlannerMember.removed_at.is_(None)).distinct().count()
    return {"owned_trips": db.query(PlannerTrip).filter_by(owner_id=user_id).count(), "shared_owned_trips": shared}


async def revoke_connections(db: Session, user_id: int) -> None:
    apple = db.query(AuthIdentity).filter_by(user_id=user_id, provider="apple").first()
    try:
        if apple:
            if not apple.refresh_token_encrypted:
                raise HTTPException(409, "apple_reauthentication_required")
            await apple_auth.revoke_refresh_token(decrypt_refresh_token(apple.refresh_token_encrypted))
        for account in db.query(Account).filter_by(user_id=user_id, provider="google"):
            if not account.refresh_token_encrypted:
                continue
            token = decrypt_refresh_token(account.refresh_token_encrypted)
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.post("https://oauth2.googleapis.com/revoke", data={"token": token})
            if response.status_code == 400 and response.json().get("error") == "invalid_token":
                continue
            if response.status_code != 200:
                raise HTTPException(503, "account_deletion_retry")
    except (ValueError, httpx.RequestError) as exc:
        raise HTTPException(503, "account_deletion_retry") from exc


def _without_person(value, user_id: int, emails: set[str]):
    """Strip provider/member references from historical plan input snapshots."""
    if isinstance(value, dict):
        if str(value.get("user_id", "")) == str(user_id):
            return None
        return {key: (None if key in {"created_by", "owner_id"} and str(item) == str(user_id)
                      else _without_person(item, user_id, emails)) for key, item in value.items()}
    if isinstance(value, list):
        return [cleaned for item in value if (cleaned := _without_person(item, user_id, emails)) is not None]
    if isinstance(value, str) and value.casefold() in emails:
        return None
    return value


def erase_database(db: Session, user: User) -> str:
    """Caller owns a user lock and commits the account and cleanup job together."""
    user_id = user.id
    emails = verified_emails(db, user)
    item_ids = [row[0] for row in db.query(DreamItem.id).filter_by(user_id=user_id)]
    cleanup = AccountErasureCleanup(thumbnail_item_ids=item_ids)
    db.add(cleanup)
    db.flush()
    affected = [row[0] for row in db.query(PlannerMember.trip_id).filter_by(user_id=user_id)]
    # Invalidate in-flight plan writes before deleting votes/membership.
    if affected:
        db.execute(update(PlannerTrip).where(PlannerTrip.id.in_(affected)).values(
            version=PlannerTrip.version + 1, updated_at=datetime.now(timezone.utc)))
        for row in db.query(PlannerJob).filter(PlannerJob.trip_id.in_(affected), PlannerJob.user_id != user_id):
            row.input_json = _without_person(row.input_json, user_id, emails)
        for row in db.query(PlannerRevision).filter(PlannerRevision.trip_id.in_(affected)):
            row.plan = _without_person(row.plan, user_id, emails)
    # RESTRICT evidence references must be removed before observations cascade.
    db.execute(delete(TravelInboxEvidence).where(TravelInboxEvidence.observation_id.in_(
        select(BookingObservation.id).where(BookingObservation.user_id == user_id))))
    db.execute(delete(PlannerContribution).where(PlannerContribution.user_id == user_id))
    db.execute(delete(PlannerInvite).where(or_(PlannerInvite.created_by == user_id,
        func.lower(PlannerInvite.recipient_email).in_(emails))))
    db.execute(delete(FlightShare).where(or_(FlightShare.recipient_user_id == user_id,
        func.lower(FlightShare.recipient_email).in_(emails))))
    db.flush()
    # Database CASCADE / SET NULL covers all private rows and shared attribution.
    db.execute(delete(User).where(User.id == user_id), execution_options={"synchronize_session": False})
    return cleanup.id


def clean_thumbnails(db: Session, cleanup_id: str | None = None) -> int:
    """Retry for 24 hours to catch a thumbnail request already running at erasure."""
    query = db.query(AccountErasureCleanup).order_by(AccountErasureCleanup.last_swept_at.asc().nullsfirst(), AccountErasureCleanup.created_at)
    if cleanup_id:
        query = query.filter_by(id=cleanup_id)
    cleaned = 0
    for row in query.limit(100):
        row.last_swept_at = datetime.now(timezone.utc)
        try:
            root = thumbnail_cache_dir()
            for item_id in row.thumbnail_item_ids:
                if type(item_id) is not int or item_id <= 0:
                    continue
                paths = [root / f"{item_id}.bin", root / f"{item_id}.json", *root.glob(f"{item_id}-*.webp")]
                for path in paths:
                    path.unlink(missing_ok=True)
            created = row.created_at.replace(tzinfo=timezone.utc) if row.created_at.tzinfo is None else row.created_at
            if created < datetime.now(timezone.utc) - timedelta(days=1):
                db.delete(row)
            cleaned += 1
        except OSError:
            # Keep this durable row for the next worker pass; account stays gone.
            continue
    db.commit()
    return cleaned
