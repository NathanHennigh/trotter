from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.services.flight_times import normalize_flight_times, resolve_printed_elapsed_arrival
from app.services.parser import _shape_ota_multi_confirmation


def make(dep, arr, day, dep_clock, arr_clock, minutes, next_day=None):
    value = SimpleNamespace(dep_airport=dep, arr_airport=arr,
        dep_time=datetime.fromisoformat(day + "T" + dep_clock).replace(tzinfo=timezone.utc),
        arr_time=datetime.fromisoformat(day + "T" + arr_clock).replace(tzinfo=timezone.utc),
        time_provenance={}, force_review=False)
    resolve_printed_elapsed_arrival(value, minutes=minutes, explicit_day_offset=next_day)
    normalize_flight_times(value)
    return value


@pytest.mark.parametrize("dep,arr,day,start,end,minutes,offset,expected", [
    ("NRT", "IAH", "2025-10-03", "17:00", "14:55", 715, None, "2025-10-03T19:55:00+00:00"),
    ("JFK", "LAX", "2025-07-11", "17:00", "16:45", 165, None, "2025-07-11T23:45:00+00:00"),
    ("IAH", "TPE", "2025-04-26", "01:00", "06:30", 990, 1, "2025-04-26T22:30:00+00:00"),
    ("JFK", "LHR", "2025-07-11", "22:00", "10:00", 420, 1, "2025-07-12T09:00:00+00:00"),
])
def test_unique_elapsed_proof_resolves_day_without_changing_clocks(dep, arr, day, start, end, minutes, offset, expected):
    value = make(dep, arr, day, start, end, minutes, offset)
    assert not value.force_review
    assert value.arr_time.isoformat() == expected
    assert value.time_provenance["arrival"]["local"].endswith(end + ":00")
    assert value.time_provenance["date_evidence"]["status"] == "verified"
    before = (value.dep_time, value.arr_time, value.time_provenance.copy())
    normalize_flight_times(value)
    assert (value.dep_time, value.arr_time, value.time_provenance) == before


@pytest.mark.parametrize("duration,explicit_offset", [(700, None), (715, 1)])
def test_conflicting_duration_or_explicit_day_is_held(duration, explicit_offset):
    value = make("NRT", "IAH", "2025-10-03", "17:00", "14:55", duration, explicit_offset)
    assert value.force_review
    assert value.time_provenance["status"] == "needs_review"
    assert value.time_provenance["reason"] == "printed_flight_duration_conflict"


def test_dst_ambiguous_clock_is_not_resolved_by_duration_guess():
    value = make("IAH", "DCA", "2025-11-02", "01:30", "05:30", 180)
    assert value.force_review
    assert value.time_provenance["status"] == "needs_review"


def ota(duration):
    return f"""Your confirmation codes
ANA
TEST01
Return to Houston
October 03, 2025
ANA - NH6450
Tokyo
NRT
5:00 p.m.
{duration}
Houston
IAH
2:55 p.m.
Operated by United.
Fare Details
Alex Avery
"""


def test_ota_shape_uses_per_flight_duration():
    value, = _shape_ota_multi_confirmation(ota("11h 55m"), fallback_pnr=None, received_at=datetime(2025, 9, 25))
    normalize_flight_times(value)
    assert value.dep_time.isoformat() == "2025-10-03T08:00:00+00:00"
    assert value.arr_time.isoformat() == "2025-10-03T19:55:00+00:00"
    assert value.time_provenance["date_evidence"]["minutes"] == 715


def test_no_printed_flight_duration_preserves_existing_path():
    value, = _shape_ota_multi_confirmation(ota(""), fallback_pnr=None, received_at=datetime(2025, 9, 25))
    assert value.arr_time.day == 4
    assert not value.time_provenance


def test_layover_duration_is_not_a_flight_duration():
    value, = _shape_ota_multi_confirmation(ota("11h 55m layover in Tokyo"), fallback_pnr=None, received_at=datetime(2025, 9, 25))
    assert value.arr_time.day == 4
    assert not value.time_provenance


@pytest.mark.parametrize("layover", ["Layover in Tokyo\n11h 55m", "11h 55m\nLayover in Tokyo"])
def test_separate_layover_label_cannot_prove_a_flight_arrival_day(layover):
    value, = _shape_ota_multi_confirmation(ota(layover), fallback_pnr=None, received_at=datetime(2025, 9, 25))
    assert value.arr_time.day == 4
    assert not value.time_provenance


