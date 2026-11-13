from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from itertools import permutations

import pytest

from app.models import FlightShare, ItineraryHistory, Segment, User
from app.services.booking_projection_context import is_new_projection, projection_run
from test_booking_lifecycle_hardening import apply, db_user, legs
from test_booking_import_worker import worker, run


@pytest.mark.parametrize("order", list(permutations(("confirmation", "cancellation", "reminder"))))
@pytest.mark.parametrize("after_all", [False, True])
def test_new_postdeparture_conflict_projection_converges_within_worker_run(db_user, order, after_all):
    db, user = db_user
    times = {"confirmation":"2025-01-20T12:00:00Z", "reminder":"2025-02-19T12:00:00Z",
             "cancellation":"2025-02-18T12:00:00Z" if after_all else "2025-02-16T12:00:00Z"}
    with projection_run(db, user.id):
        for kind in order:
            outcome = apply(db, user, kind, legs(), kind=kind, at=times[kind])
            if kind == "cancellation":
                assert outcome.review_reason == "post_departure_cancellation_conflict"
                expected_retired = (2 if after_all else 1) if order.index("cancellation") else 0
                assert outcome.held_conflict_retirements == expected_retired
                assert outcome.evidence("test", "test")["held_conflict_retirements"] == expected_retired
                assert outcome.canceled <= (0 if after_all else 1)
        assert db.query(Segment).count() == 0
    with projection_run(db, user.id):
        for kind in reversed(order):
            apply(db, user, kind, legs(), kind=kind, at=times[kind])
        assert db.query(Segment).count() == 0


def test_pre_run_rows_remain_reviewable_and_new_exact_scopes_only_are_retired(db_user):
    db, user = db_user
    apply(db, user, "prior-run", legs())
    original_ids = {row.id for row in db.query(Segment)}
    with projection_run(db, user.id):
        unrelated = deepcopy(legs()[0])
        unrelated.flight_number = "WN999"
        unrelated.dep_time += timedelta(hours=5)
        unrelated.arr_time += timedelta(hours=5)
        db.add(Segment(trip_id=db.query(Segment).first().trip_id, mode="flight", pnr=unrelated.pnr,
            dep_airport=unrelated.dep_airport, arr_airport=unrelated.arr_airport,
            dep_time=unrelated.dep_time, arr_time=unrelated.arr_time,
            flight_number=unrelated.flight_number, meta_json={"source":"synthetic"}))
        db.flush()
        outcome = apply(db, user, "cancel", legs(), kind="cancellation", at="2025-02-18T12:00:00Z")
        assert outcome.held_conflict_retirements == 0
    assert db.query(Segment).count() == 3
    assert all(db.get(Segment, sid).meta_json["booking_conflicts"] for sid in original_ids)


@pytest.mark.parametrize("protected", ["manual", "shared"])
def test_same_run_manual_or_shared_projection_is_never_retired(db_user, protected):
    db, user = db_user
    with projection_run(db, user.id):
        apply(db, user, "original", legs())
        rows = db.query(Segment).all()
        ids = [row.id for row in rows]
        if protected == "manual":
            for row in rows:
                row.meta_json = {**row.meta_json, "manually_edited": True, "personal_note":"Owner reviewed"}
        else:
            db.add(FlightShare(sender_id=user.id, recipient_user_id=user.id, recipient_email=user.email,
                passenger_name=user.name, client_request_id="synthetic", request_hash="a"*64,
                token_hash="b"*64, token_encrypted=b"synthetic", item_ids=[], flights=[], status="accepted",
                expires_at=datetime(2028,1,1,tzinfo=timezone.utc), accepted_segment_ids=ids))
        db.flush()
        outcome = apply(db, user, "cancel", legs(), kind="cancellation", at="2025-02-18T12:00:00Z")
        assert outcome.held_conflict_retirements == 0
        assert {row.id for row in db.query(Segment)} == set(ids)


def test_context_is_account_scoped_thread_isolated_and_resets_after_exception(db_user):
    db, user = db_user
    other = User(name="Other User", email="other@example.test")
    db.add(other)
    db.flush()
    with pytest.raises(RuntimeError):
        with projection_run(db, user.id):
            assert is_new_projection(user.id, 999)
            assert not is_new_projection(other.id, 999)
            with projection_run(db, other.id):
                assert is_new_projection(user.id, 999) and is_new_projection(other.id, 999)
            assert not is_new_projection(other.id, 999)
            with ThreadPoolExecutor(max_workers=1) as pool:
                assert pool.submit(is_new_projection, user.id, 999).result() is False
            raise RuntimeError("worker failed")
    assert not is_new_projection(user.id, 999)


def durable_enabled(monkeypatch, user_id):
    monkeypatch.setenv("BOOKING_LEG_RECONCILIATION_ENABLED", "true")
    monkeypatch.setenv("FLIGHT_IMPORT_RECOVERY_USER_IDS", str(user_id))


