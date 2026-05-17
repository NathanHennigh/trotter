"""Seed canonical Message rows from developer audit result files.

This bridges audit-only Gmail scans back into the local app database so repair
tools can refetch and parse older confirmed messages that production discovery
has not backfilled yet.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from email.utils import parsedate_to_datetime
from hashlib import sha256
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(".env")
sys.path.insert(0, os.getcwd())

from app.db import SessionLocal
from app.models import Message, MessageStatus, User


def _parse_date(value: str | None):
    if not value:
        return None
    try:
        return parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        return None


def seed(user_email: str, files: list[Path], *, apply: bool) -> dict[str, int]:
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == user_email).first()
        if not user:
            raise SystemExit(f"User not found: {user_email}")

        seen = inserted = existing = 0
        for path in files:
            payload = json.loads(path.read_text(encoding="utf-8"))
            for message_id, row in payload.get("scanned", {}).items():
                seen += 1
                current = (
                    db.query(Message)
                    .filter(Message.user_id == user.id, Message.provider_msg_id == message_id)
                    .first()
                )
                if current:
                    existing += 1
                    continue
                if not apply:
                    inserted += 1
                    continue
                sender = row.get("from") or ""
                db.add(
                    Message(
                        user_id=user.id,
                        provider_msg_id=message_id,
                        internal_ts=_parse_date(row.get("date")),
                        from_domain_hash=sha256((row.get("sender_domain") or "").encode("utf-8")).hexdigest()
                        if row.get("sender_domain")
                        else None,
                        from_email=sender,
                        subject=row.get("subject"),
                        snippet_sha256=sha256((row.get("safe_snippet") or "").encode("utf-8")).hexdigest()
                        if row.get("safe_snippet")
                        else None,
                        status=MessageStatus.PENDING,
                    )
                )
                inserted += 1

        if apply:
            db.commit()
        return {"seen": seen, "inserted": inserted, "existing": existing}
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--user-email", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("files", nargs="+", type=Path)
    args = parser.parse_args()
    print(seed(args.user_email, args.files, apply=args.apply))


if __name__ == "__main__":
    main()
