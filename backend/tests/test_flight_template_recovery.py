import pytest
import json
from pathlib import Path

from app.models import Message, MessageStatus
from app.services import flight_template_recovery as recovery
from app.services.parser import PARSER_VERSION
from app.tasks.import_tasks import _message_skip_reason
from test_booking_import_worker import worker, run
from test_carrier_worker_integration import select_message
from test_partial_airline_evidence import UA, message


def setup(monkeypatch, user_id):
    monkeypatch.setenv("FLIGHT_IMPORT_RECOVERY_USER_IDS", str(user_id))
    monkeypatch.setenv("BOOKING_STRICT_ENRICHMENT_ENABLED", "true")
    monkeypatch.setenv("CARRIER_TRAVEL_CORROBORATION_ENABLED", "true")


PRICELINE_SUBJECT = "Your priceline itinerary for Example City, Country - Sunday, December 22, 2019 (Itinerary# 123-456-789-01)"


@pytest.mark.parametrize("prefix", ["", "Fwd: ", "Re: ", "Re: Fwd: "])
def test_exact_dated_priceline_receipt_subject_allows_a_forwarder(prefix):
    assert recovery.eligible(prefix + PRICELINE_SUBJECT, "Forwarder <person@example.test>")
    assert not recovery.eligible(prefix + PRICELINE_SUBJECT, "a@example.test, b@example.test")
    assert not recovery.eligible(prefix + PRICELINE_SUBJECT, "@example.test")
    assert not recovery.eligible(prefix + PRICELINE_SUBJECT, "person@@example.test")


@pytest.mark.parametrize("subject", [
    "Priceline flight deals", "Fwd: Your priceline itinerary for Example City",
    PRICELINE_SUBJECT.replace("2019", ""), PRICELINE_SUBJECT.replace("123-456-789-01", "ABC123"),
    "Offer: " + PRICELINE_SUBJECT, PRICELINE_SUBJECT + " flight sale",
    "Re: Fwd: Re: Fwd: Re: " + PRICELINE_SUBJECT,
])
def test_priceline_metadata_does_not_expand_to_generic_forwarded_travel(subject):
    assert not recovery.eligible(subject, "person@example.test")


def test_priceline_forwarded_metadata_keeps_sql_and_source_budgets(worker, monkeypatch):
    factory, uid, _ = worker
    setup(monkeypatch, uid)
    with factory() as db:
        for i in range(105):
            db.add(Message(user_id=uid, provider_msg_id=f"noise-{i}", subject=PRICELINE_SUBJECT + " sale",
                from_email="person@example.test", parse_version=PARSER_VERSION, status=MessageStatus.ACCEPTED))
        for i in range(30):
            db.add(Message(user_id=uid, provider_msg_id=f"receipt-{i}", subject="Fwd: " + PRICELINE_SUBJECT,
                from_email="person@example.test", parse_version=PARSER_VERSION, status=MessageStatus.ACCEPTED,
                parse_evidence={"resolved":True}))
        db.commit()
        assert recovery.select_messages(db, uid) == []
        assert sum(bool((r.parse_evidence or {}).get(recovery.MARKER)) for r in db.query(Message)) == 100
        first = recovery.select_messages(db, uid, limit=1000)
        assert len(first) == 25
        for row in first:
            row.parse_evidence = {recovery.MARKER: recovery.completed_marker(uid)}
        db.commit()
        second = recovery.select_messages(db, uid)
        assert len(second) == 5
        for row in second:
            row.parse_evidence = {recovery.MARKER: recovery.completed_marker(uid)}
        db.commit()
        assert recovery.select_messages(db, uid) == []
        monkeypatch.setenv("BOOKING_STRICT_ENRICHMENT_ENABLED", "false")
        assert recovery.select_messages(db, uid) == []
        monkeypatch.setenv("BOOKING_STRICT_ENRICHMENT_ENABLED", "true")
        monkeypatch.setenv("FLIGHT_IMPORT_RECOVERY_USER_IDS", str(uid + 1))
        assert recovery.select_messages(db, uid) == []


