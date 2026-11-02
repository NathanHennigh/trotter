"""Full-timeline context for scoped, non-destructive journey regrouping."""
from copy import deepcopy
from datetime import datetime, timedelta
from itertools import permutations

import pytest

from app.models import BookingObservation, ItineraryHistory, Segment, Trip, User
from app.services import builder
from app.services.booking_ledger import record_user_decision
from test_legacy_local_clock_replay import account  # noqa: F401


def dt(value):
    return datetime.fromisoformat(value)


def snapshot(rows):
    return {row.id: deepcopy({column.name: getattr(row, column.name)
                             for column in row.__table__.columns}) for row in rows}


def add_trip(db, user, title, legs, *, verified=True, meta=None):
    trip = Trip(user_id=user.id, title=title, visibility="private")
    db.add(trip); db.flush()
    result = []
    for index, (departure, arrival, dep, arr) in enumerate(legs):
        evidence = {"ownership": "self", "observation_ids": [1000 + index]} if verified else {}
        evidence.update(meta or {})
        row = Segment(trip_id=trip.id, mode="flight", dep_airport=dep, arr_airport=arr,
                      dep_time=dt(departure), arr_time=dt(arrival), airline="ZZ",
                      flight_number=f"ZZ{100 + index}", pnr=f"B{trip.id:05d}",
                      meta_json=evidence)
        db.add(row); result.append(row)
    db.flush()
    trip.start_ts = min(row.dep_time for row in result)
    trip.end_ts = max(row.arr_time for row in result)
    return trip, result


def country_journey(db, user):
    # The frequent airport is not the origin of this particular roundtrip.
    other, other_rows = add_trip(db, user, "Keep unrelated custom title", [
        ("2024-01-01T12:00", "2024-01-01T14:00", "DFW", "SFO"),
        ("2024-01-04T12:00", "2024-01-04T14:00", "SFO", "DFW"),
    ], verified=False, meta={"note": "must remain untouched"})
    outbound, outbound_rows = add_trip(db, user, "Imported outbound", [
        ("2025-04-26T06:00", "2025-04-26T22:30", "IAH", "TPE"),
        ("2025-04-27T07:15", "2025-04-27T09:35", "TPE", "MNL"),
        ("2025-04-28T06:45", "2025-04-28T07:45", "MNL", "MPH"),
        ("2025-05-03T11:15", "2025-05-03T12:20", "KLO", "MNL"),
    ])
    # The affected trip already contains an incorrect historical attachment.
    combined, combined_rows = add_trip(db, user, "Return with later journey", [
        ("2025-05-09T04:40", "2025-05-09T06:55", "MNL", "TPE"),
        ("2025-05-09T13:20", "2025-05-10T03:20", "TPE", "IAH"),
        ("2025-06-18T23:28", "2025-06-19T02:23", "IAH", "ORD"),
        ("2025-06-22T20:30", "2025-06-22T23:19", "ORD", "IAH"),
    ])
    # Existing domestic/return facts can be legacy, and must not be discarded.
    for row in [*outbound_rows[2:], combined_rows[-1]]:
        row.meta_json = {"legacy_notes": ["retain"]}
    tail, tail_rows = add_trip(db, user, "Independent later roundtrip", [
        ("2026-01-01T12:00", "2026-01-01T14:00", "DFW", "SFO"),
        ("2026-01-05T12:00", "2026-01-05T14:00", "SFO", "DFW"),
    ], verified=False)
    db.flush()
    return outbound, outbound_rows, combined, combined_rows, [other, tail], [*other_rows, *tail_rows]


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setenv("BOOKING_CONTEXTUAL_TRIP_GROUPING_ENABLED", "true")
    monkeypatch.setenv("FLIGHT_IMPORT_RECOVERY_USER_IDS", "*")


@pytest.mark.parametrize("cohort", ["", "invalid", "another", "unlisted", "listed", "*"])
def test_contextual_rebuild_requires_the_affected_account_in_cohort(account, monkeypatch, cohort):
    db, user = account
    trip, _ = add_trip(db, user, "Existing trip", [
        ("2026-01-01T12:00", "2026-01-01T15:00", "DFW", "SFO")])
    monkeypatch.setenv("BOOKING_CONTEXTUAL_TRIP_GROUPING_ENABLED", "true")
    value = str(user.id) if cohort == "listed" else str(user.id + 100) if cohort == "unlisted" else cohort
    monkeypatch.setenv("FLIGHT_IMPORT_RECOVERY_USER_IDS", value)
    called = []
    monkeypatch.setattr(builder, "_rebuild_contextual_trips", lambda *args: called.append(args[1]) or 731)
    result = builder.rebuild_affected_trips(db, user.id, {trip.id})
    assert called == ([user.id] if cohort in {"listed", "*"} else [])
    assert (result == 731) == (cohort in {"listed", "*"})