@pytest.mark.parametrize("order", [("confirmation", "cancellation"), ("cancellation", "confirmation")])
@pytest.mark.parametrize("after_all", [False, True])
@pytest.mark.parametrize("lane", ["on", "off", "unlisted"])
def test_conflict_converges_across_committed_worker_restarts(db_user, monkeypatch, order, after_all, lane):
    from sqlalchemy.orm import Session
    from app.models import BookingObservation, BookingCancellation
    from app.services.booking_projection_context import CREATION_MARKER
    db, user = db_user
    durable_enabled(monkeypatch, user.id)
    if lane == "off":
        monkeypatch.setenv("BOOKING_LEG_RECONCILIATION_ENABLED", "false")
    elif lane == "unlisted":
        monkeypatch.setenv("FLIGHT_IMPORT_RECOVERY_USER_IDS", str(user.id + 1))
    uid, engine = user.id, db.get_bind()
    db.commit()
    counts = []
    for iteration in range(3):
        for kind in order:
            # New session and ContextVar scope model another worker process.
            with Session(engine) as restarted, projection_run(restarted, uid):
                person = restarted.get(User, uid)
                outcome = apply(restarted, person, kind, legs(), kind=kind,
                    at="2025-01-20T12:00:00Z" if kind == "confirmation" else
                    "2025-02-18T12:00:00Z" if after_all else "2025-02-16T12:00:00Z")
                if iteration == 0 and kind == "confirmation" and order[0] == kind:
                    assert all(s.meta_json[CREATION_MARKER]["segment_id"] == s.id for s in restarted.query(Segment))
                if kind == "cancellation":
                    assert outcome.canceled == (1 if not after_all and order[0] == "confirmation" and iteration == 0 else 0)
                    assert outcome.held_conflict_retirements == ((2 if after_all else 1)
                        if order[0] == "confirmation" and iteration == 0 else 0)
                restarted.commit()
        with Session(engine) as restarted:
            assert restarted.query(Segment).count() == 0
            assert restarted.query(BookingObservation).count() == 4
            assert restarted.query(BookingCancellation).count() == 1
            counts.append(restarted.query(ItineraryHistory).count())
    assert counts[1] == counts[2]


def test_existing_projection_is_never_tagged_when_adopted_in_upgrade_worker(db_user, monkeypatch):
    from app.services.booking_projection_context import CREATION_MARKER
    db, user = db_user
    apply(db, user, "original", legs())
    ids = {s.id for s in db.query(Segment)}
    durable_enabled(monkeypatch, user.id)
    with projection_run(db, user.id):
        apply(db, user, "original", legs())
    assert all(CREATION_MARKER not in s.meta_json for s in db.query(Segment))
    with projection_run(db, user.id):
        result = apply(db, user, "cancellation", legs(), kind="cancellation", at="2025-02-18T12:00:00Z")
    assert result.held_conflict_retirements == 0
    assert {s.id for s in db.query(Segment)} == ids


def test_actual_insert_is_stamped_when_sqlite_reuses_deleted_baseline_id(db_user):
    from app.services.booking_projection_context import CREATION_MARKER
    db, user = db_user
    apply(db, user, "baseline", legs())
    highest = db.query(Segment).order_by(Segment.id.desc()).first()
    reused_id = highest.id
    with projection_run(db, user.id):
        db.delete(highest)
        db.flush()
        changed = legs()[1]
        changed.flight_number = "WN999"
        apply(db, user, "new-insert", [changed])
        new = db.query(Segment).filter_by(flight_number="WN999").one()
        assert new.id == reused_id
        assert new.meta_json[CREATION_MARKER]["source_message_id"] == "new-insert"
    with projection_run(db, user.id):
        outcome = apply(db, user, "cancel-new", [changed], kind="cancellation", at="2025-02-18T12:00:00Z")
    assert outcome.held_conflict_retirements == 1
    assert [s.flight_number for s in db.query(Segment)] == ["WN120"]


@pytest.mark.parametrize("protection", ["manual", "shared", "different_scope", "different_source"])
def test_durable_marker_does_not_override_protection_or_scope(db_user, monkeypatch, protection):
    from app.services.booking_projection_context import CREATION_MARKER
    db, user = db_user
    durable_enabled(monkeypatch, user.id)
    with projection_run(db, user.id):
        apply(db, user, "original", legs())
    rows = db.query(Segment).all()
    ids = {s.id for s in rows}
    assert all(CREATION_MARKER in s.meta_json for s in rows)
    for row in rows:
        if protection == "manual":
            row.meta_json = {**row.meta_json, "manually_edited": True}
        elif protection in {"different_scope", "different_source"}:
            marker = deepcopy(row.meta_json[CREATION_MARKER])
            if protection == "different_scope":
                marker["scope"]["flight_number"] = "WN999"
            else:
                marker["source_message_id"] = "unrelated-source"
            row.meta_json = {**row.meta_json, CREATION_MARKER: marker}
    if protection == "shared":
        db.add(FlightShare(sender_id=user.id, recipient_user_id=user.id, recipient_email=user.email,
            passenger_name=user.name, client_request_id="durable", request_hash="c"*64,
            token_hash="d"*64, token_encrypted=b"synthetic", item_ids=[], flights=[], status="accepted",
            expires_at=datetime(2028,1,1,tzinfo=timezone.utc), accepted_segment_ids=list(ids)))
    db.commit()
    with projection_run(db, user.id):
        result = apply(db, user, "cancellation", legs(), kind="cancellation", at="2025-02-18T12:00:00Z")
    assert result.held_conflict_retirements == 0
    assert {s.id for s in db.query(Segment)} == ids