def test_forwarded_priceline_current_parser_source_revisits_once_without_discovery(worker, monkeypatch):
    factory, uid, _ = worker
    setup(monkeypatch, uid)
    msg = message("A forwarded receipt whose malformed card must remain held.")
    msg["payload"]["headers"] = [{"name":"From", "value":"person@example.test"},
        {"name":"Subject", "value":"Fwd: " + PRICELINE_SUBJECT}]
    with factory() as db:
        db.add(Message(user_id=uid, provider_msg_id=msg["id"], subject="Fwd: " + PRICELINE_SUBJECT,
            from_email="person@example.test", parse_version=PARSER_VERSION, status=MessageStatus.ACCEPTED,
            ignored=True, parse_evidence={"resolved":True}))
        db.commit()
    fetched = select_message(monkeypatch, msg)
    assert run(factory, uid, "sync", "priceline-first")["state"] == "completed"
    with factory() as db:
        assert recovery.current_for_user(db.query(Message).one().parse_evidence, uid)
        assert recovery.select_messages(db, uid) == []
    assert run(factory, uid, "sync", "priceline-repeat")["state"] == "completed"
    assert fetched == [msg["id"]]


def test_affected_current_version_source_refetches_once_through_real_worker(worker, monkeypatch):
    factory, uid, _ = worker
    setup(monkeypatch, uid)
    msg = message(UA)
    msg["payload"]["headers"].append({"name": "Subject", "value": "Wi-Fi options for your July 31 flight"})
    msg["internalDate"] = "1785456000000"
    with factory() as db:
        db.add(Message(user_id=uid, provider_msg_id=msg["id"], from_email="info@enews.united.com",
            subject="Wi-Fi options for your July 31 flight", status=MessageStatus.ACCEPTED, ignored=True,
            parse_version=PARSER_VERSION, parse_error="ignored_nonflight_promo", parse_evidence={"resolved": True}))
        db.commit()
        assert len(recovery.select_messages(db, uid)) == 1
    fetched = select_message(monkeypatch, msg)
    assert run(factory, uid, "sync", "recovery-first")["state"] == "completed"
    with factory() as db:
        row = db.query(Message).one()
        assert recovery.current(row.parse_evidence)
        assert row.parse_evidence["partial_flight_evidence"]["flight_creation_authority"] is False
        assert recovery.select_messages(db, uid) == []
    assert run(factory, uid, "sync", "recovery-repeat")["state"] == "completed"
    assert fetched == [msg["id"]]


def test_recovery_is_account_scoped_and_does_not_match_lookalike_domains(worker, monkeypatch):
    factory, uid, _ = worker
    setup(monkeypatch, uid + 1)
    row = Message(user_id=uid, subject="Your flight confirmation", from_email="receipt@united.com",
        parse_version=PARSER_VERSION, status=MessageStatus.ACCEPTED, parse_evidence={"resolved": True})
    assert _message_skip_reason(row, PARSER_VERSION) == "resolved"
    assert not recovery.eligible(row.subject, "receipt@united.com.attacker.example")
    assert not recovery.eligible("Flight deal alert", "receipt@united.com")


@pytest.mark.parametrize("domain,sender", [("delta.com", "e.delta.com"),
    ("allegiant.com", "t.allegiant.com"), ("expediamail.com", "expediamail.com")])
def test_supported_audited_senders_are_in_bounded_recovery_cohort(worker, monkeypatch, domain, sender):
    factory, uid, _ = worker
    setup(monkeypatch, uid)
    assert recovery.eligible("Your flight confirmation", f"Travel <receipt@{domain}>")
    assert recovery.eligible("Your flight itinerary", f"receipt@{sender}")
    assert not recovery.eligible("Flight deal alert", f"offers@{domain}")
    assert not recovery.eligible("Your flight confirmation", f"receipt@{domain}.example.test")
    with factory() as db:
        for index in range(30):
            db.add(Message(user_id=uid, provider_msg_id=f"source-{index}", subject="Your flight confirmation",
                from_email=f"Travel <receipt@{sender}>", parse_version=PARSER_VERSION,
                status=MessageStatus.ACCEPTED, ignored=True, parse_evidence={"resolved": True}))
        db.commit()
        rows = recovery.select_messages(db, uid, limit=1000)
        assert len(rows) == recovery.MAX_PER_SCAN == 25
        assert all(recovery.needs_recovery(row) for row in rows)
        assert recovery.select_messages(db, uid + 1) == []


