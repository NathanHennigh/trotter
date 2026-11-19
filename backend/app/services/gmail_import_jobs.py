"""Reserve, dispatch and resume mailbox imports."""
import logging
import os
from datetime import datetime, timedelta, timezone
from uuid import NAMESPACE_URL, uuid4, uuid5

from fastapi import BackgroundTasks
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from ..models import SyncJob
from ..tasks.import_tasks import run_gmail_import

logger = logging.getLogger(__name__)
QUEUE_ERROR = "The flight scan could not start. Try scanning again."


def _first_job_id(user_id: int) -> str:
    # A stable idempotency key also lets older clients adopt the automatic job
    # when the user taps Scan. Ordinary and bounded imports keep their own IDs.
    return str(uuid5(NAMESPACE_URL, f"urn:trotter:gmail:first-import:{user_id}"))


def active_mailbox_import(db: Session, user_id: int, *, automatic_only: bool = False) -> SyncJob | None:
    kinds = ("daily",) if automatic_only else ("mailbox", "daily")
    return db.query(SyncJob).filter(
        SyncJob.user_id == user_id,
        or_(SyncJob.id == _first_job_id(user_id), SyncJob.kind.in_(kinds)),
        SyncJob.state.in_(("pending", "running")),
        SyncJob.updated_at >= datetime.now(timezone.utc) - timedelta(days=1),
    ).order_by(SyncJob.started_at.desc()).first()


def last_mailbox_scan(db: Session, user_id: int) -> datetime | None:
    return db.query(func.max(SyncJob.updated_at)).filter(
        SyncJob.user_id == user_id, SyncJob.state == "completed",
        or_(SyncJob.id == _first_job_id(user_id), SyncJob.kind.in_(("mailbox", "daily"))),
    ).scalar()


def new_import(db: Session, user_id: int, *, first: bool = False, kind: str | None = None) -> SyncJob:
    now = datetime.now(timezone.utc)
    job = SyncJob(id=_first_job_id(user_id) if first else str(uuid4()), user_id=user_id,
                  state="pending", kind=kind, started_at=now, updated_at=now)
    db.add(job)
    return job


def reserve_first_import(db: Session, user_id: int) -> SyncJob | None:
    """Called under the Gmail owner's row lock, in the grant transaction."""
    if db.query(SyncJob.id).filter(SyncJob.user_id == user_id, SyncJob.kind.is_distinct_from("daily")).first() is None:
        return new_import(db, user_id, first=True, kind="mailbox")
    return None


def dispatch_import(db: Session, job: SyncJob, background: BackgroundTasks | None = None, *,
                    limit: int | None = None, mode: str | None = None) -> bool:
    """The caller commits first so the worker can see the job and credentials."""
    args = dict(job_id=job.id, user_id=job.user_id, limit=limit, mode=mode)
    if background is not None and any(os.getenv(key, "").lower() in ("1", "true", "yes")
           for key in ("CELERY_TASK_ALWAYS_EAGER", "DEV_MODE")):
        background.add_task(run_gmail_import.run, **args)
        return True
    try:
        if job.kind == "daily" and os.getenv("TROTTER_PARSER_PILOT_ROUTING") == "1":
            run_gmail_import.apply_async(kwargs=args, queue="flight_parser_pilot")
        else:
            run_gmail_import.delay(**args)
    except Exception:
        logger.exception("Could not dispatch Gmail import %s", job.id)
        db.query(SyncJob).filter_by(id=job.id, state="pending").update(
            {"state": "failed", "error_message": QUEUE_ERROR, "updated_at": datetime.now(timezone.utc)},
            synchronize_session=False,
        )
        db.commit()
        return False
    return True
