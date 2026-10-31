"""A completed journey keeps its boundary away from the most-used airport."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.models import Segment, Trip
from app.services import builder
from test_legacy_local_clock_replay import account  # noqa: F401


@pytest.mark.parametrize("pnr", ["RETURN", "LATER1"])
def test_completed_origin_return_starts_new_journey_after_two_days(pnr):
    current = [SimpleNamespace(dep_airport="IAH", arr_airport="CLT", pnr="RETURN"),
               SimpleNamespace(dep_airport="CLT", arr_airport="IAH", pnr="RETURN")]
    next_leg = SimpleNamespace(dep_airport="IAH", arr_airport="MIA", pnr=pnr)
    assert not builder._belongs_to_current_trip(current, next_leg, timedelta(days=5), "DFW", {"DFW"})


@pytest.mark.parametrize("gap", [timedelta(hours=3), timedelta(hours=48)])
def test_short_continuation_retains_existing_grouping(gap):
    current = [SimpleNamespace(dep_airport="IAH", arr_airport="CLT", pnr="RETURN"),
               SimpleNamespace(dep_airport="CLT", arr_airport="IAH", pnr="RETURN")]
    next_leg = SimpleNamespace(dep_airport="IAH", arr_airport="MIA", pnr="RETURN")
    assert builder._belongs_to_current_trip(current, next_leg, gap, "DFW", {"DFW"})


def test_away_city_side_trip_does_not_end_the_whole_journey():
    current = [SimpleNamespace(dep_airport="IAH", arr_airport="NRT", pnr="AWAY01"),
               SimpleNamespace(dep_airport="NRT", arr_airport="SIN", pnr="AWAY01"),
               SimpleNamespace(dep_airport="SIN", arr_airport="NRT", pnr="AWAY01")]
    next_leg = SimpleNamespace(dep_airport="NRT", arr_airport="IAH", pnr="AWAY01")
    assert builder._belongs_to_current_trip(current, next_leg, timedelta(days=5), "DFW", {"DFW"})


def test_reimport_preserves_separate_round_trip_ids_and_visibility(account, monkeypatch):
    db, user = account
    monkeypatch.setattr(builder, "_infer_home_airport", lambda _: "DFW")
    first = Trip(user_id=user.id, title="Charlotte", visibility="private")
    second = Trip(user_id=user.id, title="Tulum", visibility="private")
    db.add_all([first, second]); db.flush()
    start = datetime(2025, 8, 9, 12, tzinfo=timezone.utc)
    groups = []
    for trip, pnr, legs in [
        (first, "RETURN", [("IAH", "CLT", 0), ("CLT", "IAH", 2)]),
        (second, "LATER1", [("IAH", "MIA", 7), ("MIA", "TQO", 7.2),
                             ("TQO", "DFW", 14), ("DFW", "IAH", 14.2)]),
    ]:
        rows = []
        for index, (dep, arr, day) in enumerate(legs):
            departure = start + timedelta(days=day)
            row = Segment(trip_id=trip.id, mode="flight", dep_airport=dep, arr_airport=arr,
                          dep_time=departure, arr_time=departure+timedelta(hours=2),
                          airline="AA", flight_number=f"AA{index+100}", pnr=pnr,
                          meta_json={"ownership": "self", "observation_ids": [index+1]})
            db.add(row); rows.append(row)
        groups.append((trip.id, rows))
    db.flush()
    original = {row.id: trip_id for trip_id, rows in groups for row in rows}
    for _ in range(2):
        builder.rebuild_affected_trips(db, user.id, {first.id, second.id})
        assert {row.id: row.trip_id for row in db.query(Segment).all()} == original
        assert db.query(Trip).count() == 2
        assert all(trip.visibility == "private" for trip in db.query(Trip).all())
