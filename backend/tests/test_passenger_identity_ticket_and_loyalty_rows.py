"""Named manifests retain every traveler across narrowly typed metadata rows."""
from html import escape

import pytest

from test_passenger_identity import flight, identify


def apply(text, *, html=False, flights=None, user='Alex Avery'):
    rows=flights or [flight('UA2311','TEST12','BNA','IAH')]
    return identify(rows, html='<div>'+'</div><div>'.join(escape(x) for x in text.splitlines())+'</div>' if html else '',
                    text='' if html else text, user=user)


def emirates(names=('Mr Morgan Avery',), footer=None):
    return '\n'.join(['Confirmation code: TEST12','Passengers',*names,
        *(footer if footer is not None else ['Emirates Skywards number','EK123456789','Choose your seat |']),
        'Payment information','Paid by Alex Avery'])


@pytest.mark.parametrize('html',[False,True])
@pytest.mark.parametrize('names,ownership',[(('Mr Morgan Avery',),'other'),(('Mr Alex Avery',),'self'),
    (('Mr Morgan Avery','Mr Alex Avery'),'self')])
def test_exact_loyalty_footer_closes_a_named_roster(html,names,ownership):
    row=apply(emirates(names),html=html)[0]
    assert row.ownership==ownership and row.passenger_names==list(names)
    assert all(e['complete'] for e in row.passenger_evidence if e.get('applies'))


@pytest.mark.parametrize('html',[False,True])
@pytest.mark.parametrize('footer',[
    ['Emirates Skywards number'],
    ['Emirates Skywards number','EK123456789'],
    ['Emirates Skywards numbers','EK123456789','Choose your seat'],
    ['Emirates Skywards number Alex Avery','EK123456789','Choose your seat'],
    ['Emirates Skywards number','EK12345','Choose your seat'],
    ['Emirates Skywards number','123456789','Choose your seat'],
    ['Emirates Skywards number','EK123456789-SUFFIX','Choose your seat'],
    ['Emirates Skywards number','EK123456789','Choose your seat with Alex Avery'],
    ['Emirates Skywards number','EK123456789','Alex Avery','Choose your seat'],
])
def test_unrecognized_or_incomplete_loyalty_footer_cannot_prove_other(html,footer):
    row=apply(emirates(footer=footer),html=html)[0]
    assert row.ownership=='unknown'


@pytest.mark.parametrize('html',[False,True])
def test_unreadable_name_before_loyalty_footer_keeps_roster_incomplete(html):
    row=apply(emirates(('Mr Morgan Avery','<unreadable person>')),html=html)[0]
    assert row.ownership=='unknown'


@pytest.mark.parametrize('html',[False,True])
def test_passenger_options_section_title_cannot_supply_recipient_names(html):
    text='Confirmation code: TEST12\nPASSENGERS\nADULT(S)\n1 - Alex Avery\nSERVICES\nPASSENGER OPTIONS & EXTRAS DETAIL\nBaggage purchased'
    row=apply(text,html=html)[0]
    assert row.ownership=='self'
    assert row.passenger_names==['Alex Avery']
    assert not any(e['name'] in {'OPTIONS','EXTRAS DETAIL'} for e in row.passenger_evidence)


@pytest.mark.parametrize('html',[False,True])
def test_legitimate_name_under_explicit_passenger_label_is_unchanged(html):
    row=apply('Confirmation code: TEST12\nPassenger name: Morgan Detail\nPayment details',html=html,user='Morgan Detail')[0]
    assert row.ownership=='self' and row.passenger_names==['Morgan Detail']


@pytest.mark.parametrize('html',[False,True])
@pytest.mark.parametrize('name,owner,expected',[('Alex Avery','Alex Avery','self'),('Morgan Avery','Alex Avery','other')])
def test_exact_bundle_section_closes_explicit_numbered_roster(html,name,owner,expected):
    text=f'Confirmation code: TEST12\nPASSENGERS |\nADULT(S)\n1 - {name} |\nNot a FRONTIER Miles sm Member? Sign Up!\nBUNDLE IT |\nLIMITED TIME OFFER\nPASSENGER OPTIONS & EXTRAS DETAIL\nBilled payer\n'
    row=apply(text,html=html,user=owner)[0]
    assert row.ownership==expected and row.passenger_names==[name]
    assert all(e['complete'] for e in row.passenger_evidence if e.get('applies'))


