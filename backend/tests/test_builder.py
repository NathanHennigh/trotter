from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, Segment, Trip, User
from app.services.builder import (
    build_segments_and_trips,
    build_segments_and_trips_detailed,
    cancel_segments_for_pnr,
    infer_home_airport_for_segments,
    resolve_booking_relationships,
    trip_destination_airport,
    trip_route_label_for_segments,
)


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)


def _flight(
    dep: str,
    arr: str,
    dep_time: str,
    arr_time: str,
    airline: str,
    number: str,
    pnr: str,
    *,
    source_received_at: str | None = None,
    pnr_aliases: list[str] | None = None,
    nonstop: bool = False,
):
    return SimpleNamespace(
        dep_airport=dep,
        arr_airport=arr,
        dep_time=_dt(dep_time),
        arr_time=_dt(arr_time),
        airline=airline,
        flight_number=number,
        pnr=pnr,
        source="test",
        source_received_at=_dt(source_received_at) if source_received_at else None,
        pnr_aliases=pnr_aliases or [],
        nonstop=nonstop,
    )


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    user = User(email="nathan@example.com")
    db.add(user)
    db.commit()
    return db, user


def test_rebuild_groups_return_with_different_booking_code():
    db, user = _session()

    build_segments_and_trips(
        db,
        user.id,
        [
            _flight("DFW", "FLL", "2023-03-03T14:01:00", "2023-03-03T17:46:00", "NK", "NK360", "UF8K9P"),
            _flight("FLL", "MGA", "2023-03-03T23:40:00", "2023-03-04T01:22:00", "NK", "NK435", "UF8K9P"),
        ],
    )
    build_segments_and_trips(
        db,
        user.id,
        [
            _flight("MGA", "MEX", "2023-03-12T07:00:00", "2023-03-12T09:42:00", "AM", "AM651", "WNAUQY"),
            _flight("MEX", "DFW", "2023-03-13T10:00:00", "2023-03-13T13:46:00", "AM", "AM2682", "WNAUQY"),
        ],
    )
    db.commit()

    trips = db.query(Trip).all()
    assert len(trips) == 1
    assert trips[0].title == "Nicaragua"
    assert [(s.dep_airport, s.arr_airport) for s in sorted(trips[0].segments, key=lambda s: s.dep_time)] == [
        ("DFW", "FLL"),
        ("FLL", "MGA"),
        ("MGA", "MEX"),
        ("MEX", "DFW"),
    ]


def test_multileg_coterminal_round_trip_classifies_the_stay_not_the_layover():
    db, user = _session()

    build_segments_and_trips(
        db,
        user.id,
        [
            _flight("DAL", "LAS", "2026-08-16T10:00:00", "2026-08-16T11:00:00", "WN", "WN184", "OUT123"),
            _flight("LAS", "KOA", "2026-08-16T13:00:00", "2026-08-16T17:00:00", "WN", "WN4738", "OUT123"),
        ],
    )
    build_segments_and_trips(
        db,
        user.id,
        [
            _flight("KOA", "SEA", "2026-08-22T22:25:00", "2026-08-23T07:20:00", "AS", "AS259", "BACK26"),
            _flight("SEA", "DFW", "2026-08-23T08:40:00", "2026-08-23T14:46:00", "AS", "AS340", "BACK26"),
        ],
    )
    db.commit()

    [trip] = db.query(Trip).all()
    segments = sorted(trip.segments, key=lambda segment: segment.dep_time)

    assert infer_home_airport_for_segments(segments) == "DAL"
    assert trip.title == "Kailua Kona"
    assert trip_destination_airport(segments, home_airport="DAL") == "KOA"
    assert trip_route_label_for_segments(segments, home_airport="DAL") == "DAL -> KOA"

    from app.routers.trips import _trip_out

    response = _trip_out(trip, home_airport="DAL")
    assert response.destination_airport == "KOA"
    assert response.route_label == "DAL -> KOA"


def test_inbound_only_trip_keeps_its_actual_route_and_departure_destination():
    db, user = _session()
    build_segments_and_trips(
        db,
        user.id,
        [_flight("BNA", "DFW", "2026-04-04T18:00:00", "2026-04-04T20:15:00", "AA", "AA100", "HOME26")],
    )
    db.commit()

    [trip] = db.query(Trip).all()
    assert trip_destination_airport(trip.segments, home_airport="DAL") == "BNA"
    assert trip_route_label_for_segments(trip.segments, home_airport="DAL") == "BNA -> DFW"


def test_rebuild_splits_new_home_departure_after_prior_trip_finished():
    db, user = _session()

    build_segments_and_trips(
        db,
        user.id,
        [
            _flight("MCO", "ATL", "2025-02-23T17:01:00", "2025-02-23T18:40:00", "NK", "NK1651", "LI2HXS"),
            _flight("ATL", "IAH", "2025-02-23T20:49:00", "2025-02-23T22:49:00", "NK", "NK512", "LI2HXS"),
            _flight("IAH", "TPE", "2025-04-26T01:00:00", "2025-04-26T15:00:00", "BR", "BR51", "3EZ3KP"),
            _flight("TPE", "IAH", "2025-05-09T21:20:00", "2025-05-10T07:20:00", "BR", "BR52", "3EZ3KP"),
        ],
    )
    db.commit()

    trips = db.query(Trip).order_by(Trip.start_ts).all()
    assert [trip.title for trip in trips] == ["Atlanta", "Taiwan"]


