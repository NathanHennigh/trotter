"""Append-only failure log for the developer audit pipeline.

When the audit script encounters a parser hang, exception, or a message that
v4 discovery surfaces but the parser cannot turn into segments, we append a
structured row to ``flight_parser_failures.jsonl``. The log is the input to
the regression-fixture freezer and the open-misses summary, so each session
of parser tuning starts from a complete picture of what is still broken
without re-running Gmail discovery from scratch.

This module is developer-only. Production ingestion does not import it.
"""

from __future__ import annotations

import json
import os
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Iterable, Iterator

DEFAULT_LOG_PATH = Path(
    os.getenv(
        "TROTTER_PARSER_FAILURE_LOG",
        Path(__file__).resolve().parents[2] / "scripts" / "flight_parser_failures.jsonl",
    )
)

FAILURE_TYPES = {
    "timeout",          # parser exceeded the per-message wall-clock budget
    "exception",        # parser raised before producing any flights
    "parser_miss",      # v4 discovery + AI both said flight; parser produced none
    "discovery_miss",   # AI said flight but v4 did not surface the message
}

_WRITE_LOCK = Lock()


@dataclass
class FailureRecord:
    """One row in the append-only failure log.

    The fields are intentionally narrow: every entry must be re-readable
    cross-session without joining against the audit JSON. PII never goes in
    here directly; ``safe_snippet`` is the redacted form produced by
    ``flight_audit.make_safe_snippet``.
    """

    message_id: str
    failure_type: str
    parser_version: int
    sender_domain: str = ""
    subject: str = ""
    safe_snippet: str = ""
    parse_miss_score: int = 0
    ai_label: str = ""
    ai_confidence: float = 0.0
    discovery_tiers: list[str] = field(default_factory=list)
    extractor_name: str = ""
    duration_seconds: float | None = None
    error_message: str = ""
    recorded_at: str = ""

    def __post_init__(self) -> None:
        if self.failure_type not in FAILURE_TYPES:
            raise ValueError(
                f"unknown failure_type {self.failure_type!r}; expected one of {sorted(FAILURE_TYPES)}"
            )
        if not self.recorded_at:
            self.recorded_at = datetime.now(timezone.utc).isoformat(timespec="seconds")


def record_failure(record: FailureRecord, *, log_path: Path | None = None) -> None:
    """Append one ``FailureRecord`` to the JSONL log.

    Concurrency: a process-level lock guards the file open + write so the
    audit script can call this from a worker thread without interleaving
    rows. The OS-level append is atomic for small payloads on Windows and
    POSIX, so multi-process callers also get clean lines.
    """
    target = Path(log_path) if log_path else DEFAULT_LOG_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(asdict(record), sort_keys=True, ensure_ascii=False)
    with _WRITE_LOCK:
        with target.open("a", encoding="utf-8", newline="") as handle:
            handle.write(line + "\n")


def iter_failures(log_path: Path | None = None) -> Iterator[dict[str, Any]]:
    """Yield each row from the failure log as a dict, oldest first."""
    target = Path(log_path) if log_path else DEFAULT_LOG_PATH
    if not target.exists():
        return
    with target.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def latest_per_message(rows: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Collapse rows to the most recent failure per message_id.

    The log is append-only, so the same message can appear many times across
    parser-version bumps. For "what is currently still broken", only the
    latest entry matters.
    """
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        msg_id = row.get("message_id")
        if not msg_id:
            continue
        previous = latest.get(msg_id)
        if previous is None or row.get("recorded_at", "") >= previous.get("recorded_at", ""):
            latest[msg_id] = row
    return latest


def open_misses(log_path: Path | None = None, *, current_parser_version: int) -> list[dict[str, Any]]:
    """Return failures that are still open at ``current_parser_version``.

    A failure is "open" when the latest row for that message is still a
    failure type (rather than a synthetic "resolved" marker we may add later)
    and its parser_version is < current_parser_version OR equal to it. We
    keep both because a ratcheted regression-fixture test should also catch
    re-broken cases at the current version.
    """
    rows = latest_per_message(iter_failures(log_path))
    return sorted(
        rows.values(),
        key=lambda row: (row.get("sender_domain", ""), row.get("recorded_at", "")),
    )


def truncate_log(log_path: Path | None = None) -> None:
    """Drop the failure log entirely. Used by tests."""
    target = Path(log_path) if log_path else DEFAULT_LOG_PATH
    if target.exists():
        os.remove(target)
