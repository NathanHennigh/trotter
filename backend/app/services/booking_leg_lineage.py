"""Match parser corrections to the same original document's flight block.

A document-local fingerprint is independent of parsed dates and airports. It is
never a cross-message booking ID and never authorizes passenger inference.
Old records without this pointer require a separately reviewed repair.
"""
from __future__ import annotations

from dataclasses import dataclass
import re

from ..models import BookingObservation, Segment, Trip, User
from .booking_ledger import booking_code, event_time
from .booking_reconciliation import ambiguous, matches, original_source


def enabled(user_id=None):
    from .flight_import_rollout import enabled as account_enabled
    return account_enabled("BOOKING_LEG_RECONCILIATION_ENABLED", user_id)


def key(value):
    if not isinstance(value, dict) or value.get("version") != 1 or value.get("ambiguous"):
        return None
    digest = value.get("key")
    return digest if isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest) else None


def _revision(facts):
    value = facts.get("parser_version")
    return value if type(value) is int and value > 0 else 0


def _schedule(row):
    facts = row.facts or {}
    return (row.dep_airport, row.arr_airport, row.flight_number,
            event_time(facts.get("dep_time")), event_time(facts.get("arr_time")))


@dataclass
class LegMatch:
    segment: object | None = None
    status: str = "none"
    overwrite: bool = False


def find(db, user_id, flight):
    """Read-only decision; the normal builder still performs all protections.

Only observations from the *same original* and fingerprint can bridge a date
or airport correction. A newer parser revision can correct that interpretation;
reprocessing an older revision cannot put it back. Source chronology still
protects later schedule messages. Queries are scoped to one account/document.
"""
    if not getattr(flight, "source_leg", None):
        return LegMatch()
    correction_enabled = enabled(user_id)
    if not correction_enabled:
        # Parsing can establish an overnight connection even when automatic
        # correction is disabled. Keep its duplicate safety guard active, but
        # grant no correction authority and avoid lookups for other flights.
        proof = (getattr(flight, 'time_provenance', None) or {}).get('date_evidence') or {}
        if (proof.get('departure_evidence') or {}).get('kind') != 'printed_connection':
            return LegMatch()
    pointer = key(flight.source_leg)
    source = getattr(flight, "source_message_id", None)
    current = db.get(BookingObservation, getattr(flight, "observation_id", None))
    if not correction_enabled:
        if (current and current.user_id == user_id and current.source_message_id == source
                and original_source(current) and getattr(flight, 'ownership', None) == 'self'
                and _legacy_connection_collision(db, user_id, current)):
            return LegMatch(status='held')
        return LegMatch()
    if current and not original_source(current):
        return LegMatch()
    if (not source or not current or current.user_id != user_id
            or current.source_message_id != source or not original_source(current)):
        return LegMatch(status="held")
    if not pointer:
        # Ambiguous document pointers grant no extra identity authority. They
        # must not stop an otherwise valid first import of an explicit leg.
        # A later parser revision touching an older linked ambiguous block is
        # held for review, rather than silently adding a replacement dated leg.
        raw_key = flight.source_leg.get("key")
        if flight.source_leg.get("ambiguous") and isinstance(raw_key, str) and re.fullmatch(r"[0-9a-f]{64}", raw_key):
            prior = db.query(BookingObservation).filter_by(user_id=user_id, source_message_id=source).limit(501).all()
            if len(prior) > 500:
                return LegMatch(status="held")
            ids = {row.id for row in prior if (row.facts or {}).get('source_leg', {}).get('key') == raw_key
                   and _revision(row.facts or {}) < _revision(current.facts or {})}
            if ids and any(ids.intersection((s.meta_json or {}).get('observation_ids') or [])
                           for s in db.query(Segment).join(Trip).filter(Trip.user_id == user_id)):
                return LegMatch(status="held")
            return LegMatch()
        return LegMatch(status="held")
    if key((current.facts or {}).get("source_leg")) != pointer:
        return LegMatch(status="held")
    user = db.get(User, user_id)
    names = [user.name, *(user.travel_name_aliases or [])] if user else []
    if getattr(flight, 'ownership', None) == 'self' and _legacy_connection_collision(db, user_id, current):
        return LegMatch(status='held')
    if current.ownership != "self" or not current.pnr:
        # Carrier/name corroboration keeps its established exact-leg path. It
        # cannot gain permission to correct a different route/date through here.
        return LegMatch()
    if (ambiguous(current) or not matches(current, names) or not _revision(current.facts or {})
            or (getattr(flight, 'time_provenance', None) or {}).get('status') != 'normalized'):
        return LegMatch(status='held')
    rows = db.query(BookingObservation).filter_by(user_id=user_id, source_message_id=source).limit(501).all()
    if len(rows) > 500:
        return LegMatch(status="held")
    uncertain_ids = {row.id for row in rows if (row.facts or {}).get('source_leg', {}).get('key') == pointer
                     and not key((row.facts or {}).get('source_leg'))}
    # A prior interpretation of this very document may predate fingerprints.
    # It cannot authorize a cross-date correction, but its linked active flight
    # must not be silently duplicated either. Leave an explicit legacy review.
    from .builder import _normalize_flight_number
    uncertain_ids.update(row.id for row in rows if not (row.facts or {}).get('source_leg')
        and booking_code(row.pnr) == booking_code(current.pnr)
        and _normalize_flight_number(row.flight_number) == _normalize_flight_number(current.flight_number))
    if uncertain_ids and any(uncertain_ids.intersection((segment.meta_json or {}).get('observation_ids') or [])
                             and _segment_schedule(segment) != _schedule(current)
                             for segment in db.query(Segment).join(Trip).filter(Trip.user_id == user_id)):
        return LegMatch(status="held")
    rows = [row for row in rows if original_source(row) and key((row.facts or {}).get("source_leg")) == pointer]
    revision = max((_revision(row.facts or {}) for row in rows), default=0)
    latest = [row for row in rows if _revision(row.facts or {}) == revision]
    if (any(ambiguous(row) or not matches(row, names) or row.ownership != "self" for row in latest)
            or len({_schedule(row) for row in latest}) != 1
            or any(booking_code(row.pnr) != booking_code(current.pnr) for row in rows)
            or len({event_time(row.source_event_at) for row in rows}) != 1):
        return LegMatch(status="held")
    if _revision(current.facts or {}) < revision:
        return LegMatch(status="stale")

    ids = {row.id for row in rows}
    segments = db.query(Segment).join(Trip).filter(Trip.user_id == user_id).all()
    linked = [segment for segment in segments if ids.intersection((segment.meta_json or {}).get("observation_ids") or [])]
    if len(linked) > 1:
        return LegMatch(status="held")
    if not linked:
        return LegMatch()
    segment = linked[0]
    meta = segment.meta_json or {}
    from .booking_ledger import user_decision_for_flight, cancellation_blocks_flight
    from .travel_name_recovery import flight_from, recovery_blocked, active_shares_for_item
    from ..models import TravelInboxEvidence, TravelInboxItem, TravelInboxAssignment, FlightShare
    if meta.get("source") in {"manual", "user_review", "accepted_flight_share", "flight_share"}:
        return LegMatch(status="held")
    if any(segment.id in (share.accepted_segment_ids or []) for share in db.query(FlightShare).filter_by(recipient_user_id=user_id).all()):
        return LegMatch(status="held")
    segment_codes = {booking_code(segment.pnr), *(booking_code(code) for code in meta.get('pnr_aliases') or [])}
    if any(user_decision_for_flight(db, user_id, segment, pnr=code)
           or cancellation_blocks_flight(db, user_id, segment, pnr=code) for code in segment_codes if code):
        return LegMatch(status="held")
    for row in rows:
        previous = flight_from(row)
        codes = {previous.pnr, *(booking_code(code) for code in previous.pnr_aliases or [])}
        if (any(user_decision_for_flight(db, user_id, previous, pnr=code) for code in codes if code)
                or recovery_blocked(db, user_id, row, previous, names)):
            return LegMatch(status="held")
    items = db.query(TravelInboxItem).join(TravelInboxEvidence).filter(
        TravelInboxItem.user_id == user_id, TravelInboxEvidence.observation_id.in_(ids)).all()
    if any(db.get(TravelInboxAssignment, item.id) or active_shares_for_item(db, user_id, item.id) for item in items):
        return LegMatch(status="held")
    if booking_code(segment.pnr) != booking_code(current.pnr):
        return LegMatch(status="held")
    # Do not create another active copy by correcting onto an existing flight.
    # A reviewed merge must preserve the existing record and its references.
    if any(other.id != segment.id and _segment_schedule(other) == _schedule(current) for other in segments):
        return LegMatch(status="held")
    current_time = event_time(meta.get("source_received_at"))
    incoming_time = event_time(current.source_event_at)
    overwrite = bool(incoming_time and (not current_time or incoming_time >= current_time))
    if not overwrite and _segment_schedule(segment) != _schedule(current):
        return LegMatch(status="stale")
    return LegMatch(segment=segment, status="linked", overwrite=overwrite)


