"""Explicit flight invitations. No mailbox, payment or shared-booking access is transferred."""
from __future__ import annotations

from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import os
import re
import secrets
from types import SimpleNamespace
import unicodedata
from urllib.parse import urlparse
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import func

from ..crypto import decrypt_refresh_token, encrypt_refresh_token
from ..models import (BookingObservation, FlightShare, Segment, TravelInboxAssignment,
                      TravelInboxEvidence, TravelInboxItem, Trip, User)
from .booking_ledger import event_time, record_flight_observations
from .builder import _normalize_flight_number, build_segments_and_trips_detailed
from .import_lock import ImportAlreadyRunning, user_import_lock
from .travel_inbox import _cancellation_state, _is_review_projection, _source_order, serialize_item

MAX_INBOX_RECORDS = 5000
SHARE_DAYS = 14
PUBLIC_FLIGHT_FIELDS = ("dep_airport", "arr_airport", "travel_date", "flight_number", "dep_time", "arr_time", "airline")


def utcnow():
    return datetime.now(timezone.utc)


def normalize_email(value):
    value = str(value or "").strip().casefold()
    # Exact email identity. Do not strip plus-addresses, dots or infer aliases.
    if len(value) > 255 or not re.fullmatch(r"[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+", value):
        raise HTTPException(422, "Enter the email address they use to sign in to Trotter")
    return value


def normalize_name(value):
    value = " ".join(unicodedata.normalize("NFC", str(value or "")).split())
    if not 2 <= len(value) <= 100 or not any(c.isalpha() for c in value):
        raise HTTPException(422, "Enter the traveler's name")
    if any(not (c.isalpha() or c in " '-.’,()") for c in value):
        raise HTTPException(422, "Enter a name, without an email address or booking reference")
    return value


