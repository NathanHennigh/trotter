"""Source-shaped schedule revisions through the real booking import service."""
from copy import deepcopy
from datetime import datetime
from functools import lru_cache
from html import escape
from itertools import permutations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import Base, BookingObservation, Segment, Trip, User
from app.services.booking_import import apply_booking_message
from app.services.booking_legacy_repair import _state
from app.services.booking_ledger import event_time
from app.services.flight_import_rollout import ALLOWLIST_ENV, FEATURE_FLAGS, enabled
from app.services.parser import parse_email


SENT = {"original": "2026-10-01T12:00:00Z", "reminder": "2026-10-02T12:00:00Z",
        "changed": "2026-10-03T12:00:00Z", "changed-again": "2027-01-15T12:00:00Z"}
SUBJECT = {"original": "Your flight confirmation", "reminder": "Reminder: your upcoming flight",
           "changed": "Alert: Aeromexico changed your flight(s)",
           "changed-again": "Alert: Aeromexico changed your flight(s)"}


def itinerary(kind, *, passenger="TAYLOR/ALEX", pnr="TEST01", agency="AGENCY1", number="AM901"):
    # Labels/marker placement mirror an agency change card. Names, references,
    # flight numbers and dates are synthetic; no captured email is a fixture.
    clocks = {
        "original": ("1:49 PM", "4:40 PM"),
        "reminder": ("1:49 PM", "4:40 PM"),
        "changed": ("1:49 PM", "4:40 PM\n4:45 PM\n(change)"),
        "changed-again": ("1:49 PM\n2:19 PM\n(change)", "4:45 PM\n5:10 PM\n(change)"),
    }
    departure, arrival = clocks[kind]
    return f"""Passenger(s):
{passenger}
Expedia Itinerary Number:
12345678901234
Aeromexico Confirmation Code:
{pnr}
Expedia Confirmation Code:
{agency}
Aeromexico Flight Details
Your itinerary is updated. See changes in red below.
These changes only affect the flights listed below.
Managua to Mexico City
Friday, Mar 12, 2027
Flight Change Details
Aeromexico
Flight Number:
{number}
From:
Managua (MGA-Augusto C. Sandino Intl.)
To:
Mexico City (MEX-Mexico City Intl.)
Status:
CONFIRMED
Depart:
{departure}
Arrive:
{arrival}
Class:
Coach
Equipment:
Embraer ERJ-190
View Itinerary Online
"""


@lru_cache(maxsize=64)
def prepared(kind, representation="plain", passenger="TAYLOR/ALEX", pnr="TEST01",
             agency="AGENCY1", number="AM901"):
    text = itinerary(kind, passenger=passenger, pnr=pnr, agency=agency, number=number)
    html = "<html><body>" + "".join(f"<div>{escape(line)}</div>" for line in text.splitlines()) + "</body></html>"
    kwargs = {"plain_text": text if representation == "plain" else "",
              "html": html if representation == "html" else "", "attachments": [],
              "user_name": "Alex Taylor", "aliases": [], "received_at": SENT[kind],
              "subject": SUBJECT[kind], "from_email": "Expedia <notify@example.test>"}
    return parse_email(**kwargs), kwargs


@pytest.fixture
def db_user(monkeypatch):
    monkeypatch.setattr("app.services.builder.enrich_segment", lambda *args, **kwargs: None)
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = User(name="Alex Taylor", email="alex@example.test")
        db.add(user)
        db.flush()
        yield db, user
    engine.dispose()


def policy(monkeypatch, uid, lane):
    for flag in FEATURE_FLAGS:
        monkeypatch.setenv(flag, "false" if lane == "off" else "true")
    monkeypatch.setenv(ALLOWLIST_ENV, str(uid if lane == "on" else uid + 9000))
    assert all(enabled(flag, uid) == (lane == "on") for flag in FEATURE_FLAGS)


def apply(db, user, kind, representation="plain", *, source=None, **options):
    parsed, kwargs = prepared(kind, representation, **options)
    assert len(parsed.flights) == 1
    assert parsed.flights[0].source == "shape_labeled_agency_card"
    assert not getattr(parsed.flights[0], "force_review", False)
    result = apply_booking_message(db, user.id, deepcopy(parsed), source_message_id=source or kind,
        subject=kwargs["subject"], plain_text=kwargs["plain_text"], html=kwargs["html"], received_at=kwargs["received_at"])
    db.flush()
    return result


def observations(db, uid):
    return {row.id: {column.name: deepcopy(getattr(row, column.name)) for column in row.__table__.columns}
            for row in db.query(BookingObservation).filter_by(user_id=uid)}


