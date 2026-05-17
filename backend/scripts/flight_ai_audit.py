"""Developer-only flight discovery/parser audit using local AI classification.

This script is not part of production ingestion. It uses local AI only to label
candidate missed emails so deterministic discovery/parser fixtures can be
improved afterward.

Usage:
    cd backend
    python scripts/flight_ai_audit.py --limit 500
    python scripts/flight_ai_audit.py --query "category:travel"
    python scripts/flight_ai_audit.py --analyze-only
    python scripts/flight_ai_audit.py --skip-ai

Outputs:
    scripts/flight_ai_audit_results.json
    scripts/flight_ai_audit_report.csv
    scripts/flight_ai_audit_report.md
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sqlite3
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

from dotenv import load_dotenv

load_dotenv(".env")
sys.path.insert(0, os.getcwd())

try:
    from google.auth.exceptions import RefreshError
except Exception:  # pragma: no cover - optional in non-Gmail test envs
    RefreshError = None  # type: ignore[assignment]

from app.services.flight_audit import (
    FlightAuditAiResult,
    body_hash,
    classify_audit_bucket,
    make_safe_snippet,
    normalize_ai_classifier_response,
)
from app.services.flight_query_v2 import looks_like_flight_email
from app.services.flight_query_v4 import build_discovery_plan
from app.services.gmail import (
    build_gmail_service,
    extract_attachments,
    extract_headers,
    extract_message_body,
    get_message,
    list_messages,
)
from app.services.parse_audit import assess_parse_miss
from app.services.parser import PARSER_VERSION, parse_email, _extract_pnr
from app.services.parser_failures import FailureRecord, record_failure


# Wall-clock budget for `parse_and_classify_message`. Bounded regexes should
# finish well under this; the timeout is a safety net so a single bad email
# can never wedge the whole audit run again.
PER_MESSAGE_TIMEOUT_SECONDS = 30


RESULTS_FILE = Path(__file__).parent / "flight_ai_audit_results.json"
CSV_REPORT_FILE = Path(__file__).parent / "flight_ai_audit_report.csv"
MD_REPORT_FILE = Path(__file__).parent / "flight_ai_audit_report.md"
REVIEW_QUEUE_FILE = Path(__file__).parent / "flight_ai_audit_review_queue.md"
FEEDBACK_FILE = Path(__file__).parent / "flight_ai_audit_feedback.json"
OLLAMA_URL = os.getenv("TROTTER_AUDIT_OLLAMA_URL", "http://localhost:11434/api/chat")
DEFAULT_MODEL = os.getenv("TROTTER_AUDIT_MODEL", "qwen3.5:4b")
PRESET_QUERIES = {
    "travel": "category:travel",
    "broad-flight-nontravel": (
        '("boarding pass" OR "record locator" OR "booking reference" '
        'OR "flight itinerary" OR "e-ticket" OR eticket OR "flight confirmation" '
        'OR "flight number" OR "check in for your flight" OR "check-in for your flight" '
        'OR "upcoming flight" OR "your flight to" OR "gate assigned" '
        'OR "puerta de embarque" OR "online validation of your documents") -category:travel'
    ),
    "strong-flight-nontravel": (
        '("boarding pass" OR "record locator" OR "booking reference" '
        'OR "flight itinerary" OR "e-ticket" OR eticket OR "flight confirmation") -category:travel'
    ),
}

AI_SYSTEM_PROMPT = """You classify travel emails for a developer audit of a flight parser.

Return exactly one valid JSON object only. No markdown. No explanations.

Question: Is this email evidence of an actual booked/taken flight?

Schema:
{
  "label": "flight_confirmation | boarding_pass | itinerary | flight_change | cancellation | reminder | receipt | not_flight | other_travel | unsure",
  "confidence": 0-1,
  "has_actual_flight": boolean,
  "is_marketing": boolean,
  "is_cancellation": boolean,
  "is_change_notice": boolean,
  "detected_airlines": [],
  "detected_flight_numbers": [],
  "detected_airports": [],
  "detected_dates": [],
  "reason": "short explanation"
}