def _segment_schedule(segment):
    return (segment.dep_airport, segment.arr_airport, segment.flight_number,
            event_time(segment.dep_time), event_time(segment.arr_time))


def _legacy_connection_collision(db, user_id, current):
    """Recognize an old connection stamped with its outbound's heading date.

This only blocks a speculative duplicate; it never rewrites the legacy row.
The printed connection and original preceding block must establish both dates.
Normalized flights and other bookings cannot trigger this legacy guard.
"""
    from .builder import _normalize_flight_number
    proof = ((current.facts or {}).get('time_provenance') or {}).get('date_evidence') or {}
    connection = proof.get('departure_evidence') or {}
    if (proof.get('status') != 'verified' or connection.get('kind') != 'printed_connection'
            or connection.get('status') != 'verified' or not connection.get('previous_leg_key')):
        return False
    # The parser retains this verified departure even if deduplication chooses
    # another (held) representation of the preceding leg. Holding a potential
    # duplicate does not require promoting that preceding leg into the archive.
    recorded_day = connection.get('previous_departure_date')
    days = {recorded_day} if (isinstance(recorded_day, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', recorded_day)
                              and recorded_day != current.travel_date) else set()
    prior = db.query(BookingObservation).filter_by(user_id=user_id, source_message_id=current.source_message_id,
        pnr=current.pnr, arr_airport=current.dep_airport).limit(501).all()
    if len(prior) > 500:
        return True
    days.update(row.travel_date for row in prior if key((row.facts or {}).get('source_leg')) == connection['previous_leg_key']
            and ((row.facts or {}).get('time_provenance') or {}).get('status') == 'normalized'
            and row.travel_date != current.travel_date)
    if not days:
        return False
    for segment in db.query(Segment).join(Trip).filter(Trip.user_id == user_id, Segment.pnr == current.pnr,
            Segment.dep_airport == current.dep_airport, Segment.arr_airport == current.arr_airport):
        if (not (segment.meta_json or {}).get('time_provenance')
                and _normalize_flight_number(segment.flight_number) == _normalize_flight_number(current.flight_number)
                and event_time(segment.dep_time).date().isoformat() in days):
            return True
    return False