def test_trip_title_uses_country_for_multi_city_foreign_trip():
    db, user = _session()

    build_segments_and_trips(
        db,
        user.id,
        [
            _flight("IAH", "TPE", "2025-04-26T01:00:00", "2025-04-26T15:00:00", "BR", "BR51", "3EZ3KP"),
            _flight("TPE", "MNL", "2025-04-26T16:30:00", "2025-04-26T18:45:00", "BR", "BR277", "3EZ3KP"),
            _flight("MNL", "MPH", "2025-04-28T09:10:00", "2025-04-28T10:20:00", "PR", "PR2041", "3EZ3KP"),
            _flight("KLO", "MNL", "2025-05-03T11:15:00", "2025-05-03T12:30:00", "PR", "PR2042", "3EZ3KP"),
            _flight("MNL", "TPE", "2025-05-09T18:20:00", "2025-05-09T20:20:00", "BR", "BR278", "3EZ3KP"),
            _flight("TPE", "IAH", "2025-05-09T21:20:00", "2025-05-10T07:20:00", "BR", "BR52", "3EZ3KP"),
        ],
    )
    db.commit()

    [trip] = db.query(Trip).all()
    assert trip.title == "Philippines"


def test_trip_title_uses_multiple_countries_for_multi_country_trip():
    db, user = _session()

    build_segments_and_trips(
        db,
        user.id,
        [
            _flight("LAX", "MAD", "2022-05-30T10:00:00", "2022-05-31T06:00:00", "IB", "IB6170", "MAES22"),
            _flight("MAD", "RAK", "2022-05-31T08:00:00", "2022-05-31T10:00:00", "IB", "IB3340", "MAES22"),
            _flight("TNG", "MAD", "2022-06-06T11:00:00", "2022-06-06T13:00:00", "IB", "IB8797", "MAES22"),
            _flight("MAD", "PMI", "2022-06-06T15:00:00", "2022-06-06T16:15:00", "IB", "IB3924", "MAES22"),
            _flight("MAD", "JFK", "2022-06-11T12:00:00", "2022-06-11T15:00:00", "IB", "IB6251", "MAES22"),
        ],
    )
    db.commit()

    [trip] = db.query(Trip).all()
    assert trip.title == "Morocco and Spain"


def test_trip_title_uses_city_for_nearby_international_trip():
    db, user = _session()

    build_segments_and_trips(
        db,
        user.id,
        [
            _flight("IAH", "TQO", "2025-08-16T08:00:00", "2025-08-16T10:15:00", "UA", "UA100", "TULUM1"),
            _flight("TQO", "IAH", "2025-08-23T11:00:00", "2025-08-23T13:20:00", "UA", "UA101", "TULUM1"),
        ],
    )
    db.commit()

    [trip] = db.query(Trip).all()
    assert trip.title == "Tulum"


def test_one_way_connection_uses_final_destination_not_connection_city():
    db, user = _session()

    build_segments_and_trips(
        db,
        user.id,
        [
            _flight("JFK", "CMN", "2016-08-11T20:30:00", "2016-08-12T08:20:00", "AT", "AT201", "YSCMJG"),
            _flight("CMN", "NBO", "2016-08-12T16:15:00", "2016-08-13T02:00:00", "AT", "AT263", "YSCMJG"),
        ],
    )
    db.commit()

    [trip] = db.query(Trip).all()
    assert trip.title == "Kenya"


def test_incomplete_return_trip_title_uses_non_home_endpoint():
    db, user = _session()

    build_segments_and_trips(
        db,
        user.id,
        [
            _flight("IAH", "ORD", "2025-06-18T18:28:00", "2025-06-18T21:15:00", "UA", "UA100", "CHI1"),
            _flight("ORD", "IAH", "2025-06-22T20:30:00", "2025-06-22T23:20:00", "UA", "UA101", "CHI1"),
            _flight("BNA", "IAH", "2025-07-01T20:25:00", "2025-07-01T22:46:00", "UA", "UA2311", "BNA1"),
        ],
    )
    db.commit()

    trips = db.query(Trip).order_by(Trip.start_ts).all()
    assert [trip.title for trip in trips] == ["Chicago", "Nashville"]


def test_trip_title_rules_are_relative_to_non_us_home_country():
    db, user = _session()

    build_segments_and_trips(
        db,
        user.id,
        [
            _flight("CDG", "BCN", "2025-03-01T08:00:00", "2025-03-01T09:45:00", "AF", "AF1448", "EU1"),
            _flight("BCN", "CDG", "2025-03-04T18:00:00", "2025-03-04T19:50:00", "AF", "AF1449", "EU1"),
            _flight("CDG", "NBO", "2025-04-01T10:00:00", "2025-04-01T20:30:00", "KQ", "KQ115", "KE1"),
            _flight("NBO", "CDG", "2025-04-10T23:00:00", "2025-04-11T07:30:00", "KQ", "KQ112", "KE1"),
        ],
    )
    db.commit()

    trips = db.query(Trip).order_by(Trip.start_ts).all()
    assert [trip.title for trip in trips] == ["Barcelona", "Kenya"]


