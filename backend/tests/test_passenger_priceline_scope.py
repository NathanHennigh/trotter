"""Issued-ticket names apply only to their complete dated journey cards."""
from html import escape

import pytest

from app.services.parser import parse_email
from app.services.passenger_identity import apply_passenger_identity
from test_priceline_itinerary import itinerary


def prepared(text, *, user="Alex Jordan Taylor", html=False):
    markup = "<p>" + "</p><p>".join(escape(line) for line in text.splitlines()) + "</p>" if html else ""
    return parse_email(html=markup, plain_text="" if html else text, attachments=[],
        user_name=user, aliases=[], received_at="2025-01-05T12:00:00+00:00",
        subject="Your priceline itinerary", from_email="person@example.test")


@pytest.mark.parametrize("html", [False, True])
@pytest.mark.parametrize("user,ownership", [("Alex Jordan Taylor", "self"), ("Alex Casey Taylor", "other")])
def test_priceline_visible_issued_ticket_roster_owns_exact_four_legs(html, user, ownership):
    result = prepared(itinerary(), user=user, html=html)
    assert len(result.flights) == 4
    assert all(f.source == "shape_priceline_trip_cards" for f in result.flights)
    assert all(f.ownership == ownership and f.passenger_names == ["Alex Jordan Taylor"] for f in result.flights)
    assert all(f.pnr is None and f.pnr_aliases == [] for f in result.flights)
    assert all(any(e.get("applies") and e["scope"].get("journey_scope") == f.source_leg["journey_scope"]
                   for e in f.passenger_evidence) for f in result.flights)


@pytest.mark.parametrize("html", [False, True])
def test_priceline_different_ticket_journeys_keep_passengers_separate(html):
    text = itinerary().replace("NBO\n>\nEWR\n: 1761234567890", "Morgan Blake\nNBO\n>\nEWR\n: 1761234567890")
    flights = prepared(text, html=html).flights
    assert [f.ownership for f in flights] == ["self", "self", "other", "other"]
    assert [f.passenger_names for f in flights] == [["Alex Jordan Taylor"]] * 2 + [["Morgan Blake"]] * 2


@pytest.mark.parametrize("replace_with", ["", "not a ticket", "0061234567890 extra words"])
def test_priceline_missing_or_invalid_issued_ticket_cannot_use_greeting_or_payer(replace_with):
    text = itinerary().replace(": 0061234567890", replace_with)
    flights = prepared("Dear Alex Jordan Taylor\n" + text).flights
    assert len(flights) == 4
    assert all(f.ownership == "unknown" and not f.passenger_names for f in flights)


def test_priceline_legacy_unbounded_candidates_cannot_inherit_ticket_roster():
    flights = prepared(itinerary()).flights
    for f in flights:
        f.source = "heuristic"
        f.source_leg = {}
        f.passenger_names = []
        f.passenger_name = None
        f.passenger_evidence = []
    apply_passenger_identity(flights, html="", plain_text=itinerary(), user_name="Alex Jordan Taylor", aliases=[])
    assert all(f.ownership == "unknown" and not f.passenger_names for f in flights)


def test_priceline_hidden_roster_is_not_ticket_authority():
    text = itinerary()
    start, end = text.index("Passengers"), text.index("Sun Dec 22\nSun Dec 22")
    html = "<div>" + "</div><div>".join(escape(line) for line in (text[:start] + text[end:]).splitlines()) + "</div>"
    html += "<template>" + text[start:end].replace("\n", "<br>") + "</template>"
    result = parse_email(html=html, plain_text="", attachments=[], user_name="Alex Jordan Taylor", aliases=[],
                        received_at="2025-01-05T12:00:00+00:00", subject="Your priceline itinerary", from_email="person@example.test")
    assert len(result.flights) == 4
    assert all(f.ownership == "unknown" and not f.passenger_names for f in result.flights)


