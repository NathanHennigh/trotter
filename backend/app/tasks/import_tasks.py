"""Celery task: run_gmail_import — scans Gmail and persists flight data."""

from __future__ import annotations

import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from hashlib import sha256

from sqlalchemy.exc import IntegrityError

from app.celery_app import celery_app
from app.db import SessionLocal
from app.models import Account, Message, MessageStatus, Segment, SyncJob, Trip, User

logger = logging.getLogger(__name__)
PROGRESS_COMMIT_EVERY = 25
MAX_STALE_REPARSE_PER_SYNC = int(os.getenv("TROTTER_STALE_REPARSE_MAX_PER_SYNC", "250"))
DEFAULT_TARGETED_REPARSE_MESSAGE_IDS = frozenset(
    {
        "1594c8cc524dd7d7",  # Emirates NT24IF
        "1602c26a9f15a000",  # Emirates EG24Z6
        "16838e9f378cd13f",  # Delta GVPIAT receipt
        "17dca33c908674ac",  # Southwest 3WVTUA sparse/context email
        "176e6a1ed4f90665",  # Nairobi/United forwarded alias cluster
    }
)
HEAVY_DISCOVERY_TIERS = {
    "incremental_precise",
    "initial_broad_recent",
    "exhaustive_backfill",
    "stale_reparse",
}
REPAIR_REVIEW_ERRORS = {
    "strong_flight_evidence_but_no_segments",
    "partial_flight_evidence_but_no_segments",
    "weak_flight_evidence_but_candidate_query_matched",
}


def _env_int(name: str, default: int | None = None) -> int | None:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        parsed = int(value)
    except ValueError:
        return default
    return parsed if parsed > 0 else None


def _env_message_ids(name: str) -> set[str]:
    value = os.getenv(name, "")
    return {part.strip() for part in value.replace(";", ",").split(",") if part.strip()}

# ── Terminal helpers ───────────────────────────────────────────────────────────
ORANGE = "\033[38;5;208m"
GREEN  = "\033[92m"
RED    = "\033[91m"
DIM    = "\033[90m"
BOLD   = "\033[1m"
RESET  = "\033[0m"
CYAN   = "\033[96m"
_ACTIVE_PROGRESS_PHASE: str | None = None

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

def _print_progress(scanned: int, total: int, parsed: int, flights: int, skipped: int = 0, phase: str | None = None) -> None:
    bar = _bar(scanned, total)
    active_phase = phase if phase is not None else _ACTIVE_PROGRESS_PHASE
    label = f"Sync/{active_phase}" if active_phase else "Sync"
    line = (
        f"\r{BOLD}{label}{RESET}  {bar}  "
        f"{CYAN}{scanned:,}{RESET} emails  "
        f"{DIM}{skipped} skipped  {RESET}"
        f"{GREEN}✈ {flights} flight{'s' if flights != 1 else ''}{RESET}  "
        f"{DIM}{parsed} parsed{RESET}   "
    )
    sys.stdout.write(line)
    sys.stdout.flush()


def _fast_metadata_looks_like_flight(*, subject: str, sender: str, snippet: str) -> bool:
    """Cheap first-pass gate before sender matches fetch full Gmail bodies."""
    text = f"{subject}\n{sender}\n{snippet}".lower()
    return any(
        term in text
        for term in (
            "boarding pass",
            "boarding document",
            "check in for your flight",
            "check-in for your flight",
            "flight confirmation",
            "flight receipt",
            "flight itinerary",
            "flight update",
            "flight change",
            "your flight",
            "upcoming flight",
            "record locator",
            "e-ticket",
            "eticket",
            "ticket number",
            "schedule change",
            "gate change",
            "departure gate",
            "your trip",
            "trip itinerary",
            "travel itinerary",
            "itinerary",
        )
    )


def _looks_like_cancellation_notice(subject: str, body: str) -> bool:
    subject_text = (subject or "").lower()
    body_text = (body or "").lower()
    travel_subject = any(term in subject_text for term in ("flight", "trip", "itinerary", "booking", "reservation"))
    if travel_subject and any(term in subject_text for term in ("cancelled", "canceled", "cancellation")):
        return True
    cancellation_phrases = (
        "has been cancelled",
        "has been canceled",
        "was cancelled",
        "was canceled",
        "is cancelled",
        "is canceled",
        "your flight cancellation",
        "your trip cancellation",
        "your booking cancellation",
        "your reservation cancellation",
    )
    return any(phrase in body_text for phrase in cancellation_phrases)


def _looks_like_change_notice(subject: str, body: str) -> bool:
    text = f"{subject}\n{body}".lower()
    if not any(term in text for term in ("change", "changed", "schedule", "updated", "delay", "delayed")):
        return False
    return any(term in text for term in ("flight", "trip", "itinerary", "booking", "reservation"))


def _looks_like_ancillary_flight_notice(subject: str, body: str) -> bool:
    text = f"{subject}\n{body}".lower()
    return any(
        term in text
        for term in (
            "check in",
            "check-in",
            "boarding pass",
            "boarding documents",
            "mobile boarding",
            "upcoming trip",
            "flight reminder",
            "trip reminder",
            "flight receipt",
            "receipt for confirmation",
            "gate assigned",
        )
    )


def _existing_segments_for_pnr(db, user_id: int, pnr: str) -> int:
    if not pnr:
        return 0
    return (
        db.query(Segment)
        .join(Trip, Segment.trip_id == Trip.id)
        .filter(Trip.user_id == user_id, Segment.pnr == pnr)
        .count()
    )


def _parse_received_at(value: str | None):
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        return None
    if parsed.tzinfo is None:
        return parsed
    return parsed.astimezone(timezone.utc).replace(tzinfo=None)


def _get_or_create_message(db, user_id: int, provider_msg_id: str, **defaults) -> Message:
    existing = (
        db.query(Message)
        .filter(Message.user_id == user_id, Message.provider_msg_id == provider_msg_id)
        .first()
    )
    if existing:
        return existing

    msg = Message(user_id=user_id, provider_msg_id=provider_msg_id, **defaults)
    try:
        with db.begin_nested():
            db.add(msg)
            db.flush()
        return msg
    except IntegrityError:
        existing = (
            db.query(Message)
            .filter(Message.user_id == user_id, Message.provider_msg_id == provider_msg_id)
            .first()
        )
        if existing:
            return existing
        raise


def _ordered_tier_names(discovery_plan: list) -> list[str]:
    seen: set[str] = set()
    tiers: list[str] = []
    for item in discovery_plan:
        if item.tier not in seen:
            seen.add(item.tier)
            tiers.append(item.tier)
    return tiers


