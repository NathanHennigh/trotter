"""Render ``PARSER_OPEN_MISSES.md`` from the failure log.

This script is the briefing every new parser-tuning session reads first.
It collapses ``flight_parser_failures.jsonl`` to the latest row per
message, groups rows by sender domain, and writes a small markdown summary
that sits next to the parser. Running it is cheap; running it after every
audit pass is the recommended loop.

Usage:
    cd backend
    python scripts/parser_open_misses.py
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.parser import PARSER_VERSION
from app.services.parser_failures import iter_failures, latest_per_message


OUTPUT_PATH = Path(__file__).resolve().parents[2] / "PARSER_OPEN_MISSES.md"
AUDIT_RESULTS_PATH = Path(__file__).resolve().parent / "flight_ai_audit_results.json"

FAILURE_TYPE_ORDER = ["timeout", "exception", "parser_miss", "discovery_miss"]


def _bucket_label(failure_type: str) -> str:
    return {
        "timeout": "Timeouts (parser hangs)",
        "exception": "Exceptions (parser raised)",
        "parser_miss": "Parser misses (v4 found, parser produced 0 flights)",
        "discovery_miss": "Discovery misses (AI says flight, v4 missed it)",
    }.get(failure_type, failure_type)


def render(rows: dict[str, dict[str, Any]]) -> str:
    if not rows:
        return (
            "# Parser Open Misses\n\n"
            f"_Parser version: {PARSER_VERSION}_\n\n"
            "No open failures recorded. Run "
            "`python scripts/flight_ai_audit.py --reparse-cached` to refresh.\n"
        )

    by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows.values():
        by_type[row.get("failure_type") or "parser_miss"].append(row)

    type_counts = Counter(row.get("failure_type") for row in rows.values())
    domain_counts = Counter(row.get("sender_domain") or "?" for row in rows.values())

    lines: list[str] = [
        "# Parser Open Misses",
        "",
        f"_Parser version: {PARSER_VERSION}. Auto-generated from "
        "`backend/scripts/flight_parser_failures.jsonl`._",
        "",
        f"- Total open misses: **{len(rows)}**",
    ]
    for failure_type in FAILURE_TYPE_ORDER:
        count = type_counts.get(failure_type, 0)
        if count:
            lines.append(f"- {failure_type}: {count}")

    lines.extend(["", "## Top sender domains", ""])
    for domain, count in domain_counts.most_common(10):
        lines.append(f"- `{domain}`: {count}")

    for failure_type in FAILURE_TYPE_ORDER:
        bucket = by_type.get(failure_type) or []
        if not bucket:
            continue
        lines.extend(["", f"## {_bucket_label(failure_type)} ({len(bucket)})", ""])
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in bucket:
            grouped[row.get("sender_domain") or "?"].append(row)
        for domain, items in sorted(grouped.items(), key=lambda kv: (-len(kv[1]), kv[0])):
            lines.append(f"### `{domain}` ({len(items)})")
            lines.append("")
            for item in sorted(items, key=lambda row: row.get("subject") or "")[:25]:
                msg_id = item.get("message_id", "")
                subject = (item.get("subject") or "(no subject)").replace("\n", " ")[:120]
                ai_label = item.get("ai_label") or "-"
                ai_conf = item.get("ai_confidence")
                ai_conf_str = f"{ai_conf:.2f}" if isinstance(ai_conf, (int, float)) else "-"
                score = item.get("parse_miss_score") or 0
                duration = item.get("duration_seconds")
                duration_str = f" {duration:.1f}s" if isinstance(duration, (int, float)) else ""
                lines.append(
                    f"- `{msg_id}` ai={ai_label}/{ai_conf_str} score={score}{duration_str}  "
                    f"_{subject}_"
                )
            lines.append("")

    lines.extend([
        "",
        "## Loop",
        "",
        "1. `python scripts/flight_ai_audit.py --reparse-cached` to refresh failures.",
        "2. `python scripts/freeze_parser_fixture.py --from-failures` to lock fixtures.",
        "3. Edit the parser. Re-run with `pytest tests/test_parser_regressions.py`.",
        "4. `python scripts/parser_open_misses.py` regenerates this file.",
        "",
    ])
    return "\n".join(lines)


def current_audit_miss_ids() -> set[str] | None:
    """Return message ids still missed in the latest audit report, if present."""
    if not AUDIT_RESULTS_PATH.exists():
        return None
    try:
        payload = json.loads(AUDIT_RESULTS_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None

    scanned = payload.get("scanned")
    if not isinstance(scanned, dict):
        return None

    miss_buckets = {"likely_flight_parser_missed", "likely_flight_discovery_missed"}
    miss_ids = {
        msg_id
        for msg_id, row in scanned.items()
        if isinstance(row, dict) and row.get("audit_bucket") in miss_buckets
    }
    return miss_ids


def main() -> None:
    all_latest = latest_per_message(iter_failures())
    # The failure log is append-only across parser versions. Once the parser
    # is bumped, older failure rows for the same message are stale: the new
    # parser may handle the case fine, and we just haven't re-run the audit
    # on those messages yet (or the new reparse already produced a flight,
    # in which case nothing was logged on the second pass). Keep only rows
    # at or above the current PARSER_VERSION so the report reflects what is
    # *actually* broken right now.
    rows = {
        msg_id: row
        for msg_id, row in all_latest.items()
        if int(row.get("parser_version") or 0) >= PARSER_VERSION
    }
    stale = len(all_latest) - len(rows)
    audit_miss_ids = current_audit_miss_ids()
    resolved_by_audit = 0
    if audit_miss_ids is not None:
        before = len(rows)
        rows = {
            msg_id: row
            for msg_id, row in rows.items()
            if msg_id in audit_miss_ids
        }
        resolved_by_audit = before - len(rows)
    text = render(rows)
    OUTPUT_PATH.write_text(text, encoding="utf-8")
    suffixes = []
    if stale:
        suffixes.append(f"{stale} stale older-version rows hidden")
    if resolved_by_audit:
        suffixes.append(f"{resolved_by_audit} resolved by current audit hidden")
    suffix = f", {', '.join(suffixes)}" if suffixes else ""
    print(f"Wrote {OUTPUT_PATH} ({len(rows)} open misses{suffix})")


if __name__ == "__main__":
    main()