def test_captured_header_structures_cover_ten_complete_and_four_partial_leg_sources(worker, monkeypatch):
    cases = json.loads((Path(__file__).parent / "fixtures/flight-recovery-supported-metadata.json").read_text())["cases"]
    assert len({leg for case in cases for leg in case.get("complete", [])}) == 10
    assert len({leg for case in cases for leg in case.get("partial", [])}) == 4
    factory, uid, _ = worker
    setup(monkeypatch, uid)
    with factory() as db:
        for case in cases:
            assert recovery.eligible(case["subject"], case["sender"]), case["case"]
            db.add(Message(user_id=uid, provider_msg_id=case["case"], subject=case["subject"],
                from_email=case["sender"], parse_version=PARSER_VERSION, status=MessageStatus.ACCEPTED,
                ignored=True, parse_evidence={"resolved": True}))
        db.commit()
        selected = recovery.select_messages(db, uid)
        assert {row.provider_msg_id for row in selected} == {case["case"] for case in cases}
        for row in selected:
            row.parse_evidence = {**row.parse_evidence, recovery.MARKER: recovery.completed_marker(uid)}
        db.commit()
        assert recovery.select_messages(db, uid) == []


@pytest.mark.parametrize("subject,sender", [
    ("You're going to save on your next vacation!", "offers@ifly.southwest.com"),
    ("You're going to Example City on 08/18!", "notices@ifly.southwest.com"),
    ("You're going to Example City on 08/18 (ABC123)!", "notices@united.com"),
    ("You're going to Example City on 08/18 (ABC123)!", "notices@southwest.com.example.test"),
])
def test_booked_city_subject_is_narrow_and_carrier_scoped(subject, sender):
    assert not recovery.eligible(subject, sender)


@pytest.mark.parametrize("subject,sender", [
    ("Confirmation of email address update", "notice@welcome.americanexpress.com"),
    ("Confirmation of your Voice ID enrollment", "notice@welcome.americanexpress.com"),
    ("Your $75 Example Credit enrollment confirmation", "notice@welcome.americanexpress.com"),
    ("Your AutoPay changes are confirmed", "notice@welcome.americanexpress.com"),
    ("Your Amex Offer expires 08/31/2026: Airline Flights at AmexTravel.com", "notice@email.americanexpress.com"),
    ("Made to Travel: Popular summer trips", "notice@eg.expedia.com"),
    ("Your One Key monthly check-in, plus travel tips", "notice@eg.expedia.com"),
    ("Flight deals to set your sights on savings", "notice@eg.expedia.com"),
    ("Book your entire trip—all in one place", "notice@eg.expedia.com"),
    ("Roundtrip flights under $200 from Example City", "notice@enews.united.com"),
    ("Your flight from Example City could be under $250 for a round trip-Book today", "notice@enews.united.com"),
    ("Save up to 20% when you bundle your flight and hotel", "notice@eg.expedia.com"),
])
def test_explicit_profile_and_campaign_metadata_does_not_refetch_originals(worker, monkeypatch, subject, sender):
    factory, uid, _ = worker
    setup(monkeypatch, uid)
    assert not recovery.eligible(subject, sender)
    with factory() as db:
        row = Message(user_id=uid, provider_msg_id="profile-or-campaign", subject=subject, from_email=sender,
            parse_version=PARSER_VERSION, status=MessageStatus.ACCEPTED, ignored=True,
            parse_evidence={"resolved": True, "preserved": "original audit"})
        db.add(row)
        db.commit()
        assert recovery.select_messages(db, uid) == []
        assert row.parse_evidence["preserved"] == "original audit"


def test_marker_never_overrides_forced_retry_or_parser_upgrade(monkeypatch):
    setup(monkeypatch, 1)
    row = Message(user_id=1, subject="Your flight", from_email="info@united.com", status=MessageStatus.REVIEW_REQUIRED,
        parse_version=PARSER_VERSION, parse_evidence={recovery.MARKER: recovery.completed_marker(1)})
    assert _message_skip_reason(row, PARSER_VERSION) == "hardened_template_examined"
    assert _message_skip_reason(row, PARSER_VERSION, force_parse=True) is None
    assert _message_skip_reason(row, PARSER_VERSION + 1) is None


def test_index_recovery_is_bounded_and_advances_past_completed_sources(worker, monkeypatch):
    factory, uid, _ = worker
    setup(monkeypatch, uid)
    with factory() as db:
        for index in range(60):
            db.add(Message(user_id=uid, provider_msg_id=f"source-{index}", subject="Your flight confirmation",
                from_email="receipt@alaskaair.com", parse_version=PARSER_VERSION, status=MessageStatus.ACCEPTED,
                parse_evidence={"resolved": True}))
        db.commit()
        first = recovery.select_messages(db, uid, limit=1000)
        assert len(first) == 25
        first_ids = {row.id for row in first}
        for row in first:
            row.parse_evidence = {recovery.MARKER: recovery.completed_marker(uid)}
        db.commit()
        second = recovery.select_messages(db, uid)
        assert len(second) == 25 and not first_ids & {row.id for row in second}
        assert recovery.select_messages(db, uid + 1) == []


