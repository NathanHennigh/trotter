"""Reconcile known Gmail booking evidence without clearing existing travel.

This is a local repair tool for development data. It re-fetches message bodies
from Gmail by provider message ID, reparses with the current deterministic
parser, and applies the same scoped ownership/cancellation policy as normal sync.
Unfetched, unresolved, and unrelated legacy travel stays intact. Existing graph
backups and the immutable booking ledger preserve the evidence behind changes.

Usage:
    cd backend
    python scripts/rebuild_flight_segments.py --user-email you@example.com --dry-run
    python scripts/rebuild_flight_segments.py --user-email you@example.com --apply
    python scripts/rebuild_flight_segments.py --user-email you@example.com --apply --limit 500
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv(".env")
sys.path.insert(0, os.getcwd())

from app.db import SessionLocal
from app.models import Account, Message, MessageStatus, Segment, Trip, User
from app.services.booking_import import apply_booking_message, set_message_outcome
from app.services.enrichment import enrich_user_segments
from app.services.import_lock import user_import_lock
from app.services.gmail import (
    build_gmail_service,
    extract_attachments,
    extract_headers,
    extract_message_body,
    get_message,
)
from app.services.flight_query_v2 import looks_like_flight_email
from app.services.parse_audit import assess_parse_miss
from app.services.parser import PARSER_VERSION, parse_email


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _backup_path(user_id: int) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return Path(__file__).parent / f"rebuild_flight_segments_backup_user_{user_id}_{stamp}.json"


def _backup_graph(db, user_id: int) -> Path:
    trips = db.query(Trip).filter(Trip.user_id == user_id).order_by(Trip.start_ts, Trip.id).all()
    trip_ids = [trip.id for trip in trips]
    segments = []
    if trip_ids:
        segments = db.query(Segment).filter(Segment.trip_id.in_(trip_ids)).order_by(Segment.dep_time, Segment.id).all()

    payload = {
        "created_at": datetime.now(timezone.utc),
        "parser_version": PARSER_VERSION,
        "user_id": user_id,
        "trips": [
            {
                "id": trip.id,
                "title": trip.title,
                "start_ts": trip.start_ts,
                "end_ts": trip.end_ts,
                "visibility": trip.visibility,
            }
            for trip in trips
        ],
        "segments": [
            {
                "id": segment.id,
                "trip_id": segment.trip_id,
                "mode": segment.mode,
                "dep_airport": segment.dep_airport,
                "arr_airport": segment.arr_airport,
                "dep_time": segment.dep_time,
                "arr_time": segment.arr_time,
                "airline": segment.airline,
                "flight_number": segment.flight_number,
                "pnr": segment.pnr,
                "distance_km": segment.distance_km,
                "geom": segment.geom,
                "meta_json": segment.meta_json,
            }
            for segment in segments
        ],
    }
    path = _backup_path(user_id)
    path.write_text(json.dumps(payload, indent=2, default=_json_default), encoding="utf-8")
    return path


def _message_sort_key(message: Message):
    return (
        message.internal_ts or message.created_at or datetime.min,
        message.id or 0,
    )


def rebuild(user_email: str, *, apply: bool, limit: int | None, progress_every: int) -> dict[str, Any]:
    db = SessionLocal()
    locks = ExitStack()
    try:
        user = db.query(User).filter(User.email == user_email).first()
        if not user:
            raise SystemExit(f"User not found: {user_email}")
        if apply:
            locks.enter_context(user_import_lock(db.get_bind(), user.id))
        account = (
            db.query(Account)
            .filter(Account.user_id == user.id, Account.provider == "google")
            .first()
        )
        if not account:
            raise SystemExit(f"No Google account linked for {user_email}")

        before_trips = db.query(Trip).filter(Trip.user_id == user.id).count()
        before_segments = db.query(Segment).join(Trip).filter(Trip.user_id == user.id).count()
        message_query = (
            db.query(Message)
            .filter(Message.user_id == user.id, Message.ignored.is_(False))
            .order_by(Message.internal_ts.asc().nullslast(), Message.created_at.asc(), Message.id.asc())
        )
        if limit:
            message_query = message_query.limit(limit)
        messages = message_query.all()
        messages = sorted(messages, key=_message_sort_key)

        service = build_gmail_service(account.refresh_token_encrypted)
        backup_file = None
        if apply:
            backup_file = _backup_graph(db, user.id)
        touched_segment_ids: set[int] = set()

        report = {
            "mode": "apply" if apply else "dry-run",
            "user_email": user.email,
            "parser_version": PARSER_VERSION,
            "backup_file": str(backup_file) if backup_file else None,
            "before_trips": before_trips,
            "before_segments": before_segments,
            "known_messages": len(messages),
            "fetched_messages": 0,
            "parsed_messages": 0,
            "candidate_segments": 0,
            "inserted_segments": 0,
            "updated_segments": 0,
            "skipped_segments": 0,
            "canceled_segments": 0,
            "review_candidates": 0,
            "held_other": 0,
            "held_unknown": 0,
            "blocked_cancellation": 0,
            "fetch_errors": 0,
            "after_trips": before_trips,
            "after_segments": before_segments,
        }

        print(
            f"Rebuild {'APPLY' if apply else 'DRY-RUN'} for {user.email}: "
            f"{len(messages)} known messages, {before_segments} current segments, parser v{PARSER_VERSION}",
            flush=True,
        )
        user_name = user.name or user.email
        for index, message in enumerate(messages, 1):
            if index == 1 or index % progress_every == 0:
                print(
                    f"fetch {index}/{len(messages)} id={message.provider_msg_id} "
                    f"parsed={report['parsed_messages']} candidates={report['candidate_segments']} "
                    f"errors={report['fetch_errors']}",
                    flush=True,
                )
            try:
                full_msg = get_message(service, message.provider_msg_id)
            except Exception as exc:
                report["fetch_errors"] += 1
                print(f"fetch failed {index}/{len(messages)} id={message.provider_msg_id}: {exc}", flush=True)
                continue

            report["fetched_messages"] += 1
            headers = extract_headers(full_msg)
            plain_text, html = extract_message_body(full_msg)
            attachments = extract_attachments(full_msg)
            body_for_filter = plain_text if plain_text.strip() else html
            subject = headers.get("subject") or message.subject or ""
            sender = headers.get("from") or message.from_email or ""

            parse_result = parse_email(
                html=html,
                plain_text=plain_text,
                attachments=attachments,
                user_name=user_name,
                aliases=list(user.travel_name_aliases or []),
                received_at=headers.get("date"),
                subject=subject,
                from_email=sender,
            )
            if parse_result.flights:
                report["parsed_messages"] += 1
                report["candidate_segments"] += len(parse_result.flights)

            if not apply:
                continue

            applied = apply_booking_message(
                db, user.id, parse_result, source_message_id=message.provider_msg_id,
                subject=subject, plain_text=plain_text, html=html, received_at=headers.get("date"),
            )
            if parse_result.flights or applied.is_cancellation:
                result = applied.build
                report["inserted_segments"] += result.inserted
                report["updated_segments"] += result.updated
                report["skipped_segments"] += result.skipped
                report["canceled_segments"] += applied.canceled
                report["held_other"] += result.held_other
                report["held_unknown"] += result.held_unknown
                report["blocked_cancellation"] += result.blocked_cancellation
                touched_segment_ids.update(result.affected_segment_ids)
                set_message_outcome(message, applied, source=parse_result.source, tier="repair_script")
                if message.status == MessageStatus.REVIEW_REQUIRED:
                    report["review_candidates"] += 1
            else:
                if not looks_like_flight_email(subject=subject, sender=sender, body=body_for_filter):
                    message.status = MessageStatus.ACCEPTED
                    message.parse_error = "not_flight_like"
                    message.parse_evidence = None
                    message.parse_version = PARSER_VERSION
                    internal_ms = full_msg.get("internalDate")
                    if internal_ms:
                        message.internal_ts = datetime.fromtimestamp(int(internal_ms) / 1000, tz=timezone.utc)
                    if apply and index % 25 == 0:
                        db.commit()
                        print(f"rebuilt {index}/{len(messages)} candidate_segments={report['candidate_segments']}", flush=True)
                    continue
                miss = assess_parse_miss(
                    subject=subject,
                    sender=sender,
                    body=body_for_filter,
                )
                if miss.score >= 6:
                    report["review_candidates"] += 1
                    message.status = MessageStatus.REVIEW_REQUIRED
                message.parse_error = miss.reason
                message.parse_evidence = miss.as_dict()

            message.parse_version = PARSER_VERSION
            internal_ms = full_msg.get("internalDate")
            if internal_ms:
                message.internal_ts = datetime.fromtimestamp(int(internal_ms) / 1000, tz=timezone.utc)

            if apply and index % 25 == 0:
                db.commit()
                print(f"rebuilt {index}/{len(messages)} candidate_segments={report['candidate_segments']}", flush=True)

        if apply:
            enriched = enrich_user_segments(db, user.id, include_weather=True, segment_ids=touched_segment_ids)
            report["enriched_segments"] = enriched
            report["after_trips"] = db.query(Trip).filter(Trip.user_id == user.id).count()
            report["after_segments"] = db.query(Segment).join(Trip).filter(Trip.user_id == user.id).count()
            db.commit()

        return report
    finally:
        db.close()
        locks.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--user-email", required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--progress-every", type=int, default=10)
    args = parser.parse_args()

    apply = bool(args.apply)
    report = rebuild(args.user_email, apply=apply, limit=args.limit, progress_every=max(1, args.progress_every))
    print(json.dumps(report, indent=2, default=_json_default))


if __name__ == "__main__":
    main()
