"""Benchmark v4 flight discovery against brute-force all-mail parsing.

This is a diagnostic script, not the production sync path. It stores only
headers and parsed flight metadata, never email bodies.

Usage:
    cd backend
    python scripts/flight_discovery_benchmark.py
    python scripts/flight_discovery_benchmark.py --analyze-only
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from dotenv import load_dotenv

load_dotenv(".env")
sys.path.insert(0, os.getcwd())

from app.services.flight_query_v4 import build_discovery_plan
from app.services.gmail import (
    build_gmail_service,
    extract_attachments,
    extract_headers,
    extract_message_body,
    get_message,
    list_messages,
)
from app.services.parser import parse_email

RESULTS_FILE = Path(__file__).parent / ".flight_discovery_benchmark.json"
PARSER_VERSION = 2


def get_token() -> bytes | None:
    conn = sqlite3.connect("trotter.db", uri=True)
    cursor = conn.cursor()
    cursor.execute("SELECT refresh_token_encrypted FROM accounts WHERE provider='google' LIMIT 1")
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None


def load_results() -> dict[str, Any]:
    if RESULTS_FILE.exists():
        results = json.loads(RESULTS_FILE.read_text())
        if results.get("parser_version") != PARSER_VERSION:
            results["parsed"] = {}
            results["parser_version"] = PARSER_VERSION
        return results
    return {
        "parser_version": PARSER_VERSION,
        "v4_ids": [],
        "v4_membership": {},
        "brute_ids": [],
        "parsed": {},
        "started_at": datetime.now(timezone.utc).isoformat(),
    }


def save_results(results: dict[str, Any]) -> None:
    RESULTS_FILE.write_text(json.dumps(results, indent=2, sort_keys=True))


def collect_ids(service, query: str, label: str) -> list[str]:
    ids: list[str] = []
    seen: set[str] = set()
    page_token = None
    pages = 0
    started = time.time()
    while True:
        messages, page_token = list_messages(service, query=query, page_token=page_token)
        for message in messages:
            msg_id = message["id"]
            if msg_id not in seen:
                seen.add(msg_id)
                ids.append(msg_id)
        pages += 1
        print(f"{label}: pages={pages} ids={len(ids)} elapsed={time.time() - started:.1f}s", flush=True)
        if not page_token:
            break
    return ids


def collect_v4_ids(service, results: dict[str, Any]) -> None:
    if results["v4_ids"]:
        print(f"v4: using cached ids={len(results['v4_ids'])}", flush=True)
        return

    state = SimpleNamespace(
        last_incremental_scan_at=None,
        backfill_cursor_before=None,
        backfill_complete=False,
    )
    plan = build_discovery_plan(state, now=datetime.now(timezone.utc), max_backfill_windows=1)
    seen: set[str] = set()
    membership: dict[str, list[str]] = defaultdict(list)

    for index, item in enumerate(plan, 1):
        ids = collect_ids(service, item.query, f"v4 {index}/{len(plan)} {item.tier}")
        new_count = 0
        for msg_id in ids:
            membership[msg_id].append(item.tier)
            if msg_id not in seen:
                seen.add(msg_id)
                new_count += 1
        print(f"v4 {index}/{len(plan)} new={new_count} unique_total={len(seen)}", flush=True)

    results["v4_ids"] = sorted(seen)
    results["v4_membership"] = dict(membership)
    save_results(results)


def collect_brute_ids(service, results: dict[str, Any]) -> None:
    if results["brute_ids"]:
        print(f"brute: using cached ids={len(results['brute_ids'])}", flush=True)
        return
    results["brute_ids"] = collect_ids(service, "", "brute all-mail")
    save_results(results)


def parse_message(service, msg_id: str) -> dict[str, Any]:
    try:
        message = get_message(service, msg_id)
        headers = extract_headers(message)
        plain_text, html = extract_message_body(message)
        attachments = extract_attachments(message)
        parsed = parse_email(
            html=html,
            plain_text=plain_text,
            attachments=attachments,
            user_name="",
            aliases=[],
            received_at=headers.get("date"),
        )
        return {
            "has_flights": bool(parsed.flights),
            "source": parsed.source if parsed.flights else None,
            "subject": headers.get("subject", "")[:240],
            "from": headers.get("from", "")[:240],
            "flights": [
                {
                    "dep_airport": flight.dep_airport,
                    "arr_airport": flight.arr_airport,
                    "dep_time": flight.dep_time.isoformat(),
                    "arr_time": flight.arr_time.isoformat(),
                    "airline": flight.airline,
                    "flight_number": flight.flight_number,
                    "pnr": flight.pnr,
                    "source": flight.source,
                }
                for flight in parsed.flights
            ],
        }
    except Exception as exc:
        return {
            "has_flights": False,
            "source": None,
            "subject": "",
            "from": "",
            "flights": [],
            "error": f"{type(exc).__name__}: {str(exc)[:240]}",
        }


def parse_brute_messages(service, results: dict[str, Any]) -> None:
    brute_ids = results["brute_ids"]
    parsed = results["parsed"]
    started = time.time()

    for index, msg_id in enumerate(brute_ids, 1):
        if msg_id not in parsed:
            parsed[msg_id] = parse_message(service, msg_id)
            if len(parsed) % 25 == 0:
                save_results(results)

        if index % 100 == 0 or index == len(brute_ids):
            flight_emails = sum(1 for item in parsed.values() if item.get("has_flights"))
            segments = sum(len(item.get("flights", [])) for item in parsed.values())
            print(
                "parse "
                f"{index}/{len(brute_ids)} cached={len(parsed)} "
                f"flight_emails={flight_emails} segments={segments} "
                f"elapsed={time.time() - started:.1f}s",
                flush=True,
            )

    save_results(results)


def unique_segments(parsed: dict[str, Any]) -> dict[tuple[str, str, str, str], dict[str, Any]]:
    segments: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for msg_id, item in parsed.items():
        for flight in item.get("flights", []):
            key = (
                flight.get("dep_airport") or "",
                flight.get("arr_airport") or "",
                flight.get("dep_time") or "",
                flight.get("flight_number") or "",
            )
            segments.setdefault(key, {"messages": [], **flight})
            segments[key]["messages"].append(msg_id)
    return segments


def infer_home_airport(segments: dict[tuple[str, str, str, str], dict[str, Any]]) -> str | None:
    counts: Counter[str] = Counter()
    for segment in segments.values():
        counts[segment["dep_airport"]] += 1
        counts[segment["arr_airport"]] += 1
    return counts.most_common(1)[0][0] if counts else None


def trip_summary(segments: dict[tuple[str, str, str, str], dict[str, Any]], home: str | None) -> list[dict[str, Any]]:
    by_pnr: dict[str, list[dict[str, Any]]] = defaultdict(list)
    no_pnr: list[dict[str, Any]] = []
    for segment in segments.values():
        if segment.get("pnr"):
            by_pnr[segment["pnr"]].append(segment)
        else:
            no_pnr.append(segment)

    groups = list(by_pnr.values())
    for segment in sorted(no_pnr, key=lambda item: item["dep_time"]):
        groups.append([segment])

    summaries: list[dict[str, Any]] = []
    for group in groups:
        ordered = sorted(group, key=lambda item: item["dep_time"])
        has_outbound = bool(home and any(item["dep_airport"] == home for item in ordered))
        has_return = bool(home and any(item["arr_airport"] == home for item in ordered))
        summaries.append(
            {
                "start": ordered[0]["dep_time"],
                "end": ordered[-1]["arr_time"],
                "segment_count": len(ordered),
                "route": " -> ".join([ordered[0]["dep_airport"]] + [item["arr_airport"] for item in ordered]),
                "has_outbound_from_home": has_outbound,
                "has_return_to_home": has_return,
                "pnr": ordered[0].get("pnr"),
            }
        )
    return summaries


def analyze(results: dict[str, Any]) -> None:
    parsed = results["parsed"]
    brute_ids = set(results["brute_ids"])
    v4_ids = set(results["v4_ids"])
    flight_message_ids = {msg_id for msg_id, item in parsed.items() if item.get("has_flights")}
    segments = unique_segments(parsed)
    home = infer_home_airport(segments)
    summaries = trip_summary(segments, home)

    missed_by_v4 = flight_message_ids - v4_ids
    extra_v4 = v4_ids - brute_ids
    source_counts = Counter(item.get("source") for item in parsed.values() if item.get("has_flights"))

    print("\n=== Flight Discovery Benchmark ===")
    print(f"brute_ids              : {len(brute_ids):,}")
    print(f"v4_ids                 : {len(v4_ids):,}")
    print(f"v4_not_in_brute         : {len(extra_v4):,}")
    print(f"parsed_messages         : {len(parsed):,}")
    print(f"flight_emails_brute     : {len(flight_message_ids):,}")
    print(f"unique_segments_brute   : {len(segments):,}")
    print(f"flight_emails_missed_v4 : {len(missed_by_v4):,}")
    print(f"parse_sources           : {dict(source_counts)}")
    print(f"inferred_home_airport   : {home or 'unknown'}")
    print(f"trip_groups             : {len(summaries):,}")
    print(f"groups_with_outbound    : {sum(1 for item in summaries if item['has_outbound_from_home']):,}")
    print(f"groups_with_return      : {sum(1 for item in summaries if item['has_return_to_home']):,}")
    print(f"groups_with_both        : {sum(1 for item in summaries if item['has_outbound_from_home'] and item['has_return_to_home']):,}")

    if missed_by_v4:
        print("\nFlights found by brute force but missed by v4:")
        for msg_id in sorted(missed_by_v4):
            item = parsed[msg_id]
            print(f"- {msg_id} | {item.get('from')} | {item.get('subject')}")
            for flight in item.get("flights", []):
                print(
                    "  "
                    f"{flight['dep_time']} {flight['dep_airport']}->{flight['arr_airport']} "
                    f"{flight.get('flight_number') or ''}"
                )

    print("\nTrip groups:")
    for item in sorted(summaries, key=lambda row: row["start"]):
        flags = []
        if item["has_outbound_from_home"]:
            flags.append("outbound")
        if item["has_return_to_home"]:
            flags.append("return")
        print(
            f"- {item['start'][:10]}..{item['end'][:10]} "
            f"{item['route']} segments={item['segment_count']} "
            f"pnr={item.get('pnr') or '-'} flags={','.join(flags) or '-'}"
        )


def run(analyze_only: bool) -> None:
    results = load_results()
    if analyze_only:
        analyze(results)
        return

    token = get_token()
    if not token:
        print("No Google account found in trotter.db.")
        return

    service = build_gmail_service(token)
    collect_v4_ids(service, results)
    collect_brute_ids(service, results)
    parse_brute_messages(service, results)
    analyze(results)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--analyze-only", action="store_true")
    args = parser.parse_args()
    run(analyze_only=args.analyze_only)