@pytest.mark.parametrize("seed", ["outbound", "return", "both"])
def test_return_uses_complete_journey_closure_and_leaves_later_roundtrip_separate(account, enabled, seed):
    db, user = account
    outbound, outrows, combined, returnrows, others, otherrows = country_journey(db, user)
    before_facts = snapshot(db.query(Segment).all())
    before_other = snapshot(otherrows), snapshot(others)
    # Explicitly reproduce the old defect: a subset beginning with a return has
    # no original-origin closure, and swallows a later departure from that city.
    subset = builder._cluster_saved_segments(returnrows, "DFW")
    assert len(subset) == 1
    selected = {outbound.id} if seed == "outbound" else {combined.id} if seed == "return" else {outbound.id, combined.id}
    builder.rebuild_affected_trips(db, user.id, selected)
    philippines_ids = {row.trip_id for row in [*outrows, *returnrows[:2]]}
    chicago_ids = {row.trip_id for row in returnrows[2:]}
    assert len(philippines_ids) == len(chicago_ids) == 1
    assert philippines_ids.isdisjoint(chicago_ids)
    assert (snapshot(otherrows), snapshot(others)) == before_other
    after_facts = snapshot(db.query(Segment).all())
    assert before_facts.keys() == after_facts.keys()
    for row_id in before_facts:
        assert {k: v for k, v in before_facts[row_id].items() if k != "trip_id"} == {
            k: v for k, v in after_facts[row_id].items() if k != "trip_id"}
    stable = snapshot(db.query(Segment).all()), snapshot(db.query(Trip).all()), snapshot(db.query(ItineraryHistory).all())
    for _ in range(3):
        builder.rebuild_affected_trips(db, user.id, philippines_ids | chicago_ids)
        assert (snapshot(db.query(Segment).all()), snapshot(db.query(Trip).all()),
                snapshot(db.query(ItineraryHistory).all())) == stable


def test_feature_is_off_by_default(account, monkeypatch):
    db, user = account
    monkeypatch.delenv("BOOKING_CONTEXTUAL_TRIP_GROUPING_ENABLED", raising=False)
    monkeypatch.setattr(builder, "_rebuild_contextual_trips", lambda *args: pytest.fail("disabled path called"))
    trip, rows = add_trip(db, user, "Existing", [("2025-01-01T10:00", "2025-01-01T12:00", "LHR", "CDG")])
    builder.rebuild_affected_trips(db, user.id, {trip.id})
    assert db.query(Segment).count() == 1


@pytest.mark.parametrize("protection", ["manual", "shared", "lock", "manual_group", "manual_id", "decision", "decision_alias", "accepted_reference", "public"])
@pytest.mark.parametrize("seed_protected", [True, False])
def test_protected_trip_stays_identical_even_when_directly_affected(account, enabled, protection, seed_protected):
    db, user = account
    outbound, outrows, combined, returnrows, _, _ = country_journey(db, user)
    meta = dict(returnrows[0].meta_json)
    if protection == "manual": meta["source"] = "manual"
    if protection == "shared": meta["source"] = "accepted_flight_share"
    if protection == "lock": meta["trip_grouping_locked"] = True
    if protection == "manual_group": meta["manual_grouping"] = True
    if protection == "manual_id": meta["manual_trip_id"] = combined.id
    if protection == "decision":
        record_user_decision(db, user.id, returnrows[0], reason="Explicit confirmed travel")
    if protection == "decision_alias":
        from types import SimpleNamespace
        alias = SimpleNamespace(**{column.name: getattr(returnrows[0], column.name)
                                  for column in Segment.__table__.columns})
        alias.pnr = "ALIAS1"
        meta["pnr_aliases"] = ["ALIAS1"]
        record_user_decision(db, user.id, alias, reason="Explicit alias confirmation")
    if protection == "accepted_reference":
        from test_booking_leg_lineage_independent_review import share
        sender = User(name="Sender", email="sender@example.test")
        db.add(sender); db.flush()
        share(db, sender, user, segment_ids=[returnrows[0].id])
        meta["source"] = "receipt"
    if protection == "public": combined.visibility = "public"
    returnrows[0].meta_json = meta
    db.flush()
    before = snapshot(returnrows), snapshot([combined])
    selected = {outbound.id, combined.id} if seed_protected else {outbound.id}
    builder.rebuild_affected_trips(db, user.id, selected)
    assert (snapshot(returnrows), snapshot([combined])) == before


def test_other_account_and_unrelated_empty_draft_are_untouched(account, enabled):
    db, user = account
    outbound, _, combined, _, _, _ = country_journey(db, user)
    other = User(name="Different traveler", email="different@example.test")
    db.add(other); db.flush()
    other_trip, other_rows = add_trip(db, other, "Independent", [
        ("2025-05-04T01:00", "2025-05-04T04:00", "MNL", "SIN")])
    draft = Trip(user_id=user.id, title="Unrelated draft")
    db.add(draft); db.flush()
    before = snapshot(other_rows), snapshot([other_trip, draft])
    builder.rebuild_affected_trips(db, user.id, {combined.id, other_trip.id})
    assert (snapshot(other_rows), snapshot([other_trip, draft])) == before