def test_newer_same_pnr_flight_number_supersedes_prior_segment_details():
    db, user = _session()

    build_segments_and_trips(
        db,
        user.id,
        [
            _flight(
                "EWR",
                "DFW",
                "2025-01-10T10:00:00",
                "2025-01-10T13:00:00",
                "UA",
                "UA100",
                "ABC123",
                source_received_at="2025-01-01T12:00:00",
            )
        ],
    )
    build_segments_and_trips(
        db,
        user.id,
        [
            _flight(
                "EWR",
                "ORD",
                "2025-01-10T14:00:00",
                "2025-01-10T16:00:00",
                "UA",
                "UA100",
                "ABC123",
                source_received_at="2025-01-02T12:00:00",
            )
        ],
    )
    db.commit()

    segments = db.query(Segment).all()
    assert len(segments) == 1
    assert segments[0].dep_airport == "EWR"
    assert segments[0].arr_airport == "ORD"
    assert segments[0].dep_time == datetime.fromisoformat("2025-01-10T14:00:00")
    assert segments[0].meta_json["source_received_at"].startswith("2025-01-02T12:00:00")


def test_same_pnr_route_match_handles_timezone_aware_db_segment_times():
    db, user = _session()

    build_segments_and_trips(
        db,
        user.id,
        [
            _flight(
                "IAH",
                "DFW",
                "2025-01-10T10:00:00",
                "2025-01-10T11:20:00",
                "AA",
                "",
                "TZPNR1",
                source_received_at="2025-01-01T12:00:00",
            )
        ],
    )
    [segment] = db.query(Segment).all()
    segment.dep_time = segment.dep_time.replace(tzinfo=timezone.utc)
    segment.arr_time = segment.arr_time.replace(tzinfo=timezone.utc)

    result = build_segments_and_trips_detailed(
        db,
        user.id,
        [
            _flight(
                "IAH",
                "DFW",
                "2025-01-10T10:05:00",
                "2025-01-10T11:25:00",
                "AA",
                "",
                "TZPNR1",
                source_received_at="2025-01-02T12:00:00",
            )
        ],
    )

    assert result.updated == 1


def test_newer_direct_change_replaces_older_same_pnr_layover_chain():
    db, user = _session()

    build_segments_and_trips(
        db,
        user.id,
        [
            _flight("DAL", "BNA", "2021-12-18T12:45:00", "2021-12-18T14:25:00", "WN", "WN2772", "2F3SW8", source_received_at="2021-11-29T18:49:35"),
            _flight("BNA", "LGA", "2021-12-18T17:00:00", "2021-12-18T20:10:00", "WN", "WN3054", "2F3SW8", source_received_at="2021-11-29T18:49:35"),
            _flight("LGA", "DAL", "2022-01-07T09:35:00", "2022-01-07T15:15:00", "WN", "WN284", "2F3SW8", source_received_at="2021-11-29T18:49:35"),
        ],
    )
    build_segments_and_trips(
        db,
        user.id,
        [
            _flight("DAL", "LGA", "2021-12-18T13:05:00", "2021-12-18T17:20:00", "WN", "WN3111", "2F3SW8", source_received_at="2021-12-18T17:34:26"),
        ],
    )

    segments = db.query(Segment).order_by(Segment.dep_time).all()
    assert [(s.flight_number, s.dep_airport, s.arr_airport) for s in segments] == [
        ("WN3111", "DAL", "LGA"),
        ("WN284", "LGA", "DAL"),
    ]
    assert any(
        item.get("type") == "older_layover_leg_removed"
        for item in (segments[0].meta_json or {}).get("booking_relationships", [])
    )


def test_specific_operating_layover_legs_replace_summary_segment():
    db, user = _session()

    build_segments_and_trips(
        db,
        user.id,
        [
            _flight("TNG", "PMI", "2022-06-07T12:25:00", "2022-06-07T17:10:00", "IB", "IB1", "MEQQ0", source_received_at="2022-04-21T23:09:49"),
        ],
    )
    build_segments_and_trips(
        db,
        user.id,
        [
            _flight("TNG", "MAD", "2022-06-07T12:25:00", "2022-06-07T14:50:00", "IB", "IB8797", "MEQQ0", source_received_at="2022-06-06T21:15:43"),
            _flight("MAD", "PMI", "2022-06-07T15:45:00", "2022-06-07T17:10:00", "IB", "IB3912", "MEQQ0", source_received_at="2022-06-06T21:15:43"),
        ],
    )

    segments = db.query(Segment).order_by(Segment.dep_time).all()
    assert [(s.flight_number, s.dep_airport, s.arr_airport) for s in segments] == [
        ("IB8797", "TNG", "MAD"),
        ("IB3912", "MAD", "PMI"),
    ]
    assert any(
        item.get("type") == "covered_through_segment_removed"
        for item in (segments[0].meta_json or {}).get("booking_relationships", [])
    )


def test_no_pnr_same_route_duplicate_loses_to_richer_segment():
    db, user = _session()

    build_segments_and_trips(
        db,
        user.id,
        [
            _flight("FRA", "EWR", "2021-01-10T10:20:00", "2021-01-10T13:05:00", "UA", "UA961", "OB5PJV", source_received_at="2020-12-09T13:05:04"),
            _flight("EWR", "DFW", "2021-01-10T15:29:00", "2021-01-10T18:43:00", "UA", "UA3412", None, source_received_at="2020-12-09T13:05:04"),
        ],
    )
    build_segments_and_trips(
        db,
        user.id,
        [
            _flight("EWR", "DFW", "2021-01-10T16:08:00", "2021-01-10T19:12:00", "UA", "UA570", "OB5PJV", source_received_at="2021-01-09T10:12:09"),
        ],
    )

    segments = db.query(Segment).order_by(Segment.dep_time).all()
    assert [(s.flight_number, s.pnr, s.dep_airport, s.arr_airport) for s in segments] == [
        ("UA961", "OB5PJV", "FRA", "EWR"),
        ("UA570", "OB5PJV", "EWR", "DFW"),
    ]
    assert any(
        item.get("type") == "no_pnr_same_route_segment_removed"
        for item in (segments[1].meta_json or {}).get("booking_relationships", [])
    )


