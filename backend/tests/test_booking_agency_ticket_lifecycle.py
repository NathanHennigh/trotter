"""Exact named agency tickets reconcile schedules without creating a locator."""
from copy import deepcopy
from html import escape
from itertools import permutations
from datetime import datetime
import json

import pytest

from app.models import BookingObservation, Segment, Trip, User
from app.services.booking_import import apply_booking_message
from app.services.booking_legacy_repair import _state
from app.services.booking_projection_context import projection_run
from app.services.flight_import_rollout import FEATURE_FLAGS, ALLOWLIST_ENV
from app.services.parser import parse_email
from test_booking_lifecycle_hardening import db_user
from test_priceline_itinerary import itinerary


TIMES = {"old": "November 1, 2024 at 2:20:10 PM GMT+3",
         "new": "January 7, 2025 at 5:17:44 PM GMT+3",
         "reminder": "January 9, 2025 at 5:17:44 PM GMT+3",
         "unknown": "November 1, 2024 at 2:20:10 PM GMT+3"}


def body(kind):
    text = itinerary()
    if kind == "new":
        text = text.replace("4h 5m layover in Dubai", "3h 50m layover in Dubai").replace("02:55 AM", "02:40 AM").replace("14h 0m", "14h 15m")
    return ("Begin forwarded message:\n> From: Priceline <receipt@example.test>\n> Date: "
            + TIMES[kind] + "\n> To: someone@example.test\n> Subject: Your flight confirmation\n>\n" + text)


def prepare(kind, *, html=False, changed=None, user_name="Alex Jordan Taylor"):
    text = changed if changed is not None else body(kind)
    subject = ("Re: Your Priceline itinerary" if kind == "unknown" else
               "Fwd: Reminder: your Priceline itinerary" if kind == "reminder" else
               "Fwd: Your flight confirmation")
    kwargs = dict(plain_text="" if html else text,
                  html="" if not html else "<html><body>" + "".join(f"<div>{escape(line)}</div>" for line in text.splitlines()) + "</body></html>",
                  attachments=[], user_name=user_name, aliases=[], subject=subject,
                  received_at="Fri, 10 Jan 2025 08:00:00 +0000")
    return parse_email(**kwargs), kwargs


def policy(monkeypatch, user, lane):
    for flag in FEATURE_FLAGS:
        monkeypatch.setenv(flag, str(lane != "off").lower())
    monkeypatch.setenv(ALLOWLIST_ENV, str(user.id if lane == "on" else user.id + 1000))


def apply(db, user, kind, *, html=False, source=None, changed=None):
    parsed, kwargs = prepare(kind, html=html, changed=changed, user_name=user.name)
    assert len(parsed.flights) == 4
    with projection_run(db, user.id):
        result = apply_booking_message(db, user.id, parsed, source_message_id=source or kind,
            subject=kwargs["subject"], plain_text=kwargs["plain_text"], html=kwargs["html"], received_at=kwargs["received_at"])
    db.flush()
    return result


def assert_latest(db, user):
    rows = db.query(Segment).join(Trip).filter(Trip.user_id == user.id).all()
    assert len(rows) == 4
    last, = [row for row in rows if row.flight_number == "EK904"]
    assert last.dep_time.isoformat() == "2025-01-10T22:40:00"
    assert last.arr_time.isoformat() == "2025-01-11T12:55:00"
    assert all(row.pnr is None and not row.meta_json.get("pnr_aliases") for row in rows)
    encoded = json.dumps([row.meta_json for row in rows])
    assert all(raw not in encoded for raw in ("321-654-987-10", "0061234567890", "1761234567890"))
    return last.id


def assert_repeat_capture_only(before, after):
    assert {key: value for key, value in after.items() if key != "history"} == {key: value for key, value in before.items() if key != "history"}
    assert all(after["history"][key] == value for key, value in before["history"].items())
    for key in after["history"].keys() - before["history"].keys():
        row = after["history"][key]
        assert row["reason"] in {"before_booking_import", "recluster_changed_booking_trips"}
        assert row["entity_type"] in {"trip", "segment"}
        assert row["snapshot"] == before[row["entity_type"] + "s"][str(row["entity_id"])]


