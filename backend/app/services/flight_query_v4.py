"""Tiered, stateful Gmail discovery for production flight imports."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from typing import Iterable, Optional

from sqlalchemy.orm import Session

from ..models import GmailDiscoverySignal, GmailDiscoveryState
from .flight_query_v2 import build_gmail_queries as build_broad_queries
from .flight_query_v3 import DEFAULT_LOOKBACK_START, build_gmail_queries as build_precise_queries
from .parser import PARSER_VERSION

RECENT_BROAD_DAYS = 548
INCREMENTAL_OVERLAP_DAYS = 2
BACKFILL_WINDOW_DAYS = 31
MAX_BACKFILL_WINDOWS_PER_SYNC = 1


@dataclass(frozen=True)
class DiscoveryQuery:
    tier: str
    query: str
    prefilter: bool = True
    window_start: Optional[datetime] = None
    window_end: Optional[datetime] = None


@dataclass(frozen=True)
class DiscoveryCandidate:
    msg: dict
    tier: str
    query: str
    prefilter: bool


def get_or_create_discovery_state(db: Session, user_id: int) -> GmailDiscoveryState:
    state = (
        db.query(GmailDiscoveryState)
        .filter(GmailDiscoveryState.user_id == user_id, GmailDiscoveryState.provider == "google")
        .first()
    )
    if state:
        return state

    state = GmailDiscoveryState(user_id=user_id, provider="google")
    db.add(state)
    db.flush()
    return state


def build_discovery_plan(
    state: GmailDiscoveryState,
    *,
    now: datetime,
    learned_sender_domains: Optional[list[str]] = None,
    max_backfill_windows: int = MAX_BACKFILL_WINDOWS_PER_SYNC,
) -> list[DiscoveryQuery]:
    """Return ordered v4 discovery tiers for this sync run.

    The first run is intentionally deep. Once a user has completed a sync,
    normal app-triggered runs become incremental-only so they do not keep
    paging through old travel/promotional mail just to skip known message IDs.
    """
    now = _ensure_utc(now)
    plan: list[DiscoveryQuery] = []
    has_completed_sync = bool(state.last_incremental_scan_at)
    needs_parser_repair = (getattr(state, "parser_version", 0) or 0) < PARSER_VERSION

    incremental_start = _incremental_start(state, now)
    plan.extend(
        DiscoveryQuery(tier="incremental_precise", query=query, prefilter=True)
        for query in build_precise_queries(since=_gmail_after_date(incremental_start))
    )

    if has_completed_sync:
        learned_queries = _build_learned_sender_queries(
            learned_sender_domains or [],
            since=_gmail_after_date(incremental_start),
        )
        plan.extend(
            DiscoveryQuery(tier="incremental_learned_senders", query=query, prefilter=True)
            for query in learned_queries
        )

    if has_completed_sync and needs_parser_repair:
        repair_start = max(_earliest_supported_datetime(), now - timedelta(days=RECENT_BROAD_DAYS))
        plan.extend(
            DiscoveryQuery(tier="parser_upgrade_recent_repair", query=query, prefilter=True)
            for query in build_broad_queries(since=_gmail_after_date(repair_start))
        )

    if not has_completed_sync:
        broad_start = max(incremental_start, now - timedelta(days=RECENT_BROAD_DAYS))
        plan.extend(
            DiscoveryQuery(tier="initial_broad_recent", query=query, prefilter=True)
            for query in build_broad_queries(since=_gmail_after_date(broad_start))
        )

    if not state.backfill_complete:
        plan.extend(_build_backfill_windows(state, now, max_backfill_windows=max_backfill_windows))

    return plan


def get_learned_sender_domains(db: Session, user_id: int, limit: int = 100) -> list[str]:
    rows = (
        db.query(GmailDiscoverySignal)
        .filter(
            GmailDiscoverySignal.user_id == user_id,
            GmailDiscoverySignal.provider == "google",
            GmailDiscoverySignal.signal_type == "sender_domain",
        )
        .order_by(GmailDiscoverySignal.hit_count.desc(), GmailDiscoverySignal.last_seen_at.desc())
        .limit(limit)
        .all()
    )
    return [row.signal_value for row in rows]


def record_flight_discovery_signals(db: Session, user_id: int, headers: dict[str, str]) -> None:
    sender = headers.get("from", "")
    domain = _extract_sender_domain(sender)
    if not domain:
        return

    now = datetime.now(timezone.utc)
    signal = (
        db.query(GmailDiscoverySignal)
        .filter(
            GmailDiscoverySignal.user_id == user_id,
            GmailDiscoverySignal.provider == "google",
            GmailDiscoverySignal.signal_type == "sender_domain",
            GmailDiscoverySignal.signal_value == domain,
        )
        .first()
    )
    if signal:
        signal.hit_count += 1
        signal.last_seen_at = now
        return

    db.add(
        GmailDiscoverySignal(
            user_id=user_id,
            provider="google",
            signal_type="sender_domain",
            signal_value=domain,
            hit_count=1,
            first_seen_at=now,
            last_seen_at=now,
        )
    )


def iter_discovery_messages(service, plan: Iterable[DiscoveryQuery]) -> Iterable[DiscoveryCandidate]:
    """Yield deduped Gmail message stubs for an ordered discovery plan."""
    from .gmail import iter_all_messages

    seen: set[str] = set()
    for item in plan:
        for msg, _page_token in iter_all_messages(service, query=item.query):
            msg_id = msg.get("id")
            if not msg_id or msg_id in seen:
                continue
            seen.add(msg_id)
            yield DiscoveryCandidate(
                msg=msg,
                tier=item.tier,
                query=item.query,
                prefilter=item.prefilter,
            )


def mark_discovery_plan_success(
    state: GmailDiscoveryState,
    plan: Iterable[DiscoveryQuery],
    *,
    scan_started_at: datetime,
) -> None:
    """Persist successful incremental and backfill progress."""
    state.last_incremental_scan_at = _ensure_utc(scan_started_at)
    backfill_items = [item for item in plan if item.tier == "exhaustive_backfill"]
    if backfill_items:
        oldest_start = min(item.window_start for item in backfill_items if item.window_start)
        earliest = _earliest_supported_datetime()
        if oldest_start <= earliest:
            state.backfill_complete = True
            state.backfill_cursor_before = earliest
        else:
            state.backfill_cursor_before = oldest_start
    if any(item.tier == "parser_upgrade_recent_repair" for item in plan):
        state.parser_version = PARSER_VERSION
    state.updated_at = datetime.now(timezone.utc)


def _incremental_start(state: GmailDiscoveryState, now: datetime) -> datetime:
    if state.last_incremental_scan_at:
        return _ensure_utc(state.last_incremental_scan_at) - timedelta(days=INCREMENTAL_OVERLAP_DAYS)
    return _earliest_supported_datetime()


def _build_backfill_windows(
    state: GmailDiscoveryState,
    now: datetime,
    *,
    max_backfill_windows: int,
) -> list[DiscoveryQuery]:
    windows: list[DiscoveryQuery] = []
    cursor = _ensure_utc(state.backfill_cursor_before) if state.backfill_cursor_before else now
    earliest = _earliest_supported_datetime()

    for _ in range(max(0, max_backfill_windows)):
        if cursor <= earliest:
            break
        window_end = _start_of_day(cursor)
        window_start = max(earliest, window_end - timedelta(days=BACKFILL_WINDOW_DAYS))
        if window_start >= window_end:
            break
        windows.append(
            DiscoveryQuery(
                tier="exhaustive_backfill",
                query=f"after:{_gmail_after_date(window_start)} before:{_gmail_date(window_end)}",
                prefilter=False,
                window_start=window_start,
                window_end=window_end,
            )
        )
        cursor = window_start
    return windows


def _build_learned_sender_queries(sender_domains: list[str], *, since: str) -> list[str]:
    terms = [f"from:{domain}" for domain in sorted(set(sender_domains)) if domain]
    return _chunk_terms(terms, since=since, max_query_length=1400)


def _chunk_terms(terms: list[str], *, since: str, max_query_length: int) -> list[str]:
    queries: list[str] = []
    current: list[str] = []
    for term in terms:
        candidate = current + [term]
        rendered = f"after:{since} (" + " OR ".join(candidate) + ")"
        if current and len(rendered) > max_query_length:
            queries.append(f"after:{since} (" + " OR ".join(current) + ")")
            current = [term]
        else:
            current = candidate
    if current:
        queries.append(f"after:{since} (" + " OR ".join(current) + ")")
    return queries


def _extract_sender_domain(sender: str) -> Optional[str]:
    if "@" not in sender:
        return None
    domain = sender.split("@")[-1].rstrip(">").strip().lower()
    return domain or None


def _gmail_date(dt: datetime) -> str:
    dt = _ensure_utc(dt)
    return f"{dt.year}/{dt.month}/{dt.day}"


def _gmail_after_date(dt: datetime) -> str:
    """Return a Gmail `after:` date that includes the UTC day containing dt."""
    inclusive_start = _ensure_utc(dt) - timedelta(days=1)
    return _gmail_date(inclusive_start)


def _earliest_supported_datetime() -> datetime:
    year, month, day = (int(part) for part in DEFAULT_LOOKBACK_START.split("/"))
    return datetime(year, month, day, tzinfo=timezone.utc)


def _start_of_day(dt: datetime) -> datetime:
    dt = _ensure_utc(dt)
    return datetime.combine(dt.date(), time.min, tzinfo=timezone.utc)


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
