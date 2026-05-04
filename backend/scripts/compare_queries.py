import os
import sys
import sqlite3
import time
import json
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.services.gmail import (
    build_gmail_service, list_messages, get_message,
    extract_message_body, extract_attachments, extract_headers,
)
from app.services.flight_query import build_gmail_query as build_v1
from app.services.flight_query_v2 import build_gmail_queries as build_v2
from app.services.flight_query_v3 import build_gmail_queries as build_v3
from app.services.parser import parse_email

RESULTS_FILE = Path(__file__).parent / "compare_results.json"


def get_token():
    conn = sqlite3.connect("trotter.db", uri=True)
    cursor = conn.cursor()
    cursor.execute("SELECT refresh_token_encrypted FROM accounts WHERE provider='google' LIMIT 1")
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None


def load_results() -> dict:
    if RESULTS_FILE.exists():
        return json.loads(RESULTS_FILE.read_text())
    return {}


def save_results(results: dict) -> None:
    RESULTS_FILE.write_text(json.dumps(results, indent=2))


def collect_ids(service, query: str, label: str) -> set:
    print(f"\n--- Collecting IDs: {label} ---")
    msg_ids = set()
    page_token = None
    pages = 0
    start = time.time()
    while True:
        messages, next_token = list_messages(service, query=query, page_token=page_token)
        for msg in messages:
            msg_ids.add(msg["id"])
        pages += 1
        sys.stdout.write(f"\r  {pages} pages, {len(msg_ids)} messages so far")
        sys.stdout.flush()
        if not next_token:
            break
        page_token = next_token
    print(f"\n  Done in {time.time() - start:.1f}s. Total: {len(msg_ids)}")
    return msg_ids


def collect_query_group(service, queries: list[str], label: str) -> set:
    msg_ids = set()
    for i, query in enumerate(queries, 1):
        msg_ids.update(collect_ids(service, query, f"{label} {i}/{len(queries)}"))
    print(f"\n--- {label}: {len(msg_ids)} unique messages across {len(queries)} queries ---")
    return msg_ids


def parse_message(service, msg_id: str) -> dict:
    try:
        full_msg = get_message(service, msg_id)
    except Exception as exc:
        return {"error": str(exc), "has_flights": False, "flight_count": 0, "source": None}

    headers = extract_headers(full_msg)
    plain_text, html = extract_message_body(full_msg)
    attachments = extract_attachments(full_msg)

    result = parse_email(
        html=html,
        plain_text=plain_text,
        attachments=attachments,
        user_name="",
        aliases=[],
    )

    return {
        "has_flights": bool(result.flights),
        "flight_count": len(result.flights),
        "source": result.source if result.flights else None,
        "subject": headers.get("subject", "")[:80],
        "from": headers.get("from", "")[:80],
    }


def run_comparison():
    token_encrypted = get_token()
    if not token_encrypted:
        print("No Google account found in database.")
        return

    print("Building Gmail service...")
    service = build_gmail_service(token_encrypted)

    q_v1 = build_v1()
    q_v2 = build_v2()
    q_v3 = build_v3()

    # Step 1: Collect message IDs for both queries
    v1_ids = collect_ids(service, q_v1, "v1 (Domain/Keyword List)")
    v2_ids = collect_query_group(service, q_v2, "v2 (Smart Hybrid)")
    v3_ids = collect_query_group(service, q_v3, "v3 (Production Bounded v1)")
    all_ids = v1_ids | v2_ids | v3_ids

    def which(msg_id: str) -> str:
        if msg_id in v1_ids and msg_id in v2_ids:
            return "both"
        if msg_id in v3_ids and msg_id not in v1_ids and msg_id not in v2_ids:
            return "v3_only"
        return "v1_only" if msg_id in v1_ids else "v2_only"

    # Step 2: Load any previously parsed results
    results = load_results()

    # Step 3: Parse emails not yet cached
    to_parse = [mid for mid in all_ids if mid not in results]
    print(f"\n--- Parsing {len(to_parse)} new emails ({len(all_ids)} total, {len(results)} already cached) ---")

    for i, msg_id in enumerate(to_parse, 1):
        sys.stdout.write(f"\r  {i}/{len(to_parse)}: {msg_id[:12]}…   ")
        sys.stdout.flush()
        result = parse_message(service, msg_id)
        result["found_by"] = which(msg_id)
        results[msg_id] = result
        if i % 25 == 0:
            save_results(results)

    save_results(results)
    print(f"\n  Saved to {RESULTS_FILE}")

    # Refresh found_by for all IDs in case query membership changed between runs
    for msg_id in all_ids:
        if msg_id in results:
            results[msg_id]["found_by"] = which(msg_id)
    save_results(results)

    # Step 4: Analysis
    v1_total     = len(v1_ids)
    v2_total     = len(v2_ids)
    v3_total     = len(v3_ids)
    v1_flights   = sum(1 for mid in v1_ids if results.get(mid, {}).get("has_flights"))
    v2_flights   = sum(1 for mid in v2_ids if results.get(mid, {}).get("has_flights"))
    v3_flights   = sum(1 for mid in v3_ids if results.get(mid, {}).get("has_flights"))
    both_flights = sum(1 for mid in v1_ids & v2_ids if results.get(mid, {}).get("has_flights"))
    only_v1      = sum(1 for mid in v1_ids - v2_ids if results.get(mid, {}).get("has_flights"))
    only_v2      = sum(1 for mid in v2_ids - v1_ids if results.get(mid, {}).get("has_flights"))

    print("\n=== Query coverage ===")
    print(f"  v1 matched emails : {v1_total:,}")
    print(f"  v2 matched emails : {v2_total:,}")
    print(f"  v3 matched emails : {v3_total:,}")
    print(f"  Total unique      : {len(all_ids):,}")

    print("\n=== Actual flight emails found by parser ===")
    print(f"  v1 total          : {v1_flights}  ({v1_flights/v1_total*100:.1f}% of v1 matches)")
    print(f"  v2 total          : {v2_flights}  ({v2_flights/v2_total*100:.1f}% of v2 matches)")
    print(f"  v3 total          : {v3_flights}  ({v3_flights/v3_total*100:.1f}% of v3 matches)")
    print(f"  Found by BOTH     : {both_flights}")
    print(f"  Found ONLY by v1  : {only_v1}")
    print(f"  Found ONLY by v2  : {only_v2}")
    print(f"\n  Winner            : {'v1' if v1_flights > v2_flights else 'v2' if v2_flights > v1_flights else 'tie'}")


if __name__ == "__main__":
    run_comparison()
