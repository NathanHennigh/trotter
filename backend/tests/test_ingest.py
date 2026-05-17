"""Tests for the ingest router: POST /ingest/gmail/import and GET /ingest/jobs/{job_id}."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import get_db
from app.main import app
from app.models import Message, MessageStatus, SyncJob, User
from app.routers.auth import get_current_user


# ────────────────────────── shared fixtures ───────────────────────────────────


@pytest.fixture
def test_db():
    """In-memory SQLite DB wired into the app for the duration of the test.

    Only creates the tables relevant to ingest tests (no PostGIS Geography columns).
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,  # reuse the same connection so in-memory DB persists
    )
    # Create only the tables used by ingest tests (avoids PostGIS columns in segments)
    User.__table__.create(engine)
    SyncJob.__table__.create(engine)
    Message.__table__.create(engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override_get_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    session = Session()
    yield session
    session.close()
    app.dependency_overrides.pop(get_db, None)
    Message.__table__.drop(engine)
    SyncJob.__table__.drop(engine)
    User.__table__.drop(engine)


@pytest.fixture
def test_user(test_db):
    """Persist a test user and override the auth dependency to return it."""
    user = User(id=1, email="test@example.com", name="Test User")
    test_db.add(user)
    test_db.commit()
    test_db.refresh(user)

    app.dependency_overrides[get_current_user] = lambda: user
    yield user
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=True)


# ────────────────────────── auth guard tests ──────────────────────────────────


class TestIngestAuthGuard:
    def test_start_import_requires_auth(self):
        """POST /ingest/gmail/import must reject unauthenticated requests."""
        # Ensure no auth override is active
        app.dependency_overrides.pop(get_current_user, None)
        c = TestClient(app, raise_server_exceptions=False)
        response = c.post("/ingest/gmail/import")
        assert response.status_code in (401, 403)

    def test_get_job_requires_auth(self):
        """GET /ingest/jobs/{id} must reject unauthenticated requests."""
        app.dependency_overrides.pop(get_current_user, None)
        c = TestClient(app, raise_server_exceptions=False)
        response = c.get("/ingest/jobs/some-uuid")
        assert response.status_code in (401, 403)


# ────────────────────────── start import tests ───────────────────────────────


class TestStartImport:
    @patch.dict("os.environ", {"DEV_MODE": "false", "CELERY_TASK_ALWAYS_EAGER": "false"})
    @patch("app.routers.ingest.run_gmail_import")
    def test_creates_sync_job_and_returns_job_id(self, mock_task, client, test_user, test_db):
        """POST /ingest/gmail/import should create a SyncJob row and return its ID."""
        mock_task.delay = MagicMock()

        response = client.post("/ingest/gmail/import")

        assert response.status_code == 200
        data = response.json()
        assert "job_id" in data
        assert len(data["job_id"]) > 0

        # SyncJob row must exist in DB
        job = test_db.query(SyncJob).filter(SyncJob.id == data["job_id"]).first()
        assert job is not None
        assert job.user_id == test_user.id
        assert job.state == "pending"
        assert job.scanned_count == 0

    @patch.dict("os.environ", {"DEV_MODE": "false", "CELERY_TASK_ALWAYS_EAGER": "false"})
    @patch("app.routers.ingest.run_gmail_import")
    def test_dispatches_celery_task(self, mock_task, client, test_user, test_db):
        """POST /ingest/gmail/import must enqueue the run_gmail_import task."""
        mock_task.delay = MagicMock()

        response = client.post("/ingest/gmail/import")
        assert response.status_code == 200

        mock_task.delay.assert_called_once()
        kwargs = mock_task.delay.call_args.kwargs
        assert kwargs["job_id"] == response.json()["job_id"]
        assert kwargs["user_id"] == test_user.id
        assert kwargs["limit"] is None

    @patch.dict("os.environ", {"DEV_MODE": "true", "CELERY_TASK_ALWAYS_EAGER": "false"})
    @patch("app.routers.ingest.run_gmail_import")
    def test_dev_mode_dispatches_background_task(self, mock_task, client, test_user, test_db):
        mock_task.run = MagicMock()

        response = client.post("/ingest/gmail/import?limit=25")
        assert response.status_code == 200

        mock_task.run.assert_called_once()
        kwargs = mock_task.run.call_args.kwargs
        assert kwargs["job_id"] == response.json()["job_id"]
        assert kwargs["user_id"] == test_user.id
        assert kwargs["limit"] == 25

    @patch.dict("os.environ", {"DEV_MODE": "false", "CELERY_TASK_ALWAYS_EAGER": "false"})
    @patch("app.routers.ingest.run_gmail_import")
    def test_multiple_imports_create_separate_jobs(self, mock_task, client, test_user, test_db):
        """Each POST should create an independent SyncJob with a unique ID."""
        mock_task.delay = MagicMock()

        r1 = client.post("/ingest/gmail/import")
        r2 = client.post("/ingest/gmail/import")

        assert r1.status_code == 200
        assert r2.status_code == 200
        assert r1.json()["job_id"] != r2.json()["job_id"]

        assert test_db.query(SyncJob).filter(SyncJob.user_id == test_user.id).count() == 2


