"""Apply parsed mailbox evidence through one ownership/cancellation policy.

This module never treats mailbox possession as passenger ownership. Ambiguous
notices are retained for review, and all active-row changes go through the
builder's durable observation/history ledger.
"""
from __future__ import annotations

import re
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from types import SimpleNamespace

from bs4 import BeautifulSoup

from ..models import MessageStatus
from .builder import BuildSegmentsResult, build_segments_and_trips_detailed, cancel_segments_for_pnr


def visible_message_text(plain_text: str, html: str) -> str:
    soup = BeautifulSoup(html or "", "html.parser")
    for node in soup(["script", "style", "head"]):
        node.decompose()
    parts = [plain_text or "", soup.get_text("\n", strip=True)]
    return "\n".join(part for part in parts if part)


def booking_time_text(plain_text: str, html: str) -> str:
    # MIME alternatives describe one message. Combining them repeats forwarded
    # Date headers and incorrectly turns a single original receipt into an
    # ambiguous nested forward. Keep the unmodified plain version when present.
    return plain_text if (plain_text or '').strip() else visible_message_text('', html)


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


def booking_time_provenance(received_at, subject: str, text: str):
    """Retain receipt time separately; an unknown forwarded timezone is an
    interval, never a manufactured UTC instant or a newly received booking.
    """
    received = _date(received_at)
    event = booking_event_time(received_at, subject, text)
    result = {'version': 1, 'received_at': received.isoformat() if received else None,
              'event_at': event.isoformat() if event else None, 'kind': 'direct'}
    if event:
        result.update(earliest=event.isoformat(), latest=event.isoformat())
    if re.match(r'^\s*re\s*:', subject or '', re.I):
        result['kind'] = 'reply_unknown'; return result
    if not re.match(r'^\s*(?:fwd?|fw)\s*:', subject or '', re.I):
        return result
    result['kind'] = 'forwarded' if event else 'forwarded_unknown'
    if event:
        return result
    marker = r'(?:-{2,}\s*Forwarded message\s*-{2,}|Begin forwarded message:)'
    if len(re.findall(marker, text, re.I)) != 1:
        return result
    match = re.search(marker + r'\s*([\s\S]{0,1600})', text, re.I)
    values = re.findall(r'(?im)^\s*Date:\s*(.+)$', match[1] if match else '')
    if len(values) != 1:
        return result
    result['original_date'] = values[0].strip()
    # dateutil otherwise supplies this year's value for abbreviated headers.
    # A guessed year cannot establish ordering against another booking notice.
    if not re.search(r'\b(?:19|20)\d{2}\b', values[0]):
        return result
    try:
        from dateutil.parser import parse
        local = parse(values[0], fuzzy=False)
    except (ValueError, TypeError, OverflowError):
        return result
    if local.tzinfo is not None:
        return result
    lower = local.replace(tzinfo=timezone.utc) - timedelta(hours=14)
    upper = local.replace(tzinfo=timezone.utc) + timedelta(hours=12)
    if received and lower > received:
        return result
    result.update(kind='forwarded_timezone_unknown', earliest=lower.isoformat(),
                  latest=min(upper, received).isoformat() if received else upper.isoformat())
    return result


