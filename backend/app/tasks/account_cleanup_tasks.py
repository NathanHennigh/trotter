from ..celery_app import celery_app


@celery_app.task(name="app.tasks.account_cleanup_tasks.clean_erased_accounts", soft_time_limit=50, time_limit=55)
def clean_erased_accounts():
    from ..db import SessionLocal
    from ..services.account_deletion import clean_thumbnails
    with SessionLocal() as db:
        return clean_thumbnails(db)