def test_rejected_metadata_scan_is_bounded_and_does_not_starve_later_sources(worker, monkeypatch):
    factory, uid, _ = worker
    setup(monkeypatch, uid)
    with factory() as db:
        for index in range(110):
            db.add(Message(user_id=uid, provider_msg_id=f"promo-{index}", subject="Flight deal alert",
                from_email="offers@united.com", parse_version=PARSER_VERSION, status=MessageStatus.ACCEPTED))
        db.add(Message(user_id=uid, provider_msg_id="real", subject="Your flight confirmation",
            from_email="receipt@united.com", parse_version=PARSER_VERSION, status=MessageStatus.ACCEPTED))
        db.commit()
        assert recovery.select_messages(db, uid) == []
        assert sum(bool((r.parse_evidence or {}).get(recovery.MARKER)) for r in db.query(Message)) == 100
        db.commit()
        assert [r.provider_msg_id for r in recovery.select_messages(db, uid)] == ["real"]


def test_enabling_carrier_feature_after_template_pass_revisits_independent_hook(monkeypatch):
    setup(monkeypatch, 1)
    row = Message(user_id=1, subject="Booking Confirmation ABC123", from_email="suncountry@info.suncountry.com",
        status=MessageStatus.ACCEPTED, parse_version=PARSER_VERSION,
        parse_evidence={recovery.MARKER: {"version": recovery.VERSION, "completed": True}, "resolved": True})
    monkeypatch.setenv("CARRIER_TRAVEL_CORROBORATION_ENABLED", "false")
    assert _message_skip_reason(row, PARSER_VERSION) == "hardened_template_examined"
    monkeypatch.setenv("CARRIER_TRAVEL_CORROBORATION_ENABLED", "true")
    assert _message_skip_reason(row, PARSER_VERSION) is None


@pytest.mark.parametrize("flag,key,expected_version", [
    ("BOOKING_LEG_RECONCILIATION_ENABLED", "leg_reconciliation_version", 2),
    ("BOOKING_CONTEXTUAL_TRIP_GROUPING_ENABLED", "contextual_grouping_version", 1),
])
@pytest.mark.parametrize("carrier_enabled", [False, True])
def test_independent_hook_enable_and_rollback_through_normal_worker_without_discovery(
        worker, monkeypatch, flag, key, expected_version, carrier_enabled):
    from app.models import BookingObservation, Segment, Trip
    from app.services import gmail, flight_query_v4
    factory, uid, _ = worker
    setup(monkeypatch, uid)
    monkeypatch.setenv("CARRIER_TRAVEL_CORROBORATION_ENABLED", str(carrier_enabled).lower())
    monkeypatch.setenv("BOOKING_LEG_RECONCILIATION_ENABLED", "false")
    monkeypatch.setenv("BOOKING_CONTEXTUAL_TRIP_GROUPING_ENABLED", "false")
    msg = message(UA)
    msg["payload"]["headers"].append({"name": "Subject", "value": "Your flight itinerary"})
    msg["internalDate"] = "1785456000000"
    with factory() as db:
        db.add(Message(user_id=uid, provider_msg_id=msg["id"], subject="Your flight itinerary",
            from_email="info@enews.united.com", status=MessageStatus.REVIEW_REQUIRED,
            parse_version=PARSER_VERSION, parse_evidence={"resolved": False}))
        db.commit()
    fetched = []
    monkeypatch.setattr(flight_query_v4, "iter_discovery_messages", lambda *args: [])
    monkeypatch.setattr(gmail, "get_message", lambda service, mid: (fetched.append(mid) or msg))
    assert run(factory, uid, "sync", "hook-disabled-first")["state"] == "completed"
    with factory() as db:
        row = db.query(Message).one()
        assert recovery.current_for_user(row.parse_evidence, uid)
        assert key not in row.parse_evidence[recovery.MARKER]
        assert not recovery.select_messages(db, uid)
    assert run(factory, uid, "sync", "hook-disabled-repeat")["state"] == "completed"
    assert fetched == [msg["id"]]

    monkeypatch.setenv(flag, "true")
    with factory() as db:
        row = db.query(Message).one()
        assert recovery.select_messages(db, uid) == [row]
        assert _message_skip_reason(row, PARSER_VERSION) is None
    assert run(factory, uid, "sync", "hook-enabled")["state"] == "completed"
    assert run(factory, uid, "sync", "hook-enabled-repeat")["state"] == "completed"
    assert fetched == [msg["id"], msg["id"]]
    with factory() as db:
        row = db.query(Message).one()
        before = row.parse_evidence
        assert before[recovery.MARKER][key] == expected_version
        counts = (db.query(BookingObservation).count(), db.query(Segment).count(), db.query(Trip).count())

    # Turning off this hook or the whole recovery gate must neither fetch a
    # stable source nor mutate its evidence/flight facts. Re-enable is stable.
    for label, changes in [
        ("hook-rollback", {flag: "false"}),
        ("hook-reenable", {flag: "true"}),
        ("strict-rollback", {"BOOKING_STRICT_ENRICHMENT_ENABLED": "false"}),
        ("strict-reenable", {"BOOKING_STRICT_ENRICHMENT_ENABLED": "true"}),
        ("cohort-rollback", {"FLIGHT_IMPORT_RECOVERY_USER_IDS": ""}),
        ("cohort-reenable", {"FLIGHT_IMPORT_RECOVERY_USER_IDS": str(uid)}),
    ]:
        for name, value in changes.items():
            monkeypatch.setenv(name, value)
        assert run(factory, uid, "sync", label)["state"] == "completed"
        assert fetched == [msg["id"], msg["id"]]
        with factory() as db:
            assert db.query(Message).one().parse_evidence == before
            assert (db.query(BookingObservation).count(), db.query(Segment).count(), db.query(Trip).count()) == counts