def test_rebooked_same_route_segment_replaces_older_linked_booking():
    db, user = _session()

    build_segments_and_trips(
        db,
        user.id,
        [
            _flight("IAH", "DCA", "2025-03-24T07:30:00", "2025-03-24T11:28:00", "UA", "UA546", "DZYJCJ", source_received_at="2025-01-03T01:04:02"),
            _flight("DCA", "IAH", "2025-03-27T12:42:00", "2025-03-27T15:25:00", "UA", "UA1808", "DZYJCJ", source_received_at="2025-01-03T01:04:02"),
        ],
    )
    build_segments_and_trips(
        db,
        user.id,
        [
            _flight("IAH", "DCA", "2025-03-24T07:30:00", "2025-03-24T11:28:00", "UA", "UA546", "DZ9KZ1", source_received_at="2025-01-04T01:14:30", pnr_aliases=["DZYJCJ"]),
            _flight("DCA", "IAH", "2025-03-27T14:46:00", "2025-03-27T17:25:00", "UA", "UA1274", "DZ9KZ1", source_received_at="2025-01-04T01:14:30"),
        ],
    )

    segments = db.query(Segment).order_by(Segment.dep_time).all()
    assert [(s.flight_number, s.dep_airport, s.arr_airport) for s in segments] == [
        ("UA546", "IAH", "DCA"),
        ("UA1274", "DCA", "IAH"),
    ]
    assert {segments[0].pnr, *((segments[0].meta_json or {}).get("pnr_aliases") or [])} == {"DZYJCJ", "DZ9KZ1"}
    assert [(s.pnr, s.flight_number, s.dep_airport, s.arr_airport) for s in segments[1:]] == [
        ("DZ9KZ1", "UA1274", "DCA", "IAH"),
    ]
    assert "DZYJCJ" in ((segments[1].meta_json or {}).get("pnr_aliases") or [])
    assert any(
        item.get("type") == "rebooked_same_route_segment_removed"
        for item in (segments[1].meta_json or {}).get("booking_relationships", [])
    )


def test_rebuild_user_trips_handles_mixed_naive_and_aware_segment_times():
    db, user = _session()

    build_segments_and_trips(
        db,
        user.id,
        [
            _flight("IAH", "DCA", "2025-03-24T07:30:00", "2025-03-24T11:28:00", "UA", "UA546", "MIXED1"),
        ],
    )
    [existing] = db.query(Segment).all()
    existing.dep_time = existing.dep_time.replace(tzinfo=None)
    existing.arr_time = existing.arr_time.replace(tzinfo=None)

    result = build_segments_and_trips_detailed(
        db,
        user.id,
        [
            _flight("DCA", "MCO", "2025-03-24T13:30:00", "2025-03-24T16:00:00", "UA", "UA1200", "MIXED1"),
        ],
    )

    assert result.inserted == 1
    assert db.query(Segment).count() == 2
    assert db.query(Trip).count() == 1


def test_newer_partial_stopover_leg_does_not_replace_richer_through_flight():
    db, user = _session()

    build_segments_and_trips(
        db,
        user.id,
        [
            _flight(
                "EWR",
                "ADD",
                "2022-12-16T21:15:00",
                "2022-12-17T21:25:00",
                "ET",
                "ET509",
                "UTIKKU",
                source_received_at="2022-12-01T12:00:00",
            )
        ],
    )
    build_segments_and_trips(
        db,
        user.id,
        [
            _flight(
                "LFW",
                "ADD",
                "2022-12-17T13:55:00",
                "2022-12-17T22:20:00",
                "ET",
                "ET509",
                "UTIKKU",
                source_received_at="2022-12-17T06:23:13",
            )
        ],
    )
    db.commit()

    [segment] = db.query(Segment).all()
    assert (segment.dep_airport, segment.arr_airport) == ("EWR", "ADD")
    assert segment.dep_time == datetime.fromisoformat("2022-12-16T21:15:00")
    assert segment.arr_time == datetime.fromisoformat("2022-12-17T21:25:00")


def test_same_trip_flight_key_collision_keeps_itinerary_continuity():
    db, user = _session()

    build_segments_and_trips(
        db,
        user.id,
        [
            _flight("LFW", "ADD", "2022-12-17T13:55:00", "2022-12-17T22:20:00", "ET", "ET509", "UTIKKU"),
            _flight("ADD", "HGA", "2022-12-18T09:20:00", "2022-12-18T10:50:00", "ET", "ET372", "UTIKKU"),
            _flight("HGA", "ADD", "2022-12-27T17:40:00", "2022-12-27T19:00:00", "ET", "ET375", "UTIKKU"),
            _flight("ADD", "IAD", "2022-12-27T22:50:00", "2022-12-28T08:15:00", "ET", "ET500", "UTIKKU"),
            _flight("IAD", "EWR", "2022-12-28T12:30:00", "2022-12-28T13:50:00", "UA", "UA1911", "UTIKKU"),
        ],
    )
    build_segments_and_trips(
        db,
        user.id,
        [
            _flight("ADD", "DUB", "2022-12-27T22:50:00", "2022-12-28T04:20:00", "ET", "ET500", "UTIKKU"),
        ],
    )
    db.commit()

    routes = {(segment.flight_number, segment.dep_airport, segment.arr_airport) for segment in db.query(Segment).all()}
    assert ("ET500", "ADD", "IAD") in routes
    assert ("ET500", "ADD", "DUB") not in routes
    kept = db.query(Segment).filter(Segment.flight_number == "ET500").one()
    relationships = (kept.meta_json or {}).get("booking_relationships", [])
    assert any(
        item.get("type") == "same_trip_flight_key_collision_removed"
        and item.get("removed_route") == "ADD-DUB"
        for item in relationships
    )


