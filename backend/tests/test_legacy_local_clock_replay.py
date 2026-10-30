"""Normal-import replay against legacy rows with no source observation links."""
from copy import deepcopy
from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import Base, BookingObservation, MessageStatus, Segment, Trip, User
from app.routers.trips import SegmentOut
from app.services.booking_import import apply_booking_message
from app.services.booking_ledger import record_cancellation, record_flight_observations, record_user_decision
from app.services.flight_times import normalize_flight_times
from app.services.parser import ParsedFlight, ParseResult


def dt(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


@pytest.fixture
def account():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = User(name="Alex Avery", email="alex@example.test")
        db.add(user); db.flush()
        yield db, user
    engine.dispose()


def flight(*, pnr="BOOK01", dep="ATL", arr="IAH", number="NK512",
           departure="2025-02-23T20:49:00Z", arrival="2025-02-23T22:10:00Z", ownership="self"):
    value = ParsedFlight(dep, arr, dt(departure), dt(arrival), airline=number[:2],
        flight_number=number, pnr=pnr, source="receipt", ownership=ownership,
        passenger_names=["Alex Avery"], passenger_evidence=[{"name": "Alex Avery", "role": "traveler",
            "applies": True, "complete": True, "scope_ambiguous": False, "scope": {"pnr": pnr}}])
    normalize_flight_times(value)
    return value


def seed(db, user, value, *, pnr=None, source_time="2025-01-01T12:00:00Z", note="keep"):
    provenance = value.time_provenance
    dep = dt(provenance["departure"]["original"])
    arr = dt(provenance["arrival"]["original"])
    trip = Trip(user_id=user.id, title="Original journey", start_ts=dep, end_ts=arr)
    db.add(trip); db.flush()
    row = Segment(trip_id=trip.id, mode="flight", dep_airport=value.dep_airport,
        arr_airport=value.arr_airport, dep_time=dep, arr_time=arr, airline=value.airline,
        flight_number=value.flight_number, pnr=pnr or value.pnr,
        meta_json={"source": "v5", "source_received_at": dt(source_time).isoformat(), "personal_note": note})
    db.add(row); db.commit()
    return row


def apply(db, user, flights, *, source="original-message", received="2025-01-02T12:00:00Z"):
    result = apply_booking_message(db, user.id, ParseResult(flights=deepcopy(flights)),
        source_message_id=source, subject="Flight confirmation", received_at=dt(received))
    db.commit()
    return result


def test_local_date_rollover_updates_legacy_id_once_and_preserves_display_clocks(account):
    db, user = account
    incoming = flight()
    old = seed(db, user, incoming)
    original_id = old.id
    for _ in range(2):
        result = apply(db, user, [incoming])
        assert result.build.inserted == 0 and result.build.updated == 1
        assert result.status == MessageStatus.ACCEPTED
        row = db.query(Segment).one()
        assert row.id == original_id and row.dep_time.isoformat() == "2025-02-24T01:49:00"
        assert row.arr_time.isoformat() == "2025-02-24T04:10:00"
        assert row.meta_json["personal_note"] == "keep"
        output = SegmentOut.model_validate(row).model_dump(mode="json")
        assert output["dep_time"] == "2025-02-23T20:49:00-05:00"
        assert output["arr_time"] == "2025-02-23T22:10:00-06:00"
    assert db.query(BookingObservation).count() == 1


def test_older_receipt_normalizes_identical_clocks_without_replacing_newer_source(account):
    db, user = account
    incoming = flight()
    old = seed(db, user, incoming, source_time="2025-01-20T12:00:00Z")
    result = apply(db, user, [incoming])
    assert result.build.inserted == 0
    assert db.query(Segment).one().id == old.id
    assert old.meta_json["source_received_at"] == "2025-01-20T12:00:00+00:00"
    assert old.meta_json["source"] == "v5"
    assert old.meta_json["time_provenance"]["status"] == "normalized"


@pytest.mark.parametrize("route,number,departure,arrival", [
    (("ATL", "IAH"), "NK512", "2025-02-23T20:49:00Z", "2025-02-23T22:10:00Z"),
    (("ACT", "DFW"), "AA3393", "2026-09-09T05:10:00Z", "2026-09-09T06:05:00Z"),
    (("DCA", "DFW"), "AA1414", "2026-09-11T17:01:00Z", "2026-09-11T19:29:00Z"),
])
def test_linked_legacy_row_with_newer_receipt_normalizes_only_identical_wall_clocks(account, route, number, departure, arrival):
    db, user = account
    incoming = flight(dep=route[0], arr=route[1], number=number, departure=departure, arrival=arrival)
    old = seed(db, user, incoming, source_time="2026-09-08T12:00:00Z")
    previous = deepcopy(incoming)
    previous.dep_time = dt(incoming.time_provenance["departure"]["original"])
    previous.arr_time = dt(incoming.time_provenance["arrival"]["original"])
    previous.time_provenance = {}
    record_flight_observations(db, user.id, [previous], source_message_id="original-message",
                               source_event_at=dt("2025-01-02T12:00:00Z"))
    observation = db.query(BookingObservation).one()
    original_facts = deepcopy(observation.facts)
    old.meta_json = {**old.meta_json, "observation_ids": [observation.id],
                     "source_message_ids": ["original-message"], "ownership": "self"}
    db.commit()
    old_id = old.id
    for _ in range(2):
        result = apply(db, user, [incoming])
        assert result.build.inserted == 0 and result.build.updated == 1
        row = db.query(Segment).one()
        assert row.id == old_id
        assert row.dep_time == incoming.dep_time.replace(tzinfo=None)
        assert row.arr_time == incoming.arr_time.replace(tzinfo=None)
        assert row.meta_json["source_received_at"] == "2026-09-08T12:00:00+00:00"
        assert row.meta_json["time_provenance"] == incoming.time_provenance
        assert db.get(BookingObservation, observation.id).facts == original_facts


@pytest.mark.parametrize("source", ["jsonld", "ics"])
def test_known_absolute_legacy_sources_are_not_reinterpreted_as_local_clocks(account, source):
    db, user = account
    incoming = flight()
    old = seed(db, user, incoming, source_time="2025-01-20T12:00:00Z")
    old.meta_json = {**old.meta_json, "source": source}
    db.commit()
    original = (old.dep_time, old.arr_time)
    apply(db, user, [incoming])
    assert db.query(Segment).count() == 1
    assert (old.dep_time, old.arr_time) == original
    assert not old.meta_json.get("time_provenance")


def test_conflicting_colisted_reference_is_held_without_alias_or_losing_other_valid_leg(account):
    db, user = account
    incoming = flight(pnr="NEW001", dep="DCA", arr="MCO", number="B62023",
                      departure="2025-02-21T15:00:00Z", arrival="2025-02-21T17:40:00Z")
    old = seed(db, user, incoming, pnr="OLD001", source_time="2025-01-03T23:59:48Z")
    before = (old.id, old.trip_id, old.dep_time, old.arr_time, old.pnr, deepcopy(old.meta_json))
    incoming.passenger_evidence[0]["scope"] = {"pnrs": ["NEW001", "OLD001"]}
    other_leg = flight(pnr="OTHER1", dep="IAH", arr="DCA", number="UA1540",
                       departure="2025-02-18T07:30:00Z", arrival="2025-02-18T11:28:00Z")
    for _ in range(2):
        result = apply(db, user, [incoming, other_leg], received="2025-01-03T00:45:01Z")
        assert result.review_reason == "legacy_flight_identity_conflict"
        assert result.build.held_unknown == 1 and result.status == MessageStatus.REVIEW_REQUIRED
        assert db.query(Segment).count() == 2
        db.refresh(old)
        assert (old.id, old.trip_id, old.dep_time, old.arr_time, old.pnr, old.meta_json) == before
        assert not old.meta_json.get("pnr_aliases")
        assert db.query(Segment).filter_by(flight_number="UA1540").count() == 1
    assert db.query(BookingObservation).count() == 2
    # Later cancellation of the different booking cannot be projected as an
    # alias onto the retained original leg merely because both refs were listed.
    assert "NEW001" not in (old.meta_json.get("pnr_aliases") or [])


@pytest.mark.parametrize("decision", ["hold", "canceled", "other"])
def test_manual_decision_prevents_legacy_normalization(account, decision):
    db, user = account
    incoming = flight()
    old = seed(db, user, incoming)
    original = (old.id, old.dep_time, old.arr_time)
    record_user_decision(db, user.id, incoming, ownership="other" if decision == "other" else "self",
                         status="active" if decision == "other" else decision)
    db.commit()
    # Explicit 'other' removes the active legacy row when the new observation
    # is reconciled; repeated self receipts must respect that user decision.
    before = db.query(Segment).count()
    apply(db, user, [incoming])
    assert db.query(Segment).count() == (0 if decision == "other" else before)
    apply(db, user, [incoming])
    assert db.query(Segment).count() == (0 if decision == "other" else before)
    if decision != "other":
        row = db.query(Segment).one()
        assert (row.id, row.dep_time, row.arr_time) == original


def test_cancellation_cannot_be_bypassed_by_utc_day_rollover(account):
    db, user = account
    incoming = flight()
    record_cancellation(db, user.id, incoming.pnr, source_message_id="cancel",
                        source_event_at=dt("2025-01-03T12:00:00Z"), flights=[incoming])
    db.commit()
    result = apply(db, user, [incoming])
    assert result.build.blocked_cancellation == 1 and db.query(Segment).count() == 0


@pytest.mark.parametrize("protection", ["hold", "canceled", "other", "cancellation_ledger"])
@pytest.mark.parametrize("already_normalized", [False, True])
@pytest.mark.parametrize("linked", [False, True])
def test_source_alias_never_bypasses_protection_on_legacy_primary(account, protection, already_normalized, linked):
    db, user = account
    incoming = flight(pnr="NEW001")
    incoming.pnr_aliases = ["OLD001"]
    old = seed(db, user, incoming, pnr="OLD001")
    record_flight_observations(db, user.id, [incoming], source_message_id="original-message",
                              source_event_at=dt("2025-01-02T12:00:00Z"))
    observation = db.query(BookingObservation).one()
    if linked:
        old.meta_json = {**old.meta_json, "observation_ids": [observation.id],
                         "source_message_ids": ["original-message"]}
    if already_normalized:
        old.dep_time, old.arr_time = incoming.dep_time, incoming.arr_time
        old.meta_json = {**old.meta_json, "time_provenance": incoming.time_provenance}
    protected = deepcopy(incoming)
    protected.pnr, protected.pnr_aliases = "OLD001", []
    if protection == "cancellation_ledger":
        record_cancellation(db, user.id, "OLD001", source_message_id="cancellation",
                            source_event_at=dt("2025-01-03T12:00:00Z"), flights=[protected])
    else:
        record_user_decision(db, user.id, protected,
                            ownership="other" if protection == "other" else "self",
                            status="active" if protection == "other" else protection)
    db.commit()
    original = (old.id, old.trip_id, old.dep_time, old.arr_time, old.pnr, deepcopy(old.meta_json))
    decisions = {row.id: deepcopy(row.facts) for row in db.query(BookingObservation)}
    for _ in range(2):
        result = apply(db, user, [incoming])
        assert result.build.updated == result.build.inserted == 0
        assert result.build.held_unknown == 1
        assert result.review_reason == "legacy_booking_protected"
        assert result.status == MessageStatus.REVIEW_REQUIRED
        row = db.query(Segment).one()
        assert (row.id, row.trip_id, row.dep_time, row.arr_time, row.pnr, row.meta_json) == original
        assert not row.meta_json.get("pnr_aliases")
        assert all(db.get(BookingObservation, key).facts == facts for key, facts in decisions.items())


@pytest.mark.parametrize("protection", ["hold", "canceled", "other", "cancellation_ledger"])
@pytest.mark.parametrize("same_booking", [False, True])
def test_changed_route_cannot_overwrite_negative_decision_on_saved_leg(account, protection, same_booking):
    db, user = account
    previous = flight(pnr="OLD001")
    old = seed(db, user, previous)
    old.dep_time, old.arr_time = previous.dep_time, previous.arr_time
    old.meta_json = {**old.meta_json, "time_provenance": previous.time_provenance}
    trip = db.get(Trip, old.trip_id)
    trip.start_ts, trip.end_ts = old.dep_time, old.arr_time
    incoming = flight(pnr="OLD001" if same_booking else "NEW001", arr="DFW")
    if not same_booking:
        incoming.pnr_aliases = ["OLD001"]
    assert incoming.dep_time == previous.dep_time and incoming.arr_time == previous.arr_time
    if protection == "cancellation_ledger":
        record_cancellation(db, user.id, "OLD001", source_message_id="cancellation",
                            source_event_at=dt("2025-01-03T12:00:00Z"), flights=[previous])
    else:
        record_user_decision(db, user.id, previous,
                            ownership="other" if protection == "other" else "self",
                            status="active" if protection == "other" else protection)
    db.commit()
    original = {column.name: deepcopy(getattr(old, column.name)) for column in Segment.__table__.columns}
    decisions = {row.id: deepcopy(row.facts) for row in db.query(BookingObservation)}
    for _ in range(2):
        result = apply(db, user, [incoming])
        assert result.build.updated == result.build.inserted == 0
        assert result.build.held_unknown == 1 and result.review_reason == "legacy_booking_protected"
        row = db.query(Segment).one()
        assert {column.name: getattr(row, column.name) for column in Segment.__table__.columns} == original
        assert all(db.get(BookingObservation, key).facts == facts for key, facts in decisions.items())


@pytest.mark.parametrize("same_booking", [False, True])
def test_saved_scope_cancellation_uses_incoming_confirmation_time(account, same_booking):
    db, user = account
    previous = flight(pnr="OLD001")
    old = seed(db, user, previous)
    old.dep_time, old.arr_time = previous.dep_time, previous.arr_time
    old.meta_json = {**old.meta_json, "time_provenance": previous.time_provenance}
    trip = db.get(Trip, old.trip_id)
    trip.start_ts, trip.end_ts = old.dep_time, old.arr_time
    record_cancellation(db, user.id, "OLD001", source_message_id="cancellation",
                        source_event_at=dt("2025-01-03T12:00:00Z"), flights=[previous])
    db.commit()
    incoming = flight(pnr="OLD001" if same_booking else "NEW001", arr="DFW")
    if not same_booking:
        incoming.pnr_aliases = ["OLD001"]
    result = apply(db, user, [incoming], received="2025-01-04T12:00:00Z")
    assert result.build.updated == 1 and result.build.held_unknown == 0
    assert db.query(Segment).one().id == old.id and old.arr_airport == "DFW"


def test_repeated_flight_next_local_day_does_not_overwrite_neighbor(account):
    db, user = account
    incoming = flight()
    same = seed(db, user, incoming)
    next_day = flight(departure="2025-02-24T20:49:00Z", arrival="2025-02-24T22:10:00Z")
    neighbor = seed(db, user, next_day, note="next-day")
    original = (neighbor.id, neighbor.dep_time, neighbor.arr_time, deepcopy(neighbor.meta_json))
    result = apply(db, user, [incoming])
    assert result.build.inserted == 0 and db.query(Segment).count() == 2
    db.refresh(neighbor)
    assert (neighbor.id, neighbor.dep_time, neighbor.arr_time, neighbor.meta_json) == original
    assert db.get(Segment, same.id).dep_time == dt("2025-02-24T01:49:00Z").replace(tzinfo=None)


def test_duplicate_legacy_candidates_hold_instead_of_choosing_arbitrary_row(account):
    db, user = account
    incoming = flight()
    first, second = seed(db, user, incoming), seed(db, user, incoming)
    result = apply(db, user, [incoming])
    assert result.review_reason == "legacy_flight_identity_conflict"
    assert result.build.inserted == result.build.updated == 0
    assert {row.id for row in db.query(Segment)} == {first.id, second.id}


@pytest.mark.parametrize("field", ["recovery_observation_ids", "reconciles_observation_ids"])
def test_legacy_clock_match_does_not_bypass_recovery_link_validation(account, field):
    db, user = account
    incoming = flight()
    old = seed(db, user, incoming)
    original = (old.id, old.dep_time, old.arr_time, deepcopy(old.meta_json))
    setattr(incoming, field, [999999])
    with pytest.raises(ValueError, match="not linked"):
        apply(db, user, [incoming])
    db.rollback()
    row = db.query(Segment).one()
    assert (row.id, row.dep_time, row.arr_time, row.meta_json) == original
    assert db.query(BookingObservation).count() == 0


def test_other_accounts_and_unnamed_receipts_do_not_gain_legacy_matching(account):
    db, user = account
    other = User(name="Other Person", email="other@example.test")
    db.add(other); db.commit()
    incoming = flight()
    old = seed(db, other, incoming)
    unknown = deepcopy(incoming); unknown.ownership = "unknown"; unknown.passenger_evidence = []
    result = apply(db, user, [unknown])
    assert result.build.held_unknown == 1 and db.query(Segment).count() == 1
    result = apply(db, user, [incoming], source="named")
    assert result.build.inserted == 1 and db.query(Segment).count() == 2
    assert db.get(Segment, old.id).trip_id == old.trip_id
