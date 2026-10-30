"""Recover personal flights from retained facts, never by fetching the mailbox.

Each bounded batch and its cursor commit together under the import lock. A
crashed worker can replay the batch safely. Original facts and cancellation
timestamps are never rewritten by name confirmation.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from types import SimpleNamespace

from sqlalchemy import func

from ..models import BookingObservation, FlightShare, TravelInboxEvidence, TravelInboxItem, TravelNameRecovery, User
from .booking_ledger import booking_code, event_time, user_decision_for_flight
from .builder import _normalize_flight_number, build_segments_and_trips_detailed
from .import_lock import ImportAlreadyRunning, user_import_lock
from .passenger_identity import full_names_match
from .travel_inbox import _cancellation_state
from .booking_reconciliation import observation_groups, resolve_group, current_document_versions


def now():
    return datetime.now(timezone.utc)


def names_for(user):
    return [name for name in [user.name, *(user.travel_name_aliases or [])] if name]


def fingerprint(names):
    return sha256(json.dumps(sorted(set(name.casefold() for name in names)), ensure_ascii=False).encode()).hexdigest()


def latest_job(db, user_id):
    return db.query(TravelNameRecovery).filter_by(user_id=user_id).order_by(
        TravelNameRecovery.created_at.desc(), TravelNameRecovery.id.desc()).first()


def identity_state(db, user):
    job = latest_job(db, user.id)
    return {"aliases": user.travel_name_aliases or [], "primary_name": user.name,
            "confirmed": bool(user.travel_names_confirmed_at),
            "onboarding_completed": bool(user.travel_onboarding_completed_at),
            "recovery": {key: getattr(job, key) for key in
                         ("id", "state", "checked", "added", "existing", "needs_review", "error")} if job else None}


def queue_recovery(db, user, *, force=False):
    """Caller holds the import lock and commits. Beat reliably discovers jobs."""
    names = names_for(user)
    digest = fingerprint(names)
    prior = latest_job(db, user.id)
    if not force and prior and prior.fingerprint == digest:
        later = db.query(BookingObservation).filter(BookingObservation.user_id == user.id,
            BookingObservation.id > prior.max_observation_id).all()
        if prior.state in {"queued", "running"} or not any(original_source(row) for row in later):
            return prior
    # Superseded work has no authority to project a formerly confirmed name.
    for pending in db.query(TravelNameRecovery).filter(
            TravelNameRecovery.user_id == user.id, TravelNameRecovery.state.in_(["queued", "running"])).all():
        pending.state = "completed"
        pending.updated_at = now()
    upper = db.query(func.max(BookingObservation.id)).filter_by(user_id=user.id).scalar() or 0
    job = TravelNameRecovery(user_id=user.id, names=names, fingerprint=digest, max_observation_id=upper)
    db.add(job)
    db.flush()
    return job


def original_source(observation):
    facts = observation.facts or {}
    return (not facts.get("user_decision")
            and facts.get("source") not in {"user_review", "travel_name_recovery", "booking_repair_reconciliation", "flight_share", "accepted_flight_share"})


def matching_evidence(observation, names):
    evidence = (observation.facts or {}).get("passenger_evidence") or []
    evidence = [evidence] if isinstance(evidence, dict) else evidence
    if not isinstance(evidence, list):
        return []
    return [entry for entry in evidence
            if isinstance(entry, dict) and entry.get("role") == "traveler"
            and entry.get("applies") is True and not entry.get("scope_ambiguous")
            and any(full_names_match(entry.get("name"), name) for name in names)]


def flight_from(observation):
    facts = observation.facts or {}
    return SimpleNamespace(
        dep_airport=observation.dep_airport, arr_airport=observation.arr_airport,
        dep_time=event_time(facts.get("dep_time")), arr_time=event_time(facts.get("arr_time")),
        airline=facts.get("airline"), flight_number=_normalize_flight_number(observation.flight_number),
        pnr=booking_code(observation.pnr), pnr_aliases=facts.get("pnr_aliases") or [],
        source="travel_name_recovery", source_received_at=event_time(observation.source_event_at),
        confidence=facts.get("confidence"), nonstop=bool(facts.get("nonstop")), aircraft=facts.get("aircraft"),
        ownership="self", passenger_names=facts.get("passenger_names") or [],
        passenger_evidence=facts.get("passenger_evidence") or [], force_review=bool(facts.get("force_review")),
        **{key: facts.get(key) for key in ('time_provenance', 'source_time_provenance', 'parser_version',
            'recovery_observation_ids', 'reconciles_observation_ids', 'document_provenance', 'mail_received_at')})


def active_shares_for_item(db, user_id, item_id):
    return [share for share in db.query(FlightShare).filter(
        FlightShare.sender_id == user_id, FlightShare.status.in_(["pending", "accepted"])).all()
        if item_id in (share.item_ids or []) and (share.status == "accepted" or event_time(share.expires_at) > event_time(now()))]


def recovery_blocked(db, user_id, observation, flight, names):
    if (flight.force_review or not flight.pnr or not flight.dep_time or not flight.arr_time
            or flight.arr_time <= flight.dep_time or not flight.flight_number
            or not flight.dep_airport or not flight.arr_airport):
        return True
    for code in {flight.pnr, *(booking_code(code) for code in flight.pnr_aliases)}:
        decision = user_decision_for_flight(db, user_id, flight, pnr=code)
        if decision and (decision.get("ownership") != "self" or decision.get("status") != "active"):
            return True
        scoped = SimpleNamespace(**{key: getattr(observation, key) for key in
            ("travel_date", "dep_airport", "arr_airport", "flight_number", "source_event_at")}, pnr=code)
        if _cancellation_state(db, user_id, scoped):
            return True
    items = db.query(TravelInboxItem).join(TravelInboxEvidence).filter(
        TravelInboxItem.user_id == user_id, TravelInboxEvidence.observation_id == observation.id).all()
    return any(item.passenger_name and any(full_names_match(item.passenger_name, name) for name in names)
               and active_shares_for_item(db, user_id, item.id) for item in items)


def recover_batch(db, job, *, batch_size=75):
    """Atomic worker core. Caller holds lock; this function does not commit."""
    user = db.get(User, job.user_id)
    if not user or fingerprint(names_for(user)) != job.fingerprint or not user.travel_names_confirmed_at:
        job.state = "completed"
        return
    rows = db.query(BookingObservation).filter(
        BookingObservation.user_id == job.user_id, BookingObservation.id > job.cursor,
        BookingObservation.id <= job.max_observation_id).order_by(BookingObservation.id).limit(batch_size).all()
    original_rows = db.query(BookingObservation).filter(BookingObservation.user_id == job.user_id,
        BookingObservation.id <= job.max_observation_id).order_by(BookingObservation.id).all()
    groups = observation_groups(original_rows)
    groups_by_anchor = {max(row.id for row in group): group for group in groups}
    job.state = "running"
    for observation in rows:
        job.cursor = observation.id
        if not original_source(observation):
            continue
        job.checked += 1
        group = groups_by_anchor.get(observation.id)
        if not group or not any(matching_evidence(row, job.names) for row in current_document_versions(group)):
            continue
        resolved = resolve_group(group, job.names)
        if resolved.review_reason:
            job.needs_review += 1
            continue
        if not resolved.schedule:
            continue
        flight = flight_from(resolved.schedule)
        flight.passenger_evidence = resolved.passenger_evidence
        flight.passenger_names = list(dict.fromkeys(entry['name'] for entry in resolved.passenger_evidence))
        flight.recovery_observation_ids = sorted(row.id for row in group)
        protected_sources = [row for row in group if row.id in resolved.source_ids]
        if any(recovery_blocked(db, job.user_id, row, flight_from(row), job.names) for row in protected_sources):
            job.needs_review += 1
            continue
        result = build_segments_and_trips_detailed(db, job.user_id, [flight],
            source_message_id=f"travel-name:{observation.id}:{job.fingerprint}",
            source_event_at=event_time(resolved.schedule.source_event_at))
        job.added += result.inserted
        job.existing += 1 if not result.inserted and not result.held else 0
        job.needs_review += 1 if result.held else 0
    job.state = "queued" if len(rows) == batch_size and job.cursor < job.max_observation_id else "completed"
    job.attempts = 0
    job.error = None
    job.updated_at = now()
    job.next_attempt_at = now()


def run_recovery(job_id, *, session_factory=None):
    from ..db import SessionLocal
    factory = session_factory or SessionLocal
    with factory() as db:
        job = db.get(TravelNameRecovery, job_id)
        if not job or job.state not in {"queued", "running"} or event_time(job.next_attempt_at) > event_time(now()):
            return
        user_id = job.user_id
        try:
            with user_import_lock(db.get_bind(), user_id):
                db.expire_all()
                job = db.get(TravelNameRecovery, job_id)
                if not job or job.state not in {"queued", "running"}:
                    return
                recover_batch(db, job)
                db.commit()
        except ImportAlreadyRunning:
            db.rollback()
            # Do not write state without the user's lock; an in-flight worker
            # might commit completion. Beat will try again on its next sweep.
            return
        except Exception:
            db.rollback()
            # A retry starts from the last committed cursor, not a partial batch.
            try:
                with user_import_lock(db.get_bind(), user_id):
                    db.expire_all()
                    job = db.get(TravelNameRecovery, job_id)
                    if job and job.state in {"queued", "running"}:
                        job.attempts += 1
                        job.state = "failed" if job.attempts >= 5 else "queued"
                        job.error = "Saved bookings could not be checked. Please try again." if job.state == "failed" else None
                        job.next_attempt_at = now() + timedelta(seconds=min(300, 15 * 2 ** job.attempts))
                        job.updated_at = now()
                        db.commit()
            except ImportAlreadyRunning:
                db.rollback()
            raise


def discover_recoveries(db):
    """Bounded sweep recovers queued work after worker/broker restarts."""
    return [row.id for row in db.query(TravelNameRecovery).filter(
        TravelNameRecovery.state.in_(["queued", "running"]), TravelNameRecovery.next_attempt_at <= now()
    ).order_by(TravelNameRecovery.next_attempt_at, TravelNameRecovery.created_at).limit(50).all()]
