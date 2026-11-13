"""Empty HTML layout cells must not hide an explicit visible traveler roster."""
import base64
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from html import escape
from itertools import permutations

import pytest

from app.models import BookingObservation, Segment, TravelInboxItem, User
from app.services.booking_import import apply_booking_message
from app.services.booking_legacy_repair import _state
from app.services.booking_projection_context import projection_run
from app.services.flight_import_rollout import ALLOWLIST_ENV, FEATURE_FLAGS
from app.services.flight_message import prepare_flight_message
from app.services.parser import ParsedFlight
from app.services.passenger_identity import apply_passenger_identity
from test_booking_lifecycle_hardening import db_user
from test_booking_protected_trip_inserts import protect


HEADER = '<tr><td><img alt="" src="icon.png"></td><td>Traveler Information</td></tr>'
PERSON = ('<tr><td><div>Alex Morgan (Adult)</div><div>Ticket Number:</div>'
          '<div>0060000000123</div></td></tr>')
ROSTER = '<table>' + HEADER + PERSON + '</table>'


def identify(html, *, pnrs=("AGCY12",), user="Alex Morgan"):
    start = datetime(2027, 7, 10, 6, tzinfo=timezone.utc)
    flights = [ParsedFlight("DFW", "LAX", start, start + timedelta(hours=3),
                            airline="DL", flight_number="DL901", pnr=pnr) for pnr in pnrs]
    apply_passenger_identity(flights, html=html, plain_text="", user_name=user, aliases=[])
    return flights


@pytest.mark.parametrize("padding", [
    '<td></td>', '<td> </td><td></td>', '<td><img alt="" src="icon.png"></td>',
])
@pytest.mark.parametrize("heading", ["Traveler Information", "Traveler Information:"])
def test_visible_exact_heading_with_empty_layout_cells_preserves_roster(padding, heading):
    html = '<table><tr>' + padding + '<td>' + heading + '</td></tr>' + PERSON + '</table>'
    row = identify(html + '<p>Airline Confirmation: AGCY12</p>')[0]
    assert row.ownership == "self"
    assert row.passenger_names == ["Alex Morgan"]
    assert all(e["complete"] and e["scope"] == {"pnr": "AGCY12"} for e in row.passenger_evidence)


@pytest.mark.parametrize("html", [
    ROSTER.replace('alt=""', 'alt="Cardholder"').replace('<td><img', '<td>Cardholder<img'),
    ROSTER.replace('Traveler Information', 'Traveler Information is available online'),
    ROSTER.replace('Traveler Information', 'Cardholder Information'),
    ROSTER.replace('Traveler Information', '| Traveler Information'),
    ROSTER.replace('<td>Traveler Information', '<td hidden>Traveler Information'),
    ROSTER.replace('<td><div>Alex', '<td hidden><div>Alex'),
    ROSTER.replace(PERSON, ''),
    '<template>' + ROSTER + '</template>',
    '<section hidden>' + ROSTER + '</section>',
    '<noscript>' + ROSTER + '</noscript>',
    '<script>' + ROSTER + '</script>',
    '<style>' + ROSTER + '</style>',
])
def test_nonempty_prose_payer_literal_pipe_and_inert_content_gain_no_authority(html):
    row = identify(html + '<p>Airline Confirmation: AGCY12</p>')[0]
    assert row.ownership == "unknown"
    assert row.passenger_names == []


def test_noninteractive_but_visible_content_keeps_existing_visibility_semantics():
    padded = '<div inert>' + ROSTER + '</div>'
    ordinary = padded.replace('<td><img alt="" src="icon.png"></td>', '')
    assert identify(padded)[0].ownership == identify(ordinary)[0].ownership == "self"


def test_other_traveler_is_not_replaced_by_the_account_or_cardholder():
    html = '<p>Hello Alex Morgan</p>' + ROSTER.replace('Alex Morgan', 'Taylor Reed')
    html += '<p>Cardholder: Alex Morgan</p><p>Airline Confirmation: AGCY12</p>'
    row = identify(html)[0]
    assert row.ownership == "other" and row.passenger_names == ["Taylor Reed"]


