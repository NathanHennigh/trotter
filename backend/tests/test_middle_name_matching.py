"""Compact names require known components, not an arbitrary first-name prefix."""
from datetime import datetime, timedelta, timezone

import pytest

from app.services.parser import ParsedFlight
from app.services.passenger_identity import apply_passenger_identity, full_names_match, identity_candidates, names_match


@pytest.mark.parametrize('printed', [
    'AlexJordan Avery', 'AVERY/ALEXJORDAN', 'AVERY,ALEXJORDAN', 'Avery AlexJordan',
    'Mr. AlexJordan Avery', 'ALEXJORDAN AVERY', 'AVERY/ALEX JORDAN',
])
def test_known_full_given_names_match_exact_compaction(printed):
    assert names_match(printed, 'Alex Jordan Avery')
    assert full_names_match(printed, 'Alex Jordan Avery')
    assert names_match('Alex Jordan Avery', printed)


@pytest.mark.parametrize('printed', ['AlexJ Avery', 'AVERY/ALEXJ', 'Avery, AlexJ'])
def test_compact_middle_initial_is_not_inferred(printed):
    assert not names_match(printed, 'Alex Jordan Avery')
    assert not full_names_match(printed, 'Alex Jordan Avery')


@pytest.mark.parametrize('printed', ['AlexJordanC Avery', 'AlexJCasey Avery', 'AVERY/ALEXJC'])
def test_multiple_confirmed_middle_names_do_not_resolve_fused_initials(printed):
    assert not names_match(printed, 'Alex Jordan Casey Avery')
    assert not full_names_match(printed, 'Alex Jordan Casey Avery')


@pytest.mark.parametrize('printed,candidate', [
    ('AlexJordan Avery', 'Alex Avery'), ('Alexandra Avery', 'Alex Avery'),
    ('AVERY/ALEXANDRA', 'Alex Avery'), ('AlexC Avery', 'Alex Jordan Avery'),
    ('AlexCasey Avery', 'Alex Jordan Avery'), ('AlexJordan Avery', 'Alex Casey Avery'),
    ('AlexJordan Avery', 'Al Jordan Avery'), ('JordanAlex Avery', 'Alex Jordan Avery'),
    ('Jordan Alex Avery', 'Alex Jordan Avery'), ('Alex Casey Jordan Avery', 'Alex Jordan Casey Avery'),
    ('AlexJordan Avery Jr', 'Alex Jordan Avery'), ('AVERY/ALEXJORDAN JR', 'Alex Jordan Avery Sr'),
    ('AJ Avery', 'Alex Jordan Avery'), ('AlexJordan Other', 'Alex Jordan Avery'),
])
def test_compaction_never_guesses_missing_components_or_discards_conflicts(printed, candidate):
    assert not names_match(printed, candidate)
    assert not full_names_match(printed, candidate)


@pytest.mark.parametrize('printed', ['AlexJordan Avery Jr', 'AVERY/ALEXJORDAN JR'])
def test_matching_suffix_is_preserved(printed):
    assert names_match(printed, 'Alex Jordan Avery Jr')
    assert full_names_match(printed, 'Alex Jordan Avery Jr')


def test_unicode_components_match_without_changing_surname():
    assert full_names_match('GARCÍA/JOSÉLUIS', 'José Luis García')
    assert not names_match('GARCÍA/JOSÉLUIS', 'José Luis González')


def test_full_alias_supersedes_only_its_short_normal_order_name():
    assert identity_candidates('Alex Avery', ['Alex Jordan Avery', 'Alex Casey Avery', 'Alex Avery']) == [
        'Alex Jordan Avery', 'Alex Casey Avery']
    assert identity_candidates('Alex Jordan Avery', ['Alex Avery', 'Morgan Avery']) == [
        'Alex Jordan Avery', 'Morgan Avery']
    assert identity_candidates('Sam Carter', ['Sam Taylor Blake']) == ['Sam Carter', 'Sam Taylor Blake']


@pytest.mark.parametrize('alias', ['A Jordan Avery', 'Alex J Avery', 'Alex Jordan Avery Jr', 'Maria de la Cruz'])
def test_incomplete_or_compound_alias_does_not_suppress_short_candidate(alias):
    user = 'Maria Cruz' if alias.startswith('Maria') else 'Alex Avery'
    assert user in identity_candidates(user, [alias])


@pytest.mark.parametrize('printed,ownership', [
    ('Alex Avery', 'self'), ('Alex Jordan Avery', 'self'), ('AlexJordan Avery', 'self'),
    ('AVERY/ALEXJORDAN', 'self'), ('Alex Casey Avery', 'other'), ('AlexCasey Avery', 'other'),
])
def test_explicit_middle_alias_controls_personal_ownership(printed, ownership):
    start = datetime(2025, 1, 1, 12, tzinfo=timezone.utc)
    flight = ParsedFlight('IAH', 'DCA', start, start + timedelta(hours=3), pnr='BOOK01', flight_number='UA123')
    apply_passenger_identity([flight], html='', plain_text=f'Booking reference: BOOK01\nTraveler: {printed}\nPayment details',
                             user_name='Alex Avery', aliases=['Alex Jordan Avery'])
    assert flight.ownership == ownership
    assert flight.passenger_names == [printed]