@pytest.mark.parametrize("new_first", [False, True])
def test_held_alaska_ticket_sources_recover_once_when_leg_hook_is_enabled(worker, monkeypatch, new_first):
    from copy import deepcopy
    from app.models import BookingObservation, ItineraryHistory, Segment, Trip, TravelInboxEvidence
    from app.services import gmail, flight_query_v4
    factory, uid, _ = worker
    setup(monkeypatch, uid)
    monkeypatch.setenv("BOOKING_LEG_RECONCILIATION_ENABLED", "false")
    monkeypatch.setenv("BOOKING_CONTEXTUAL_TRIP_GROUPING_ENABLED", "false")
    messages = {}
    for new in [False, True]:
        day, number = (27, "AS124") if new else (20, "AS123")
        ticket = "0271234567891 (Previous Ticket 0271234567890)" if new else "0271234567890"
        body = f"""Alaska Airlines
Confirmation code:
ASK123
Trip details
Flight 1 . Thu May {day}
Alaska Airlines
{number[:2]} {number[2:]} . Embraer 175
SNA
SFO
Santa Ana
San Francisco
5:47 PM
7:19 PM
Thu May {day}
Thu May {day}
Traveler(s):
Alex Avery
Seat: 15C
Summary of airfare charges
Fare breakdownAir travel charges
Alex Avery
Ticket {ticket}
New Ticket Value
$100.00
Total charges for air travel
$100.00"""
        msg = message(body, sender="reservation@email.alaskaair.com")
        msg["id"] = "ticket-new" if new else "ticket-old"
        msg["payload"]["headers"].extend([
            {"name": "Subject", "value": f"Your flight is booked: ASK123 to San Francisco on 05/{day}/2027"},
            {"name": "Date", "value": "Sun, 02 May 2027 12:00:00 +0000" if new else "Sat, 01 May 2027 12:00:00 +0000"},
        ])
        messages[msg["id"]] = msg
    with factory() as db:
        for mid in (["ticket-new", "ticket-old"] if new_first else ["ticket-old", "ticket-new"]):
            msg = messages[mid]
            headers = {h["name"].lower(): h["value"] for h in msg["payload"]["headers"]}
            db.add(Message(user_id=uid, provider_msg_id=mid, subject=headers["subject"],
                from_email=headers["from"], status=MessageStatus.ACCEPTED, parse_version=PARSER_VERSION,
                parse_evidence={"resolved": True}))
        db.commit()
    fetched = []
    monkeypatch.setattr(flight_query_v4, "iter_discovery_messages", lambda *args: [])
    monkeypatch.setattr(gmail, "get_message", lambda service, mid: (fetched.append(mid) or messages[mid]))
    assert run(factory, uid, "sync", "ticket-gate-off")["state"] == "completed"
    assert run(factory, uid, "sync", "ticket-gate-off-repeat")["state"] == "completed"
    assert len(fetched) == 2
    with factory() as db:
        assert db.query(Segment).count() == db.query(Trip).count() == 0
        assert db.query(BookingObservation).count() == 2
        # The exact account holder is retained in the source observation and
        # review outcome; do not manufacture a companion inbox identity.
        assert db.query(TravelInboxEvidence).count() == 0
        for row in db.query(Message):
            assert row.parse_error == "ticket_reconciliation_not_enabled"
            assert recovery.current_for_user(row.parse_evidence, uid)
            assert "leg_reconciliation_version" not in row.parse_evidence[recovery.MARKER]
        assert all(row.facts.get("booking_ticket") for row in db.query(BookingObservation))
    monkeypatch.setenv("BOOKING_LEG_RECONCILIATION_ENABLED", "true")
    assert run(factory, uid, "sync", "ticket-gate-enabled")["state"] == "completed"
    assert run(factory, uid, "sync", "ticket-gate-enabled-repeat")["state"] == "completed"
    assert len(fetched) == 4
    with factory() as db:
        assert [row.flight_number for row in db.query(Segment)] == ["AS124"]
        assert db.query(BookingObservation).count() == 2
        before = [(r.id, r.trip_id, r.dep_time, r.arr_time, deepcopy(r.meta_json)) for r in db.query(Segment)]
        history = db.query(ItineraryHistory).count()
        assert all(recovery.current_for_user(r.parse_evidence, uid) for r in db.query(Message))
    for index, value in enumerate(["false", "true"]):
        monkeypatch.setenv("BOOKING_LEG_RECONCILIATION_ENABLED", value)
        assert run(factory, uid, "sync", f"ticket-gate-rollback-{index}")["state"] == "completed"
        assert len(fetched) == 4
        with factory() as db:
            assert [(r.id, r.trip_id, r.dep_time, r.arr_time, r.meta_json) for r in db.query(Segment)] == before
            assert db.query(ItineraryHistory).count() == history


