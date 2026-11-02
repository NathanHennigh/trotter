"""Explicit, reviewed corrections for records created before source-leg tracking.

This is an operator-only preview/apply utility, never called by normal scanning.
Each legacy record and its successor must be named in the reviewed manifest;
no matching by timestamp, route proximity or repeated flight number is inferred.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from uuid import uuid4

from ..models import (BookingCancellation, BookingObservation, BookingRepairManifest,
    FlightShare, ItineraryHistory, Segment, TravelInboxAssignment, Trip, User)
from .booking_ledger import _json_value, _key, booking_code, event_time, snapshot_user_itinerary
from .booking_reconciliation import ambiguous, matches, original_source, flight_key, resolve_group
from .booking_repair import RepairConflict, _rows, _state as booking_state, _semantic_segment
from .builder import _normalize_flight_number, _refresh_existing_segment, rebuild_affected_trips
from .import_lock import user_import_lock
from .travel_name_recovery import flight_from, names_for, recovery_blocked


def _state(db, user_id):
    from ..models import Message, TravelInboxEvidence, TravelInboxItem, CarrierTravelEvidence
    ids = [row[0] for row in db.query(Message.id).filter_by(user_id=user_id)]
    value = booking_state(db, user_id, ids)
    value['assignments'] = {
        row.item_id: {col.name: _json_value(getattr(row, col.name)) for col in row.__table__.columns}
        for row in db.query(TravelInboxAssignment).filter_by(user_id=user_id)}
    value['received_shares'] = _rows(db.query(FlightShare).filter_by(recipient_user_id=user_id).all())
    value['history'] = _rows(db.query(ItineraryHistory).filter_by(user_id=user_id).all())
    value['retained_links'] = _rows(db.query(TravelInboxEvidence).join(TravelInboxItem).filter(TravelInboxItem.user_id == user_id).all())
    value['carrier_evidence'] = _rows(db.query(CarrierTravelEvidence).filter_by(user_id=user_id).all())
    return value


def _protected(db, user_id, segment):
    meta = segment.meta_json or {}
    if (meta.get('source') in {'manual', 'user_review', 'accepted_flight_share', 'flight_share'}
            or any(meta.get(key) for key in ('personal_note', 'manual', 'manually_edited', 'user_edited'))):
        return True
    code = booking_code(segment.pnr)
    codes = {code, *(booking_code(value) for value in meta.get('pnr_aliases') or [])} - {None}
    number = _normalize_flight_number(segment.flight_number)
    for row in db.query(BookingObservation).filter_by(user_id=user_id).all():
        if ((row.facts or {}).get('user_decision') and booking_code(row.pnr) in codes
                and _normalize_flight_number(row.flight_number) == number):
            return True
    # A legacy date may itself be wrong. Any cancellation of this booking/number
    # requires separate adjudication; do not evade it using the corrected date.
    for row in db.query(BookingCancellation).filter(BookingCancellation.user_id == user_id, BookingCancellation.pnr.in_(codes)).all() if codes else []:
        if not row.scopes or any(_normalize_flight_number(scope.get('flight_number')) in {None, number} for scope in row.scopes):
            return True
    if any(segment.id in (row.accepted_segment_ids or []) for row in db.query(FlightShare).filter_by(recipient_user_id=user_id)):
        return True
    return False


def _same_legacy_wall_clocks(segment, evidence):
    if (segment.meta_json or {}).get('time_provenance'):
        return False
    if (segment.dep_airport, segment.arr_airport) != (evidence.dep_airport, evidence.arr_airport):
        return False
    proof = (evidence.facts or {}).get('time_provenance') or {}
    return all(event_time(getattr(segment, field)) == event_time((proof.get(endpoint) or {}).get('local'))
               for field, endpoint in (('dep_time', 'departure'), ('arr_time', 'arrival')))


def _require_current_document_leg(db, user_id, evidence, names):
    """Selected schedule and passenger originals must both remain current."""
    from .booking_leg_lineage import key as leg_key, _schedule
    facts = evidence.facts or {}
    revision = facts.get('parser_version')
    if type(revision) is not int or revision <= 0:
        raise RepairConflict('Selected source lacks a valid parser revision')
    rows = db.query(BookingObservation).filter_by(user_id=user_id,
        source_message_id=evidence.source_message_id).all()
    for row in rows:
        row_revision = (row.facts or {}).get('parser_version')
        if type(row_revision) is int and row_revision > revision:
            raise RepairConflict('Selected source has a newer parser revision')
    siblings = [row for row in rows
        if leg_key((row.facts or {}).get('source_leg')) == leg_key(facts.get('source_leg'))
        and (row.facts or {}).get('parser_version') == revision]
    if any(ambiguous(row) or row.ownership != evidence.ownership
           or row.ownership == 'self' and not matches(row, names)
           or _schedule(row) != _schedule(evidence) or row.pnr != evidence.pnr
           or event_time(row.source_event_at) != event_time(evidence.source_event_at) for row in siblings):
        raise RepairConflict('Selected document leg has conflicting current evidence')


def _trip_projection(before, after):
    """Compare new trips by their members, never by a rolled-back sequence ID.

    Existing trip and segment IDs retain their exact identity. Only explicit
    references to newly created trips are substituted; integers in metadata,
    observations and other records are never rewritten.
    """
    members = {key: [] for key in after['trips']}
    for segment_id, row in after['segments'].items():
        trip_id = str(row['trip_id'])
        if trip_id not in members:
            raise RepairConflict('Flight references a trip outside the reviewed account')
        members[trip_id].append(int(segment_id))
    references, allocated, memberships, trips = {}, {}, {}, {}
    for trip_id, row in after['trips'].items():
        flights = sorted(members[trip_id])
        if trip_id in before['trips']:
            reference = int(trip_id)
        else:
            if not flights:
                raise RepairConflict('Repair unexpectedly created an empty trip')
            reference = 'new:' + _key(flights)
            if reference in allocated:
                raise RepairConflict('New trip identities are ambiguous')
            allocated[reference] = int(trip_id)
        references[trip_id] = reference
        memberships[str(reference)] = flights
        trips[str(reference)] = {**deepcopy(row), 'id': reference}
    segments = {key: {**deepcopy(row), 'trip_id': references[str(row['trip_id'])]}
                for key, row in after['segments'].items()}
    return memberships, {'trips': trips, 'segments': segments}, allocated


def _run(db, user_id, manifest):
    from ..models import TravelInboxEvidence, TravelInboxItem
    from .travel_name_recovery import active_shares_for_item
    from .booking_leg_lineage import key as leg_key, _segment_schedule, _schedule
    if not manifest['corrections']:
        raise RepairConflict('Select at least one reviewed correction')
    before = _state(db, user_id)
    user = db.get(User, user_id)
    used, retired, affected, updates = set(), set(), set(), []
    validated = []
    for spec in manifest['corrections']:
        if not isinstance(spec.get('reason'), str) or not spec['reason'].strip():
            raise RepairConflict('Legacy corrections require an explicit source-review reason')
        segment = db.query(Segment).join(Trip).filter(Trip.user_id == user_id, Segment.id == spec['segment_id']).one_or_none()
        evidence = db.query(BookingObservation).filter_by(user_id=user_id, id=spec['target_observation_id']).one_or_none()
        if not segment or not evidence or not original_source(evidence):
            raise RepairConflict('Correction must use an existing account flight and original account evidence')
        facts = evidence.facts or {}
        target = flight_from(evidence)
        proof_ids = spec.get('passenger_proof_observation_ids') or []
        proofs = db.query(BookingObservation).filter(BookingObservation.user_id == user_id,
            BookingObservation.id.in_(proof_ids)).all() if proof_ids else []
        if len(proofs) != len(proof_ids) or len(proofs) > 4:
            raise RepairConflict('Passenger proof must identify up to four unique account originals')
        if any(not original_source(row) or ambiguous(row) or row.ownership != 'self'
               or not matches(row, names_for(user)) or not leg_key((row.facts or {}).get('source_leg'))
               or flight_key(row) != flight_key(evidence) or row.pnr != evidence.pnr
               or recovery_blocked(db, user_id, row, flight_from(row), names_for(user)) for row in proofs):
            raise RepairConflict('Passenger proof must be the same explicit booking and dated leg')
        for original in [evidence, *proofs]:
            _require_current_document_leg(db, user_id, original, names_for(user))
        resolved = resolve_group([evidence, *proofs], names_for(user))
        if (ambiguous(evidence) or evidence.ownership not in {'self', 'unknown'}
                or resolved.review_reason or not resolved.schedule or _schedule(resolved.schedule) != _schedule(evidence)
                or evidence.ownership == 'unknown' and not proofs
                or not leg_key(facts.get('source_leg'))
                or (facts.get('time_provenance') or {}).get('status') != 'normalized'
                or not event_time(evidence.source_event_at)
                or recovery_blocked(db, user_id, evidence, target, names_for(user))):
            raise RepairConflict('Target flight lacks complete, unambiguous, unprotected passenger/date evidence')
        target.passenger_evidence = resolved.passenger_evidence
        target.passenger_names = list(dict.fromkeys(entry['name'] for entry in resolved.passenger_evidence))
        others = []
        for segment_id in spec.get('superseded_segment_ids') or []:
            old = db.query(Segment).join(Trip).filter(Trip.user_id == user_id, Segment.id == segment_id).one_or_none()
            if not old:
                raise RepairConflict('Superseded flight is not in this account')
            others.append(old)
        for old in [segment, *others]:
            if old.id in used:
                raise RepairConflict('A flight may occur in only one correction role')
            used.add(old.id)
            if _protected(db, user_id, old):
                raise RepairConflict('Legacy flight has protected manual, cancellation or sharing history')
            if (_normalize_flight_number(old.flight_number) != _normalize_flight_number(evidence.flight_number)
                    or old.dep_airport != evidence.dep_airport
                    or old.pnr and booking_code(old.pnr) != booking_code(evidence.pnr)):
                raise RepairConflict('Reviewed legacy link must retain the passenger booking, carrier flight and origin')
            if old is not segment and ((old.meta_json or {}).get('time_provenance') or {}).get('status') == 'normalized':
                raise RepairConflict('A normalized independent flight cannot be retired by a legacy repair')
            previous_ids = (old.meta_json or {}).get('observation_ids') or []
            items = db.query(TravelInboxItem).join(TravelInboxEvidence).filter(
                TravelInboxItem.user_id == user_id, TravelInboxEvidence.observation_id.in_(previous_ids + [evidence.id, *proof_ids])).all()
            if any(db.get(TravelInboxAssignment, item.id) or active_shares_for_item(db, user_id, item.id) for item in items):
                raise RepairConflict('Correction touches assigned or actively shared evidence')
            affected.add(old.trip_id)
        # Never replace a verified later schedule with an older original.
        meta = segment.meta_json or {}
        if (event_time(meta.get('source_received_at'))
                and event_time(meta['source_received_at']) > event_time(evidence.source_event_at)
                and _segment_schedule(segment) != _schedule(evidence)
                and not _same_legacy_wall_clocks(segment, evidence)):
            raise RepairConflict('A later confirmed schedule already exists')
        validated.append((spec, segment, evidence, target, others))
    snapshot_user_itinerary(db, user_id, reason='before_reviewed_legacy_repair', segment_ids=used, trip_ids=affected)
    for spec, segment, evidence, target, others in validated:
        target.source = (evidence.facts or {}).get('source') or 'receipt'
        target.source_message_id, target.observation_id = evidence.source_message_id, evidence.id
        if not _refresh_existing_segment(db, segment, target, user_id=user_id, allow_overwrite=True):
            raise RepairConflict('Existing flight protection blocked correction')
        # A verified wall-clock-to-UTC correction may use an older complete
        # receipt while retaining a later legacy source timestamp. The normal
        # metadata merge intentionally keeps that chronology; the reviewed
        # projection must nevertheless carry the proof of its actual clocks.
        segment.meta_json = {**(segment.meta_json or {}),
            'time_provenance': deepcopy(target.time_provenance),
            'clock_observation_id': evidence.id}
        for old in others:
            link = {'superseded_segment_id': old.id, 'successor_segment_id': segment.id,
                    'target_observation_id': evidence.id, 'reason': spec['reason']}
            digest = _key(link)
            db.add(ItineraryHistory(user_id=user_id, entity_type='segment_link', entity_id=old.id,
                reason='reviewed_legacy_supersession', evidence_key=digest, snapshot=link))
            retired.add(old.id)
            db.delete(old)
        updates.append({'segment_id': segment.id, 'target_observation_id': evidence.id,
                        'passenger_proof_observation_ids': sorted(spec.get('passenger_proof_observation_ids') or []),
                        'superseded_segment_ids': sorted(old.id for old in others), 'reason': spec['reason']})
    db.flush()
    rebuild_affected_trips(db, user_id, affected)
    after = _state(db, user_id)
    if set(before['segments']) - set(after['segments']) != {str(value) for value in retired}:
        raise RepairConflict('Repair removed a flight outside the reviewed supersessions')
    if set(after['segments']) - set(before['segments']):
        raise RepairConflict('Legacy correction unexpectedly added a flight')
    for segment_id, original in before['segments'].items():
        if int(segment_id) in used:
            continue
        current = after['segments'][segment_id]
        if {k: v for k, v in current.items() if k != 'trip_id'} != {k: v for k, v in original.items() if k != 'trip_id'}:
            raise RepairConflict('Repair changed unrequested flight facts or metadata')
    if any(after['history'].get(key) != row for key, row in before['history'].items()):
        raise RepairConflict('Repair altered prior itinerary history')
    for table in ('observations', 'cancellations', 'inbox', 'retained_links', 'carrier_evidence',
                  'shares', 'received_shares', 'assignments', 'messages', 'identity'):
        if before[table] != after[table]:
            raise RepairConflict(f'Repair changed protected {table}')
    for old_id in retired:
        if not any(row.snapshot == before['segments'][str(old_id)] for row in db.query(ItineraryHistory).filter_by(
                user_id=user_id, entity_type='segment', entity_id=old_id, reason='before_reviewed_legacy_repair')):
            raise RepairConflict('Superseded flight lacks its full original snapshot')
    memberships, projection, allocated = _trip_projection(before, after)
    return {'corrections': updates, 'retired_segment_ids': sorted(retired),
        'flights_before': len(before['segments']), 'flights_after': len(after['segments']),
        'trips_before': len(before['trips']), 'trips_after': len(after['trips']),
        'updated': [{'segment_id': int(key), 'before': _semantic_segment(before['segments'][key]),
                     'after': _semantic_segment(row)} for key, row in after['segments'].items()
                    if key in before['segments'] and _semantic_segment(before['segments'][key]) != _semantic_segment(row)],
        'memberships': memberships, 'projection': projection, 'created_trip_ids': allocated,
        'original_evidence_preserved': True, 'supersessions_fully_snapshotted': True}


def prepare_legacy_repair(db, user_id, corrections):
    if db.new or db.dirty or db.deleted:
        raise RepairConflict('Prepare requires a clean dedicated session')
    with user_import_lock(db.get_bind(), user_id):
        before = _state(db, user_id)
        manifest = {'version': 3, 'user_id': user_id, 'corrections': deepcopy(corrections)}
        savepoint = db.begin_nested()
        try:
            preview = _run(db, user_id, manifest)
            # Preview allocations are temporary and PostgreSQL sequences do not
            # roll back. Persist only stable identities in the reviewed plan.
            preview.pop('created_trip_ids')
        finally:
            savepoint.rollback(); db.expire_all()
        if _state(db, user_id) != before:
            raise RepairConflict('Preview rollback changed the account')
        base = _key(before)
        digest = _key({'manifest': manifest, 'base_fingerprint': base, 'preview': preview})
        row = db.query(BookingRepairManifest).filter_by(user_id=user_id, plan_hash=digest).one_or_none()
        if not row:
            row = BookingRepairManifest(id=str(uuid4()), user_id=user_id, schema_version=3, state='previewed',
                base_fingerprint=base, plan_hash=digest, manifest_json=manifest, preview_json=preview)
            db.add(row); db.flush()
        return row


def apply_legacy_repair(db, user_id, manifest_id, *, expected_plan_hash):
    if db.new or db.dirty or db.deleted:
        raise RepairConflict('Apply requires a clean dedicated session')
    with user_import_lock(db.get_bind(), user_id):
        row = db.query(BookingRepairManifest).filter_by(user_id=user_id, id=manifest_id).one_or_none()
        if (not row or row.schema_version not in {2, 3}
                or row.manifest_json.get('version') != row.schema_version
                or row.manifest_json.get('user_id') != user_id):
            raise RepairConflict('Legacy repair manifest not found for this account')
        digest = _key({'manifest': row.manifest_json, 'base_fingerprint': row.base_fingerprint, 'preview': row.preview_json})
        if row.plan_hash != expected_plan_hash or row.plan_hash != digest:
            raise RepairConflict('Legacy repair manifest checksum changed')
        if row.state == 'applied':
            return deepcopy(row.result_json)
        if row.schema_version != 3:
            raise RepairConflict('Repair preview uses an older format; prepare a new plan')
        if _key(_state(db, user_id)) != row.base_fingerprint:
            raise RepairConflict('Account changed since preview; prepare a new plan')
        savepoint = db.begin_nested()
        try:
            result = _run(db, user_id, row.manifest_json)
            reviewed = {key: value for key, value in result.items() if key != 'created_trip_ids'}
            if reviewed != row.preview_json:
                raise RepairConflict('Application differs from reviewed preview')
            row.state, row.applied_at, row.result_json = 'applied', datetime.now(timezone.utc), result
            db.flush(); savepoint.commit(); db.commit()
            return deepcopy(result)
        except Exception:
            if savepoint.is_active:
                savepoint.rollback()
            else:
                db.rollback()
            db.expire_all()
            raise
