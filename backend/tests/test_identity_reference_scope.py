"""Synthetic regressions for compound agency references in traveler scope."""
from datetime import datetime, timezone
from html import escape
import pytest
from app.services.parser import parse_email, ParsedFlight
from app.services.passenger_identity import apply_passenger_identity


def body(separator):
    return f'''Your StudentUniverse Order
StudentUniverse Reservation Code: BOOK01
StudentUniverse confirmation number: 12345{separator}LONGAGENCYID
Airline Reservation Code: Royal Air Maroc: 8X2ZQW
Travelers: Alex Avery
Flight details
Royal Air Maroc
Flight 0262
departs NBO
3:30AM
Sat, Jul 16, 2016
arrives CMN
9:50AM
Sat, Jul 16, 2016
Flight 0200
departs CMN
3:05PM
Sat, Jul 16, 2016
arrives JFK
5:55PM
Sat, Jul 16, 2016
Flight 0201
departs JFK
8:30PM
Thu, Aug 11, 2016
arrives CMN
8:20AM
Fri, Aug 12, 2016
Flight 0263
departs CMN
4:15PM
Fri, Aug 12, 2016
arrives NBO
2:00AM
Sat, Aug 13, 2016'''


@pytest.mark.parametrize('separator', ['-', '/', '_'])
@pytest.mark.parametrize('html', [False, True])
def test_compound_agency_reference_does_not_override_named_booking_scope(separator, html):
    text = body(separator)
    result = parse_email(plain_text='' if html else text,
        html=''.join(f'<div>{escape(line)}</div>' for line in text.splitlines()) if html else '',
        attachments=[], user_name='Alex Avery', aliases=[],
        received_at='Mon, 13 Jun 2016 12:00:00 +0000', subject='Your StudentUniverse Order',
        from_email='StudentUniverse <travel@studentuniverse.com>')
    assert len(result.flights) == 4
    assert {f.flight_number for f in result.flights} == {'AT262','AT200','AT201','AT263'}
    assert all(f.ownership == 'self' and f.passenger_names == ['Alex Avery'] for f in result.flights)
    assert all(f.pnr == 'BOOK01' and f.pnr_aliases == ['8X2ZQW'] for f in result.flights)
    assert all(e['scope'].get('pnr') == 'BOOK01' for f in result.flights for e in f.passenger_evidence if e.get('applies'))


@pytest.mark.parametrize('separator', ['-', '/', '_'])
def test_compound_reference_does_not_transfer_traveler_between_bookings(separator):
    start=datetime(2025,2,21,16,tzinfo=timezone.utc)
    flights=[ParsedFlight('IAH','DCA',start,start.replace(hour=19),flight_number='UA123',pnr=pnr)
             for pnr in ['BOOK01','OTHER2']]
    text=f'''Booking reference: BOOK01
Confirmation number: 12345{separator}LONGAGENCYID
Traveler: Alex Avery
Payment details
Fare details
Card payment details
Booking reference: OTHER2
Confirmation number: 67890{separator}ANOTHERAGENCYID
Traveler: Morgan Other
Payment details'''
    apply_passenger_identity(flights,html='',plain_text=text,user_name='Alex Avery',aliases=[])
    assert flights[0].ownership == 'self' and flights[0].passenger_names == ['Alex Avery']
    assert flights[1].ownership == 'other' and flights[1].passenger_names == ['Morgan Other']
