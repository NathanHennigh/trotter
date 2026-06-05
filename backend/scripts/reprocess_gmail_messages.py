"""Run a targeted Gmail message reparse from the local backend environment."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load_env() -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env")
    except Exception:
        pass


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user-id", type=int, help="Local Trotter user id")
    parser.add_argument("--email", help="Local Trotter user email")
    parser.add_argument("--ids", nargs="+", required=True, help="Gmail message ids to reprocess first")
    parser.add_argument("--limit", type=int, default=None, help="Maximum stale messages to reprocess")
    args = parser.parse_args()

    _load_env()
    os.environ["TROTTER_REPARSE_MESSAGE_IDS"] = ",".join(args.ids)
    if args.limit:
        os.environ["TROTTER_STALE_REPARSE_MAX_PER_SYNC"] = str(args.limit)

    from app.db import SessionLocal
    from app.models import SyncJob, User
    from app.tasks.import_tasks import run_gmail_import

    db = SessionLocal()
    try:
        query = db.query(User)
        if args.user_id:
            user = query.filter(User.id == args.user_id).first()
        elif args.email:
            user = query.filter(User.email == args.email).first()
        else:
            user = query.order_by(User.id.asc()).first()
        if not user:
            raise SystemExit("No matching user found. Pass --user-id or --email.")
        selected_user_id = int(user.id)

        job_id = str(uuid4())
        now = datetime.now(timezone.utc)
        db.add(SyncJob(id=job_id, user_id=selected_user_id, state="pending", started_at=now, updated_at=now))
        db.commit()
    finally:
        db.close()

    result = run_gmail_import.run(job_id=job_id, user_id=selected_user_id, limit=args.limit, mode="reparse")
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
