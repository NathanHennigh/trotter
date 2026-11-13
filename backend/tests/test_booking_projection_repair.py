"""Reviewed sparse retirement is atomic, source bound, and replay durable."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from app.models import BookingObservation, BookingRepairManifest, ItineraryHistory, Message, Segment, Trip
from app.services.booking_ledger import _key, record_flight_observations, record_user_decision
from app.services.booking_legacy_repair import _state
from app.services.booking_projection_repair import (
    apply_unsupported_projection_repair, prepare_unsupported_projection_repair,
)
from app.services.booking_repair import RepairConflict
from app.services.builder import build_segments_and_trips_detailed
from app.services.parser import ParseResult
from test_booking_lifecycle_hardening import db_user, legs


def case(db_user):
    db, user = db_user
    sparse = legs()[0]
    sparse.dep_time = datetime(2025, 2, 14, tzinfo=timezone.utc)
    sparse.arr_time = sparse.dep_time + timedelta(hours=1)
    sparse.flight_number = None
    sparse.source = "legacy_airline_sparse"
    build_segments_and_trips_detailed(db, user.id, [sparse], source_message_id="sparse-original")
    target = db.query(Segment).one()
    safe = legs()[1]
    safe.pnr = "SAFE99"
    build_segments_and_trips_detailed(db, user.id, [safe], source_message_id="safe-original")
    db.add(Message(user_id=user.id, provider_msg_id="sparse-original"))
    db.commit()
    prepared = {"msg_id": "sparse-original", "full_msg": {"id": "sparse-original",
        "payload": {"body": "Your February 14 trip. No clocks or flight number printed."}},
        "subject": "Your trip is almost here", "received_at": "2025-01-20T12:00:00Z",
        "plain_text": "Your February 14 trip. No clocks or flight number printed.",
        "parse_result": ParseResult(flights=[])}
    spec = {"segment_id": target.id, "expected_segment_hash": _key(_state(db, user.id)["segments"][str(target.id)]),
        "reason": "Reviewed original has a trip date banner but neither projected flight clock.",
        "unsupported_fields": ["departure_clock", "arrival_clock"],
        "source_hashes": {"sparse-original": _key({"message": prepared["full_msg"], "documents": None})}}
    return db, user, sparse, target, prepared, spec


def prepare(db, user, prepared, spec):
    plan = prepare_unsupported_projection_repair(db, user.id, [spec], [prepared])
    db.commit()
    return plan


def apply(db, user, plan):
    return apply_unsupported_projection_repair(db, user.id, plan.id, expected_plan_hash=plan.plan_hash)


def test_preview_retains_every_row_apply_retires_only_reviewed_projection_and_repeat_holds(db_user):
    db, user, sparse, target, prepared, spec = case(db_user)
    original = _state(db, user.id)
    plan = prepare(db, user, prepared, spec)
    assert _state(db, user.id) == original
    assert plan.preview_json["retired_segment_ids"] == [target.id]
    assert plan.preview_json["original_evidence_preserved"]
    result = apply(db, user, plan)
    assert db.get(Segment, target.id) is None
    after = _state(db, user.id)
    for table in original.keys() - {"segments", "trips", "history"}:
        assert original[table] == after[table]
    assert len(after["segments"]) == 1
    assert all(after["segments"][key] == value for key, value in original["segments"].items()
               if int(key) != target.id)
    snapshots = db.query(ItineraryHistory).filter_by(entity_type="segment", entity_id=target.id).all()
    assert any(row.snapshot == original["segments"][str(target.id)] for row in snapshots)
    assert db.query(ItineraryHistory).filter_by(entity_type="projection_hold").count() == 1
    assert apply(db, user, plan) == result
    for _ in range(3):
        outcome = build_segments_and_trips_detailed(db, user.id, [deepcopy(sparse)],
                                                   source_message_id="sparse-original")
        assert outcome.held_unknown == 1
        assert outcome.review_reasons == ["reviewed_unsupported_projection"]
        assert db.query(Segment).count() == 1
    # New complete facts from the original remain eligible after the hold.
    complete = deepcopy(sparse)
    complete.flight_number = "WN120"
    complete.source = "numbered_receipt"
    assert build_segments_and_trips_detailed(db, user.id, [complete],
        source_message_id="sparse-original").inserted == 1


@pytest.mark.parametrize("change", ["row_hash", "source_hash", "missing_source", "manual", "user_decision",
                                    "numbered", "strong_evidence", "parsed_evidence", "no_reason"])
def test_unsafe_or_stale_retirement_is_refused_without_changes(db_user, change):
    db, user, sparse, target, prepared, spec = case(db_user)
    if change == "row_hash":
        target.airline = "Changed"
    elif change == "source_hash":
        prepared["full_msg"]["payload"]["body"] += " changed"
    elif change == "missing_source":
        spec["source_hashes"] = {}
    elif change == "manual":
        target.meta_json = {**target.meta_json, "manually_edited": True}
    elif change == "user_decision":
        record_user_decision(db, user.id, sparse, status="active")
    elif change == "numbered":
        target.flight_number = "WN120"
    elif change in {"strong_evidence", "parsed_evidence"}:
        complete = deepcopy(sparse)
        complete.flight_number = "WN120"
        if change == "strong_evidence":
            record_flight_observations(db, user.id, [complete], source_message_id="independent-receipt")
        else:
            prepared["parse_result"] = ParseResult(flights=[complete])
    elif change == "no_reason":
        spec["reason"] = ""
    db.commit()
    if change != "row_hash":
        spec["expected_segment_hash"] = _key(_state(db, user.id)["segments"][str(target.id)])
    before = _state(db, user.id)
    with pytest.raises(RepairConflict):
        prepare_unsupported_projection_repair(db, user.id, [spec], [prepared])
    assert _state(db, user.id) == before
    assert db.query(BookingRepairManifest).count() == 0


def test_changed_account_and_tampered_manifest_cannot_apply(db_user):
    db, user, _, target, prepared, spec = case(db_user)
    plan = prepare(db, user, prepared, spec)
    target.airline = "Changed"
    db.commit()
    with pytest.raises(RepairConflict, match="changed since preview"):
        apply(db, user, plan)
    target.airline = plan.preview_json["retired_projection_snapshots"][str(target.id)]["airline"]
    db.commit()
    data = deepcopy(plan.manifest_json)
    data["retirements"][0]["reason"] = "tampered"
    plan.manifest_json = data
    db.commit()
    with pytest.raises(RepairConflict, match="checksum"):
        apply(db, user, plan)
    assert db.query(Segment).count() == 2


def test_apply_is_atomic_on_failure_after_projection_changes(db_user, monkeypatch):
    db, user, _, _, prepared, spec = case(db_user)
    plan = prepare(db, user, prepared, spec)
    before = _state(db, user.id)
    from app.services import booking_projection_repair as service
    real = service._run
    def fail(*args):
        real(*args)
        raise RuntimeError("injected failure after projection mutation")
    monkeypatch.setattr(service, "_run", fail)
    with pytest.raises(RuntimeError):
        apply(db, user, plan)
    assert _state(db, user.id) == before
    assert db.get(BookingRepairManifest, plan.id).state == "previewed"
