"""Persisted, account-scoped preview/apply of exact parsed mailbox evidence.

No mailbox discovery or arbitrary flight inserts occur here. Preparation accepts
the shared parser's payloads; only their facts and source digests are retained.
Both preview and apply run the same ledger/builder path under the import lock.
The caller commits a preview manifest. Apply commits its complete transaction
while still holding the account lock, never individual operations.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from ..models import (BookingCancellation, BookingObservation, BookingRepairManifest, FlightShare,
    ItineraryHistory, Message, MessageStatus, Segment, TravelInboxEvidence, TravelInboxItem, Trip, User)
from .booking_import import _cancellation_intent, _date, booking_event_time, booking_time_provenance, booking_time_text, visible_message_text
from .booking_ledger import _json_value, _key, event_time, flight_facts, record_flight_observations, snapshot_user_itinerary
from .booking_reconciliation import (current_document_versions, flight_key, local_day, matches,
    identical_schedule, observation_codes, observation_groups, original_source, resolve_group, strictly_newer)
from .builder import build_segments_and_trips_detailed
from .import_lock import user_import_lock
from .travel_name_recovery import active_shares_for_item, flight_from, names_for, recovery_blocked


class RepairConflict(ValueError):
    pass


def _rows(rows):
    return {str(row.id): {column.name: _json_value(getattr(row, column.name)) for column in row.__table__.columns}
            for row in rows}


def _state(db, user_id, message_ids):
    user = db.get(User, user_id)
    if not user:
        raise RepairConflict('Account not found')
    return {
        'identity': {'id': user.id, 'name': user.name, 'aliases': user.travel_name_aliases or [],
                     'confirmed': _json_value(user.travel_names_confirmed_at)},
        'segments': _rows(db.query(Segment).join(Trip).filter(Trip.user_id == user_id).all()),
        'trips': _rows(db.query(Trip).filter_by(user_id=user_id).all()),
        'observations': _rows(db.query(BookingObservation).filter_by(user_id=user_id).all()),
        'cancellations': _rows(db.query(BookingCancellation).filter_by(user_id=user_id).all()),
        'inbox': _rows(db.query(TravelInboxItem).filter_by(user_id=user_id).all()),
        'shares': _rows(db.query(FlightShare).filter_by(sender_id=user_id).all()),
        'messages': _rows(db.query(Message).filter(Message.user_id == user_id, Message.id.in_(message_ids)).all()),
    }


def _source_facts(db, user_id, prepared):
    from .parser import PARSER_VERSION
    provider_id = prepared['msg_id']
    message = db.query(Message).filter_by(user_id=user_id, provider_msg_id=provider_id).one_or_none()
    if not message:
        raise RepairConflict('Every repair source must be an existing message owned by this account')
    text = visible_message_text(prepared.get('plain_text', ''), prepared.get('html', ''))
    subject = prepared.get('subject', '')
    received = prepared.get('received_at')
    time_text = booking_time_text(prepared.get('plain_text', ''), prepared.get('html', ''))
    event = booking_event_time(received, subject, time_text)
    provenance = booking_time_provenance(received, subject, time_text)
    cancellation = _cancellation_intent(subject, text)
    parsed = prepared.get('parse_result')
    flights = []
    for item in deepcopy(parsed.flights if parsed else []):
        item.force_review = bool(getattr(item, 'force_review', False))
        item.source_received_at = event
        item.mail_received_at = _date(received)
        item.source_time_provenance = provenance
        item.parser_version = PARSER_VERSION
        flights.append(flight_facts(item))
    return {'message_id': message.id, 'provider_msg_id': provider_id,
        'source_digest': _key({'message': prepared.get('full_msg'), 'documents': prepared.get('document_provenance')}),
        'parser_version': PARSER_VERSION, 'source_event_at': _json_value(event),
        'internal_ts': _json_value(prepared.get('internal_ts')), 'flights': flights,
        'excluded_reason': 'cancellation_source_requires_separate_review' if cancellation else None}


def _flight(facts):
    result = deepcopy(facts)
    for key in ('dep_time', 'arr_time', 'source_received_at', 'mail_received_at'):
        result[key] = event_time(result.get(key))
    return SimpleNamespace(**result)


def _select(source, selector):
    matches_ = [(index, facts) for index, facts in enumerate(source['flights'])
        if ''.join(str(facts.get('flight_number') or '').split()).upper() == selector.get('flight_number')
        and ((facts.get('time_provenance') or {}).get('departure_local_date')
             or (event_time(facts.get('dep_time')).date().isoformat() if facts.get('dep_time') else None))
        == selector.get('departure_local_date')]
    if len(matches_) != 1:
        raise RepairConflict('Schedule links must identify exactly one parsed flight in each source')
    return matches_[0][0]


def _validate_source(db, user_id, source):
    message = db.query(Message).filter_by(id=source['message_id'], user_id=user_id,
        provider_msg_id=source['provider_msg_id']).one_or_none()
    if not message:
        raise RepairConflict('Source ownership or identity changed')
    if not isinstance(source.get('source_digest'), str) or len(source['source_digest']) != 64:
        raise RepairConflict('Missing immutable source digest')
    return message


def _semantic_segment(row):
    return {key: row[key] for key in ('dep_airport', 'arr_airport', 'dep_time', 'arr_time', 'airline', 'flight_number', 'pnr')} | {
        'time_provenance': (row.get('meta_json') or {}).get('time_provenance')}


def _duplicate_keys(state):
    result = Counter()
    for row in state['segments'].values():
        meta = row.get('meta_json') or {}
        day = (meta.get('time_provenance') or {}).get('departure_local_date') or str(row['dep_time'])[:10]
        result[(row['pnr'], row['dep_airport'], row['arr_airport'], row['flight_number'], day)] += 1
    return result


def _preview(before, after, held, message_ids):
    lost = set(before['segments']) - set(after['segments'])
    if lost:
        raise RepairConflict(f'Repair would remove existing segment IDs: {sorted(lost)}')
    for table in ('observations', 'cancellations', 'shares'):
        if any(after[table].get(key) != row for key, row in before[table].items()):
            raise RepairConflict(f'Repair would alter retained {table}')
    if set(before['inbox']) - set(after['inbox']):
        raise RepairConflict('Repair would remove retained tickets')
    prior, current = _duplicate_keys(before), _duplicate_keys(after)
    if any(count > max(1, prior[key]) for key, count in current.items()):
        raise RepairConflict('Repair would create a duplicate booking leg')
    added = [_semantic_segment(row) for key, row in after['segments'].items() if key not in before['segments']]
    updated = [{'segment_id': int(key), 'before': _semantic_segment(before['segments'][key]),
                'after': _semantic_segment(row)} for key, row in after['segments'].items()
               if key in before['segments'] and _semantic_segment(before['segments'][key]) != _semantic_segment(row)]
    def membership(state, trip_id):
        return sorted([_semantic_segment(row) for row in state['segments'].values() if row['trip_id'] == trip_id], key=_key)
    trip_changes = []
    for key, old in before['segments'].items():
        current = after['segments'][key]
        previous_members, current_members = membership(before, old['trip_id']), membership(after, current['trip_id'])
        if previous_members != current_members:
            trip_changes.append({'existing_segment_id': int(key), 'from_trip_id': old['trip_id'],
                                 'from_flights': previous_members, 'to_flights': current_members})
    return {'added': sorted(added, key=_key), 'updated': sorted(updated, key=lambda row: row['segment_id']),
        'trip_changes': sorted(trip_changes, key=lambda row: row['existing_segment_id']),
        'preserved_segment_ids': sorted(int(key) for key in before['segments']),
        'flights_before': len(before['segments']), 'flights_after': len(after['segments']),
        'trips_before': len(before['trips']), 'trips_after': len(after['trips']),
        'retained_observations_added': len(after['observations']) - len(before['observations']),
        'retained_tickets_added': len(after['inbox']) - len(before['inbox']),
        'held': sorted(held, key=_key), 'message_ids': sorted(message_ids),
        'invariants': {'existing_segment_ids_preserved': True, 'original_evidence_unchanged': True,
            'cancellations_unchanged': True, 'shares_unchanged': True, 'no_new_duplicate_legs': True}}


def _covered_body_placeholder(row, projected):
    facts = row.facts or {}
    if row.flight_number or row.pnr or facts.get('force_review') or facts.get('passenger_evidence') or any(facts.get('passenger_names') or []):
        return False
    # Body headings may contain only a route/date and no ticket facts. An exact
    # same-message PDF leg can resolve that heading without inventing ownership
    # for another document, route, date, or named passenger.
    complete = [other for other in projected if other.source_message_id == row.source_message_id
        and other.dep_airport == row.dep_airport and other.arr_airport == row.arr_airport
        and local_day(other) == local_day(row) and other.flight_number and other.pnr
        and (other.facts or {}).get('document_provenance')]
    return len({flight_key(other) for other in complete}) == 1


def _run(db, user_id, manifest, repair_id):
    sources = manifest['sources']
    message_ids = [row['message_id'] for row in sources]
    before = _state(db, user_id, message_ids)
    user = db.get(User, user_id)
    snapshot_user_itinerary(db, user_id, reason='before_controlled_booking_repair')
    records, selected_ids, held, source_by_id = {}, set(), [], {row['message_id']: row for row in sources}
    # Retain every original parse before projecting any personal itinerary.
    for source in sources:
        _validate_source(db, user_id, source)
        if source['excluded_reason']:
            held.append({'message_id': source['message_id'], 'reason': source['excluded_reason']}); continue
        flights = [_flight(facts) for facts in source['flights']]
        record_flight_observations(db, user_id, flights, source_message_id=source['provider_msg_id'],
            source_event_at=event_time(source['source_event_at']))
        for index, flight in enumerate(flights):
            digest = _key({'message': source['provider_msg_id'], 'event_at': event_time(source['source_event_at']), 'facts': flight_facts(flight)})
            row = db.query(BookingObservation).filter_by(user_id=user_id, evidence_key=digest).one()
            records[(source['message_id'], index)] = row
            selected_ids.add(row.id)

    all_rows = db.query(BookingObservation).filter_by(user_id=user_id).all()
    projections, suppressed, unresolved, projected_ids = [], set(), [], set()
    for link in manifest['schedule_links']:
        left_source, right_source = (source_by_id.get(link[side]['message_id']) for side in ('from', 'to'))
        if not left_source or not right_source:
            raise RepairConflict('Schedule links must use sources in this exact manifest')
        left = records[(left_source['message_id'], _select(left_source, link['from']))]
        right = records[(right_source['message_id'], _select(right_source, link['to']))]
        left_day, right_day = datetime.fromisoformat(local_day(left)), datetime.fromisoformat(local_day(right))
        if (flight_key(left)[1:] != flight_key(right)[1:] or not observation_codes(left).intersection(observation_codes(right))
                or not 0 < abs((right_day - left_day).days) <= 2 or not strictly_newer(right, left)):
            raise RepairConflict('Schedule link needs a newer source for the same explicitly linked booking and flight')
        if not matches(left, names_for(user)):
            raise RepairConflict('Schedule link lacks affirmative owner passenger evidence')
        related = [row for row in all_rows if original_source(row) and flight_key(row) == flight_key(left)
                   and observation_codes(row).intersection(observation_codes(left))]
        target_related = [row for row in all_rows if original_source(row) and flight_key(row) == flight_key(right)
                          and observation_codes(row).intersection(observation_codes(right))]
        resolved = resolve_group([*related, *target_related], names_for(user))
        if (resolved.review_reason or not resolved.schedule or flight_key(resolved.schedule) != flight_key(right)
                or not identical_schedule(resolved.schedule, right)):
            raise RepairConflict('Schedule link has ambiguous passenger or chronology evidence')
        # The explicit projection handles both old and replacement evidence;
        # do not report its unnamed duplicate as a separate unrecovered flight.
        suppressed.update(row.id for row in [*related, *target_related])
        projections.append((resolved, [*related, *target_related], True))

    for group in observation_groups(all_rows):
        if not selected_ids.intersection(row.id for row in group) or suppressed.intersection(row.id for row in group):
            continue
        resolved = resolve_group(group, names_for(user))
        if resolved.review_reason or not resolved.schedule:
            unresolved.append((group, resolved.review_reason or 'passenger_not_confirmed'))
            continue
        if any(resolved.schedule.id == projection[0].schedule.id for projection in projections):
            continue
        projections.append((resolved, group, False))

    for resolved, group, is_link in projections:
        proof_sources = current_document_versions(group)
        blocked = any(recovery_blocked(db, user_id, row, flight_from(row), names_for(user))
                      for row in proof_sources if matches(row, names_for(user)) or row is resolved.schedule)
        matching_items = db.query(TravelInboxItem).join(TravelInboxEvidence).filter(
            TravelInboxItem.user_id == user_id, TravelInboxEvidence.observation_id.in_([row.id for row in group])).all()
        if blocked or any(active_shares_for_item(db, user_id, item.id) for item in matching_items):
            if is_link:
                raise RepairConflict('Schedule link is canceled, manually held, incomplete, or actively shared')
            held.append({'flight_number': resolved.schedule.flight_number, 'reason': 'protected_or_incomplete_booking'}); continue
        flight = flight_from(resolved.schedule)
        flight.source = 'booking_repair_reconciliation'
        flight.passenger_evidence = resolved.passenger_evidence
        flight.passenger_names = list(dict.fromkeys(entry['name'] for entry in resolved.passenger_evidence))
        flight.recovery_observation_ids = sorted(row.id for row in group)
        flight.reconciles_observation_ids = sorted(row.id for row in group) if is_link else []
        result = build_segments_and_trips_detailed(db, user_id, [flight],
            source_message_id=f'booking-repair:{repair_id}:{resolved.schedule.source_message_id}',
            source_event_at=event_time(resolved.schedule.source_event_at))
        if result.held or result.removed_other:
            raise RepairConflict('Projection was blocked after reconciliation')
        projected_ids.update(row.id for row in group)

    projected = [row for row in all_rows if row.id in projected_ids]
    covered_ids = {row.id for row in all_rows if _covered_body_placeholder(row, projected)}
    for group, reason in unresolved:
        if all(row.id in covered_ids for row in group):
            continue
        held.append({'message_ids': sorted({next((source['message_id'] for source in sources
            if source['provider_msg_id'] == row.source_message_id), 0) for row in group} - {0}),
            'flight_number': group[0].flight_number, 'reason': reason})

    for source in sources:
        if source['excluded_reason'] or not source['flights']:
            continue
        message = _validate_source(db, user_id, source)
        message.internal_ts = event_time(source['internal_ts']) or message.internal_ts
        message.parse_version = source['parser_version']
        message.parse_evidence = {**(message.parse_evidence or {}), 'controlled_repair_id': repair_id,
            'source_digest': source['source_digest'], 'source': 'controlled_reparse'}
        source_rows = [records[(source['message_id'], index)] for index in range(len(source['flights']))]
        if all(row.id in projected_ids | covered_ids for row in source_rows):
            if message.parse_error:
                message.parse_evidence = {**message.parse_evidence, 'original_review_error': message.parse_error}
            message.status = MessageStatus.ACCEPTED
            message.parse_error = None
            message.parse_evidence = {**message.parse_evidence, 'resolved': True}
    db.flush()
    after = _state(db, user_id, message_ids)
    # Any prior trip that merges away is fully preserved by the pre-repair ledger.
    removed_trips = set(before['trips']) - set(after['trips'])
    for trip_id in removed_trips:
        history = db.query(ItineraryHistory).filter_by(user_id=user_id, entity_type='trip', entity_id=int(trip_id),
            reason='before_controlled_booking_repair').all()
        if not any(row.snapshot == before['trips'][trip_id] for row in history):
            raise RepairConflict('Merged trip lacks a complete original snapshot')
    return _preview(before, after, held, message_ids)


def prepare_repair(db, user_id, prepared_messages, *, schedule_links=()):
    """Dry-run and persist the exact preview. Caller commits after inspecting it."""
    with user_import_lock(db.get_bind(), user_id):
        sources = [_source_facts(db, user_id, prepared) for prepared in prepared_messages]
        ids = [row['message_id'] for row in sources]
        if len(set(ids)) != len(ids) or not ids:
            raise RepairConflict('Select each source message exactly once')
        manifest = {'version': 1, 'user_id': user_id, 'sources': sorted(sources, key=lambda row: row['message_id']),
                    'schedule_links': deepcopy(list(schedule_links))}
        before = _state(db, user_id, ids)
        repair_id = str(uuid4())
        savepoint = db.begin_nested()
        try:
            preview = _run(db, user_id, manifest, repair_id)
        finally:
            savepoint.rollback(); db.expire_all()
        if _state(db, user_id, ids) != before:
            raise RepairConflict('Preview rollback changed the account')
        base = _key(before)
        digest = _key({'manifest': manifest, 'base_fingerprint': base, 'preview': preview})
        existing = db.query(BookingRepairManifest).filter_by(user_id=user_id, plan_hash=digest).one_or_none()
        if existing:
            return existing
        row = BookingRepairManifest(id=repair_id, user_id=user_id, schema_version=1, state='previewed',
            base_fingerprint=base, plan_hash=digest, manifest_json=manifest, preview_json=preview)
        db.add(row); db.flush()
        return row


def apply_repair(db, user_id, manifest_id, *, expected_plan_hash):
    """Apply only the reviewed persisted plan; stale/edited plans fail closed."""
    if db.new or db.dirty or db.deleted:
        raise RepairConflict('Apply requires a clean dedicated session with no pending changes')
    with user_import_lock(db.get_bind(), user_id):
        row = db.query(BookingRepairManifest).filter_by(id=manifest_id, user_id=user_id).one_or_none()
        if not row:
            raise RepairConflict('Repair manifest not found for this account')
        expected = _key({'manifest': row.manifest_json, 'base_fingerprint': row.base_fingerprint, 'preview': row.preview_json})
        if row.plan_hash != expected_plan_hash or row.plan_hash != expected:
            raise RepairConflict('Repair manifest checksum does not match the reviewed plan')
        if row.state == 'applied':
            return deepcopy(row.result_json)
        manifest = row.manifest_json
        if row.schema_version != 1 or manifest.get('version') != 1 or manifest.get('user_id') != user_id:
            raise RepairConflict('Unsupported repair scope or version')
        ids = [source['message_id'] for source in manifest['sources']]
        if _key(_state(db, user_id, ids)) != row.base_fingerprint:
            raise RepairConflict('Account data changed after preview. Prepare and review a new plan.')
        # Keep the caller's transaction usable and leave the plan retryable on any failure.
        savepoint = db.begin_nested()
        try:
            result = _run(db, user_id, manifest, row.id)
            if result != row.preview_json:
                raise RepairConflict('Applied results differ from the reviewed preview')
            row.state = 'applied'; row.applied_at = datetime.now(timezone.utc); row.result_json = result
            db.flush(); savepoint.commit(); db.commit()
            return deepcopy(result)
        except Exception:
            if savepoint.is_active:
                savepoint.rollback()
            else:
                db.rollback()
            db.expire_all(); raise
