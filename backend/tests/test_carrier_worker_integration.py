"""Real-worker carrier hooks: bounded rereads, retries and partial registrations."""
import socket
from copy import deepcopy

import pytest
from app.models import Message, MessageStatus, CarrierTravelEvidence, Segment, SyncJob, Trip, BookingObservation, User
from app.services import carrier_travel_recovery as recovery, partial_flight_evidence as partial, gmail, flight_query_v4
from app.services.flight_query_v4 import DiscoveryCandidate
from app.services.parser import PARSER_VERSION
from app.tasks.import_tasks import _message_skip_reason
from test_booking_import_worker import worker, run
from test_partial_flight_evidence import source as registration
from carrier_corroboration_fixture_helpers import source, gmail_message, fixture


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setenv("FLIGHT_IMPORT_RECOVERY_USER_IDS", "1")
    monkeypatch.setattr(socket.socket, "connect", lambda *args, **kwargs: pytest.fail("Network prohibited"))
    monkeypatch.setattr(socket, "create_connection", lambda *args, **kwargs: pytest.fail("Network prohibited"))


def select_message(monkeypatch, msg):
    fetched = []
    def fetch(service, ids):
        fetched.extend(ids)
        return {mid: msg for mid in ids}, {}
    monkeypatch.setattr(gmail, "batch_get_messages", fetch)
    monkeypatch.setattr(flight_query_v4, "iter_discovery_messages", lambda service, plan: [
        DiscoveryCandidate({"id": msg["id"]}, "fixture", "offline", False)])
    return fetched


@pytest.mark.parametrize("enabled", [False, True])
def test_partial_hook_keeps_normal_review_without_creating_flights(worker, monkeypatch, enabled):
    monkeypatch.setenv("CARRIER_TRAVEL_CORROBORATION_ENABLED", str(enabled).lower())
    factory, user_id, _ = worker
    msg = registration()
    msg["internalDate"] = "1745712000000"
    select_message(monkeypatch, msg)
    if not enabled:
        monkeypatch.setattr(partial, "extract_partial_flight_evidence", lambda *args: pytest.fail("Default-off partial hook ran"))
        monkeypatch.setattr(recovery, "record_payload", lambda *args: pytest.fail("Default-off carrier hook ran"))
    result = run(factory, user_id, "sync", "partial")
    assert result["state"] == "completed"
    with factory() as db:
        row = db.query(Message).one()
        assert row.status == MessageStatus.REVIEW_REQUIRED
        assert row.parse_error == "partial_flight_evidence_but_no_segments"
        assert bool(row.parse_evidence.get("partial_flight_evidence")) == enabled
        assert not row.parse_evidence["resolved"]
        assert db.query(Segment).count() == db.query(CarrierTravelEvidence).count() == 0


@pytest.mark.parametrize("cohort", ["", "invalid", "unlisted"])
def test_worker_never_extracts_optional_evidence_for_an_unlisted_account(worker, monkeypatch, cohort):
    factory, user_id, _ = worker
    monkeypatch.setenv("CARRIER_TRAVEL_CORROBORATION_ENABLED", "true")
    monkeypatch.setenv("FLIGHT_IMPORT_RECOVERY_USER_IDS", str(user_id + 100) if cohort == "unlisted" else cohort)
    msg = registration()
    msg["internalDate"] = "1745712000000"
    select_message(monkeypatch, msg)
    monkeypatch.setattr(partial, "extract_partial_flight_evidence", lambda *args: pytest.fail("Unlisted partial extraction"))
    monkeypatch.setattr(recovery, "record_payload", lambda *args: pytest.fail("Unlisted carrier extraction"))
    assert run(factory, user_id, "sync", "unlisted-partial")["state"] == "completed"
    with factory() as db:
        row = db.query(Message).one()
        assert row.status == MessageStatus.REVIEW_REQUIRED
        assert not row.parse_evidence.get("partial_flight_evidence")
        assert not row.parse_evidence.get("carrier_evidence")
        assert db.query(Segment).count() == db.query(CarrierTravelEvidence).count() == 0


def survey():
    value = source("aa-survey")
    value["subject"] = "ALEX, how was your flight?"
    return gmail_message(value, recipient="alex@example.com")


