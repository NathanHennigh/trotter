"""Email-to-itinerary regressions: ownership, cancellation order and replay."""
from __future__ import annotations

import json
import random
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, BookingObservation, MessageStatus, Segment, Trip, User
from app.services.booking_import import apply_booking_message, booking_event_time, set_message_outcome
from app.services.parser import ParsedFlight, ParseResult, parse_email


FIXTURES = json.loads((Path(__file__).parent / "fixtures/orlando-bookings.json").read_text(encoding="utf-8"))
FIXTURES = {row["id"]: row for row in FIXTURES}
EXPECTED = {("IAH", "DCA", "UA1540"), ("DCA", "MCO", "B62023"),
            ("MCO", "ATL", "NK1651"), ("ATL", "IAH", "NK512")}


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as db:
        user = User(name="Alex Avery", email="alex@example.com")
        db.add(user)
        db.flush()
        yield db, user
    engine.dispose()


def parse_fixture(row):
    return parse_email(html=row["html"], plain_text=row["plain_text"], attachments=[],
                       user_name="Alex Avery", aliases=[], received_at=row["received_at"],
                       subject=row["subject"], from_email=row["from_email"])


def apply_fixture(db, user, key, parsed=None):
    row = FIXTURES[key]
    return apply_booking_message(db, user.id, parsed or parse_fixture(row), source_message_id=key,
                                 subject=row["subject"], html=row["html"], plain_text=row["plain_text"],
                                 received_at=row["received_at"])


def orders():
    chronological = ["multicity", "frontier", "canceled_confirmation", "cancellation", "return"]
    result = [chronological, list(reversed(chronological)), ["cancellation", "return", "frontier", "multicity", "canceled_confirmation"]]
    for seed in range(8):
        order = chronological.copy()
        random.Random(seed).shuffle(order)
        if order not in result:
            result.append(order)
    return result


@pytest.mark.parametrize("order", orders())
def test_orlando_import_is_order_independent_and_repeatable(session, order):
    db, user = session
    parsed = {key: parse_fixture(row) for key, row in FIXTURES.items()}
    for key in order:
        apply_fixture(db, user, key, parsed[key])
    db.flush()
    assert {(s.dep_airport, s.arr_airport, s.flight_number) for s in db.query(Segment)} == EXPECTED
    assert db.query(Trip).count() == 1
    trip = db.query(Trip).one()
    assert trip.start_ts.date().isoformat() == "2025-02-18"
    # The return lands Feb 23 at 22:10 in Houston, Feb 24 at 04:10 UTC.
    assert trip.end_ts.isoformat().startswith("2025-02-24T04:10:00")
    before = [(s.id, s.trip_id, s.dep_airport, s.arr_airport, s.dep_time, s.arr_time) for s in db.query(Segment).order_by(Segment.id)]
    observations = db.query(BookingObservation).count()
    for key in reversed(order):
        apply_fixture(db, user, key, parsed[key])
    assert [(s.id, s.trip_id, s.dep_airport, s.arr_airport, s.dep_time, s.arr_time) for s in db.query(Segment).order_by(Segment.id)] == before
    assert db.query(BookingObservation).count() == observations


def test_other_traveler_retained_but_not_counted(session):
    db, user = session
    applied = apply_fixture(db, user, "frontier")
    assert applied.build.held_other == 1
    assert applied.status == MessageStatus.ACCEPTED
    assert db.query(Segment).count() == 0
    assert db.query(BookingObservation).one().ownership == "other"


def flight(ownership="unknown"):
    return ParsedFlight("IAH", "MCO", datetime(2025, 2, 21, 16, 16, tzinfo=timezone.utc),
                        datetime(2025, 2, 21, 19, 40, tzinfo=timezone.utc),
                        airline="F9", flight_number="F91418", pnr="OTHER1", ownership=ownership)


def test_unknown_ownership_is_not_silently_accepted(session):
    db, user = session
    applied = apply_booking_message(db, user.id, ParseResult(flights=[flight()]),
                                    source_message_id="no-name", subject="Flight confirmation",
                                    received_at="Thu, 16 Jan 2025 21:00:00 +0000")
    message = SimpleNamespace()
    set_message_outcome(message, applied, source="test", tier="stale_reparse")
    assert message.status == MessageStatus.REVIEW_REQUIRED
    assert message.parse_evidence["held_unknown"] == 1
    assert db.query(Segment).count() == 0
    assert db.query(BookingObservation).count() == 1


def test_ambiguous_cancellation_keeps_existing_and_does_not_authorize_unknown(session):
    db, user = session
    parsed = ParseResult(flights=[flight("self")])
    result = apply_booking_message(db, user.id, parsed, source_message_id="mixed",
        subject="Your booking was canceled", plain_text="Your booking was canceled. New booking is confirmed.",
        received_at="Thu, 16 Jan 2025 21:00:00 +0000")
    assert result.status == MessageStatus.REVIEW_REQUIRED
    assert db.query(Segment).count() == 0
    later = apply_booking_message(db, user.id, ParseResult(flights=[flight()]),
        source_message_id="unknown-later", subject="Flight confirmation",
        received_at="Fri, 17 Jan 2025 21:00:00 +0000")
    assert later.status == MessageStatus.REVIEW_REQUIRED
    assert db.query(Segment).count() == 0


