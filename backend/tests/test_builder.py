from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, Segment, Trip, User
from app.services.builder import build_segments_and_trips, build_segments_and_trips_detailed, cancel_segments_for_pnr


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
