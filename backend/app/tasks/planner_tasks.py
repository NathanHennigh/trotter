"""Recoverable generation dispatch. Paid work is never retried implicitly."""
from ..celery_app import celery_app


@celery_app.task(name="app.tasks.planner_tasks.generate_trip_plan", soft_time_limit=240, time_limit=270)
def generate_trip_plan(job_id: str):
    from ..services.planner import process_job
    process_job(job_id)


@celery_app.task(name="app.tasks.planner_tasks.discover_planner_jobs", soft_time_limit=50, time_limit=55)
def discover_planner_jobs():
    from ..services.planner import discover_jobs
    return discover_jobs()
