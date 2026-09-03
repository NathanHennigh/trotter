import os
from celery import Celery


def create_celery_app() -> Celery:
	redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
	broker_url = os.getenv("CELERY_BROKER_URL", redis_url)
	backend_url = os.getenv("CELERY_RESULT_BACKEND", redis_url)
	app = Celery(
		"travelstrava",
		broker=broker_url,
		backend=backend_url,
		include=["app.tasks.example", "app.tasks.import_tasks"],
	)

	app.conf.update(
		task_serializer="json",
		result_serializer="json",
		accept_content=["json"],
		timezone="UTC",
		enable_utc=True,
		task_always_eager=os.getenv("CELERY_TASK_ALWAYS_EAGER", "").lower() in ("1", "true", "yes"),
		task_eager_propagates=True,
	)
	return app


celery_app = create_celery_app()


