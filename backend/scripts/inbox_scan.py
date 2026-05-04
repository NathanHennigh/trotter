"""
Bulk inbox scan for v3 query development.

Scans every email in your inbox (no pre-filter), runs parse_email on each one,
then reports what keywords and sender domains consistently appear in confirmed
flight emails. Use the output to build a tighter v3 Gmail query.

Usage:
    cd backend
    python scripts/inbox_scan.py                  # full scan (slow, resumable)
    python scripts/inbox_scan.py --analyze-only   # just re-print stats from cache
    python scripts/inbox_scan.py --query "category:travel"  # narrow scope

Results are saved to scripts/inbox_scan_results.json after every 50 emails,
so you can Ctrl-C and resume later without losing work.
"""

import argparse
import json
import os
import re
import sqlite3
import sys
import time
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.gmail import (
    build_gmail_service,
    extract_attachments,
    extract_headers,
    extract_message_body,
    get_message,
    list_messages,
)
from app.services.flight_query import build_gmail_query as build_v1
from app.services.flight_query_v2 import build_gmail_queries as build_v2
from app.services.flight_query_v3 import build_gmail_queries as build_v3
from app.services.parser import parse_email

RESULTS_FILE = Path(__file__).parent / "inbox_scan_results.json"

STOP_WORDS = {
    "the", "a", "an", "is", "in", "on", "at", "to", "for", "of", "and", "or",
    "your", "you", "re", "from", "with", "this", "that", "has", "are", "was",
    "it", "have", "be", "as", "by", "we", "our", "us", "my", "me", "i", "not",
    "but", "so", "if", "do", "can", "all", "any", "get", "its", "new", "now",
    "one", "two", "up", "out", "no", "about", "which", "when", "will", "been",
    "also", "into", "just", "than", "then", "they", "their", "there",
}


# ─── helpers ──────────────────────────────────────────────────────────────────

def get_token():
    conn = sqlite3.connect("trotter.db", uri=True)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT refresh_token_encrypted FROM accounts WHERE provider='google' LIMIT 1"
    )
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None


def load_results() -> dict:
    if RESULTS_FILE.exists():
        return json.loads(RESULTS_FILE.read_text())
    return {"scanned": {}, "v1_ids": None, "v2_ids": None, "v3_ids": None}


def save_results(results: dict) -> None:
    RESULTS_FILE.write_text(json.dumps(results, indent=2))


def parse_one(service, msg_id: str) -> dict:
    try:
        full_msg = get_message(service, msg_id)
        headers = extract_headers(full_msg)
        plain_text, html = extract_message_body(full_msg)
        attachments = extract_attachments(full_msg)
        result = parse_email(
            html=html, plain_text=plain_text, attachments=attachments,
            user_name="", aliases=[],
        )
        sender = headers.get("from", "")
        domain = sender.split("@")[-1].rstrip(">").strip() if "@" in sender else ""
        return {
            "has_flight": bool(result.flights),
            "flight_count": len(result.flights),
            "source": result.source if result.flights else None,
            "subject": headers.get("subject", "")[:200],
            "sender": sender[:200],
            "domain": domain,
        }
    except Exception as exc:
        return {"has_flight": False, "error": str(exc)[:120]}


def collect_ids(service, query: str, label: str) -> list[str]:
    ids = []
    page_token = None
    while True:
        msgs, page_token = list_messages(service, query=query, page_token=page_token)
        ids.extend(m["id"] for m in msgs)
        sys.stdout.write(f"\r  {label}: {len(ids):,} IDs collected")
        sys.stdout.flush()
        if not page_token:
            break
    print()
    return ids


def collect_query_group(service, queries: list[str], label: str) -> list[str]:
    ids: list[str] = []
    seen: set[str] = set()
    for i, query in enumerate(queries, 1):
        for msg_id in collect_ids(service, query, f"{label} {i}/{len(queries)}"):
            if msg_id not in seen:
                seen.add(msg_id)
                ids.append(msg_id)
    print(f"  {label}: {len(ids):,} unique IDs collected")
    return ids


# ─── analysis ─────────────────────────────────────────────────────────────────

