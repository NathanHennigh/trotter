from ..celery_app import celery_app


@celery_app.task(name="app.tasks.travel_name_tasks.recover_travel_names", soft_time_limit=240, time_limit=270)
def recover_travel_names(job_id):
    from ..services.travel_name_recovery import run_recovery
    run_recovery(job_id)


@celery_app.task(name="app.tasks.travel_name_tasks.discover_travel_name_recovery", soft_time_limit=50, time_limit=55)
def discover_travel_name_recovery():
    from ..db import SessionLocal
    from ..services.travel_name_recovery import discover_recoveries
    with SessionLocal() as db:
        ids = discover_recoveries(db)
    for job_id in ids:
        recover_travel_names.apply_async(args=[job_id], retry=False)
    return len(ids)