def test_older_same_pnr_flight_number_does_not_overwrite_newer_segment():
    db, user = _session()

    build_segments_and_trips(
        db,
        user.id,
        [
            _flight(
                "EWR",
                "ORD",
                "2025-01-10T14:00:00",
                "2025-01-10T16:00:00",
                "UA",
                "UA100",
                "ABC123",
                source_received_at="2025-01-02T12:00:00",
            )
        ],
    )
    build_segments_and_trips(
        db,
        user.id,
        [
            _flight(
                "EWR",
                "DFW",
                "2025-01-10T10:00:00",
                "2025-01-10T13:00:00",
                "UA",
                "UA100",
                "ABC123",
                source_received_at="2025-01-01T12:00:00",
            )
        ],
    )
    db.commit()

    segments = db.query(Segment).all()
    assert len(segments) == 1
    assert segments[0].arr_airport == "ORD"
    assert segments[0].dep_time == datetime.fromisoformat("2025-01-10T14:00:00")


def test_cancel_segments_for_pnr_removes_canceled_booking():
    db, user = _session()

    build_segments_and_trips(
        db,
        user.id,
        [
            _flight("EWR", "DFW", "2025-01-10T10:00:00", "2025-01-10T13:00:00", "UA", "UA100", "ABC123"),
            _flight("DFW", "EWR", "2025-01-15T10:00:00", "2025-01-15T14:00:00", "UA", "UA101", "ABC123"),
        ],
    )

    assert cancel_segments_for_pnr(db, user.id, "ABC123") == 2
    db.commit()

    assert db.query(Segment).count() == 0


def test_flight_number_normalization_dedupes_leading_zero_variants():
    db, user = _session()

    build_segments_and_trips(
        db,
        user.id,
        [_flight("IAH", "TPE", "2025-04-26T01:00:00", "2025-04-26T15:00:00", "BR", "BR051", "3EZ3KP")],
    )
    result = build_segments_and_trips_detailed(
        db,
        user.id,
        [_flight("IAH", "TPE", "2025-04-26T01:00:00", "2025-04-26T15:00:00", "BR", "BR51", "3EZ3KP")],
    )
    db.commit()

    segments = db.query(Segment).all()
    assert len(segments) == 1
    assert segments[0].flight_number == "BR51"
    assert result.updated == 1


def test_numeric_flight_number_dedupes_against_airline_prefixed_copy():
    db, user = _session()

    build_segments_and_trips(
        db,
        user.id,
        [_flight("MCO", "ATL", "2025-02-23T17:01:00", "2025-02-23T18:49:00", "", "1651", "LI2HXS")],
    )
    build_segments_and_trips(
        db,
        user.id,
        [_flight("MCO", "ATL", "2025-02-23T17:01:00", "2025-02-23T18:49:00", "NK", "NK1651", "WITHIN")],
    )
    db.commit()

    segments = db.query(Segment).all()
    assert len(segments) == 1
    assert segments[0].airline == "NK"
    assert segments[0].flight_number == "NK1651"
    assert segments[0].pnr == "LI2HXS"


def test_generic_words_are_not_used_as_pnr_grouping_keys():
    db, user = _session()

    build_segments_and_trips(
        db,
        user.id,
        [
            _flight("DFW", "ORD", "2020-12-11T14:20:00", "2020-12-11T16:40:00", "UA", "UA3462", "PRINT"),
            _flight("ORD", "FRA", "2020-12-20T18:00:00", "2020-12-21T09:00:00", "UA", "UA907", "PRINT"),
        ],
    )
    db.commit()

    segments = db.query(Segment).order_by(Segment.dep_time).all()
    assert [segment.pnr for segment in segments] == [None, None]


def test_zero_duration_placeholder_is_skipped_and_later_full_segment_imports():
    db, user = _session()

    placeholder = build_segments_and_trips_detailed(
        db,
        user.id,
        [_flight("ORD", "IAH", "2025-06-22T00:00:00", "2025-06-22T00:00:00", "UA", "UA100", "CHI1")],
    )
    full = build_segments_and_trips_detailed(
        db,
        user.id,
        [_flight("ORD", "IAH", "2025-06-22T20:30:00", "2025-06-22T23:20:00", "UA", "UA100", "CHI1")],
    )
    db.commit()

    segments = db.query(Segment).all()
    assert placeholder.skipped == 1
    assert full.inserted == 1
    assert len(segments) == 1
    assert segments[0].arr_time > segments[0].dep_time


