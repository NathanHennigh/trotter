from fastapi.testclient import TestClient

from app.main import app


def test_health_endpoint_ok():
	client = TestClient(app)
	resp = client.get("/health")
	assert resp.status_code == 200
	assert resp.json() == {"status": "ok"}


def test_ready_endpoint_ok(monkeypatch):
	monkeypatch.setattr("app.routers.health._database_ready", lambda: True)
	monkeypatch.setattr("app.routers.health._redis_ready", lambda: True)
	client = TestClient(app)
	resp = client.get("/ready")
	assert resp.status_code == 200
	assert resp.json() == {
		"status": "ready",
		"checks": {"database": True, "redis": True},
	}


def test_ready_endpoint_reports_unavailable_dependency(monkeypatch):
	monkeypatch.setattr("app.routers.health._database_ready", lambda: True)
	monkeypatch.setattr("app.routers.health._redis_ready", lambda: False)
	client = TestClient(app)
	resp = client.get("/ready")
	assert resp.status_code == 503
	assert resp.json()["status"] == "not_ready"