def test_strict_middle_name_conflict_remains_other():
    row = identify(ROSTER.replace('Alex Morgan', 'Alex Jordan Morgan'), user="Alex Casey Morgan")[0]
    assert row.ownership == "other"


def test_unscoped_roster_does_not_claim_multiple_bookings():
    rows = identify(ROSTER, pnrs=("AGCY12", "OTHER3"))
    assert [row.ownership for row in rows] == ["unknown", "unknown"]
    assert all(not row.passenger_names for row in rows)


def test_two_explicit_booking_sections_keep_passenger_scopes_separate():
    html = '<p>Airline Confirmation: AGCY12</p>' + ROSTER
    html += '<p>Airline Confirmation: OTHER3</p>' + ROSTER.replace('Alex Morgan', 'Taylor Reed')
    rows = identify(html, pnrs=("AGCY12", "OTHER3"))
    assert [(row.ownership, row.passenger_names) for row in rows] == [
        ("self", ["Alex Morgan"]), ("other", ["Taylor Reed"])]


def prepared(kind):
    latest = kind != "original"
    clocks = ("06:15 AM", "07:25 AM", "11:10 AM", "03:26 PM") if latest else (
        "06:00 AM", "07:13 AM", "10:30 AM", "03:15 PM")
    durations = ("03H 10M", "05H 16M") if latest else ("03H 13M", "05H 45M")
    roster = ROSTER if kind == "original" else '<p>Passengers: Alex Morgan (Adult), E-ticket 0060000000123</p>'
    lines = f"""Your reservation is booked and confirmed.
Saturday, July 10, 2027
Delta Air Lines - Dallas to Los Angeles
From:
DFW
Dallas, Texas, US
{clocks[0]}
To:
LAX
Los Angeles, California, US
{clocks[1]}
Flight Number:
DL 901
Airline Confirmation:
AGCY12
Duration:
{durations[0]}, Non-Stop
Saturday, July 10, 2027
Delta Air Lines - Los Angeles to Anchorage
From:
LAX
Los Angeles, California, US
{clocks[2]}
To:
ANC
Anchorage, Alaska, US
{clocks[3]}
Flight Number:
DL 902
Airline Confirmation:
AGCY12
Duration:
{durations[1]}, Non-Stop
"""
    html = roster + ''.join('<p>' + escape(line) + '</p>' for line in lines.splitlines())
    month = {"original": 2, "change": 4, "reminder": 7}[kind]
    event = datetime(2027, month, 2, 12, tzinfo=timezone.utc)
    subject = {"original": "Confirmed: your trip to Anchorage", "change": "Flight Schedule Change",
               "reminder": "Review details for your upcoming trip"}[kind]
    message = {"id": kind, "internalDate": str(int(event.timestamp() * 1000)), "payload": {
        "mimeType": "text/html", "headers": [
            {"name": "Subject", "value": subject}, {"name": "Date", "value": format_datetime(event)},
            {"name": "From", "value": "Travel <AmericanExpress@welcome.americanexpress.com>"}],
        "body": {"data": base64.urlsafe_b64encode(html.encode()).decode()}}}
    result = prepare_flight_message(message, user_name="Alex Morgan", aliases=[])
    assert len(result["parse_result"].flights) == 2
    assert all(f.ownership == "self" and f.passenger_names == ["Alex Morgan"] for f in result["parse_result"].flights)
    return result


def policy(monkeypatch, user_id, setting):
    for flag in FEATURE_FLAGS:
        monkeypatch.setenv(flag, "false" if setting == "off" else "true")
    monkeypatch.setenv(ALLOWLIST_ENV, str(user_id if setting == "on" else user_id + 100))


