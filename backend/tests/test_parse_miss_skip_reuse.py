"""Call-local skip reuse keeps eligibility, MIME choice and persistence intact."""
import base64
from dataclasses import replace

import pytest

from app.models import BookingObservation, Message, MessageStatus, Segment, Trip
from app.services import flight_evidence, flight_query_v4, gmail, parse_audit
from app.services.flight_message import prepare_flight_message
from app.services.flight_query_v4 import DiscoveryCandidate, DiscoveryQuery
from app.services.flight_import_rollout import FEATURE_FLAGS
from test_booking_import_worker import worker, run


def full_message(plain, html, subject="Travel information", sender="newsletter@example.test"):
    parts = [{"mimeType": mime, "body": {"data": base64.urlsafe_b64encode(body.encode()).decode()}}
             for mime, body in (("text/plain", plain), ("text/html", html)) if body]
    return {"id": "synthetic-skip", "internalDate": "1793700000000", "payload": {
        "mimeType": "multipart/alternative", "headers": [
            {"name": "Subject", "value": subject}, {"name": "From", "value": sender},
            {"name": "Date", "value": "Tue, 03 Nov 2026 10:00:00 +0000"}], "parts": parts}}


@pytest.mark.parametrize("plain,html", [
    ("Weekly newsletter offers", ""), ("", "<p>Weekly newsletter offers</p>"),
    ("Weekly newsletter offers", "<p>Different hotel offers</p>"),
    ("Choose your seats and sit together", "<p>Choose your seats and sit together</p>"),
    ("Weekly newsletter", "<div hidden>Confirmation TEST12 WN120 DAL to HOU March 12, 2027</div>"),
    ("", "<template>Confirmation TEST12 WN120 DAL to HOU March 12, 2027</template>"),
    ("", "<head><title>Newsletter</title><body><p>Weekly newsletter offers</p></body>"),
    ("", ""),
])
def test_selected_skip_reuses_exact_raw_decision_without_another_score(monkeypatch, plain, html):
    payload = prepare_flight_message(full_message(plain, html), user_name="Alex Avery", aliases=[])
    assert payload["evidence_skipped"] and payload["evidence"].verdict == "skip"
    arguments = dict(subject=payload["subject"], sender=payload["from_email"], body=payload["body_for_filter"])
    assert payload["evidence"] == flight_evidence.assess_flight_evidence(**arguments)
    expected = parse_audit.assess_parse_miss(**arguments)
    original_signals = payload["evidence"].signals
    monkeypatch.setattr(flight_evidence, "assess_flight_evidence", lambda **kw: pytest.fail("Duplicate skip score"))
    assert parse_audit.assess_skipped_parse_miss(**arguments, evidence=payload["evidence"]) == expected
    assert payload["evidence"].signals is original_signals
    assert isinstance(expected.signals, list)


@pytest.mark.parametrize("change", [
    None, {}, "object", {"verdict": "parse"}, {"verdict": "review"},
    {"version": -1}, {"version": True}, {"score": True}, {"score": "2"},
    {"signals": []}, {"signals": (None,)},
])
def test_missing_malformed_or_non_skip_evidence_keeps_standard_scorer(monkeypatch, change):
    arguments = dict(subject="Travel information", sender="newsletter@example.test", body="Weekly newsletter offers")
    gate = flight_evidence.assess_flight_evidence(**arguments)
    evidence = replace(gate, **change) if isinstance(change, dict) and change else change
    expected = parse_audit.assess_parse_miss(**arguments)
    calls = []
    original = flight_evidence.assess_flight_evidence
    monkeypatch.setattr(flight_evidence, "assess_flight_evidence", lambda **kw: (calls.append(kw), original(**kw))[1])
    assert parse_audit.assess_skipped_parse_miss(**arguments, evidence=evidence) == expected
    assert calls == [arguments]


@pytest.mark.parametrize("force,documents", [
    (True, []), (False, [{"filename": "notes.pdf", "attachment_id": "synthetic", "part": "1",
                        "sha256": "a" * 64, "pages": [{"number": 1, "text": "Weekly newsletter offers"}]}]),
])
def test_force_and_document_paths_preserve_existing_skip_definition(force, documents):
    payload = prepare_flight_message(full_message("Weekly newsletter offers", "<p>Hotel offers</p>"),
                                     user_name="Alex Avery", aliases=[], force_parse=force, documents=documents)
    assert payload["evidence_skipped"] is (payload["parse_result"] is None)
    if payload["evidence_skipped"]:
        assert payload["evidence"] == flight_evidence.assess_flight_evidence(
            subject=payload["subject"], sender=payload["from_email"], body=payload["body_for_filter"])


@pytest.mark.parametrize("rollout", ["off", "unlisted", "on"])
def test_actual_worker_persists_unchanged_ignored_evidence_and_cached_repeat(worker, monkeypatch, rollout):
    factory, uid, _ = worker
    monkeypatch.setenv("FLIGHT_IMPORT_RECOVERY_USER_IDS", str(uid + 1 if rollout == "unlisted" else uid))
    for flag in FEATURE_FLAGS:
        monkeypatch.setenv(flag, "false" if rollout == "off" else "true")
    full = full_message("Choose your seats and sit together", "<p>Choose your seats and sit together</p>")
    mid = full["id"]
    monkeypatch.setattr(gmail, "batch_get_messages", lambda service, ids: ({key: full for key in ids}, {}))
    monkeypatch.setattr(gmail, "get_message", lambda service, key: full)
    monkeypatch.setattr(flight_query_v4, "build_discovery_plan", lambda *a, **kw: [DiscoveryQuery("fixture", "offline", False)])
    monkeypatch.setattr(flight_query_v4, "iter_discovery_messages", lambda service, plan:
                        [DiscoveryCandidate({"id": mid}, "fixture", "offline", False)] if plan else [])
    payload = prepare_flight_message(full, user_name="Alex Avery", aliases=[])
    expected = parse_audit.assess_parse_miss(subject=payload["subject"], sender=payload["from_email"], body=payload["body_for_filter"])
    calls = []
    original = parse_audit.assess_skipped_parse_miss
    def reuse(**arguments):
        calls.append(arguments)
        assert arguments["evidence"] == payload["evidence"]
        assert arguments["body"] == payload["body_for_filter"]
        return original(**arguments)
    monkeypatch.setattr(parse_audit, "assess_skipped_parse_miss", reuse)
    assert run(factory, uid, "sync", "skip-initial")["state"] == "completed"
    assert len(calls) == 1
    with factory() as db:
        row = db.query(Message).one()
        assert row.ignored and row.status == MessageStatus.ACCEPTED and row.parse_error == expected.reason
        assert row.parse_evidence["score"] == expected.score
        assert row.parse_evidence["signals"] == expected.signals
        before = {column.name: getattr(row, column.name) for column in Message.__table__.columns}
        assert all(db.query(model).count() == 0 for model in (Segment, Trip, BookingObservation))
    assert run(factory, uid, "sync", "skip-repeat")["state"] == "completed"
    assert len(calls) == 1
    with factory() as db:
        row = db.query(Message).one()
        assert {column.name: getattr(row, column.name) for column in Message.__table__.columns} == before
