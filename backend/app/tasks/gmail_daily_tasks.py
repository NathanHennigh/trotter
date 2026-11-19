from ..celery_app import celery_app
from ..db import SessionLocal
from ..services.gmail_daily import schedule_due


@celery_app.task(name="gmail.discover_daily")
def discover_daily():
    with SessionLocal() as db:
        return {"queued": schedule_due(db)}