def seed_resolved(factory, user_id, msg):
    with factory() as db:
        headers = {h["name"].lower(): h["value"] for h in msg["payload"]["headers"]}
        db.add(Message(user_id=user_id, provider_msg_id=msg["id"], status=MessageStatus.ACCEPTED,
            parse_version=PARSER_VERSION, ignored=True, parse_error="non_flight_noise",
            subject=headers["subject"], from_email=headers["from"],
            parse_evidence={"resolved": True, "reason": "non_flight_noise"}))
        db.commit()


def test_supported_resolved_survey_fetches_once(worker, monkeypatch):
    monkeypatch.setenv("CARRIER_TRAVEL_CORROBORATION_ENABLED", "true")
    factory, user_id, _ = worker
    msg = survey()
    seed_resolved(factory, user_id, msg)
    fetched = select_message(monkeypatch, msg)
    assert run(factory, user_id, "sync", "first")["state"] == "completed"
    with factory() as db:
        marker = db.query(Message).one().parse_evidence["carrier_evidence"]
        assert marker["version"] == 1
        assert db.query(CarrierTravelEvidence).count() == 1
    assert run(factory, user_id, "sync", "second")["state"] == "completed"
    assert fetched == [msg["id"]]


def test_failed_carrier_transaction_rolls_back_marker_and_is_retried(worker, monkeypatch):
    monkeypatch.setenv("CARRIER_TRAVEL_CORROBORATION_ENABLED", "true")
    factory, user_id, _ = worker
    msg = survey()
    seed_resolved(factory, user_id, msg)
    fetched = select_message(monkeypatch, msg)
    real_record = recovery.record_payload
    def fail_after_record(*args, **kwargs):
        real_record(*args, **kwargs)
        raise RuntimeError("Injected carrier failure")
    monkeypatch.setattr(recovery, "record_payload", fail_after_record)
    run(factory, user_id, "sync", "failed")
    with factory() as db:
        assert db.get(SyncJob, "failed").state == "failed"
        row = db.query(Message).one()
        assert "carrier_evidence" not in row.parse_evidence
        assert _message_skip_reason(row, PARSER_VERSION) is None
        assert db.query(CarrierTravelEvidence).count() == db.query(Segment).count() == 0
    monkeypatch.setattr(recovery, "record_payload", real_record)
    assert run(factory, user_id, "sync", "retried")["state"] == "completed"
    assert run(factory, user_id, "sync", "settled")["state"] == "completed"
    assert fetched == [msg["id"], msg["id"]]
    with factory() as db:
        assert db.query(CarrierTravelEvidence).count() == 1
        assert db.query(Segment).count() == 0


@pytest.mark.parametrize("failure", ["hook_failure", "feature_disabled", "no_new_facts", "new_version"])
def test_prior_partial_facts_survive_reprocessing_and_remain_non_authoritative(worker, monkeypatch, failure):
    monkeypatch.setenv("CARRIER_TRAVEL_CORROBORATION_ENABLED", "true")
    factory, user_id, _ = worker
    msg = registration()
    msg["internalDate"] = "1745712000000"
    select_message(monkeypatch, msg)
    assert run(factory, user_id, "sync", "partial-first")["state"] == "completed"
    with factory() as db:
        prior = deepcopy(db.query(Message).one().parse_evidence["partial_flight_evidence"])
    extract = partial.extract_partial_flight_evidence
    if failure == "hook_failure":
        def fail(*args):
            raise RuntimeError("Injected after ordinary outcome commit")
        monkeypatch.setattr(partial, "extract_partial_flight_evidence", fail)
    elif failure == "feature_disabled":
        monkeypatch.setenv("CARRIER_TRAVEL_CORROBORATION_ENABLED", "false")
        monkeypatch.setattr(partial, "extract_partial_flight_evidence", lambda *args: pytest.fail("Disabled partial hook ran"))
    elif failure == "no_new_facts":
        monkeypatch.setattr(partial, "extract_partial_flight_evidence", lambda *args: None)
    else:
        monkeypatch.setattr(partial, "extract_partial_flight_evidence",
            lambda *args: {**extract(*args), "version": 2, "source_sha256": "b" * 64})
    run(factory, user_id, "reparse", "partial-second")
    with factory() as db:
        row = db.query(Message).one()
        assert prior in row.parse_evidence["partial_flight_evidence_history"]
        assert row.status == MessageStatus.REVIEW_REQUIRED
        assert not row.parse_evidence["resolved"]
        assert db.query(Segment).count() == db.query(CarrierTravelEvidence).count() == 0
        if failure == "new_version":
            assert row.parse_evidence["partial_flight_evidence"]["version"] == 2
        else:
            assert "partial_flight_evidence" not in row.parse_evidence
    monkeypatch.setenv("CARRIER_TRAVEL_CORROBORATION_ENABLED", "true")
    monkeypatch.setattr(partial, "extract_partial_flight_evidence", extract)
    assert run(factory, user_id, "reparse", "partial-retry")["state"] == "completed"
    with factory() as db:
        outcome = deepcopy(db.query(Message).one().parse_evidence)
        assert outcome["partial_flight_evidence"] == prior
        historical = outcome.get("partial_flight_evidence_history", [])
        assert len(historical) == (1 if failure == "new_version" else 0)
        assert all(not item["ownership_authority"] and not item["flight_creation_authority"] for item in historical)
    assert run(factory, user_id, "reparse", "partial-repeat")["state"] == "completed"
    with factory() as db:
        assert db.query(Message).one().parse_evidence == outcome


