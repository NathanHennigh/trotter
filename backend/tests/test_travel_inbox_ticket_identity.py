"""A source-bound ticket can corroborate one exact airline name-format variant."""
import copy
from datetime import datetime, timezone

import pytest

from app.models import BookingObservation, FlightShare, TravelInboxAssignment, TravelInboxEvidence, TravelInboxItem, User
from app.services.passenger_identity import _issued_ticket_key, apply_passenger_identity
from app.services.travel_inbox import retain_observation, serialize_item
from app.services.travel_inbox_identity import exact_airline_name_format_match
from test_travel_inbox import session, flight, record
from test_passenger_identity_ticket_and_loyalty_rows import united, ticket_row, apply


FIRST, SECOND = "BLAKE/MORGANCASEY", "Morgan Casey Blake"
TICKET, DIFFERENT = "0161234567890", "0161234567891"


def issued(name=FIRST, ticket=TICKET, **kwargs):
    f = flight(name=name, ownership="self", pnr="TEST12", **kwargs)
    for e in f.passenger_evidence:
        e.update(scope={"pnr":f.pnr},scope_ambiguous=False)
        if e["name"] == name and ticket:
            e.update(issued_ticket_key=_issued_ticket_key(ticket),issued_ticket_version=1)
    return f


def state(db):
    return {m.__tablename__:[{c.name:copy.deepcopy(getattr(row,c.name)) for c in m.__table__.columns}
        for row in db.query(m).order_by(m.id)] for m in (TravelInboxItem,TravelInboxEvidence,BookingObservation,FlightShare)}


@pytest.mark.parametrize("order", [(FIRST,SECOND),(SECOND,FIRST)])
def test_exact_ticket_and_explicit_name_format_reuse_first_item_without_rewriting(session,order):
    db,user=session
    record(db,user,issued(order[0]),message="first")
    item=db.query(TravelInboxItem).one();saved={c.name:getattr(item,c.name) for c in item.__table__.columns}
    record(db,user,issued(order[1]),message="second")
    assert db.query(TravelInboxItem).count()==1
    assert {c.name:getattr(item,c.name) for c in item.__table__.columns}==saved
    assert db.query(TravelInboxEvidence).count()==2
    settled=state(db)
    for _ in range(3):
        for i,name in enumerate(order):record(db,user,issued(name),message=("first","second")[i])
        assert state(db)==settled
    output=serialize_item(db,user.id,item,include_evidence=True)
    assert "issued_ticket" not in str(output) and TICKET not in str(output)


@pytest.mark.parametrize("left,right,expected",[
    (FIRST,SECOND,True),("Blake, Morgan Casey",SECOND,True),("BLAKE/MORGAN","Morgan Blake",True),
    (FIRST,"Morgan Blake",False),(FIRST,"Morgan C Blake",False),(FIRST,"Morgan Jordan Blake",False),
    (FIRST,"Morgan Casey Smith",False),(FIRST,"Morgan Casey de Blake",False),
    (FIRST,"Morgan Casey Blake Jr",False),("BLAKE-SMITH/MORGANCASEY",SECOND,False),
    ("BLAKE/M","Morgan Blake",False),("Morgan Casey Blake", "Morgan Blake",False),
])
def test_name_format_corroboration_is_exact_not_fuzzy(left,right,expected):
    assert exact_airline_name_format_match(left,right) is expected


@pytest.mark.parametrize("other",["Morgan Jordan Blake","Morgan Blake","Morgan C Blake","Morgan Casey Smith"])
def test_distinct_or_incomplete_people_are_not_matched_even_with_same_ticket(session,other):
    db,user=session
    record(db,user,issued(),message="first");record(db,user,issued(other),message="second")
    assert db.query(TravelInboxItem).count()==2


def test_same_concatenated_given_letters_with_different_tickets_remain_distinct(session):
    db,user=session
    record(db,user,issued("BLAKE/ANNABELLA"),message="first")
    record(db,user,issued("Anna Bella Blake",DIFFERENT),message="second")
    assert {i.passenger_name for i in db.query(TravelInboxItem)}=={"BLAKE/ANNABELLA","Anna Bella Blake"}


