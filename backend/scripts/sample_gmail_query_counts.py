"""Read-only Gmail query sampler for flight discovery tuning.

Counts Gmail message stubs only. It does not fetch full messages, parse bodies,
or write to the database.

Usage:
    cd backend
    poetry run python scripts/sample_gmail_query_counts.py --user-email you@example.com
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

load_dotenv(".env")
sys.path.insert(0, os.getcwd())

from app.db import SessionLocal
from app.models import Account, User
from app.services.flight_query_v4 import (
    build_fast_known_sender_queries,
    build_fast_strong_keyword_queries,
)
from app.services.gmail import build_gmail_service, list_messages


def _gmail_date(dt: datetime) -> str:
    return f"{dt.year}/{dt.month}/{dt.day}"


def _collect_ids(service, query: str, *, max_pages: int | None) -> set[str]:
    ids: set[str] = set()
    page_token = None
    pages = 0
    while True:
        messages, page_token = list_messages(service, query=query, page_token=page_token)
        pages += 1
        for msg in messages:
            msg_id = msg.get("id")
            if msg_id:
                ids.add(msg_id)
        print(f"    pages={pages:,} ids={len(ids):,}")
        if max_pages and pages >= max_pages:
            break
        if not page_token:
            break
    return ids


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--user-email", required=True)
    parser.add_argument("--recent-days", type=int, default=730)
    parser.add_argument("--max-pages", type=int, default=None)
    args = parser.parse_args()

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == args.user_email).first()
        if not user:
            raise SystemExit(f"User not found: {args.user_email}")
        account = db.query(Account).filter(Account.user_id == user.id, Account.provider == "google").first()
        if not account:
            raise SystemExit(f"Google account not linked for: {args.user_email}")
        service = build_gmail_service(account.refresh_token_encrypted)
    finally:
        db.close()

    recent_since = _gmail_date(datetime.now(timezone.utc) - timedelta(days=args.recent_days))
    query_groups: dict[str, list[str]] = {
        "category_travel_all": ["category:travel"],
        "category_travel_no_promotions": ["category:travel -category:promotions"],
        "category_travel_recent": [f"after:{recent_since} category:travel"],
        "category_travel_recent_no_promotions": [f"after:{recent_since} category:travel -category:promotions"],
        "fast_known_senders_recent": build_fast_known_sender_queries(since=recent_since),
        "fast_strong_keywords_recent": build_fast_strong_keyword_queries(since=recent_since),
    }

    results: dict[str, set[str]] = {}
    for label, queries in query_groups.items():
        print(f"\n{label}")
        ids: set[str] = set()
        for index, query in enumerate(queries, 1):
            print(f"  query {index}/{len(queries)}: {query[:180]}")
            ids.update(_collect_ids(service, query, max_pages=args.max_pages))
        results[label] = ids
        print(f"  unique ids: {len(ids):,}")

    print("\nOverlap")
    known = results["fast_known_senders_recent"]
    keywords = results["fast_strong_keywords_recent"]
    travel = results["category_travel_recent_no_promotions"]
    print(f"  known_senders + strong_keywords unique: {len(known | keywords):,}")
    print(f"  travel_recent_no_promotions overlap with fast: {len(travel & (known | keywords)):,}")
    print(f"  travel_recent_no_promotions only: {len(travel - (known | keywords)):,}")


if __name__ == "__main__":
    main()
