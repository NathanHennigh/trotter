"""Apply parsed mailbox evidence through one ownership/cancellation policy.

This module never treats mailbox possession as passenger ownership. Ambiguous
notices are retained for review, and all active-row changes go through the
builder's durable observation/history ledger.
"""
from __future__ import annotations

import re
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from bs4 import BeautifulSoup

from ..models import MessageStatus
from .builder import BuildSegmentsResult, build_segments_and_trips_detailed, cancel_segments_for_pnr


def visible_message_text(plain_text: str, html: str) -> str:
    soup = BeautifulSoup(html or "", "html.parser")
    for node in soup(["script", "style", "head"]):
        node.decompose()
    parts = [plain_text or "", soup.get_text("\n", strip=True)]
    return "\n".join(part for part in parts if part)


def _date(value) -> datetime | None:
    if isinstance(value, datetime):
        result = value
    else:
        try:
            result = parsedate_to_datetime(str(value))
        except (TypeError, ValueError, OverflowError):
            try:
                result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            except (TypeError, ValueError):
                return None
    return result.replace(tzinfo=timezone.utc) if result.tzinfo is None else result.astimezone(timezone.utc)


def booking_event_time(received_at, subject: str, text: str) -> datetime | None:
    """A forwarded old receipt is old evidence, not a new reservation.

    Only an explicit forward with an unambiguous timezone-bearing original
    Date header can change the event time. Reply quotations never do so.
    """
    received = _date(received_at)
    if re.match(r"^\s*re\s*:", subject or "", re.I):
        # A reply may reproduce old booking content; its send time cannot prove
        # a new booking after cancellation.
        return None
    if not re.match(r"^\s*(?:fwd?|fw)\s*:", subject or "", re.I):
        return received
    marker = r"(?:-{2,}\s*Forwarded message\s*-{2,}|Begin forwarded message:)"
    if len(re.findall(marker, text, re.I)) != 1:
        return None
    match = re.search(marker + r"\s*([\s\S]{0,1600})", text, re.I)
    if not match:
        return None
    date_match = re.search(r"(?im)^\s*Date:\s*(.+)$", match.group(1))
    if (len(re.findall(r"(?im)^\s*Date:", match.group(1))) != 1
            or not date_match or not re.search(r"(?:[+-]\d{4}|\b(?:UTC|GMT|[ECMP][SD]T))\b", date_match[1])):
        return None
    original = _date(date_match[1])
    return original if original and (not received or original <= received) else None


@dataclass
class AppliedBooking:
    build: BuildSegmentsResult
    canceled: int = 0
    is_cancellation: bool = False
    review_reason: str | None = None

    @property
    def status(self):
        return MessageStatus.REVIEW_REQUIRED if self.review_reason or getattr(self.build, "held_unknown", 0) else MessageStatus.ACCEPTED

    def evidence(self, source: str, tier: str) -> dict:
        return {
            "reason": self.review_reason or ("cancellation_notice" if self.is_cancellation else "reconciled_flights"),
            "resolved": self.status == MessageStatus.ACCEPTED,
            "source": source,
            "tier": tier,
            "inserted": self.build.inserted,
            "updated": self.build.updated,
            "held_other": getattr(self.build, "held_other", 0),
            "held_unknown": getattr(self.build, "held_unknown", 0),
            "blocked_cancellation": getattr(self.build, "blocked_cancellation", 0),
            "canceled_segments": self.canceled,
        }


_NONFINAL_CANCELLATION = re.compile(
    r"\b(?:not|never|no longer|if|when|unless|whether|may|might|could|would|will|"
    r"policy|policies|fees|insurance|how to|request(?:ed)?|pending|denied|declined|"
    r"rejected|failed|unsuccessful)\b", re.I,
)


def _cancellation_assertions(subject: str, text: str) -> list[str]:
    """Return completed cancellation statements, excluding conditions and quotes."""
    if re.match(r"^\s*re\s*:", subject or "", re.I):
        return []
    subject_text = re.sub(r"^\s*(?:(?:fwd?|fw)\s*:\s*)+", "", subject or "", flags=re.I)
    assertions = []
    if (re.search(r"\b(?:flight|trip|itinerary|booking|reservation)\b", subject_text, re.I)
            and re.search(r"\bcancel(?:led|ed)\b|\bcancellation\s+(?:confirmed|complete[ds]?|successful)\b", subject_text, re.I)
            and not _NONFINAL_CANCELLATION.search(subject_text)):
        assertions.append(subject_text)
    current = re.split(r"(?im)^\s*(?:On .+wrote:|>{1,}|-{2,}\s*Original Message)", text, maxsplit=1)[0]
    # DOM line breaks can split 'If' from 'your flight is canceled'. Preserve
    # that grammatical relationship before checking the complete sentence.
    current = re.sub(r"\s+", " ", current)
    pattern = r"\b(?:your|the)\s+(?:flight|trip|booking|reservation)(?:[^.!?]{0,80})\s+(?:has been|was|is)\s+cancel(?:led|ed)\b"
    for match in re.finditer(pattern, current, re.I):
        prefix = re.split(r"[.!?]", current[:match.start()])[-1]
        suffix = re.split(r"[.!?]", current[match.end():], maxsplit=1)[0]
        sentence = prefix + match.group(0) + suffix
        if not _NONFINAL_CANCELLATION.search(sentence):
            assertions.append(sentence.strip())
    return list(dict.fromkeys(assertions))


