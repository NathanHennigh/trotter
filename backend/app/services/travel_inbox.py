"""Private retention of other travelers' flight facts, not a sharing service.

Inbox identities are local to the importing user and exact booking/dated leg.
Names are labels, never account identities. The immutable booking ledger remains
the source of truth. This module never writes personal trips or sends anything.
Writers must use the existing per-user import lock and caller's transaction.
"""

from __future__ import annotations

from datetime import datetime
from hashlib import sha256
import json
import re

from ..models import (BookingCancellation, BookingObservation, FlightShare, TravelInboxAssignment,
                      TravelInboxEvidence, TravelInboxItem, User)
from .booking_ledger import booking_code, event_time
from .travel_inbox_identity import exact_airline_name_format_match, retained_passengers


def _hash(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _flight_identity(observation):
    # Match the existing review/import canonicalization, including UA015/UA15.
    # A local import avoids the builder -> ledger -> retention import cycle.
    from .builder import _normalize_flight_number
    return {
        "pnr": booking_code(observation.pnr),
        "date": observation.travel_date,
        "from": booking_code(observation.dep_airport),
        "to": booking_code(observation.arr_airport),
        "number": _normalize_flight_number(observation.flight_number),
    }


def observation_flight_key(observation):
    """Do not conflate reused PNRs, different dates, or weakly identified emails."""
    identity = _flight_identity(observation)
    if not all(identity.values()):
        # With no complete booking identity, only the same source can be grouped.
        identity["source"] = observation.source_message_id or observation.evidence_key
    return _hash(identity)


def _owner(db, user_id, observation=None):
    if observation is not None and observation.user_id != user_id:
        raise ValueError("Booking observation belongs to another user")
    user = db.get(User, user_id)
    if user is None:
        raise ValueError("Travel inbox owner does not exist")
    return user


def _is_review_projection(db, user_id, observation):
    """A review's synthesized personal flight isn't a new passenger receipt."""
    if (observation.facts or {}).get("source") == "travel_name_recovery":
        parts = str(observation.source_message_id or "").split(":")
        source = db.get(BookingObservation, int(parts[1])) if len(parts) == 3 and parts[0] == "travel-name" and parts[1].isdigit() else None
        return bool(source and source.user_id == user_id and _flight_identity(source) == _flight_identity(observation))
    if (observation.facts or {}).get("source") != "user_review":
        return False
    prefix, separator, suffix = str(observation.source_message_id or "").partition(":")
    if prefix != "user-decision" or not separator or not suffix.isdigit():
        return False
    decision = db.get(BookingObservation, int(suffix))
    return bool(decision and decision.user_id == user_id and (decision.facts or {}).get("user_decision")
                and _flight_identity(decision) == _flight_identity(observation))


def _link(db, item, observation):
    if item.user_id != observation.user_id:
        raise ValueError("Travel inbox evidence must belong to the same user")
    existing = db.query(TravelInboxEvidence.id).filter_by(
        item_id=item.id, observation_id=observation.id,
    ).first()
    if not existing:
        db.add(TravelInboxEvidence(item_id=item.id, observation_id=observation.id))
        db.flush()


def _retain_passenger(db, user_id, observation, passenger, *, flight_key=None):
    flight_key = flight_key or observation_flight_key(observation)
    record_key = _hash({"flight": flight_key, "passenger": passenger["passenger_key"]})
    item = db.query(TravelInboxItem).filter_by(user_id=user_id, record_key=record_key).first()
    if item is None and passenger["reason"] in {"companion", "other_traveler"}:
        item, ambiguous = _same_issued_ticket_item(db, user_id, observation, passenger, flight_key)
        if ambiguous:
            # Retain the new source for review without merging existing people,
            # rewriting their labels, or changing their decisions/shares.
            return _retain_passenger(db, user_id, observation,
                {"passenger_name":None, "passenger_key":None, "reason":"unassigned"}, flight_key=flight_key)
    if item is None:
        item = TravelInboxItem(user_id=user_id, record_key=record_key, flight_key=flight_key, **passenger)
        db.add(item)
        db.flush()
    _link(db, item, observation)
    return item


def _named_issued_ticket(observation, passenger_name, *, ownership):
    facts = observation.facts or {}
    if (ownership not in {"self", "other"} or observation.ownership != ownership
            or not all(_flight_identity(observation).values())
            or facts.get("user_decision") or facts.get("force_review")
            or any(facts.get(field) != getattr(observation, field) for field in ("pnr", "dep_airport", "arr_airport", "flight_number"))):
        return None
    entries = facts.get("passenger_evidence")
    if not isinstance(entries, list):
        return None
    keys = set()
    for evidence in entries:
        if (not isinstance(evidence, dict) or evidence.get("role") != "traveler"
                or evidence.get("applies") is not True or evidence.get("complete") is not True
                or evidence.get("scope_ambiguous") is not False
                or not (" ".join(str(evidence.get("name") or "").split()).casefold() == passenger_name.casefold()
                        or exact_airline_name_format_match(evidence.get("name"), passenger_name))):
            continue
        scope = evidence.get("scope") or {}
        if not isinstance(scope, dict) or any(scope.get(field) and scope[field] != getattr(observation, field)
                for field in ("dep_airport", "arr_airport", "flight_number")):
            continue
        pnr = booking_code(observation.pnr)
        if scope.get("pnr") != pnr and scope.get("pnrs") != [pnr]:
            continue
        key = evidence.get("issued_ticket_key")
        if type(evidence.get("issued_ticket_version")) is int and evidence["issued_ticket_version"] == 1 and isinstance(key, str) and re.fullmatch(r"[a-f0-9]{64}", key):
            keys.add(key)
    return next(iter(keys)) if len(keys) == 1 else None


def _same_issued_ticket_item(db, user_id, observation, passenger, flight_key):
    ownership = {"companion": "self", "other_traveler": "other"}.get(passenger["reason"])
    if ownership is None or not all(_flight_identity(observation).values()):
        return None, False
    candidates = [item for item in db.query(TravelInboxItem).filter_by(user_id=user_id, flight_key=flight_key)
                  if item.reason == passenger["reason"] and item.passenger_name
                  and exact_airline_name_format_match(item.passenger_name, passenger["passenger_name"])]
    if not candidates:
        return None, False
    incoming = _named_issued_ticket(observation, passenger["passenger_name"], ownership=ownership)
    matching, uncertain = [], False
    for item in candidates:
        rows = db.query(BookingObservation).join(TravelInboxEvidence).filter(
            TravelInboxEvidence.item_id == item.id, BookingObservation.user_id == user_id).all()
        keys = {_named_issued_ticket(row, item.passenger_name, ownership=ownership) for row in rows}
        # Different explicit tickets can belong to different people whose
        # printed given names happen to concatenate identically.
        if incoming and len(keys) == 1 and None not in keys and incoming not in keys:
            continue
        protected = (db.get(TravelInboxAssignment, item.id) is not None
            or any(item.id in (share.item_ids or []) for share in db.query(FlightShare).filter_by(sender_id=user_id))
            or any((row.facts or {}).get("user_decision") for row in rows))
        if (not incoming or not rows or keys != {incoming} or protected
                or any(observation_flight_key(row) != flight_key for row in rows)):
            uncertain = True
        else:
            matching.append(item)
    if uncertain or len(matching) > 1:
        return None, True
    return (matching[0], False) if matching else (None, False)


def retain_observation(db, user_id, observation):
    """Idempotently retain companions, other travelers and unassigned evidence.

Must be called before the personal-history ownership/cancellation gate. Every
source remains saved even when a later source corrects its passenger manifest.
No email replay may remove an inbox identity or its evidence.
"""
    user = _owner(db, user_id, observation)
    if (observation.facts or {}).get("user_decision"):
        return retain_user_decision(db, user_id, observation)
    if _is_review_projection(db, user_id, observation):
        # The explicit decision already links to the original ticket. Its copied
        # passenger manifest must not manufacture companions or revise identity.
        return []
    return [_retain_passenger(db, user_id, observation, passenger)
            for passenger in retained_passengers(observation, user)]


def retain_user_decision(db, user_id, observation):
    """Attach personal-history decisions without applying them to companions.

An explicit OTHER decision can establish an unnamed retained record when there
is no source manifest. A SELF decision cannot claim somebody else's ticket.
"""
    _owner(db, user_id, observation)
    decision = (observation.facts or {}).get("user_decision") or {}
    if not decision:
        raise ValueError("A user decision observation is required")
    source_id = decision.get("source_observation_id")
    source = None
    key = observation_flight_key(observation)
    if source_id is not None:
        source = db.get(BookingObservation, source_id) if isinstance(source_id, int) else None
        if source is None or source.user_id != user_id or _flight_identity(source) != _flight_identity(observation):
            raise ValueError("Decision source must be the same user's exact flight observation")
        key = observation_flight_key(source)
        items = db.query(TravelInboxItem).join(TravelInboxEvidence).filter(
            TravelInboxItem.user_id == user_id, TravelInboxEvidence.observation_id == source.id,
        ).all()
    else:
        items = db.query(TravelInboxItem).filter_by(user_id=user_id, flight_key=key).all()
    if not items and decision.get("ownership") in {"other", "unknown"}:
        item = _retain_passenger(db, user_id, observation, {
            "passenger_name": None, "passenger_key": None, "reason": "unassigned",
        }, flight_key=key)
        if source is not None:
            _link(db, item, source)
        return [item]
    for item in items:
        _link(db, item, observation)
    return items


def backfill_user_travel_inbox(db, user_id):
    """Index already retained facts; no reparse, mailbox fetch or old-row writes.

Caller holds user_import_lock and commits/rolls back. Sources are visited before
manual decisions so a named record is preferred over a redundant placeholder.
"""
    _owner(db, user_id)

    def counts():
        return (
            db.query(TravelInboxItem).filter_by(user_id=user_id).count(),
            db.query(TravelInboxEvidence).join(TravelInboxItem).filter(TravelInboxItem.user_id == user_id).count(),
        )

    before_items, before_evidence = counts()
    observations = db.query(BookingObservation).filter_by(user_id=user_id).order_by(BookingObservation.id).all()
    for observation in observations:
        if not (observation.facts or {}).get("user_decision"):
            retain_observation(db, user_id, observation)
    for observation in observations:
        if (observation.facts or {}).get("user_decision"):
            retain_user_decision(db, user_id, observation)
    after_items, after_evidence = counts()
    return {"items_added": after_items - before_items, "evidence_added": after_evidence - before_evidence,
            "total_items": after_items, "total_evidence": after_evidence}


def _source_order(observation):
    # Event time, not import order, determines which receipt is newest. The hash
    # breaks ties deterministically even when messages are replayed in reverse.
    return (event_time(observation.source_event_at) or datetime.min, observation.evidence_key)


def _same_scope(observation, scope):
    if not observation.travel_date or observation.travel_date != scope.get("travel_date"):
        return False
    if any(booking_code(getattr(observation, field)) != booking_code(scope.get(field))
           for field in ("dep_airport", "arr_airport")):
        return False
    left = "".join(str(observation.flight_number or "").split()).upper()
    right = "".join(str(scope.get("flight_number") or "").split()).upper()
    return not left or not right or left == right


def _cancellation_state(db, user_id, observation, *, passenger_name=None):
    if not observation.pnr:
        return None
    events = db.query(BookingCancellation).filter_by(user_id=user_id, pnr=booking_code(observation.pnr)).all()
    uncertain = False
    for event in events:
        if not event.scopes:
            uncertain = True
            continue
        if not any(_same_scope(observation, scope) for scope in event.scopes):
            continue
        if passenger_name and (event.facts or {}).get("strict_lifecycle"):
            from .passenger_identity import full_names_match
            scoped_facts = [facts for facts in (event.facts or {}).get("flights", [])
                if _same_scope(observation, {
                    "travel_date": (facts.get("time_provenance") or {}).get("departure_local_date")
                        or str(facts.get("dep_time") or "")[:10],
                    "dep_airport": facts.get("dep_airport"), "arr_airport": facts.get("arr_airport"),
                    "flight_number": facts.get("flight_number")})]
            names = [name for facts in scoped_facts for name in facts.get("passenger_names") or []]
            if names and not any(full_names_match(passenger_name, name) for name in names):
                continue
            if not names:
                uncertain = True
                continue
        received = event_time(observation.source_event_at)
        canceled = event_time(event.source_event_at)
        if received and canceled and received <= canceled:
            return "canceled"
        # A later receipt isn't proof that a companion's canceled ticket was
        # reinstated. Keep it for review instead of silently making it active.
        uncertain = True
    return "needs_review" if uncertain else None


def serialize_item(db, user_id, item, *, include_evidence=False, siblings=None):
    """Owner-only, passenger-specific read projection; never a transfer payload.

Source pointers are available only to the importing owner. Raw email content,
co-traveler manifests and payer information are deliberately absent. Actual
sharing will require separate authorization and an explicit payload allowlist.
"""
    if item.user_id != user_id:
        raise ValueError("Travel inbox item belongs to another user")
    user = _owner(db, user_id)
    observations = db.query(BookingObservation).join(
        TravelInboxEvidence, TravelInboxEvidence.observation_id == BookingObservation.id,
    ).filter(TravelInboxEvidence.item_id == item.id, BookingObservation.user_id == user_id).all()
    sources = [row for row in observations if not (row.facts or {}).get("user_decision")
               and not _is_review_projection(db, user_id, row)]
    decisions = [row for row in observations if (row.facts or {}).get("user_decision")]
    latest = max(sources or decisions, key=_source_order) if sources or decisions else None
    facts = latest.facts or {} if latest else {}
    # The stored reason describes intake. Current presentation follows source
    # chronology, so reversed email replay cannot change companion semantics.
    reason = ("companion" if latest.ownership == "self" else "other_traveler") \
        if item.passenger_name and sources else item.reason
    status = "retained" if latest and item.passenger_name and not facts.get("force_review") else "needs_review"
    decision = max(decisions, key=_source_order).facts["user_decision"] if decisions else {}
    from .passenger_identity import full_names_match, identity_candidates
    owner_names = identity_candidates(user.name, user.travel_name_aliases or [])
    if (item.passenger_name and any(full_names_match(item.passenger_name, name) for name in owner_names if name)
            and not facts.get("force_review") and decision.get("ownership") != "other"
            and decision.get("status") not in {"canceled", "hold"}):
        # Name confirmation queues recovery; it is not itself proof that the
        # itinerary accepted a held/canceled/shared booking. Keep those visible.
        proofs = db.query(BookingObservation).filter_by(user_id=user_id, pnr=latest.pnr,
            travel_date=latest.travel_date, ownership="self").all() if latest else []
        verified = any(_flight_identity(proof) == _flight_identity(latest)
            and not (proof.facts or {}).get("force_review")
            and (proof.facts or {}).get("user_decision", {}).get("status") not in {"canceled", "hold"}
            for proof in proofs)
        status = "belongs_to_you" if verified else "needs_review"
    elif item.passenger_name and reason != "companion" and decision.get("ownership") == "self":
        status = "needs_review"
    elif not item.passenger_name and decision.get("ownership") == "self" and decision.get("status") == "active":
        status = "belongs_to_you"
    cancellation = _cancellation_state(db, user_id, latest, passenger_name=item.passenger_name) if latest else None
    if cancellation:
        status = cancellation
    # Personal decisions have no authority over a named companion's ticket.
    if not item.passenger_name and decision.get("ownership") == "self" and decision.get("status") == "active":
        status = "belongs_to_you"
    if not item.passenger_name and decision.get("status") == "canceled":
        status = "canceled"
    if not item.passenger_name and decision.get("status") == "hold":
        status = "needs_review"
    time_proof = facts.get("time_provenance")
    hide_subject_dates = (facts.get("force_review") is True and isinstance(time_proof, dict)
                          and time_proof.get("extraction_review_reason") == "subject_only_itinerary_requires_review")
    # Subject-only placeholders remain immutable evidence, not displayed dates
    # or clocks. The empty date keeps the existing retained-flight API contract.
    result = {
        "id": item.id, "passenger_name": item.passenger_name, "reason": reason,
        "status": status, "created_at": item.created_at, "observation_count": len(observations),
        "flight": {
            "pnr": latest.pnr, "travel_date": "" if hide_subject_dates else latest.travel_date,
            "dep_airport": latest.dep_airport, "arr_airport": latest.arr_airport,
            "flight_number": latest.flight_number, "dep_time": None if hide_subject_dates else facts.get("dep_time"),
            "arr_time": None if hide_subject_dates else facts.get("arr_time"), "airline": facts.get("airline"),
            "aircraft": facts.get("aircraft"),
        } if latest else None,
    }
    # A read projection preserves every stored recipient and source.
    from .recipient_name_revision import recipient_revision_for_item
    revision = recipient_revision_for_item(db, item, observations, siblings=siblings)
    if revision:
        result['recipient_revision'] = revision
        if revision['state'] in {'superseded', 'needs_review'} and result['status'] != 'canceled':
            result['status'] = 'needs_review'
    if include_evidence:
        result["evidence"] = [{
            "observation_id": row.id, "source_message_id": row.source_message_id,
            "source_event_at": row.source_event_at, "source": (row.facts or {}).get("source"),
            "kind": "user_decision" if (row.facts or {}).get("user_decision") else "booking",
        } for row in sorted(observations, key=_source_order, reverse=True)]
    return result