@pytest.mark.parametrize("missing_first",[False,True])
def test_missing_ticket_holds_format_resolution_without_merging_named_item(session,missing_first):
    db,user=session
    record(db,user,issued(FIRST,None if missing_first else TICKET),message="first")
    old=db.query(TravelInboxItem).one();old_id=old.id
    record(db,user,issued(SECOND,TICKET if missing_first else None),message="second")
    assert {(i.id==old_id,i.passenger_name) for i in db.query(TravelInboxItem)}=={(True,FIRST),(False,None)}
    assert db.query(TravelInboxEvidence).filter_by(item_id=old_id).count()==1


@pytest.mark.parametrize("mutation",["pnr","route","number","date","account"])
def test_exact_booking_dated_leg_and_account_boundaries(session,mutation):
    db,user=session
    record(db,user,issued(),message="first")
    second=issued(SECOND)
    if mutation=="pnr":
        second.pnr="ELSE12"
        for e in second.passenger_evidence:e["scope"]={"pnr":"ELSE12"}
    if mutation=="route":second.arr_airport="DFW"
    if mutation=="number":second.flight_number="NK1652"
    if mutation=="date":
        second.dep_time=second.dep_time.replace(day=24);second.arr_time=second.arr_time.replace(day=24)
    if mutation=="account":
        user=User(name="Alex Avery",email="second@example.test");db.add(user);db.flush()
    record(db,user,second,message="second")
    assert db.query(TravelInboxItem).count()==2
    assert all(db.query(TravelInboxEvidence).filter_by(item_id=i.id).count()==1 for i in db.query(TravelInboxItem))


@pytest.mark.parametrize("protection",["assignment","pending","accepted","declined","revoked","decision"])
def test_existing_assignments_shares_and_decisions_are_never_transferred(session,protection):
    db,user=session
    record(db,user,issued(),message="first");old=db.query(TravelInboxItem).one()
    if protection=="assignment":
        db.add(TravelInboxAssignment(item_id=old.id,user_id=user.id,passenger_name="Reviewed Person"))
    elif protection=="decision":
        obs=db.query(BookingObservation).one();obs.facts={**obs.facts,"user_decision":{"ownership":"self", "status":"active"}}
    else:
        db.add(FlightShare(sender_id=user.id,recipient_email="recipient@example.test",passenger_name=FIRST,
            client_request_id="request",request_hash="a"*64,token_hash="b"*64,token_encrypted=b"encrypted",
            item_ids=[old.id],flights=[],status=protection,expires_at=datetime(2030,1,1,tzinfo=timezone.utc)))
    db.flush();saved=state(db);record(db,user,issued(SECOND),message="second")
    assert db.query(TravelInboxEvidence).filter_by(item_id=old.id).count()==1
    assert {(i.passenger_name,i.reason) for i in db.query(TravelInboxItem)}=={(FIRST,"companion"),(None,"unassigned")}
    assert state(db)["flight_shares"]==saved["flight_shares"]


def test_legacy_ambiguous_matching_items_are_preserved_and_new_source_held(session):
    db,user=session
    record(db,user,issued(),message="first");old=db.query(TravelInboxItem).one();obs=db.query(BookingObservation).one()
    legacy=TravelInboxItem(user_id=user.id,record_key="c"*64,flight_key=old.flight_key,
        passenger_name="Blake, Morgan Casey",passenger_key="blake, morgan casey",reason="companion")
    db.add(legacy);db.flush();db.add(TravelInboxEvidence(item_id=legacy.id,observation_id=obs.id));db.flush()
    old_ids={old.id,legacy.id};record(db,user,issued(SECOND),message="second")
    assert old_ids <= {i.id for i in db.query(TravelInboxItem)}
    assert db.query(TravelInboxItem).filter(TravelInboxItem.passenger_name.is_(None)).count()==1
    assert all(db.query(TravelInboxEvidence).filter_by(item_id=i).count()==1 for i in old_ids)