@pytest.mark.parametrize("order", list(permutations(("old", "new", "reminder"))))
@pytest.mark.parametrize("html", [False, True])
@pytest.mark.parametrize("lane", ["off", "unlisted", "on"])
def test_named_ticket_original_changed_receipt_and_old_reminder_converge(db_user, monkeypatch, order, html, lane):
    db, user = db_user
    user.name = "Alex Jordan Taylor"
    policy(monkeypatch, user, lane)
    first_id = None
    old_evidence = {}
    for kind in order:
        apply(db, user, kind, html=html)
        rows = db.query(Segment).filter_by(flight_number="EK904").all()
        if rows:
            first_id = first_id or rows[0].id
            assert rows[0].id == first_id
        current = _state(db, user.id)["observations"]
        assert all(current[key] == value for key, value in old_evidence.items())
        old_evidence = deepcopy(current)
    if lane == "on":
        assert assert_latest(db, user) == first_id
    else:
        assert db.query(Segment).count() == db.query(Trip).count() == 0
        policy(monkeypatch, user, "on")
        for kind in reversed(order):
            apply(db, user, kind, html=html)
        assert_latest(db, user)
    assert db.query(BookingObservation).filter_by(user_id=user.id).count() == 12
    before = deepcopy(_state(db, user.id))
    for repeat in range(4):
        for kind in reversed(order):
            apply(db, user, kind, html=html)
        assert_latest(db, user)
        after = _state(db, user.id)
        if repeat == 0:
            assert_repeat_capture_only(before, after)
            before = deepcopy(after)
        else:
            assert after == before


@pytest.mark.parametrize("order", list(permutations(("unknown", "old", "new"))))
def test_unknown_reply_copies_do_not_choose_chronology_and_last_old_proof_can_project_retained_winner(db_user, monkeypatch, order):
    db, user = db_user
    user.name = "Alex Jordan Taylor"
    policy(monkeypatch, user, "on")
    for kind in order:
        apply(db, user, kind)
    assert_latest(db, user)
    assert db.query(BookingObservation).count() == 12


@pytest.mark.parametrize("change", ["ticket", "document", "journey_date", "route", "flight", "same_time", "unknown_order"])
def test_competing_identity_or_unproved_schedule_cannot_replace_or_duplicate_existing(db_user, monkeypatch, change):
    db, user = db_user
    user.name = "Alex Jordan Taylor"
    policy(monkeypatch, user, "on")
    apply(db, user, "old")
    before = deepcopy(_state(db, user.id))
    text = body("new")
    if change == "ticket": text = text.replace("1761234567890", "1761234567891")
    if change == "document": text = text.replace("321-654-987-10", "321-654-987-11")
    if change == "journey_date": text = text.replace("Fri Jan 10", "Sat Jan 11")
    if change == "route": text = text.replace("EWR", "JFK")
    if change == "flight": text = text.replace("Emirates Airlines Flight 904", "Emirates Airlines Flight 906")
    if change == "same_time": text = text.replace(TIMES["new"], TIMES["old"])
    kind = "unknown" if change == "unknown_order" else "new"
    result = apply(db, user, kind, source="competing", changed=text)
    assert result.review_reason == "agency_ticket_revision_requires_review"
    after = _state(db, user.id)
    assert after["segments"].keys() == before["segments"].keys()
    assert {(row["flight_number"], row["dep_time"], row["arr_time"], row["trip_id"]) for row in after["segments"].values()} == {(row["flight_number"], row["dep_time"], row["arr_time"], row["trip_id"]) for row in before["segments"].values()}
    assert all(after["observations"][key] == value for key, value in before["observations"].items())


@pytest.mark.parametrize("protection", ["public", "locked", "manual", "share_origin", "note"])
def test_revision_preserves_all_protected_member_facts_and_grouping(db_user, monkeypatch, protection):
    db, user = db_user
    user.name = "Alex Jordan Taylor"
    policy(monkeypatch, user, "on")
    apply(db, user, "old")
    target = db.query(Segment).filter_by(flight_number="EK904").one()
    if protection == "public": db.get(Trip, target.trip_id).visibility = "public"
    else:
        key, value = {"locked": ("trip_grouping_locked", True), "manual": ("manually_edited", True),
                      "share_origin": ("source", "accepted_flight_share"), "note": ("personal_note", "Owner reviewed")}[protection]
        target.meta_json = {**target.meta_json, key: value}
    db.flush()
    before = deepcopy(_state(db, user.id))
    result = apply(db, user, "new")
    assert result.review_reason == "agency_ticket_projection_protected"
    after = _state(db, user.id)
    assert after["segments"][str(target.id)] == before["segments"][str(target.id)]
    assert after["trips"] == before["trips"]


def test_other_account_and_other_passenger_ticket_are_separate(db_user, monkeypatch):
    db, user = db_user
    user.name = "Alex Jordan Taylor"
    policy(monkeypatch, user, "on")
    other = User(name=user.name, email="other-agency@example.test")
    db.add(other); db.flush()
    monkeypatch.setenv(ALLOWLIST_ENV, f"{user.id},{other.id}")
    apply(db, other, "old")
    other_before = deepcopy(_state(db, other.id))
    apply(db, user, "old")
    text = body("new").replace("Alex Jordan Taylor", "Jamie Morgan Avery").replace("1761234567890", "1769876543210").replace("0061234567890", "0069876543210")
    result = apply(db, user, "new", source="other-passenger", changed=text)
    assert result.build.held_other == 4
    apply(db, user, "new")
    assert_latest(db, user)
    assert _state(db, other.id) == other_before


