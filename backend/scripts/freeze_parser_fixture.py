"""Freeze a Gmail message into a permanent regression fixture.

When the audit surfaces a message the parser still cannot handle, this script
re-fetches the email, redacts personal data, and writes a JSON fixture under
``backend/tests/fixtures/regressions/`` plus an entry in
``backend/tests/fixtures/regressions/_index.json``. The companion test
``test_parser_regressions.py`` loads every fixture and asserts that the
parser either extracts the recorded flights (for parser misses) or returns
within a time budget (for timeouts). Once frozen, that exact mistake cannot
silently regress.

Usage:
    cd backend
    # freeze a single message id
    python scripts/freeze_parser_fixture.py <message_id>

    # show the currently-open failure rows from the failure log
    python scripts/freeze_parser_fixture.py --list

    # freeze every currently-open failure row at once
    python scripts/freeze_parser_fixture.py --from-failures
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv(".env")
sys.path.insert(0, os.getcwd())

from app.services.gmail import (
    build_gmail_service,
    extract_attachments,
    extract_headers,
    extract_message_body,
    get_message,
)
from app.services.parser import PARSER_VERSION
from app.services.parser_failures import iter_failures, latest_per_message


REGRESSION_DIR = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "regressions"
INDEX_PATH = REGRESSION_DIR / "_index.json"


# Light-touch redaction. The fixture must preserve everything the parser
# needs (IATA codes, flight numbers, dates, times, PNR labels, passenger
# names for identity checks), so we only scrub things the parser does not
# read: email addresses, URLs, phone numbers, payment fragments.
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_URL_RE = re.compile(r"https?://\S+|www\.[^\s<>\"]+", re.IGNORECASE)
# Phone numbers must show actual phone-y shape: a country/area-code paren or
# a leading + or "tel:" / "phone" label, OR three digit groups separated by
# dashes/dots/spaces (the classic ###-###-#### form). The earlier loose form
# `\+?\d[\d\-\s().]{7,}\d` ate dates like "11-06-2022", which destroyed the
# very signal the parser needs from gate-change emails.
_PHONE_RE = re.compile(
    r"""
    (?:\+\d[\d \-().]{6,}\d)              # international prefix
    |
    (?:\(\d{2,4}\)[\s\-.]?\d{2,4}[\s\-.]?\d{2,4}\b)  # (xxx) xxx-xxxx style
    |
    \b\d{3}[\s.\-]\d{3}[\s.\-]\d{4}\b      # 800-555-1234 / 800.555.1234
    |
    \b1[\s\-]\d{3}[\s\-]\d{3}[\s\-]\d{4}\b # 1-800-555-1234
    """,
    re.VERBOSE,
)
_LONG_DIGITS_RE = re.compile(r"\b\d{12,}\b")  # card-like sequences


def _redact(text: str) -> str:
    if not text:
        return text
    text = _EMAIL_RE.sub("[email]", text)
    text = _URL_RE.sub("[url]", text)
    text = _PHONE_RE.sub("[phone]", text)
    text = _LONG_DIGITS_RE.sub("[digits]", text)
    return text


def _safe_filename(value: str, *, default: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("_")
    return cleaned[:80] or default


def _get_token() -> bytes | None:
    conn = sqlite3.connect("trotter.db", uri=True)
    cur = conn.cursor()
    cur.execute("SELECT refresh_token_encrypted FROM accounts WHERE provider='google' LIMIT 1")
    row = cur.fetchone()
    conn.close()
    return row[0] if row else None


def _load_index() -> dict[str, Any]:
    if INDEX_PATH.exists():
        try:
            return json.loads(INDEX_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {"fixtures": {}, "updated_at": None}


def _save_index(index: dict[str, Any]) -> None:
    REGRESSION_DIR.mkdir(parents=True, exist_ok=True)
    index["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    INDEX_PATH.write_text(json.dumps(index, indent=2, sort_keys=True), encoding="utf-8")


def _failure_lookup() -> dict[str, dict[str, Any]]:
    return latest_per_message(iter_failures())


def _expectations_for(failure: dict[str, Any]) -> dict[str, Any]:
    failure_type = failure.get("failure_type") or "parser_miss"
    if failure_type in {"timeout", "exception"}:
        # Timeouts only need to assert the parser returns within budget;
        # asserting a specific flight list is rarely useful for these because
        # we never got a parse to compare against.
        return {
            "must_complete_within_seconds": 5.0,
            "expected_flights": None,
            "notes": failure.get("error_message") or "",
        }
    return {
        "must_complete_within_seconds": 5.0,
        # Set this by hand after inspection — leaving it null means the test
        # only asserts the parser produces at least one flight.
        "expected_flights": None,
        "notes": failure.get("ai_label") or "",
    }


def freeze(message_id: str, *, service, failure: dict[str, Any] | None) -> Path:
    msg = get_message(service, message_id)
    headers = extract_headers(msg)
    plain_text, html = extract_message_body(msg)
    attachments = extract_attachments(msg)

    sender_raw = headers.get("from", "")
    subject = headers.get("subject", "(no subject)")
    received_at = headers.get("date", "")

    sender_domain = (failure or {}).get("sender_domain") or ""
    if not sender_domain and "@" in sender_raw:
        sender_domain = sender_raw.split("@")[-1].rstrip(">").strip().lower()

    short_sender = _safe_filename(sender_domain or "unknown", default="unknown")
    short_subject = _safe_filename(subject, default="no_subject")[:40]
    fixture_name = f"{short_sender}__{short_subject}__{message_id[:10]}.json"

    failure_type = (failure or {}).get("failure_type") or "parser_miss"
    payload = {
        "message_id": message_id,
        "fixture_version": 1,
        "frozen_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "parser_version_when_frozen": PARSER_VERSION,
        "failure_type": failure_type,
        "sender_domain": sender_domain,
        "subject": subject,
        "received_at": received_at,
        "html": _redact(html),
        "plain_text": _redact(plain_text),
        "attachment_filenames": [a.get("filename") or "" for a in attachments],
        "expectations": _expectations_for(failure or {}),
        "source_failure_summary": {
            "ai_label": (failure or {}).get("ai_label") or "",
            "ai_confidence": (failure or {}).get("ai_confidence") or 0.0,
            "parse_miss_score": (failure or {}).get("parse_miss_score") or 0,
            "discovery_tiers": (failure or {}).get("discovery_tiers") or [],
        },
    }

    REGRESSION_DIR.mkdir(parents=True, exist_ok=True)
    target = REGRESSION_DIR / fixture_name
    target.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False), encoding="utf-8")

    index = _load_index()
    index["fixtures"][message_id] = {
        "path": fixture_name,
        "frozen_at": payload["frozen_at"],
        "failure_type": failure_type,
        "sender_domain": sender_domain,
        "subject": subject,
        "parser_version_when_frozen": PARSER_VERSION,
    }
    _save_index(index)

    return target


def list_open_failures() -> None:
    rows = _failure_lookup()
    if not rows:
        print("No open failures in flight_parser_failures.jsonl")
        return
    print(f"Open failures: {len(rows)}")
    for msg_id, row in sorted(rows.items(), key=lambda kv: kv[1].get("sender_domain", "")):
        sender = row.get("sender_domain") or "-"
        subject = (row.get("subject") or "")[:60]
        ftype = row.get("failure_type") or "?"
        print(f"  {msg_id}  {ftype:14s}  {sender:32s}  {subject}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Freeze a Gmail message as a parser regression fixture.")
    parser.add_argument("message_id", nargs="?", help="Message id to freeze.")
    parser.add_argument("--list", action="store_true", help="List currently open failures.")
    parser.add_argument(
        "--from-failures",
        action="store_true",
        help="Freeze every currently open failure row at once.",
    )
    args = parser.parse_args()

    if args.list:
        list_open_failures()
        return

    failures = _failure_lookup()

    token = _get_token()
    if not token:
        print("No Google account found in backend/trotter.db.")
        sys.exit(1)
    service = build_gmail_service(token)

    if args.from_failures:
        if not failures:
            print("No open failures to freeze.")
            return
        for msg_id, failure in failures.items():
            try:
                path = freeze(msg_id, service=service, failure=failure)
                print(f"froze {msg_id} → {path.name}")
            except Exception as exc:  # noqa: BLE001
                print(f"freeze error {msg_id}: {type(exc).__name__}: {exc}")
        return

    if not args.message_id:
        parser.error("provide a message_id, or use --list / --from-failures")

    failure = failures.get(args.message_id)
    path = freeze(args.message_id, service=service, failure=failure)
    print(f"froze {args.message_id} → {path}")


if __name__ == "__main__":
    main()
