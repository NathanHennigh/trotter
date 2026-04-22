from time import sleep

from app.celery_app import celery_app


@celery_app.task(name="example.ping")
def ping(payload: dict | None = None) -> dict:
	"""Simple task to verify Celery+Redis plumbing.

	Returns payload with a pong and simulated latency.
	"""
	sleep(0.1)
	return {"ok": True, "pong": True, "payload": payload or {}}


