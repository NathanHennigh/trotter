"""An exact self-leg link does not validate unrelated codes in earlier mail."""
from copy import deepcopy
import base64
import json
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from app.models import BookingObservation, ItineraryHistory, Segment
from app.services.booking_import import apply_booking_message
from test_booking_import_convergence import apply, flight, observations, projection, session
from test_booking_import_worker import worker


@pytest.mark.parametrize("reverse", [False, True])
def test_inherited_unknown_alias_claims_remain_evidence_without_projection(session, reverse):
    db, user = session
    notice = flight()
    notice.pnr_aliases = ["OTHER1"]
    receipt = flight("self")
    receipt.pnr_aliases = ["SHARE1"]
    sources = [("notice", notice), ("receipt", receipt)]
    for source, value in reversed(sources) if reverse else sources:
        apply(db, user, source, deepcopy(value))
    segment = db.query(Segment).one()
    assert segment.pnr == "TEST01"
    assert segment.meta_json.get("pnr_aliases") == ["SHARE1"]
    original = db.query(BookingObservation).filter_by(source_message_id="notice").one()
    assert original.ownership == "unknown"
    assert original.facts["pnr_aliases"] == ["OTHER1"]
    stable, evidence = projection(db), observations(db)
    for source, value in sources:
        apply(db, user, source, deepcopy(value))
    assert projection(db) == stable
    assert observations(db) == evidence
    history = db.query(ItineraryHistory).count()
    for source, value in sources:
        apply(db, user, source, deepcopy(value))
    assert db.query(ItineraryHistory).count() == history


def _multi_booking_sources():
    """Two anonymized real-layout messages, before and after fare/name details."""
    rows = json.loads((Path(__file__).parent / "fixtures/orlando-bookings.json").read_text(encoding="utf8"))
    receipt = next(row for row in rows if row["id"] == "multicity")
    text = BeautifulSoup(receipt["html"], "html.parser").get_text("\n", strip=True)
    schedule = text[text.index("Houston to Washington, D.C."):text.index("Fare Details")]
    notice = ("Confirmed\nYou're on your way!\n" + schedule +
        "\nYour booking with United is confirmed.\n"
        "Here's your outbound confirmation code: ORLU01\n"
        "Here's your return confirmation code: ORLB01\n"
        "You're flying on a combination of two one-way fares.\n")
    return {"notice": {"subject": "View your Capital One Travel Confirmation", "plain": notice, "html": ""},
            "receipt": {"subject": receipt["subject"], "plain": receipt["plain_text"], "html": receipt["html"]}}


@pytest.mark.parametrize("reverse", [False, True])
def test_raw_multi_booking_messages_keep_separate_references_in_both_orders(session, reverse):
    from app.services.parser import parse_email
    db, user = session
    sources = _multi_booking_sources()
    def ingest(kind):
        source = sources[kind]
        parsed = parse_email(subject=source["subject"], plain_text=source["plain"], html=source["html"],
            attachments=[], aliases=[], user_name=user.name,
            received_at="2025-01-03T00:44:48Z" if kind == "notice" else "2025-01-03T00:45:01Z")
        return apply_booking_message(db, user.id, parsed, source_message_id=kind,
            subject=source["subject"], plain_text=source["plain"], html=source["html"],
            received_at="2025-01-03T00:44:48Z" if kind == "notice" else "2025-01-03T00:45:01Z")
    order = ["notice", "receipt"]
    for kind in reversed(order) if reverse else order:
        ingest(kind)
    rows = db.query(Segment).order_by(Segment.flight_number).all()
    assert {(row.flight_number, row.pnr) for row in rows} == {("UA1540", "ORLU01"), ("B62023", "ORLB01")}
    assert all(not row.meta_json.get("pnr_aliases") for row in rows)
    pending = db.query(BookingObservation).filter_by(source_message_id="notice", flight_number="UA1540").one()
    assert pending.ownership == "unknown" and pending.facts["pnr_aliases"] == ["ORLB01"]
    stable, evidence = projection(db), observations(db)
    for kind in order:
        ingest(kind)
    assert projection(db) == stable
    assert observations(db) == evidence
    history = db.query(ItineraryHistory).count()
    for kind in order:
        ingest(kind)
    assert db.query(ItineraryHistory).count() == history


@pytest.mark.parametrize("reverse", [False, True])
def test_separate_worker_jobs_preserve_scoped_aliases_and_original_claims(worker, monkeypatch, reverse):
    from app.models import SyncJob
    from app.services import gmail
    from app.tasks import import_tasks
    factory, user_id, _ = worker
    sources = _multi_booking_sources()
    messages = {}
    for kind, source in sources.items():
        headers = [{"name": "Subject", "value": source["subject"]},
            {"name": "From", "value": "Capital One Travel <travel@example.test>"},
            {"name": "Date", "value": "Fri, 03 Jan 2025 00:44:48 +0000" if kind == "notice" else "Fri, 03 Jan 2025 00:45:01 +0000"}]
        parts = [{"mimeType": mime, "body": {"data": base64.urlsafe_b64encode(value.encode()).decode()}}
            for mime, value in (("text/plain", source["plain"]), ("text/html", source["html"])) if value]
        messages[kind] = {"id": kind, "internalDate": "1735865088000" if kind == "notice" else "1735865101000",
            "snippet": source["subject"], "payload": {"mimeType": "multipart/alternative", "headers": headers, "parts": parts}}
    monkeypatch.setattr(gmail, "get_message", lambda service, key: messages[key])
    monkeypatch.setattr(gmail, "batch_get_messages", lambda service, ids: ({key: messages[key] for key in ids}, {}))
    order = ["receipt", "notice"] if reverse else ["notice", "receipt"]
    stable = None
    for repeat in range(3):
        for kind in order:
            job_id = f"alias-{repeat}-{kind}"
            with factory() as db:
                db.add(SyncJob(id=job_id, user_id=user_id, state="pending"))
                db.commit()
            result = import_tasks.run_gmail_import.run(job_id=job_id, user_id=user_id,
                mode="exact_reprocess", message_ids=[kind])
            assert result["state"] == "completed"
        with factory() as db:
            rows = db.query(Segment).all()
            assert {(row.flight_number, row.pnr) for row in rows} == {("UA1540", "ORLU01"), ("B62023", "ORLB01")}
            assert all(not row.meta_json.get("pnr_aliases") for row in rows)
            original = db.query(BookingObservation).filter_by(source_message_id="notice", flight_number="UA1540").one()
            assert original.ownership == "unknown" and original.facts["pnr_aliases"] == ["ORLB01"]
            current = (projection(db), observations(db))
            if stable is not None:
                assert current == stable
            stable = current
