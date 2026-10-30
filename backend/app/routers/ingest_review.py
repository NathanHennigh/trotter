"""Authenticated review of immutable booking evidence and explicit name aliases."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Literal
import unicodedata

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import BookingObservation, Message, MessageStatus, Segment, TravelInboxItem, Trip, User
from ..services.booking_ledger import (
    booking_code, event_time, flight_scope, has_verified_self_observation,
    record_user_decision, snapshot_user_itinerary, user_decision_for_flight,
)
from ..services.builder import build_segments_and_trips_detailed, rebuild_affected_trips, _normalize_flight_number
from ..services.import_lock import ImportAlreadyRunning, user_import_lock
from ..services import travel_name_recovery as name_recovery
from .auth import get_current_user

router = APIRouter(prefix="/ingest", tags=["ingest"])


class BookingDecisionIn(BaseModel):
    decision: Literal["self", "other", "canceled"]


class TravelNameAliases(BaseModel):
    aliases: list[str] = Field(default_factory=list, max_length=20)
    confirmed: bool = True

    @field_validator("aliases")
    @classmethod
    def normalize_aliases(cls, aliases):
        normalized = []
        seen = set()
        for alias in aliases:
            value = " ".join(unicodedata.normalize("NFKC", alias).split())
            if not 2 <= len(value) <= 100 or not any(character.isalpha() for character in value):
                raise ValueError("Each alias must be a name between 2 and 100 characters")
            if any(not (character.isalpha() or character in " '-.’,()/") for character in value):
                raise ValueError("Aliases must contain names, not email addresses or booking codes")
            if value.casefold() not in seen:
                normalized.append(value)
                seen.add(value.casefold())
        return normalized


def _observation_flight(observation):
    facts = observation.facts or {}
    return SimpleNamespace(
        dep_airport=observation.dep_airport, arr_airport=observation.arr_airport,
        dep_time=event_time(facts.get("dep_time")), arr_time=event_time(facts.get("arr_time")),
        airline=facts.get("airline"), flight_number=_normalize_flight_number(observation.flight_number),
        pnr=booking_code(observation.pnr), pnr_aliases=facts.get("pnr_aliases") or [],
        source=facts.get("source") or "booking_observation", source_received_at=event_time(observation.source_event_at),
        confidence=facts.get("confidence"), nonstop=bool(facts.get("nonstop")), aircraft=facts.get("aircraft"),
        ownership=observation.ownership, passenger_names=facts.get("passenger_names") or [],
        passenger_evidence=facts.get("passenger_evidence") or [], force_review=False,
    )


def _validate_decision_scope(flight, decision):
    if (not flight.dep_time or not flight.arr_time or flight.arr_time <= flight.dep_time
            or not flight.dep_airport or not flight.arr_airport):
        raise HTTPException(422, "This observation needs complete departure, arrival, and route facts before it can be resolved")
    if not flight.flight_number:
        raise HTTPException(422, "A flight number is required to resolve this exact flight safely")
    if decision != "self" and not flight.pnr:
        raise HTTPException(422, "This observation has no booking reference; it remains held because a stored flight cannot be safely removed")


def _message_review_state(db, user_id, source_message_id, *, observation_id, decision_id, decision):
    if not source_message_id:
        return None
    message = db.query(Message).filter_by(user_id=user_id, provider_msg_id=source_message_id).first()
    if not message:
        return None
    pending = False
    observations = db.query(BookingObservation).filter_by(user_id=user_id, source_message_id=source_message_id).all()
    for observation in observations:
        fact = _observation_flight(observation)
        if user_decision_for_flight(db, user_id, fact):
            continue
        if observation.facts.get("force_review"):
            pending = True
            break
        if observation.ownership == "unknown" and not has_verified_self_observation(
            db, user_id, observation.pnr, flight_scope(fact),
        ):
            pending = True
            break
    evidence = dict(message.parse_evidence or {})
    actions = list(evidence.get("user_decisions") or [])
    actions.append({"observation_id": observation_id, "decision_id": decision_id, "decision": decision})
    evidence["user_decisions"] = actions
    evidence["resolved"] = not pending
    if not pending:
        if message.parse_error:
            evidence.setdefault("original_review_error", message.parse_error)
        message.status = MessageStatus.ACCEPTED
        message.parse_error = None
    else:
        message.status = MessageStatus.REVIEW_REQUIRED
    message.parse_evidence = evidence
    message.ignored = False
    return message.status.value


@router.get("/booking-observations")
def list_booking_observations(
    limit: int = Query(50, ge=1, le=100), before_id: int | None = Query(None, ge=1),
    source_message_id: str | None = Query(None, max_length=255),
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    query = db.query(BookingObservation).filter(BookingObservation.user_id == current_user.id)
    if source_message_id is not None:
        query = query.filter(BookingObservation.source_message_id == source_message_id)
    if before_id is not None:
        query = query.filter(BookingObservation.id < before_id)
    rows = query.order_by(BookingObservation.id.desc()).limit(limit + 1).all()
    page = rows[:limit]
    return {
        "observations": [{
            "id": row.id, "source_message_id": row.source_message_id,
            "source_event_at": row.source_event_at, "pnr": row.pnr, "ownership": row.ownership,
            "facts": row.facts, "decision": user_decision_for_flight(db, current_user.id, _observation_flight(row)),
        } for row in page],
        "next_before_id": page[-1].id if len(rows) > limit else None,
    }


@router.post("/booking-observations/{observation_id}/decision")
def decide_booking_observation(
    observation_id: int, body: BookingDecisionIn,
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    # Scope the lookup before attempting a lock; another user's IDs always look
    # exactly like nonexistent IDs, including while that other user is importing.
    observation = db.query(BookingObservation).filter_by(id=observation_id, user_id=current_user.id).first()
    if observation is None:
        raise HTTPException(404, "Booking observation not found")
    try:
        with user_import_lock(db.get_bind(), current_user.id):
            flight = _observation_flight(observation)
            _validate_decision_scope(flight, body.decision)
            decision = record_user_decision(
                db, current_user.id, flight,
                ownership="other" if body.decision == "other" else "self",
                status="canceled" if body.decision == "canceled" else "active",
                reason=f"User reviewed booking observation {observation.id}: {body.decision}",
                source_observation_id=observation.id,
            )
            affected_ids = set()
            inserted = updated = removed = 0
            if body.decision == "self":
                flight.ownership = "self"
                flight.source = "user_review"
                flight.source_received_at = datetime.now(timezone.utc)
                result = build_segments_and_trips_detailed(
                    db, current_user.id, [flight], source_message_id=f"user-decision:{decision.id}",
                    source_event_at=flight.source_received_at,
                )
                affected_ids = result.affected_segment_ids
                inserted, updated = result.inserted, result.updated
            else:
                candidates = db.query(Segment).join(Trip).filter(
                    Trip.user_id == current_user.id, Segment.pnr == flight.pnr,
                    Segment.dep_airport == flight.dep_airport, Segment.arr_airport == flight.arr_airport,
                ).all()
                matching = [segment for segment in candidates
                            if event_time(segment.dep_time).date() == flight.dep_time.date()
                            and _normalize_flight_number(segment.flight_number) == flight.flight_number]
                trip_ids = {segment.trip_id for segment in matching}
                affected_ids = {segment.id for segment in matching}
                snapshot_user_itinerary(
                    db, current_user.id, reason=f"user_marked_{body.decision}",
                    segment_ids=affected_ids, trip_ids=trip_ids,
                )
                for segment in matching:
                    db.delete(segment)
                db.flush()
                removed = len(matching)
                rebuild_affected_trips(db, current_user.id, trip_ids)
            message_status = _message_review_state(
                db, current_user.id, observation.source_message_id,
                observation_id=observation.id, decision_id=decision.id, decision=body.decision,
            )
            db.commit()
            return {"observation_id": observation.id, "decision_id": decision.id, "decision": body.decision,
                    "inserted": inserted, "updated": updated, "removed": removed,
                    "affected_segment_ids": sorted(affected_ids), "message_status": message_status}
    except ImportAlreadyRunning as exc:
        db.rollback()
        raise HTTPException(409, str(exc)) from exc
    except Exception:
        db.rollback()
        raise


@router.get("/travel-name-aliases")
def get_travel_name_aliases(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    user = db.query(User).filter_by(id=current_user.id).one()
    return name_recovery.identity_state(db, user)


@router.put("/travel-name-aliases")
def put_travel_name_aliases(
    body: TravelNameAliases, current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    try:
        with user_import_lock(db.get_bind(), current_user.id):
            user = db.query(User).filter_by(id=current_user.id).one()
            user.travel_name_aliases = body.aliases
            if body.confirmed:
                user.travel_names_confirmed_at = datetime.now(timezone.utc)
                name_recovery.queue_recovery(db, user)
            db.commit()
            return name_recovery.identity_state(db, user)
    except ImportAlreadyRunning as exc:
        db.rollback()
        raise HTTPException(409, str(exc)) from exc
    except Exception:
        db.rollback()
        raise


@router.post("/travel-name-recovery")
def retry_name_recovery(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        with user_import_lock(db.get_bind(), current_user.id):
            user = db.get(User, current_user.id)
            if not user.travel_names_confirmed_at:
                raise HTTPException(409, "Confirm your travel names before checking saved bookings")
            name_recovery.queue_recovery(db, user, force=True)
            db.commit()
            return name_recovery.identity_state(db, user)
    except ImportAlreadyRunning as exc:
        db.rollback()
        raise HTTPException(409, str(exc)) from exc


class ClaimSelfIn(BaseModel):
    passenger_name: str = Field(min_length=2, max_length=100)


@router.post("/travel-inbox/{item_id}/claim-self")
def claim_self(item_id: str, body: ClaimSelfIn, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        with user_import_lock(db.get_bind(), current_user.id):
            item = db.query(TravelInboxItem).filter_by(id=item_id, user_id=current_user.id).first()
            if item is None:
                raise HTTPException(404, "Saved flight not found")
            normalize = lambda value: " ".join(unicodedata.normalize("NFKC", value).split()).casefold()
            if not item.passenger_name or normalize(item.passenger_name) != normalize(body.passenger_name):
                raise HTTPException(422, "Confirm the passenger name printed on this booking")
            from ..services.passenger_identity import full_names_match
            if not full_names_match(item.passenger_name, item.passenger_name):
                raise HTTPException(422, "Add your full travel name in Profile so this booking can be checked safely")
            if name_recovery.active_shares_for_item(db, current_user.id, item.id):
                raise HTTPException(409, "This booking has already been shared. Resolve that invitation before claiming it")
            user = db.get(User, current_user.id)
            try:
                aliases = list(user.travel_name_aliases or [])
                if normalize(item.passenger_name) not in {normalize(name) for name in aliases}:
                    aliases.append(item.passenger_name)
                validated = TravelNameAliases(aliases=aliases)
            except ValueError as exc:
                raise HTTPException(422, "Review your saved travel names in Profile before adding this name") from exc
            user.travel_name_aliases = validated.aliases
            user.travel_names_confirmed_at = datetime.now(timezone.utc)
            name_recovery.queue_recovery(db, user)
            db.commit()
            return name_recovery.identity_state(db, user)
    except ImportAlreadyRunning as exc:
        db.rollback()
        raise HTTPException(409, str(exc)) from exc


@router.post("/travel-onboarding/complete")
def complete_travel_onboarding(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    user = db.get(User, current_user.id)
    user.travel_onboarding_completed_at = datetime.now(timezone.utc)
    db.commit()
    return name_recovery.identity_state(db, user)
