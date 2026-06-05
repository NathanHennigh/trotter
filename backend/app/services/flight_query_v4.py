"""Tiered, stateful Gmail discovery for production flight imports."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
import csv
import os
from pathlib import Path
from typing import Iterable, Optional

from sqlalchemy.orm import Session

from ..models import GmailDiscoverySignal, GmailDiscoveryState
from .flight_query import (
    HIGH_CONFIDENCE_FLIGHT_SENDERS,
    NOISY_TRAVEL_SENDERS,
    OTA_FLIGHT_SENDERS,
    SENDER_DOMAINS,
)
from .flight_query_v2 import build_gmail_queries as build_broad_queries
from .flight_query_v3 import DEFAULT_LOOKBACK_START, build_gmail_queries as build_precise_queries

INITIAL_QUICK_DAYS = int(os.getenv("TROTTER_INITIAL_QUICK_DAYS", "180"))
RECENT_BROAD_DAYS = int(os.getenv("TROTTER_RECENT_BROAD_DAYS", "548"))
INCREMENTAL_OVERLAP_DAYS = 2
BACKFILL_WINDOW_DAYS = 31
MAX_BACKFILL_WINDOWS_PER_SYNC = 1
ENABLE_AUTOMATIC_BACKFILL = os.getenv("TROTTER_ENABLE_AUTOMATIC_BACKFILL", "").strip().lower() in {
    "1",
    "true",
    "yes",
}
ENABLE_RECALL_DISCOVERY_TIERS = os.getenv("TROTTER_ENABLE_RECALL_DISCOVERY_TIERS", "").strip().lower() in {
    "1",
    "true",
    "yes",
}
PROMOTIONS_EXCLUSION = "-category:promotions"
STRONG_FLIGHT_KEYWORDS = [
    "boarding pass",
    "mobile boarding pass",
    "record locator",
    "confirmation #",
    "confirmation code",
    "confirmation number",
    "flight confirmation",
    "flight receipt",
    "e-ticket",
    "eticket",
    "check in for your flight",
    "check in online for your flight",
    "check-in for your flight",
    "check-in online for your flight",
    "schedule change",
    "flight update",
    "your trip",
    "itinerary",
]
BROAD_BACKSCAN_KEYWORDS = sorted(
    set(
        STRONG_FLIGHT_KEYWORDS
        + [
            "booking reference",
            "confirmation code",
            "confirmation number",
            "reservation code",
            "your flight",
            "your upcoming trip",
            "trip confirmation",
            "travel itinerary",
            "ticket number",
            "passenger receipt",
            "download your boarding pass",
            "time to check in",
        ]
    )
)
EXCLUDED_FAST_SENDER_DOMAINS = {
    "airbnb.com",
    "barclaycardus.com",
    "barclays.com",
    "biltrewards.com",
    "capitalone.com",
    "citi.com",
    "citicards.com",
    "discover.com",
    "email-marriott.com",
    "marriott.com",
    "prioritypass.com",
    "uber.com",
    "venture.capitalone.com",
    "wellsfargo.com",
}


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
    incremental_start = _incremental_start(state, now)

    # Sender-first discovery remains useful as additive coverage for known
    # transactional domains and user-learned senders. It must not replace the
    # committed v3 precise path until baseline recall proves that is safe.
    plan.extend(
        DiscoveryQuery(tier="fast_known_senders", query=query, prefilter=True)
        for query in build_fast_known_sender_queries(
            since=_gmail_after_date(incremental_start),
            learned_sender_domains=learned_sender_domains or [],
        )
    )

    plan.extend(
        DiscoveryQuery(tier="fast_strong_keywords", query=query, prefilter=True)
        for query in build_fast_strong_keyword_queries(since=_gmail_after_date(incremental_start))
    )

    if ENABLE_RECALL_DISCOVERY_TIERS:
        plan.extend(
            DiscoveryQuery(tier="incremental_precise", query=query, prefilter=True)
            for query in build_precise_queries(since=_gmail_after_date(incremental_start))
        )

    if ENABLE_RECALL_DISCOVERY_TIERS and not has_completed_sync:
        broad_start = max(incremental_start, now - timedelta(days=RECENT_BROAD_DAYS))
        plan.extend(
            DiscoveryQuery(tier="initial_broad_recent", query=query, prefilter=True)
            for query in build_broad_queries(since=_gmail_after_date(broad_start))
        )

    if ENABLE_AUTOMATIC_BACKFILL and not state.backfill_complete:
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
    if not ENABLE_AUTOMATIC_BACKFILL:
        state.backfill_complete = True
        state.backfill_cursor_before = _ensure_utc(scan_started_at)
        state.updated_at = datetime.now(timezone.utc)
        return
    backfill_items = [item for item in plan if item.tier == "exhaustive_backfill"]
    if backfill_items:
        oldest_start = min(item.window_start for item in backfill_items if item.window_start)
        earliest = _earliest_supported_datetime()
        if oldest_start <= earliest:
            state.backfill_complete = True
            state.backfill_cursor_before = earliest
        else:
            state.backfill_cursor_before = oldest_start
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


def build_fast_known_sender_queries(
    *,
    since: str,
    learned_sender_domains: Optional[list[str]] = None,
) -> list[str]:
    domains = sorted(
        _expand_sender_domain_terms(
            set(load_fast_known_sender_domains())
            | set(_normal_sender_domains(learned_sender_domains or []))
        )
    )
    terms = [f"from:{domain}" for domain in domains]
    return _chunk_terms(terms, since=since, max_query_length=1400, suffix=PROMOTIONS_EXCLUSION)


def build_fast_strong_keyword_queries(*, since: str) -> list[str]:
    terms = [f'"{keyword}"' for keyword in STRONG_FLIGHT_KEYWORDS]
    return _chunk_terms(terms, since=since, max_query_length=1400, suffix=PROMOTIONS_EXCLUSION)


def build_background_backscan_queries(window_start: datetime, window_end: datetime) -> list[str]:
    since = _gmail_after_date(window_start)
    before = _gmail_date(window_end)
    safe_domains = sorted(
        _expand_sender_domain_terms(
            set(load_fast_known_sender_domains())
            | set(OTA_FLIGHT_SENDERS)
            | (set(SENDER_DOMAINS) - set(NOISY_TRAVEL_SENDERS))
        )
    )
    terms = [f"from:{domain}" for domain in safe_domains]
    terms.extend(f'"{keyword}"' for keyword in BROAD_BACKSCAN_KEYWORDS)
    return _chunk_terms(
        terms,
        since=since,
        max_query_length=1400,
        suffix=f"before:{before}",
    )


def load_fast_known_sender_domains(csv_path: Optional[Path] = None) -> list[str]:
    """Return built-in + optional root domains.csv sender domains."""
    domains = set(HIGH_CONFIDENCE_FLIGHT_SENDERS)
    path = csv_path or _default_domains_csv_path()
    if path.exists():
        with path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                domains.update(_normal_sender_domains([row.get("domain") or ""]))
    return sorted(domain for domain in domains if not _is_excluded_fast_sender_domain(domain))


def _chunk_terms(terms: list[str], *, since: str, max_query_length: int, suffix: str = "") -> list[str]:
    queries: list[str] = []
    current: list[str] = []
    extra = f" {suffix}" if suffix else ""
    for term in terms:
        candidate = current + [term]
        rendered = f"after:{since} (" + " OR ".join(candidate) + f"){extra}"
        if current and len(rendered) > max_query_length:
            queries.append(f"after:{since} (" + " OR ".join(current) + f"){extra}")
            current = [term]
        else:
            current = candidate
    if current:
        queries.append(f"after:{since} (" + " OR ".join(current) + f"){extra}")
    return queries


def _normal_sender_domains(domains: list[str]) -> list[str]:
    results: list[str] = []
    for value in domains:
        domain = (value or "").strip().lower()
        if not domain:
            continue
        if "@" in domain:
            domain = domain.split("@")[-1].rstrip(">").strip()
        if domain:
            results.append(domain)
    return results


def _expand_sender_domain_terms(domains: set[str]) -> set[str]:
    """Include exact domains plus root-domain wildcard terms.

    Gmail search does not support a literal ``from:*.example.com`` operator.
    In practice, querying ``from:example.com`` is the wildcard-style term we
    need because subdomain senders still contain the registrable root in the
    From address, e.g. ``receipt@t.delta.com`` contains ``delta.com``.
    Keep exact subdomains too so named transactional domains remain explicit.
    """
    expanded: set[str] = set()
    for domain in domains:
        normalized = _normal_sender_domains([domain])
        if not normalized:
            continue
        value = normalized[0]
        if not _is_excluded_fast_sender_domain(value):
            expanded.add(value)
        root = _registrable_domain(value)
        if root and not _is_excluded_fast_sender_domain(root):
            expanded.add(root)
    return expanded


def _is_excluded_fast_sender_domain(domain: str) -> bool:
    value = (domain or "").strip().lower()
    if not value:
        return True
    root = _registrable_domain(value)
    return value in EXCLUDED_FAST_SENDER_DOMAINS or root in EXCLUDED_FAST_SENDER_DOMAINS


_SECOND_LEVEL_TLDS = {
    "co.id",
    "co.uk",
    "co.kr",
    "co.za",
    "com.au",
    "com.br",
    "com.np",
    "com.mx",
    "com.tr",
    "co.jp",
    "co.nz",
    "co.in",
    "com.ph",
    "com.sg",
    "com.my",
    "com.cn",
    "com.hk",
    "com.tw",
    "com.ar",
    "com.co",
}


def _registrable_domain(domain: str) -> str:
    parts = [part for part in domain.lower().split(".") if part]
    if len(parts) <= 2:
        return domain.lower()
    suffix = ".".join(parts[-2:])
    if suffix in _SECOND_LEVEL_TLDS and len(parts) >= 3:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def _default_domains_csv_path() -> Path:
    return Path(__file__).resolve().parents[3] / "domains.csv"


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