def assert_repeat_capture_only(before, after):
    """The first repeat may snapshot the final existing row once, never shells."""
    assert {key: value for key, value in before.items() if key != "history"} == {
        key: value for key, value in after.items() if key != "history"}
    assert all(after["history"][key] == value for key, value in before["history"].items())
    for key in set(after["history"]) - set(before["history"]):
        row = after["history"][key]
        assert row["reason"] in {"before_booking_import", "recluster_changed_booking_trips"}
        assert row["entity_type"] in {"trip", "segment"}
        assert row["snapshot"] == before[row["entity_type"] + "s"][str(row["entity_id"])]


def assert_current(db, uid, kind):
    row = db.query(Segment).join(Trip).filter(Trip.user_id == uid).one()
    assert (row.pnr, row.flight_number, row.dep_airport, row.arr_airport) == ("TEST01", "AM901", "MGA", "MEX")
    times = {"changed": ("2027-03-12T19:49:00", "2027-03-12T22:45:00"),
             "changed-again": ("2027-03-12T20:19:00", "2027-03-12T23:10:00")}
    assert (event_time(row.dep_time).isoformat(), event_time(row.arr_time).isoformat()) == times[kind]
    return row


@pytest.mark.parametrize("lane", ["off", "unlisted", "on"])
@pytest.mark.parametrize("representation", ["plain", "html"])
@pytest.mark.parametrize("order", list(permutations(("original", "changed", "reminder"))))
def test_marked_schedule_change_beats_older_receipt_and_late_delivered_reminder(
        db_user, monkeypatch, lane, representation, order):
    db, user = db_user
    policy(monkeypatch, user.id, lane)
    retained = {}
    first_id = None
    for kind in order:
        apply(db, user, kind, representation)
        current = observations(db, user.id)
        assert all(current[key] == value for key, value in retained.items())
        retained = current
        row = db.query(Segment).one()
        first_id = first_id or row.id
        assert row.id == first_id
    row = assert_current(db, user.id, "changed")
    assert set(row.meta_json.get("pnr_aliases", [])) <= {"AGENCY1"}
    assert len(retained) == 3
    changed = db.query(BookingObservation).filter_by(source_message_id="changed").one()
    original = db.query(BookingObservation).filter_by(source_message_id="original").one()
    assert event_time(original.facts["arr_time"]) == datetime(2027, 3, 12, 22, 40)
    clock = changed.facts["time_provenance"]["date_evidence"]["clock_evidence"]["arrival"]
    assert clock["selected"] == "4:45 PM" and clock["other_printed_clocks"] == ["4:40 PM"]
    # Processing order is deliberately different from the original Date header.
    # Older mail arriving later cannot replace the changed schedule.
    stable = deepcopy(_state(db, user.id))
    for repeat in range(4):
        for kind in reversed(order):
            apply(db, user, kind, representation)
        assert_current(db, user.id, "changed")
        current = _state(db, user.id)
        if repeat == 0:
            assert_repeat_capture_only(stable, current)
            stable = deepcopy(current)
        else:
            assert current == stable


@pytest.mark.parametrize("lane", ["off", "unlisted", "on"])
def test_marked_revision_does_not_touch_another_accounts_same_booking(db_user, monkeypatch, lane):
    db, user = db_user
    second = User(name="Alex Taylor", email="another-alex@example.test")
    db.add(second)
    db.flush()
    apply(db, second, "original")
    protected = deepcopy(_state(db, second.id))
    policy(monkeypatch, user.id, lane)
    for _ in range(3):
        for kind in ("changed-again", "original", "changed", "reminder"):
            apply(db, user, kind)
        assert_current(db, user.id, "changed-again")
        assert _state(db, second.id) == protected