def test_partial_history_survives_ordinary_flight_and_cancellation_outcomes_with_feature_off(worker, monkeypatch):
    from test_booking_import_worker import ROWS, EXPECTED
    monkeypatch.setenv("CARRIER_TRAVEL_CORROBORATION_ENABLED", "false")
    factory, user_id, _ = worker
    prior = {"version": 1, "source_sha256": "c" * 64, "ownership_authority": False,
             "flight_creation_authority": False, "known_airport": {"code": "MNL", "role": "arrival"}}
    with factory() as db:
        for value in ROWS:
            db.add(Message(user_id=user_id, provider_msg_id=value["id"], status=MessageStatus.REVIEW_REQUIRED,
                parse_version=1, parse_evidence={"partial_flight_evidence": deepcopy(prior), "resolved": False}))
        db.commit()
    assert run(factory, user_id, "reparse", "ordinary-outcomes")["state"] == "completed"
    with factory() as db:
        assert {(row.dep_airport, row.arr_airport, row.flight_number) for row in db.query(Segment)} == EXPECTED
        for row in db.query(Message):
            assert row.parse_evidence["partial_flight_evidence_history"] == [prior]
            assert "partial_flight_evidence" not in row.parse_evidence
        assert db.query(CarrierTravelEvidence).count() == 0


def test_recovery_projection_failure_rolls_back_then_retry_is_idempotent(worker, monkeypatch):
    monkeypatch.setenv("CARRIER_TRAVEL_CORROBORATION_ENABLED", "true")
    factory, user_id, _ = worker
    with factory() as db:
        user = db.get(User, user_id)
        person = fixture()["user"]
        user.name, user.email, user.travel_name_aliases = person["name"], person["email"], person["aliases"]
        db.commit()
    def records():
        with factory() as db:
            return {model.__tablename__: [{column.name: deepcopy(getattr(row, column.name)) for column in model.__table__.columns}
                    for row in db.query(model).order_by(model.id)]
                    for model in [Trip, Segment, BookingObservation, CarrierTravelEvidence]}
    select_message(monkeypatch, gmail_message(source("sun-update-3")))
    assert run(factory, user_id, "sync", "prepare-projection")["state"] == "completed"
    before = records()
    msg = gmail_message(source("sun-survey"))
    fetched = select_message(monkeypatch, msg)
    reconcile = recovery.reconcile
    def fail_after_recovery(*args, **kwargs):
        result = reconcile(*args, **kwargs)
        assert result.inserted == 1
        raise RuntimeError("Injected after recovered flight projection")
    monkeypatch.setattr(recovery, "reconcile", fail_after_recovery)
    run(factory, user_id, "sync", "failed-projection")
    assert records() == before
    monkeypatch.setattr(recovery, "reconcile", reconcile)
    assert run(factory, user_id, "sync", "retry-projection")["state"] == "completed"
    after = records()
    assert len(after["segments"]) == 1
    assert run(factory, user_id, "sync", "repeat-projection")["state"] == "completed"
    assert records() == after
    assert fetched == [msg["id"], msg["id"]]
