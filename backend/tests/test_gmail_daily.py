from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import Account, Base, GmailDiscoveryState, SyncJob, User
from app.services import flight_query_v4 as discovery, gmail_daily as daily, gmail_import_jobs as jobs
from app.services.gmail_connection import GMAIL_READONLY_SCOPE


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def owner(db, name, *, scopes=GMAIL_READONLY_SCOPE, status=None):
    user = User(name=name, email=f"{name}@example.test")
    db.add(user)
    db.flush()
    db.add(Account(user_id=user.id, provider="google", scopes=scopes, refresh_token_encrypted=b"fixture",
                   gmail_connection_status=status))
    db.commit()
    return user.id


def test_daily_schedule_uses_consent_and_joins_manual_scan(db, monkeypatch):
    now = datetime.now(timezone.utc)
    uid = owner(db, "due")
    owner(db, "identity", scopes="openid")
    owner(db, "revoked", status="needs_reconnect")
    recent = owner(db, "scanned")
    db.add(GmailDiscoveryState(user_id=recent, provider="google", last_incremental_scan_at=now))
    active = owner(db, "busy")
    jobs.new_import(db, active, kind="mailbox")
    db.commit()
    sent = []
    monkeypatch.setattr(daily, "dispatch_import", lambda db, job, **opts: sent.append((job.user_id, opts)) or True)
    assert daily.schedule_due(db, now=now) == 1
    assert sent == [(uid, {"limit": 0})]
    assert jobs.active_mailbox_import(db, uid).kind == "daily"
    assert daily.schedule_due(db, now=now) == 0
    job = jobs.active_mailbox_import(db, uid)
    job.state = "completed"
    db.commit()
    assert daily.schedule_due(db, now=now + timedelta(hours=23)) == 0
    assert [u for u, in daily.due_users(db, now + timedelta(hours=25)).filter(User.id == uid)] == [uid]


def test_failure_keeps_original_window_and_retries_after_cooldown(db, monkeypatch):
    uid = owner(db, "retry")
    now = datetime.now(timezone.utc)
    job = jobs.new_import(db, uid, kind="daily")
    job.started_at = now - timedelta(days=3)
    job.updated_at, job.state = now, "failed"
    db.commit()
    assert not daily.due_users(db, now).all()
    assert daily.due_users(db, now + timedelta(minutes=61)).one() == (uid,)
    retry = jobs.new_import(db, uid, kind="daily")
    state = discovery.get_or_create_discovery_state(db, uid)
    assert daily.daily_since(db, retry, state) == now - timedelta(days=4)
    state.last_incremental_scan_at = now - timedelta(days=2)
    assert daily.daily_since(db, retry, state) == now - timedelta(days=2, hours=1)
    retry.state, retry.started_at = "completed", now
    db.flush()
    assert daily.daily_since(db, retry, state) == now - timedelta(hours=1)


def test_every_daily_query_has_the_same_precise_bounds_without_archive_tiers(monkeypatch):
    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=25)
    monkeypatch.setattr(discovery, "ENABLE_RECALL_DISCOVERY_TIERS", True)
    plan = discovery.build_discovery_plan(GmailDiscoveryState(), now=now, recent_since=since)
    assert {q.tier for q in plan} == {"fast_known_senders", "fast_strong_keywords", "fast_bilt_confirmations", "incremental_precise"}
    for item in plan:
        assert f"after:{int(since.timestamp()) - 1}" in item.query
        assert f"before:{int(now.timestamp()) + 1}" in item.query
        assert item.query.count("after:") == item.query.count("before:") == 1


def test_actual_daily_worker_repeats_without_refetch_or_historical_repair(monkeypatch, tmp_path):
    from sqlalchemy.orm import sessionmaker
    from app.models import Message, MessageStatus
    from app.services import enrichment, flight_template_recovery, gmail
    from app.tasks import import_tasks

    engine = create_engine(f"sqlite:///{tmp_path / 'daily.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False)
    with factory() as db:
        uid = owner(db, "worker")
        db.add(Message(user_id=uid, provider_msg_id="known", status=MessageStatus.ACCEPTED, parse_version=1))
        db.commit()
    monkeypatch.setattr(import_tasks, "SessionLocal", factory)
    monkeypatch.setattr(gmail, "build_gmail_service", lambda _: object())
    monkeypatch.setattr(gmail, "batch_get_messages", lambda *a: pytest.fail("Refetched an old email"))
    monkeypatch.setattr(flight_template_recovery, "select_messages", lambda *a, **k: pytest.fail("Selected historical repair"))
    monkeypatch.setattr(enrichment, "enrich_user_segments", lambda *a, **k: 0)
    windows = []
    def candidates(service, plan):
        windows.append([q.query for q in plan])
        assert all(" before:" in q.query for q in plan)
        return [discovery.DiscoveryCandidate({"id": "known"}, plan[0].tier, plan[0].query, True)]
    monkeypatch.setattr(discovery, "iter_discovery_messages", candidates)
    try:
        for attempt in range(2):
            with factory() as db:
                job = jobs.new_import(db, uid, kind="daily")
                db.commit()
                jid = job.id
            result = import_tasks.run_gmail_import.run(jid, uid, limit=0)
            assert (result["state"], result["scanned_count"], result["parsed_count"]) == ("completed", 1, 0)
            assert import_tasks.run_gmail_import.run(jid, uid, limit=0)["state"] == "completed"
        assert len(windows) == 2
        with factory() as db:
            assert db.query(Message).one().parse_version == 1
            assert db.query(GmailDiscoveryState).one().last_incremental_scan_at is None
    finally:
        engine.dispose()
