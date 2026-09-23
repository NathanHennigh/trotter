"""Redis accelerates the durable database queue; scheduler ticks recover lost delivery."""
import os

from app.celery_app import celery_app
from app.db import SessionLocal
from app.services.dream_enrichment import discover_enrichment, due_enrichment_jobs, resolve_enrichment_job
from app.services.dream_locations import setting, utcnow


def enabled():
    return os.getenv("DREAM_ENRICHMENT_ENABLED", "true").lower() in {"1", "true", "yes"}


def notify_enrichment(job_ids):
    """Best-effort wakeup after HTTP response and database commit."""
    if not enabled():
        return
    for job_id in job_ids:
        try:
            process_dream_enrichment.apply_async(args=[job_id], retry=False)
        except Exception:
            # Do not log broker URLs/credentials. The next scheduler tick retries.
            return


def dispatch_pending_enrichment(*, session_factory=None, publish=None, now=None):
    if not enabled():
        return {"queued": 0, "dispatched": 0, "enabled": False}
    session_factory = session_factory or SessionLocal
    publish = publish or (lambda job_id: process_dream_enrichment.apply_async(args=[job_id], retry=False))
    now = now or utcnow()
    with session_factory() as db:
        limit = setting("DREAM_ENRICHMENT_BATCH_SIZE", 25, 100)
        queued = discover_enrichment(db, now=now, limit=limit)
        rows = due_enrichment_jobs(db, now=now, limit=limit)
        ids = [row.id for row in rows]
        for row in rows:
            row.last_dispatched_at = now
        db.commit()
    sent = 0
    for job_id in ids:
        try:
            publish(job_id)
            sent += 1
        except Exception:
            continue
    return {"queued": queued, "dispatched": sent, "enabled": True}


@celery_app.task(name="app.tasks.dream_enrichment_tasks.discover_dream_enrichment", ignore_result=True)
def discover_dream_enrichment():
    return dispatch_pending_enrichment()


@celery_app.task(name="app.tasks.dream_enrichment_tasks.process_dream_enrichment", ignore_result=True,
                 acks_late=True, reject_on_worker_lost=True, soft_time_limit=210, time_limit=240)
def process_dream_enrichment(job_id):
    if not enabled():
        return "disabled"
    return resolve_enrichment_job(job_id)
