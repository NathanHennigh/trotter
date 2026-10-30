"""Durable, bounded historical discovery independent of recent mail sync."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os

from sqlalchemy import and_, func, literal, or_
from sqlalchemy.exc import IntegrityError

from ..models import Account, GmailDiscoveryState, GmailHistoryState, User
from .flight_query_v4 import BACKFILL_WINDOW_DAYS, _earliest_supported_datetime, _ensure_utc, _gmail_after_date, _gmail_date, _start_of_day
from .gmail_connection import READABLE_GMAIL_SCOPES, connection_status

PAGE_SIZE = 50
LEASE_SECONDS = 420
MAX_ATTEMPTS = 8


def enabled() -> bool:
    return os.getenv("TROTTER_ENABLE_AUTOMATIC_BACKFILL", "").strip().lower() in {"1", "true", "yes"}


def allowed_user_ids() -> set[int] | None:
    value = os.getenv("TROTTER_GMAIL_HISTORY_USER_IDS", "")
    if value.strip() == "*":
        return None
    return {int(part.strip()) for part in value.split(",") if part.strip().isdigit()}


def user_enabled(user_id: int) -> bool:
    allowed = allowed_user_ids()
    return enabled() and (allowed is None or user_id in allowed)


def _connected_account_filter():
    # Match connection_status before limiting a scheduler batch. Otherwise older
    # disconnected accounts can occupy every slot forever. OAuth scopes are
    # whitespace-separated tokens, so substring matches must not grant access.
    scopes = func.coalesce(Account.scopes, "")
    for separator in ("\t", "\r", "\n", "\v", "\f"):
        scopes = func.replace(scopes, separator, " ")
    scopes = literal(" ") + scopes + literal(" ")
    return and_(
        Account.provider == "google",
        or_(Account.gmail_connection_status.is_(None), Account.gmail_connection_status != "needs_reconnect"),
        func.length(Account.refresh_token_encrypted) > 0,
        or_(*(scopes.contains(f" {scope} ") for scope in sorted(READABLE_GMAIL_SCOPES))),
    )


def discover_history_jobs(db, *, now=None, limit=2) -> list[tuple[int, int]]:
    if not enabled():
        return []
    allowed = allowed_user_ids()
    if allowed == set():
        return []
    now = now or datetime.now(timezone.utc)
    reconnect_query = (db.query(GmailHistoryState)
                       .join(Account, Account.user_id == GmailHistoryState.user_id)
                       .filter(GmailHistoryState.state == "paused",
                               GmailHistoryState.error_code == "gmail_connection_required",
                               _connected_account_filter()))
    if allowed is not None:
        reconnect_query = reconnect_query.filter(GmailHistoryState.user_id.in_(allowed))
    for row in reconnect_query.order_by(GmailHistoryState.updated_at).limit(limit).all():
        account = db.query(Account).filter_by(user_id=row.user_id, provider="google").first()
        if connection_status(account) == "connected":
            row.state, row.error_code, row.attempts = "pending", None, 0
            row.next_attempt_at, row.lease_until = now, None
    # Only users with a successful initial recent-mail scan enter the background
    # lane. Legacy backfill_complete was unreliable, so new coverage starts fresh.
    accounts_query = (db.query(Account).join(User, User.id == Account.user_id)
                .join(GmailDiscoveryState, GmailDiscoveryState.user_id == Account.user_id)
                .outerjoin(GmailHistoryState, GmailHistoryState.user_id == Account.user_id)
                .filter(_connected_account_filter(), GmailDiscoveryState.last_incremental_scan_at.is_not(None),
                        GmailHistoryState.id.is_(None)))
    if allowed is not None:
        accounts_query = accounts_query.filter(Account.user_id.in_(allowed))
    accounts = accounts_query.order_by(Account.user_id).limit(limit).all()
    for account in accounts:
        if connection_status(account) == "connected":
            try:
                with db.begin_nested():
                    db.add(GmailHistoryState(user_id=account.user_id, state="pending", pending_message_ids=[],
                                             cursor_before=now, next_attempt_at=now))
                    db.flush()
            except IntegrityError:
                pass  # Another scheduler won creation, or the account was erased.
    db.commit()
    query = (db.query(GmailHistoryState).join(User, User.id == GmailHistoryState.user_id)
            .filter(GmailHistoryState.state.in_(["pending", "queued", "running"]),
                    or_(GmailHistoryState.next_attempt_at.is_(None), GmailHistoryState.next_attempt_at <= now),
                    or_(GmailHistoryState.lease_until.is_(None), GmailHistoryState.lease_until <= now)))
    if allowed is not None:
        query = query.filter(GmailHistoryState.user_id.in_(allowed))
    rows = query.order_by(GmailHistoryState.next_attempt_at, GmailHistoryState.id).with_for_update(skip_locked=True).limit(limit).all()
    claimed = []
    for row in rows:
        account = db.query(Account).filter_by(user_id=row.user_id, provider="google").first()
        if connection_status(account) != "connected":
            row.state, row.error_code = "paused", "gmail_connection_required"
            continue
        row.state, row.lease_until = "queued", now + timedelta(seconds=LEASE_SECONDS)
        row.updated_at = now
        claimed.append((row.id, row.user_id))
    db.commit()
    return claimed


def prepare_history_page(db, user_id: int, state_id: int, service):
    from .gmail import list_messages
    row = db.query(GmailHistoryState).filter_by(id=state_id, user_id=user_id).first()
    if row is None or row.state not in {"pending", "queued", "running"}:
        raise ValueError("history_job_unavailable")
    now = datetime.now(timezone.utc)
    row.state, row.updated_at = "running", now
    row.lease_until = now + timedelta(seconds=LEASE_SECONDS)
    if row.pending_message_ids:
        db.commit()
        return row, list(row.pending_message_ids)
    earliest = _earliest_supported_datetime()
    if not row.window_start:
        end = _start_of_day(_ensure_utc(row.cursor_before or now))
        if end <= earliest:
            row.state = "complete"
            row.lease_until = None
            db.commit()
            return row, []
        row.window_end, row.window_start = end, max(earliest, end - timedelta(days=BACKFILL_WINDOW_DAYS))
    query = f"after:{_gmail_after_date(row.window_start)} before:{_gmail_date(row.window_end)}"
    try:
        messages, next_token = list_messages(service, query=query, page_token=row.page_token, max_results=PAGE_SIZE)
    except Exception as exc:
        if row.page_token and getattr(getattr(exc, "resp", None), "status", None) == 400:
            # Gmail may expire a search cursor. Repeat this window safely through
            # stored message IDs, never jump past a page whose coverage is unknown.
            row.page_token = row.next_page_token = None
            db.commit()
        raise
    ids = list(dict.fromkeys(str(message["id"]) for message in messages if message.get("id")))
    if len(ids) > PAGE_SIZE:
        raise ValueError("gmail_history_page_exceeded")
    row.pending_message_ids, row.next_page_token = ids, next_token
    db.commit()  # Never lose a fetched page when a worker exits halfway through it.
    return row, ids


def finish_history_page(db, row, failed_ids: set[str], *, deferred_ids: set[str] | None = None, now=None):
    now = now or datetime.now(timezone.utc)
    # Account erasure removes this row. Never recreate it from a queued task.
    if row is None or db.query(GmailHistoryState.id).filter_by(id=row.id, user_id=row.user_id).first() is None:
        return
    pending = list(row.pending_message_ids or [])
    failures = [mid for mid in pending if mid in failed_ids]
    deferred = [mid for mid in pending if mid in (deferred_ids or set())]
    row.scanned_count += len(pending) - len(set(failures + deferred))
    row.pending_message_ids = list(dict.fromkeys(failures + deferred))
    row.updated_at, row.lease_until = now, None
    if failures:
        fail_history_page(db, row.id, "gmail_fetch_retry", now=now)
        return
    if deferred:
        row.state, row.error_code = "pending", None
        row.next_attempt_at = now + timedelta(seconds=60)
        return
    row.attempts, row.error_code = 0, None
    if row.state == "complete":
        return
    if row.next_page_token:
        row.page_token, row.next_page_token = row.next_page_token, None
    else:
        row.cursor_before = row.window_start
        row.window_start = row.window_end = row.page_token = row.next_page_token = None
    row.state = "complete" if _ensure_utc(row.cursor_before) <= _earliest_supported_datetime() else "pending"
    row.next_attempt_at = now + timedelta(seconds=60)


def fail_history_page(db, state_id: int, error_code: str, *, now=None):
    now = now or datetime.now(timezone.utc)
    row = db.get(GmailHistoryState, state_id)
    if row is None:
        return
    row.attempts += 1
    row.state = "paused" if row.attempts >= MAX_ATTEMPTS or error_code == "gmail_connection_required" else "pending"
    row.error_code, row.lease_until, row.updated_at = error_code, None, now
    row.next_attempt_at = now + timedelta(seconds=min(3600, 60 * 2 ** min(row.attempts, 6)))


def history_progress(db, user_id: int) -> dict:
    row = db.query(GmailHistoryState).filter_by(user_id=user_id, provider="google").first()
    if not row:
        return {"state": "not_started", "complete": False}
    return {"state": row.state, "complete": row.state == "complete", "checked_before": row.cursor_before,
            "scanned_count": row.scanned_count, "error_code": row.error_code}
