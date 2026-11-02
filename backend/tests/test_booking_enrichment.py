"""Opt-in exact-leg evidence checks do not assign greetings or loose aliases."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import (Base, BookingObservation, FlightShare, Message, MessageStatus,
                        Segment, TravelInboxEvidence, TravelInboxItem, User)
from app.services.booking_enrichment import current_source, enabled, evaluate
from app.services.booking_import import apply_booking_message
from app.services.booking_ledger import _key, record_cancellation, record_flight_observations, record_user_decision
from app.services.flight_times import normalize_flight_times
from app.services.parser import PARSER_VERSION, ParsedFlight, ParseResult


@pytest.fixture
def account(monkeypatch):
    monkeypatch.setenv("BOOKING_STRICT_ENRICHMENT_ENABLED", "true")
    monkeypatch.setenv("FLIGHT_IMPORT_RECOVERY_USER_IDS", "*")
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = User(name="Alex Avery", email="alex@example.com", travel_name_aliases=["Alex Morgan Avery"])
        db.add(user)
        db.flush()
        yield db, user
    engine.dispose()


def flight(ownership="unknown", *, hour=15, pnr="EXACT1", name="Alex Avery", number="UA123"):
    result = ParsedFlight("IAH", "DCA", datetime(2025, 2, 21, hour, tzinfo=timezone.utc),
        datetime(2025, 2, 21, hour + 4, tzinfo=timezone.utc), airline="UA", flight_number=number,
        pnr=pnr, ownership=ownership, source="shape_ticket", confidence=98,
        passenger_names=[name] if ownership != "unknown" else [],
        passenger_evidence=[dict(name=name, role="traveler", source="text_passenger_label",
            applies=True, complete=True, scope={"pnr": pnr, "flight_number": number})]
            if ownership != "unknown" else [])
    normalize_flight_times(result)
    result.parser_version = PARSER_VERSION
    result.source_received_at = datetime(2025, 1, 2 if ownership == "unknown" else 1, tzinfo=timezone.utc)
    return result


def seed(db, user, value, source, *, metadata=True):
    record_flight_observations(db, user.id, [value], source_message_id=source,
                              source_event_at=value.source_received_at)
    value.source_message_id = source
    if metadata:
        db.add(Message(user_id=user.id, provider_msg_id=source, parse_version=PARSER_VERSION,
            status=MessageStatus.REVIEW_REQUIRED if value.ownership == "unknown" else MessageStatus.ACCEPTED,
            parse_error="passenger_identity_unresolved" if value.ownership == "unknown" else None))
        db.flush()
    return db.query(BookingObservation).filter_by(user_id=user.id, source_message_id=source).one()


def pair(db, user):
    proof = seed(db, user, flight("self", hour=14), "proof")
    target = flight()
    seed(db, user, target, "notice")
    return proof, target


def replace_facts(row, facts):
    """Simulate a consistently persisted parser result, not a broken checksum."""
    row.facts = facts
    row.evidence_key = _key({"message": row.source_message_id,
        "event_at": row.source_event_at, "facts": facts})


@pytest.mark.parametrize("value, expected", [(None, False), ("0", False), ("false", False),
                                            ("1", True), (" TRUE ", True), ("yes", False)])
def test_feature_is_off_unless_explicitly_enabled(monkeypatch, value, expected):
    monkeypatch.setenv("FLIGHT_IMPORT_RECOVERY_USER_IDS", "1")
    monkeypatch.delenv("BOOKING_STRICT_ENRICHMENT_ENABLED", raising=False)
    if value is not None:
        monkeypatch.setenv("BOOKING_STRICT_ENRICHMENT_ENABLED", value)
    assert enabled(1) is expected
    assert not enabled()


def test_complete_original_proof_resolves_exact_unnamed_leg_without_mutation(account):
    db, user = account
    proof, target = pair(db, user)
    before = [(row.id, deepcopy(row.facts)) for row in db.query(BookingObservation)]
    for _ in range(3):
        result = evaluate(db, user.id, target)
        assert result.allowed and result.proof_observation_ids == (proof.id,)
        assert result.reason == "verified_original_same_booking_dated_leg"
    assert [(row.id, row.facts) for row in db.query(BookingObservation)] == before
    assert db.query(Segment).count() == 0


@pytest.mark.parametrize("field,value", [("pnr", "OTHER1"), ("airline", "AA"),
    ("flight_number", None), ("flight_number", "UA124"), ("dep_airport", "DFW"),
    ("ownership", "other")])
def test_only_exact_leg_is_eligible(account, field, value):
    db, user = account
    _, target = pair(db, user)
    setattr(target, field, value)
    assert not evaluate(db, user.id, target).allowed


def test_other_accounts_and_aliases_supply_no_authority(account):
    db, user = account
    other = User(name="Alex Avery", email="other@example.com")
    db.add(other); db.flush()
    seed(db, other, flight("self"), "other-account-proof")
    proof = flight("self", pnr="AGENCY1")
    proof.pnr_aliases = ["EXACT1"]
    seed(db, user, proof, "alias-proof")
    target = flight()
    target.pnr_aliases = ["AGENCY1"]
    seed(db, user, target, "notice")
    assert evaluate(db, user.id, target).reason == "no_direct_passenger_proof"


@pytest.mark.parametrize("evidence_change", ["greeting", "survey", "parsed_fallback", "incomplete",
    "unscoped", "wrong_scope", "wrong_name", "ambiguous", "inherited", "wrong_role", "not_applies"])
def test_weak_or_conflicting_names_cannot_supply_proof(account, evidence_change):
    db, user = account
    proof, target = pair(db, user)
    facts = deepcopy(proof.facts)
    entry = facts["passenger_evidence"][0]
    if evidence_change in {"greeting", "survey", "parsed_fallback"}:
        entry["source"] = {"parsed_fallback": "parsed_passenger"}.get(evidence_change, evidence_change)
    elif evidence_change == "incomplete":
        entry["complete"] = False
    elif evidence_change == "unscoped":
        entry["scope"] = {}
    elif evidence_change == "wrong_scope":
        entry["scope"]["pnr"] = "OTHER1"
    elif evidence_change == "wrong_name":
        entry["name"] = "Morgan Other"
    elif evidence_change == "ambiguous":
        entry["scope_ambiguous"] = True
    elif evidence_change == "inherited":
        entry["source_observation_id"] = 1
    elif evidence_change == "wrong_role":
        entry["role"] = "booker"
    else:
        entry["applies"] = False
    replace_facts(proof, facts)
    assert not evaluate(db, user.id, target).allowed


@pytest.mark.parametrize("source", ["user_review", "travel_name_recovery", "booking_repair_reconciliation",
                                     "accepted_flight_share", "flight_share", "booking_enrichment"])
def test_synthetic_proof_does_not_chain(account, source):
    db, user = account
    proof, target = pair(db, user)
    replace_facts(proof, {**proof.facts, "source": source})
    assert not evaluate(db, user.id, target).allowed


@pytest.mark.parametrize("source", ["user_review", "travel_name_recovery", "booking_repair_reconciliation",
                                     "accepted_flight_share", "flight_share", "booking_enrichment"])
def test_synthetic_projection_does_not_poison_independent_original_proof(account, source):
    db, user = account
    proof, target = pair(db, user)
    derived = flight("self", hour=16)
    derived.source = source
    derived.parser_version = PARSER_VERSION + 1
    derived.source_received_at = datetime(2025, 1, 3, tzinfo=timezone.utc)
    seed(db, user, derived, "derived:without-message", metadata=False)
    result = evaluate(db, user.id, target)
    assert result.allowed and result.proof_observation_ids == (proof.id,)


def test_positive_user_decision_is_not_an_original_message_or_proof(account):
    db, user = account
    proof, target = pair(db, user)
    record_user_decision(db, user.id, target, ownership="self", status="active")
    result = evaluate(db, user.id, target)
    assert result.allowed and result.proof_observation_ids == (proof.id,)


def test_share_of_synthetic_projection_still_protects_its_original_leg(account):
    db, user = account
    _, target = pair(db, user)
    derived = flight("self")
    derived.source = "booking_repair_reconciliation"
    row = seed(db, user, derived, "derived:without-message", metadata=False)
    item = TravelInboxItem(user_id=user.id, record_key="synthetic-only", flight_key="synthetic-only",
                          passenger_name="Alex Avery", passenger_key="alex", reason="unassigned")
    db.add(item); db.flush()
    db.add(TravelInboxEvidence(item_id=item.id, observation_id=row.id))
    db.add(FlightShare(sender_id=user.id, recipient_email="other@example.com", passenger_name="Alex Avery",
        client_request_id="derived-share", request_hash="x", token_hash="derived", token_encrypted=b"test",
        item_ids=[item.id], flights=[], status="accepted", expires_at=datetime.now(timezone.utc) - timedelta(days=1)))
    db.flush()
    assert evaluate(db, user.id, target).reason == "active_share"


@pytest.mark.parametrize("change", ["empty_reparse", "moved_leg", "missing_message", "ignored", "duplicate_message"])
def test_source_revision_is_checked_outside_target_leg(account, change):
    db, user = account
    proof, target = pair(db, user)
    message = db.query(Message).filter_by(provider_msg_id="proof").one()
    if change == "empty_reparse":
        message.parse_version = PARSER_VERSION + 1
        message.status = MessageStatus.IGNORED
    elif change == "moved_leg":
        facts = deepcopy(proof.facts)
        facts.update(parser_version=PARSER_VERSION + 1, arr_airport="LAX")
        db.add(BookingObservation(user_id=user.id, evidence_key="moved", source_message_id="proof",
            source_event_at=proof.source_event_at, pnr=proof.pnr, travel_date=proof.travel_date,
            dep_airport=proof.dep_airport, arr_airport="LAX", flight_number=proof.flight_number,
            ownership="self", facts=facts))
    elif change == "missing_message":
        db.delete(message)
    elif change == "ignored":
        message.ignored = True
    else:
        db.add(Message(user_id=user.id, provider_msg_id="proof", parse_version=PARSER_VERSION,
                       status=MessageStatus.ACCEPTED))
    db.flush()
    assert not evaluate(db, user.id, target).allowed


@pytest.mark.parametrize("decision", ["hold", "canceled", "other"])
def test_manual_negative_decisions_survive(account, decision):
    db, user = account
    _, target = pair(db, user)
    record_user_decision(db, user.id, target, ownership="other" if decision == "other" else "self",
                         status="active" if decision == "other" else decision)
    assert evaluate(db, user.id, target).reason == "manual_decision"


def test_cancellation_is_not_resurrected_by_later_notice(account):
    db, user = account
    _, target = pair(db, user)
    record_cancellation(db, user.id, target.pnr, source_message_id="cancel",
                        source_event_at=datetime(2025, 1, 1), flights=[target])
    assert evaluate(db, user.id, target).reason == "cancellation_evidence"


def test_other_passenger_manifest_is_not_outvoted(account):
    db, user = account
    _, target = pair(db, user)
    seed(db, user, flight("other", name="Morgan Other"), "other-passenger")
    assert evaluate(db, user.id, target).reason == "conflicting_passenger"


@pytest.mark.parametrize("malformation", ["facts_pnr", "facts_dep", "facts_arr", "facts_number",
    "facts_ownership", "facts_event", "provenance_airport", "force_review", "unnormalized"])
def test_inconsistent_saved_proof_is_never_authority(account, malformation):
    db, user = account
    proof, target = pair(db, user)
    facts = deepcopy(proof.facts)
    key_values = {"facts_pnr": ("pnr", "OTHER1"), "facts_dep": ("dep_airport", "DFW"),
        "facts_arr": ("arr_airport", "LAX"), "facts_number": ("flight_number", "UA999"),
        "facts_ownership": ("ownership", "other"), "facts_event": ("source_received_at", "2024-01-01T00:00:00Z")}
    if malformation in key_values:
        key, value = key_values[malformation]
        facts[key] = value
    elif malformation == "provenance_airport":
        facts["time_provenance"]["departure"]["airport"] = "DFW"
    elif malformation == "force_review":
        facts["force_review"] = True
    else:
        facts["time_provenance"]["status"] = "needs_review"
    replace_facts(proof, facts)
    assert not evaluate(db, user.id, target).allowed


def test_same_timestamp_conflicting_schedules_remain_held(account):
    db, user = account
    proof, target = pair(db, user)
    conflict = flight(hour=16)
    seed(db, user, conflict, "same-time-conflict")
    assert evaluate(db, user.id, target).reason == "source_chronology_conflict"


def test_actual_travel_alias_can_supply_direct_passenger_proof(account):
    db, user = account
    own = flight("self", name="Alex Morgan Avery")
    proof = seed(db, user, own, "middle-name-proof")
    target = flight()
    seed(db, user, target, "notice")
    assert evaluate(db, user.id, target).proof_observation_ids == (proof.id,)


@pytest.mark.parametrize("status,reason", [(MessageStatus.REVIEW_REQUIRED, "ambiguous_cancellation_scope"),
    (MessageStatus.REVIEW_REQUIRED, "ambiguous_passenger"), (MessageStatus.IGNORED, "survey"),
    (MessageStatus.PENDING, None)])
def test_uncertain_related_source_cannot_be_filtered_away(account, status, reason):
    db, user = account
    _, target = pair(db, user)
    seed(db, user, flight("other", name="Morgan Other"), "uncertain-other")
    message = db.query(Message).filter_by(provider_msg_id="uncertain-other").one()
    message.status, message.parse_error = status, reason
    assert not evaluate(db, user.id, target).allowed


@pytest.mark.parametrize("multiple", [False, True, "unparsed_alias"])
def test_number_only_passenger_scope_requires_one_original_booking(account, multiple):
    db, user = account
    proof, target = pair(db, user)
    facts = deepcopy(proof.facts)
    facts["passenger_evidence"][0]["scope"] = {"flight_number": "UA123"}
    if multiple == "unparsed_alias":
        facts["pnr_aliases"] = ["OTHER1"]
    replace_facts(proof, facts)
    if multiple is True:
        other = deepcopy(facts)
        other.update(pnr="OTHER1", ownership="other", passenger_names=["Morgan Other"])
        other["passenger_evidence"][0].update(name="Morgan Other", scope={"pnr": "OTHER1"})
        db.add(BookingObservation(user_id=user.id, evidence_key="other-booking-same-flight",
            source_message_id="proof", source_event_at=proof.source_event_at, pnr="OTHER1",
            travel_date=proof.travel_date, dep_airport=proof.dep_airport, arr_airport=proof.arr_airport,
            flight_number=proof.flight_number, ownership="other", facts=other))
        db.flush()
    assert evaluate(db, user.id, target).allowed is (not multiple)


def test_active_shared_ticket_remains_separate(account):
    db, user = account
    _, target = pair(db, user)
    items = [row.id for row in db.query(TravelInboxItem)]
    assert items
    db.add(FlightShare(sender_id=user.id, recipient_email="other@example.com", passenger_name="Alex Avery",
        client_request_id="share-1", request_hash="x", token_hash="y", token_encrypted=b"test",
        item_ids=items, flights=[], status="pending", expires_at=datetime.now(timezone.utc) + timedelta(days=1)))
    db.flush()
    assert evaluate(db, user.id, target).reason == "active_share"


@pytest.mark.parametrize("overflow", ["booking", "source"])
def test_large_histories_fail_closed_without_truncated_decisions(account, overflow):
    db, user = account
    proof, target = pair(db, user)
    for i in range(127):
        db.add(BookingObservation(user_id=user.id, evidence_key=f"history-{i}", source_message_id="proof",
            source_event_at=proof.source_event_at, pnr=proof.pnr if overflow == "booking" else "OTHER1",
            travel_date=proof.travel_date, dep_airport="DFW", arr_airport="LAX", flight_number="UA999",
            ownership="unknown", facts={"parser_version": PARSER_VERSION}))
    db.flush()
    assert evaluate(db, user.id, target).reason == f"{overflow}_history_limit"


def test_current_import_context_does_not_escape_transaction_scope(account):
    db, user = account
    proof, target = pair(db, user)
    db.delete(db.query(Message).filter_by(provider_msg_id="proof").one()); db.flush()
    assert not evaluate(db, user.id, target).allowed
    with current_source(db, user.id, "proof", PARSER_VERSION):
        assert evaluate(db, user.id, target).allowed
    assert not evaluate(db, user.id, target).allowed
    assert "booking_strict_enrichment" not in db.info


@pytest.mark.parametrize("reverse", [False, True])
def test_import_and_retained_replay_use_same_gate_and_keep_originals(account, reverse):
    db, user = account
    inputs = [("proof", flight("self", hour=14, number="UA0123")), ("notice", flight())]
    audits = []
    for source, value in reversed(inputs) if reverse else inputs:
        result = apply_booking_message(db, user.id, ParseResult(flights=[value]), source_message_id=source,
            subject="Flight confirmation", received_at=value.source_received_at)
        audits.extend(result.enrichment_audit or [])
        db.add(Message(user_id=user.id, provider_msg_id=source, parse_version=PARSER_VERSION,
            status=result.status, parse_error="passenger_identity_unresolved" if value.ownership == "unknown" and result.build.held_unknown else None))
        db.flush()
    segment = db.query(Segment).one()
    assert segment.dep_time == datetime(2025, 2, 21, 21)
    assert {row.ownership for row in db.query(BookingObservation)} == {"self", "unknown"}
    assert any(entry.get("proof_observation_ids") for entry in segment.meta_json["passenger_evidence"])
    assert any(audit["mode"] == "additive" and audit["inheritance_applied"]
               and audit["proof_observation_ids"] for audit in audits)
    before = [(row.id, row.evidence_key, deepcopy(row.facts)) for row in db.query(BookingObservation)]
    active = (segment.id, segment.trip_id, deepcopy(segment.meta_json))
    for source, value in inputs:
        apply_booking_message(db, user.id, ParseResult(flights=[value]), source_message_id=source,
            subject="Flight confirmation", received_at=value.source_received_at)
    assert [(row.id, row.evidence_key, row.facts) for row in db.query(BookingObservation)] == before
    assert (segment.id, segment.trip_id, segment.meta_json) == active


def test_existing_verified_correction_is_preserved_without_new_veto(account, monkeypatch):
    db, user = account
    own = flight("self", hour=14)
    own.passenger_evidence = []
    apply_booking_message(db, user.id, ParseResult(flights=[own]), source_message_id="legacy",
                          received_at=own.source_received_at)
    from app.services import booking_enrichment
    monkeypatch.setattr(booking_enrichment, "evaluate", lambda *args, **kwargs:
                        pytest.fail("Established links must bypass the candidate evaluator"))
    before = db.query(Segment).one().id
    result = apply_booking_message(db, user.id, ParseResult(flights=[flight()]), source_message_id="notice",
                                   received_at="2025-01-02T00:00:00Z")
    assert result.build.updated == 1 and result.build.held_unknown == 0
    segment = db.query(Segment).one()
    assert segment.id == before and segment.dep_time == datetime(2025, 2, 21, 21)
    assert "strict_enrichment" not in result.evidence("test", "test")


def test_failed_new_fallback_leaves_active_row_unchanged_and_reports_reason(account):
    db, user = account
    own = flight("self", hour=14, number="UA0123")
    own.passenger_evidence = []
    apply_booking_message(db, user.id, ParseResult(flights=[own]), source_message_id="legacy",
                          received_at=own.source_received_at)
    db.add(Message(user_id=user.id, provider_msg_id="legacy", parse_version=PARSER_VERSION,
                   status=MessageStatus.ACCEPTED)); db.flush()
    before = [(row.id, row.dep_time, deepcopy(row.meta_json)) for row in db.query(Segment)]
    result = apply_booking_message(db, user.id, ParseResult(flights=[flight()]), source_message_id="notice",
                                   received_at="2025-01-02T00:00:00Z")
    assert result.build.held_unknown == 1
    assert [(row.id, row.dep_time, row.meta_json) for row in db.query(Segment)] == before
    audit = result.evidence("test", "test")["strict_enrichment"][0]
    assert audit["allowed"] is False and audit["inheritance_applied"] is False and audit["mode"] == "additive"


def test_added_normalized_replay_cannot_bypass_strict_check_via_legacy_wildcard(account):
    db, user = account
    notice = flight()
    result = apply_booking_message(db, user.id, ParseResult(flights=[notice]), source_message_id="notice",
                                   received_at=notice.source_received_at)
    assert result.build.held_unknown == 1
    db.add(Message(user_id=user.id, provider_msg_id="notice", parse_version=PARSER_VERSION,
        status=MessageStatus.REVIEW_REQUIRED, parse_error="passenger_identity_unresolved")); db.flush()
    numbered = flight("self", hour=14, number="UA0123")
    wildcard = flight("self", hour=14, number=None)
    numbered.passenger_evidence = []
    wildcard.passenger_evidence = []
    apply_booking_message(db, user.id, ParseResult(flights=[numbered, wildcard]), source_message_id="legacy-batch",
                          received_at=numbered.source_received_at)
    assert db.query(Segment).count() >= 1
    for segment in db.query(Segment):
        assert segment.dep_time == datetime(2025, 2, 21, 20)
        assert "notice" not in segment.meta_json.get("source_message_ids", [])


def test_default_off_preserves_existing_inheritance(account, monkeypatch):
    db, user = account
    monkeypatch.delenv("BOOKING_STRICT_ENRICHMENT_ENABLED")
    own = flight("self", hour=14)
    own.passenger_evidence = []
    apply_booking_message(db, user.id, ParseResult(flights=[own]), source_message_id="legacy",
                          received_at=own.source_received_at)
    result = apply_booking_message(db, user.id, ParseResult(flights=[flight()]), source_message_id="notice",
                                   received_at="2025-01-02T00:00:00Z")
    assert result.build.updated == 1 and result.build.held_unknown == 0
    assert "strict_enrichment" not in result.evidence("test", "test")