# ────────────────────────── job status tests ─────────────────────────────────


class TestJobStatus:
    def test_returns_404_for_unknown_job(self, client, test_user):
        response = client.get("/ingest/jobs/00000000-0000-0000-0000-000000000000")
        assert response.status_code == 404

    def test_returns_job_state(self, client, test_user, test_db):
        """GET /ingest/jobs/{id} should return the stored job fields."""
        now = datetime.now(timezone.utc)
        job = SyncJob(
            id="test-job-123",
            user_id=test_user.id,
            state="completed",
            scanned_count=42,
            parsed_count=10,
            segment_count=15,
            started_at=now,
            updated_at=now,
        )
        test_db.add(job)
        test_db.commit()

        response = client.get("/ingest/jobs/test-job-123")

        assert response.status_code == 200
        data = response.json()
        assert data["job_id"] == "test-job-123"
        assert data["state"] == "completed"
        assert data["scanned_count"] == 42
        assert data["parsed_count"] == 10
        assert data["segment_count"] == 15
        assert data["error_message"] is None

    def test_cannot_see_another_users_job(self, client, test_user, test_db):
        """A user must not be able to access a job that belongs to a different user."""
        other_user = User(id=99, email="other@example.com", name="Other")
        test_db.add(other_user)
        job = SyncJob(
            id="other-job-id",
            user_id=99,
            state="running",
            scanned_count=0,
            parsed_count=0,
            segment_count=0,
        )
        test_db.add(job)
        test_db.commit()

        response = client.get("/ingest/jobs/other-job-id")
        assert response.status_code == 404


class TestUnparsedCandidates:
    def test_lists_review_required_parse_misses(self, client, test_user, test_db):
        msg = Message(
            user_id=test_user.id,
            provider_msg_id="gmail-1",
            from_email="Airline <noreply@example.com>",
            subject="Your flight confirmation",
            status=MessageStatus.REVIEW_REQUIRED,
            parse_version=7,
            parse_error="strong_flight_evidence_but_no_segments",
            parse_evidence={"score": 9, "signals": ["flight_number", "date"]},
        )
        accepted = Message(
            user_id=test_user.id,
            provider_msg_id="gmail-2",
            subject="Parsed flight",
            status=MessageStatus.ACCEPTED,
            parse_version=7,
        )
        test_db.add_all([msg, accepted])
        test_db.commit()

        response = client.get("/ingest/unparsed-candidates")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["candidates"][0]["provider_msg_id"] == "gmail-1"
        assert data["candidates"][0]["parse_evidence"]["score"] == 9
