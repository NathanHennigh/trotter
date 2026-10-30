from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Account, Base, GmailDiscoveryState, GmailHistoryState, User
from app.services import gmail, gmail_history as history

NOW = datetime(2026, 10, 30, 12, tzinfo=timezone.utc)


@pytest.fixture
def db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'history.sqlite'}")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as session:
        user = User(email="one@example.com", name="One Person")
        session.add(user)
        session.flush()
        session.add(Account(user_id=user.id, provider="google", refresh_token_encrypted=b"test",
                            scopes="https://www.googleapis.com/auth/gmail.readonly"))
        session.add(GmailDiscoveryState(user_id=user.id, provider="google", last_incremental_scan_at=NOW,
                                        backfill_complete=True))
        session.commit()
        yield session
    engine.dispose()


def add_history(db):
    row = GmailHistoryState(user_id=db.query(User).first().id, state="queued", cursor_before=NOW)
    db.add(row)
    db.commit()
    return row


def test_history_is_explicitly_opted_in_and_account_scoped(db, monkeypatch):
    monkeypatch.setenv("TROTTER_ENABLE_AUTOMATIC_BACKFILL", "true")
    monkeypatch.delenv("TROTTER_GMAIL_HISTORY_USER_IDS", raising=False)
    assert history.discover_history_jobs(db, now=NOW) == []
    monkeypatch.setenv("TROTTER_GMAIL_HISTORY_USER_IDS", str(db.query(User).first().id))
    jobs = history.discover_history_jobs(db, now=NOW)
    assert len(jobs) == 1
    assert history.discover_history_jobs(db, now=NOW + timedelta(seconds=1)) == []
    assert db.query(GmailHistoryState).one().state == "queued"
    # A legacy boolean claiming completion does not suppress unverified history.
    assert db.query(GmailDiscoveryState).one().backfill_complete is True


def test_page_checkpoint_retries_only_failed_ids_without_advancing_coverage(db, monkeypatch):
    row = add_history(db)
    calls = []
    def fetch(*args, **kwargs):
        calls.append(kwargs)
        return [{"id": "first"}, {"id": "second"}], "page-two"
    monkeypatch.setattr(gmail, "list_messages", fetch)
    _, ids = history.prepare_history_page(db, row.user_id, row.id, object())
    assert ids == ["first", "second"]
    assert calls[0]["max_results"] == 50
    original_cursor = row.cursor_before
    history.finish_history_page(db, row, {"second"}, now=NOW)
    db.commit()
    assert row.pending_message_ids == ["second"]
    assert row.cursor_before == original_cursor
    assert row.scanned_count == 1
    assert row.attempts == 1
    _, retry_ids = history.prepare_history_page(db, row.user_id, row.id, object())
    assert retry_ids == ["second"] and len(calls) == 1
    history.finish_history_page(db, row, set(), now=NOW)
    db.commit()
    assert row.page_token == "page-two" and row.pending_message_ids == []
    assert row.scanned_count == 2 and row.attempts == 0
    assert row.cursor_before == original_cursor
    monkeypatch.setattr(gmail, "list_messages", lambda *a, **kw: ([], None))
    history.prepare_history_page(db, row.user_id, row.id, object())
    window_start = row.window_start
    history.finish_history_page(db, row, set(), now=NOW)
    db.commit()
    assert row.cursor_before == window_start
    assert row.window_start is None and row.page_token is None
    assert db.query(GmailDiscoveryState).one().last_incremental_scan_at.replace(tzinfo=timezone.utc) == NOW


def test_failed_page_stops_after_bounded_attempts(db):
    row = add_history(db)
    row.pending_message_ids = ["unavailable"]
    for _ in range(history.MAX_ATTEMPTS):
        history.fail_history_page(db, row.id, "gmail_fetch_retry", now=NOW)
    db.commit()
    assert row.state == "paused" and row.pending_message_ids == ["unavailable"]
    assert row.error_code == "gmail_fetch_retry"


def test_stale_lease_can_be_resumed_but_live_lease_is_not_duplicated(db, monkeypatch):
    row = add_history(db)
    monkeypatch.setenv("TROTTER_ENABLE_AUTOMATIC_BACKFILL", "true")
    monkeypatch.setenv("TROTTER_GMAIL_HISTORY_USER_IDS", "*")
    row.state, row.lease_until = "running", NOW + timedelta(seconds=30)
    row.pending_message_ids = ["keep"]
    db.commit()
    assert history.discover_history_jobs(db, now=NOW) == []
    assert history.discover_history_jobs(db, now=NOW + timedelta(seconds=31)) == [(row.id, row.user_id)]
    assert row.pending_message_ids == ["keep"]


def test_deleted_or_foreign_history_job_cannot_be_recreated(db, monkeypatch):
    row = add_history(db)
    monkeypatch.setattr(gmail, "list_messages", lambda *a, **kw: pytest.fail("must not fetch"))
    with pytest.raises(ValueError, match="unavailable"):
        history.prepare_history_page(db, row.user_id + 99, row.id, object())
    state_id, user_id = row.id, row.user_id
    db.delete(row)
    db.commit()
    with pytest.raises(ValueError, match="unavailable"):
        history.prepare_history_page(db, user_id, state_id, object())
    history.fail_history_page(db, state_id, "retry")
    assert db.query(GmailHistoryState).count() == 0


def test_final_empty_window_finishes_only_at_supported_start(db, monkeypatch):
    row = add_history(db)
    row.cursor_before = history._earliest_supported_datetime() + timedelta(days=3)
    db.commit()
    monkeypatch.setattr(gmail, "list_messages", lambda *a, **kw: ([], None))
    history.prepare_history_page(db, row.user_id, row.id, object())
    history.finish_history_page(db, row, set(), now=NOW)
    db.commit()
    assert row.state == "complete"
    assert history.history_progress(db, row.user_id)["complete"] is True


def test_history_has_a_separate_worker_queue():
    from app.celery_app import celery_app
    assert celery_app.conf.task_routes["app.tasks.gmail_history_tasks.scan_history_page"]["queue"] == "gmail_history"


def test_reconnection_resumes_only_connection_pause_and_preserves_page(db, monkeypatch):
    row = add_history(db)
    row.state, row.error_code = "paused", "gmail_connection_required"
    row.pending_message_ids, row.next_page_token = ["still-needed"], "next"
    account = db.query(Account).one()
    account.gmail_connection_status = "needs_reconnect"
    db.commit()
    monkeypatch.setenv("TROTTER_ENABLE_AUTOMATIC_BACKFILL", "true")
    monkeypatch.setenv("TROTTER_GMAIL_HISTORY_USER_IDS", "*")
    assert history.discover_history_jobs(db, now=NOW) == []
    account.gmail_connection_status = "connected"
    db.commit()
    assert history.discover_history_jobs(db, now=NOW) == [(row.id, row.user_id)]
    assert row.pending_message_ids == ["still-needed"] and row.next_page_token == "next"
