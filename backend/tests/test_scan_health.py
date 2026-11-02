"""Operational reports use real stored outcomes without writes or private data."""
from datetime import datetime, timedelta, timezone
import json

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.models import Base, BookingObservation, GmailHistoryState, Message, MessageStatus, SyncJob, User
from app.services.scan_health import build_scan_health, render_scan_health
from scripts import scan_health_report as cli


NOW = datetime(2026, 11, 2, 15, tzinfo=timezone.utc)
SECRET = "PRIVATE_EMAIL_NAME_TOKEN_PNR"
TABLES = [m.__table__ for m in (User, SyncJob, GmailHistoryState, Message, BookingObservation)]


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=TABLES)
    with Session(engine) as session:
        session.add_all([User(id=1, email="private@example.test"), User(id=9, email="other@example.test")])
        session.commit()
        yield session
    engine.dispose()


def job(db, ref, state, age_minutes=0, duration=60, user_id=1, **kwargs):
    updated = NOW - timedelta(minutes=age_minutes)
    row = SyncJob(id=ref, user_id=user_id, state=state, started_at=updated - timedelta(seconds=duration),
        updated_at=updated, page_token=SECRET, **kwargs)
    db.add(row)
    return row


def message(db, ref, error=None, status=MessageStatus.REVIEW_REQUIRED, user_id=1, evidence=None, **kwargs):
    row = Message(user_id=user_id, provider_msg_id=ref, parse_error=error, status=status,
        parse_version=44, parse_evidence={"source": SECRET, "passenger": SECRET, **(evidence or {})},
        subject=SECRET, from_email=SECRET, **kwargs)
    db.add(row)
    return row


def observation(db, source, number, suffix="", user_id=1):
    db.add(BookingObservation(user_id=user_id, evidence_key=f"{source}-{number}-{suffix}",
        source_message_id=source, flight_number=number, ownership="unknown", pnr=SECRET,
        facts={"passenger": SECRET}))


def test_stale_active_jobs_survive_lookback_terminal_spans_honest_and_scope(db):
    job(db, SECRET, "running", age_minutes=60 * 48)
    job(db, "pending-old", "pending", age_minutes=16)
    job(db, "failed-recent", "failed", age_minutes=5, duration=90, error_message=f"invalid_grant {SECRET}")
    job(db, "old-terminal", "failed", age_minutes=60 * 48)
    job(db, "completed", "completed", age_minutes=10, duration=30)
    job(db, "other-account", "failed", user_id=9)
    db.commit()
    report = build_scan_health(db, user_ids=[1], now=NOW, max_jobs=2)
    assert report["jobs"]["total"] == 4
    assert report["jobs"]["by_state"] == {"completed": 1, "failed": 1, "pending": 1, "running": 1}
    assert report["jobs"]["warnings"] == {"pending_without_recent_update": 1, "suspected_stalled": 1}
    assert report["jobs"]["recorded_terminal_spans_seconds"] == {"count": 2, "min": 30, "max": 90, "mean": 60}
    assert report["jobs"]["failure_categories"] == {"gmail_reconnect_required": 1}
    assert report["jobs"]["details_truncated"]
    assert report["attention_required"]
    assert report["jobs"]["details"][0]["job_ref"].startswith("opaque-")
    assert SECRET not in json.dumps(report) + render_scan_health(report)


def test_future_or_inverted_clocks_never_invent_duration(db):
    job(db, "future", "running", age_minutes=-10)
    job(db, "backwards", "completed", duration=-60)
    db.commit()
    rows = build_scan_health(db, user_ids=[1], now=NOW)["jobs"]["details"]
    assert rows[0]["seconds_since_update"] is None
    assert "missing_or_future_update_timestamp" in rows[0]["warnings"]
    assert rows[0]["elapsed_since_recorded_start_seconds"] is None
    assert rows[1]["recorded_span_seconds"] is None


def test_classify_persisted_outcomes_carriers_templates_without_echoing_evidence(db):
    message(db, "strong", "strong_flight_evidence_but_no_segments",
        evidence={"evidence_gate": {"flight_numbers": ["BR51", "BR51", SECRET]}})
    message(db, "incomplete", "partial_flight_evidence_but_no_segments", evidence={
        "partial_flight_evidence": {"provider": "philippines_etravel", "carrier": "PR", "missing_fields": ["departure_time"], "name": SECRET}})
    message(db, "ownership", "passenger_identity_unresolved")
    message(db, "conflict", "legacy_flight_identity_conflict")
    message(db, "good", status=MessageStatus.ACCEPTED, evidence={"resolved": True, "held_other": 2, "source": "shape_pdf_ticket_itinerary"})
    message(db, "ignored", SECRET, status=MessageStatus.IGNORED)
    message(db, "unexpected", SECRET)
    message(db, "attachment", "ticket_attachment_needs_review")
    message(db, "weak", "weak_flight_evidence_but_candidate_query_matched")
    message(db, "pending", status=MessageStatus.PENDING)
    message(db, "other-user", "strong_flight_evidence_but_no_segments", user_id=9)
    observation(db, "good", "UA100")
    observation(db, "good", "UA100", "repeat")
    observation(db, "good", "AA200")
    observation(db, "good", SECRET)
    observation(db, "strong", "AA500", user_id=9)
    db.commit()
    report = build_scan_health(db, user_ids=[1], now=NOW)
    rows = report["messages"]
    assert rows["total"] == 10
    assert rows["outcomes"] == {"unsupported_or_unrecognized_format": 1, "incomplete_evidence": 1,
        "ownership_review": 1, "identity_schedule_or_protection_review": 1, "resolved": 1,
        "ignored": 1, "unclassified_review": 1, "attachment_review": 1, "unconfirmed_candidate": 1, "pending": 1}
    assert rows["by_carrier"]["UA"] == {"resolved": 1}
    assert rows["by_carrier"]["AA"] == {"resolved": 1}
    assert rows["by_carrier"]["BR"] == {"unsupported_or_unrecognized_format": 1}
    assert rows["by_template"]["philippines_etravel"] == {"incomplete_evidence": 1}
    assert rows["messages_retaining_other_travelers"] == 1
    assert not report["attention_required"]  # review is not an operational outage
    output = json.dumps(report) + render_scan_health(report)
    assert SECRET not in output
    assert "private@example.test" not in output
    assert "provider_msg_id" not in output