def test_cell_comment_markers_cannot_hide_visible_roster_or_supply_another_name():
    text = itinerary().replace("Alex Jordan Taylor", "Morgan Blake")
    html = "<table>" + "".join("<tr><td>" + escape(line) + "<!--IF SPLIT TICKET--></td></tr>" for line in text.splitlines()) + "</table>"
    html += "<table><tr><td><!--Passenger: Alex Jordan Taylor--></td></tr></table>"
    result = parse_email(html=html, plain_text="", attachments=[], user_name="Alex Jordan Taylor", aliases=[],
                        received_at="2025-01-05T12:00:00+00:00", subject="Your priceline itinerary", from_email="person@example.test")
    assert len(result.flights) == 4
    assert all(f.ownership == "other" and f.passenger_names == ["Morgan Blake"] for f in result.flights)


def test_exact_named_tickets_attach_only_hashed_journey_authority():
    import json
    from app.services.agency_ticket_evidence import agency_identity_key, agency_source_proof_key, agency_traveler_key
    flights=prepared(itinerary()).flights
    proofs=[flight.source_leg['agency_ticket'] for flight in flights]
    assert proofs[0]['identity_key']==proofs[1]['identity_key']
    assert proofs[2]['identity_key']==proofs[3]['identity_key']
    assert proofs[0]['ticket_key']!=proofs[2]['ticket_key']
    assert proofs[0]['document_key']==proofs[2]['document_key']
    for flight,proof in zip(flights,proofs):
        assert proof['provider']=='priceline' and proof['version']==1
        assert proof['identity_key']==agency_identity_key(proof)
        assert proof['source_proof_key']==agency_source_proof_key(proof['identity_key'],flight.source_leg['key'])
        assert proof['traveler_key']==agency_traveler_key('Alex Jordan Taylor')
        assert proof['journey_scope']==flight.source_leg['journey_scope']
    stored=json.dumps([{'source_leg':f.source_leg,'evidence':f.passenger_evidence} for f in flights])
    assert '321-654-987-10' not in stored
    assert '0061234567890' not in stored and '1761234567890' not in stored


@pytest.mark.parametrize('mutation',[
    lambda s:s.replace('Priceline Trip Number: 321-654-987-10','Priceline Trip Number: not-a-reference'),
    lambda s:s.replace('Priceline Trip Number: 321-654-987-10','Priceline Trip Number: 321-654-987-10\nPriceline Trip Number: 123-456-789-01'),
    lambda s:s.replace(': 0061234567890',': https://example.test/0061234567890'),
    lambda s:s.replace(': 0061234567890',': 0061234567890\nJFK > NBO : 0061234567891'),
    lambda s:s.replace('Sun Dec 22\nSun Dec 22','Morgan Blake\nJFK > NBO : 0061234567890\nSun Dec 22\nSun Dec 22'),
])
def test_missing_malformed_or_competing_document_ticket_person_has_no_revision_authority(mutation):
    flights=prepared(itinerary()).flights
    for f in flights:
        f.passenger_names=[]
        f.passenger_name=None
        f.passenger_evidence=[]
    apply_passenger_identity(flights,html='',plain_text=mutation(itinerary()),user_name='Alex Jordan Taylor',aliases=[])
    assert all('agency_ticket' not in f.source_leg for f in flights[:2])


def test_ticket_proof_does_not_attach_for_another_recipient():
    flights=prepared(itinerary(),user='Morgan Blake').flights
    assert all(f.ownership=='other' and 'agency_ticket' not in f.source_leg for f in flights)
    assert all(any(e.get('agency_ticket') for e in f.passenger_evidence) for f in flights)


def test_agency_fingerprints_distinguish_exact_person_document_ticket_and_journey():
    from app.services.agency_ticket_evidence import make_agency_ticket
    scope={'dep_airport':'JFK','arr_airport':'NBO','departure_date':'2024-12-22'}
    original=make_agency_ticket('321-654-987-10','0061234567890','Alex Jordan Taylor',scope)
    variants=[make_agency_ticket('123-456-789-01','0061234567890','Alex Jordan Taylor',scope),
        make_agency_ticket('321-654-987-10','0061234567891','Alex Jordan Taylor',scope),
        make_agency_ticket('321-654-987-10','0061234567890','Alex Casey Taylor',scope),
        make_agency_ticket('321-654-987-10','0061234567890','Alex Jordan Taylor',{**scope,'arr_airport':'DXB'}),
        make_agency_ticket('321-654-987-10','0061234567890','Alex Jordan Taylor',{**scope,'departure_date':'2024-12-23'})]
    assert all(value['identity_key']!=original['identity_key'] for value in variants)
