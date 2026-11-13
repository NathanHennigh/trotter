"""Immutable booking evidence and conservative, replay-safe itinerary decisions.

The active segments are a projection. Nothing in this module deletes observations,
cancellation events, or the complete snapshots taken before projection changes.
"""

from __future__ import annotations

from contextlib import contextmanager
from copy import copy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
import json
import re

from sqlalchemy import inspect
from sqlalchemy.orm import Session

from ..models import BookingCancellation, BookingObservation, ItineraryHistory, Segment, Trip


def event_time(value):
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    if value.tzinfo:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _json_value(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _key(value):
    return sha256(json.dumps(_json_value(value), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def booking_code(value):
    return str(value or "").strip().upper() or None


def flight_scope(flight):
    departure = event_time(getattr(flight, "dep_time", None))
    local_date = (getattr(flight, "time_provenance", None) or (getattr(flight, "meta_json", None) or {}).get('time_provenance') or {}).get("departure_local_date")
    return {
        "travel_date": local_date or (departure.date().isoformat() if departure else None),
        "dep_airport": getattr(flight, "dep_airport", None),
        "arr_airport": getattr(flight, "arr_airport", None),
        "flight_number": str(getattr(flight, "flight_number", None) or "").replace(" ", "").upper() or None,
    }


def _same_leg(left, right, *, require_number=False):
    if not left.get("travel_date") or not right.get("travel_date"):
        return False
    if any(left.get(key) != right.get(key) for key in ("travel_date", "dep_airport", "arr_airport")):
        return False
    left_number, right_number = left.get("flight_number"), right.get("flight_number")
    return not require_number or not left_number or not right_number or left_number == right_number


def flight_facts(flight):
    names = (
        "dep_airport", "arr_airport", "dep_time", "arr_time", "airline", "flight_number",
        "pnr", "pnr_aliases", "source", "source_received_at", "confidence", "nonstop", "aircraft",
        "ownership", "passenger_names", "passenger_evidence", "force_review",
        "time_provenance", "source_time_provenance", "parser_version", "recovery_observation_ids",
        "reconciles_observation_ids", "mail_received_at",
        "document_provenance",
    )
    facts = {name: _json_value(getattr(flight, name, None)) for name in names}
    if getattr(flight, "source_leg", None):
        facts["source_leg"] = _json_value(flight.source_leg)
    if getattr(flight, "booking_lifecycle", None):
        facts["booking_lifecycle"] = _json_value(flight.booking_lifecycle)
    if getattr(flight, "booking_ticket", None):
        facts["booking_ticket"] = _json_value(flight.booking_ticket)
    return facts


def _row_snapshot(row):
    return {column.name: _json_value(getattr(row, column.name)) for column in row.__table__.columns}


def _save_snapshots(db, user_id, reason, snapshots):
    pending = {}
    for kind, row_id, before in snapshots:
        key = _key({"entity_type": kind, "entity_id": row_id, "snapshot": before, "reason": reason})
        pending[key] = (kind, row_id, before)
    if not pending:
        return 0
    for row in db.new:
        if isinstance(row, ItineraryHistory) and row.user_id == user_id:
            pending.pop(row.evidence_key, None)
    keys = list(pending)
    with db.no_autoflush:
        existing = db.query(ItineraryHistory.evidence_key).filter_by(user_id=user_id)
        for offset in range(0, len(keys), 500):
            for (key,) in existing.filter(ItineraryHistory.evidence_key.in_(keys[offset:offset + 500])):
                del pending[key]
    history = [
        ItineraryHistory(user_id=user_id, evidence_key=key, entity_type=kind,
                         entity_id=row_id, reason=reason, snapshot=before)
        for key, (kind, row_id, before) in pending.items()
    ]
    if history:
        db.add_all(history)
        # Import sessions disable autoflush. Expose preimages immediately without
        # flushing unrelated in-progress changes ahead of their normal boundary.
        db.flush(history)
    return len(history)


def _row_changed(row, original):
    for column in row.__table__.columns:
        value = getattr(row, column.name)
        previous = original[column.name]
        if isinstance(value, datetime):
            # PostgreSQL returns aware instants. The builder also uses naive UTC.
            if event_time(value) != event_time(previous):
                return True
        elif _json_value(value) != previous:
            return True
    return False


@contextmanager
def preserve_itinerary_changes(db, user_id, *, reason, trips=(), segments=()):
    """Retain the original rows only when this operation changes or deletes them.

    Callers supply owned, persisted rows. Capturing JSON before edits also covers
    nested metadata and intermediate flushes. History and edits commit together.
    """
    originals = [(kind, row, _row_snapshot(row))
                 for kind, rows in (("trip", trips), ("segment", segments)) for row in rows]
    yield
    _save_snapshots(db, user_id, reason, (
        (kind, before["id"], before) for kind, row, before in originals
        if row in db.deleted or inspect(row).deleted or _row_changed(row, before)
    ))


def snapshot_user_itinerary(db: Session, user_id: int, *, reason: str,
                            segment_ids=None, trip_ids=None) -> int:
    """Add complete, idempotent snapshots, including untouched legacy data.

    Called before builder operations, in the same transaction as their mutations.
    The historical IDs are plain values, so deleting/replacing live rows cannot
    cascade into the retained evidence.
    """
    trip_query = db.query(Trip).filter(Trip.user_id == user_id)
    segment_query = db.query(Segment).join(Trip).filter(Trip.user_id == user_id)
    if trip_ids is not None:
        trip_query = trip_query.filter(Trip.id.in_(trip_ids))
    if segment_ids is not None:
        segment_query = segment_query.filter(Segment.id.in_(segment_ids))
    added = _save_snapshots(db, user_id, reason, (
        (kind, row.id, _row_snapshot(row))
        for kind, rows in (("trip", trip_query.all()), ("segment", segment_query.all())) for row in rows
    ))
    db.flush()
    return added


def has_verified_self_observation(db, user_id, pnr, scope):
    if not pnr or not scope.get("travel_date"):
        return False
    observations = db.query(BookingObservation).filter(
        BookingObservation.user_id == user_id,
        BookingObservation.pnr == booking_code(pnr),
        BookingObservation.travel_date == scope["travel_date"],
        BookingObservation.ownership == "self",
    ).all()
    return any(not observation.facts.get("force_review")
               and observation.facts.get("user_decision", {}).get("status") not in {"canceled", "hold"}
               and _same_leg(scope, {
        "travel_date": observation.travel_date,
        "dep_airport": observation.dep_airport,
        "arr_airport": observation.arr_airport,
        "flight_number": observation.flight_number,
    }, require_number=True) for observation in observations)


def _can_reinstate(flight):
    meta = getattr(flight, "meta_json", None) or {}
    lifecycle = getattr(flight, "booking_lifecycle", None) or meta.get("booking_lifecycle") or {}
    ownership = getattr(flight, "ownership", None) or meta.get("ownership")
    return ownership == "self" and lifecycle.get("can_reinstate") is True


def _same_cancellation_leg(left, right):
    fields = ("travel_date", "dep_airport", "arr_airport", "flight_number")
    if not all(left.get(key) and right.get(key) for key in fields):
        return False
    def number(value):
        return re.sub(r"^([A-Z0-9]{2})0+(?=\d)", r"\1", value)
    return (all(left[key] == right[key] for key in ("travel_date", "dep_airport", "arr_airport"))
            and number(left["flight_number"]) == number(right["flight_number"]))


def _retained_reinstatement(db, user_id, code, scope, canceled_time, incoming_time):
    """A later reminder must not discard a real post-cancellation receipt."""
    rows = db.query(BookingObservation).filter_by(user_id=user_id, pnr=code,
        ownership="self", travel_date=scope["travel_date"], dep_airport=scope["dep_airport"],
        arr_airport=scope["arr_airport"]).all()
    return any(not (row.facts or {}).get("force_review")
        and ((row.facts or {}).get("booking_lifecycle") or {}).get("can_reinstate") is True
        and _same_cancellation_leg(scope, {"travel_date": row.travel_date,
            "dep_airport": row.dep_airport, "arr_airport": row.arr_airport,
            "flight_number": row.flight_number})
        and event_time(row.source_event_at) is not None
        and canceled_time < event_time(row.source_event_at) <= incoming_time for row in rows)


def cancellation_holds_flight(db, user_id, flight):
    """A post-departure notice holds recovery, without erasing an active row."""
    code = booking_code(getattr(flight, "pnr", None))
    if not code or user_decision_for_flight(db, user_id, flight, pnr=code):
        return False
    scope = flight_scope(flight)
    return any(_same_cancellation_leg(scope, held) for event in db.query(BookingCancellation).filter_by(
        user_id=user_id, pnr=code).all() for held in (event.facts or {}).get("review_scopes", []))


def reviewed_projection_holds_flight(db, user_id, flight):
    """A reviewed sparse-source retirement cannot be undone by replaying it.

    A numbered complete ticket from the same original remains eligible. The
    hold is only the reviewed unnumbered dated route, account, and source.
    """
    if getattr(flight, "flight_number", None) or user_decision_for_flight(db, user_id, flight):
        return False
    scope = flight_scope(flight)
    source = getattr(flight, "source_message_id", None)
    if not source:
        return False
    for row in db.query(ItineraryHistory).filter_by(user_id=user_id,
            entity_type="projection_hold", reason="reviewed_unsupported_projection"):
        hold = row.snapshot or {}
        if (source in hold.get("source_message_ids", [])
                and booking_code(getattr(flight, "pnr", None)) == booking_code(hold.get("pnr"))
                and scope == hold.get("scope")):
            return True
    return False


def cancellation_blocks_flight(db, user_id, flight, *, source_event_at=None, pnr=None):
    code = booking_code(pnr if pnr is not None else getattr(flight, "pnr", None))
    if not code:
        return False
    decision = user_decision_for_flight(db, user_id, flight, pnr=code)
    if decision:
        if decision.get("status") == "canceled":
            return True
        if decision.get("status") == "active" and decision.get("ownership") == "self":
            return False
    scope = flight_scope(flight)
    incoming_time = event_time(source_event_at or getattr(flight, "source_received_at", None))
    cancellations = db.query(BookingCancellation).filter(
        BookingCancellation.user_id == user_id, BookingCancellation.pnr == code,
    ).all()
    for cancellation in cancellations:
        strict = (cancellation.facts or {}).get("strict_lifecycle", False)
        if not any(_same_cancellation_leg(scope, canceled_scope) if strict else _same_leg(scope, canceled_scope)
                   for canceled_scope in ((cancellation.facts or {}).get("personal_scopes", cancellation.scopes)
                                          if strict else cancellation.scopes)):
            continue
        canceled_time = event_time(cancellation.source_event_at)
        classified = bool(getattr(flight, "booking_lifecycle", None)
                          or (getattr(flight, "meta_json", None) or {}).get("booking_lifecycle"))
        if (incoming_time and canceled_time and incoming_time > canceled_time
                and (not (strict or classified) or _can_reinstate(flight)
                     or _retained_reinstatement(db, user_id, code, scope, canceled_time, incoming_time))):
            continue
        return True
    return False


@dataclass
class ObservationDecision:
    flights: list = field(default_factory=list)
    held_other: int = 0
    held_unknown: int = 0
    blocked_cancellation: int = 0
    removed_other: int = 0
    affected_trip_ids: set = field(default_factory=set)
    removed_leg_scopes: list[dict] = field(default_factory=list)
    review_reasons: list[str] = field(default_factory=list)
    superseded: int = 0
    retired_superseded: int = 0
    held_ticket_retirements: int = 0


def record_flight_observations(db, user_id, flights, *, source_message_id=None, source_event_at=None, force_review=False):
    """Record all facts before deciding which may enter the active itinerary.

    Direct legacy builder calls without a message ID retain their existing unknown
    ownership behavior. Message imports require self evidence or an exact dated-leg
    link to previously verified self evidence. OTHER never inherits ownership.
    """
    decision = ObservationDecision()
    prepared = []
    for original in flights:
        flight = copy(original)
        ownership = getattr(flight, "ownership", "unknown") or "unknown"
        if ownership not in {"self", "other", "unknown"}:
            ownership = "unknown"
        flight.ownership = ownership
        flight.force_review = force_review or bool(getattr(flight, "force_review", False))
        timestamp = event_time(source_event_at or getattr(flight, "source_received_at", None))
        if timestamp:
            flight.source_received_at = timestamp
        flight.source_message_id = source_message_id
        scope = flight_scope(flight)
        facts = flight_facts(flight)
        evidence_key = _key({"message": source_message_id, "event_at": timestamp, "facts": facts})
        observation = db.query(BookingObservation).filter_by(user_id=user_id, evidence_key=evidence_key).first()
        if observation is None:
            observation = BookingObservation(
                user_id=user_id, evidence_key=evidence_key, source_message_id=source_message_id,
                source_event_at=timestamp, pnr=booking_code(getattr(flight, "pnr", None)),
                ownership=ownership, facts=facts, **scope,
            )
            db.add(observation)
            db.flush()
        flight.observation_id = observation.id
        from .travel_inbox import retain_observation
        retain_observation(db, user_id, observation)
        prepared.append(flight)

    from .booking_ticket_lifecycle import reconcile_ticket_revisions, superseded_ticket_flight
    affected, retired, held_retirements = reconcile_ticket_revisions(db, user_id, prepared)
    decision.affected_trip_ids.update(affected)
    decision.retired_superseded = retired
    decision.held_ticket_retirements = held_retirements
    protected_other_trip_ids = None
    for flight in prepared:
        pnr = booking_code(getattr(flight, "pnr", None))
        scope = flight_scope(flight)
        if getattr(flight, "ticket_successor_conflict", False):
            decision.held_unknown += 1
            if "competing_ticket_successors" not in decision.review_reasons:
                decision.review_reasons.append("competing_ticket_successors")
            continue
        if flight.force_review:
            decision.held_unknown += 1
            continue
        if ((getattr(flight, "booking_lifecycle", None) or {}).get("kind") == "cancellation"
                and any(_same_cancellation_leg(scope, canceled) for row in
                    db.query(BookingCancellation).filter_by(user_id=user_id, pnr=pnr,
                        source_message_id=source_message_id).all() for canceled in row.scopes)):
            # A resolved cancellation is retained evidence, never a new ticket.
            # Unknown/other passenger scopes do not gain personal authority.
            decision.blocked_cancellation += 1
            continue
        user_decision = user_decision_for_flight(db, user_id, flight)
        if user_decision:
            if user_decision["status"] == "canceled":
                decision.blocked_cancellation += 1
                continue
            if user_decision["status"] == "hold":
                decision.held_unknown += 1
                continue
            flight.ownership = user_decision["ownership"]
        verified = has_verified_self_observation(db, user_id, pnr, scope)
        if user_decision and user_decision["ownership"] == "other":
            verified = False
        if flight.ownership == "other":
            decision.held_other += 1
            # Explicit incompatible passenger evidence may correct a legacy import,
            # but cannot erase independently verified self travel on the same flight.
            if pnr and not verified:
                candidates = db.query(Segment).join(Trip).filter(Trip.user_id == user_id, Segment.pnr == pnr).all()
                for segment in candidates:
                    if _same_leg(scope, flight_scope(segment), require_number=True):
                        # Automatic passenger evidence has no authority to undo
                        # explicit ownership, grouping or sharing choices. An
                        # exact active user OTHER decision retains its existing
                        # correction authority; it is not inferred from email.
                        explicit_other = (user_decision and user_decision.get("ownership") == "other"
                                          and user_decision.get("status") == "active")
                        if not explicit_other:
                            if protected_other_trip_ids is None:
                                from .builder import _protected_trip_ids
                                owned = db.query(Segment).join(Trip).filter(Trip.user_id == user_id).all()
                                protected_other_trip_ids = _protected_trip_ids(db, user_id, segments=owned)
                                protected_other_trip_ids.update(row.trip_id for row in owned
                                    if any((row.meta_json or {}).get(key)
                                           for key in ("manual", "user_edited", "personal_note")))
                            if segment.trip_id in protected_other_trip_ids:
                                if "protected_other_passenger_conflict" not in decision.review_reasons:
                                    decision.review_reasons.append("protected_other_passenger_conflict")
                                continue
                        snapshot_user_itinerary(db, user_id, reason="explicit_other_passenger",
                                                segment_ids={segment.id}, trip_ids={segment.trip_id})
                        decision.affected_trip_ids.add(segment.trip_id)
                        removed_scope = flight_scope(segment)
                        if removed_scope not in decision.removed_leg_scopes:
                            decision.removed_leg_scopes.append(removed_scope)
                        db.delete(segment)
                        db.flush()
                        decision.removed_other += 1
            continue
        if superseded_ticket_flight(db, user_id, flight):
            decision.superseded += 1
            continue
        from .booking_ticket_lifecycle import holds_new_ticket_projection
        if holds_new_ticket_projection(db, user_id, flight):
            decision.held_unknown += 1
            if "ticket_reconciliation_not_enabled" not in decision.review_reasons:
                decision.review_reasons.append("ticket_reconciliation_not_enabled")
            continue
        if reviewed_projection_holds_flight(db, user_id, flight):
            decision.held_unknown += 1
            if "reviewed_unsupported_projection" not in decision.review_reasons:
                decision.review_reasons.append("reviewed_unsupported_projection")
            continue
        if cancellation_holds_flight(db, user_id, flight):
            decision.held_unknown += 1
            if "post_departure_cancellation_conflict" not in decision.review_reasons:
                decision.review_reasons.append("post_departure_cancellation_conflict")
            continue
        if cancellation_blocks_flight(db, user_id, flight):
            decision.blocked_cancellation += 1
            continue
        enrichment = None
        if flight.ownership == "unknown" and source_message_id:
            from .booking_enrichment import enabled, evaluate, record_audit
            # Preserve the established import/correction path completely. The
            # candidate only supplies additional authority where that path held
            # an unnamed notice; it never vetoes an existing verified link.
            if enabled(user_id) and not verified:
                enrichment = evaluate(db, user_id, flight)
                record_audit(db, user_id, enrichment, flight.observation_id)
                verified = enrichment.allowed
            if not verified:
                from .carrier_travel_recovery import enabled as carrier_enabled, evaluate as evaluate_carrier
                if carrier_enabled(user_id):
                    carrier_decision = evaluate_carrier(db, user_id, flight)
                    record_audit(db, user_id, carrier_decision, flight.observation_id)
                    if carrier_decision.allowed:
                        enrichment = carrier_decision
                        verified = True
            if not verified:
                decision.held_unknown += 1
                continue
        if flight.ownership == "unknown" and verified:
            flight.ownership = "self"
            if source_message_id:
                # Corroboration proves this primary booking's exact dated leg,
                # not every other booking code in an unnamed source. Preserve
                # those alias claims in the immutable observation above, but
                # do not project them as relationships to this personal flight.
                # Independently named/manual aliases already on a row remain.
                flight.pnr_aliases = []
            original = getattr(flight, "passenger_evidence", None) or []
            flight.passenger_evidence = (list(original) if isinstance(original, list) else [original]) + [
                ({"reason": enrichment.reason,
                  "proof_observation_ids": list(enrichment.proof_observation_ids),
                  **({"carrier_evidence_ids": list(enrichment.carrier_evidence_ids)}
                     if getattr(enrichment, "carrier_evidence_ids", ()) else {})}
                 if enrichment else {"reason": "verified_same_booking_dated_leg"}),
            ]
        decision.flights.append(flight)
    return decision


def record_cancellation(db, user_id, pnr, *, source_message_id=None, source_event_at=None,
                        flights=None, strict_lifecycle=False):
    """Persist cancellation even when no active matching segment has arrived yet.

    Empty scopes retain unresolved evidence without cancelling every lifetime use
    of a PNR. Explicit dated legs or existing booking evidence establish scope.
    """
    pnr = booking_code(pnr)
    timestamp = event_time(source_event_at)
    supplied_flights = list(flights or [])
    scopes = []
    personal_scopes = []
    review_scopes = []
    for flight in supplied_flights:
        if booking_code(getattr(flight, "pnr", None)) not in {None, pnr}:
            continue
        scope = flight_scope(flight)
        if strict_lifecycle:
            # A partial route cannot establish an exact canceled leg. Passenger
            # authority is tracked separately from the retained booking state.
            if getattr(flight, "force_review", False) or not all(scope.values()):
                continue
            departure = event_time(getattr(flight, "dep_time", None))
            if not timestamp or not departure:
                continue
            if timestamp >= departure:
                if getattr(flight, "ownership", None) == "self" and scope not in review_scopes:
                    review_scopes.append(scope)
                continue
            if getattr(flight, "ownership", None) == "self" and scope not in personal_scopes:
                personal_scopes.append(scope)
        if scope["travel_date"] and scope not in scopes:
            scopes.append(scope)
    if not scopes and not strict_lifecycle:
        candidates = db.query(Segment).join(Trip).filter(Trip.user_id == user_id, Segment.pnr == pnr).all()
        for segment in candidates:
            scope = flight_scope(segment)
            # No timestamp means legacy cancellation API: its scope is the current
            # stored booking. With a timestamp, future confirmations are protected.
            current_time = event_time((segment.meta_json or {}).get("source_received_at"))
            if timestamp and current_time and current_time > timestamp:
                continue
            if scope not in scopes:
                scopes.append(scope)
    facts = {"flights": [flight_facts(flight) for flight in supplied_flights], "scope_resolved": bool(scopes)}
    if strict_lifecycle:
        # A fully specified unnamed/other booking can be canceled in retained
        # inbox evidence without authorizing changes to personal flight history.
        facts.update(strict_lifecycle=True, review_scopes=review_scopes,
                     personal_scopes=personal_scopes)
    key = _key({"message": source_message_id, "pnr": pnr, "event_at": timestamp, "scopes": scopes, "facts": facts})
    existing = db.query(BookingCancellation).filter_by(user_id=user_id, evidence_key=key).first()
    if existing:
        _mark_cancellation_conflicts(db, user_id, existing)
        return existing
    cancellation = BookingCancellation(user_id=user_id, evidence_key=key, source_message_id=source_message_id,
                                       source_event_at=timestamp, pnr=pnr, scopes=scopes, facts=facts)
    db.add(cancellation)
    db.flush()
    _mark_cancellation_conflicts(db, user_id, cancellation)
    return cancellation


def _same_cancellation_conflict(left, right):
    """Compare the exact notice while treating equivalent UTC instants alike."""
    if not isinstance(left, dict) or not isinstance(right, dict):
        return False

    def normalized(value):
        result = dict(value)
        timestamp = event_time(result.get("source_event_at"))
        if timestamp is not None:
            result["source_event_at"] = _json_value(timestamp)
        # Invalid/missing values retain their exact identity, never becoming a
        # shared None sentinel or acquiring authority from a valid timestamp.
        return result

    return normalized(left) == normalized(right)


def _mark_cancellation_conflicts(db, user_id, cancellation):
    """Preserved historical projections must expose their unresolved notice."""
    from .booking_projection_context import can_retire_new_projection
    cancellation.retired_conflict_segment_ids = []
    scopes = (cancellation.facts or {}).get("review_scopes", [])
    if not scopes:
        return
    from .builder import _protected_trip_ids
    protected_trip_ids = _protected_trip_ids(db, user_id)
    affected = set()
    for segment in db.query(Segment).join(Trip).filter(Trip.user_id == user_id,
            Segment.pnr == cancellation.pnr).all():
        meta = segment.meta_json or {}
        if (meta.get("source") in {"manual", "user_review", "accepted_flight_share", "flight_share"}
                or user_decision_for_flight(db, user_id, segment)
                or not any(_same_cancellation_leg(flight_scope(segment), scope) for scope in scopes)):
            continue
        if can_retire_new_projection(db, user_id, segment, protected_trip_ids=protected_trip_ids):
            snapshot_user_itinerary(db, user_id, reason="post_departure_conflict_new_projection",
                                    segment_ids={segment.id}, trip_ids={segment.trip_id})
            cancellation.retired_conflict_segment_ids.append(segment.id)
            affected.add(segment.trip_id)
            db.delete(segment)
            continue
        conflict = {"reason": "post_departure_cancellation_conflict", "pnr": cancellation.pnr,
            "source_message_id": cancellation.source_message_id,
            "source_event_at": _json_value(event_time(cancellation.source_event_at)), "scope": flight_scope(segment)}
        conflicts = list(meta.get("booking_conflicts") or [])
        if not any(_same_cancellation_conflict(existing, conflict) for existing in conflicts):
            snapshot_user_itinerary(db, user_id, reason="before_cancellation_conflict_annotation",
                                    segment_ids={segment.id}, trip_ids={segment.trip_id})
            segment.meta_json = {**meta, "booking_conflicts": [*conflicts, conflict]}
    db.flush()
    for trip_id in affected:
        trip = db.get(Trip, trip_id)
        remaining = db.query(Segment).filter_by(trip_id=trip_id).all()
        if not remaining:
            db.delete(trip)
        else:
            trip.start_ts = min(event_time(row.dep_time) for row in remaining)
            trip.end_ts = max(event_time(row.arr_time) for row in remaining)
    db.flush()


def cancellation_scope_resolved(db, user_id, pnr, source_message_id):
    events = db.query(BookingCancellation).filter_by(
        user_id=user_id, pnr=booking_code(pnr), source_message_id=source_message_id,
    ).all()
    return any(event.scopes for event in events)


def user_decision_for_flight(db, user_id, flight, *, pnr=None):
    scope = flight_scope(flight)
    if not scope["travel_date"]:
        return None
    observations = db.query(BookingObservation).filter_by(
        user_id=user_id, pnr=booking_code(pnr if pnr is not None else getattr(flight, "pnr", None)),
        travel_date=scope["travel_date"],
    ).order_by(BookingObservation.id.desc()).all()
    for observation in observations:
        decision = observation.facts.get("user_decision")
        if decision and _same_leg(scope, {
            "travel_date": observation.travel_date, "dep_airport": observation.dep_airport,
            "arr_airport": observation.arr_airport, "flight_number": observation.flight_number,
        }, require_number=True):
            return decision
    return None


def record_user_decision(db, user_id, flight, *, ownership="self", status="active", reason="User confirmed travel",
                         source_observation_id=None):
    """Persist an explicit user correction; email replay cannot override it.

    The caller must obtain the user's decision. This is deliberately separate from
    inferred parser evidence and changes only the exact booking and dated flight.
    """
    if ownership not in {"self", "other", "unknown"} or status not in {"active", "canceled", "hold"}:
        raise ValueError("Invalid booking decision")
    scope = flight_scope(flight)
    if not scope["travel_date"] or not scope["dep_airport"] or not scope["arr_airport"]:
        raise ValueError("A user decision requires a dated flight route")
    if source_observation_id is not None:
        from .builder import _normalize_flight_number
        with db.no_autoflush:
            source = db.query(BookingObservation).filter_by(id=source_observation_id, user_id=user_id).first()
        if source is None:
            raise ValueError("Source booking observation not found for this user")
        source_scope = {
            "travel_date": source.travel_date,
            "dep_airport": booking_code(source.dep_airport),
            "arr_airport": booking_code(source.arr_airport),
            "flight_number": _normalize_flight_number(source.flight_number),
        }
        expected_scope = {**scope, "dep_airport": booking_code(scope["dep_airport"]),
                          "arr_airport": booking_code(scope["arr_airport"]),
                          "flight_number": _normalize_flight_number(scope["flight_number"])}
        if (source_scope != expected_scope
                or booking_code(source.pnr) != booking_code(getattr(flight, "pnr", None))):
            raise ValueError("Source booking observation must match this exact booking and dated flight")
    snapshot_user_itinerary(db, user_id, reason="before_user_booking_decision")
    facts = flight_facts(flight)
    facts["user_decision"] = {"ownership": ownership, "status": status, "reason": reason}
    if source_observation_id is not None:
        facts["user_decision"]["source_observation_id"] = source_observation_id
    now = datetime.now(timezone.utc)
    observation = BookingObservation(
        user_id=user_id, evidence_key=_key({"decision": facts, "at": now}),
        source_message_id=None, source_event_at=now, pnr=booking_code(getattr(flight, "pnr", None)),
        ownership=ownership, facts=facts, **scope,
    )
    db.add(observation)
    db.flush()
    from .travel_inbox import retain_user_decision
    retain_user_decision(db, user_id, observation)
    return observation
