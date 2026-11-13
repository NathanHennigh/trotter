from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.services.ticket_revision_evidence import extract_ticket_revision, ticket_supersedes


def receipt(*, ticket="0271234567890", previous=None, day=20, name="Alex Jordan Avery", pnr="AB12CD"):
    evidence = [{"name":name,"role":"traveler","complete":True,"applies":True,"scope":{"pnr":pnr}}]
    flight = SimpleNamespace(pnr=pnr, flight_number="AS123", dep_airport="SEA", arr_airport="SFO",
        dep_time=datetime(2027,5,day,12,tzinfo=timezone.utc),arr_time=datetime(2027,5,day,14,tzinfo=timezone.utc),
        ownership="self",force_review=False,passenger_evidence=evidence)
    field = f"Ticket {ticket}" + (f" (Previous Ticket {previous})" if previous else "")
    text = f"""Alaska Airlines
Trip details
Confirmation code:
https://example.test/manage
{pnr}
Flight 1 . Thu May {day}
AS123
Traveler(s):
{name}
Summary of airfare charges
Fare breakdownAir travel charges
{name}
Atmos™ Rewards Member: #123456
{field}
New Ticket Value
$100.00
Total charges for air travel
$100.00"""
    return text, flight


def facts(*, new=False):
    text, flight = receipt(ticket="0271234567891" if new else "0271234567890",
                          previous="0271234567890" if new else None,day=27 if new else 20)
    result = vars(flight).copy()
    result["booking_ticket"] = extract_ticket_revision("Your trip",text,[flight])
    assert result["booking_ticket"]
    return result


def supersedes(old,new, earlier="2027-05-01T00:00:00Z",later="2027-05-02T00:00:00Z"):
    return ticket_supersedes(old,new,previous_event_at=earlier,successor_event_at=later)


def test_explicit_ticket_chain_can_replace_a_different_dated_route():
    old,new = facts(),facts(new=True)
    # Explicit ticket exchange, not route similarity, supplies the relationship.
    new['dep_airport'] = new['booking_ticket']['legs'][0]['dep_airport'] = 'PDX'
    assert supersedes(old,new)
    assert not supersedes(new,old)


@pytest.mark.parametrize("rewrite",[
    lambda text: text.replace("Previous Ticket", "Previous reservation"),
    lambda text: text.replace("0271234567890)", "027123456789012)"),
    lambda text: text.replace("Ticket 0271234567891", "Ticket 0271234567891-XYZ"),
    lambda text: text.replace("Flight 1 .", "Flight 2 ."),
    lambda text: text.replace("Total charges for air travel", "Estimated total"),
    lambda text: text.replace("Summary of airfare charges", "Promotional offer"),
    lambda text: text + "\nConfirmation code: XY98ZZ",
    lambda text: text.replace("Atmos™ Rewards Member: #123456", "Billing contact: Alex Jordan Avery"),
    lambda text: text.replace("Ticket 0271234567891", "Ticket 0161234567891"),
    lambda text: text.replace("Ticket 0271234567891", "Ticket 0271234567891\nTicket 0271234567892"),
])
def test_partial_ambiguous_or_unbounded_cards_carry_no_authority(rewrite):
    text, flight = receipt(ticket="0271234567891",previous="0271234567890")
    assert extract_ticket_revision("Trip",rewrite(text),[flight]) is None


@pytest.mark.parametrize("field,value",[("ownership","unknown"),("ownership","other"),("force_review",True)])
def test_extractor_requires_trustworthy_self(field,value):
    text,flight=receipt()
    setattr(flight,field,value)
    assert extract_ticket_revision("Trip",text,[flight]) is None


def test_no_cross_passenger_or_missing_middle_name_proof():
    text,flight=receipt()
    flight.passenger_evidence[0]['name']='Alex Avery'
    assert extract_ticket_revision("Trip",text,[flight]) is None
    old,new=facts(),facts(new=True)
    new['booking_ticket']['passenger_name']='Alex Casey Avery'
    new['passenger_evidence'][0]['name']='Alex Casey Avery'
    assert not supersedes(old,new)


@pytest.mark.parametrize("mutate",[
    lambda old,new: new['booking_ticket'].update(pnr='XX12YY'),
    lambda old,new: new['booking_ticket'].update(previous_ticket_number='0279999999999'),
    lambda old,new: new['booking_ticket'].update(document_complete=False),
    lambda old,new: old['booking_ticket'].update(document_complete=False),
    lambda old,new: old['booking_ticket'].update(source='loose_body_regex'),
    lambda old,new: old['booking_ticket'].update(legs=[]),
    lambda old,new: new['booking_ticket'].update(legs=[new['booking_ticket']['legs'][0]]*2),
    lambda old,new: old.update(dep_airport='LAX'),
    lambda old,new: old.update(ownership='other'),
    lambda old,new: new['passenger_evidence'][0].update(complete=False),
    lambda old,new: new['passenger_evidence'].append({'name':'Morgan Blake','role':'traveler','complete':True}),
    lambda old,new: old.update(passenger_evidence=['invalid']),
    lambda old,new: new['booking_ticket']['legs'][0].update(flight_number=123),
])
def test_validator_requires_complete_exact_source_linkage(mutate):
    old,new=facts(),facts(new=True)
    mutate(old,new)
    assert not supersedes(old,new)


@pytest.mark.parametrize("earlier,later",[
    (None,'2027-05-02T00:00:00Z'),
    ('2027-05-03T00:00:00Z','2027-05-02T00:00:00Z'),
    ('2027-05-02T00:00:00Z','2027-05-02T00:00:00Z'),
    ('2027-05-01T00:00:00Z','2027-05-20T12:00:00Z'),
    ('2027-05-01T00:00:00Z','2027-05-25T12:00:00Z'),
])
def test_replacement_received_after_original_departure_or_without_order_is_not_authoritative(earlier,later):
    assert not supersedes(facts(),facts(new=True),earlier,later)


def test_all_ticket_legs_must_still_be_future_at_exchange():
    old,new=facts(),facts(new=True)
    early=deepcopy(new['booking_ticket']['legs'][0])
    early.update(dep_time='2027-05-01T12:00:00Z',arr_time='2027-05-01T14:00:00Z')
    new['booking_ticket']['legs'].append(early)
    assert not supersedes(old,new)