def test_deleted_source_terminal_and_transient_backoff_preserve_prior_evidence(worker, monkeypatch):
    factory, uid, _ = worker
    setup(monkeypatch, uid)
    with factory() as db:
        row = Message(user_id=uid, provider_msg_id="missing", subject="Your flight confirmation",
            from_email="receipt@united.com", parse_version=PARSER_VERSION, status=MessageStatus.ACCEPTED,
            parse_evidence={"retained_original_fact": "test"})
        db.add(row)
        db.commit()
        recovery.record_fetch_failure(row, now=100)
        assert recovery.unavailable_or_waiting(row.parse_evidence, now=159) == "template_source_retry_backoff"
        assert recovery.unavailable_or_waiting(row.parse_evidence, now=160) is None
        recovery.record_fetch_failure(row, not_found=True)
        db.commit()
        assert recovery.select_messages(db, uid) == []
        assert _message_skip_reason(row, PARSER_VERSION) == "source_no_longer_available"
        assert row.parse_evidence["retained_original_fact"] == "test"
        assert _message_skip_reason(row, PARSER_VERSION, force_parse=True) is None


def test_combined_recovery_and_stale_queues_respect_single_message_budget(worker, monkeypatch):
    from app.services import gmail, flight_query_v4
    from app.tasks import import_tasks
    from app.models import SyncJob
    factory, uid, _ = worker
    setup(monkeypatch, uid)
    msg = message(UA)
    msg["payload"]["headers"].append({"name": "Subject", "value": "Your flight"})
    with factory() as db:
        db.add(Message(user_id=uid, provider_msg_id="template", subject="Your flight", from_email="info@united.com",
            parse_version=PARSER_VERSION, status=MessageStatus.ACCEPTED, parse_evidence={"resolved": True}))
        db.add(Message(user_id=uid, provider_msg_id="ordinary", subject="Other", from_email="info@example.com",
            parse_version=1, status=MessageStatus.ACCEPTED, ignored=False))
        db.add(SyncJob(id="budget", user_id=uid, state="pending"))
        db.commit()
    fetched = []
    def get(service, mid):
        fetched.append(mid)
        return {**msg, "id": mid}
    monkeypatch.setattr(gmail, "get_message", get)
    assert import_tasks.run_gmail_import.run("budget", uid, limit=1, mode="reparse")["state"] == "completed"
    assert len(fetched) == 1