def test_forward_and_reply_do_not_promote_old_receipt_to_new_booking():
    assert booking_event_time("Fri, 7 Feb 2025 20:00:00 +0000", "Fwd: Receipt",
        "---------- Forwarded message ---------\nFrom: Airline\nDate: Wed, 1 Jan 2025 20:00:00 +0000\nSubject: Receipt") == datetime(2025, 1, 1, 20, tzinfo=timezone.utc)
    assert booking_event_time("Fri, 7 Feb 2025 20:00:00 +0000", "Fwd: Receipt",
        "---------- Forwarded message ---------\nDate: Jan 1, 2025 2:00 PM\nSubject: Receipt") is None
    assert booking_event_time("Fri, 7 Feb 2025 20:00:00 +0000", "Re: Receipt", "Old receipt") is None


def test_cancellation_policy_footer_is_not_cancellation(session):
    db, user = session
    result = apply_booking_message(db, user.id, ParseResult(flights=[flight("self")]),
        source_message_id="ordinary", subject="Flight confirmation",
        plain_text="If your flight is canceled, contact us. Cancellation fees may apply.",
        received_at="Thu, 16 Jan 2025 21:00:00 +0000")
    assert not result.is_cancellation
    assert db.query(Segment).count() == 1


@pytest.mark.parametrize('from_name_recovery', [False, True])
def test_normal_history_reparse_corrects_utc_day_using_same_original_segment(session, monkeypatch, from_name_recovery):
    from app.services import parser
    from app.services.builder import build_segments_and_trips_detailed
    db, user = session
    old = ParsedFlight('LAS', 'IAH', datetime(2026, 3, 23, 23, 30, tzinfo=timezone.utc),
        datetime(2026, 3, 24, 4, 20, tzinfo=timezone.utc), airline='UA', flight_number='UA123',
        pnr='TIME01', ownership='other' if from_name_recovery else 'self')
    monkeypatch.setattr(parser, 'PARSER_VERSION', 25)
    apply_booking_message(db, user.id, ParseResult(flights=[old]), source_message_id='original',
        subject='Flight receipt', received_at='2026-03-01T12:00:00Z')
    if from_name_recovery:
        source = db.query(BookingObservation).one()
        derived = deepcopy(old); derived.ownership = 'self'; derived.source = 'travel_name_recovery'
        derived.source_received_at = datetime(2026, 3, 1, 12, tzinfo=timezone.utc)
        build_segments_and_trips_detailed(db, user.id, [derived],
            source_message_id=f'travel-name:{source.id}:confirmed-alias')
    db.commit()
    segment_id = db.query(Segment).one().id
    originals = {row.id: deepcopy(row.facts) for row in db.query(BookingObservation)}
    corrected = deepcopy(old); corrected.ownership = 'self'
    corrected.dep_time = datetime(2026, 3, 24, 6, 30, tzinfo=timezone.utc)
    corrected.arr_time = datetime(2026, 3, 24, 9, 20, tzinfo=timezone.utc)
    corrected.time_provenance = {'version': 1, 'status': 'normalized', 'departure_local_date': '2026-03-23',
        'departure': {'basis': 'airport_local', 'airport': 'LAS', 'timezone': 'America/Los_Angeles',
                      'local': '2026-03-23T23:30:00', 'utc': corrected.dep_time.isoformat()},
        'arrival': {'basis': 'airport_local', 'airport': 'IAH', 'timezone': 'America/Chicago',
                    'local': '2026-03-24T04:20:00', 'utc': corrected.arr_time.isoformat()}}
    monkeypatch.setattr(parser, 'PARSER_VERSION', 26)
    for _ in range(2):
        result = apply_booking_message(db, user.id, ParseResult(flights=[corrected]), source_message_id='original',
            subject='Flight receipt', received_at='2026-03-01T12:00:00Z')
        db.commit()
        assert result.build.inserted == 0
        stored = db.query(Segment).one()
        assert stored.id == segment_id and stored.dep_time == corrected.dep_time.replace(tzinfo=None)
        assert stored.arr_time == corrected.arr_time.replace(tzinfo=None)
        assert stored.meta_json['time_provenance']['departure_local_date'] == '2026-03-23'
        assert all(db.get(BookingObservation, key).facts == facts for key, facts in originals.items())


def test_multipart_forward_preserves_original_date_without_double_counting_headers(session):
    db, user = session
    text = '---------- Forwarded message ---------\nDate: Jan 1, 2025 14:00:00 +0000\nSubject: Receipt'
    apply_booking_message(db, user.id, ParseResult(flights=[flight('self')]), source_message_id='multipart',
        subject='Fwd: Flight receipt', plain_text=text, html='<div>' + text.replace('\n', '<br>') + '</div>',
        received_at='2025-02-01T12:00:00Z')
    observed = db.query(BookingObservation).one()
    assert observed.source_event_at == datetime(2025, 1, 1, 14)
    assert observed.facts['source_time_provenance']['received_at'] == '2025-02-01T12:00:00+00:00'


def test_partial_cancellation_uses_airport_local_day_after_utc_normalization(session):
    db, user = session
    target = flight('self'); target.dep_airport = 'LAS'; target.arr_airport = 'IAH'
    target.dep_time = datetime(2025, 2, 22, 7, 30, tzinfo=timezone.utc)
    target.arr_time = datetime(2025, 2, 22, 10, 20, tzinfo=timezone.utc)
    target.time_provenance = {'version': 1, 'status': 'normalized', 'departure_local_date': '2025-02-21'}
    apply_booking_message(db, user.id, ParseResult(flights=[target]), source_message_id='initial',
        subject='Flight receipt', received_at='2025-01-01T12:00:00Z')
    result = apply_booking_message(db, user.id, ParseResult(flights=[target]), source_message_id='canceled',
        subject='Flight cancellation confirmed',
        plain_text='Your flight F91418 on February 21, 2025 was canceled.', received_at='2025-01-02T12:00:00Z')
    assert result.canceled == 1 and db.query(Segment).count() == 0
