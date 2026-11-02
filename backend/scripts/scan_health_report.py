"""Read-only operational scan report; credentials are read from DATABASE_URL only."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sqlite3
import sys

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.scan_health import build_scan_health, render_scan_health


def read_report(database_url, **options):
    """Enforce a read-only transaction independently of database-role grants."""
    if not database_url:
        raise ValueError("DATABASE_URL must be set")
    url = make_url(database_url)
    dialect = url.get_backend_name()
    if dialect == "sqlite":
        if not url.database or url.database == ":memory:" or url.query:
            raise ValueError("Use an existing SQLite file without URL parameters")
        database = Path(url.database).resolve(strict=True)
        if not database.is_file():
            raise ValueError("SQLite database must be an existing file")
        engine = create_engine("sqlite://", creator=lambda: sqlite3.connect(database.as_uri() + "?mode=ro", uri=True))
    elif dialect == "postgresql":
        engine = create_engine(url, hide_parameters=True)
    else:
        raise ValueError("Only PostgreSQL and existing SQLite files are supported")
    try:
        with engine.connect() as connection:
            if dialect == "postgresql":
                connection.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
                connection.execute(text("SET LOCAL statement_timeout = '60s'"))
            else:
                connection.exec_driver_sql("PRAGMA query_only=ON")
                # Python sqlite3 otherwise defers BEGIN until the first write.
                connection.exec_driver_sql("BEGIN")
            with Session(bind=connection, autoflush=False) as session:
                return build_scan_health(session, **options)
    finally:
        engine.dispose()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--user-id", type=int, action="append", dest="user_ids", help="Internal account ID; may be repeated")
    scope.add_argument("--all-users", action="store_true", help="Explicitly inspect all accounts")
    parser.add_argument("--hours", type=int, default=24, help="Terminal job lookback; all active jobs are always included")
    parser.add_argument("--stale-minutes", type=int, default=30)
    parser.add_argument("--pending-minutes", type=int, default=15)
    parser.add_argument("--max-jobs", type=int, default=50, help="Maximum detailed job rows, not aggregate scope")
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--fail-on-attention", action="store_true", help="Exit 1 when operational attention is needed")
    args = parser.parse_args(argv)
    try:
        report = read_report(os.environ.get("DATABASE_URL"), user_ids=args.user_ids,
            lookback_hours=args.hours, stale_minutes=args.stale_minutes,
            pending_minutes=args.pending_minutes, max_jobs=args.max_jobs)
    except Exception:
        # Connection and SQL errors may include passwords, URLs, or parameters.
        print("Scan-health report failed. Check DATABASE_URL, read access, schema availability, and positive report limits. No database changes were made.", file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2, sort_keys=True) if args.as_json else render_scan_health(report), end="\n" if args.as_json else "")
    return 1 if args.fail_on_attention and report["attention_required"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