@pytest.mark.parametrize("legacy", ["same_day_wrong_locator", "wrong_day_same_source", "both"])
def test_unproven_legacy_wall_clock_counterpart_is_held_without_repair_or_duplicate(db_user, monkeypatch, legacy):
    db, user = db_user
    user.name = "Alex Jordan Taylor"
    policy(monkeypatch, user, "on")
    preserved = []
    for kind in ("same_day_wrong_locator", "wrong_day_same_source"):
        if legacy not in {kind, "both"}:
            continue
        day = "2025-01-11" if kind == "same_day_wrong_locator" else "2025-12-25"
        trip = Trip(user_id=user.id, title="Existing legacy journey", visibility="private",
                    start_ts=datetime.fromisoformat(day + "T02:40:00"), end_ts=datetime.fromisoformat(day + "T07:55:00"))
        db.add(trip); db.flush()
        row = Segment(trip_id=trip.id, mode="flight", dep_airport="DXB", arr_airport="EWR",
                      dep_time=trip.start_ts, arr_time=trip.end_ts, airline="EK", flight_number="EK904",
                      pnr="EMAIL" if kind == "same_day_wrong_locator" else None,
                      meta_json={"source": "heuristic", "source_received_at": "2025-01-10T08:00:00+00:00"})
        db.add(row); db.flush();preserved.append(row.id)
    before = deepcopy(_state(db, user.id))
    for _ in range(3):
        result = apply(db, user, "new")
        assert result.review_reason == "agency_ticket_revision_requires_review"
        state = _state(db, user.id)
        assert {row.id for row in db.query(Segment).filter_by(flight_number="EK904")} == set(preserved)
        for sid in preserved:
            assert state["segments"][str(sid)] == before["segments"][str(sid)]
            tid = str(before["segments"][str(sid)]["trip_id"])
            assert state["trips"][tid] == before["trips"][tid]


@pytest.mark.parametrize("malformed", ["leg_version_bool", "proof_version_bool", "time_version_bool",
                                      "ambiguous_missing", "ambiguous_none", "complete_string",
                                      "named_conflicting_document", "named_extra_raw_id", "bad_identity_hash",
                                      "bad_source_hash", "slot_missing", "slot_bool", "departure_list", "arrival_string",
                                      "airport_proof_mismatch"])
def test_malformed_ticket_authority_is_held_without_projection(db_user, monkeypatch, malformed):
    db, user = db_user
    user.name = "Alex Jordan Taylor"
    policy(monkeypatch, user, "on")
    parsed, kwargs = prepare("old", user_name=user.name)
    for flight in parsed.flights:
        leg = flight.source_leg
        proof = leg["agency_ticket"]
        if malformed == "leg_version_bool": leg["version"] = True
        if malformed == "proof_version_bool": proof["version"] = True
        if malformed == "time_version_bool": flight.time_provenance["version"] = True
        if malformed == "ambiguous_missing": leg.pop("ambiguous")
        if malformed == "ambiguous_none": leg["ambiguous"] = None
        if malformed == "bad_identity_hash": proof["identity_key"] = "a" * 64
        if malformed == "bad_source_hash": proof["source_proof_key"] = "a" * 64
        if malformed == "slot_missing": leg.pop("journey_leg_sequence")
        if malformed == "slot_bool": leg["journey_leg_sequence"] = True
        if malformed == "departure_list": flight.time_provenance["departure"] = ["bad"]
        if malformed == "arrival_string": flight.time_provenance["arrival"] = "bad"
        if malformed == "airport_proof_mismatch": flight.time_provenance["departure"]["airport"] = "LAX"
        for entry in flight.passenger_evidence:
            if malformed == "complete_string": entry["complete"] = "yes"
            if malformed == "named_conflicting_document" and entry.get("agency_ticket"):
                entry["agency_ticket"] = {**entry["agency_ticket"], "document_key": "b" * 64}
            if malformed == "named_extra_raw_id" and entry.get("agency_ticket"):
                entry["agency_ticket"] = {**entry["agency_ticket"], "ticket_number": "0061234567890"}
    result = apply_booking_message(db, user.id, parsed, source_message_id="malformed",
        subject=kwargs["subject"], plain_text=kwargs["plain_text"], html=kwargs["html"], received_at=kwargs["received_at"])
    assert result.review_reason == "agency_ticket_revision_requires_review"
    assert db.query(Segment).count() == db.query(Trip).count() == 0
    assert db.query(BookingObservation).count() == 4