def _tier_phase_labels(discovery_plan: list) -> dict[str, str]:
    tiers = _ordered_tier_names(discovery_plan)
    total = len(tiers)
    return {tier: f"{index}/{total} {tier}" for index, tier in enumerate(tiers, start=1)}


def _print_phase(label: str, detail: str | None = None) -> None:
    sys.stdout.write("\r" + " " * 120 + "\r")
    suffix = f"  {DIM}{detail}{RESET}" if detail else ""
    print(f"{BOLD}Phase {label}{RESET}{suffix}")


def _message_skip_reason(existing_msg: Message | None, parser_version: int) -> str | None:
    """Return why an existing message is resolved, or None when it should parse."""
    if not existing_msg:
        return None
    if existing_msg.status == MessageStatus.PENDING:
        return None
    if (existing_msg.parse_version or 0) < parser_version:
        return None

    evidence = existing_msg.parse_evidence or {}
    if isinstance(evidence, dict) and evidence.get("resolved"):
        return str(evidence.get("reason") or "resolved")

    if existing_msg.status == MessageStatus.IGNORED:
        return "ignored"
    if existing_msg.status == MessageStatus.REVIEW_REQUIRED:
        return None
    if existing_msg.parse_error in {
        "strong_flight_evidence_but_no_segments",
        "partial_flight_evidence_but_no_segments",
        "weak_flight_evidence_but_candidate_query_matched",
    }:
        return None
    if existing_msg.status == MessageStatus.ACCEPTED and existing_msg.parse_error in {
        "cancellation_notice",
        "ancillary_existing_pnr",
    }:
        return existing_msg.parse_error
    return None


def _targeted_reparse_message_ids() -> set[str]:
    return set(DEFAULT_TARGETED_REPARSE_MESSAGE_IDS) | _env_message_ids("TROTTER_REPARSE_MESSAGE_IDS")


def _should_skip_expensive_parse(*, tier: str, prefilter: bool, evidence, force_parse: bool = False) -> bool:
    if force_parse:
        return False
    verdict = getattr(evidence, "verdict", "")
    if tier in HEAVY_DISCOVERY_TIERS and verdict in {"parse", "review"}:
        return not _heavy_tier_has_flight_anchor(evidence)
    if verdict != "skip":
        return False
    signals = set(getattr(evidence, "signals", ()) or ())
    if tier not in HEAVY_DISCOVERY_TIERS and _has_transactional_flight_anchor(signals):
        return False
    if tier in HEAVY_DISCOVERY_TIERS:
        return True
    if prefilter and {"newsletter_sender", "promo_noise", "non_flight_travel_noise"} & signals:
        return True
    return False


def _has_transactional_flight_anchor(signals: set[str]) -> bool:
    has_booking = "booking_identifier" in signals
    has_route = "route_airport_pair" in signals
    has_flight_number = "flight_number" in signals
    has_date = "date_or_time" in signals
    has_boarding = "boarding_or_checkin" in signals
    has_ticket = "ticket_language" in signals
    return (
        has_booking
        and (has_route or has_flight_number or has_boarding or has_ticket)
        and (has_date or has_boarding or has_ticket or has_flight_number)
    ) or (
        has_flight_number
        and has_boarding
        and (has_date or has_ticket)
    ) or (
        has_route
        and has_boarding
        and has_date
    )


def _heavy_tier_has_flight_anchor(evidence) -> bool:
    signals = set(getattr(evidence, "signals", ()) or ())
    has_booking = "booking_identifier" in signals
    has_route = "route_airport_pair" in signals
    has_flight_number = "flight_number" in signals
    has_date = "date_or_time" in signals
    has_boarding = "boarding_or_checkin" in signals
    has_ticket = "ticket_language" in signals
    has_airline_sender = "airline_sender" in signals
    has_flight_language = "flight_language" in signals
    noisy = bool({"newsletter_sender", "promo_noise", "noisy_sender", "non_flight_travel_noise"} & signals)

    if noisy:
        return has_booking and (has_boarding or has_ticket) and (has_route or has_flight_number or has_airline_sender)

    return (
        (has_booking and (has_route or has_flight_number or has_boarding or has_ticket) and (has_flight_language or has_boarding or has_ticket or has_airline_sender))
        or (has_route and has_flight_number and has_date and (has_flight_language or has_airline_sender))
        or (has_boarding and has_date and (has_route or has_flight_number or has_airline_sender))
    )


def _select_stale_reparse_messages(
    db,
    *,
    user_id: int,
    parser_version: int,
    limit: int,
    targeted_ids: set[str],
) -> list[Message]:
    if limit <= 0:
        return []

    selected: list[Message] = []
    seen: set[str] = set()
    base_filters = (
        Message.user_id == user_id,
        Message.status.in_([MessageStatus.ACCEPTED, MessageStatus.REVIEW_REQUIRED]),
        Message.parse_version < parser_version,
        Message.ignored.is_(False),
    )

    if targeted_ids:
        targeted = (
            db.query(Message)
            .filter(
                Message.user_id == user_id,
                Message.parse_version < parser_version,
                Message.provider_msg_id.in_(targeted_ids),
            )
            .order_by(Message.created_at.desc(), Message.id.desc())
            .all()
        )
        for row in targeted:
            selected.append(row)
            seen.add(row.provider_msg_id)
            if len(selected) >= limit:
                return selected

    remaining = limit - len(selected)
    if remaining <= 0:
        return selected

    query = db.query(Message).filter(*base_filters)
    if seen:
        query = query.filter(Message.provider_msg_id.notin_(seen))

    review_rows = (
        query.filter(
            Message.status == MessageStatus.REVIEW_REQUIRED,
            Message.parse_error.in_(REPAIR_REVIEW_ERRORS),
        )
        .order_by(Message.created_at.desc(), Message.id.desc())
        .limit(remaining)
        .all()
    )
    for row in review_rows:
        selected.append(row)
        seen.add(row.provider_msg_id)
        if len(selected) >= limit:
            return selected

    remaining = limit - len(selected)
    query = db.query(Message).filter(*base_filters)
    if seen:
        query = query.filter(Message.provider_msg_id.notin_(seen))
    selected.extend(
        query.order_by(Message.created_at.desc(), Message.id.desc())
        .limit(remaining)
        .all()
    )
    return selected


def _count_remaining_stale_reparse_messages(db, *, user_id: int, parser_version: int) -> int:
    return (
        db.query(Message)
        .filter(
            Message.user_id == user_id,
            Message.status.in_([MessageStatus.ACCEPTED, MessageStatus.REVIEW_REQUIRED]),
            Message.parse_version < parser_version,
            Message.ignored.is_(False),
        )
        .count()
    )


