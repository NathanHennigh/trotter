from ..celery_app import celery_app


@celery_app.task(name="app.tasks.gmail_history_tasks.scan_history_page", soft_time_limit=300, time_limit=330)
def scan_history_page(state_id: int, user_id: int):
    from uuid import uuid4
    from ..db import SessionLocal
    from ..models import GmailHistoryState, SyncJob, User
    from ..services.gmail_history import fail_history_page, user_enabled
    from .import_tasks import run_gmail_import
    if not user_enabled(user_id):
        return {"state": "disabled"}
    with SessionLocal() as db:
        row = (db.query(GmailHistoryState).filter_by(id=state_id, user_id=user_id, state="queued")
               .with_for_update(skip_locked=True).first())
        if row is None or db.get(User, user_id) is None:
            return {"state": "unavailable"}
        row.state = "running"
        job_id = str(uuid4())
        db.add(SyncJob(id=job_id, user_id=user_id, state="pending"))
        db.commit()
    result = run_gmail_import.run(job_id=job_id, user_id=user_id, limit=50, mode="history", history_state_id=state_id)
    if not result or result.get("error"):
        with SessionLocal() as db:
            fail_history_page(db, state_id, (result or {}).get("error", "history_worker_retry"))
            db.commit()
    return result


@celery_app.task(name="app.tasks.gmail_history_tasks.discover_history", soft_time_limit=40, time_limit=45)
def discover_history():
    from ..db import SessionLocal
    from ..services.gmail_history import discover_history_jobs
    with SessionLocal() as db:
        jobs = discover_history_jobs(db)
    for state_id, user_id in jobs:
        scan_history_page.apply_async(args=[state_id, user_id], retry=False)
    return len(jobs)
