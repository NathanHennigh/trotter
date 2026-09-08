"""Index saved booking evidence in private travel inboxes, without reparsing mail.

Requires DATABASE_URL explicitly in the environment and migration 0009 applied.
Defaults to a rollback-only preview. No passenger names or booking details are
printed. Each user is processed atomically under the normal import lock.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--user-id", type=int, action="append", help="Owner to backfill; repeat for multiple users")
    scope.add_argument("--all-users", action="store_true", help="Backfill each existing owner")
    parser.add_argument("--apply", action="store_true", help="Commit the additive inbox records (default: roll back)")
    args = parser.parse_args(argv)
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        parser.error("DATABASE_URL must be set explicitly")

    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.models import User
    from app.services.import_lock import user_import_lock
    from app.services.travel_inbox import backfill_user_travel_inbox

    engine = create_engine(database_url)
    results = []
    try:
        with Session(engine) as db:
            user_ids = [value for (value,) in db.query(User.id).order_by(User.id)] if args.all_users else sorted(set(args.user_id))
        for user_id in user_ids:
            with user_import_lock(engine, user_id), Session(engine) as db:
                try:
                    result = backfill_user_travel_inbox(db, user_id)
                    if args.apply:
                        db.commit()
                    else:
                        db.rollback()
                    results.append({"user_id": user_id, **result})
                except BaseException:
                    db.rollback()
                    raise
        print(json.dumps({"applied": args.apply, "users": results}, indent=2))
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