@pytest.mark.parametrize("error,completed", [("oversized_pdf", True), ("pdf_has_no_text", True),
    ("pdf_extraction_failed", True), ("pdf_fetch_failed", False), ("pdf_timeout", False)])
def test_unsupported_attachments_are_examined_once_but_transient_failures_back_off(worker, monkeypatch, error, completed):
    from app.services import flight_documents
    factory, uid, _ = worker
    setup(monkeypatch, uid)
    msg = message(UA)
    msg["payload"]["headers"].append({"name": "Subject", "value": "Your flight itinerary"})
    msg["internalDate"] = "1785456000000"
    original = msg["payload"]
    msg["payload"] = {"mimeType": "multipart/mixed", "headers": original["headers"],
        "parts": [original, {"mimeType": "application/pdf", "filename": "ticket.pdf",
            "body": {"size": 100, "attachmentId": "synthetic-document"}}]}
    loads = []
    monkeypatch.setattr(flight_documents, "load_ticket_documents", lambda *args: (loads.append(1) or [], [error]))
    fetched = select_message(monkeypatch, msg)
    first = run(factory, uid, "sync", "document-first")
    assert first["state"] == ("failed" if error == "pdf_fetch_failed" else "completed")
    with factory() as db:
        row = db.query(Message).one()
        assert recovery.current(row.parse_evidence) == completed
        assert row.status == MessageStatus.REVIEW_REQUIRED
        assert row.parse_evidence["document_errors"] == [error]
    assert run(factory, uid, "sync", "document-repeat")["state"] == "completed"
    assert len(fetched) == len(loads) == 1
    if not completed:
        # A new body parse replaces normal outcome JSON. Retry accounting must
        # survive that replacement and increase instead of resetting to one.
        with factory() as db:
            row = db.query(Message).one()
            retry = {**row.parse_evidence["template_fetch_retry"], "after_epoch": 0}
            row.parse_evidence = {**row.parse_evidence, "template_fetch_retry": retry}
            db.commit()
        run(factory, uid, "sync", "document-after-backoff")
        with factory() as db:
            assert db.query(Message).one().parse_evidence["template_fetch_retry"]["attempts"] == 2
        assert len(fetched) == len(loads) == 2


@pytest.mark.parametrize("transition", ["enable", "partial_version", "carrier_version", "leg_version", "grouping_version"])
def test_old_source_hook_transition_is_selected_without_gmail_discovery(worker, monkeypatch, transition):
    from app.services import carrier_travel_evidence, partial_airline_evidence, gmail, flight_query_v4
    factory, uid, _ = worker
    setup(monkeypatch, uid)
    if transition == "enable":
        monkeypatch.setenv("CARRIER_TRAVEL_CORROBORATION_ENABLED", "false")
    elif transition == "leg_version":
        monkeypatch.setenv("BOOKING_LEG_RECONCILIATION_ENABLED", "true")
    elif transition == "grouping_version":
        monkeypatch.setenv("BOOKING_CONTEXTUAL_TRIP_GROUPING_ENABLED", "true")
    msg = message(UA)
    msg["payload"]["headers"].append({"name": "Subject", "value": "Your flight itinerary"})
    msg["internalDate"] = "1785456000000"
    with factory() as db:
        db.add(Message(user_id=uid, provider_msg_id=msg["id"], subject="Your flight itinerary",
            from_email="info@enews.united.com", status=MessageStatus.ACCEPTED, ignored=True,
            parse_version=PARSER_VERSION, parse_evidence={"resolved": True, recovery.MARKER: recovery.completed_marker(uid)}))
        db.commit()
        assert recovery.select_messages(db, uid) == []
    if transition == "enable":
        monkeypatch.setenv("CARRIER_TRAVEL_CORROBORATION_ENABLED", "true")
    elif transition == "partial_version":
        monkeypatch.setattr(partial_airline_evidence, "VERSION", partial_airline_evidence.VERSION + 1)
    elif transition == "carrier_version":
        monkeypatch.setattr(carrier_travel_evidence, "EVIDENCE_VERSION", carrier_travel_evidence.EVIDENCE_VERSION + 1)
    elif transition == "leg_version":
        from app.services import booking_ticket_lifecycle
        monkeypatch.setattr(booking_ticket_lifecycle, "VERSION", booking_ticket_lifecycle.VERSION + 1)
    else:
        monkeypatch.setattr(recovery, "CONTEXTUAL_GROUPING_VERSION", recovery.CONTEXTUAL_GROUPING_VERSION + 1)
    fetched = []
    monkeypatch.setattr(flight_query_v4, "iter_discovery_messages", lambda *args: [])
    monkeypatch.setattr(gmail, "get_message", lambda service, mid: (fetched.append(mid) or msg))
    with factory() as db:
        row = db.query(Message).one()
        assert recovery.needs_recovery(row)
        assert recovery.select_messages(db, uid) == [row]
    assert run(factory, uid, "sync", "hook-transition")["state"] == "completed"
    assert run(factory, uid, "sync", "hook-transition-repeat")["state"] == "completed"
    assert fetched == [msg["id"]]
    with factory() as db:
        row = db.query(Message).one()
        assert recovery.current_for_user(row.parse_evidence, uid)
        assert row.parse_evidence["partial_flight_evidence"]["flight_creation_authority"] is False