def analyze(results: dict) -> None:
    scanned = results["scanned"]
    flight_msgs = {mid: r for mid, r in scanned.items() if r.get("has_flight")}
    total = len(scanned)

    print(f"\n{'='*62}")
    print(f"  INBOX SCAN ANALYSIS")
    print(f"  {len(flight_msgs):,} confirmed flight emails out of {total:,} scanned")
    print(f"{'='*62}")

    if not flight_msgs:
        print("  No confirmed flight emails found yet — run without --analyze-only.")
        return

    # ── sender domains ──────────────────────────────────────────────────────
    domain_counts = Counter(r["domain"] for r in flight_msgs.values() if r.get("domain"))
    print(f"\nTop 30 sender domains in confirmed flight emails:")
    for domain, count in domain_counts.most_common(30):
        pct = count / len(flight_msgs) * 100
        print(f"  {count:5d} ({pct:4.1f}%)  {domain}")

    # ── subject keywords ────────────────────────────────────────────────────
    word_counts: Counter = Counter()
    phrase_counts: Counter = Counter()
    for r in flight_msgs.values():
        subj = r.get("subject", "").lower()
        words = re.findall(r"\b[a-z]{3,}\b", subj)
        filtered = [w for w in words if w not in STOP_WORDS]
        for w in filtered:
            word_counts[w] += 1
        # bigrams
        for i in range(len(filtered) - 1):
            phrase_counts[f"{filtered[i]} {filtered[i+1]}"] += 1

    print(f"\nTop 40 subject keywords in confirmed flight emails:")
    for word, count in word_counts.most_common(40):
        pct = count / len(flight_msgs) * 100
        print(f"  {count:5d} ({pct:4.1f}%)  {word}")

    print(f"\nTop 20 subject bigrams:")
    for phrase, count in phrase_counts.most_common(20):
        pct = count / len(flight_msgs) * 100
        print(f"  {count:5d} ({pct:4.1f}%)  {phrase}")

    # ── parse source breakdown ───────────────────────────────────────────────
    source_counts = Counter(r.get("source") for r in flight_msgs.values() if r.get("source"))
    print(f"\nParse source (how the flight was extracted):")
    for src, count in source_counts.most_common():
        print(f"  {count:5d}  {src}")

    # ── query coverage ───────────────────────────────────────────────────────
    v1_set = set(results.get("v1_ids") or [])
    v2_set = set(results.get("v2_ids") or [])
    flight_ids = set(flight_msgs.keys())

    if v1_set or v2_set:
        print(f"\nQuery coverage over confirmed flight emails:")
        if v1_set:
            caught = len(flight_ids & v1_set)
            print(f"  v1 caught: {caught:,}/{len(flight_ids):,}  ({caught/max(1,len(flight_ids))*100:.1f}%)")
        if v2_set:
            caught = len(flight_ids & v2_set)
            print(f"  v2 caught: {caught:,}/{len(flight_ids):,}  ({caught/max(1,len(flight_ids))*100:.1f}%)")

        missed_by_both = flight_ids - v1_set - v2_set
        if missed_by_both:
            print(f"\nFlight emails MISSED by both v1 and v2 ({len(missed_by_both)} total):")
            for mid in list(missed_by_both)[:25]:
                r = scanned[mid]
                print(f"  Subject: {r.get('subject','')[:80]}")
                print(f"  Sender:  {r.get('sender','')[:70]}")
                print()
        else:
            print(f"\n  All confirmed flight emails were caught by at least one query.")


# ─── main ─────────────────────────────────────────────────────────────────────

def run_scan(query: str | None) -> None:
    token_enc = get_token()
    if not token_enc:
        print("No Google account found in database.")
        return

    print("Building Gmail service...")
    service = build_gmail_service(token_enc)
    results = load_results()

    # Cache v1/v2 query IDs once for coverage analysis
    if results["v1_ids"] is None:
        print("\nCollecting v1 query IDs for coverage analysis...")
        results["v1_ids"] = collect_ids(service, build_v1(), "v1")
        save_results(results)

    if results["v2_ids"] is None:
        print("Collecting v2 query IDs for coverage analysis...")
        results["v2_ids"] = collect_query_group(service, build_v2(), "v2")
        save_results(results)

    if results.get("v3_ids") is None:
        print("Collecting v3 query IDs for coverage analysis...")
        results["v3_ids"] = collect_query_group(service, build_v3(), "v3")
        save_results(results)

    # Collect all inbox IDs under the given query (or all mail)
    scan_q = query if query is not None else ""
    scope_label = f"'{scan_q}'" if scan_q else "all mail (no filter)"
    print(f"\nCollecting all message IDs for {scope_label}...")
    all_ids = collect_ids(service, scan_q, "inbox")
    print(f"  Total messages: {len(all_ids):,}")

    to_scan = [mid for mid in all_ids if mid not in results["scanned"]]
    already_done = len(all_ids) - len(to_scan)
    print(f"  Already cached: {already_done:,}   New to parse: {len(to_scan):,}")
    print("  Ctrl-C at any time — progress is saved every 50 emails.\n")

    t0 = time.time()
    for i, msg_id in enumerate(to_scan, 1):
        elapsed = time.time() - t0
        rate = i / elapsed if elapsed > 0 else 0
        eta = int((len(to_scan) - i) / rate) if rate > 0 else 0
        sys.stdout.write(
            f"\r  {i:,}/{len(to_scan):,}  "
            f"({rate:.1f}/s  ETA {eta//60}m{eta%60:02d}s)   "
        )
        sys.stdout.flush()
        results["scanned"][msg_id] = parse_one(service, msg_id)
        if i % 50 == 0:
            save_results(results)

    save_results(results)
    print(f"\n\n  Done! Results saved to {RESULTS_FILE}")
    analyze(results)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Bulk inbox scan for v3 query development")
    parser.add_argument("--query", default=None, help="Gmail search query (default: all messages)")
    parser.add_argument("--analyze-only", action="store_true", help="Print analysis from cached results without scanning")
    args = parser.parse_args()

    if args.analyze_only:
        analyze(load_results())
    else:
        run_scan(query=args.query)