@dataclass
class AppliedBooking:
    build: BuildSegmentsResult
    canceled: int = 0
    is_cancellation: bool = False
    review_reason: str | None = None
    enrichment_audit: list | None = None

    @property
    def status(self):
        return MessageStatus.REVIEW_REQUIRED if self.review_reason or getattr(self.build, "held_unknown", 0) else MessageStatus.ACCEPTED

    def evidence(self, source: str, tier: str) -> dict:
        result = {
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
        if self.enrichment_audit:
            result["strict_enrichment"] = self.enrichment_audit
        return result


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
            from .booking_ledger import flight_scope
            if flight_scope(flight)['travel_date'] in {value.isoformat() for value in dates} and flight not in selected:
                selected.append(flight)
    return partial, selected


def _new_self_scopes(db, user_id, flights):
    """Capture only exact dated legs whose ownership is not established yet."""
    from .booking_ledger import booking_code, flight_scope, has_verified_self_observation

    scopes = {}
    for flight in flights:
        if getattr(flight, "ownership", None) != "self" or getattr(flight, "force_review", False):
            continue
        code, scope = booking_code(getattr(flight, "pnr", None)), flight_scope(flight)
        if not code or not all(scope.values()):
            continue
        key = (code, scope["travel_date"], scope["dep_airport"], scope["arr_airport"], scope["flight_number"])
        if key not in scopes and not has_verified_self_observation(db, user_id, code, scope):
            scopes[key] = flight
    return scopes


def _retained_flight(observation, *, ownership="unknown"):
    """Restore exactly one immutable fact set, never reparse or infer its times."""
    from .booking_ledger import _key, booking_code, event_time, flight_facts, flight_scope

    facts = observation.facts
    if (not isinstance(facts, dict) or facts.get("ownership") != ownership
            or observation.ownership != ownership
            or facts.get("force_review") or facts.get("user_decision")
            or not observation.source_message_id or observation.source_event_at is None):
        return None
    provenance = facts.get("time_provenance") or {}
    if (not isinstance(provenance, dict) or provenance.get("version") != 1
            or provenance.get("status") != "normalized"):
        return None
    restored = deepcopy(facts)
    try:
        for field in ("dep_time", "arr_time", "source_received_at", "mail_received_at"):
            if restored.get(field) is not None:
                restored[field] = datetime.fromisoformat(restored[field].replace("Z", "+00:00"))
        flight = SimpleNamespace(**restored)
        if (booking_code(flight.pnr) != observation.pnr
                or flight_scope(flight) != {
                    "travel_date": observation.travel_date, "dep_airport": observation.dep_airport,
                    "arr_airport": observation.arr_airport, "flight_number": observation.flight_number}
                or flight.dep_time.tzinfo is None or flight.arr_time.tzinfo is None
                or not 0 < (flight.arr_time - flight.dep_time).total_seconds() <= 48 * 3600
                or event_time(provenance["departure"]["utc"]) != event_time(flight.dep_time)
                or event_time(provenance["arrival"]["utc"]) != event_time(flight.arr_time)
                or provenance["departure"]["local"][:10] != observation.travel_date):
            return None
    except (AttributeError, KeyError, TypeError, ValueError):
        return None
    # The ledger canonicalizes the source event before calculating its key.
    # Requiring the old key prevents schema/default changes from producing a
    # second observation or silently modifying the original evidence.
    flight.source_received_at = event_time(observation.source_event_at)
    flight.force_review = False
    key = _key({"message": observation.source_message_id, "event_at": flight.source_received_at,
                "facts": flight_facts(flight)})
    return flight if key == observation.evidence_key else None


def _reconcile_new_self_scopes(db, user_id, scopes):
    """Project earlier unnamed notices once their exact leg gains self proof.

    Queries are scoped to this import's newly proven legs, never the mailbox or
    the whole account. Replay keeps the original unknown ownership: the normal
    ledger establishes the connection and applies all manual/cancellation holds.
    Its result deliberately does not change the current email's review status.
    """
    from ..models import BookingObservation
    from .booking_ledger import (cancellation_blocks_flight, flight_scope,
                                has_verified_self_observation, user_decision_for_flight)

    pending = {}
    for (code, day, dep, arr, number), proof in scopes.items():
        decision = user_decision_for_flight(db, user_id, proof)
        if (decision and (decision.get("status") in {"hold", "canceled"}
                          or decision.get("ownership") == "other")):
            continue
        if (not has_verified_self_observation(db, user_id, code, flight_scope(proof))
                or cancellation_blocks_flight(db, user_id, proof)):
            continue
        observations = db.query(BookingObservation).filter_by(
            user_id=user_id, pnr=code, travel_date=day, dep_airport=dep,
            arr_airport=arr, flight_number=number, ownership="unknown",
        ).order_by(BookingObservation.source_event_at.desc(), BookingObservation.id.desc()).limit(129).all()
        # Abnormally large/conflicting histories remain retained for review;
        # don't perform an unbounded import or pick an arbitrary partial set.
        if len(observations) > 128:
            continue
        for observation in observations:
            flight = _retained_flight(observation)
            if flight is not None:
                pending[observation.id] = (observation, flight)
        from .booking_enrichment import enabled
        if enabled(user_id):
            # Supplement only zero-padded equivalents (UA0123 / UA123) under
            # the same primary booking and dated route. Original exact-number
            # behavior above is unchanged. The ledger independently requires
            # strict original passenger proof before any new inheritance.
            from .builder import _normalize_flight_number
            equivalents = db.query(BookingObservation).filter_by(
                user_id=user_id, pnr=code, travel_date=day, dep_airport=dep,
                arr_airport=arr, ownership="unknown",
            ).order_by(BookingObservation.source_event_at.desc(), BookingObservation.id.desc()).limit(129).all()
            if len(equivalents) <= 128:
                for observation in equivalents:
                    if (observation.flight_number != number
                            and _normalize_flight_number(observation.flight_number) == _normalize_flight_number(number)):
                        flight = _retained_flight(observation)
                        # This additional replay must always use the strict
                        # fallback in the ledger. A missing-number legacy proof
                        # can make its older wildcard verifier true after the
                        # current batch is stored; that does not authorize this
                        # newly introduced replay path.
                        if (flight is not None and not has_verified_self_observation(
                                db, user_id, code, flight_scope(flight))):
                            pending[observation.id] = (observation, flight)
    return _replay_retained(db, user_id, pending)


def _reconcile_removed_self_scopes(db, user_id, scopes):
    """A removed other-passenger row may have blocked a real personal receipt.

    Only explicit self evidence is eligible across booking references. The
    removed leg supplies a bounded lookup scope, never passenger identity or
    aliases; all ownership and cancellation decisions still run in the builder.
    """
    from ..models import BookingObservation

    pending = {}
    for scope in scopes:
        if not all(scope.get(field) for field in ("travel_date", "dep_airport", "arr_airport", "flight_number")):
            continue
        observations = db.query(BookingObservation).filter_by(
            user_id=user_id, ownership="self", **scope,
        ).order_by(BookingObservation.source_event_at.desc(), BookingObservation.id.desc()).limit(129).all()
        if len(observations) > 128:
            continue
        for observation in observations:
            if not isinstance(observation.facts, dict) or observation.facts.get("source") in {
                    "travel_name_recovery", "user_review", "accepted_flight_share"}:
                continue
            flight = _retained_flight(observation, ownership="self")
            if flight is not None:
                pending[observation.id] = (observation, flight)
    return _replay_retained(db, user_id, pending)


def _merge_successful_replay(result, replay):
    result.inserted += replay.inserted
    result.updated += replay.updated
    result.deduped += replay.deduped
    result.affected_segment_ids.update(replay.affected_segment_ids)
    # The same affected trip can be rebuilt more than once, not added anew.
    result.trips = max(result.trips, replay.trips)


def _replay_retained(db, user_id, pending):
    result = BuildSegmentsResult()
    ordered = sorted(pending.values(), key=lambda item: (item[0].source_event_at, item[0].id))
    for observation, flight in ordered:
        replay = build_segments_and_trips_detailed(db, user_id, [flight],
            source_message_id=observation.source_message_id, source_event_at=observation.source_event_at)
        _merge_successful_replay(result, replay)
    return result


def apply_booking_message(db, user_id: int, parsed, *, source_message_id: str,
                          subject: str = "", plain_text: str = "", html: str = "",
                          received_at=None) -> AppliedBooking:
    from .booking_enrichment import enabled, current_source
    from .carrier_travel_recovery import enabled as carrier_enabled
    from .parser import PARSER_VERSION
    kwargs = dict(source_message_id=source_message_id, subject=subject,
                  plain_text=plain_text, html=html, received_at=received_at)
    if not (enabled(user_id) or carrier_enabled(user_id)):
        return _apply_booking_message(db, user_id, parsed, **kwargs)
    with current_source(db, user_id, source_message_id, PARSER_VERSION) as context:
        applied = _apply_booking_message(db, user_id, parsed, **kwargs)
        applied.enrichment_audit = list(context["audit"])
        return applied


def _apply_booking_message(db, user_id: int, parsed, *, source_message_id: str,
                          subject: str = "", plain_text: str = "", html: str = "",
                          received_at=None) -> AppliedBooking:
    from .parser import _extract_pnr

    text = visible_message_text(plain_text, html)
    time_text = booking_time_text(plain_text, html)
    event_at = booking_event_time(received_at, subject, time_text)
    flights = deepcopy(parsed.flights)
    provenance = booking_time_provenance(received_at, subject, time_text)
    from .parser import PARSER_VERSION
    for flight in flights:
        flight.source_received_at = event_at
        flight.mail_received_at = _date(received_at)
        flight.source_time_provenance = provenance
        flight.parser_version = PARSER_VERSION
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

    new_self_scopes = _new_self_scopes(db, user_id, flights) if not cancellation else {}
    result = build_segments_and_trips_detailed(
        db, user_id, flights, source_message_id=source_message_id,
        source_event_at=event_at,
    ) if flights else BuildSegmentsResult()
    _merge_successful_replay(result, _reconcile_new_self_scopes(db, user_id, new_self_scopes))
    if result.removed_leg_scopes:
        _merge_successful_replay(result, _reconcile_removed_self_scopes(db, user_id, result.removed_leg_scopes))
    if not review_reason and result.review_reasons:
        review_reason = result.review_reasons[0]
    return AppliedBooking(result, canceled, cancellation, review_reason)


def preserve_partial_evidence(previous, replacement) -> dict:
    """Retain prior partial facts when a normal parse replaces its outcome.

    Historical annotations are supporting records only. They cannot resolve a
    message, identify its passenger, or create a flight. A successful new partial
    extraction supplies the current annotation; older distinct facts stay here
    even if the feature is disabled or a later extraction fails.
    """
    previous = previous if isinstance(previous, dict) else {}
    result = dict(replacement)
    history = []
    for evidence in (previous, result):
        stored = evidence.get("partial_flight_evidence_history", [])
        for item in stored if isinstance(stored, list) else []:
            if isinstance(item, dict) and item not in history:
                history.append(deepcopy(item))
    prior = previous.get("partial_flight_evidence")
    if isinstance(prior, dict) and prior not in history:
        history.append(deepcopy(prior))
    current = result.get("partial_flight_evidence")
    history = [item for item in history if item != current]
    if history:
        result["partial_flight_evidence_history"] = history
    else:
        result.pop("partial_flight_evidence_history", None)
    return result


def set_message_outcome(message, applied: AppliedBooking, *, source: str, tier: str) -> None:
    existing_evidence = getattr(message, "parse_evidence", None)
    carrier_marker = existing_evidence.get("carrier_evidence") if isinstance(existing_evidence, dict) else None
    message.status = applied.status
    message.ignored = False
    message.parse_error = applied.review_reason or (
        "passenger_identity_unresolved" if getattr(applied.build, "held_unknown", 0)
        else "cancellation_notice" if applied.is_cancellation else None
    )
    message.parse_evidence = preserve_partial_evidence(existing_evidence, applied.evidence(source, tier))
    if carrier_marker is not None:
        message.parse_evidence = {**message.parse_evidence, "carrier_evidence": carrier_marker}