def test_cancellation_then_newer_same_pnr_confirmation_recreates_booking():
    db, user = _session()

    build_segments_and_trips(
        db,
        user.id,
        [_flight("IAH", "DCA", "2025-03-01T09:00:00", "2025-03-01T13:00:00", "UA", "UA300", "ABC123")],
    )
    assert cancel_segments_for_pnr(db, user.id, "ABC123") == 1
    build_segments_and_trips(
        db,
        user.id,
        [_flight("IAH", "DCA", "2025-03-02T09:00:00", "2025-03-02T13:00:00", "UA", "UA301", "ABC123")],
    )
    db.commit()

    segments = db.query(Segment).all()
    assert len(segments) == 1
    assert segments[0].flight_number == "UA301"
    assert segments[0].dep_time == datetime.fromisoformat("2025-03-02T09:00:00")


def test_older_cancellation_does_not_remove_newer_same_pnr_confirmation():
    db, user = _session()

    build_segments_and_trips(
        db,
        user.id,
        [
            _flight(
                "IAH",
                "DCA",
                "2025-03-02T09:00:00",
                "2025-03-02T13:00:00",
                "UA",
                "UA301",
                "ABC123",
                source_received_at="2025-02-02T12:00:00",
            )
        ],
    )
    removed = cancel_segments_for_pnr(db, user.id, "ABC123", received_at=_dt("2025-02-01T12:00:00"))
    db.commit()

    assert removed == 0
    assert db.query(Segment).count() == 1


def test_long_away_from_home_round_trip_stays_one_trip():
    db, user = _session()

    build_segments_and_trips(
        db,
        user.id,
        [
            _flight("IAH", "FRA", "2020-12-01T16:00:00", "2020-12-02T07:00:00", "LH", "LH441", "NAIROBI"),
            _flight("FRA", "NBO", "2020-12-02T10:00:00", "2020-12-02T20:00:00", "LH", "LH590", "NAIROBI"),
            _flight("NBO", "FRA", "2020-12-28T23:00:00", "2020-12-29T06:00:00", "LH", "LH591", "NAIROBI"),
            _flight("FRA", "IAH", "2020-12-29T10:00:00", "2020-12-29T15:00:00", "LH", "LH440", "NAIROBI"),
        ],
    )
    db.commit()

    trips = db.query(Trip).all()
    assert len(trips) == 1
    assert [segment.dep_airport for segment in sorted(trips[0].segments, key=lambda item: item.dep_time)] == [
        "IAH",
        "FRA",
        "NBO",
        "FRA",
    ]


def test_overlapping_conflicting_same_pnr_segments_split_into_separate_trips():
    db, user = _session()

    build_segments_and_trips(
        db,
        user.id,
        [
            _flight("IAH", "DCA", "2025-03-01T09:00:00", "2025-03-01T13:00:00", "UA", "UA300", "ABC123"),
            _flight("IAH", "MCO", "2025-03-01T10:00:00", "2025-03-01T12:30:00", "UA", "UA400", "ABC123"),
        ],
    )
    db.commit()

    trips = db.query(Trip).order_by(Trip.start_ts).all()
    assert len(trips) == 2
    assert sorted(len(trip.segments) for trip in trips) == [1, 1]


def test_completed_home_trip_does_not_absorb_later_same_pnr_home_departure():
    db, user = _session()

    build_segments_and_trips(
        db,
        user.id,
        [
            _flight("IAH", "CLT", "2025-08-01T08:00:00", "2025-08-01T11:30:00", "AA", "AA100", "MULTI1"),
            _flight("CLT", "IAH", "2025-08-04T15:00:00", "2025-08-04T17:30:00", "AA", "AA101", "MULTI1"),
            _flight("IAH", "MIA", "2025-08-16T08:00:00", "2025-08-16T10:20:00", "AA", "AA200", "MULTI1"),
            _flight("MIA", "TQO", "2025-08-16T12:00:00", "2025-08-16T13:30:00", "AA", "AA201", "MULTI1"),
            _flight("TQO", "IAH", "2025-08-23T11:00:00", "2025-08-23T13:20:00", "AA", "AA202", "MULTI1"),
        ],
    )
    db.commit()

    trips = db.query(Trip).order_by(Trip.start_ts).all()
    assert len(trips) == 2
    assert [[(s.dep_airport, s.arr_airport) for s in sorted(t.segments, key=lambda s: s.dep_time)] for t in trips] == [
        [("IAH", "CLT"), ("CLT", "IAH")],
        [("IAH", "MIA"), ("MIA", "TQO"), ("TQO", "IAH")],
    ]


def test_unrelated_future_home_departure_does_not_join_completed_trip():
    db, user = _session()

    build_segments_and_trips(
        db,
        user.id,
        [
            _flight("IAH", "DCA", "2025-03-01T09:00:00", "2025-03-01T13:00:00", "UA", "UA300", "WASH1"),
            _flight("DCA", "IAH", "2025-03-05T09:00:00", "2025-03-05T13:00:00", "UA", "UA301", "WASH1"),
            _flight("IAH", "EWR", "2025-03-10T09:00:00", "2025-03-10T13:00:00", "UA", "UA400", "NYC1"),
            _flight("EWR", "IAH", "2025-03-14T09:00:00", "2025-03-14T13:00:00", "UA", "UA401", "NYC1"),
            _flight("IAH", "TPE", "2025-04-26T01:00:00", "2025-04-26T15:00:00", "BR", "BR51", "PHIL1"),
        ],
    )
    db.commit()

    trips = db.query(Trip).order_by(Trip.start_ts).all()
    assert len(trips) == 3
    assert [trip.title for trip in trips] == ["Washington", "Newark", "Taiwan"]


