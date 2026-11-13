"""Reviewed retirement of a source-bound, unsupported legacy sparse projection.

This operator-only preview/apply path is never called by mailbox scanning. It
retains complete snapshots and a narrow source hold; absent parser output alone
does not authorize removing a flight.
"""
from copy import deepcopy
from datetime import datetime, timezone
from uuid import uuid4

from ..models import (BookingObservation, BookingRepairManifest, ItineraryHistory,
                      Segment, TravelInboxAssignment, TravelInboxEvidence, TravelInboxItem, Trip)
from .booking_ledger import _key, event_time, flight_scope, snapshot_user_itinerary
from .booking_legacy_repair import _protected, _state
from .booking_repair import RepairConflict, _source_facts, _validate_source
from .import_lock import user_import_lock


def _route_day(facts):
    departure = event_time(facts.get("dep_time"))
    return (facts.get("dep_airport"), facts.get("arr_airport"),
            (facts.get("time_provenance") or {}).get("departure_local_date")
            or (departure.date().isoformat() if departure else None))


def _supports_route(facts, scope):
    return (bool(facts.get("flight_number")) and not facts.get("force_review")
        and facts.get("dep_time") and facts.get("arr_time")
        and _route_day(facts) == (scope["dep_airport"], scope["arr_airport"], scope["travel_date"]))


def _run(db, user_id, manifest):
    from .parser import PARSER_VERSION
    from .travel_name_recovery import active_shares_for_item

    before = _state(db, user_id)
    sources = {source["provider_msg_id"]: source for source in manifest["sources"]}
    if not manifest["retirements"] or len(sources) != len(manifest["sources"]):
        raise RepairConflict("Select unique original sources and at least one retirement")
    for source in sources.values():
        _validate_source(db, user_id, source)
        if source["parser_version"] != PARSER_VERSION:
            raise RepairConflict("Parser changed since source review; prepare a new plan")

    validated, used, affected = [], set(), set()
    for spec in manifest["retirements"]:
        if not isinstance(spec.get("reason"), str) or not spec["reason"].strip():
            raise RepairConflict("Retirement requires an explicit original-source review reason")
        if set(spec.get("unsupported_fields") or []) != {"departure_clock", "arrival_clock"}:
            raise RepairConflict("Explicit review must establish both projected clocks are unsupported")
        segment = db.query(Segment).join(Trip).filter(Trip.user_id == user_id,
            Segment.id == spec["segment_id"]).one_or_none()
        if not segment or segment.id in used:
            raise RepairConflict("Retirement must select one existing account flight exactly once")
        snapshot = before["segments"][str(segment.id)]
        if spec.get("expected_segment_hash") != _key(snapshot):
            raise RepairConflict("Full flight row differs from reviewed hash")
        meta = segment.meta_json or {}
        if (segment.mode != "flight" or segment.flight_number
                or not str(meta.get("source") or "").endswith("_sparse")):
            raise RepairConflict("Only an unnumbered legacy sparse projection is eligible")
        if _protected(db, user_id, segment):
            raise RepairConflict("Flight has protected manual, cancellation, or sharing evidence")
        attached_ids = set(meta.get("observation_ids") or [])
        attached = db.query(BookingObservation).filter(BookingObservation.user_id == user_id,
            BookingObservation.id.in_(attached_ids)).all() if attached_ids else []
        if {row.id for row in attached} != attached_ids:
            raise RepairConflict("Attached observations are missing or belong to another account")
        source_ids = set(meta.get("source_message_ids") or []) | {row.source_message_id for row in attached}
        if not source_ids or None in source_ids or source_ids != set(spec.get("source_hashes") or {}):
            raise RepairConflict("Every attached original must be included in the reviewed source hashes")
        for source_id in source_ids:
            source = sources.get(source_id)
            if not source or source["source_digest"] != spec["source_hashes"][source_id]:
                raise RepairConflict("Original source hash differs from reviewed evidence")
        scope = flight_scope(segment)
        if not all(scope[key] for key in ("travel_date", "dep_airport", "arr_airport")):
            raise RepairConflict("Legacy projection lacks an exact dated route")
        if any(_supports_route(facts, scope) for source_id in source_ids
               for facts in sources[source_id]["flights"]):
            raise RepairConflict("A reviewed original supplies a complete flight on this dated route")
        observations = db.query(BookingObservation).filter_by(user_id=user_id,
            travel_date=scope["travel_date"], dep_airport=scope["dep_airport"],
            arr_airport=scope["arr_airport"]).all()
        if any(_supports_route(row.facts or {}, scope) for row in observations):
            raise RepairConflict("Independent complete flight evidence corroborates this dated route")
        items = db.query(TravelInboxItem).join(TravelInboxEvidence).filter(
            TravelInboxItem.user_id == user_id, TravelInboxEvidence.observation_id.in_(attached_ids)).all()
        if any(db.get(TravelInboxAssignment, item.id) or active_shares_for_item(db, user_id, item.id)
               for item in items):
            raise RepairConflict("Retirement touches assigned or actively shared evidence")
        used.add(segment.id)
        affected.add(segment.trip_id)
        validated.append((spec, segment, scope, sorted(source_ids), sorted(attached_ids)))

    snapshot_user_itinerary(db, user_id, reason="before_reviewed_projection_retirement",
                            segment_ids=used, trip_ids=affected)
    for spec, segment, scope, source_ids, observation_ids in validated:
        hold = {"segment_id": segment.id, "segment_hash": spec["expected_segment_hash"],
            "pnr": segment.pnr, "scope": scope, "source_message_ids": source_ids,
            "observation_ids": observation_ids, "source_hashes": spec["source_hashes"],
            "unsupported_fields": spec["unsupported_fields"], "reason": spec["reason"]}
        db.add(ItineraryHistory(user_id=user_id, entity_type="projection_hold", entity_id=segment.id,
            reason="reviewed_unsupported_projection", evidence_key=_key(hold), snapshot=hold))
        db.delete(segment)
    db.flush()
    for trip_id in affected:
        trip = db.get(Trip, trip_id)
        remaining = db.query(Segment).filter_by(trip_id=trip_id).all()
        if remaining:
            trip.start_ts = min(event_time(row.dep_time) for row in remaining)
            trip.end_ts = max(event_time(row.arr_time) for row in remaining)
        else:
            db.delete(trip)
    db.flush()
    after = _state(db, user_id)
    if set(before["segments"]) - set(after["segments"]) != {str(value) for value in used}:
        raise RepairConflict("Retirement changed an unreviewed flight")
    if any(before["segments"].get(key) != row for key, row in after["segments"].items()):
        raise RepairConflict("Retirement changed another flight's facts or metadata")
    for key, row in before["trips"].items():
        if int(key) not in affected and after["trips"].get(key) != row:
            raise RepairConflict("Retirement changed an unrelated trip")
    for table in before.keys() - {"segments", "trips", "history"}:
        if after[table] != before[table]:
            raise RepairConflict(f"Retirement changed protected {table}")
    if any(after["history"].get(key) != row for key, row in before["history"].items()):
        raise RepairConflict("Retirement changed prior history")
    return {"retired_segment_ids": sorted(used), "flights_before": len(before["segments"]),
        "flights_after": len(after["segments"]), "trips_before": len(before["trips"]),
        "trips_after": len(after["trips"]), "original_evidence_preserved": True,
        "retired_projection_snapshots": {key: before["segments"][key] for key in sorted(before["segments"])
                                         if int(key) in used},
        "retained_trip_snapshots": {str(key): before["trips"][str(key)] for key in sorted(affected)},
        "source_hashes": {key: sources[key]["source_digest"] for key in sorted(sources)}}