@pytest.mark.parametrize('html',[False,True])
def test_bundle_heading_cannot_repair_unreadable_traveler_before_it(html):
    text='Confirmation code: TEST12\nPASSENGERS |\nADULT(S)\n1 - Morgan Avery |\n<unreadable traveler>\nBUNDLE IT |\nPayment details'
    row=apply(text,html=html)[0]
    assert row.ownership=='unknown'


def ticket_row(name,ticket='0161234567890',route='BNA-IAH',seat='-----',split=False):
    return [name,f'eTicket number: {ticket}',f'Seats: {route} {seat}'] if split else [name,f'eTicket number: {ticket} | Seats: {route} {seat}']


def united(records=None,end='Purchase Summary'):
    if records is None:records=[*ticket_row('AVERY/MORGAN'),*ticket_row('AVERY/ALEX','0161234567891')]
    return '\n'.join(['Confirmation code: TEST12','Traveler Details',*records,end,'Payment information','Taylor Payer'])


@pytest.mark.parametrize('html',[False,True])
@pytest.mark.parametrize('credited',[False,True])
@pytest.mark.parametrize('split',[False,True])
def test_ticketed_manifest_retains_every_seat_route_across_frequent_flyer_row(html,credited,split):
    ticket='0161234567890'+(' (Credited)' if credited else '')
    records=['AVERY/ALEX',f'eTicket number: {ticket} | Seats: BNA-IAH 30F',
        *(['Frequent Flyer: UA-XXXXX111 Member','IAH-BNA 31A'] if split else ['Frequent Flyer: UA-XXXXX111 Member | IAH-BNA 31A']),
        'Preferred zone seat (0161234567899) | IAH-BNA']
    values=[flight('UA123','TEST12','BNA','IAH'),flight('UA456','TEST12','IAH','BNA',day=23)]
    result=apply(united(records),html=html,flights=values)
    assert [f.ownership for f in result]==['self','self']
    assert all(f.passenger_names==['AVERY/ALEX'] for f in result)
    hashes=[]
    for f in result:
        evidence=[e for e in f.passenger_evidence if e['applies']]
        assert evidence and all(e['complete'] is True for e in evidence)
        assert all((e['scope']['dep_airport'],e['scope']['arr_airport'])==(f.dep_airport,f.arr_airport) for e in evidence)
        hashes.extend(e['issued_ticket_key'] for e in evidence)
    from app.services.passenger_identity import _issued_ticket_key
    assert set(hashes)=={_issued_ticket_key('0161234567890')}
    assert _issued_ticket_key('0161234567899') not in hashes


@pytest.mark.parametrize('html',[False,True])
@pytest.mark.parametrize('extra',[
    'Frequent Flyer: UA-XXXXX111 Member | IAH-BNA unreadable',
    'Frequent Flyer: UA-XXXXX111 Member | Alex Avery',
    'Preferred zone seat (0161234567899) | IAH-BNA',
    'Seat payment 0161234567899 | IAH-BNA 31A',
    'IAH-IAH 31A', 'IAH-BNA', '<unreadable passenger>',
])
def test_malformed_or_ancillary_only_extra_route_cannot_prove_complete_other(html,extra):
    result=apply(united(['AVERY/MORGAN','eTicket number: 0161234567890 | Seats: BNA-IAH 30F',extra]),html=html)[0]
    assert result.ownership=='unknown'
    assert not any(e.get('issued_ticket_key') or e.get('complete') for e in result.passenger_evidence if e['applies'])


def test_multiple_named_ticket_routes_do_not_bleed_into_another_person():
    records=['AVERY/MORGAN','eTicket number: 0161234567890 | Seats: BNA-IAH 30F',
        'Frequent Flyer: UA-XXXXX111 Member | IAH-BNA 31A',
        'AVERY/ALEX','eTicket number: 0161234567891 | Seats: BNA-DEN 12A']
    result=apply(united(records),flights=[flight('UA123','TEST12','BNA','IAH'),flight('UA456','TEST12','IAH','BNA',day=23),flight('UA789','TEST12','BNA','DEN')])
    assert [f.ownership for f in result]==['other','other','self']
    assert [f.passenger_names for f in result]==[['AVERY/MORGAN'],['AVERY/MORGAN'],['AVERY/ALEX']]


