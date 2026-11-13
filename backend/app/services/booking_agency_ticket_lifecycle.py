"""Exact, named issued-ticket schedule revisions without inventing a PNR.

This is a read-only decision. The builder keeps its ordinary mutation,
protection, snapshot and trip-boundary paths. Fingerprints identify explicit
source fields; they are never chronological evidence.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import re

from ..models import BookingObservation, Segment, Trip, User
from .agency_ticket_evidence import agency_identity_key, agency_source_proof_key, agency_traveler_key
from .booking_ledger import event_time
from .booking_reconciliation import current_document_versions, matches, original_source
from .flight_import_rollout import enabled


@dataclass
class AgencyTicketMatch:
    status: str = "none"
    segment: object | None = None
    flight: object | None = None
    overwrite: bool = False
    reason: str = "agency_ticket_revision_requires_review"


def _scope(row):
    facts = row.facts or {}
    return (row.travel_date, row.dep_airport, row.arr_airport,
            facts.get("airline"), "".join(str(row.flight_number or "").upper().split()))


def _schedule(row):
    return tuple(event_time((row.facts or {}).get(key)) for key in ("dep_time", "arr_time"))


def _proof(row, names):
    facts = row.facts or {}
    if not isinstance(facts, dict):
        return None
    leg = facts.get("source_leg") or {}
    time = facts.get("time_provenance") or {}
    if not isinstance(leg, dict) or not isinstance(time, dict):
        return None
    proof = leg.get("agency_ticket")
    if (not original_source(row) or row.ownership != "self" or facts.get("ownership") != "self"
            or row.pnr or facts.get("pnr") or facts.get("force_review") or not row.source_message_id
            or facts.get("source") != "shape_priceline_trip_cards"
            or leg.get("template") != "priceline_trip_cards" or type(leg.get("version")) is not int or leg["version"] != 1 or leg.get("ambiguous") is not False
            or not isinstance(proof, dict) or type(proof.get("version")) is not int or proof["version"] != 1 or proof.get("provider") != "priceline"
            or type(time.get("version")) is not int or time["version"] != 1 or time.get("status") != "normalized"):
        return None
    proof_fields = {"version", "provider", "document_key", "ticket_key", "traveler_key",
                    "identity_key", "journey_scope", "source_proof_key"}
    if set(proof) != proof_fields:
        return None
    if any(not re.fullmatch(r"[a-f0-9]{64}", str(proof.get(key) or ""))
           for key in ("document_key", "ticket_key", "traveler_key", "identity_key", "source_proof_key")):
        return None
    if not re.fullmatch(r"[a-f0-9]{64}", str(leg.get("key") or "")):
        return None
    scope = proof.get("journey_scope")
    if not isinstance(scope, dict) or set(scope) != {"dep_airport", "arr_airport", "departure_date"}:
        return None
    try:
        date.fromisoformat(scope["departure_date"])
    except (TypeError, ValueError):
        return None
    if (any(not re.fullmatch(r"[A-Z]{3}", str(scope.get(key) or "")) for key in ("dep_airport", "arr_airport"))
            or scope != leg.get("journey_scope") or proof["identity_key"] != agency_identity_key(proof)
            or proof["source_proof_key"] != agency_source_proof_key(proof["identity_key"], leg["key"])):
        return None
    count, slot = leg.get("journey_leg_count"), leg.get("journey_leg_sequence")
    if type(count) is not int or type(slot) is not int or not 1 <= slot <= count <= 12:
        return None
    named_proof = {key: value for key, value in proof.items() if key != "source_proof_key"}
    named = [entry for entry in matches(row, names) if entry.get("complete") is True
             and agency_traveler_key(entry["name"]) == proof["traveler_key"]
             and entry.get("agency_ticket") == named_proof]
    if not named or not all(_scope(row)):
        return None
    departure, arrival = time.get("departure"), time.get("arrival")
    if (not isinstance(departure, dict) or not isinstance(arrival, dict)
            or facts.get("dep_airport") != row.dep_airport or facts.get("arr_airport") != row.arr_airport
            or "".join(str(facts.get("flight_number") or "").upper().split()) != _scope(row)[4]
            or not _scope(row)[4].startswith(str(facts.get("airline") or ""))
            or departure.get("airport") != row.dep_airport or arrival.get("airport") != row.arr_airport):
        return None
    dep, arr = _schedule(row)
    if (not dep or not arr or not 0 < (arr - dep).total_seconds() <= 48 * 3600
            or time.get("departure_local_date") != row.travel_date
            or event_time(departure.get("utc")) != dep
            or event_time(arrival.get("utc")) != arr):
        return None
    return proof


def _event(row):
    """A canonical original event, never a fresh fetch or fingerprint order."""
    stamp = event_time(row.source_event_at)
    proof = (row.facts or {}).get("source_time_provenance") or {}
    if (not stamp or not isinstance(proof, dict) or type(proof.get("version")) is not int or proof["version"] != 1
            or proof.get("kind") not in {"direct", "forwarded"}
            or any(event_time(proof.get(key)) != stamp for key in ("event_at", "earliest", "latest"))):
        return None
    return stamp


def find(db, user_id, flight, *, protected_trip_ids=()) -> AgencyTicketMatch:
    """Select a single source-backed schedule or hold before ordinary matching.

    The scope is this newly supported no-locator template. Other carriers and
    PNR-backed imports keep their existing policy. Different legs on one ticket
    are separate slots; changed dates/routes/numbers do not gain authority.
    """
    if (getattr(flight, "source", None) != "shape_priceline_trip_cards"
            or getattr(flight, "pnr", None)):
        return AgencyTicketMatch()
    held = AgencyTicketMatch(status="held")
    current = db.get(BookingObservation, getattr(flight, "observation_id", None))
    user = db.get(User, user_id)
    if not current or current.user_id != user_id or not user:
        return held
    names = [user.name, *(user.travel_name_aliases or [])]
    proof = _proof(current, names)
    if not proof:
        return held
    current_leg = current.facts["source_leg"]
    slot, count = current_leg["journey_leg_sequence"], current_leg["journey_leg_count"]
    rows = db.query(BookingObservation).filter(BookingObservation.user_id == user_id,
        BookingObservation.facts["source"].as_string() == "shape_priceline_trip_cards").all()
    rows = current_document_versions(rows)
    relevant = []
    for row in rows:
        leg = (row.facts or {}).get("source_leg") or {}
        if not isinstance(leg, dict):
            if _scope(row) == _scope(current) or row.source_message_id == current.source_message_id:
                return held
            continue
        other = leg.get("agency_ticket") or {}
        if not isinstance(other, dict):
            if _scope(row) == _scope(current) or row.source_message_id == current.source_message_id:
                return held
            continue
        if not other:
            claims = [entry.get("agency_ticket") for entry in (row.facts or {}).get("passenger_evidence") or []
                      if isinstance(entry, dict) and isinstance(entry.get("agency_ticket"), dict)]
            if any(claim.get("ticket_key") == proof["ticket_key"]
                   and claim.get("traveler_key") != proof["traveler_key"] for claim in claims):
                return held
            # A competing incomplete document for this same ticket journey
            # cannot authorize joining two clocks, even with a named traveler.
            if (row.ownership == "self" and leg.get("journey_scope") == proof["journey_scope"]
                    and leg.get("journey_leg_sequence") == slot and _scope(row) == _scope(current)):
                return held
            continue
        same_ticket = other.get("ticket_key") == proof["ticket_key"]
        same_document_journey = (other.get("document_key") == proof["document_key"]
                                 and other.get("journey_scope") == proof["journey_scope"])
        if not (same_ticket or same_document_journey):
            continue
        if (other.get("identity_key") != proof["identity_key"] or not _proof(row, names)
                or leg.get("journey_leg_count") != count):
            return held
        if leg.get("journey_leg_sequence") == slot:
            if _scope(row) != _scope(current):
                return held
            relevant.append(row)
        elif _scope(row) == _scope(current):
            return held
    if not relevant:
        return held
    groups = {}
    for row in relevant:
        groups.setdefault(_schedule(row), []).append(row)
    ranked = []
    for schedule, group in groups.items():
        authorities = [row for row in group if _event(row)
                       and ((row.facts or {}).get("booking_lifecycle") or {}).get("kind") == "confirmation"]
        if not authorities:
            return held
        stamp = max(_event(row) for row in authorities)
        ranked.append((stamp, schedule, min((row for row in authorities if _event(row) == stamp), key=lambda row: row.id)))
    newest = max(item[0] for item in ranked)
    tops = [item for item in ranked if item[0] == newest]
    if len(tops) != 1:
        return held
    _, winning_schedule, winner = tops[0]
    if len(groups) > 1 and newest >= min(schedule[0] for schedule in groups):
        return held
    from .booking_import import _retained_flight
    chosen = _retained_flight(winner, ownership="self")
    if chosen is None:
        return held
    chosen.source_message_id, chosen.observation_id = winner.source_message_id, winner.id
    from .builder import _local_service_day, _normalize_flight_number
    wanted_ids = {row.id for row in relevant}
    candidates = []
    for segment in db.query(Segment).join(Trip).filter(Trip.user_id == user_id).all():
        same_service = (segment.dep_airport == current.dep_airport and segment.arr_airport == current.arr_airport
                        and _normalize_flight_number(segment.flight_number) == _normalize_flight_number(current.flight_number))
        exact_leg = same_service and _local_service_day(segment) == current.travel_date
        meta = segment.meta_json or {}
        # Old parsers sometimes stored printed wall clocks on the wrong date.
        # Exact receipt timestamp plus both printed clocks is enough to stop a
        # speculative duplicate, never authority to correct or retire that row.
        mail_time = event_time(winner.facts.get("mail_received_at"))
        if (same_service and not meta.get("time_provenance") and mail_time
                and event_time(meta.get("source_received_at")) == mail_time):
            time = winner.facts["time_provenance"]
            printed = [event_time((time.get(endpoint) or {}).get("local"))
                       for endpoint in ("departure", "arrival")]
            if all(printed) and all(event_time(value).time() == clock.time()
                                     for value, clock in zip((segment.dep_time, segment.arr_time), printed)):
                return held
        linked = bool(wanted_ids.intersection((segment.meta_json or {}).get("observation_ids") or []))
        if exact_leg or linked:
            if not exact_leg or segment.pnr or segment.airline != current.facts.get("airline"):
                return held
            candidates.append(segment)
    if len(candidates) > 1:
        return held
    allowed = enabled("BOOKING_LEG_RECONCILIATION_ENABLED", user_id)
    if not allowed:
        return AgencyTicketMatch(status="held", reason="agency_ticket_reconciliation_not_enabled")
    existing = candidates[0] if candidates else None
    if existing:
        from .booking_legacy_repair import _protected
        from .travel_name_recovery import active_shares_for_item
        from ..models import TravelInboxAssignment, TravelInboxEvidence, TravelInboxItem
        meta = existing.meta_json or {}
        if existing.trip_id in protected_trip_ids or _protected(db, user_id, existing) or meta.get("pnr_aliases"):
            return AgencyTicketMatch(status="held", reason="agency_ticket_projection_protected")
        ids = list(meta.get("observation_ids") or [])
        items = db.query(TravelInboxItem).join(TravelInboxEvidence).filter(
            TravelInboxItem.user_id == user_id, TravelInboxEvidence.observation_id.in_(ids)).all()
        if any(db.get(TravelInboxAssignment, item.id) or active_shares_for_item(db, user_id, item.id) for item in items):
            return AgencyTicketMatch(status="held", reason="agency_ticket_projection_protected")
        existing_schedule = event_time(existing.dep_time), event_time(existing.arr_time)
        if existing_schedule != winning_schedule:
            attached = [row for row in relevant if row.id in ids and _schedule(row) == existing_schedule]
            if not attached:
                return held
        return AgencyTicketMatch(status="matched", segment=existing, flight=chosen,
                                 overwrite=existing_schedule != winning_schedule)
    return AgencyTicketMatch(status="ready", flight=chosen)
