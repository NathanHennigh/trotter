"""Schedule incremental new-mail checks independently of historical recovery."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from ..models import Account, GmailDiscoveryState, SyncJob, User
from .flight_query_v4 import _ensure_utc
from .gmail_connection import connected_account_filter
from .gmail_import_jobs import dispatch_import, new_import

DAY = timedelta(days=1)
RETRY = timedelta(hours=1)
OVERLAP = timedelta(hours=1)


def daily_since(db: Session, job: SyncJob, state: GmailDiscoveryState) -> datetime:
    daily = db.query(func.max(SyncJob.started_at)).filter_by(
        user_id=job.user_id, kind="daily", state="completed",
    ).scalar()
    covered = [_ensure_utc(value) for value in (daily, state.last_incremental_scan_at) if value]
    if covered:
        return max(covered) - OVERLAP
    # Retain the original window if the very first daily check has to retry.
    first_attempt = db.query(func.min(SyncJob.started_at)).filter_by(user_id=job.user_id, kind="daily").scalar()
    return _ensure_utc(first_attempt or job.started_at) - DAY


def due_users(db: Session, now: datetime):
    recent_import = db.query(SyncJob.id).filter(SyncJob.user_id == User.id, or_(
        and_(SyncJob.state.in_(("pending", "running")), SyncJob.updated_at >= now - DAY),
        and_(SyncJob.kind == "daily", SyncJob.state == "completed", SyncJob.started_at >= now - DAY),
        and_(SyncJob.kind == "daily", SyncJob.updated_at >= now - RETRY),
    )).exists()
    manual_coverage = db.query(GmailDiscoveryState.id).filter(
        GmailDiscoveryState.user_id == User.id, GmailDiscoveryState.provider == "google",
        GmailDiscoveryState.last_incremental_scan_at >= now - DAY,
    ).exists()
    connected = db.query(Account.id).filter(Account.user_id == User.id, connected_account_filter()).exists()
    return db.query(User.id).filter(connected, ~recent_import, ~manual_coverage)


def schedule_due(db: Session, *, now=None, limit=25) -> int:
    now = now or datetime.now(timezone.utc)
    ids = [uid for uid, in due_users(db, now).order_by(User.id).limit(limit)]
    sent = 0
    for uid in ids:
        # Consent, the manual Scan endpoint and competing schedulers share this lock.
        owner = db.query(User.id).filter(User.id == uid).with_for_update(skip_locked=True).first()
        if owner is None or not due_users(db, now).filter(User.id == uid).first():
            db.rollback()
            continue
        job = new_import(db, uid, kind="daily")
        db.commit()
        sent += int(dispatch_import(db, job, limit=0))
    return sent
