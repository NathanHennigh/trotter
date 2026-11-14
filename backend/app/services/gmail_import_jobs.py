"""Start the first mailbox import at consent and let any client resume it."""
import logging
import os
from datetime import datetime, timedelta, timezone
from uuid import NAMESPACE_URL, uuid4, uuid5

from fastapi import BackgroundTasks
from sqlalchemy.orm import Session

from ..models import SyncJob
from ..tasks.import_tasks import run_gmail_import

logger = logging.getLogger(__name__)
QUEUE_ERROR = "The flight scan could not start. Try scanning again."


def _first_job_id(user_id: int) -> str:
    # A stable idempotency key also lets older clients adopt the automatic job
    # when the user taps Scan. Ordinary and bounded imports keep their own IDs.
    return str(uuid5(NAMESPACE_URL, f"urn:trotter:gmail:first-import:{user_id}"))


def active_first_import(db: Session, user_id: int) -> SyncJob | None:
    return db.query(SyncJob).filter(
        SyncJob.id == _first_job_id(user_id), SyncJob.user_id == user_id,
        SyncJob.state.in_(("pending", "running")),
        SyncJob.updated_at >= datetime.now(timezone.utc) - timedelta(days=1),
    ).first()


def new_import(db: Session, user_id: int, *, first: bool = False) -> SyncJob:
    now = datetime.now(timezone.utc)
    job = SyncJob(id=_first_job_id(user_id) if first else str(uuid4()), user_id=user_id,
                  state="pending", started_at=now, updated_at=now)
    db.add(job)
    return job


def reserve_first_import(db: Session, user_id: int) -> SyncJob | None:
    """Called under the Gmail owner's row lock, in the grant transaction."""
    if db.query(SyncJob.id).filter_by(user_id=user_id).first() is None:
        return new_import(db, user_id, first=True)
    return None


def dispatch_import(db: Session, job: SyncJob, background: BackgroundTasks, *,
                    limit: int | None = None, mode: str | None = None) -> bool:
    """The caller commits first so the worker can see the job and credentials."""
    args = dict(job_id=job.id, user_id=job.user_id, limit=limit, mode=mode)
    if any(os.getenv(key, "").lower() in ("1", "true", "yes")
           for key in ("CELERY_TASK_ALWAYS_EAGER", "DEV_MODE")):
        background.add_task(run_gmail_import.run, **args)
        return True
    try:
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
