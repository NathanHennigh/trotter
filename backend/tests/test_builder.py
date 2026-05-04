from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, Trip, User
from app.services.builder import build_segments_and_trips


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)


def _flight(dep: str, arr: str, dep_time: str, arr_time: str, airline: str, number: str, pnr: str):
    return SimpleNamespace(
        dep_airport=dep,
        arr_airport=arr,
        dep_time=_dt(dep_time),
        arr_time=_dt(arr_time),
        airline=airline,
        flight_number=number,
        pnr=pnr,
        source="test",
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