def test_without_confirmed_middle_name_compact_given_name_remains_unknown():
    start = datetime(2025, 1, 1, 12, tzinfo=timezone.utc)
    flight = ParsedFlight('IAH', 'DCA', start, start + timedelta(hours=3), pnr='BOOK01', flight_number='UA123')
    apply_passenger_identity([flight], html='', plain_text='Traveler: AVERY/ALEXJORDAN\nPayment details',
                             user_name='Alex Avery', aliases=[])
    assert flight.ownership == 'unknown'


@pytest.mark.parametrize('printed', ['AlexJ Avery', 'AVERY/ALEXJ'])
def test_compact_initial_cannot_choose_between_explicitly_different_travelers(printed):
    start = datetime(2025, 1, 1, 12, tzinfo=timezone.utc)
    flight = ParsedFlight('IAH', 'DCA', start, start + timedelta(hours=3), pnr='BOOK01', flight_number='UA123')
    apply_passenger_identity([flight], html='',
        plain_text=f'Booking reference: BOOK01\nPassengers: {printed}; Alex James Avery\nPayment details',
        user_name='Alex Jordan Avery', aliases=[])
    assert flight.ownership == 'unknown'


def test_existing_spaced_initial_matching_remains_unchanged():
    assert names_match('Alex J Avery', 'Alex Jordan Avery')
    assert not full_names_match('Alex J Avery', 'Alex Jordan Avery')


@pytest.mark.parametrize('printed,candidate', [
    ('AVERY JR/ALEX', 'Alex Avery Jr'), ('AVERY SR/ALEX', 'Alex Avery Sr'),
    ('AVERY III/ALEX JORDAN', 'Alex Jordan Avery III'),
    ('AVERY JR/ALEXJORDAN', 'Alex Jordan Avery Jr'),
    ('AVERY JR, ALEX', 'Alex Avery Jr'), ('AVERY/ALEX JR', 'Alex Avery Jr'),
    ('AVERY JR/ALEX JR', 'Alex Avery Jr'), ('Alex Avery, Jr', 'Alex Avery Jr'),
    ('Alex Avery Jr, Jr', 'Alex Avery Jr'),
])
def test_explicit_name_order_preserves_suffix_on_either_side(printed, candidate):
    assert names_match(printed, candidate)
    assert names_match(candidate, printed)
    assert full_names_match(printed, candidate)


@pytest.mark.parametrize('printed,candidate', [
    ('AVERY JR/ALEX', 'Alex Avery Sr'), ('AVERY JR/ALEX', 'Alex Avery'),
    ('AVERY JR/ALEX SR', 'Alex Avery Jr'), ('AVERY JR/ALEX SR', 'Alex Avery Sr'),
    ('Alex Avery Jr, Sr', 'Alex Avery Jr'), ('AVERY III/ALEX', 'Alex Avery II'),
    ('AVERY/ALEX JR', 'Alex Avery Sr'), ('AVERY/JR', 'Alex Avery Jr'),
])
def test_conflicting_or_missing_suffixes_never_match(printed, candidate):
    assert not names_match(printed, candidate)
    assert not full_names_match(printed, candidate)


def test_family_side_suffix_does_not_remove_existing_personal_flight():
    from copy import deepcopy
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.models import Base, Segment, User
    from app.services.booking_import import apply_booking_message
    from app.services.parser import ParseResult
    from app.services.flight_times import normalize_flight_times

    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = User(name='Alex Avery Jr', email='alex@example.test')
        db.add(user); db.flush()
        start = datetime(2025, 1, 1, 12, tzinfo=timezone.utc)
        value = ParsedFlight('IAH', 'DCA', start, start + timedelta(hours=3), pnr='BOOK01', flight_number='UA123')
        normalize_flight_times(value)
        ids = []
        for index, name in enumerate(['Alex Avery Jr', 'AVERY JR/ALEX', 'AVERY JR/ALEX']):
            incoming = deepcopy(value)
            apply_passenger_identity([incoming], html='',
                plain_text=f'Booking reference: BOOK01\nTraveler: {name}\nPayment details',
                user_name=user.name, aliases=[])
            assert incoming.ownership == 'self'
            apply_booking_message(db, user.id, ParseResult(flights=[incoming]),
                source_message_id=f'receipt-{min(index, 1)}', subject='Flight confirmation',
                received_at=f'2024-12-0{min(index, 1) + 1}T12:00:00Z')
            ids.append(db.query(Segment).one().id)
        assert len(set(ids)) == 1
