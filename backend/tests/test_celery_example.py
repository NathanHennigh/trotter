import os

import pytest

# Skip if no Redis URL is provided; avoids test flakiness when Redis isn't running
pytestmark = pytest.mark.skipif(
	os.getenv("REDIS_URL") is None,
	reason="REDIS_URL not set; skip Celery integration test",
)


def test_example_ping_task_eager(monkeypatch):
	# Run tasks eagerly to avoid needing a running worker in CI
	from app import celery_app as celery_module
	app = celery_module.create_celery_app()
	app.conf.task_always_eager = True

	from app.tasks.example import ping

	res = ping.delay({"hello": "world"})
	assert res.successful()
	assert res.get(timeout=1) == {"ok": True, "pong": True, "payload": {"hello": "world"}}


