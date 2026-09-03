import os

from fastapi import APIRouter, Response, status
from redis import Redis
from sqlalchemy import text

from ..db import engine


router = APIRouter(tags=["health"]) 


@router.get("/health")
def health() -> dict:
	return {"status": "ok"}


def _database_ready() -> bool:
	try:
		with engine.connect() as connection:
			connection.execute(text("SELECT 1"))
		return True
	except Exception:
		return False


def _redis_ready() -> bool:
	redis_url = os.getenv("REDIS_URL") or os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")
	try:
		client = Redis.from_url(redis_url, socket_connect_timeout=2, socket_timeout=2)
		return bool(client.ping())
	except Exception:
		return False


@router.get("/ready")
def ready(response: Response) -> dict:
	checks = {"database": _database_ready(), "redis": _redis_ready()}
	if not all(checks.values()):
		response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
		return {"status": "not_ready", "checks": checks}
	return {"status": "ready", "checks": checks}