def test_noop_does_not_erase_custom_title_or_add_history(account, enabled):
    db, user = account
    trip, rows = add_trip(db, user, "A title I chose", [
        ("2025-01-01T10:00", "2025-01-01T12:00", "IAH", "DCA"),
        ("2025-01-05T10:00", "2025-01-05T12:00", "IAD", "IAH"),
    ])
    before = snapshot(rows), snapshot([trip])
    builder.rebuild_affected_trips(db, user.id, {trip.id})
    assert (snapshot(rows), snapshot([trip])) == before
    assert db.query(ItineraryHistory).count() == 0


def test_changed_clocks_refresh_derived_bounds_without_touching_custom_title(account, enabled):
    db, user = account
    trip, rows = add_trip(db, user, "A title I chose", [("2025-01-01T10:00", "2025-01-01T12:00", "LHR", "CDG")])
    rows[0].arr_time += timedelta(hours=1)
    builder.rebuild_affected_trips(db, user.id, {trip.id})
    assert trip.title == "A title I chose"
    assert trip.end_ts == rows[0].arr_time
    assert db.query(ItineraryHistory).filter_by(entity_type="trip", entity_id=trip.id).count() == 1


def test_unknown_external_trip_is_not_absorbed_by_timing(account, enabled):
    db, user = account
    out, outrows = add_trip(db, user, "Known outbound", [("2025-01-01T10:00", "2025-01-01T12:00", "IAH", "MNL")])
    other, otherrows = add_trip(db, user, "Unverified legacy", [("2025-01-05T10:00", "2025-01-05T12:00", "MNL", "IAH")], verified=False)
    before = snapshot(otherrows), snapshot([other])
    builder.rebuild_affected_trips(db, user.id, {out.id})
    assert (snapshot(otherrows), snapshot([other])) == before
    assert outrows[0].trip_id != otherrows[0].trip_id


def test_affected_empty_shell_is_cleaned_but_unrelated_draft_is_not(account, enabled):
    db, user = account
    empty = Trip(user_id=user.id, title="Import shell")
    other = Trip(user_id=user.id, title="Keep draft")
    db.add_all([empty, other]); db.flush()
    empty_id = empty.id
    builder.rebuild_affected_trips(db, user.id, {empty_id})
    assert db.get(Trip, empty_id) is None
    assert db.get(Trip, other.id) is other
    assert db.query(ItineraryHistory).filter_by(entity_type="trip", entity_id=empty_id).count() == 1


@pytest.mark.parametrize("order", list(permutations(("outbound", "return", "later"))))
def test_incremental_source_order_converges_without_rewriting_flight_facts(account, enabled, order):
    db, user = account
    add_trip(db, user, "Earlier context", [
        ("2024-01-01T10:00", "2024-01-01T12:00", "DFW", "SFO"),
        ("2024-01-04T10:00", "2024-01-04T12:00", "SFO", "DFW")], verified=False)
    add_trip(db, user, "Later context", [
        ("2026-01-01T10:00", "2026-01-01T12:00", "DFW", "SFO"),
        ("2026-01-04T10:00", "2026-01-04T12:00", "SFO", "DFW")], verified=False)
    sources = {
        "outbound": [
            ("2025-04-26T06:00", "2025-04-26T22:30", "IAH", "TPE"),
            ("2025-04-27T07:15", "2025-04-27T09:35", "TPE", "MNL")],
        "return": [
            ("2025-05-09T04:40", "2025-05-09T06:55", "MNL", "TPE"),
            ("2025-05-09T13:20", "2025-05-10T03:20", "TPE", "IAH")],
        "later": [
            ("2025-06-18T23:28", "2025-06-19T02:23", "IAH", "ORD"),
            ("2025-06-22T20:30", "2025-06-22T23:19", "ORD", "IAH")],
    }
    by_source = {}
    for source in order:
        trip, rows = add_trip(db, user, source, sources[source])
        by_source[source] = rows
        before = snapshot(db.query(Segment).all())
        builder.rebuild_affected_trips(db, user.id, {trip.id})
        after = snapshot(db.query(Segment).all())
        assert before.keys() == after.keys()
        for row_id in before:
            assert {k: v for k, v in before[row_id].items() if k != "trip_id"} == {
                k: v for k, v in after[row_id].items() if k != "trip_id"}
    abroad = {row.trip_id for source in ("outbound", "return") for row in by_source[source]}
    later = {row.trip_id for row in by_source["later"]}
    assert len(abroad) == len(later) == 1 and abroad.isdisjoint(later)
    stable = snapshot(db.query(Segment).all()), snapshot(db.query(Trip).all()), snapshot(db.query(ItineraryHistory).all())
    for source in reversed(order):
        builder.rebuild_affected_trips(db, user.id, {row.trip_id for row in by_source[source]})
    assert (snapshot(db.query(Segment).all()), snapshot(db.query(Trip).all()),
            snapshot(db.query(ItineraryHistory).all())) == stable
