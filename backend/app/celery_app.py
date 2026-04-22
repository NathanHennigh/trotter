import os
from celery import Celery


def create_celery_app() -> Celery:
	broker_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
	backend_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
	app = Celery(
		"travelstrava",
		broker=broker_url,
		backend=backend_url,
		include=["app.tasks.example"],
	)

	app.conf.update(
		task_serializer="json",
		result_serializer="json",
		accept_content=["json"],
		timezone="UTC",
		enable_utc=True,
	)
	return app


celery_app = create_celery_app()