@pytest.mark.parametrize("cancel_first", [False, True])
def test_real_worker_recovery_rows_25_and_26_converge_across_scans(worker, monkeypatch, cancel_first):
    import base64
    from html import escape
    from app.models import BookingObservation, BookingCancellation, Message, MessageStatus
    from app.services import flight_query_v4, gmail
    from app.services.flight_template_recovery import select_messages
    from app.services.parser import PARSER_VERSION
    from app.services.booking_projection_context import CREATION_MARKER
    factory, uid, _ = worker
    durable_enabled(monkeypatch, uid)
    monkeypatch.setenv("BOOKING_STRICT_ENRICHMENT_ENABLED", "true")
    monkeypatch.setenv("CARRIER_TRAVEL_CORROBORATION_ENABLED", "false")
    monkeypatch.setattr(flight_query_v4, "iter_discovery_messages", lambda *a: [])
    body = """Confirmation number: ROUND1
Flight 1 of 2 UA120
Class: United Economy
Fri, Feb 14, 2025
Fri, Feb 14, 2025
06:00 AM
07:00 AM
Dallas, TX, US (DAL)
Austin, TX, US (AUS)
Flight 2 of 2 UA230
Class: United Economy
Mon, Feb 17, 2025
Mon, Feb 17, 2025
06:00 AM
07:00 AM
Austin, TX, US (AUS)
Dallas, TX, US (DAL)
Traveler Details
AVERY/ALEX
"""
    messages, fetched = {}, []
    order = ["cancellation", "confirmation"] if cancel_first else ["confirmation", "cancellation"]
    with factory() as db:
        for index, kind in enumerate(["guide"] * 24 + order):
            mid = f"bounded-{index + 1}"
            subject = {"guide": "Your flight guide", "confirmation": "Your flight confirmation ROUND1",
                       "cancellation": "Your reservation ROUND1 has been canceled"}[kind]
            content = "See our flight guide and destination map." if kind == "guide" else body
            if kind == "cancellation":
                content = "Your reservation has been canceled.\n" + content
            date = "Tue, 18 Feb 2025 12:00:00 +0000" if kind == "cancellation" else "Mon, 20 Jan 2025 12:00:00 +0000"
            messages[mid] = {"id": mid, "payload": {"mimeType": "text/html",
                "headers": [{"name": k, "value": v} for k, v in
                    [("Subject", subject), ("From", "receipt@united.com"), ("Date", date)]],
                "body": {"data": base64.urlsafe_b64encode("".join(f"<div>{escape(line)}</div>" for line in content.splitlines()).encode()).decode()}}}
            db.add(Message(user_id=uid, provider_msg_id=mid, subject=subject, from_email="receipt@united.com",
                status=MessageStatus.ACCEPTED, parse_version=PARSER_VERSION, ignored=True,
                parse_evidence={"resolved": True}))
        db.commit()
        assert len(select_messages(db, uid)) == 25

    def fetch(service, mid):
        fetched.append(mid)
        return messages[mid]
    monkeypatch.setattr(gmail, "get_message", fetch)
    first = run(factory, uid, "sync", "bounded-pass-1")
    assert first["state"] == "completed" and len(fetched) == 25
    with factory() as db:
        assert db.query(Segment).count() == (0 if cancel_first else 2)
        assert all(CREATION_MARKER in s.meta_json for s in db.query(Segment))
        assert [m.provider_msg_id for m in select_messages(db, uid)] == ["bounded-26"]
    second = run(factory, uid, "sync", "bounded-pass-2")
    assert second["state"] == "completed" and len(fetched) == 26
    with factory() as db:
        assert db.query(Segment).count() == 0
        assert db.query(BookingObservation).count() == 4
        assert db.query(BookingCancellation).count() == 1
        assert select_messages(db, uid) == []
        if not cancel_first:
            assert db.query(Message).filter_by(provider_msg_id="bounded-26").one().parse_evidence["held_conflict_retirements"] == 2
    assert run(factory, uid, "sync", "bounded-pass-3")["state"] == "completed"
    assert len(fetched) == 26