def test_numeric_duplicate_merges_details_from_prefixed_copy():
    db, user = _session()

    build_segments_and_trips(
        db,
        user.id,
        [_flight("ATL", "IAH", "2025-02-23T20:49:00", "2025-02-23T22:49:00", "", "512", "LI2HXS")],
    )
    build_segments_and_trips(
        db,
        user.id,
        [_flight("ATL", "IAH", "2025-02-23T20:49:00", "2025-02-23T22:49:00", "NK", "NK512", "")],
    )
    db.commit()

    [segment] = db.query(Segment).all()
    assert segment.airline == "NK"
    assert segment.flight_number == "NK512"
    assert segment.pnr == "LI2HXS"


def test_later_low_information_duplicate_merges_into_richer_existing_segment():
    db, user = _session()

    build_segments_and_trips(
        db,
        user.id,
        [_flight("ATL", "IAH", "2025-02-23T20:49:00", "2025-02-23T22:49:00", "NK", "NK512", "")],
    )
    build_segments_and_trips(
        db,
        user.id,
        [_flight("ATL", "IAH", "2025-02-23T20:49:00", "2025-02-23T22:49:00", "", "512", "LI2HXS")],
    )
    db.commit()

    [segment] = db.query(Segment).all()
    assert segment.airline == "NK"
    assert segment.flight_number == "NK512"
    assert segment.pnr == "LI2HXS"


def test_codeshare_style_carrier_prefixes_dedupe_by_underlying_flight_number():
    db, user = _session()

    build_segments_and_trips(
        db,
        user.id,
        [_flight("DCA", "MCO", "2025-02-21T15:00:00", "2025-02-21T17:40:00", "UA", "UA2023", "AHKPGY")],
    )
    build_segments_and_trips(
        db,
        user.id,
        [_flight("DCA", "MCO", "2025-02-21T15:00:00", "2025-02-21T17:40:00", "B6", "B62023", "DYXGR8")],
    )
    db.commit()

    segments = db.query(Segment).all()
    assert len(segments) == 1
    assert segments[0].dep_airport == "DCA"
    assert segments[0].arr_airport == "MCO"


def test_cancellation_marks_surviving_similar_booking_as_replacement_candidate():
    db, user = _session()

    build_segments_and_trips(
        db,
        user.id,
        [
            _flight(
                "IAH",
                "DCA",
                "2025-03-24T07:30:00",
                "2025-03-24T11:28:00",
                "UA",
                "UA546",
                "DZ9KZ1",
                source_received_at="2025-01-03T01:01:49",
            ),
            _flight(
                "DCA",
                "IAH",
                "2025-03-27T14:46:00",
                "2025-03-27T17:25:00",
                "UA",
                "UA1274",
                "DZ9KZ1",
                source_received_at="2025-01-03T01:01:49",
            ),
        ],
    )
    build_segments_and_trips(
        db,
        user.id,
        [
            _flight(
                "IAH",
                "DCA",
                "2025-03-24T07:30:00",
                "2025-03-24T11:28:00",
                "UA",
                "UA546",
                "DZYJCJ",
                source_received_at="2025-01-03T01:04:02",
            ),
            _flight(
                "DCA",
                "IAH",
                "2025-03-27T12:42:00",
                "2025-03-27T15:25:00",
                "UA",
                "UA1808",
                "DZYJCJ",
                source_received_at="2025-01-03T01:04:02",
            ),
        ],
    )

    assert cancel_segments_for_pnr(db, user.id, "DZ9KZ1", received_at=_dt("2025-02-05T20:34:41")) == 2
    db.commit()

    segments = db.query(Segment).order_by(Segment.dep_time).all()
    assert [segment.pnr for segment in segments] == ["DZYJCJ", "DZYJCJ"]
    outbound_meta = segments[0].meta_json or {}
    assert "DZ9KZ1" in outbound_meta.get("pnr_aliases", [])
    assert any(
        item.get("type") == "surviving_replacement_candidate"
        and item.get("replaces_pnr") == "DZ9KZ1"
        for item in outbound_meta.get("booking_relationships", [])
    )


def test_reused_pnr_on_later_unrelated_trip_is_marked_as_travel_credit_candidate():
    db, user = _session()

    build_segments_and_trips(
        db,
        user.id,
        [
            _flight(
                "IAH",
                "DCA",
                "2025-03-24T07:30:00",
                "2025-03-24T11:28:00",
                "UA",
                "UA546",
                "DZ9KZ1",
                source_received_at="2025-01-03T01:01:49",
            ),
            _flight(
                "DCA",
                "IAH",
                "2025-03-27T14:46:00",
                "2025-03-27T17:25:00",
                "UA",
                "UA1274",
                "DZ9KZ1",
                source_received_at="2025-01-03T01:01:49",
            ),
        ],
    )
    build_segments_and_trips(
        db,
        user.id,
        [
            _flight(
                "IAH",
                "ORD",
                "2025-06-18T18:28:00",
                "2025-06-18T21:23:00",
                "AA",
                "AA2064",
                "67RXDT",
                source_received_at="2025-05-26T03:08:55",
            ),
            _flight(
                "ORD",
                "IAH",
                "2025-06-22T20:30:00",
                "2025-06-22T23:19:00",
                "UA",
                "UA2426",
                "DZ9KZ1",
                source_received_at="2025-05-26T03:39:57",
            ),
        ],
    )
    db.commit()

    chicago_return = (
        db.query(Segment)
        .filter(Segment.flight_number == "UA2426", Segment.pnr == "DZ9KZ1")
        .one()
    )
    relationships = (chicago_return.meta_json or {}).get("booking_relationships", [])
    assert any(item.get("type") == "possible_reused_pnr_or_travel_credit" for item in relationships)


