"""Destination-bearing email titles cannot become booking-reference aliases."""
import pytest

from app.services.booking_references import extract_primary_reference, extract_reference_fields
from app.services.parser import _extract_pnr_aliases


@pytest.mark.parametrize('city,airport', [
    ('Denver', 'DEN-Denver Intl.'), ('London', 'LHR-London Heathrow'),
    ('Nairobi', 'NBO-Jomo Kenyatta'),
])
@pytest.mark.parametrize('title', ['Flight purchase confirmation', 'Flight confirmation',
                                  'Travel Desk Flight purchase confirmation'])
@pytest.mark.parametrize('separator', [' - ', ' — ', ' – '])
def test_destination_title_does_not_supply_an_alias(city, airport, title, separator):
    text = (f'{title}{separator}{city}, Region ({airport}) - Fri, Mar 4 - '
            '(Itinerary # 123456789)\nAirline confirmation: SAFE12')
    fields = extract_reference_fields(text)
    assert [field.code for field in fields] == ['SAFE12']
    assert text[fields[0].start:fields[0].end] == 'Airline confirmation: SAFE12'
    assert extract_primary_reference(text) == 'SAFE12'
    assert _extract_pnr_aliases(text.upper(), primary='SAFE12') == []


@pytest.mark.parametrize('text,code', [
    ('Confirmation: DENVER', 'DENVER'),
    ('Confirmation - DENVER', 'DENVER'),
    ('Flight purchase confirmation - DENVER', 'DENVER'),
    ('Airline confirmation: DENVER', 'DENVER'),
    ('Booking reference: LONDON', 'LONDON'),
    ('Confirmation: DENVER (United)', 'DENVER'),
    ('Flight confirmation: ABC123, Denver, CO (DEN-Denver Intl.)', 'ABC123'),
    ('Flight purchase confirmation - ABC123, Denver, CO (DEN-Denver Intl.) - '
     'Fri, Mar 4 - (Itinerary # 123456789)', 'ABC123'),
    ('Flight purchase confirmation: Denver, CO (DEN-Denver Intl.)', 'DENVER'),
    ('Confirmation code: DENVER, CO (DEN-Denver Intl.)', 'DENVER'),
    ('Confirmation: ABC123 | Denver, CO (DEN-Denver Intl.)', 'ABC123'),
    ('Flight purchase confirmation - ABC123; Denver, CO (DEN-Denver Intl.)', 'ABC123'),
    ('Flight purchase confirmation - ABC123\nDenver, CO (DEN-Denver Intl.)', 'ABC123'),
])
def test_explicit_reference_fields_and_codes_named_after_cities_are_preserved(text, code):
    assert extract_primary_reference(text) == code
    assert [field.code for field in extract_reference_fields(text)] == [code]
