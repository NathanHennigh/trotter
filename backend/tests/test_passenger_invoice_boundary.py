"""Invoice summaries following a real passenger table are not travelers."""
from html import escape

import pytest

from test_passenger_identity import flight, identify
from app.services.travel_inbox_identity import retained_passengers


def receipt(names, *, html=False, combined=False, malformed=False):
    heading = ['INVOICE SUMMARY'] if combined else ['INVOICE', 'SUMMARY']
    roster = [*names, *(['<unreadable passenger>'] if malformed else [])]
    if html:
        return '<p>Confirmation code: TEST12</p><table><tr><th>Passenger Name</th><th>Seats</th><th>Bags</th><th>Special Services</th></tr>' + ''.join(
            '<tr><td>' + escape(name) + '</td><td></td><td></td><td></td></tr>' for name in roster) + '</table>' + ''.join(
            '<div>' + value + '</div>' for value in heading) + '<table><tr><td>Airfare</td><td>$12.34</td></tr><tr><td>Options</td><td>$0.00</td></tr><tr><td>Discounts</td><td>-$1.00</td></tr></table><div>Payment details</div>'
    return '\n'.join(['Confirmation code: TEST12', 'Passenger Name | Seats | Bags | Special Services',
                      *roster, *heading, 'Airfare | $12.34', 'Options | $0.00', 'Discounts | -$1.00', 'Payment details'])


@pytest.mark.parametrize('html', [False, True])
@pytest.mark.parametrize('combined', [False, True])
@pytest.mark.parametrize('names,owner,ownership', [
    (['Alex Avery'], 'Alex Avery', 'self'),
    (['Morgan Avery'], 'Alex Avery', 'other'),
    (['Alex Avery', 'Morgan Avery'], 'Alex Avery', 'self'),
    (['Morgan Invoice', 'Taylor Summary'], 'Morgan Invoice', 'self'),
])
def test_invoice_fields_never_become_passenger_or_ambiguity(html, combined, names, owner, ownership):
    body = receipt(names, html=html, combined=combined)
    row = identify([flight(pnr='TEST12')], html=body if html else '', text='' if html else body, user=owner)[0]
    assert row.ownership == ownership and row.passenger_names == names
    assert all(e['complete'] for e in row.passenger_evidence if e.get('applies'))
    retained = retained_passengers({'ownership': row.ownership, 'facts': vars(row)}, {'name': owner})
    expected = [name for name in names if name != owner]
    assert [person['passenger_name'] for person in retained] == expected


@pytest.mark.parametrize('html', [False, True])
def test_invoice_heading_cannot_repair_a_malformed_additional_traveler(html):
    body = receipt(['Morgan Avery'], html=html, malformed=True)
    row = identify([flight(pnr='TEST12')], html=body if html else '', text='' if html else body)[0]
    assert row.ownership == 'unknown'
    assert not any(e['complete'] for e in row.passenger_evidence if e.get('applies'))


@pytest.mark.parametrize('name', ['Morgan Invoice', 'Taylor Summary', 'Invoice Summary'])
def test_invoice_words_in_explicit_full_name_are_not_globally_excluded(name):
    body = f'Confirmation code: TEST12\nPassenger Name: {name}\nPayment details'
    row = identify([flight(pnr='TEST12')], text=body, user=name)[0]
    assert row.ownership == 'self' and row.passenger_names == [name]


@pytest.mark.parametrize('footer', ['INVOICE\nSUMMARY\nMorgan Avery', 'INVOICE SUMMARY Morgan Avery\nAirfare | $12.34'])
def test_similar_prose_or_untyped_summary_is_not_an_exclusive_roster_boundary(footer):
    body = 'Confirmation code: TEST12\nPassenger Name\nAlex Avery\n' + footer + '\nPayment details'
    row = identify([flight(pnr='TEST12')], text=body, user='Morgan Avery')[0]
    assert row.ownership != 'other'