@pytest.mark.parametrize('suffix',['(Refunded)','(Credited EXTRA)','-Credited','(Credited)/123'])
def test_ticket_status_suffix_is_exact_and_not_arbitrary_prose(suffix):
    result=apply(united(['AVERY/MORGAN',f'eTicket number: 0161234567890 {suffix} | Seats: BNA-IAH 30F']))[0]
    assert result.ownership=='unknown'
    assert not any(e.get('issued_ticket_key') for e in result.passenger_evidence)


@pytest.mark.parametrize('html',[False,True])
@pytest.mark.parametrize('split',[False,True])
@pytest.mark.parametrize('user',['Alex Avery','Morgan Avery','Taylor Payer'])
def test_ticket_and_seat_metadata_do_not_end_a_two_person_manifest(html,split,user):
    records=[*ticket_row('AVERY/MORGAN',split=split),*ticket_row('AVERY/ALEX','0161234567891',split=split)]
    row=apply(united(records),html=html,user=user)[0]
    assert row.ownership==('other' if user=='Taylor Payer' else 'self')
    assert row.passenger_names==['AVERY/MORGAN','AVERY/ALEX']
    assert all(e['complete'] and e['scope']=={'pnr':'TEST12','dep_airport':'BNA','arr_airport':'IAH'}
               for e in row.passenger_evidence if e.get('applies'))


@pytest.mark.parametrize('html',[False,True])
@pytest.mark.parametrize('records,end',[
    ([*ticket_row('AVERY/MORGAN'),'AVERY/ALEX'],'Purchase Summary'),
    ([*ticket_row('AVERY/MORGAN'),*ticket_row('AVERY/ALEX','0161234567891-EXTRA')],'Purchase Summary'),
    ([*ticket_row('AVERY/MORGAN'),*ticket_row('not@a-person','0161234567891')],'Purchase Summary'),
    (ticket_row('AVERY/MORGAN'),'Payment information'),
    (ticket_row('AVERY/MORGAN'),'Unrecognized footer'),
    (ticket_row('AVERY/MORGAN'),'')])
def test_malformed_or_unclosed_ticket_manifest_does_not_prove_exclusive_other(html,records,end):
    assert apply(united(records,end),html=html)[0].ownership=='unknown'


@pytest.mark.parametrize('html',[False,True])
def test_ticket_seat_routes_keep_passengers_scoped_to_their_printed_legs(html):
    rows=[flight('UA2311','TEST12','BNA','IAH'),flight('UA999','TEST12','IAH','AUS')]
    records=[*ticket_row('AVERY/MORGAN'),*ticket_row('AVERY/ALEX','0161234567891','IAH-AUS','12A')]
    apply(united(records),html=html,flights=rows)
    assert [r.ownership for r in rows]==['other','self']
    assert rows[0].passenger_names==['AVERY/MORGAN'] and rows[1].passenger_names==['AVERY/ALEX']


@pytest.mark.parametrize('html',[False,True])
def test_separate_booking_manifests_do_not_bleed_names(html):
    rows=[flight('UA2311','TEST12','BNA','IAH'),flight('UA2311','OTHER1','BNA','IAH')]
    text=united(ticket_row('AVERY/MORGAN'))+'\n'+united(ticket_row('AVERY/ALEX')).replace('TEST12','OTHER1')
    apply(text,html=html,flights=rows)
    assert [r.ownership for r in rows]==['other','self']


@pytest.mark.parametrize('heading',['Billing Details','Payment Details','Customer Details'])
def test_ticket_like_payer_rows_are_not_travelers(heading):
    row=apply(united(ticket_row('AVERY/ALEX')).replace('Traveler Details',heading))[0]
    assert row.ownership=='unknown' and not row.passenger_names


def test_ticket_rows_do_not_relax_middle_name_identity():
    row=apply(united(ticket_row('AVERY/ALEXJORDAN')),user='Alex Casey Avery')[0]
    assert row.ownership!='self'
