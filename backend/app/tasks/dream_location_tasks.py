"""Redis notifications accelerate durable database work; periodic recovery is authoritative."""
from __future__ import annotations

import asyncio
import os

from app.celery_app import celery_app
from app.db import SessionLocal
from app.services.dream_locations import due_jobs, queue_missing, resolve_location_job, setting, utcnow


def enabled():
    return os.getenv("DREAM_LOCATION_ENABLED", "true").lower() in {"1", "true", "yes"}


def dispatch_pending_locations(*, session_factory=None, publish=None, now=None):
    """Safe after lost broker messages, expired worker leases, and ordinary restarts."""
    if not enabled():
        return {"queued": 0, "dispatched": 0, "enabled": False}
    session_factory = session_factory or SessionLocal
    publish = publish or resolve_dream_location.delay
    now = now or utcnow()
    with session_factory() as db:
        discovery = queue_missing(db, limit=setting("DREAM_LOCATION_BATCH_SIZE", 25, 100), only_undiscovered=True, now=now)
        jobs = due_jobs(db, now=now, limit=setting("DREAM_LOCATION_BATCH_SIZE", 25, 100))
        ids = [row.id for row in jobs]
        for row in jobs:
            row.last_dispatched_at = now
        db.commit()
    dispatched = 0
    for job_id in ids:
        try:
            publish(job_id)
            dispatched += 1
        except Exception:
            # Do not log broker credentials or payloads. Durable rows remain due;
            # the next tick retries notification after the 60-second dispatch lease.
            continue
    return {"queued": discovery["queued"], "dispatched": dispatched, "enabled": True}


@celery_app.task(name="app.tasks.dream_location_tasks.discover_dream_locations", ignore_result=True)
def discover_dream_locations():
    return dispatch_pending_locations()


@celery_app.task(name="app.tasks.dream_location_tasks.resolve_dream_location", ignore_result=True,
                 acks_late=True, reject_on_worker_lost=True, soft_time_limit=90, time_limit=100)
def resolve_dream_location(job_id: int):
    if not enabled():
        return "disabled"
    return asyncio.run(resolve_location_job(job_id))