def ingest(db, user, source):
    with projection_run(db, user.id):
        result = apply_booking_message(db, user.id, deepcopy(source["parse_result"]),
            source_message_id=source["msg_id"], subject=source["subject"], plain_text=source["plain_text"],
            html=source["html"], received_at=source["received_at"])
    db.commit()
    return result


def assert_latest(db):
    expected = {"DL901": (datetime(2027, 7, 10, 11, 15), datetime(2027, 7, 10, 14, 25)),
                "DL902": (datetime(2027, 7, 10, 18, 10), datetime(2027, 7, 10, 23, 26))}
    rows = db.query(Segment).all()
    assert len(rows) == 2 and len({r.trip_id for r in rows}) == 1
    assert all((r.dep_time, r.arr_time) == expected[r.flight_number] and r.pnr == "AGCY12" for r in rows)
    assert db.query(TravelInboxItem).count() == 0


def repeat(db, user, sources):
    before = _state(db, user.id)
    for index in range(4):
        for source in sources:
            ingest(db, user, source)
        current = _state(db, user.id)
        if index == 0:
            assert {k: v for k, v in before.items() if k != "history"} == {
                k: v for k, v in current.items() if k != "history"}
            for key, row in current["history"].items():
                if key in before["history"]:
                    assert row == before["history"][key]
                else:
                    assert row["entity_type"] in ("trip", "segment")
                    assert row["snapshot"] == before[row["entity_type"] + "s"][str(row["entity_id"])]
        else:
            assert current == before
        before = current


@pytest.mark.parametrize("setting", ["off", "unlisted", "on"])
@pytest.mark.parametrize("order", list(permutations(("original", "change", "reminder"))))
def test_later_schedule_wins_every_receipt_order_without_unassigned_copies(db_user, monkeypatch, setting, order):
    db, user = db_user
    policy(monkeypatch, user.id, setting)
    sources = [prepared(kind) for kind in order]
    for source in sources:
        ingest(db, user, source)
    assert_latest(db)
    assert db.query(BookingObservation).count() == 6
    repeat(db, user, sources)


@pytest.mark.parametrize("setting", ["off", "unlisted", "on"])
@pytest.mark.parametrize("protection", ["public", "manual", "user_review", "accepted_flight_share",
    "flight_share", "manual_grouping", "trip_grouping_locked", "personal_note", "decision", "accepted_reference"])
def test_old_named_receipt_preserves_latest_ids_and_protected_records(db_user, monkeypatch, setting, protection):
    db, user = db_user
    policy(monkeypatch, user.id, setting)
    sources = [prepared(kind) for kind in ("original", "change", "reminder")]
    ingest(db, user, sources[-1])
    rows = db.query(Segment).all()
    for row in rows:
        if protection == "personal_note":
            row.meta_json = {**row.meta_json, "personal_note": "Keep this note"}
        elif protection == "accepted_reference":
            pass
        else:
            protect(db, row, protection)
    if protection == "accepted_reference":
        from test_booking_leg_lineage_independent_review import share
        sender = User(name="Independent Sender", email="sender@example.test")
        db.add(sender); db.flush()
        share(db, sender, user, segment_ids=[row.id for row in rows])
    db.commit()
    before = _state(db, user.id)
    for source in sources:
        ingest(db, user, source)
    assert_latest(db)
    after = _state(db, user.id)
    assert after["trips"] == before["trips"] and after["shares"] == before["shares"]
    assert set(after["segments"]) == set(before["segments"])
    assert all(after["observations"][key] == value for key, value in before["observations"].items())
    for key, old in before["segments"].items():
        current = after["segments"][key]
        assert current["trip_id"] == old["trip_id"]
        if protection in {"manual", "user_review", "accepted_flight_share", "flight_share"}:
            assert current["meta_json"]["source"] == protection
        elif protection in {"manual_grouping", "trip_grouping_locked", "personal_note"}:
            assert current["meta_json"][protection] == old["meta_json"][protection]
    repeat(db, user, sources)