@pytest.mark.parametrize("order", list(permutations(("original", "changed", "changed-again"))))
def test_two_changed_cards_reconcile_independently_without_borrowing_endpoint_clocks(db_user, order):
    db, user = db_user
    departures = {"original": "9:15 AM", "changed": "9:15 AM\n10:00 AM\n(change)",
                  "changed-again": "10:00 AM"}
    arrivals = {"original": "1:00 PM", "changed": "1:00 PM\n1:47 PM\n(change)",
                "changed-again": "1:47 PM\n1:46 PM\n(change)"}
    parsed = {}
    bodies = {}
    for kind in order:
        bodies[kind] = itinerary(kind) + f"""
Mexico City to Dallas
Saturday, Mar 13, 2027
Flight Change Details
Aeromexico
Flight Number:
AM902
From:
Mexico City (MEX-Mexico City Intl.)
To:
Dallas (DFW-Dallas Fort Worth Intl.)
Status:
CONFIRMED
Depart:
{departures[kind]}
Arrive:
{arrivals[kind]}
Class:
Coach
"""
        parsed[kind] = parse_email(html="", plain_text=bodies[kind], attachments=[], user_name="Alex Taylor",
            aliases=[], received_at=SENT[kind], subject=SUBJECT[kind], from_email="Expedia <notify@example.test>")
        assert len(parsed[kind].flights) == 2
        assert {row.ownership for row in parsed[kind].flights} == {"self"}
        assert not any(getattr(row, "force_review", False) for row in parsed[kind].flights)

    def apply_pair(kind):
        apply_booking_message(db, user.id, deepcopy(parsed[kind]), source_message_id=kind,
            subject=SUBJECT[kind], plain_text=bodies[kind], received_at=SENT[kind])
        db.flush()

    retained = {}
    for kind in order:
        apply_pair(kind)
        current = observations(db, user.id)
        assert all(current[key] == value for key, value in retained.items())
        retained = current
    rows = {row.flight_number: row for row in db.query(Segment)}
    assert set(rows) == {"AM901", "AM902"}
    assert all(row.pnr == "TEST01" for row in rows.values())
    assert (event_time(rows["AM901"].dep_time), event_time(rows["AM901"].arr_time)) == (
        datetime(2027, 3, 12, 20, 19), datetime(2027, 3, 12, 23, 10))
    assert (event_time(rows["AM902"].dep_time), event_time(rows["AM902"].arr_time)) == (
        datetime(2027, 3, 13, 16), datetime(2027, 3, 13, 19, 46))
    assert len(retained) == 6
    stable = deepcopy(_state(db, user.id))
    for repeat in range(4):
        for kind in reversed(order):
            apply_pair(kind)
        current = _state(db, user.id)
        if repeat == 0:
            assert_repeat_capture_only(stable, current)
            stable = deepcopy(current)
        else:
            assert current == stable


@pytest.mark.parametrize("order", list(permutations(("original", "changed", "changed-again"))))
def test_two_explicit_revisions_keep_latest_clocks_and_all_prior_observations(db_user, order):
    db, user = db_user
    retained = {}
    for kind in order:
        apply(db, user, kind)
        current = observations(db, user.id)
        assert all(current[key] == value for key, value in retained.items())
        retained = current
    assert_current(db, user.id, "changed-again")
    latest = db.query(BookingObservation).filter_by(source_message_id="changed-again").one()
    clock = latest.facts["time_provenance"]["date_evidence"]["clock_evidence"]
    assert clock["departure"]["selected"] == "2:19 PM"
    assert clock["departure"]["other_printed_clocks"] == ["1:49 PM"]
    assert clock["arrival"]["selected"] == "5:10 PM"
    assert clock["arrival"]["other_printed_clocks"] == ["4:45 PM"]
    stable = deepcopy(_state(db, user.id))
    for repeat in range(4):
        for kind in order:
            apply(db, user, kind)
        current = _state(db, user.id)
        if repeat == 0:
            assert_repeat_capture_only(stable, current)
            stable = deepcopy(current)
        else:
            assert current == stable


@pytest.mark.parametrize("other_first", [False, True])
def test_revision_keeps_other_passenger_and_separate_booking_evidence_isolated(db_user, other_first):
    db, user = db_user
    if other_first:
        apply(db, user, "changed-again", passenger="MORGAN/JORDAN", source="other-person")
    apply(db, user, "changed", source="mine")
    mine = assert_current(db, user.id, "changed")
    mine_id = mine.id
    if not other_first:
        apply(db, user, "changed-again", passenger="MORGAN/JORDAN", source="other-person")
    apply(db, user, "changed-again", pnr="OTHER2", agency="AGENCY2", number="AM903", source="separate-booking")
    mine = db.get(Segment, mine_id)
    assert event_time(mine.arr_time) == datetime(2027, 3, 12, 22, 45)
    assert mine.pnr == "TEST01" and "OTHER2" not in (mine.meta_json.get("pnr_aliases") or [])
    separate = db.query(Segment).filter_by(flight_number="AM903").one()
    assert separate.pnr == "OTHER2" and "TEST01" not in (separate.meta_json.get("pnr_aliases") or [])
    other = db.query(BookingObservation).filter_by(source_message_id="other-person").one()
    assert other.ownership == "other" and other.facts["passenger_names"] == ["MORGAN/JORDAN"]
    state = _state(db, user.id)
    assert state["inbox"] and state["retained_links"]
    stable = deepcopy(state)
    for repeat in range(4):
        apply(db, user, "changed-again", passenger="MORGAN/JORDAN", source="other-person")
        apply(db, user, "changed-again", pnr="OTHER2", agency="AGENCY2", number="AM903", source="separate-booking")
        apply(db, user, "changed", source="mine")
        current = _state(db, user.id)
        if repeat == 0:
            assert_repeat_capture_only(stable, current)
            stable = deepcopy(current)
        else:
            assert current == stable
