"""Tests for the append-only failure log used by the audit pipeline."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.parser_failures import (
    FailureRecord,
    iter_failures,
    latest_per_message,
    open_misses,
    record_failure,
    truncate_log,
)


@pytest.fixture
def log_path(tmp_path: Path) -> Path:
    return tmp_path / "failures.jsonl"


def test_record_failure_appends_jsonl(log_path: Path):
    record_failure(
        FailureRecord(
            message_id="abc1",
            failure_type="parser_miss",
            parser_version=14,
            sender_domain="united.com",
            subject="Boarding pass",
            parse_miss_score=10,
            ai_label="boarding_pass",
            ai_confidence=0.95,
        ),
        log_path=log_path,
    )
    record_failure(
        FailureRecord(
            message_id="abc2",
            failure_type="timeout",
            parser_version=14,
            sender_domain="gmail.com",
            duration_seconds=31.0,
        ),
        log_path=log_path,
    )

    rows = list(iter_failures(log_path))
    assert [row["message_id"] for row in rows] == ["abc1", "abc2"]
    assert rows[1]["failure_type"] == "timeout"


def test_unknown_failure_type_rejected():
    with pytest.raises(ValueError):
        FailureRecord(message_id="x", failure_type="banana", parser_version=14)


def test_latest_per_message_keeps_most_recent(log_path: Path):
    record_failure(
        FailureRecord(
            message_id="dup",
            failure_type="parser_miss",
            parser_version=14,
            recorded_at="2025-01-01T00:00:00+00:00",
        ),
        log_path=log_path,
    )
    record_failure(
        FailureRecord(
            message_id="dup",
            failure_type="timeout",
            parser_version=15,
            recorded_at="2026-01-01T00:00:00+00:00",
        ),
        log_path=log_path,
    )

    latest = latest_per_message(iter_failures(log_path))
    assert latest["dup"]["failure_type"] == "timeout"
    assert latest["dup"]["parser_version"] == 15


def test_open_misses_sorted_by_sender(log_path: Path):
    record_failure(
        FailureRecord(message_id="m1", failure_type="parser_miss", parser_version=14, sender_domain="zeta.com"),
        log_path=log_path,
    )
    record_failure(
        FailureRecord(message_id="m2", failure_type="parser_miss", parser_version=14, sender_domain="alpha.com"),
        log_path=log_path,
    )
    rows = open_misses(log_path=log_path, current_parser_version=14)
    assert [row["sender_domain"] for row in rows] == ["alpha.com", "zeta.com"]


def test_truncate_log(log_path: Path):
    record_failure(
        FailureRecord(message_id="m", failure_type="parser_miss", parser_version=14),
        log_path=log_path,
    )
    truncate_log(log_path)
    assert not log_path.exists()
    assert list(iter_failures(log_path)) == []