def test_history_reports_expired_lease_backoff_and_counts_only(db):
    db.add(GmailHistoryState(user_id=1, state="running", pending_message_ids=[SECRET, SECRET],
        page_token=SECRET, next_page_token=SECRET, lease_until=NOW - timedelta(minutes=1),
        next_attempt_at=NOW + timedelta(minutes=3), error_code=SECRET, attempts=4, updated_at=NOW))
    db.add(GmailHistoryState(user_id=9, state="paused", pending_message_ids=[SECRET]))
    db.commit()
    report = build_scan_health(db, user_ids=[1], now=NOW)
    assert len(report["history_checkpoints"]) == 1
    row = report["history_checkpoints"][0]
    assert row["pending_message_count"] == 2 and row["lease_expired"]
    assert row["attempts"] == 4 and row["error_category"] == "unknown"
    assert row["next_attempt_at"] == "2026-11-02T15:03:00+00:00"
    assert report["attention_required"]
    assert SECRET not in json.dumps(report)


def test_report_does_not_autoflush_or_select_private_columns(db):
    message(db, "uncommitted")
    statements = []
    listener = lambda conn, cursor, statement, parameters, context, executemany: statements.append(statement.lower())
    event.listen(db.bind, "before_cursor_execute", listener)
    try:
        report = build_scan_health(db, user_ids=[1], now=NOW)
    finally:
        event.remove(db.bind, "before_cursor_execute", listener)
    assert report["messages"]["total"] == 0
    assert all(s.lstrip().startswith("select") for s in statements)
    assert all(token not in " ".join(statements) for token in ("messages.subject", "messages.from_email", "page_token", "booking_observations.facts", "booking_observations.pnr"))
    assert len(db.new) == 1


@pytest.mark.parametrize("options", [{"user_ids": []}, {"user_ids": [0]}, {"user_ids": [True]}, {"lookback_hours": 0}, {"max_jobs": 0}])
def test_invalid_report_scope_rejected(db, options):
    with pytest.raises(ValueError):
        build_scan_health(db, **options)


@pytest.fixture
def database_file(tmp_path):
    path = tmp_path / "health.sqlite"
    engine = create_engine("sqlite:///" + str(path))
    Base.metadata.create_all(engine, tables=TABLES)
    with Session(engine) as db:
        db.add(User(id=1, email="private@example.test"))
        job(db, "failed", "failed", error_message=SECRET)
        db.commit()
    engine.dispose()
    return path


def test_cli_sqlite_enforces_read_only_transaction(database_file, monkeypatch):
    original = database_file.read_bytes()
    real_builder = cli.build_scan_health
    def checked(db, **kwargs):
        with pytest.raises(OperationalError, match="readonly"):
            db.execute(text("UPDATE sync_jobs SET state = 'running'"))
        return real_builder(db, now=NOW, **kwargs)
    monkeypatch.setattr(cli, "build_scan_health", checked)
    report = cli.read_report("sqlite:///" + str(database_file), user_ids=[1])
    assert report["jobs"]["by_state"] == {"failed": 1}
    assert original == database_file.read_bytes()


def test_cli_json_human_and_optional_attention_exit(database_file, monkeypatch, capsys):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///" + str(database_file))
    assert cli.main(["--user-id", "1", "--json", "--hours", "100000"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["attention_required"]
    assert cli.main(["--user-id", "1", "--fail-on-attention", "--hours", "100000"]) == 1
    assert "Attention required: yes" in capsys.readouterr().out


def test_cli_does_not_create_missing_db_or_echo_connection_errors(tmp_path, monkeypatch, capsys):
    missing = tmp_path / (SECRET + ".sqlite")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///" + str(missing))
    assert cli.main(["--all-users"]) == 2
    assert not missing.exists()
    assert SECRET not in capsys.readouterr().err
    monkeypatch.setenv("DATABASE_URL", f"invalid-{SECRET}://password-{SECRET}")
    assert cli.main(["--all-users"]) == 2
    assert SECRET not in capsys.readouterr().err
    monkeypatch.delenv("DATABASE_URL")
    assert cli.main(["--all-users"]) == 2


def test_cli_requires_explicit_account_scope(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main([])
    assert exc.value.code == 2