@pytest.mark.parametrize("trailing", [
    "Total journey time\n35h 55m", "Total travel duration\n35h 55m",
    "Layover in Houston\n35h 55m", "35h 55m\nLayover in Houston", "35h 55m",
])
def test_duration_after_arrival_is_not_individual_flight_evidence(trailing):
    text = ota("").replace("Operated by United.", trailing + "\nOperated by United.")
    value, = _shape_ota_multi_confirmation(text, fallback_pnr=None, received_at=datetime(2025, 9, 25))
    assert value.arr_time.day == 4
    assert not value.time_provenance


@pytest.mark.parametrize("label", ["Total journey time", "Total travel duration"])
@pytest.mark.parametrize("before", [False, True])
def test_total_label_between_clocks_does_not_prove_flight_duration(label, before):
    block = label + "\n35h 55m" if before else "35h 55m\n" + label
    value, = _shape_ota_multi_confirmation(ota(block), fallback_pnr=None, received_at=datetime(2025, 9, 25))
    assert value.arr_time.day == 4
    assert not value.time_provenance


def test_real_per_flight_duration_is_not_confused_by_trailing_total():
    text = ota("11h 55m").replace("Operated by United.", "Total journey time\n35h 55m")
    value, = _shape_ota_multi_confirmation(text, fallback_pnr=None, received_at=datetime(2025, 9, 25))
    normalize_flight_times(value)
    assert value.arr_time.isoformat() == "2025-10-03T19:55:00+00:00"
    assert value.time_provenance["date_evidence"]["minutes"] == 715


def test_missing_arrival_airport_cannot_borrow_next_flight_endpoint():
    text = """Your confirmation codes
EVA Air
TEST01
Return to Houston
May 09, 2025
EVA Air - BR272
Manila
MNL
12:40 p.m.
2h 15m
2:55 p.m.
6h 25m layover in Taipei
EVA Air - BR52
9:20 p.m.
14h
Houston
IAH
10:20 p.m.
"""
    values = _shape_ota_multi_confirmation(text, fallback_pnr=None, received_at=datetime(2025, 1, 1))
    value = next(value for value in values if value.flight_number == "BR272")
    normalize_flight_times(value)
    assert value.force_review
    assert value.time_provenance["reason"] == "flight_endpoint_crosses_next_flight"
    assert value.time_provenance["date_evidence"]["kind"] == "flight_endpoint_scope"


@pytest.mark.parametrize("protected", [False, True])
def test_source_supported_arrival_day_corrects_original_id_and_respects_hold(protected):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.models import Base, User, Trip, Segment
    from app.services.booking_import import apply_booking_message
    from app.services.booking_ledger import record_user_decision
    from app.services.parser import ParseResult
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = User(name="Alex Avery", email="alex@example.test")
        db.add(user)
        db.flush()
        original_dep = datetime(2025, 10, 3, 17)
        original_arr = datetime(2025, 10, 4, 14, 55)
        trip = Trip(user_id=user.id, title="Original journey", start_ts=original_dep, end_ts=original_arr)
        db.add(trip)
        db.flush()
        segment = Segment(trip_id=trip.id, mode="flight", dep_airport="NRT", arr_airport="IAH",
            dep_time=original_dep, arr_time=original_arr, airline="NH", flight_number="NH6450", pnr="TEST01",
            meta_json={"source": "v5", "source_received_at": "2025-09-25T19:44:08Z"})
        db.add(segment)
        db.flush()
        original_id = segment.id
        value, = _shape_ota_multi_confirmation(ota("11h 55m"), fallback_pnr=None, received_at=datetime(2025, 9, 25))
        value.ownership, value.passenger_names = "self", ["Alex Avery"]
        normalize_flight_times(value)
        if protected:
            record_user_decision(db, user.id, value, status="hold")
        apply_booking_message(db, user.id, ParseResult(flights=[value]), source_message_id="receipt-proof",
            subject="Your flight receipt", received_at="2025-09-25T19:44:19Z")
        result = db.query(Segment).one()
        assert result.id == original_id
        assert result.arr_time == (original_arr if protected else datetime(2025, 10, 3, 19, 55))
        if not protected:
            assert result.dep_time == datetime(2025, 10, 3, 8)
            assert result.meta_json["time_provenance"]["date_evidence"]["minutes"] == 715