Rules:
- Do not extract a final production flight itinerary.
- Mark marketing/newsletter/deal emails as not_flight unless they contain a specific booked flight.
- Flight changes and cancellations are useful labels, even if they are not proof the user flew.
- If unsure, use label "unsure" with lower confidence.
"""


def get_token() -> bytes | None:
    conn = sqlite3.connect("trotter.db", uri=True)
    cursor = conn.cursor()
    cursor.execute("SELECT refresh_token_encrypted FROM accounts WHERE provider='google' LIMIT 1")
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None


def load_results() -> dict[str, Any]:
    if RESULTS_FILE.exists():
        data = json.loads(RESULTS_FILE.read_text(encoding="utf-8"))
        data.setdefault("schema_version", 1)
        data.setdefault("parser_version", PARSER_VERSION)
        data.setdefault("v4_ids", [])
        data.setdefault("v4_membership", {})
        data.setdefault("scan_ids", [])
        data.setdefault("scan_query", None)
        data.setdefault("scan_limit", None)
        data.setdefault("scanned", {})
        return data
    return {
        "schema_version": 1,
        "parser_version": PARSER_VERSION,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "v4_ids": [],
        "v4_membership": {},
        "scan_ids": [],
        "scan_query": None,
        "scan_limit": None,
        "scanned": {},
    }


def save_results(results: dict[str, Any]) -> None:
    RESULTS_FILE.write_text(json.dumps(results, indent=2, sort_keys=True), encoding="utf-8")


def safe_print(message: str) -> None:
    encoding = sys.stdout.encoding or "utf-8"
    try:
        print(message.encode(encoding, errors="replace").decode(encoding), flush=True)
    except OSError:
        # Console handles can disappear when a long run is interrupted or
        # wrapped by tooling. Audit logging should never turn that into a
        # parser failure or abort the scan.
        return


def collect_ids(service, query: str, label: str, *, limit: int | None = None) -> list[str]:
    ids: list[str] = []
    seen: set[str] = set()
    page_token = None
    pages = 0
    started = time.time()
    while True:
        messages, page_token = list_messages(service, query=query, page_token=page_token)
        for message in messages:
            msg_id = message.get("id")
            if not msg_id or msg_id in seen:
                continue
            seen.add(msg_id)
            ids.append(msg_id)
            if limit and len(ids) >= limit:
                print(f"{label}: hit limit={limit}", flush=True)
                return ids
        pages += 1
        print(f"{label}: pages={pages} ids={len(ids)} elapsed={time.time() - started:.1f}s", flush=True)
        if not page_token:
            break
    return ids


def collect_v4_membership(service, results: dict[str, Any]) -> None:
    if results.get("v4_ids") and results.get("v4_membership"):
        print(f"v4: using cached ids={len(results['v4_ids'])}", flush=True)
        return

    state = SimpleNamespace(
        last_incremental_scan_at=None,
        backfill_cursor_before=None,
        backfill_complete=False,
        parser_version=PARSER_VERSION,
    )
    plan = build_discovery_plan(state, now=datetime.now(timezone.utc), max_backfill_windows=1)
    seen: set[str] = set()
    membership: dict[str, list[str]] = defaultdict(list)

    for index, item in enumerate(plan, 1):
        ids = collect_ids(service, item.query, f"v4 {index}/{len(plan)} {item.tier}")
        for msg_id in ids:
            membership[msg_id].append(item.tier)
            seen.add(msg_id)
        save_results({**results, "v4_ids": sorted(seen), "v4_membership": dict(membership)})

    results["v4_ids"] = sorted(seen)
    results["v4_membership"] = dict(membership)
    save_results(results)


def collect_scan_ids(service, results: dict[str, Any], *, query: str, limit: int | None) -> None:
    cache_key = "scan_ids"
    if results.get(cache_key) and results.get("scan_query") == query and results.get("scan_limit") == limit:
        print(f"scan: using cached ids={len(results[cache_key])}", flush=True)
        return
    if results.get(cache_key):
        print("scan: query/limit changed; resetting cached scan IDs and scanned rows", flush=True)
        results["scanned"] = {}
    results[cache_key] = collect_ids(service, query, "scan", limit=limit)
    results["scan_query"] = query
    results["scan_limit"] = limit
    save_results(results)


def parse_and_classify_message(
    service,
    msg_id: str,
    *,
    v4_membership: dict[str, list[str]],
    run_ai: bool,
    model: str,
    timeout: int,
    debug: bool = False,
) -> dict[str, Any]:
    phase_started = time.time()
    if debug:
        safe_print(f"  phase get_message id={msg_id}")
    full_msg = get_message(service, msg_id)
    if debug:
        safe_print(f"  phase get_message done elapsed={time.time() - phase_started:.1f}s")
        phase_started = time.time()
        safe_print(f"  phase headers id={msg_id}")
    headers = extract_headers(full_msg)
    if debug:
        safe_print(f"  phase headers done elapsed={time.time() - phase_started:.1f}s")
        phase_started = time.time()
        safe_print(f"  phase body id={msg_id}")
    plain_text, html = extract_message_body(full_msg)
    if debug:
        safe_print(
            f"  phase body done elapsed={time.time() - phase_started:.1f}s "
            f"plain={len(plain_text)} html={len(html)}"
        )
        phase_started = time.time()
        safe_print(f"  phase attachments id={msg_id}")
    attachments = extract_attachments(full_msg)
    if debug:
        safe_print(f"  phase attachments done elapsed={time.time() - phase_started:.1f}s count={len(attachments)}")
        phase_started = time.time()
        safe_print(f"  phase prefilter id={msg_id}")
    body_for_filter = plain_text if plain_text.strip() else html
    subject = headers.get("subject", "")
    sender = headers.get("from", "")
    snippet = full_msg.get("snippet", "")

    prefilter_result = looks_like_flight_email(subject=subject, sender=sender, body=body_for_filter)
    if debug:
        safe_print(f"  phase prefilter done elapsed={time.time() - phase_started:.1f}s result={prefilter_result}")
        phase_started = time.time()
        safe_print(f"  phase parse_email id={msg_id}")
    parse_result = parse_email(
        html=html,
        plain_text=plain_text,
        attachments=attachments,
        user_name="",
        aliases=[],
        received_at=headers.get("date"),
        subject=subject,
        from_email=sender,
    )
    if debug:
        safe_print(
            f"  phase parse_email done elapsed={time.time() - phase_started:.1f}s "
            f"flights={len(parse_result.flights)} source={parse_result.source}"
        )
        phase_started = time.time()
        safe_print(f"  phase parse_audit id={msg_id}")
    parse_miss = assess_parse_miss(subject=subject, sender=sender, body=body_for_filter)
    if debug:
        safe_print(
            f"  phase parse_audit done elapsed={time.time() - phase_started:.1f}s "
            f"score={parse_miss.score}"
        )
        phase_started = time.time()
        safe_print(f"  phase ai id={msg_id} run_ai={run_ai}")
    ai_result = classify_with_ollama(
        subject=subject,
        sender=sender,
        date=headers.get("date", ""),
        snippet=snippet,
        body=body_for_filter,
        model=model,
        timeout=timeout,
    ) if run_ai else FlightAuditAiResult(label="unsure", confidence=0.0)
    if debug:
        safe_print(f"  phase ai done elapsed={time.time() - phase_started:.1f}s label={ai_result.label}")
        phase_started = time.time()
        safe_print(f"  phase bucket id={msg_id}")

    discovery_tiers = v4_membership.get(msg_id, [])
    sender_domain = sender.split("@")[-1].rstrip(">").strip().lower() if "@" in sender else ""
    safe_snippet = make_safe_snippet(subject, snippet, body_for_filter)
    bucket = classify_audit_bucket(
        in_v4_discovery=bool(discovery_tiers),
        prefilter_result=prefilter_result,
        parser_flight_count=len(parse_result.flights),
        ai_result=ai_result,
        parse_miss_score=parse_miss.score,
        sender_domain=sender_domain,
        subject=subject,
        safe_snippet=safe_snippet,
    )
    if debug:
        safe_print(f"  phase bucket done elapsed={time.time() - phase_started:.1f}s bucket={bucket}")

    return {
        "message_id": msg_id,
        "date": headers.get("date", ""),
        "from": sender[:240],
        "sender_domain": sender_domain,
        "subject": subject[:240],
        "body_sha256": body_hash(plain_text, html),
        "safe_snippet": safe_snippet,
        "attachment_names": [item.get("filename") for item in attachments if item.get("filename")][:20],
        "discovery_tiers": discovery_tiers,
        "in_v4_discovery": bool(discovery_tiers),
        "prefilter_result": prefilter_result,
        "parser_flight_count": len(parse_result.flights),
        "parser_source": parse_result.source if parse_result.flights else None,
        "parser_flights": [
            {
                "airline": flight.airline,
                "flight_number": flight.flight_number,
                "dep_airport": flight.dep_airport,
                "arr_airport": flight.arr_airport,
                "dep_time": flight.dep_time.isoformat() if flight.dep_time else None,
                "arr_time": flight.arr_time.isoformat() if flight.arr_time else None,
                "pnr": flight.pnr,
                "source": flight.source,
            }
            for flight in parse_result.flights
        ],
        "candidate_pnr": _extract_pnr(f"{subject}\n{body_for_filter}".upper()),
        "parse_miss": parse_miss.as_dict(),
        "ai": ai_result.as_dict(),
        "audit_bucket": bucket,
    }


def classify_with_ollama(
    *,
    subject: str,
    sender: str,
    date: str,
    snippet: str,
    body: str,
    model: str,
    timeout: int,
) -> FlightAuditAiResult:
    text = make_safe_snippet(
        f"Subject: {subject}",
        f"From: {sender}",
        f"Date: {date}",
        f"Snippet: {snippet}",
        body,
        max_length=5000,
    )
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": AI_SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ],
        "stream": False,
        "format": "json",
        "options": {"temperature": 0, "num_ctx": 4096, "num_predict": 320, "repeat_penalty": 1.05},
        "think": False,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        OLLAMA_URL,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
        parsed = json.loads(raw)
        content = (parsed.get("message") or {}).get("content", "")
        return normalize_ai_classifier_response(content)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        return FlightAuditAiResult(raw_error=f"{type(exc).__name__}: {str(exc)[:240]}")


def check_ollama_available(*, timeout: int = 3) -> str | None:
    tags_url = OLLAMA_URL.rsplit("/", 1)[0] + "/tags"
    try:
        with urllib.request.urlopen(tags_url, timeout=timeout) as resp:
            resp.read(512)
        return None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return f"{type(exc).__name__}: {str(exc)[:240]}"


class _MessageProcessingTimeout(Exception):
    """Raised when ``parse_and_classify_message`` exceeds the wall-clock budget."""


def _run_with_timeout(func: Callable[..., Any], *args, timeout_seconds: float, **kwargs) -> Any:
    """Run ``func`` on a daemon thread; raise ``_MessageProcessingTimeout`` on overrun.

    A daemon thread that runs past the timeout is abandoned. With the bounded
    parser regexes that abandoned thread will finish on its own shortly; the
    audit run does not wait for it. We accept the small CPU overlap because
    the alternative — subprocess isolation — adds startup cost to every
    message and would dwarf the parser's actual runtime.
    """
    box: dict[str, Any] = {}

    def _worker() -> None:
        try:
            box["value"] = func(*args, **kwargs)
        except BaseException as exc:  # noqa: BLE001 - propagated to caller below
            box["error"] = exc

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()
    thread.join(timeout=timeout_seconds)
    if thread.is_alive():
        raise _MessageProcessingTimeout(
            f"parse_and_classify_message exceeded {timeout_seconds}s"
        )
    if "error" in box:
        raise box["error"]
    return box["value"]


def _log_audit_failure(
    *,
    failure_type: str,
    message_id: str,
    row: dict[str, Any] | None,
    duration_seconds: float | None = None,
    error_message: str = "",
    extractor_name: str = "",
) -> None:
    """Append one entry to ``flight_parser_failures.jsonl``.

    The audit script calls this on timeouts, exceptions, and after final
    bucketing for "likely_flight_*_missed" rows. Failure data deliberately
    flows through the redacted ``safe_snippet`` rather than raw bodies — the
    log lives in the repo workspace and must never carry PII.
    """
    row = row or {}
    ai = row.get("ai") or {}
    parse_miss = row.get("parse_miss") or {}
    try:
        record_failure(
            FailureRecord(
                message_id=message_id,
                failure_type=failure_type,
                parser_version=PARSER_VERSION,
                sender_domain=row.get("sender_domain") or "",
                subject=(row.get("subject") or "")[:240],
                safe_snippet=row.get("safe_snippet") or "",
                parse_miss_score=int(parse_miss.get("score") or 0),
                ai_label=ai.get("label") or "",
                ai_confidence=float(ai.get("confidence") or 0.0),
                discovery_tiers=list(row.get("discovery_tiers") or []),
                extractor_name=extractor_name,
                duration_seconds=duration_seconds,
                error_message=error_message[:400],
            )
        )
    except Exception as exc:  # noqa: BLE001 - logging must never raise
        safe_print(f"failure-log write error id={message_id} {type(exc).__name__}: {exc}")


def _is_google_auth_error(exc: BaseException) -> bool:
    text = f"{type(exc).__name__}: {exc}".lower()
    if RefreshError is not None and isinstance(exc, RefreshError):
        return True
    return (
        type(exc).__name__ == "RefreshError"
        or "invalid_grant" in text
        or "expired or revoked" in text
    )


def _clear_auth_reparse_errors(results: dict[str, Any]) -> int:
    cleared = 0
    for row in (results.get("scanned") or {}).values():
        error = row.get("reparse_error") if isinstance(row, dict) else None
        if isinstance(error, str) and _is_auth_error_text(error):
            row.pop("reparse_error", None)
            cleared += 1
    if cleared:
        results.pop("auth_error", None)
        save_results(results)
    return cleared


def _is_auth_error_text(value: str) -> bool:
    lowered = value.lower()
    return (
        "refresherror" in lowered
        or "invalid_grant" in lowered
        or "expired or revoked" in lowered
    )


def _should_rescan_cached_row(row: dict[str, Any] | None, *, run_ai: bool) -> bool:
    if not row:
        return True
    if row.get("error") or row.get("timeout"):
        return True
    if not run_ai:
        return False
    ai = row.get("ai") if isinstance(row.get("ai"), dict) else {}
    return bool(ai.get("raw_error")) or not ai


def scan(service, results: dict[str, Any], *, run_ai: bool, model: str, timeout: int) -> None:
    if run_ai:
        ai_error = check_ollama_available()
        if ai_error:
            safe_print(
                "scan aborted: Ollama is not reachable for AI classification. "
                f"Start Ollama or use --skip-ai for a deterministic-only scan. {ai_error}"
            )
            results["ai_error"] = ai_error
            save_results(results)
            return

    v4_membership = results.get("v4_membership") or {}
    scanned = results["scanned"]
    ids = results["scan_ids"]
    started = time.time()

    for index, msg_id in enumerate(ids, 1):
        if _should_rescan_cached_row(scanned.get(msg_id), run_ai=run_ai):
            item_started = time.time()
            if msg_id in scanned:
                safe_print(f"scan refresh {index}/{len(ids)} id={msg_id}")
            try:
                scanned[msg_id] = _run_with_timeout(
                    parse_and_classify_message,
                    service,
                    msg_id,
                    v4_membership=v4_membership,
                    run_ai=run_ai,
                    model=model,
                    timeout=timeout,
                    timeout_seconds=PER_MESSAGE_TIMEOUT_SECONDS,
                )
            except _MessageProcessingTimeout as exc:
                duration = time.time() - item_started
                safe_print(
                    f"scan timeout {index}/{len(ids)} id={msg_id} elapsed={duration:.1f}s"
                )
                scanned[msg_id] = {
                    "message_id": msg_id,
                    "audit_bucket": "possible_flight_needs_review",
                    "error": str(exc),
                }
                _log_audit_failure(
                    failure_type="timeout",
                    message_id=msg_id,
                    row=None,
                    duration_seconds=duration,
                    error_message=str(exc),
                )
            except Exception as exc:
                if _is_google_auth_error(exc):
                    error_text = f"{type(exc).__name__}: {str(exc)[:240]}"
                    results["auth_error"] = error_text
                    save_results(results)
                    safe_print(
                        "scan auth error: Google token is expired/revoked; "
                        "aborting without recording parser failures."
                    )
                    return
                duration = time.time() - item_started
                error_text = f"{type(exc).__name__}: {str(exc)[:240]}"
                scanned[msg_id] = {
                    "message_id": msg_id,
                    "audit_bucket": "possible_flight_needs_review",
                    "error": error_text,
                }
                _log_audit_failure(
                    failure_type="exception",
                    message_id=msg_id,
                    row=None,
                    duration_seconds=duration,
                    error_message=error_text,
                )
            if len(scanned) % 25 == 0:
                save_results(results)

        if index % 50 == 0 or index == len(ids):
            print(
                f"scan {index}/{len(ids)} cached={len(scanned)} "
                f"elapsed={time.time() - started:.1f}s",
                flush=True,
            )

    save_results(results)


def reparse_cached(service, results: dict[str, Any]) -> None:
    scanned = results.get("scanned") or {}
    if not scanned:
        print("No cached scanned rows found. Run a scan first.")
        return

    cleared = _clear_auth_reparse_errors(results)
    if cleared:
        safe_print(f"reparse: cleared {cleared} stale auth reparse errors from cached rows")

    v4_membership = results.get("v4_membership") or {}
    ids = list(results.get("scan_ids") or scanned.keys())
    started = time.time()
    reparsed = 0
    safe_print(f"reparse: starting cached refresh ids={len(ids)} parser_version={PARSER_VERSION}")

    for index, msg_id in enumerate(ids, 1):
        if msg_id not in scanned:
            continue

        old_row = scanned.get(msg_id) or {}
        old_ai = old_row.get("ai") or {}
        subject = (old_row.get("subject") or "(no subject)")[:120]
        sender = (old_row.get("from") or old_row.get("sender_domain") or "-")[:80]
        safe_print(f"reparse start {index}/{len(ids)} id={msg_id} from={sender} subject={subject}")
        item_started = time.time()
        try:
            new_row = _run_with_timeout(
                parse_and_classify_message,
                service,
                msg_id,
                v4_membership=v4_membership,
                run_ai=False,
                model=DEFAULT_MODEL,
                timeout=1,
                debug=True,
                timeout_seconds=PER_MESSAGE_TIMEOUT_SECONDS,
            )
            new_row["ai"] = old_ai
            ai_payload = {
                key: value
                for key, value in old_ai.items()
                if key in FlightAuditAiResult.__dataclass_fields__
            }
            ai_result = FlightAuditAiResult(**ai_payload)
            new_row["audit_bucket"] = classify_audit_bucket(
                in_v4_discovery=bool(new_row.get("discovery_tiers")),
                prefilter_result=bool(new_row.get("prefilter_result")),
                parser_flight_count=int(new_row.get("parser_flight_count") or 0),
                ai_result=ai_result,
                parse_miss_score=int((new_row.get("parse_miss") or {}).get("score") or 0),
                sender_domain=new_row.get("sender_domain") or "",
                subject=new_row.get("subject") or "",
                safe_snippet=new_row.get("safe_snippet") or "",
            )
            scanned[msg_id] = new_row
            reparsed += 1
            item_elapsed = time.time() - item_started
            if item_elapsed >= 5:
                safe_print(
                    f"reparse slow {index}/{len(ids)} id={msg_id} "
                    f"elapsed={item_elapsed:.1f}s flights={new_row.get('parser_flight_count', 0)} "
                    f"bucket={new_row.get('audit_bucket')}"
                )
        except _MessageProcessingTimeout as exc:
            duration = time.time() - item_started
            old_row["reparse_error"] = f"timeout: {exc}"
            scanned[msg_id] = old_row
            safe_print(
                f"reparse timeout {index}/{len(ids)} id={msg_id} elapsed={duration:.1f}s"
            )
            _log_audit_failure(
                failure_type="timeout",
                message_id=msg_id,
                row=old_row,
                duration_seconds=duration,
                error_message=str(exc),
            )
        except Exception as exc:
            if _is_google_auth_error(exc):
                error_text = f"{type(exc).__name__}: {str(exc)[:240]}"
                results["auth_error"] = error_text
                save_results(results)
                safe_print(
                    "reparse auth error: Google token is expired/revoked; "
                    "aborting without modifying cached parser rows."
                )
                safe_print(
                    "Reconnect Google in the app, then rerun "
                    "`python scripts/flight_ai_audit.py --reparse-cached`."
                )
                return
            duration = time.time() - item_started
            error_text = f"{type(exc).__name__}: {str(exc)[:240]}"
            old_row["reparse_error"] = error_text
            scanned[msg_id] = old_row
            safe_print(f"reparse error {index}/{len(ids)} id={msg_id} {error_text}")
            _log_audit_failure(
                failure_type="exception",
                message_id=msg_id,
                row=old_row,
                duration_seconds=duration,
                error_message=error_text,
            )

        if reparsed and reparsed % 25 == 0:
            results["parser_version"] = PARSER_VERSION
            save_results(results)

        if index % 10 == 0 or index % 50 == 0 or index == len(ids):
            safe_print(
                f"reparse {index}/{len(ids)} updated={reparsed} "
                f"elapsed={time.time() - started:.1f}s",
            )

    results["parser_version"] = PARSER_VERSION
    save_results(results)


_MISS_BUCKET_TO_FAILURE_TYPE = {
    "likely_flight_parser_missed": "parser_miss",
    "likely_flight_discovery_missed": "discovery_miss",
}


def _record_miss_failures(rows: list[dict[str, Any]]) -> None:
    """Append a failure-log row for every message in a "missed" bucket.

    Called after the final bucket pass so we only log misses that survived
    contextual demotion (e.g., reminders that match an already-parsed trip
    are demoted to ``duplicate_or_reminder`` and skipped here).
    """
    for row in rows:
        failure_type = _MISS_BUCKET_TO_FAILURE_TYPE.get(row.get("audit_bucket") or "")
        if not failure_type:
            continue
        message_id = row.get("message_id")
        if not message_id:
            continue
        _log_audit_failure(
            failure_type=failure_type,
            message_id=message_id,
            row=row,
        )


def write_reports(results: dict[str, Any]) -> None:
    rows = list(results.get("scanned", {}).values())
    for row in rows:
        ai_payload = {
            key: value
            for key, value in (row.get("ai") or {}).items()
            if key in FlightAuditAiResult.__dataclass_fields__
        }
        ai_result = FlightAuditAiResult(**ai_payload)
        row["audit_bucket"] = classify_audit_bucket(
            in_v4_discovery=bool(row.get("discovery_tiers")),
            prefilter_result=bool(row.get("prefilter_result")),
            parser_flight_count=int(row.get("parser_flight_count") or 0),
            ai_result=ai_result,
            parse_miss_score=int((row.get("parse_miss") or {}).get("score") or 0),
            sender_domain=row.get("sender_domain") or "",
            subject=row.get("subject") or "",
            safe_snippet=row.get("safe_snippet") or "",
        )
    apply_contextual_audit_buckets(rows)
    _record_miss_failures(rows)
    save_results(results)
    rows.sort(key=lambda row: (row.get("audit_bucket", ""), row.get("date", ""), row.get("message_id", "")))
    fields = [
        "message_id",
        "date",
        "from",
        "subject",
        "discovery_tiers",
        "prefilter_result",
        "parser_flight_count",
        "parser_source",
        "ai_label",
        "ai_confidence",
        "audit_bucket",
        "parse_miss_score",
        "detected_airports",
        "detected_flight_numbers",
        "safe_snippet",
    ]
    with CSV_REPORT_FILE.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            ai = row.get("ai") or {}
            parse_miss = row.get("parse_miss") or {}
            writer.writerow(
                {
                    "message_id": row.get("message_id", ""),
                    "date": row.get("date", ""),
                    "from": row.get("from", ""),
                    "subject": row.get("subject", ""),
                    "discovery_tiers": ",".join(row.get("discovery_tiers") or []),
                    "prefilter_result": row.get("prefilter_result", ""),
                    "parser_flight_count": row.get("parser_flight_count", 0),
                    "parser_source": row.get("parser_source") or "",
                    "ai_label": ai.get("label", ""),
                    "ai_confidence": ai.get("confidence", ""),
                    "audit_bucket": row.get("audit_bucket", ""),
                    "parse_miss_score": parse_miss.get("score", ""),
                    "detected_airports": ",".join(ai.get("detected_airports") or []),
                    "detected_flight_numbers": ",".join(ai.get("detected_flight_numbers") or []),
                    "safe_snippet": row.get("safe_snippet", ""),
                }
            )

    summary = build_markdown_summary(rows)
    existing_feedback = load_existing_review_feedback()
    review_queue = build_review_queue(rows, existing_feedback=existing_feedback)
    MD_REPORT_FILE.write_text(summary, encoding="utf-8")
    REVIEW_QUEUE_FILE.write_text(review_queue, encoding="utf-8")
    print(summary.encode(sys.stdout.encoding or "utf-8", errors="replace").decode(sys.stdout.encoding or "utf-8"))
    print(f"\nSaved:\n  {RESULTS_FILE}\n  {CSV_REPORT_FILE}\n  {MD_REPORT_FILE}\n  {REVIEW_QUEUE_FILE}")


ANCILLARY_FLIGHT_RE = re.compile(
    r"\b("
    r"check[ -]?in|boarding pass|boarding documents|mobile boarding|upcoming trip|"
    r"flight reminder|trip reminder|gate|seat assignment|baggage|carry-on|"
    r"flight receipt|receipt for confirmation|processing"
    r")\b",
    re.IGNORECASE,
)


def apply_contextual_audit_buckets(rows: list[dict[str, Any]]) -> None:
    parsed_pnrs: set[str] = set()
    parsed_segment_keys: set[tuple[str, str, str]] = set()
    for row in rows:
        if int(row.get("parser_flight_count") or 0) <= 0:
            continue
        for pnr in _row_pnrs(row):
            parsed_pnrs.add(pnr)
        for key in _row_segment_keys(row):
            parsed_segment_keys.add(key)

    for row in rows:
        if int(row.get("parser_flight_count") or 0) > 0:
            continue
        bucket = row.get("audit_bucket")
        if bucket not in {"likely_flight_parser_missed", "possible_flight_needs_review"}:
            continue
        if not _looks_like_ancillary_or_reminder(row):
            continue

        matching_pnrs = sorted(_row_pnrs(row) & parsed_pnrs)
        matching_segments = sorted(_row_segment_keys(row) & parsed_segment_keys)
        if not matching_pnrs and not matching_segments:
            continue

        row["audit_bucket"] = "duplicate_or_reminder"
        row["audit_context"] = {
            "reason": "ancillary_email_matches_existing_parsed_trip",
            "matching_pnrs": matching_pnrs,
            "matching_segments": ["|".join(key) for key in matching_segments],
        }


def _row_pnrs(row: dict[str, Any]) -> set[str]:
    pnrs: set[str] = set()
    candidate = row.get("candidate_pnr")
    if isinstance(candidate, str) and candidate:
        pnrs.add(candidate.upper())
    for flight in row.get("parser_flights") or []:
        pnr = flight.get("pnr") if isinstance(flight, dict) else None
        if isinstance(pnr, str) and pnr:
            pnrs.add(pnr.upper())
    return pnrs


def _row_segment_keys(row: dict[str, Any]) -> set[tuple[str, str, str]]:
    keys: set[tuple[str, str, str]] = set()
    ai = row.get("ai") or {}
    airports = [code.upper() for code in ai.get("detected_airports") or [] if isinstance(code, str) and len(code) == 3]
    flights = [re.sub(r"\s+", "", value.upper()) for value in ai.get("detected_flight_numbers") or [] if isinstance(value, str)]
    for parsed in row.get("parser_flights") or []:
        flight_number = str(parsed.get("flight_number") or "").upper()
        dep_airport = str(parsed.get("dep_airport") or "").upper()
        arr_airport = str(parsed.get("arr_airport") or "").upper()
        if flight_number and dep_airport and arr_airport:
            keys.add((flight_number, dep_airport, arr_airport))
    if len(airports) >= 2:
        for flight_number in flights:
            if flight_number:
                keys.add((flight_number, airports[0], airports[1]))
    return keys


def _looks_like_ancillary_or_reminder(row: dict[str, Any]) -> bool:
    ai = row.get("ai") or {}
    if ai.get("label") in {"reminder", "boarding_pass", "receipt"}:
        return True
    text = f"{row.get('subject') or ''}\n{row.get('safe_snippet') or ''}"
    return bool(ANCILLARY_FLIGHT_RE.search(text))


def build_markdown_summary(rows: list[dict[str, Any]]) -> str:
    buckets = Counter(row.get("audit_bucket", "unknown") for row in rows)
    in_v4 = sum(1 for row in rows if row.get("in_v4_discovery"))
    parsed = sum(1 for row in rows if (row.get("parser_flight_count") or 0) > 0)
    likely_ai = sum(
        1
        for row in rows
        if (row.get("ai") or {}).get("has_actual_flight")
        and float((row.get("ai") or {}).get("confidence") or 0) >= 0.65
    )

    miss_buckets = {"likely_flight_discovery_missed", "likely_flight_parser_missed"}
    missed_rows = [row for row in rows if row.get("audit_bucket") in miss_buckets]
    top_senders = Counter(row.get("sender_domain") or "" for row in missed_rows if row.get("sender_domain"))
    top_subjects = Counter((row.get("subject") or "")[:90] for row in missed_rows if row.get("subject"))
    top_reasons = Counter((row.get("parse_miss") or {}).get("reason") for row in missed_rows)

    lines = [
        "# Flight AI Audit Report",
        "",
        f"- Total messages scanned: {len(rows):,}",
        f"- Messages in v4 discovery: {in_v4:,}",
        f"- Messages parsed successfully: {parsed:,}",
        f"- AI likely-flight messages: {likely_ai:,}",
        f"- Likely discovery misses: {buckets.get('likely_flight_discovery_missed', 0):,}",
        f"- Likely parser misses: {buckets.get('likely_flight_parser_missed', 0):,}",
        f"- Likely false positives: {buckets.get('possible_false_positive', 0):,}",
        "",
        "## Buckets",
        "",
    ]
    for bucket, count in buckets.most_common():
        lines.append(f"- {bucket}: {count:,}")

    lines.extend(["", "## Top Missed Senders", ""])
    lines.extend(f"- {sender}: {count}" for sender, count in top_senders.most_common(10))
    lines.extend(["", "## Top Missed Subjects", ""])
    lines.extend(f"- {count}x {subject}" for subject, count in top_subjects.most_common(10))
    lines.extend(["", "## Top Parser Miss Reasons", ""])
    lines.extend(f"- {reason}: {count}" for reason, count in top_reasons.most_common(10) if reason)
    lines.extend(["", "## Recommended Fixture Candidates", ""])
    for row in sorted(
        missed_rows,
        key=lambda item: (
            item.get("audit_bucket") != "likely_flight_parser_missed",
            -float((item.get("ai") or {}).get("confidence") or 0),
            -int((item.get("parse_miss") or {}).get("score") or 0),
        ),
    )[:25]:
        ai = row.get("ai") or {}
        parse_miss = row.get("parse_miss") or {}
        lines.append(
            f"- `{row.get('audit_bucket')}` ai={ai.get('label')}:{ai.get('confidence')} "
            f"score={parse_miss.get('score')} from={row.get('sender_domain') or '-'} "
            f"subject={row.get('subject') or '-'}"
        )
    return "\n".join(lines)


def load_existing_review_feedback() -> dict[str, dict[str, list[str] | str]]:
    json_feedback = load_review_feedback_json()
    if not REVIEW_QUEUE_FILE.exists():
        return {"subjects": {}, "senders": {}, "items": json_feedback}
    lines = REVIEW_QUEUE_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
    subjects: dict[str, list[str]] = {}
    senders: dict[str, str] = {}
    pending_comments: list[str] = []
    current_sender = ""
    item_re = re.compile(r"^- \[(?P<subject>.+?)\]\(")
    sender_re = re.compile(r"^### (?P<sender>\S+) \(\d+\)(?P<comment>.*)$")
    metadata_re = re.compile(r"^\s+- (?:ai=|snippet:)")

    for line in lines:
        sender_match = sender_re.match(line)
        if sender_match:
            current_sender = sender_match.group("sender")
            comment = sender_match.group("comment").strip()
            if comment:
                senders[current_sender] = comment
            pending_comments = []
            continue

        item_match = item_re.match(line)
        if item_match:
            subject = item_match.group("subject").replace("\\[", "[").replace("\\]", "]")
            if pending_comments:
                subjects.setdefault(subject, pending_comments.copy())
            pending_comments = []
            continue

        if not line.strip() or line.startswith("#") or line.lower().startswith("reviewed:") or metadata_re.match(line):
            continue
        if line.startswith("- "):
            continue
        pending_comments.append(line)

    return {"subjects": subjects, "senders": senders, "items": json_feedback}


def load_review_feedback_json() -> dict[str, dict[str, Any]]:
    if not FEEDBACK_FILE.exists():
        return {}
    try:
        payload = json.loads(FEEDBACK_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    items = payload.get("items") if isinstance(payload, dict) else None
    return items if isinstance(items, dict) else {}


def build_review_queue(
    rows: list[dict[str, Any]],
    *,
    existing_feedback: dict[str, dict[str, list[str] | str]] | None = None,
) -> str:
    existing_feedback = existing_feedback or {"subjects": {}, "senders": {}}
    subject_feedback = existing_feedback.get("subjects", {})
    sender_feedback = existing_feedback.get("senders", {})
    item_feedback = existing_feedback.get("items", {})
    review_buckets = {
        "likely_flight_parser_missed": "Likely Flight Parser Misses",
        "duplicate_or_reminder": "Flight Reminders / Boarding Links",
        "change_or_cancellation": "Flight Changes / Cancellations",
    }
    lines = [
        "# Flight Audit Review Queue",
        "",
        "Use this file to review messages in Gmail without opening the large JSON report.",
        "Each item includes a Gmail search link built from sender and subject. Confirm only whether the full email contains structured details worth parsing.",
        "",
    ]
    for bucket, title in review_buckets.items():
        bucket_rows = [row for row in rows if row.get("audit_bucket") == bucket]
        if not bucket_rows:
            continue
        lines.extend([f"## {title}", ""])
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in bucket_rows:
            grouped[row.get("sender_domain") or "unknown"].append(row)
        for sender_domain, group_rows in sorted(grouped.items(), key=lambda item: (-len(item[1]), item[0])):
            sender_comment = sender_feedback.get(sender_domain)
            heading = f"### {sender_domain} ({len(group_rows)})"
            if sender_comment:
                heading = f"{heading} {sender_comment}"
            lines.extend([heading, ""])
            for row in sorted(group_rows, key=lambda item: item.get("subject") or "")[:25]:
                ai = row.get("ai") or {}
                parse_miss = row.get("parse_miss") or {}
                subject = row.get("subject") or "(no subject)"
                search_url = _gmail_search_url(sender=row.get("from") or "", subject=subject)
                feedback = item_feedback.get(row.get("message_id") or "") if isinstance(item_feedback, dict) else None
                for comment in subject_feedback.get(subject, []):
                    lines.append(comment)
                if feedback:
                    label = feedback.get("category") or "reviewed"
                    note = feedback.get("note") or ""
                    lines.append(f"reviewed: {label}" + (f" - {note}" if note else ""))
                lines.append(f"- [{_escape_md(subject)}]({search_url})")
                lines.append(
                    f"  - ai={ai.get('label', '-')}/{ai.get('confidence', '-')} "
                    f"parse_score={parse_miss.get('score', '-')} "
                    f"airports={','.join(ai.get('detected_airports') or []) or '-'} "
                    f"flights={','.join(ai.get('detected_flight_numbers') or []) or '-'}"
                )
                lines.append(f"  - snippet: {_escape_md((row.get('safe_snippet') or '')[:220])}")
            lines.append("")
    return "\n".join(lines)


def _gmail_search_url(*, sender: str, subject: str) -> str:
    sender_domain = sender.split("@")[-1].rstrip(">").strip().lower() if "@" in sender else ""
    terms = []
    if sender_domain:
        terms.append(f"from:{sender_domain}")
    if subject:
        cleaned_subject = subject.replace('"', " ").strip()
        terms.append(f'subject:"{cleaned_subject}"')
    query = " ".join(terms) if terms else subject
    return "https://mail.google.com/mail/u/0/#search/" + urllib.parse.quote(query)


def _escape_md(value: str) -> str:
    return value.replace("[", "\\[").replace("]", "\\]").replace("\n", " ")


def run(args: argparse.Namespace) -> None:
    results = load_results()
    if args.analyze_only:
        write_reports(results)
        return

    token = get_token()
    if not token:
        print("No Google account found in backend/trotter.db.")
        return

    service = build_gmail_service(token)
    if args.reparse_cached:
        collect_v4_membership(service, results)
        reparse_cached(service, results)
        write_reports(results)
        return

    collect_v4_membership(service, results)
    query = "" if args.all_mail else PRESET_QUERIES.get(args.preset, args.query)
    collect_scan_ids(service, results, query=query, limit=args.limit)
    scan(service, results, run_ai=not args.skip_ai, model=args.model, timeout=args.timeout)
    write_reports(results)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Audit flight discovery/parser misses using local AI labels.")
    parser.add_argument("--query", default="category:travel", help="Gmail search query to scan. Default: category:travel.")
    parser.add_argument(
        "--preset",
        choices=sorted(PRESET_QUERIES),
        default=None,
        help="Use a built-in Gmail query preset instead of passing a fragile long query through the shell.",
    )
    parser.add_argument("--all-mail", action="store_true", help="Scan all mail. This can be extremely slow.")
    parser.add_argument("--limit", type=int, default=None, help="Limit scanned IDs for a quick audit run.")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Ollama model for audit classification.")
    parser.add_argument("--timeout", type=int, default=120, help="Timeout per Ollama request.")
    parser.add_argument("--skip-ai", action="store_true", help="Skip Ollama and bucket using deterministic evidence.")
    parser.add_argument("--analyze-only", action="store_true", help="Write reports from cached results.")
    parser.add_argument(
        "--reparse-cached",
        action="store_true",
        help="Re-fetch cached message IDs and refresh deterministic parser fields while preserving cached AI labels.",
    )
    parsed_args, extra_args = parser.parse_known_args()
    if extra_args:
        if parsed_args.query == "category:travel" and not parsed_args.preset:
            parser.error(f"unrecognized arguments: {' '.join(extra_args)}")
        parsed_args.query = " ".join([parsed_args.query, *extra_args])
    run(parsed_args)
