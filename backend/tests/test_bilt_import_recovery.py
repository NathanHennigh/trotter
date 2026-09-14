"""Real worker recovery flow with synthetic mail and an isolated database."""
import base64
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Account, Base, BookingObservation, Message, MessageStatus, Segment, SyncJob, User
from app.services import enrichment, flight_query_v4, gmail, parser
from app.services.flight_query_v4 import DiscoveryCandidate, DiscoveryQuery
from app.tasks import import_tasks

BODY = (Path(__file__).parent / "fixtures/bilt-confirmation-evidence.txt").read_text(encoding="utf-8")


@pytest.mark.parametrize("mode,version,force,discover,valid_itinerary", [
    ("sync", 24, False, False, True),  # Older receipt outside the incremental Gmail window.
    ("reparse", 25, True, False, True),  # Explicit repair of a current-version ignored row.
    ("sync", 25, True, True, True),  # Current row discovered before the recovery loop.
    ("sync", 24, False, False, False),  # Matching headers alone must not unignore mail.
])
def test_worker_recovers_ignored_bilt_without_claiming_an_unnamed_passenger(tmp_path, monkeypatch, mode, version, force, discover, valid_itinerary):
    engine = create_engine(f"sqlite:///{tmp_path / 'recovery.sqlite'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    mid = "synthetic-bilt-flight"
    subject = "Your flight booking is confirmed!"
    sender = "Bilt <notifications@members.bilt.com>"
    body = BODY if valid_itinerary else "Bilt rewards: Explore flights and hotels. Book now and earn bonus points."
    with factory() as db:
        user = User(name="Alex Avery", email="alex@example.test")
        db.add(user)
        db.flush()
        uid = user.id
        db.add(Account(user_id=uid, provider="google", refresh_token_encrypted=b"fixture", scopes="fixture"))
        db.add(Message(user_id=uid, provider_msg_id=mid, subject=subject, from_email=sender,
                       status=MessageStatus.ACCEPTED, ignored=True, parse_version=version,
                       parse_error="ignored_nonflight_promo",
                       parse_evidence={"resolved": True, "reason": "ignored_nonflight_promo"}))
        db.commit()
    full = {
        "id": mid, "snippet": subject, "internalDate": "1793534400000",
        "payload": {"mimeType": "text/plain", "headers": [
            {"name": "Subject", "value": subject}, {"name": "From", "value": sender},
            {"name": "Date", "value": "Sun, 01 Nov 2026 12:00:00 +0000"},
        ], "body": {"data": base64.urlsafe_b64encode(body.encode()).decode()}},
    }
    monkeypatch.setattr(import_tasks, "SessionLocal", factory)
    monkeypatch.setattr(parser, "PARSER_VERSION", 25)
    monkeypatch.setattr(gmail, "build_gmail_service", lambda token: object())
    monkeypatch.setattr(gmail, "get_message", lambda service, key: full if key == mid else pytest.fail("Unexpected message"))
    monkeypatch.setattr(gmail, "batch_get_messages", lambda service, ids: ({key: full for key in ids}, {}))
    monkeypatch.setattr(flight_query_v4, "build_discovery_plan", lambda *a, **kw: [DiscoveryQuery("fast_strong_keywords", "offline", True)])
    monkeypatch.setattr(flight_query_v4, "iter_discovery_messages", lambda service, plan: (
        [DiscoveryCandidate({"id": mid}, "fast_strong_keywords", "offline", True)] if discover and plan else []))
    monkeypatch.setattr(enrichment, "enrich_user_segments", lambda *a, **kw: 0)
    if force:
        monkeypatch.setenv("TROTTER_REPARSE_MESSAGE_IDS", mid)
    else:
        monkeypatch.delenv("TROTTER_REPARSE_MESSAGE_IDS", raising=False)
    parsed_calls = []

    def parse(**kwargs):
        parsed_calls.append(kwargs)
        start = datetime(2026, 11, 10, 17, 20, tzinfo=timezone.utc)
        return parser.ParseResult(source="synthetic-extractor", flights=[parser.ParsedFlight(
            "SFO", "LAX", start, start + timedelta(minutes=95), airline="UA",
            flight_number="UA1234", pnr="QZ8K2M", ownership="unknown",
        )])
    monkeypatch.setattr(parser, "parse_email", parse)
    try:
        for attempt in range(2):
            with factory() as db:
                db.add(SyncJob(id=f"job-{attempt}", user_id=uid, state="pending"))
                db.commit()
            result = import_tasks.run_gmail_import.run(job_id=f"job-{attempt}", user_id=uid, mode=mode, limit=0)
            assert result["state"] == "completed"
            with factory() as db:
                message = db.query(Message).filter_by(provider_msg_id=mid).one()
                assert message.parse_version == 25
                assert db.query(Segment).count() == 0
                if not valid_itinerary:
                    assert message.ignored is True
                    assert message.status == MessageStatus.ACCEPTED
                    assert message.parse_error == "ignored_nonflight_promo"
                    assert db.query(BookingObservation).count() == 0
                    continue
                assert message.ignored is False
                assert message.status == MessageStatus.REVIEW_REQUIRED
                assert message.parse_error == "passenger_identity_unresolved"
                assert db.query(BookingObservation).count() == 1
                assert db.query(BookingObservation).one().ownership == "unknown"
        assert bool(parsed_calls) == valid_itinerary
    finally:
        engine.dispose()
