"""Immutable booking evidence and conservative, replay-safe itinerary decisions.

The active segments are a projection. Nothing in this module deletes observations,
cancellation events, or the complete snapshots taken before projection changes.
"""

from __future__ import annotations

from copy import copy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
import json

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
    return {
        "travel_date": departure.date().isoformat() if departure else None,
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
    )
    return {name: _json_value(getattr(flight, name, None)) for name in names}


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
    trips, segments = trip_query.all(), segment_query.all()
    keys = {key for (key,) in db.query(ItineraryHistory.evidence_key).filter(ItineraryHistory.user_id == user_id).all()}
    added = 0
    for kind, rows in (("trip", trips), ("segment", segments)):
        for row in rows:
            snapshot = {column.name: _json_value(getattr(row, column.name)) for column in row.__table__.columns}
            key = _key({"entity_type": kind, "entity_id": row.id, "snapshot": snapshot, "reason": reason})
            if key in keys:
                continue
            db.add(ItineraryHistory(user_id=user_id, evidence_key=key, entity_type=kind,
                                    entity_id=row.id, reason=reason, snapshot=snapshot))
            keys.add(key)
            added += 1
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
        if not any(_same_leg(scope, canceled_scope) for canceled_scope in cancellation.scopes):
            continue
        canceled_time = event_time(cancellation.source_event_at)
        if incoming_time and canceled_time and incoming_time > canceled_time:
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

    for flight in prepared:
        pnr = booking_code(getattr(flight, "pnr", None))
        scope = flight_scope(flight)
        if flight.force_review:
            decision.held_unknown += 1
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
                        snapshot_user_itinerary(db, user_id, reason="explicit_other_passenger",
                                                segment_ids={segment.id}, trip_ids={segment.trip_id})
                        decision.affected_trip_ids.add(segment.trip_id)
                        db.delete(segment)
                        db.flush()
                        decision.removed_other += 1
            continue
        if cancellation_blocks_flight(db, user_id, flight):
            decision.blocked_cancellation += 1
            continue
        if flight.ownership == "unknown" and source_message_id and not verified:
            decision.held_unknown += 1
            continue
        if flight.ownership == "unknown" and verified:
            flight.ownership = "self"
            original = getattr(flight, "passenger_evidence", None) or []
            flight.passenger_evidence = (list(original) if isinstance(original, list) else [original]) + [
                {"reason": "verified_same_booking_dated_leg"},
            ]
        decision.flights.append(flight)
    return decision


def record_cancellation(db, user_id, pnr, *, source_message_id=None, source_event_at=None, flights=None):
    """Persist cancellation even when no active matching segment has arrived yet.

    Empty scopes retain unresolved evidence without cancelling every lifetime use
    of a PNR. Explicit dated legs or existing booking evidence establish scope.
    """
    pnr = booking_code(pnr)
    timestamp = event_time(source_event_at)
    supplied_flights = list(flights or [])
    scopes = []
    for flight in supplied_flights:
        if booking_code(getattr(flight, "pnr", None)) not in {None, pnr}:
            continue
        scope = flight_scope(flight)
        if scope["travel_date"] and scope not in scopes:
            scopes.append(scope)
    if not scopes:
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
    key = _key({"message": source_message_id, "pnr": pnr, "event_at": timestamp, "scopes": scopes, "facts": facts})
    existing = db.query(BookingCancellation).filter_by(user_id=user_id, evidence_key=key).first()
    if existing:
        return existing
    cancellation = BookingCancellation(user_id=user_id, evidence_key=key, source_message_id=source_message_id,
                                       source_event_at=timestamp, pnr=pnr, scopes=scopes, facts=facts)
    db.add(cancellation)
    db.flush()
    return cancellation


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
