"""Exercise real mailbox worker paths with local email fixtures, never Gmail."""
import base64
import json
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Account, Base, BookingObservation, Message, MessageStatus, Segment, SyncJob, Trip, User
from app.services import booking_import, enrichment, flight_query_v4, gmail
from app.services.flight_query_v4 import DiscoveryCandidate, DiscoveryQuery
from app.tasks import import_tasks


ROWS = json.loads((Path(__file__).parent / "fixtures/orlando-bookings.json").read_text(encoding="utf-8"))
EXPECTED = {("IAH", "DCA", "UA1540"), ("DCA", "MCO", "B62023"),
            ("MCO", "ATL", "NK1651"), ("ATL", "IAH", "NK512")}


@pytest.fixture
def worker(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'worker.sqlite'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        user = User(name="Alex Avery", email="alex@example.com")
        db.add(user)
        db.flush()
        user_id = user.id
        db.add(Account(user_id=user_id, provider="google", refresh_token_encrypted=b"test-only", scopes="https://www.googleapis.com/auth/gmail.readonly"))
        db.commit()
    messages = {
        row["id"]: {
            "id": row["id"], "snippet": row["subject"],
            "internalDate": str(int(parsedate_to_datetime(row["received_at"]).timestamp() * 1000)),
            "payload": {
                "mimeType": "text/html",
                "headers": [{"name": key, "value": row[value]} for key, value in
                            [("Subject", "subject"), ("From", "from_email"), ("Date", "received_at")]],
                "body": {"data": base64.urlsafe_b64encode(row["html"].encode()).decode()},
            },
        } for row in ROWS
    }
    monkeypatch.setattr(import_tasks, "SessionLocal", factory)
    monkeypatch.setattr(gmail, "build_gmail_service", lambda token: object())
    monkeypatch.setattr(gmail, "batch_get_messages", lambda service, ids: ({key: messages[key] for key in ids}, {}))
    monkeypatch.setattr(gmail, "get_message", lambda service, key: messages[key])
    monkeypatch.setattr(flight_query_v4, "build_discovery_plan", lambda *a, **kw: [DiscoveryQuery("fixture", "offline", False)])
    monkeypatch.setattr(flight_query_v4, "iter_discovery_messages", lambda service, plan: (
        [DiscoveryCandidate({"id": row["id"]}, "fixture", "offline", False) for row in ROWS] if plan else []))
    monkeypatch.setenv("TROTTER_PARSE_WORKERS", "2")
    enriched = []

    def enrich(db, uid, **kwargs):
        assert uid == user_id
        assert "segment_ids" in kwargs
        enriched.append(set(kwargs["segment_ids"]))
        return 0

    monkeypatch.setattr(enrichment, "enrich_user_segments", enrich)
    yield factory, user_id, enriched
    engine.dispose()


def run(factory, user_id, mode, job_id):
    with factory() as db:
        db.add(SyncJob(id=job_id, user_id=user_id, state="pending"))
        db.commit()
    return import_tasks.run_gmail_import.run(job_id=job_id, user_id=user_id, mode=mode, limit=0)


@pytest.mark.parametrize("stage", ["discovery", "batch", "stale_refetch"])
def test_worker_revocation_is_durable_without_deleting_tokens(worker, monkeypatch, stage):
    from google.auth.exceptions import RefreshError
    factory, user_id, _ = worker
    def revoked(*args, **kwargs):
        raise RefreshError("invalid_grant: Token has been expired or revoked.")
    mode = "sync"
    if stage == "discovery":
        monkeypatch.setattr(flight_query_v4, "iter_discovery_messages", revoked)
    elif stage == "batch":
        monkeypatch.setattr(gmail, "batch_get_messages", lambda service, ids: ({}, {ids[0]: RefreshError("invalid_grant")}))
    else:
        mode = "reparse"
        monkeypatch.setattr(gmail, "get_message", revoked)
        with factory() as db:
            db.add(Message(user_id=user_id, provider_msg_id="old-message", status=MessageStatus.ACCEPTED, parse_version=1, ignored=False))
            db.commit()
    run(factory, user_id, mode, f"revoked-{stage}")
    with factory() as db:
        account = db.query(Account).one()
        assert account.gmail_connection_status == "needs_reconnect"
        assert account.refresh_token_encrypted == b"test-only"
        assert account.scopes == "https://www.googleapis.com/auth/gmail.readonly"
        job = db.get(SyncJob, f"revoked-{stage}")
        assert job.state == "failed"
        assert job.error_message == "Reconnect Gmail to import your flights."
    assert run(factory, user_id, "sync", f"retry-{stage}") == {"error": "gmail_connection_required"}


def test_queued_worker_without_connection_makes_no_provider_call(worker, monkeypatch):
    factory, user_id, _ = worker
    with factory() as db:
        db.query(Account).delete()
        db.commit()
    monkeypatch.setattr(gmail, "build_gmail_service", lambda token: pytest.fail("Unconnected user must never contact Gmail"))
    assert run(factory, user_id, "sync", "unconnected") == {"error": "gmail_connection_required"}


@pytest.mark.parametrize("mode", ["sync", "reparse"])
def test_worker_paths_use_same_booking_policy_and_scoped_enrichment(worker, mode):
    factory, user_id, enriched = worker
    if mode == "reparse":
        with factory() as db:
            for row in ROWS:
                db.add(Message(user_id=user_id, provider_msg_id=row["id"], status=MessageStatus.ACCEPTED,
                               parse_version=1, ignored=False, created_at=parsedate_to_datetime(row["received_at"])))
            db.commit()
    result = run(factory, user_id, mode, "initial")
    assert result and result["state"] == "completed"
    with factory() as db:
        assert {(s.dep_airport, s.arr_airport, s.flight_number) for s in db.query(Segment)} == EXPECTED
        assert db.query(Trip).count() == 1
        active_ids = {s.id for s in db.query(Segment)}
        assert active_ids <= enriched[0]
        before = [(s.id, s.trip_id, s.flight_number) for s in db.query(Segment).order_by(Segment.id)]
        evidence_count = db.query(BookingObservation).count()
        assert db.query(Message).filter_by(provider_msg_id="frontier").one().status == MessageStatus.ACCEPTED
        assert db.query(Message).filter_by(provider_msg_id="cancellation").one().status == MessageStatus.ACCEPTED
    again = run(factory, user_id, mode, "repeat")
    assert again and again["state"] == "completed"
    with factory() as db:
        assert [(s.id, s.trip_id, s.flight_number) for s in db.query(Segment).order_by(Segment.id)] == before
        assert db.query(BookingObservation).count() == evidence_count


def test_worker_failure_rolls_back_whole_message_projection_and_evidence(worker, monkeypatch):
    factory, user_id, enriched = worker
    real_apply = booking_import.apply_booking_message

    def fail_after_projection(*args, **kwargs):
        real_apply(*args, **kwargs)
        raise RuntimeError("Injected failure before message commit")

    monkeypatch.setattr(booking_import, "apply_booking_message", fail_after_projection)
    run(factory, user_id, "sync", "injected-failure")
    with factory() as db:
        assert db.query(SyncJob).one().state == "failed"
        assert db.query(Segment).count() == 0
        assert db.query(Trip).count() == 0
        assert db.query(BookingObservation).count() == 0
        assert db.query(Message).count() == 0
    assert enriched == []


@pytest.mark.parametrize("mode", ["sync", "reparse"])
def test_every_worker_path_persists_original_gmail_time(worker, mode):
    factory, user_id, _ = worker
    if mode == "reparse":
        with factory() as db:
            for row in ROWS:
                db.add(Message(user_id=user_id, provider_msg_id=row["id"], status=MessageStatus.REVIEW_REQUIRED,
                               parse_version=1, internal_ts=None, ignored=False))
            db.commit()
    assert run(factory, user_id, mode, "times")["state"] == "completed"
    expected = {row["id"]: parsedate_to_datetime(row["received_at"]).astimezone(timezone.utc) for row in ROWS}
    with factory() as db:
        for message in db.query(Message):
            assert message.internal_ts.replace(tzinfo=timezone.utc) == expected[message.provider_msg_id]


def test_fetch_failure_cannot_advance_incremental_coverage(worker, monkeypatch):
    from app.models import GmailDiscoveryState
    factory, user_id, _ = worker
    monkeypatch.setattr(gmail, "batch_get_messages", lambda service, ids: ({}, {ids[0]: TimeoutError()}))
    result = run(factory, user_id, "sync", "fetch-failure")
    assert result["state"] == "failed" and result["failed_message_ids"]
    with factory() as db:
        assert db.query(GmailDiscoveryState).one().last_incremental_scan_at is None
        assert db.query(Segment).count() == 0


def test_exact_reprocess_never_discovers_or_fills_with_other_stale_messages(worker, monkeypatch):
    factory, user_id, _ = worker
    with factory() as db:
        db.add(Message(user_id=user_id, provider_msg_id="untargeted", status=MessageStatus.REVIEW_REQUIRED, parse_version=1))
        db.add(SyncJob(id="exact", user_id=user_id, state="pending"))
        db.commit()
    monkeypatch.setattr(flight_query_v4, "iter_discovery_messages", lambda *a: pytest.fail("No discovery on exact repair"))
    result = import_tasks.run_gmail_import.run(job_id="exact", user_id=user_id, mode="exact_reprocess", message_ids=[ROWS[0]["id"]])
    assert result["state"] == "completed" and result["scanned_count"] == 1
    with factory() as db:
        assert db.query(Message).filter_by(provider_msg_id="untargeted").one().parse_version == 1


def test_recent_scan_does_not_replay_older_mail_on_version_upgrade(worker, monkeypatch):
    factory, user_id, _ = worker
    with factory() as db:
        db.add(Message(user_id=user_id, provider_msg_id="old-untargeted", status=MessageStatus.REVIEW_REQUIRED, parse_version=1))
        db.commit()
    monkeypatch.setattr(gmail, "get_message", lambda *a: pytest.fail("Recent scan must not fetch older stale mail"))
    assert run(factory, user_id, "sync", "recent-only")["state"] == "completed"
    with factory() as db:
        assert db.query(Message).filter_by(provider_msg_id="old-untargeted").one().parse_version == 1


def test_history_yields_to_recent_scan_and_keeps_unprocessed_ids(worker, monkeypatch):
    from app.models import GmailHistoryState
    factory, user_id, _ = worker
    with factory() as db:
        state = GmailHistoryState(user_id=user_id, state="queued", cursor_before=datetime.now(timezone.utc))
        db.add(state)
        db.add(SyncJob(id="background", user_id=user_id, state="pending"))
        db.add(SyncJob(id="interactive", user_id=user_id, state="pending", updated_at=datetime.now(timezone.utc)))
        db.commit()
        state_id = state.id
    ids = [row["id"] for row in ROWS]
    monkeypatch.setattr(gmail, "list_messages", lambda *a, **kw: ([{"id": mid} for mid in ids], "next"))
    monkeypatch.setattr(gmail, "batch_get_messages", lambda *a: pytest.fail("Background must yield before fetching"))
    result = import_tasks.run_gmail_import.run(job_id="background", user_id=user_id, mode="history", history_state_id=state_id, limit=50)
    assert result["history_deferred"] is True
    with factory() as db:
        state = db.get(GmailHistoryState, state_id)
        assert state.pending_message_ids == ids
        assert state.state == "pending" and state.attempts == 0
        assert state.next_page_token == "next" and state.page_token is None


def test_history_timeout_keeps_fetched_page_for_recovery(worker, monkeypatch):
    from app.models import GmailHistoryState
    from billiard.exceptions import SoftTimeLimitExceeded
    factory, user_id, _ = worker
    with factory() as db:
        state = GmailHistoryState(user_id=user_id, state="queued", cursor_before=datetime.now(timezone.utc))
        db.add(state)
        db.add(SyncJob(id="timeout", user_id=user_id, state="pending"))
        db.commit()
        state_id = state.id
    ids = [ROWS[0]["id"], ROWS[1]["id"]]
    monkeypatch.setattr(gmail, "list_messages", lambda *a, **kw: ([{"id": mid} for mid in ids], "next"))
    def timeout(*args):
        raise SoftTimeLimitExceeded()
    monkeypatch.setattr(gmail, "batch_get_messages", timeout)
    import_tasks.run_gmail_import.run(job_id="timeout", user_id=user_id, mode="history", history_state_id=state_id, limit=50)
    with factory() as db:
        state = db.get(GmailHistoryState, state_id)
        assert state.pending_message_ids == ids and state.next_page_token == "next"
        assert state.state == "running" and state.scanned_count == 0
        assert db.get(SyncJob, "timeout").state == "failed"


def test_interactive_request_waits_for_history_without_creating_another_job(worker, monkeypatch):
    from contextlib import contextmanager
    from app.models import GmailHistoryState
    from app.services import import_lock
    factory, user_id, _ = worker
    monkeypatch.setattr(import_tasks.celery_app.conf, "task_always_eager", False)
    with factory() as db:
        db.add(GmailHistoryState(user_id=user_id, state="running"))
        db.commit()
    @contextmanager
    def busy(*args):
        raise import_lock.ImportAlreadyRunning("busy")
        yield
    monkeypatch.setattr(import_lock, "user_import_lock", busy)
    queued = []
    monkeypatch.setattr(import_tasks.run_gmail_import, "apply_async", lambda **kw: queued.append(kw))
    result = run(factory, user_id, "sync", "interactive-wait")
    assert result["state"] == "pending" and result["waiting_for_history"]
    assert queued[0]["kwargs"]["job_id"] == "interactive-wait"
    with factory() as db:
        assert db.query(SyncJob).count() == 1


def test_eager_development_retry_cannot_recurse_on_locked_history(worker, monkeypatch):
    from contextlib import contextmanager
    from app.models import GmailHistoryState
    from app.services import import_lock
    factory, user_id, _ = worker
    monkeypatch.setattr(import_tasks.celery_app.conf, "task_always_eager", True)
    with factory() as db:
        db.add(GmailHistoryState(user_id=user_id, state="running"))
        db.commit()
    @contextmanager
    def busy(*args):
        raise import_lock.ImportAlreadyRunning("busy")
        yield
    monkeypatch.setattr(import_lock, "user_import_lock", busy)
    monkeypatch.setattr(import_tasks.run_gmail_import, "apply_async", lambda **kw: pytest.fail("No recursive eager task"))
    run(factory, user_id, "sync", "eager-busy")
    with factory() as db:
        assert db.get(SyncJob, "eager-busy").state == "failed"