def test_duplicate_same_segment_with_different_pnr_preserves_alias_metadata():
    db, user = _session()

    build_segments_and_trips(
        db,
        user.id,
        [
            _flight(
                "ORD",
                "IAH",
                "2025-06-22T20:30:00",
                "2025-06-22T23:19:00",
                "UA",
                "UA2426",
                "DZ9KZ1",
            )
        ],
    )
    build_segments_and_trips(
        db,
        user.id,
        [
            _flight(
                "ORD",
                "IAH",
                "2025-06-22T20:30:00",
                "2025-06-22T23:19:00",
                "UA",
                "UA2426",
                "BVJ50J",
            )
        ],
    )
    db.commit()

    [segment] = db.query(Segment).all()
    aliases = (segment.meta_json or {}).get("pnr_aliases", [])
    assert {segment.pnr, *aliases} == {"DZ9KZ1", "BVJ50J"}


def test_same_pnr_layover_chain_removes_covered_through_segment():
    db, user = _session()

    build_segments_and_trips(
        db,
        user.id,
        [
            _flight("MNL", "IAH", "2025-05-09T18:20:00", "2025-05-10T07:20:00", "BR", "BR272", "3EZ3KP"),
            _flight("MNL", "TPE", "2025-05-09T18:20:00", "2025-05-09T20:20:00", "BR", "BR272", "3EZ3KP"),
            _flight("TPE", "IAH", "2025-05-09T21:20:00", "2025-05-10T07:20:00", "BR", "BR52", "3EZ3KP"),
        ],
    )
    db.commit()

    routes = {(segment.dep_airport, segment.arr_airport) for segment in db.query(Segment).all()}
    assert routes == {("MNL", "TPE"), ("TPE", "IAH")}


def test_implied_layover_rewrites_first_leg_when_following_leg_reveals_stop():
    db, user = _session()

    build_segments_and_trips(
        db,
        user.id,
        [
            _flight("MNL", "IAH", "2025-05-09T12:40:00", "2025-05-09T22:20:00", "BR", "BR272", "3EZ3KP"),
            _flight("TPE", "IAH", "2025-05-09T21:20:00", "2025-05-09T22:20:00", "BR", "BR52", "3EZ3KP"),
        ],
    )
    db.commit()

    segments = sorted(db.query(Segment).all(), key=lambda segment: segment.dep_airport)
    routes = {(segment.flight_number, segment.dep_airport, segment.arr_airport) for segment in segments}
    assert routes == {("BR272", "MNL", "TPE"), ("BR52", "TPE", "IAH")}
    rewritten = next(segment for segment in segments if segment.flight_number == "BR272")
    relationships = (rewritten.meta_json or {}).get("booking_relationships", [])
    assert any(item.get("type") == "implied_layover_destination_rewrite" for item in relationships)


def test_same_trip_unique_flight_key_updates_old_through_segment_to_layover_leg():
    db, user = _session()

    build_segments_and_trips(
        db,
        user.id,
        [
            _flight("SIN", "IAH", "2025-10-03T06:15:00", "2025-10-03T14:55:00", "NH", "NH802", "CB5Q98"),
        ],
    )
    build_segments_and_trips(
        db,
        user.id,
        [
            _flight("SIN", "NRT", "2025-10-03T06:15:00", "2025-10-03T14:30:00", "NH", "NH802", "CB5Q98"),
            _flight("NRT", "IAH", "2025-10-03T17:45:00", "2025-10-04T14:55:00", "NH", "NH6450", "CB5Q98"),
        ],
    )
    db.commit()

    routes = {(segment.flight_number, segment.dep_airport, segment.arr_airport) for segment in db.query(Segment).all()}
    assert routes == {("NH802", "SIN", "NRT"), ("NH6450", "NRT", "IAH")}


def test_explicit_nonstop_segment_is_not_removed_by_layover_chain():
    db, user = _session()

    build_segments_and_trips(
        db,
        user.id,
        [
            _flight(
                "MNL",
                "IAH",
                "2025-05-09T18:20:00",
                "2025-05-10T07:20:00",
                "BR",
                "BR272",
                "3EZ3KP",
                nonstop=True,
            ),
            _flight("MNL", "TPE", "2025-05-09T18:20:00", "2025-05-09T20:20:00", "BR", "BR272", "3EZ3KP"),
            _flight("TPE", "IAH", "2025-05-09T21:20:00", "2025-05-10T07:20:00", "BR", "BR52", "3EZ3KP"),
        ],
    )
    db.commit()

    routes = {(segment.dep_airport, segment.arr_airport) for segment in db.query(Segment).all()}
    assert routes == {("MNL", "IAH"), ("TPE", "IAH")}


def test_source_message_pnr_aliases_are_saved_on_new_segment():
    db, user = _session()

    build_segments_and_trips(
        db,
        user.id,
        [
            _flight(
                "DFW",
                "ORD",
                "2020-12-11T14:20:00",
                "2020-12-11T16:45:00",
                "UA",
                "UA3462",
                "OB5PJV",
                pnr_aliases=["BB8851"],
            )
        ],
    )
    db.commit()

    [segment] = db.query(Segment).all()
    assert (segment.meta_json or {}).get("pnr_aliases") == ["BB8851"]