def _cancellation_intent(subject: str, text: str) -> bool:
    return bool(_cancellation_assertions(subject, text))


def _dated_canceled_legs(assertions: list[str], flights: list) -> tuple[bool, list]:
    """Partial notices need an explicitly canceled flight number and travel date.

    Passenger-only changes cannot be represented by the current leg cancellation
    ledger and must be reviewed instead of deleting everybody on that booking.
    """
    partial = False
    selected = []
    for assertion in assertions:
        if re.search(r"\b(?:passenger|traveler|traveller|ticket)\b", assertion, re.I):
            return True, []
        if re.search(r"\b(?:only|outbound|inbound|return|segment|leg|one of|some of)\b", assertion, re.I):
            partial = True
        if len(flights) > 1 and re.search(r"\byour\s+flight\b", assertion, re.I):
            partial = True
        for flight in flights:
            number = re.sub(r"\s+", "", flight.flight_number or "").upper()
            if not number or not re.search(r"(?<![A-Z0-9])" + re.escape(number[:2]) + r"\s*" + re.escape(number[2:]) + r"(?![A-Z0-9])", assertion.upper()):
                continue
            partial = True
            dates = []
            for value in re.findall(r"\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}/\d{1,2}/\d{4}\b|\b[A-Za-z]+\s+\d{1,2},?\s+\d{4}\b", assertion):
                for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%B %d, %Y", "%B %d %Y", "%b %d, %Y", "%b %d %Y"):
                    try:
                        dates.append(datetime.strptime(value, fmt).date())
                        break
                    except ValueError:
                        continue
            if flight.dep_time.date() in dates and flight not in selected:
                selected.append(flight)
    return partial, selected


def apply_booking_message(db, user_id: int, parsed, *, source_message_id: str,
                          subject: str = "", plain_text: str = "", html: str = "",
                          received_at=None) -> AppliedBooking:
    from .parser import _extract_pnr

    text = visible_message_text(plain_text, html)
    event_at = booking_event_time(received_at, subject, text)
    flights = deepcopy(parsed.flights)
    for flight in flights:
        flight.source_received_at = event_at
    cancellation = _cancellation_intent(subject, text)
    canceled = 0
    review_reason = None
    if cancellation:
        partial, dated_legs = _dated_canceled_legs(_cancellation_assertions(subject, text), flights)
        cancellation_flights = dated_legs if partial else flights
        references = {str(f.pnr).strip().upper() for f in cancellation_flights if f.pnr}
        # Explicit cancellation references are preferred to a code elsewhere
        # in a mixed cancellation/rebooking email.
        explicit = set(re.findall(r"\b(?:booking|reservation)(?:\s+(?:reference|code|number))?\s*[:#]?\s*([A-Z0-9]{5,8})\s+(?:has been|was|is)\s+cancel(?:led|ed)\b", text, re.I))
        explicit = {value.upper() for value in explicit}
        reference = next(iter(explicit)) if len(explicit) == 1 else None
        if not reference and len(references) == 1:
            reference = next(iter(references))
        if not reference and not references:
            reference = _extract_pnr(f"{subject}\n{text}".upper())
        mixed = bool(re.search(r"\b(?:new|replacement|rebooked|remaining)\s+(?:flight|booking|itinerary|reservation)\b", text, re.I))
        if event_at is None:
            review_reason = "ambiguous_cancellation_time"
        elif partial and not dated_legs:
            review_reason = "ambiguous_cancellation_scope"
        elif (not reference or len(explicit) > 1
              or (mixed and not dated_legs and (not explicit or len(references) <= 1))):
            review_reason = "ambiguous_cancellation_scope"
        else:
            scoped = [f for f in cancellation_flights if not f.pnr or f.pnr.upper() == reference]
            canceled = cancel_segments_for_pnr(
                db, user_id, reference, received_at=event_at,
                source_message_id=source_message_id, source_event_at=event_at,
                flights=scoped,
            )
            # An unchanged leg quoted alongside a cancellation is not proof of
            # a new booking after some other cancellation. Keep that observation
            # for review instead of refreshing or resurrecting the active row.
            for flight in flights:
                if flight not in scoped:
                    flight.force_review = True
            from .booking_ledger import cancellation_scope_resolved
            if not cancellation_scope_resolved(db, user_id, reference, source_message_id):
                review_reason = "unresolved_cancellation_scope"
        if review_reason:
            for flight in flights:
                flight.force_review = True

    result = build_segments_and_trips_detailed(
        db, user_id, flights, source_message_id=source_message_id,
        source_event_at=event_at,
    ) if flights else BuildSegmentsResult()
    return AppliedBooking(result, canceled, cancellation, review_reason)


def set_message_outcome(message, applied: AppliedBooking, *, source: str, tier: str) -> None:
    message.status = applied.status
    message.ignored = False
    message.parse_error = applied.review_reason or (
        "passenger_identity_unresolved" if getattr(applied.build, "held_unknown", 0)
        else "cancellation_notice" if applied.is_cancellation else None
    )
    message.parse_evidence = applied.evidence(source, tier)
