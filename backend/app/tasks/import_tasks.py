"""Celery task: run_gmail_import — scans Gmail and persists flight data."""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timezone
from hashlib import sha256

from app.celery_app import celery_app
from app.db import SessionLocal
from app.models import Account, Message, MessageStatus, SyncJob, User

logger = logging.getLogger(__name__)
PROGRESS_COMMIT_EVERY = 25
MAX_STALE_REPARSE_PER_SYNC = int(os.getenv("TROTTER_STALE_REPARSE_MAX_PER_SYNC", "250"))

# ── Terminal helpers ───────────────────────────────────────────────────────────
ORANGE = "\033[38;5;208m"
GREEN  = "\033[92m"
RED    = "\033[91m"
DIM    = "\033[90m"
BOLD   = "\033[1m"
RESET  = "\033[0m"
CYAN   = "\033[96m"

def _bar(current: int, total: int, width: int = 30) -> str:
    """Return a coloured ASCII progress bar."""
    if total <= 0:
        filled = min(width, current % (width + 1))
        bar = "█" * filled + "░" * (width - filled)
        return f"[{ORANGE}{bar}{RESET}] scanning…"
    filled = int(width * current / total)
    bar = "█" * filled + "░" * (width - filled)
    pct = int(100 * current / total)
    return f"[{ORANGE}{bar}{RESET}] {pct:3d}%"

def _print_progress(scanned: int, total: int, parsed: int, flights: int, skipped: int = 0) -> None:
    bar = _bar(scanned, total)
    line = (
        f"\r{BOLD}Sync{RESET}  {bar}  "
        f"{CYAN}{scanned:,}{RESET} emails  "
        f"{DIM}{skipped} skipped  {RESET}"
        f"{GREEN}✈ {flights} flight{'s' if flights != 1 else ''}{RESET}  "
        f"{DIM}{parsed} parsed{RESET}   "
    )
    sys.stdout.write(line)
    sys.stdout.flush()