def test_unavailable_sources_do_not_consume_ordinary_stale_limit_or_block_terminal_checkpoint(worker, monkeypatch):
    from app.tasks.import_tasks import _select_stale_reparse_messages, _count_remaining_stale_reparse_messages
    factory, uid, _ = worker
    setup(monkeypatch, uid)
    with factory() as db:
        rows = [Message(user_id=uid, provider_msg_id=mid, subject="Your flight", from_email="info@united.com",
            status=MessageStatus.ACCEPTED, parse_version=1, ignored=False) for mid in ("available", "waiting", "deleted")]
        db.add_all(rows)
        db.flush()
        recovery.record_fetch_failure(rows[1])
        recovery.record_fetch_failure(rows[2], not_found=True)
        db.commit()
        args = dict(user_id=uid, parser_version=PARSER_VERSION, limit=1, targeted_ids=set())
        assert [row.provider_msg_id for row in _select_stale_reparse_messages(db, **args)] == ["available"]
        assert _count_remaining_stale_reparse_messages(db, user_id=uid, parser_version=PARSER_VERSION) == 2
        assert [row.provider_msg_id for row in _select_stale_reparse_messages(db, **args, force_ids={"deleted"})] == ["deleted"]


@pytest.mark.parametrize("retry", [[], "invalid", {"version": 1, "attempts": "bad", "after_epoch": "future"},
    {"version": 1, "attempts": [], "after_epoch": 1e100}, {"version": 0, "attempts": 8, "after_epoch": 253402300799}])
def test_malformed_or_old_retry_state_cannot_abort_or_hide_source(worker, monkeypatch, retry):
    factory, uid, _ = worker
    setup(monkeypatch, uid)
    with factory() as db:
        row = Message(user_id=uid, provider_msg_id="malformed", subject="Your flight", from_email="info@united.com",
            status=MessageStatus.ACCEPTED, parse_version=PARSER_VERSION,
            parse_evidence={"template_fetch_retry": retry, recovery.MARKER: {"version": "bad", "completed": "bad"}})
        db.add(row)
        db.commit()
        assert recovery.unavailable_or_waiting(row.parse_evidence) is None
        assert recovery.select_messages(db, uid) == [row]
        recovery.record_fetch_failure(row, now=100)
        assert row.parse_evidence["template_fetch_retry"]["attempts"] == 1


@pytest.mark.parametrize("marker", [{"version": "1", "completed": True}, {"version": True, "completed": True},
    {"version": 1, "completed": "true"}, {"version": 1, "completed": 1}, [], "bad"])
def test_malformed_completion_marker_is_not_sql_filtered_as_completed(worker, monkeypatch, marker):
    factory, uid, _ = worker
    setup(monkeypatch, uid)
    monkeypatch.setenv("CARRIER_TRAVEL_CORROBORATION_ENABLED", "false")
    with factory() as db:
        row = Message(user_id=uid, provider_msg_id="malformed", subject="Your flight", from_email="info@united.com",
            status=MessageStatus.ACCEPTED, parse_version=PARSER_VERSION, parse_evidence={recovery.MARKER: marker})
        db.add(row)
        db.commit()
        assert not recovery.current(row.parse_evidence)
        assert recovery.select_messages(db, uid) == [row]