def test_ticketed_roster_and_fare_fields_emit_same_per_name_hash_without_raw_ticket():
    roster=apply(united([*ticket_row(FIRST,TICKET),*ticket_row('AVERY/ALEX',DIFFERENT)]))[0]
    other=flight(name=SECOND,ownership="self",pnr="TEST12")
    other.passenger_evidence=[];other.passenger_names=[]
    text=f'Confirmation code: TEST12\nFare Details\n{SECOND}\nTicket #: {TICKET}\nAlex Avery\nTicket #: {DIFFERENT}\nTotal'
    apply_passenger_identity([other],html="",plain_text=text,user_name="Alex Avery",aliases=[])
    keys=[{e['name']:e.get('issued_ticket_key') for e in f.passenger_evidence if e.get('applies')} for f in (roster,other)]
    assert keys[0][FIRST]==keys[1][SECOND]==_issued_ticket_key(TICKET)
    assert keys[0]['AVERY/ALEX']==keys[1]['Alex Avery']==_issued_ticket_key(DIFFERENT)
    assert TICKET not in str(roster.passenger_evidence)+str(other.passenger_evidence)


@pytest.mark.parametrize("ticket_field",[f'Ticket #: {TICKET}-EXTRA',f'Ticket #: {TICKET} {DIFFERENT}',
    f'Ticket #: https://example.test/{TICKET}',f'Email ticket #: {TICKET}','Ticket #: 0000000000000'])
def test_only_a_single_whole_named_typed_ticket_field_can_supply_hash(ticket_field):
    f=flight(name=SECOND,ownership="self",pnr="TEST12");f.passenger_evidence=[];f.passenger_names=[]
    apply_passenger_identity([f],html="",plain_text=f'Fare Details\n{SECOND}\n{ticket_field}\nTotal',user_name='Alex Avery',aliases=[])
    assert not any(e.get('issued_ticket_key') for e in f.passenger_evidence)


def test_same_ticket_printed_for_two_distinct_given_names_cannot_establish_identity(session):
    db,user=session
    record(db,user,issued('BLAKE/ANNABELLA'),message='first')
    f=issued('Anna Bella Blake');f.passenger_evidence=[];f.passenger_names=[]
    text=f'Confirmation code: TEST12\nFare Details\nAnna Bella Blake\nTicket #: {TICKET}\nAnnabella Blake\nTicket #: {TICKET}\nAlex Avery\nTicket #: {DIFFERENT}\nTotal'
    apply_passenger_identity([f],html='',plain_text=text,user_name='Alex Avery',aliases=[])
    assert not any(e.get('issued_ticket_key') for e in f.passenger_evidence if e['name'] in {'Anna Bella Blake','Annabella Blake'})
    old=db.query(TravelInboxItem).one()
    record(db,user,f,message='malformed')
    assert db.query(TravelInboxEvidence).filter_by(item_id=old.id).count()==1
    assert old.passenger_name=='BLAKE/ANNABELLA'


@pytest.mark.parametrize('extra',[f'Ticket #: {TICKET}-EXTRA', 'Confirmation code: ELSE12'])
def test_conflicting_or_compound_additional_ticket_scope_does_not_authorize_format_merge(extra):
    f=issued(SECOND);f.passenger_evidence=[];f.passenger_names=[]
    text=f'Confirmation code: TEST12\nFare Details\n{SECOND}\nTicket #: {TICKET}\n{extra}\nTotal'
    apply_passenger_identity([f],html='',plain_text=text,user_name='Alex Avery',aliases=[])
    assert not any(e.get('issued_ticket_key') for e in f.passenger_evidence)


def test_explicit_confirmation_table_carrier_cell_binds_named_fare_ticket():
    from app.services.booking_references import extract_reference_fields
    text=f'Your confirmation codes\nUnited | TEST12\nCapital One Travel | H-Z-COMPOUND-ID\nFare Details\n{SECOND}\nTicket #: {TICKET}\nTotal'
    assert [(v.code,v.airline) for v in extract_reference_fields(text)]==[('TEST12','United')]
    f=issued(SECOND);f.passenger_evidence=[];f.passenger_names=[]
    apply_passenger_identity([f],html='',plain_text=text,user_name='Alex Avery',aliases=[])
    assert any(e.get('issued_ticket_key')==_issued_ticket_key(TICKET) for e in f.passenger_evidence)


@pytest.mark.parametrize('cell',['United | TEST12-EXTRA','United | TEST12/OTHER','United | https://example.test/TEST12',
    'Payment | TEST12','United | TEST12 plus another booking','United |','Unknown Airways | TEST12'])
def test_confirmation_table_requires_exact_carrier_and_whole_reference(cell):
    from app.services.booking_references import extract_reference_fields
    assert not extract_reference_fields('Your confirmation codes\n'+cell+'\nTotal')