@celery_app.task(name="gmail.import")
def run_gmail_import(job_id: str, user_id: int) -> dict:
    """Fetch and parse all flight-related Gmail messages for a user."""
    # Lazy imports so the module loads without the optional heavy packages installed
    from app.services.builder import build_segments_and_trips, rebuild_user_trips
    from app.services.enrichment import enrich_user_segments
    from app.services.gmail import (
        build_gmail_service,
        extract_attachments,
        extract_headers,
        extract_message_body,
        get_message,
    )
    from app.services.flight_query_v4 import (
        build_discovery_plan,
        get_or_create_discovery_state,
        get_learned_sender_domains,
        iter_discovery_messages,
        mark_discovery_plan_success,
        record_flight_discovery_signals,
    )
    from app.services.parser import PARSER_VERSION, parse_email
    from app.services.parse_audit import assess_parse_miss

    from app.services.flight_query_v2 import looks_like_flight_email

    db = SessionLocal()
    total_estimate = 0
    try:
        job = db.query(SyncJob).filter(SyncJob.id == job_id).first()
        if not job:
            logger.error("SyncJob %s not found", job_id)
            return {"error": "job_not_found"}

        job.state = "running"
        job.started_at = datetime.now(timezone.utc)
        job.updated_at = job.started_at
        db.commit()

        def flush_progress(force: bool = False) -> None:
            if force or job.scanned_count % PROGRESS_COMMIT_EVERY == 0:
                job.updated_at = datetime.now(timezone.utc)
                db.commit()

        account = (
            db.query(Account)
            .filter(Account.user_id == user_id, Account.provider == "google")
            .first()
        )
        if not account:
            job.state = "failed"
            job.error_message = "No Google account linked"
            db.commit()
            return {"error": "no_google_account"}

        user = db.query(User).filter(User.id == user_id).first()
        user_name = (user.name or user.email) if user else ""
        aliases: list[str] = []

        service = build_gmail_service(account.refresh_token_encrypted)
        discovery_state = get_or_create_discovery_state(db, user_id)
        discovery_started_at = datetime.now(timezone.utc)
        learned_sender_domains = get_learned_sender_domains(db, user_id)
        discovery_plan = build_discovery_plan(
            discovery_state,
            now=discovery_started_at,
            learned_sender_domains=learned_sender_domains,
        )



        print(f"\n{BOLD}{'─'*60}{RESET}")
        print(f"{BOLD}  ✈  Trotter Gmail Sync  —  Job {job_id[:8]}…{RESET}")
        print(f"{BOLD}{'─'*60}{RESET}")

        # Query page tokens are scoped to a single Gmail search expression. The
        # v4 discovery plan fans out across ordered tiers, so it dedupes by
        # message ID and relies on stored Message rows for idempotency.
        job.page_token = None
        db.commit()

        processed_msg_ids: set[str] = set()

        for candidate in iter_discovery_messages(service, discovery_plan):
            msg_stub = candidate.msg
            msg_id: str = msg_stub["id"]
            processed_msg_ids.add(msg_id)

            job.scanned_count += 1

            existing_msg = (
                db.query(Message)
                .filter(Message.user_id == user_id, Message.provider_msg_id == msg_id)
                .first()
            )
            skipped_count = job.scanned_count - job.parsed_count
            existing_parse_version = (getattr(existing_msg, "parse_version", 0) or 0) if existing_msg else 0
            if (
                existing_msg
                and existing_msg.status != MessageStatus.PENDING
                and existing_parse_version >= PARSER_VERSION
            ):
                flush_progress()
                _print_progress(job.scanned_count, total_estimate, job.parsed_count, job.segment_count, skipped_count)
                continue

            try:
                full_msg = get_message(service, msg_id)
            except Exception as exc:
                logger.warning("Failed to fetch message %s: %s", msg_id, exc)
                flush_progress()
                _print_progress(job.scanned_count, total_estimate, job.parsed_count, job.segment_count, skipped_count)
                continue

            headers = extract_headers(full_msg)
            plain_text, html = extract_message_body(full_msg)
            attachments = extract_attachments(full_msg)
            subject = headers.get("subject", "")
            from_email = headers.get("from", "")
            body_for_filter = plain_text if plain_text.strip() else html
            flight_like_candidate = False

            if candidate.prefilter and looks_like_flight_email:
                # Many airlines send HTML-only emails with no plain text.
                # Fall back to raw HTML so the keyword filter still fires.
                flight_like_candidate = looks_like_flight_email(
                    subject=subject,
                    sender=from_email,
                    body=body_for_filter,
                )
                if not flight_like_candidate:
                    skipped_count = job.scanned_count - job.parsed_count
                    flush_progress()
                    _print_progress(job.scanned_count, total_estimate, job.parsed_count, job.segment_count, skipped_count)
                    continue
            elif looks_like_flight_email:
                flight_like_candidate = looks_like_flight_email(
                    subject=subject,
                    sender=from_email,
                    body=body_for_filter,
                )

            parse_result = parse_email(
                html=html,
                plain_text=plain_text,
                attachments=attachments,
                user_name=user_name,
                aliases=aliases,
                received_at=headers.get("date"),
                subject=headers.get("subject"),
                from_email=headers.get("from"),
            )

            if not parse_result.flights:
                mutated = False
                parse_miss = assess_parse_miss(
                    subject=subject,
                    sender=from_email,
                    body=body_for_filter,
                )
                if existing_msg and existing_msg.status != MessageStatus.PENDING:
                    existing_msg.parse_version = PARSER_VERSION
                    existing_msg.parse_error = parse_miss.reason
                    existing_msg.parse_evidence = parse_miss.as_dict()
                    mutated = True
                elif flight_like_candidate:
                    from_domain = from_email.split("@")[-1].rstrip(">").strip() if "@" in from_email else ""
                    from_domain_hash = sha256(from_domain.encode()).hexdigest()[:64] if from_domain else None
                    snippet = full_msg.get("snippet", "")
                    snippet_hash = sha256(snippet.encode()).hexdigest()[:64] if snippet else None
                    existing_msg = Message(
                        user_id=user_id,
                        provider_msg_id=msg_id,
                        from_email=from_email[:320] or None,
                        from_domain_hash=from_domain_hash,
                        subject=subject,
                        snippet_sha256=snippet_hash,
                        status=MessageStatus.REVIEW_REQUIRED,
                        parse_version=PARSER_VERSION,
                        parse_error=parse_miss.reason,
                        parse_evidence=parse_miss.as_dict(),
                    )
                    db.add(existing_msg)
                    mutated = True
                if mutated:
                    job.updated_at = datetime.now(timezone.utc)
                    db.commit()
                    flush_progress(force=True)
                skipped_count = job.scanned_count - job.parsed_count
                flush_progress()
                _print_progress(job.scanned_count, total_estimate, job.parsed_count, job.segment_count, skipped_count)
                continue

            from_domain = from_email.split("@")[-1].rstrip(">").strip() if "@" in from_email else ""
            from_domain_hash = sha256(from_domain.encode()).hexdigest()[:64] if from_domain else None
            snippet = full_msg.get("snippet", "")
            snippet_hash = sha256(snippet.encode()).hexdigest()[:64] if snippet else None

            # Always import flights from personal Gmail — identity check is advisory only.
            # Mark as ACCEPTED so this email is not re-processed on future syncs.
            effective_status = MessageStatus.ACCEPTED

            if not existing_msg:
                existing_msg = Message(
                    user_id=user_id,
                    provider_msg_id=msg_id,
                    from_email=from_email[:320] or None,
                    from_domain_hash=from_domain_hash,
                    subject=headers.get("subject"),
                    snippet_sha256=snippet_hash,
                    status=effective_status,
                )
                db.add(existing_msg)
                db.flush()
            else:
                existing_msg.status = effective_status
            existing_msg.parse_version = PARSER_VERSION
            existing_msg.parse_error = None
            existing_msg.parse_evidence = None

            job.parsed_count += 1
            record_flight_discovery_signals(db, user_id, headers)

            new_segs = build_segments_and_trips(db, user_id, parse_result.flights)
            job.segment_count += new_segs
            subject = subject[:60]
            sys.stdout.write("\r" + " " * 120 + "\r")
            print(
                f"  {GREEN}✈  +{new_segs} flight(s){RESET}  "
                f"{DIM}{from_email[:40]}  |  {subject}{RESET}"
            )

            job.updated_at = datetime.now(timezone.utc)
            db.commit()

            skipped_count = job.scanned_count - job.parsed_count
            _print_progress(job.scanned_count, total_estimate, job.parsed_count, job.segment_count, skipped_count)

        stale_messages = (
            db.query(Message)
            .filter(
                Message.user_id == user_id,
                Message.status != MessageStatus.PENDING,
                Message.parse_version < PARSER_VERSION,
            )
            .order_by(Message.created_at.desc(), Message.id.desc())
            .limit(MAX_STALE_REPARSE_PER_SYNC)
            .all()
        )
        for stale_msg in stale_messages:
            msg_id = stale_msg.provider_msg_id
            if msg_id in processed_msg_ids:
                continue
            processed_msg_ids.add(msg_id)
            job.scanned_count += 1

            try:
                full_msg = get_message(service, msg_id)
            except Exception as exc:
                logger.warning("Failed to refetch stale message %s: %s", msg_id, exc)
                flush_progress()
                continue

            headers = extract_headers(full_msg)
            plain_text, html = extract_message_body(full_msg)
            attachments = extract_attachments(full_msg)
            body_for_filter = plain_text if plain_text.strip() else html
            parse_result = parse_email(
                html=html,
                plain_text=plain_text,
                attachments=attachments,
                user_name=user_name,
                aliases=aliases,
                received_at=headers.get("date"),
                subject=headers.get("subject"),
                from_email=headers.get("from"),
            )

            if parse_result.flights:
                job.parsed_count += 1
                record_flight_discovery_signals(db, user_id, headers)
                new_segs = build_segments_and_trips(db, user_id, parse_result.flights)
                job.segment_count += new_segs
                stale_msg.status = MessageStatus.ACCEPTED
                stale_msg.parse_error = None
                stale_msg.parse_evidence = None
                subject = (headers.get("subject") or stale_msg.subject or "")[:60]
                sys.stdout.write("\r" + " " * 120 + "\r")
                print(
                    f"  {GREEN}REPARSE  +{new_segs} flight(s){RESET}  "
                    f"{DIM}{(headers.get('from') or stale_msg.from_email or '')[:40]}  |  {subject}{RESET}"
                )
            else:
                parse_miss = assess_parse_miss(
                    subject=headers.get("subject") or stale_msg.subject or "",
                    sender=headers.get("from") or stale_msg.from_email or "",
                    body=body_for_filter,
                )
                stale_msg.parse_error = parse_miss.reason
                stale_msg.parse_evidence = parse_miss.as_dict()

            stale_msg.parse_version = PARSER_VERSION
            job.updated_at = datetime.now(timezone.utc)
            db.commit()
            skipped_count = job.scanned_count - job.parsed_count
            _print_progress(job.scanned_count, total_estimate, job.parsed_count, job.segment_count, skipped_count)

        sys.stdout.write("\n")
        mark_discovery_plan_success(
            discovery_state,
            discovery_plan,
            scan_started_at=discovery_started_at,
        )
        enriched_segments = enrich_user_segments(db, user_id, include_weather=True)
        if enriched_segments:
            rebuild_user_trips(db, user_id)
        job.state = "completed"
        job.updated_at = datetime.now(timezone.utc)
        db.commit()

        print(f"\n{BOLD}{'─'*60}{RESET}")
        print(f"  {GREEN}✔  Sync complete!{RESET}")
        print(f"  Scanned  : {CYAN}{job.scanned_count:,}{RESET} emails")
        print(f"  Parsed   : {CYAN}{job.parsed_count:,}{RESET} flight emails")
        print(f"  Flights  : {GREEN}{job.segment_count:,}{RESET} segments saved")
        print(f"  Enriched : {CYAN}{enriched_segments:,}{RESET} segments")
        print(f"{BOLD}{'─'*60}{RESET}\n")

        return {
            "job_id": job_id,
            "state": "completed",
            "scanned_count": job.scanned_count,
            "parsed_count": job.parsed_count,
            "segment_count": job.segment_count,
            "enriched_count": enriched_segments,
        }

    except Exception as exc:
        sys.stdout.write("\n")
        logger.exception("Gmail import failed for job %s: %s", job_id, exc)
        print(f"\n{RED}✘  Sync failed: {exc}{RESET}\n")
        try:
            job = db.query(SyncJob).filter(SyncJob.id == job_id).first()
            if job:
                job.state = "failed"
                job.error_message = str(exc)[:500]
                job.updated_at = datetime.now(timezone.utc)
                db.commit()
        except Exception:
            pass
    finally:
        db.close()