def _key(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _share_status(share):
    if share.status == "pending" and event_time(share.expires_at) <= event_time(utcnow()):
        return "expired"
    return share.status


def share_view(db, share):
    sender = db.get(User, share.sender_id)
    def timestamp(value):
        normalized = event_time(value)
        return normalized.replace(tzinfo=timezone.utc) if normalized else None
    # This is the entire recipient allowlist, not a generic ORM serializer.
    return {"id": share.id, "passenger_name": share.passenger_name,
            "sender_name": sender.name if sender and sender.name else "A Trotter traveler",
            "recipient_email": share.recipient_email, "status": _share_status(share),
            "created_at": timestamp(share.created_at), "expires_at": timestamp(share.expires_at),
            "accepted_at": timestamp(share.accepted_at),
            "flights": [{field: row.get(field) for field in PUBLIC_FLIGHT_FIELDS} for row in share.flights]}


def _item(db, owner_id, item_id):
    item = db.query(TravelInboxItem).filter_by(id=item_id, user_id=owner_id).first()
    if not item:
        raise HTTPException(404, "Flight record not found")
    return item


def _assignment(db, owner_id, item_id):
    return db.query(TravelInboxAssignment).filter_by(item_id=item_id, user_id=owner_id).first()


def _latest_observation(db, item):
    observations = db.query(BookingObservation).join(
        TravelInboxEvidence, TravelInboxEvidence.observation_id == BookingObservation.id,
    ).filter(TravelInboxEvidence.item_id == item.id, BookingObservation.user_id == item.user_id).all()
    sources = [row for row in observations if not (row.facts or {}).get("user_decision")
               and not _is_review_projection(db, item.user_id, row)]
    return max(sources, key=_source_order) if sources else None


def _flight_snapshot(row):
    flight = row.get("flight") or {}
    dep, arr = event_time(flight.get("dep_time")), event_time(flight.get("arr_time"))
    origin, destination = str(flight.get("dep_airport") or "").upper(), str(flight.get("arr_airport") or "").upper()
    number = _normalize_flight_number(flight.get("flight_number")) or ""
    if (not dep or not arr or arr <= dep or (arr - dep) > timedelta(days=3)
            or not re.fullmatch(r"[A-Z]{3}", origin) or not re.fullmatch(r"[A-Z]{3}", destination)
            or origin == destination or not re.fullmatch(r"[A-Z0-9]{2,3}\d{1,5}[A-Z]?", number)
            or flight.get("travel_date") != dep.date().isoformat()):
        raise HTTPException(422, "This flight needs complete route, flight number and departure/arrival times before sharing")
    airline = str(flight.get("airline") or "").upper()
    if not re.fullmatch(r"[A-Z0-9]{2,3}", airline):
        airline = None
    return {"dep_airport": origin, "arr_airport": destination, "flight_number": number,
            "dep_time": dep.replace(tzinfo=timezone.utc).isoformat(), "arr_time": arr.replace(tzinfo=timezone.utc).isoformat(),
            "travel_date": dep.date().isoformat(), "airline": airline}


def _validate_item(db, item, *, passenger_name=None, allow_unassigned=False):
    row = serialize_item(db, item.user_id, item)
    assignment = _assignment(db, item.user_id, item.id)
    name = assignment.passenger_name if assignment else item.passenger_name
    if row["status"] in {"canceled", "belongs_to_you"}:
        raise HTTPException(422, "Canceled flights and flights already identified as yours cannot be shared here")
    if item.passenger_name and row["status"] == "needs_review":
        raise HTTPException(422, "This named ticket has conflicting ownership evidence to resolve before sharing")
    source = _latest_observation(db, item)
    if (not source or (source.facts or {}).get("force_review")
            or _cancellation_state(db, item.user_id, source)):
        raise HTTPException(422, "This flight has conflicting or cancellation evidence to resolve before sharing")
    if not name and not allow_unassigned:
        raise HTTPException(422, "Assign this flight to a traveler first")
    if passenger_name and normalize_name(name).casefold() != passenger_name.casefold():
        raise HTTPException(422, "Select flights for one traveler at a time")
    return _flight_snapshot(row)


def inbox_item_view(db, owner_id, item):
    row = serialize_item(db, owner_id, item)
    assignment = _assignment(db, owner_id, item.id)
    row["assigned_passenger_name"] = assignment.passenger_name if assignment else None
    row["requires_assignment"] = False
    try:
        _validate_item(db, item)
        row.update(shareable=True, share_blocked_reason=None)
    except HTTPException as exc:
        row.update(shareable=False, share_blocked_reason=str(exc.detail))
        if not (row["assigned_passenger_name"] or item.passenger_name):
            try:
                _validate_item(db, item, allow_unassigned=True)
                row["requires_assignment"] = True
            except HTTPException:
                pass
    return row


def inbox(db, user):
    from .auth_identities import verified_emails
    items = db.query(TravelInboxItem).filter_by(user_id=user.id).order_by(TravelInboxItem.created_at.desc(), TravelInboxItem.id).limit(MAX_INBOX_RECORDS + 1).all()
    incoming = db.query(FlightShare).filter(func.lower(FlightShare.recipient_email).in_(verified_emails(db, user))).order_by(FlightShare.created_at.desc()).limit(MAX_INBOX_RECORDS + 1).all()
    outgoing = db.query(FlightShare).filter_by(sender_id=user.id).order_by(FlightShare.created_at.desc()).limit(MAX_INBOX_RECORDS + 1).all()
    if any(len(rows) > MAX_INBOX_RECORDS for rows in (items, incoming, outgoing)):
        raise HTTPException(409, "This inbox is too large to load at once. Contact support to retrieve the complete archive.")
    views = [inbox_item_view(db, user.id, item) for item in items]
    return {"items": [row for row in views if row["status"] != "belongs_to_you"],
            "incoming": [share_view(db, row) for row in incoming], "outgoing": [share_view(db, row) for row in outgoing]}


def assign(db, user, item_id, passenger_name):
    item = _item(db, user.id, item_id)
    name = normalize_name(passenger_name)
    if item.passenger_name and normalize_name(item.passenger_name).casefold() != name.casefold():
        raise HTTPException(422, "This ticket already names a different traveler; its passenger evidence cannot be relabeled")
    if serialize_item(db, user.id, item)["status"] in {"canceled", "belongs_to_you"}:
        raise HTTPException(422, "This flight cannot be assigned to another traveler")
    assignment = _assignment(db, user.id, item.id)
    if not assignment:
        assignment = TravelInboxAssignment(item_id=item.id, user_id=user.id)
        db.add(assignment)
    assignment.passenger_name = name
    assignment.updated_at = utcnow()
    db.flush()
    return inbox_item_view(db, user.id, item)


def _share_url(share):
    origin = (os.getenv("TROTTER_API_URL") or os.getenv("BACKEND_URL") or "http://localhost:8000").rstrip("/")
    parsed = urlparse(origin)
    if parsed.scheme not in {"https", "http"} or not parsed.netloc or parsed.username or parsed.password:
        raise RuntimeError("TROTTER_API_URL must be the public API origin")
    if os.getenv("TROTTER_ENV") == "production" and parsed.scheme != "https":
        raise RuntimeError("Flight invitations require HTTPS in production")
    token = decrypt_refresh_token(share.token_encrypted)
    return f"{origin}/travel-sharing/open#token={token}"


def create_share(db, user, item_ids, recipient_email, passenger_name, client_request_id=None):
    from .auth_identities import verified_emails
    recipient = normalize_email(recipient_email)
    name = normalize_name(passenger_name)
    if recipient in verified_emails(db, user):
        raise HTTPException(422, "Choose another traveler's Trotter sign-in email")
    if not 1 <= len(item_ids) <= 40 or len(set(item_ids)) != len(item_ids):
        raise HTTPException(422, "Select between 1 and 40 distinct flights")
    request_id = str(client_request_id or uuid4())
    request_hash = _key({"items": sorted(item_ids), "recipient": recipient, "name": name})
    existing = db.query(FlightShare).filter_by(sender_id=user.id, client_request_id=request_id).first()
    if existing:
        if existing.request_hash != request_hash:
            raise HTTPException(409, "This request was already used for a different invitation")
        return {"share": share_view(db, existing), "share_url": _share_url(existing)}
    items = [_item(db, user.id, item_id) for item_id in item_ids]
    flights = [_validate_item(db, item, passenger_name=name) for item in items]
    scopes = {(row["travel_date"], row["dep_airport"], row["arr_airport"], row["flight_number"]) for row in flights}
    if len(scopes) != len(flights):
        raise HTTPException(422, "The selection contains more than one copy of the same flight")
    token = secrets.token_urlsafe(32)
    now = utcnow()
    share = FlightShare(sender_id=user.id, recipient_email=recipient, passenger_name=name,
        client_request_id=request_id, request_hash=request_hash,
        token_hash=sha256(token.encode()).hexdigest(), token_encrypted=encrypt_refresh_token(token),
        item_ids=list(item_ids), flights=sorted(flights, key=lambda row: row["dep_time"]), status="pending",
        created_at=now, updated_at=now, expires_at=now + timedelta(days=SHARE_DAYS), accepted_segment_ids=[])
    db.add(share)
    db.flush()
    return {"share": share_view(db, share), "share_url": _share_url(share)}


def authorized_share(db, user, share_id=None, *, token=None, role=None, locked=False):
    from .auth_identities import verified_emails
    query = db.query(FlightShare)
    if token is not None:
        if not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
            raise HTTPException(404, "Invitation not found for this account")
        query = query.filter_by(token_hash=sha256(token.encode()).hexdigest())
    else:
        query = query.filter_by(id=share_id)
    if locked:
        query = query.populate_existing().with_for_update()
    share = query.first()
    is_sender = bool(share and share.sender_id == user.id)
    is_recipient = bool(share and share.recipient_email.casefold() in verified_emails(db, user))
    allowed = is_sender if role == "sender" else is_recipient if role == "recipient" else is_sender or is_recipient
    if not allowed:
        raise HTTPException(404, "Invitation not found for this account")
    return share


def transition(db, user, share_id, action):
    role = "sender" if action == "revoke" else "recipient"
    share = authorized_share(db, user, share_id, role=role, locked=True)
    target = "revoked" if action == "revoke" else "declined"
    status = _share_status(share)
    if status == target:
        return {"share": share_view(db, share)}
    if status != "pending":
        raise HTTPException(409, f"This invitation is {status}")
    share.status = target
    share.updated_at = utcnow()
    return {"share": share_view(db, share)}


def _duplicate(segments, row):
    dep = event_time(row["dep_time"])
    for segment in segments:
        number = _normalize_flight_number(segment.flight_number) or ""
        same_route = segment.dep_airport == row["dep_airport"] and segment.arr_airport == row["arr_airport"]
        when = event_time(segment.dep_time)
        if same_route and when.date() == dep.date():
            if number == row["flight_number"] or (not number and when == dep):
                return segment
            # An overlapping flight with different details must not be overwritten
            # or duplicated by the builder's legacy same-trip collision fallback.
            if when == dep:
                raise HTTPException(409, "A flight already in your trips has conflicting details for this departure")
        if number == row["flight_number"] and when == dep and not same_route:
            raise HTTPException(409, "A flight already in your trips has a different route for this departure")
    return None


def accept_share(db, user, share_id):
    initial = authorized_share(db, user, share_id, role="recipient")
    # The sender lock stabilizes the source cancellation/identity snapshot while
    # the recipient lock serializes acceptance with Gmail imports and repairs.
    try:
        with ExitStack() as locks:
            for owner_id in sorted({user.id, initial.sender_id}):
                locks.enter_context(user_import_lock(db.get_bind(), owner_id))
            share = authorized_share(db, user, share_id, role="recipient", locked=True)
            status = _share_status(share)
            if status == "accepted":
                return {"share": share_view(db, share), "added_flights": share.added_flights, "existing_flights": share.existing_flights}
            if status != "pending":
                raise HTTPException(409, f"This invitation is {status}")
            source_items = [_item(db, share.sender_id, item_id) for item_id in share.item_ids]
            current = [_validate_item(db, item, passenger_name=share.passenger_name) for item in source_items]
            if sorted(current, key=lambda row: row["dep_time"]) != share.flights:
                raise HTTPException(409, "The booking changed after this invitation. Ask the sender for a new invitation")
            source_times = {_key(row): event_time(_latest_observation(db, item).source_event_at)
                            for item, row in zip(source_items, current)}
            segments = db.query(Segment).join(Trip).filter(Trip.user_id == user.id).all()
            existing, missing = [], []
            for row in share.flights:
                duplicate = _duplicate(segments, row)
                if duplicate:
                    existing.append(duplicate.id)
                else:
                    missing.append(row)
            now = utcnow()
            def parsed(row):
                return SimpleNamespace(dep_airport=row["dep_airport"], arr_airport=row["arr_airport"],
                    dep_time=event_time(row["dep_time"]), arr_time=event_time(row["arr_time"]),
                    airline=row["airline"], flight_number=row["flight_number"], pnr=None, pnr_aliases=[],
                    source="accepted_flight_share", source_received_at=source_times[_key(row)], confidence=1.0,
                    ownership="self", passenger_names=[], passenger_evidence=[{"reason": "recipient_accepted", "share_id": share.id}],
                    aircraft=None, nonstop=False, force_review=False)
            source_id = f"flight-share:{share.id}"
            # The ledger stores only the allowlisted snapshot and explicit recipient
            # acceptance. Existing flights are linked as evidence, never refreshed.
            record_flight_observations(db, user.id, [parsed(row) for row in share.flights], source_message_id=source_id)
            result = build_segments_and_trips_detailed(db, user.id, [parsed(row) for row in missing], source_message_id=source_id)
            if result.inserted != len(missing) or result.updated or result.held:
                raise HTTPException(409, "These flights could not be added without changing existing travel. No flights were changed")
            after = db.query(Segment).join(Trip).filter(Trip.user_id == user.id).all()
            accepted_ids = [segment.id for row in share.flights if (segment := _duplicate(after, row))]
            if len(accepted_ids) != len(share.flights):
                raise RuntimeError("Accepted flight verification failed")
            share.status = "accepted"
            share.recipient_user_id = user.id
            share.accepted_at = share.updated_at = now
            share.added_flights, share.existing_flights = len(missing), len(existing)
            share.accepted_segment_ids = accepted_ids
            db.commit()  # Keep both import locks through the atomic commit.
            return {"share": share_view(db, share), "added_flights": len(missing), "existing_flights": len(existing)}
    except ImportAlreadyRunning as exc:
        db.rollback()
        raise HTTPException(409, "A flight import is running. Try accepting again shortly") from exc
    except Exception:
        db.rollback()
        raise