@celery_app.task(name="gmail.import")
def run_gmail_import(job_id: str, user_id: int, limit: int | None = None, mode: str | None = None) -> dict:
    """Fetch and parse all flight-related Gmail messages for a user."""
    global _ACTIVE_PROGRESS_PHASE
    _ACTIVE_PROGRESS_PHASE = None
    # Lazy imports so the module loads without the optional heavy packages installed
    from app.services.builder import build_segments_and_trips_detailed, cancel_segments_for_pnr, rebuild_user_trips
    from app.services.enrichment import enrich_user_segments
    from app.services.gmail import (
        batch_get_messages,
        batch_get_message_metadata,
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
    from app.services.parser import PARSER_VERSION, _extract_pnr, parse_email
    from app.services.parse_audit import assess_parse_miss
    from app.services.tui import GmailImportReporter

    from app.services.flight_query_v2 import looks_like_flight_email
    from app.services.flight_evidence import assess_flight_evidence

    db = SessionLocal()
    import_mode = (mode or "sync").lower()
    reparse_only = import_mode in {"reparse", "repair", "stale_reparse"}
    total_estimate = 0
    if limit == 0:
        sync_limit = None
    elif limit is not None:
        sync_limit = max(1, int(limit))
    else:
        sync_limit = _env_int("TROTTER_SYNC_MAX_MESSAGES")
    updated_segments = 0
    skipped_segments = 0
    canceled_segments = 0
    limit_reached = False
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
        fetch_batch_size = _env_int("TROTTER_GMAIL_BATCH_SIZE", 50) or 50
        parse_workers = _env_int("TROTTER_PARSE_WORKERS", 4) or 4

        service = build_gmail_service(account.refresh_token_encrypted)
        discovery_state = get_or_create_discovery_state(db, user_id)
        discovery_started_at = datetime.now(timezone.utc)
        learned_sender_domains = get_learned_sender_domains(db, user_id)
        discovery_plan = [] if reparse_only else build_discovery_plan(
            discovery_state,
            now=discovery_started_at,
            learned_sender_domains=learned_sender_domains,
        )
        reporter_tiers = _ordered_tier_names(discovery_plan)
        if reparse_only:
            reporter_tiers = ["stale_reparse"]
        elif "stale_reparse" not in reporter_tiers:
            reporter_tiers.append("stale_reparse")

        reporter = GmailImportReporter(
            job_id=job_id,
            parser_version=PARSER_VERSION,
            limit=sync_limit,
            batch_size=fetch_batch_size,
            workers=parse_workers,
            tiers=reporter_tiers,
        )
        reporter.start()

        # Query page tokens are scoped to a single Gmail search expression. The
        # v4 discovery plan fans out across ordered tiers, so it dedupes by
        # message ID and relies on stored Message rows for idempotency.
        job.page_token = None
        db.commit()

        processed_msg_ids: set[str] = set()
        phase_labels = _tier_phase_labels(discovery_plan)
        current_tier: str | None = None

        def parse_full_message(candidate, full_msg: dict) -> dict:
            msg_id = candidate.msg["id"]
            headers = extract_headers(full_msg)
            plain_text, html = extract_message_body(full_msg)
            attachments = extract_attachments(full_msg)
            subject = headers.get("subject", "")
            from_email = headers.get("from", "")
            body_for_filter = plain_text if plain_text.strip() else html
            flight_like_candidate = False
            evidence = assess_flight_evidence(
                subject=subject,
                sender=from_email,
                body=body_for_filter,
            )
            pnr = _extract_pnr(f"{subject}\n{body_for_filter}".upper())
            if _should_skip_expensive_parse(
                tier=candidate.tier,
                prefilter=candidate.prefilter,
                evidence=evidence,
            ):
                return {
                    "candidate": candidate,
                    "msg_id": msg_id,
                    "full_msg": full_msg,
                    "headers": headers,
                    "subject": subject,
                    "from_email": from_email,
                    "body_for_filter": body_for_filter,
                    "evidence": evidence,
                    "flight_like_candidate": False,
                    "prefilter_skipped": False,
                    "evidence_skipped": True,
                    "parse_result": None,
                    "parse_seconds": None,
                    "pnr": pnr,
                }

            if looks_like_flight_email:
                flight_like_candidate = looks_like_flight_email(
                    subject=subject,
                    sender=from_email,
                    body=body_for_filter,
                )
                if candidate.prefilter and not flight_like_candidate:
                    return {
                        "candidate": candidate,
                        "msg_id": msg_id,
                        "full_msg": full_msg,
                        "headers": headers,
                        "subject": subject,
                        "from_email": from_email,
                        "body_for_filter": body_for_filter,
                        "evidence": evidence,
                        "flight_like_candidate": False,
                        "prefilter_skipped": True,
                        "evidence_skipped": False,
                        "parse_result": None,
                        "parse_seconds": None,
                        "pnr": None,
                    }

            parse_started = time.perf_counter()
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
            parse_seconds = time.perf_counter() - parse_started
            return {
                "candidate": candidate,
                "msg_id": msg_id,
                "full_msg": full_msg,
                "headers": headers,
                "subject": subject,
                "from_email": from_email,
                "body_for_filter": body_for_filter,
                "evidence": evidence,
                "flight_like_candidate": flight_like_candidate,
                "prefilter_skipped": False,
                "evidence_skipped": False,
                "parse_result": parse_result,
                "parse_seconds": parse_seconds,
                "pnr": pnr,
            }

        def mark_resolved_ignored(
            *,
            existing_msg: Message | None,
            full_msg: dict,
            msg_id: str,
            from_email: str,
            subject: str,
            parse_miss,
            tier: str,
        ) -> Message:
            from_domain = from_email.split("@")[-1].rstrip(">").strip() if "@" in from_email else ""
            from_domain_hash = sha256(from_domain.encode()).hexdigest()[:64] if from_domain else None
            snippet = full_msg.get("snippet", "")
            snippet_hash = sha256(snippet.encode()).hexdigest()[:64] if snippet else None
            if not existing_msg:
                existing_msg = _get_or_create_message(
                    db,
                    user_id,
                    msg_id,
                    internal_ts=datetime.fromtimestamp(int(full_msg.get("internalDate", 0)) / 1000, tz=timezone.utc),
                    from_email=from_email[:320] or None,
                    from_domain_hash=from_domain_hash,
                    subject=subject,
                    snippet_sha256=snippet_hash,
                    status=MessageStatus.ACCEPTED,
                )
            existing_msg.status = MessageStatus.ACCEPTED
            existing_msg.ignored = True
            existing_msg.parse_version = PARSER_VERSION
            existing_msg.parse_error = parse_miss.reason
            existing_msg.parse_evidence = {
                **parse_miss.as_dict(),
                "reason": parse_miss.reason,
                "resolved": True,
                "ignored_reason": parse_miss.reason,
                "tier": tier,
            }
            return existing_msg

        def mark_unresolved_review_required(
            *,
            existing_msg: Message | None,
            full_msg: dict,
            msg_id: str,
            from_email: str,
            subject: str,
            parse_miss,
            tier: str,
            evidence_gate: dict | None = None,
        ) -> Message:
            from_domain = from_email.split("@")[-1].rstrip(">").strip() if "@" in from_email else ""
            from_domain_hash = sha256(from_domain.encode()).hexdigest()[:64] if from_domain else None
            snippet = full_msg.get("snippet", "")
            snippet_hash = sha256(snippet.encode()).hexdigest()[:64] if snippet else None
            if not existing_msg:
                existing_msg = _get_or_create_message(
                    db,
                    user_id,
                    msg_id,
                    internal_ts=datetime.fromtimestamp(int(full_msg.get("internalDate", 0)) / 1000, tz=timezone.utc),
                    from_email=from_email[:320] or None,
                    from_domain_hash=from_domain_hash,
                    subject=subject,
                    snippet_sha256=snippet_hash,
                    status=MessageStatus.REVIEW_REQUIRED,
                )
            existing_msg.status = MessageStatus.REVIEW_REQUIRED
            existing_msg.ignored = False
            existing_msg.parse_version = PARSER_VERSION
            existing_msg.parse_error = parse_miss.reason
            existing_msg.parse_evidence = {
                **parse_miss.as_dict(),
                "resolved": False,
                "tier": tier,
                **({"evidence_gate": evidence_gate} if evidence_gate else {}),
            }
            return existing_msg

        def process_payload(payload: dict, existing_msg: Message | None) -> None:
            nonlocal canceled_segments, skipped_segments, updated_segments
            candidate = payload["candidate"]
            msg_id = payload["msg_id"]
            full_msg = payload["full_msg"]
            headers = payload["headers"]
            subject = payload["subject"]
            from_email = payload["from_email"]
            body_for_filter = payload["body_for_filter"]
            flight_like_candidate = payload["flight_like_candidate"]
            parse_result = payload["parse_result"]
            pnr = payload["pnr"]

            if payload.get("evidence_skipped"):
                parse_miss = assess_parse_miss(
                    subject=subject,
                    sender=from_email,
                    body=body_for_filter,
                )
                if parse_miss.should_review:
                    mark_unresolved_review_required(
                        existing_msg=existing_msg,
                        full_msg=full_msg,
                        msg_id=msg_id,
                        from_email=from_email,
                        subject=subject,
                        parse_miss=parse_miss,
                        tier=candidate.tier,
                        evidence_gate=payload["evidence"].as_dict() if payload.get("evidence") else None,
                    )
                    reporter.parser_miss(candidate.tier, parse_miss.reason)
                else:
                    mark_resolved_ignored(
                        existing_msg=existing_msg,
                        full_msg=full_msg,
                        msg_id=msg_id,
                        from_email=from_email,
                        subject=subject,
                        parse_miss=parse_miss,
                        tier=candidate.tier,
                    )
                    reporter.count(candidate.tier, "ignored_nonflight")
                reporter.count(candidate.tier, "gate_skip")
                job.updated_at = datetime.now(timezone.utc)
                db.commit()
                skipped_count = job.scanned_count - job.parsed_count
                flush_progress()
                _print_progress(job.scanned_count, total_estimate, job.parsed_count, job.segment_count, skipped_count)
                return

            if pnr and _looks_like_cancellation_notice(subject, body_for_filter):
                canceled_count = cancel_segments_for_pnr(db, user_id, pnr, received_at=_parse_received_at(headers.get("date")))
                canceled_segments += canceled_count
                from_domain = from_email.split("@")[-1].rstrip(">").strip() if "@" in from_email else ""
                from_domain_hash = sha256(from_domain.encode()).hexdigest()[:64] if from_domain else None
                snippet = full_msg.get("snippet", "")
                snippet_hash = sha256(snippet.encode()).hexdigest()[:64] if snippet else None
                if not existing_msg:
                    existing_msg = _get_or_create_message(
                        db,
                        user_id,
                        msg_id,
                        from_email=from_email[:320] or None,
                        from_domain_hash=from_domain_hash,
                        subject=subject,
                        snippet_sha256=snippet_hash,
                        status=MessageStatus.ACCEPTED,
                    )
                existing_msg.status = MessageStatus.ACCEPTED
                existing_msg.parse_version = PARSER_VERSION
                existing_msg.parse_error = "cancellation_notice"
                existing_msg.parse_evidence = {
                    "reason": "cancellation_notice",
                    "pnr": pnr,
                    "canceled_segments": canceled_count,
                    "resolved": True,
                    "tier": candidate.tier,
                }
                reporter.count(candidate.tier, "cancellation")
                job.updated_at = datetime.now(timezone.utc)
                db.commit()
                skipped_count = job.scanned_count - job.parsed_count
                flush_progress()
                _print_progress(job.scanned_count, total_estimate, job.parsed_count, job.segment_count, skipped_count)
                return

            if not parse_result.flights:
                mutated = False
                parse_miss = assess_parse_miss(
                    subject=subject,
                    sender=from_email,
                    body=body_for_filter,
                )
                existing_pnr_segments = _existing_segments_for_pnr(db, user_id, pnr) if pnr else 0
                if existing_pnr_segments and _looks_like_ancillary_flight_notice(subject, body_for_filter):
                    from_domain = from_email.split("@")[-1].rstrip(">").strip() if "@" in from_email else ""
                    from_domain_hash = sha256(from_domain.encode()).hexdigest()[:64] if from_domain else None
                    snippet = full_msg.get("snippet", "")
                    snippet_hash = sha256(snippet.encode()).hexdigest()[:64] if snippet else None
                    if not existing_msg:
                        existing_msg = _get_or_create_message(
                            db,
                            user_id,
                            msg_id,
                            internal_ts=datetime.fromtimestamp(int(full_msg.get("internalDate", 0)) / 1000, tz=timezone.utc),
                            from_email=from_email[:320] or None,
                            from_domain_hash=from_domain_hash,
                            subject=subject,
                            snippet_sha256=snippet_hash,
                            status=MessageStatus.ACCEPTED,
                        )
                    existing_msg.status = MessageStatus.ACCEPTED
                    existing_msg.parse_version = PARSER_VERSION
                    existing_msg.parse_error = "ancillary_existing_pnr"
                    existing_msg.parse_evidence = {
                        "reason": "ancillary_email_matches_existing_pnr",
                        "pnr": pnr,
                        "existing_segments": existing_pnr_segments,
                        "parse_miss": parse_miss.as_dict(),
                        "resolved": True,
                        "tier": candidate.tier,
                    }
                    reporter.count(candidate.tier, "ancillary")
                    job.updated_at = datetime.now(timezone.utc)
                    db.commit()
                    skipped_count = job.scanned_count - job.parsed_count
                    flush_progress()
                    _print_progress(job.scanned_count, total_estimate, job.parsed_count, job.segment_count, skipped_count)
                    return
                if not parse_miss.should_review:
                    mark_resolved_ignored(
                        existing_msg=existing_msg,
                        full_msg=full_msg,
                        msg_id=msg_id,
                        from_email=from_email,
                        subject=subject,
                        parse_miss=parse_miss,
                        tier=candidate.tier,
                    )
                    reporter.count(candidate.tier, "ignored_nonflight")
                    job.updated_at = datetime.now(timezone.utc)
                    db.commit()
                    skipped_count = job.scanned_count - job.parsed_count
                    flush_progress()
                    _print_progress(job.scanned_count, total_estimate, job.parsed_count, job.segment_count, skipped_count)
                    return
                if existing_msg and existing_msg.status != MessageStatus.PENDING:
                    existing_msg.parse_version = PARSER_VERSION
                    existing_msg.parse_error = parse_miss.reason
                    existing_msg.parse_evidence = {
                        **parse_miss.as_dict(),
                        "resolved": False,
                        "tier": candidate.tier,
                    }
                    mutated = True
                elif flight_like_candidate:
                    from_domain = from_email.split("@")[-1].rstrip(">").strip() if "@" in from_email else ""
                    from_domain_hash = sha256(from_domain.encode()).hexdigest()[:64] if from_domain else None
                    snippet = full_msg.get("snippet", "")
                    snippet_hash = sha256(snippet.encode()).hexdigest()[:64] if snippet else None
                    existing_msg = _get_or_create_message(
                        db,
                        user_id,
                        msg_id,
                        from_email=from_email[:320] or None,
                        from_domain_hash=from_domain_hash,
                        subject=subject,
                        snippet_sha256=snippet_hash,
                        status=MessageStatus.REVIEW_REQUIRED,
                        parse_version=PARSER_VERSION,
                        parse_error=parse_miss.reason,
                        parse_evidence={
                            **parse_miss.as_dict(),
                            "resolved": False,
                            "tier": candidate.tier,
                        },
                    )
                    existing_msg.status = MessageStatus.REVIEW_REQUIRED
                    existing_msg.parse_version = PARSER_VERSION
                    existing_msg.parse_error = parse_miss.reason
                    existing_msg.parse_evidence = {
                        **parse_miss.as_dict(),
                        "resolved": False,
                        "tier": candidate.tier,
                    }
                    mutated = True
                if mutated:
                    reporter.parser_miss(candidate.tier, parse_miss.reason)
                    job.updated_at = datetime.now(timezone.utc)
                    db.commit()
                    flush_progress(force=True)
                skipped_count = job.scanned_count - job.parsed_count
                flush_progress()
                _print_progress(job.scanned_count, total_estimate, job.parsed_count, job.segment_count, skipped_count)
                return

            from_domain = from_email.split("@")[-1].rstrip(">").strip() if "@" in from_email else ""
            from_domain_hash = sha256(from_domain.encode()).hexdigest()[:64] if from_domain else None
            snippet = full_msg.get("snippet", "")
            snippet_hash = sha256(snippet.encode()).hexdigest()[:64] if snippet else None

            if not existing_msg:
                existing_msg = _get_or_create_message(
                    db,
                    user_id,
                    msg_id,
                    from_email=from_email[:320] or None,
                    from_domain_hash=from_domain_hash,
                    subject=headers.get("subject"),
                    snippet_sha256=snippet_hash,
                    status=MessageStatus.ACCEPTED,
                )
            else:
                existing_msg.status = MessageStatus.ACCEPTED
            existing_msg.ignored = False
            existing_msg.parse_version = PARSER_VERSION
            existing_msg.parse_error = None
            existing_msg.parse_evidence = {
                "reason": "parsed_flights",
                "resolved": True,
                "flight_count": len(parse_result.flights),
                "source": parse_result.source,
                "tier": candidate.tier,
            }

            job.parsed_count += 1
            record_flight_discovery_signals(db, user_id, headers)

            build_result = build_segments_and_trips_detailed(db, user_id, parse_result.flights)
            new_segs = build_result.inserted
            updated_segments += build_result.updated
            skipped_segments += build_result.skipped
            job.segment_count += new_segs
            reporter.parsed_flight(
                candidate.tier,
                segments=new_segs,
                updated=build_result.updated,
                skipped=build_result.skipped,
                sender=from_email,
                subject=subject,
            )
            subject = subject[:60]
            sys.stdout.write("\r" + " " * 120 + "\r")
            print(
                f"  {GREEN}âœˆ  +{new_segs} flight(s){RESET}  "
                f"{DIM}tier={candidate.tier} parsed={len(parse_result.flights)} updated={build_result.updated} skipped={build_result.skipped}  "
                f"{from_email[:40]}  |  {subject}{RESET}"
            )

            job.updated_at = datetime.now(timezone.utc)
            db.commit()

            skipped_count = job.scanned_count - job.parsed_count
            _print_progress(job.scanned_count, total_estimate, job.parsed_count, job.segment_count, skipped_count)

        def process_candidate_batch(candidate_batch: list) -> None:
            nonlocal limit_reached
            if not candidate_batch:
                return

            msg_ids = [candidate.msg["id"] for candidate in candidate_batch]
            existing_messages = (
                db.query(Message)
                .filter(Message.user_id == user_id, Message.provider_msg_id.in_(msg_ids))
                .all()
            )
            existing_by_id = {message.provider_msg_id: message for message in existing_messages}
            fetch_candidates = []

            for candidate in candidate_batch:
                if sync_limit and job.scanned_count >= sync_limit:
                    limit_reached = True
                    print(f"\n{DIM}Sync limit reached at {sync_limit} messages; stopping this dev run.{RESET}")
                    break
                msg_id = candidate.msg["id"]
                processed_msg_ids.add(msg_id)
                job.scanned_count += 1
                reporter.count(candidate.tier, "candidate")

                existing_msg = existing_by_id.get(msg_id)
                skip_reason = _message_skip_reason(existing_msg, PARSER_VERSION)
                if skip_reason:
                    reporter.count(candidate.tier, "db_skip")
                    reporter.count(candidate.tier, f"db_skip_{skip_reason}")
                    skipped_count = job.scanned_count - job.parsed_count
                    flush_progress()
                    if job.scanned_count % PROGRESS_COMMIT_EVERY == 0:
                        reporter.progress(
                            scanned=job.scanned_count,
                            parsed=job.parsed_count,
                            flights=job.segment_count,
                            skipped=skipped_count,
                        )
                    continue
                fetch_candidates.append(candidate)

            if not fetch_candidates:
                return

            fetch_tiers = {candidate.msg["id"]: candidate.tier for candidate in fetch_candidates}
            metadata_gate_candidates = [
                candidate for candidate in fetch_candidates if candidate.tier == "fast_known_senders"
            ]
            if metadata_gate_candidates:
                metadata_messages, metadata_errors = batch_get_message_metadata(
                    service,
                    [candidate.msg["id"] for candidate in metadata_gate_candidates],
                )
                if metadata_errors:
                    for msg_id in metadata_errors:
                        reporter.count(fetch_tiers.get(msg_id), "metadata_fetch_error")
                for candidate in metadata_gate_candidates:
                    metadata = metadata_messages.get(candidate.msg["id"])
                    if not metadata:
                        continue
                    headers = extract_headers(metadata)
                    if _fast_metadata_looks_like_flight(
                        subject=headers.get("subject", ""),
                        sender=headers.get("from", ""),
                        snippet=metadata.get("snippet", ""),
                    ):
                        reporter.count(candidate.tier, "metadata_pass")
                    else:
                        reporter.count(candidate.tier, "metadata_skip")
            fetch_tiers = {candidate.msg["id"]: candidate.tier for candidate in fetch_candidates}

            full_messages, fetch_errors = batch_get_messages(
                service,
                [candidate.msg["id"] for candidate in fetch_candidates],
            )
            for msg_id, exc in fetch_errors.items():
                logger.warning("Failed to fetch message %s: %s", msg_id, exc)
            if fetch_errors:
                for msg_id in fetch_errors:
                    reporter.count(fetch_tiers.get(msg_id), "fetch_error")
                skipped_count = job.scanned_count - job.parsed_count
                flush_progress(force=True)
                reporter.progress(
                    scanned=job.scanned_count,
                    parsed=job.parsed_count,
                    flights=job.segment_count,
                    skipped=skipped_count,
                )

            parse_inputs = [
                (candidate, full_messages[candidate.msg["id"]])
                for candidate in fetch_candidates
                if candidate.msg["id"] in full_messages
            ]
            if not parse_inputs:
                return
            for candidate, _full_msg in parse_inputs:
                reporter.count(candidate.tier, "full_fetch")

            if parse_workers > 1 and len(parse_inputs) > 1:
                with ThreadPoolExecutor(max_workers=parse_workers) as executor:
                    payloads = list(executor.map(lambda args: parse_full_message(*args), parse_inputs))
            else:
                payloads = [parse_full_message(candidate, full_msg) for candidate, full_msg in parse_inputs]

            for payload in payloads:
                reporter.evidence(payload["candidate"].tier, payload["evidence"].verdict)
                if payload.get("evidence_skipped"):
                    process_payload(payload, existing_by_id.get(payload["msg_id"]))
                    continue
                if payload["parse_seconds"] is not None:
                    reporter.parser_timing(
                        payload["candidate"].tier,
                        seconds=payload["parse_seconds"],
                        sender=payload["from_email"],
                        subject=payload["subject"],
                    )
                if payload["prefilter_skipped"]:
                    reporter.count(payload["candidate"].tier, "prefilter_skip")
                    skipped_count = job.scanned_count - job.parsed_count
                    flush_progress()
                    if job.scanned_count % PROGRESS_COMMIT_EVERY == 0:
                        reporter.progress(
                            scanned=job.scanned_count,
                            parsed=job.parsed_count,
                            flights=job.segment_count,
                            skipped=skipped_count,
                        )
                    continue
                process_payload(payload, existing_by_id.get(payload["msg_id"]))

        candidate_batch: list = []
        for candidate in iter_discovery_messages(service, discovery_plan):
            if candidate.tier != current_tier:
                process_candidate_batch(candidate_batch)
                candidate_batch = []
                if limit_reached:
                    break
                current_tier = candidate.tier
                _ACTIVE_PROGRESS_PHASE = phase_labels.get(candidate.tier, candidate.tier)
                if candidate.tier.startswith("background_"):
                    reporter.initial_scan_complete()
                reporter.tier_started(
                    candidate.tier,
                    "prefiltered Gmail search" if candidate.prefilter else "broad backscan window",
                )
            candidate_batch.append(candidate)
            if len(candidate_batch) >= fetch_batch_size:
                process_candidate_batch(candidate_batch)
                candidate_batch = []
                if limit_reached:
                    break
        process_candidate_batch(candidate_batch)

        for candidate in ():
            if candidate.tier != current_tier:
                current_tier = candidate.tier
                _ACTIVE_PROGRESS_PHASE = phase_labels.get(candidate.tier, candidate.tier)
                _print_phase(
                    _ACTIVE_PROGRESS_PHASE,
                    "prefiltered Gmail search" if candidate.prefilter else "exhaustive backfill window",
                )
            if sync_limit and job.scanned_count >= sync_limit:
                limit_reached = True
                print(f"\n{DIM}Sync limit reached at {sync_limit} messages; stopping this dev run.{RESET}")
                break
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
            pnr = _extract_pnr(f"{subject}\n{body_for_filter}".upper())
            if pnr and _looks_like_cancellation_notice(subject, body_for_filter):
                canceled_count = cancel_segments_for_pnr(db, user_id, pnr, received_at=_parse_received_at(headers.get("date")))
                canceled_segments += canceled_count
                from_domain = from_email.split("@")[-1].rstrip(">").strip() if "@" in from_email else ""
                from_domain_hash = sha256(from_domain.encode()).hexdigest()[:64] if from_domain else None
                snippet = full_msg.get("snippet", "")
                snippet_hash = sha256(snippet.encode()).hexdigest()[:64] if snippet else None
                if not existing_msg:
                    existing_msg = _get_or_create_message(
                        db,
                        user_id,
                        msg_id,
                        from_email=from_email[:320] or None,
                        from_domain_hash=from_domain_hash,
                        subject=subject,
                        snippet_sha256=snippet_hash,
                        status=MessageStatus.ACCEPTED,
                    )
                existing_msg.status = MessageStatus.ACCEPTED
                existing_msg.parse_version = PARSER_VERSION
                existing_msg.parse_error = "cancellation_notice"
                existing_msg.parse_evidence = {
                    "reason": "cancellation_notice",
                    "pnr": pnr,
                    "canceled_segments": canceled_count,
                }
                job.updated_at = datetime.now(timezone.utc)
                db.commit()
                skipped_count = job.scanned_count - job.parsed_count
                flush_progress()
                _print_progress(job.scanned_count, total_estimate, job.parsed_count, job.segment_count, skipped_count)
                continue

            if not parse_result.flights:
                mutated = False
                parse_miss = assess_parse_miss(
                    subject=subject,
                    sender=from_email,
                    body=body_for_filter,
                )
                existing_pnr_segments = _existing_segments_for_pnr(db, user_id, pnr) if pnr else 0
                if existing_pnr_segments and _looks_like_ancillary_flight_notice(subject, body_for_filter):
                    from_domain = from_email.split("@")[-1].rstrip(">").strip() if "@" in from_email else ""
                    from_domain_hash = sha256(from_domain.encode()).hexdigest()[:64] if from_domain else None
                    snippet = full_msg.get("snippet", "")
                    snippet_hash = sha256(snippet.encode()).hexdigest()[:64] if snippet else None
                    if not existing_msg:
                        existing_msg = _get_or_create_message(
                            db,
                            user_id,
                            msg_id,
                            internal_ts=datetime.fromtimestamp(int(full_msg.get("internalDate", 0)) / 1000, tz=timezone.utc),
                            from_email=from_email[:320] or None,
                            from_domain_hash=from_domain_hash,
                            subject=subject,
                            snippet_sha256=snippet_hash,
                            status=MessageStatus.ACCEPTED,
                        )
                    existing_msg.status = MessageStatus.ACCEPTED
                    existing_msg.parse_version = PARSER_VERSION
                    existing_msg.parse_error = "ancillary_existing_pnr"
                    existing_msg.parse_evidence = {
                        "reason": "ancillary_email_matches_existing_pnr",
                        "pnr": pnr,
                        "existing_segments": existing_pnr_segments,
                        "parse_miss": parse_miss.as_dict(),
                    }
                    job.updated_at = datetime.now(timezone.utc)
                    db.commit()
                    skipped_count = job.scanned_count - job.parsed_count
                    flush_progress()
                    _print_progress(job.scanned_count, total_estimate, job.parsed_count, job.segment_count, skipped_count)
                    continue
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
                    existing_msg = _get_or_create_message(
                        db,
                        user_id,
                        msg_id,
                        from_email=from_email[:320] or None,
                        from_domain_hash=from_domain_hash,
                        subject=subject,
                        snippet_sha256=snippet_hash,
                        status=MessageStatus.REVIEW_REQUIRED,
                        parse_version=PARSER_VERSION,
                        parse_error=parse_miss.reason,
                        parse_evidence=parse_miss.as_dict(),
                    )
                    existing_msg.status = MessageStatus.REVIEW_REQUIRED
                    existing_msg.parse_version = PARSER_VERSION
                    existing_msg.parse_error = parse_miss.reason
                    existing_msg.parse_evidence = parse_miss.as_dict()
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
                existing_msg = _get_or_create_message(
                    db,
                    user_id,
                    msg_id,
                    from_email=from_email[:320] or None,
                    from_domain_hash=from_domain_hash,
                    subject=headers.get("subject"),
                    snippet_sha256=snippet_hash,
                    status=effective_status,
                )
            else:
                existing_msg.status = effective_status
            existing_msg.parse_version = PARSER_VERSION
            existing_msg.parse_error = None
            existing_msg.parse_evidence = None

            job.parsed_count += 1
            record_flight_discovery_signals(db, user_id, headers)

            build_result = build_segments_and_trips_detailed(db, user_id, parse_result.flights)
            new_segs = build_result.inserted
            updated_segments += build_result.updated
            skipped_segments += build_result.skipped
            job.segment_count += new_segs
            subject = subject[:60]
            sys.stdout.write("\r" + " " * 120 + "\r")
            print(
                f"  {GREEN}✈  +{new_segs} flight(s){RESET}  "
                f"{DIM}tier={candidate.tier} parsed={len(parse_result.flights)} updated={build_result.updated} skipped={build_result.skipped}  "
                f"{from_email[:40]}  |  {subject}{RESET}"
            )

            job.updated_at = datetime.now(timezone.utc)
            db.commit()

            skipped_count = job.scanned_count - job.parsed_count
            _print_progress(job.scanned_count, total_estimate, job.parsed_count, job.segment_count, skipped_count)

        targeted_reparse_ids = _targeted_reparse_message_ids()
        stale_messages = []
        if not limit_reached:
            stale_messages = _select_stale_reparse_messages(
                db,
                user_id=user_id,
                parser_version=PARSER_VERSION,
                limit=sync_limit or MAX_STALE_REPARSE_PER_SYNC,
                targeted_ids=targeted_reparse_ids,
            )
        if stale_messages:
            _ACTIVE_PROGRESS_PHASE = "reparse"
            _print_phase("reparse", f"{len(stale_messages):,} previously parsed messages below parser v{PARSER_VERSION}")
            reporter.tier_started("stale_reparse", "refetching stale DB message IDs")
        for stale_msg in stale_messages:
            msg_id = stale_msg.provider_msg_id
            if msg_id in processed_msg_ids:
                continue
            processed_msg_ids.add(msg_id)
            job.scanned_count += 1
            reporter.count("stale_reparse", "candidate")

            try:
                full_msg = get_message(service, msg_id)
            except Exception as exc:
                logger.warning("Failed to refetch stale message %s: %s", msg_id, exc)
                flush_progress()
                continue
            reporter.count("stale_reparse", "full_fetch")

            headers = extract_headers(full_msg)
            plain_text, html = extract_message_body(full_msg)
            attachments = extract_attachments(full_msg)
            body_for_filter = plain_text if plain_text.strip() else html
            stale_subject = headers.get("subject") or stale_msg.subject or ""
            stale_sender = headers.get("from") or stale_msg.from_email or ""
            stale_pnr = _extract_pnr(f"{stale_subject}\n{body_for_filter}".upper())
            evidence = assess_flight_evidence(
                subject=stale_subject,
                sender=stale_sender,
                body=body_for_filter,
            )
            reporter.evidence("stale_reparse", evidence.verdict)
            if _should_skip_expensive_parse(
                tier="stale_reparse",
                prefilter=True,
                evidence=evidence,
                force_parse=msg_id in targeted_reparse_ids,
            ):
                parse_miss = assess_parse_miss(
                    subject=stale_subject,
                    sender=stale_sender,
                    body=body_for_filter,
                )
                previous_status = stale_msg.status
                stale_msg.status = MessageStatus.ACCEPTED
                stale_msg.ignored = previous_status != MessageStatus.ACCEPTED
                stale_msg.parse_error = parse_miss.reason
                stale_msg.parse_evidence = {
                    **parse_miss.as_dict(),
                    "resolved": True,
                    "reason": "stale_reparse_evidence_skip",
                    "ignored_reason": parse_miss.reason if stale_msg.ignored else None,
                    "previous_status": previous_status.value,
                    "tier": "stale_reparse",
                    "evidence_gate": evidence.as_dict(),
                }
                reporter.count("stale_reparse", "ignored_nonflight")
                stale_msg.parse_version = PARSER_VERSION
                reporter.count("stale_reparse", "gate_skip")
                job.updated_at = datetime.now(timezone.utc)
                db.commit()
                skipped_count = job.scanned_count - job.parsed_count
                _print_progress(job.scanned_count, total_estimate, job.parsed_count, job.segment_count, skipped_count)
                continue

            parse_started = time.perf_counter()
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
            reporter.parser_timing(
                "stale_reparse",
                seconds=time.perf_counter() - parse_started,
                sender=stale_sender,
                subject=stale_subject,
            )
            if stale_pnr and _looks_like_cancellation_notice(stale_subject, body_for_filter):
                canceled_count = cancel_segments_for_pnr(db, user_id, stale_pnr, received_at=_parse_received_at(headers.get("date")))
                canceled_segments += canceled_count
                stale_msg.status = MessageStatus.ACCEPTED
                stale_msg.parse_error = "cancellation_notice"
                stale_msg.parse_evidence = {
                    "reason": "cancellation_notice",
                    "pnr": stale_pnr,
                    "canceled_segments": canceled_count,
                    "resolved": True,
                    "tier": "stale_reparse",
                }
                stale_msg.parse_version = PARSER_VERSION
                job.updated_at = datetime.now(timezone.utc)
                db.commit()
                skipped_count = job.scanned_count - job.parsed_count
                _print_progress(job.scanned_count, total_estimate, job.parsed_count, job.segment_count, skipped_count)
                continue

            if parse_result.flights:
                job.parsed_count += 1
                record_flight_discovery_signals(db, user_id, headers)
                build_result = build_segments_and_trips_detailed(db, user_id, parse_result.flights)
                new_segs = build_result.inserted
                updated_segments += build_result.updated
                skipped_segments += build_result.skipped
                job.segment_count += new_segs
                stale_msg.status = MessageStatus.ACCEPTED
                stale_msg.ignored = False
                stale_msg.parse_error = None
                stale_msg.parse_evidence = {
                    "reason": "parsed_flights",
                    "resolved": True,
                    "flight_count": len(parse_result.flights),
                    "source": parse_result.source,
                    "tier": "stale_reparse",
                }
                reporter.parsed_flight(
                    "stale_reparse",
                    segments=new_segs,
                    updated=build_result.updated,
                    skipped=build_result.skipped,
                    sender=headers.get("from") or stale_msg.from_email or "",
                    subject=headers.get("subject") or stale_msg.subject or "",
                )
                subject = (headers.get("subject") or stale_msg.subject or "")[:60]
                sys.stdout.write("\r" + " " * 120 + "\r")
                print(
                    f"  {GREEN}REPARSE  +{new_segs} flight(s){RESET}  "
                    f"{DIM}parsed={len(parse_result.flights)} updated={build_result.updated} skipped={build_result.skipped}  "
                    f"{(headers.get('from') or stale_msg.from_email or '')[:40]}  |  {subject}{RESET}"
                )
            else:
                parse_miss = assess_parse_miss(
                    subject=headers.get("subject") or stale_msg.subject or "",
                    sender=headers.get("from") or stale_msg.from_email or "",
                    body=body_for_filter,
                )
                existing_pnr_segments = _existing_segments_for_pnr(db, user_id, stale_pnr) if stale_pnr else 0
                if existing_pnr_segments and _looks_like_ancillary_flight_notice(stale_subject, body_for_filter):
                    stale_msg.status = MessageStatus.ACCEPTED
                    stale_msg.parse_error = "ancillary_existing_pnr"
                    stale_msg.parse_evidence = {
                        "reason": "ancillary_email_matches_existing_pnr",
                        "pnr": stale_pnr,
                        "existing_segments": existing_pnr_segments,
                        "parse_miss": parse_miss.as_dict(),
                        "resolved": True,
                        "tier": "stale_reparse",
                    }
                elif not parse_miss.should_review:
                    stale_msg.status = MessageStatus.ACCEPTED
                    stale_msg.ignored = True
                    stale_msg.parse_error = parse_miss.reason
                    stale_msg.parse_evidence = {
                        **parse_miss.as_dict(),
                        "resolved": True,
                        "ignored_reason": parse_miss.reason,
                        "tier": "stale_reparse",
                    }
                else:
                    stale_msg.status = MessageStatus.REVIEW_REQUIRED
                    stale_msg.ignored = False
                    stale_msg.parse_error = parse_miss.reason
                    stale_msg.parse_evidence = {
                        **parse_miss.as_dict(),
                        "resolved": False,
                        "tier": "stale_reparse",
                    }

            stale_msg.parse_version = PARSER_VERSION
            job.updated_at = datetime.now(timezone.utc)
            db.commit()
            skipped_count = job.scanned_count - job.parsed_count
            _print_progress(job.scanned_count, total_estimate, job.parsed_count, job.segment_count, skipped_count)

        sys.stdout.write("\n")
        if not limit_reached and _count_remaining_stale_reparse_messages(
            db,
            user_id=user_id,
            parser_version=PARSER_VERSION,
        ) == 0:
            discovery_state.parser_version = PARSER_VERSION
        if not limit_reached and not reparse_only:
            mark_discovery_plan_success(
                discovery_state,
                discovery_plan,
                scan_started_at=discovery_started_at,
            )
        elif reparse_only:
            discovery_state.updated_at = datetime.now(timezone.utc)
        _ACTIVE_PROGRESS_PHASE = "enrich"
        reporter.tier_started("enrich", "enriching saved segments")
        enriched_segments = enrich_user_segments(db, user_id, include_weather=True)
        if enriched_segments:
            rebuild_user_trips(db, user_id)
        job.state = "completed"
        job.updated_at = datetime.now(timezone.utc)
        db.commit()

        print(f"\n{BOLD}{'─'*60}{RESET}")
        print(f"  {GREEN}✔  Sync complete!{RESET}")
        print(f"{BOLD}{'─'*60}{RESET}\n")

        reporter.final_summary(
            scanned=job.scanned_count,
            parsed=job.parsed_count,
            segments=job.segment_count,
            updated=updated_segments,
            skipped=skipped_segments,
            canceled=canceled_segments,
            enriched=enriched_segments,
        )

        return {
            "job_id": job_id,
            "state": "completed",
            "scanned_count": job.scanned_count,
            "parsed_count": job.parsed_count,
            "segment_count": job.segment_count,
            "enriched_count": enriched_segments,
            "updated_count": updated_segments,
            "skipped_count": skipped_segments,
            "canceled_count": canceled_segments,
            "tier_stats": reporter.as_dict(),
            "limit_reached": limit_reached,
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
        _ACTIVE_PROGRESS_PHASE = None
        db.close()