def prepare_unsupported_projection_repair(db, user_id, retirements, prepared_sources):
    """Persist a rollback-verified preview; callers commit the manifest only."""
    if db.new or db.dirty or db.deleted:
        raise RepairConflict("Prepare requires a clean dedicated session")
    with user_import_lock(db.get_bind(), user_id):
        before = _state(db, user_id)
        sources = []
        for prepared in prepared_sources:
            if (not isinstance(prepared.get("full_msg"), dict)
                    or prepared["full_msg"].get("id") != prepared.get("msg_id")
                    or prepared.get("parse_result") is None):
                raise RepairConflict("Every reviewed source requires its full original and current parser result")
            sources.append(_source_facts(db, user_id, prepared))
        manifest = {"version": 4, "kind": "unsupported_sparse_projection", "user_id": user_id,
                    "retirements": deepcopy(retirements), "sources": sources}
        savepoint = db.begin_nested()
        try:
            preview = _run(db, user_id, manifest)
        finally:
            savepoint.rollback()
            db.expire_all()
        if _state(db, user_id) != before:
            raise RepairConflict("Preview rollback changed the account")
        base = _key(before)
        digest = _key({"manifest": manifest, "base_fingerprint": base, "preview": preview})
        row = db.query(BookingRepairManifest).filter_by(user_id=user_id, plan_hash=digest).one_or_none()
        if not row:
            row = BookingRepairManifest(id=str(uuid4()), user_id=user_id, schema_version=4,
                state="previewed", base_fingerprint=base, plan_hash=digest,
                manifest_json=manifest, preview_json=preview)
            db.add(row)
            db.flush()
        return row


def apply_unsupported_projection_repair(db, user_id, manifest_id, *, expected_plan_hash):
    if db.new or db.dirty or db.deleted:
        raise RepairConflict("Apply requires a clean dedicated session")
    with user_import_lock(db.get_bind(), user_id):
        row = db.query(BookingRepairManifest).filter_by(user_id=user_id, id=manifest_id).one_or_none()
        if (not row or row.schema_version != 4 or row.manifest_json.get("version") != 4
                or row.manifest_json.get("kind") != "unsupported_sparse_projection"
                or row.manifest_json.get("user_id") != user_id):
            raise RepairConflict("Projection retirement manifest not found for this account")
        digest = _key({"manifest": row.manifest_json, "base_fingerprint": row.base_fingerprint,
                       "preview": row.preview_json})
        if row.plan_hash != expected_plan_hash or row.plan_hash != digest:
            raise RepairConflict("Projection retirement manifest checksum changed")
        if row.state == "applied":
            return deepcopy(row.result_json)
        if _key(_state(db, user_id)) != row.base_fingerprint:
            raise RepairConflict("Account changed since preview; prepare a new plan")
        savepoint = db.begin_nested()
        try:
            result = _run(db, user_id, row.manifest_json)
            if result != row.preview_json:
                raise RepairConflict("Application differs from reviewed preview")
            row.state, row.applied_at, row.result_json = "applied", datetime.now(timezone.utc), result
            db.flush()
            savepoint.commit()
            db.commit()
            return deepcopy(result)
        except Exception:
            if savepoint.is_active:
                savepoint.rollback()
            else:
                db.rollback()
            db.expire_all()
            raise
