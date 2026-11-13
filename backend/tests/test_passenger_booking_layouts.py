"""Anonymized passenger tables and independently scoped agency bookings."""
from datetime import datetime, timedelta, timezone
import json

import pytest

from app.services.parser import ParsedFlight
from app.services.passenger_identity import apply_passenger_identity


def leg(pnr="BOOK01", number="WN123", aliases=None):
    start = datetime(2026, 7, 24, 12, tzinfo=timezone.utc)
    return ParsedFlight("DAL", "MCI", start, start + timedelta(hours=2),
                        flight_number=number, pnr=pnr, pnr_aliases=aliases or [])


def identify(flights, text="", html="", user="Alex Jordan Avery"):
    apply_passenger_identity(flights, html=html, plain_text=text, user_name=user, aliases=[])


@pytest.mark.parametrize("heading", ["Passenger Info", "Passengers Info:", "Traveler Info", "Traveller Info"])
@pytest.mark.parametrize("mode", ["plain", "html"])
@pytest.mark.parametrize("name,ownership", [("Alex Jordan Avery", "self"), ("Alex Casey Avery", "other")])
def test_info_section_with_explicit_name_column_is_a_named_roster(heading, mode, name, ownership):
    f = leg("BOOK01", "DL345")
    text = f"Confirmation code: BOOK01\n{heading}\nNAME\n{name}\nFLIGHT\nSEAT\nDELTA 345\nSeat assigned after check-in\nPayment\nAlex Jordan Avery"
    identify([f], text if mode == "plain" else "", "<p>" + text.replace("\n", "</p><p>") + "</p>" if mode == "html" else "")
    assert f.passenger_names == [name]
    assert f.ownership == ownership
    assert all(p["scope"] == {"pnr": "BOOK01"} and p["complete"] is True for p in f.passenger_evidence)


@pytest.mark.parametrize("text", [
    "Passenger Info\nAlex Jordan Avery\nFlight DL345",
    "Passenger info is available\nNAME\nAlex Jordan Avery",
    "Passenger Info: Alex Jordan Avery",
    "Passenger Info\nBilling contact\nNAME\nAlex Jordan Avery",
    "Passenger: Info\nFlight DL345",
    "Passenger Info\nNAME\nPayment\nAlex Jordan Avery",
])
def test_info_section_requires_adjacent_explicit_name_column_and_no_prose(text):
    f = leg()
    identify([f], "Confirmation code: BOOK01\n" + text)
    assert f.passenger_names == []
    assert f.ownership == "unknown"


def test_info_rosters_keep_booking_scopes_and_hidden_names_out():
    flights = [leg("BOOK01"), leg("OTHER1")]
    text = ("Confirmation code: BOOK01\nPassenger Info\nNAME\nAlex Jordan Avery\nFLIGHT\n"
            "Confirmation code: OTHER1\nPassenger Info\nNAME\nMorgan Blake\nFLIGHT")
    html = "<body><template><p>Passenger Info</p><p>NAME</p><p>Alex Jordan Avery</p></template>"
    html += "<p>" + text.replace("\n", "</p><p>") + "</p></body>"
    identify(flights, html=html)
    assert [(f.ownership, f.passenger_names) for f in flights] == [("self", ["Alex Jordan Avery"]), ("other", ["Morgan Blake"])]


def alaska_legs():
    first = leg("BOOK01", "AS259")
    second = leg("BOOK01", "AS340")
    first.dep_airport, first.arr_airport = "KOA", "SEA"
    second.dep_airport, second.arr_airport = "SEA", "DFW"
    for flight in (first, second):
        flight.source = "shape_alaska_trip_detail_blocks"
    return [first, second]


def alaska_card(sequence, number, route, names):
    return (f"Flight {sequence}\nAS {number}\n{route}\nTraveler(s):\n"
            + "\n".join(f"{name}\n{seat} · Class: Q COACH" for name, seat in names)
            + "\nNext flight\n")


@pytest.mark.parametrize("html", [False, True])
def test_numbered_alaska_cards_keep_companions_in_their_exact_leg(html):
    flights = alaska_legs()
    text = "Confirmation code: BOOK01\n" + alaska_card(1, "259", "KOA SEA", [
        ("Alex Jordan Avery", "18B"), ("Morgan Blake", "18A")])
    text += alaska_card(2, "340", "SEA DFW", [("Taylor Avery", "9A★")])
    text += "Payment information\nPayer Jordan Stone\nContact Avery Jones"
    markup = "<table>" + "".join(f"<tr><td></td><td>{line}</td></tr>" for line in text.splitlines()) + "</table>"
    identify(flights, "" if html else text, markup if html else "")
    assert flights[0].passenger_names == ["Alex Jordan Avery", "Morgan Blake"]
    assert flights[0].ownership == "self"
    assert flights[1].passenger_names == ["Taylor Avery"]
    assert flights[1].ownership == "other"


@pytest.mark.parametrize("broken", ["???\n18A · Class: Q COACH", "999999\nMorgan Blake\n18A · Class: Q COACH"])
def test_alaska_unreadable_or_arbitrary_numbered_rows_do_not_grant_exclusive_manifest(broken):
    flights = alaska_legs()
    text = ("Confirmation code: BOOK01\nFlight 1\nAS 259\nKOA SEA\nTraveler(s):\n"
            "Taylor Avery\n18B · Class: Q COACH\n" + broken + "\nPayment information\nAlex Jordan Avery")
    identify(flights, text)
    assert flights[0].passenger_names == ["Taylor Avery"]
    assert flights[0].ownership == "unknown"
    assert flights[1].passenger_names == []


def test_alaska_card_conflicting_locator_cannot_attach_names():
    flights = alaska_legs()
    text = "Confirmation code: OTHER1\n" + alaska_card(1, "259", "KOA SEA", [("Alex Jordan Avery", "18B")])
    identify(flights, text)
    assert all(f.ownership == "unknown" and not f.passenger_names for f in flights)


def test_alaska_card_cannot_choose_between_conflicting_same_day_candidates():
    from copy import deepcopy
    flights = alaska_legs()[:1]
    alternative = deepcopy(flights[0])
    alternative.dep_time += timedelta(hours=1)
    alternative.arr_time += timedelta(hours=1)
    flights.append(alternative)
    text = "Confirmation code: BOOK01\n" + alaska_card(1, "259", "KOA SEA", [("Alex Jordan Avery", "18B")])
    identify(flights, text)
    assert all(f.ownership == "unknown" and not f.passenger_names for f in flights)


@pytest.mark.parametrize("mode", ["plain", "html"])
@pytest.mark.parametrize("suffix", ["", "CTCE, CTCM"])
@pytest.mark.parametrize("bad_row", ["", "???\n", "999999\n", "Morgan Blake\n"])
def test_alaska_special_information_ends_only_a_completed_named_seat_manifest(mode, suffix, bad_row):
    flights = alaska_legs()[:1]
    text = ("Confirmation code: BOOK01\nFlight 1\nAS259\nKOA SEA\nTraveler(s):\n"
            "Alex Jordan Avery\n18B · Class: Q COACH\n" + bad_row
            + "Special information related to your trip:" + suffix + "\nCTCE, CTCM\nMorgan Payer\n"
              "Summary of airfare charges\nTaylor Cardholder")
    identify(flights, text if mode == "plain" else "", "<p>" + text.replace("\n", "</p><p>") + "</p>" if mode == "html" else "")
    assert flights[0].ownership == "self"
    assert "Morgan Payer" not in flights[0].passenger_names
    assert "Taylor Cardholder" not in flights[0].passenger_names
    assert all(p["complete"] is (not bad_row) for p in flights[0].passenger_evidence if p["applies"])


@pytest.mark.parametrize("heading", ["Special information", "Special information related to your trip: Morgan Blake", "Special information related to your trip"])
def test_alaska_special_information_boundary_is_exact(heading):
    flights = alaska_legs()[:1]
    text = ("Confirmation code: BOOK01\nFlight 1\nAS259\nKOA SEA\nTraveler(s):\n"
            "Alex Jordan Avery\n18B · Class: Q COACH\n" + heading + "\nSummary of airfare charges")
    identify(flights, text)
    assert flights[0].ownership == "self"
    assert all(p["complete"] is False for p in flights[0].passenger_evidence if p["applies"])


@pytest.mark.parametrize("layout", ["horizontal", "vertical", "html"])
@pytest.mark.parametrize("name,ownership", [("Alex Jordan Avery", "self"), ("Alex Casey Avery", "other")])
def test_southwest_passenger_columns_are_not_person_names(layout, name, ownership):
    headers = ["PASSENGER", "RAPID REWARDS #", "TICKET #", "EST. POINTS EARNED"]
    values = [name, "12345678901", "5260000000001", "0"]
    f = leg()
    if layout == "html":
        html = "<p>Confirmation # BOOK01</p><table><tr>" + "".join(f"<th>{v}</th>" for v in headers)
        html += "</tr><tr>" + "".join(f"<td>{v}</td>" for v in values) + "</tr></table><p>Your itinerary</p>"
        identify([f], html=html)
    else:
        sep = " | " if layout == "horizontal" else "\n"
        identify([f], "Confirmation # BOOK01\n" + sep.join(headers) + "\n" + sep.join(values) + "\nYour itinerary")
    assert f.passenger_names == [name]
    assert f.ownership == ownership


def test_alternating_passenger_and_reward_fields_stop_at_metadata():
    f = leg()
    identify([f], "Confirmation # BOOK01\nPASSENGER\nAlex Jordan Avery\nRAPID REWARDS #\n12345678901\nTICKET #\n5260000000001")
    assert f.passenger_names == ["Alex Jordan Avery"]
    assert f.ownership == "self"


@pytest.mark.parametrize("mode", ["plain", "html"])
def test_wrapped_regulatory_refund_clause_is_not_a_passenger(mode):
    f = leg()
    text = ("Confirmation code: BOOK01\nTraveler 1: Alex Jordan Avery\nSeat: 12A\n"
            "seller of travel for services not performed in accordance with the contract\n"
            "between the seller of travel and the passenger will be, unless the\n"
            "passenger otherwise advises the travel promoter in writing, promptly\n"
            "refunded by the seller of travel to the passenger or the party who\n"
            "contracted on behalf of the passenger.")
    identify([f], text if mode == "plain" else "", "<p>" + text.replace("\n", "</p><p>") + "</p>" if mode == "html" else "")
    assert f.passenger_names == ["Alex Jordan Avery"]
    assert f.ownership == "self"


@pytest.mark.parametrize("columns", [False, True])
def test_html_paragraphs_inside_single_or_side_by_side_cells_keep_passenger_label(columns):
    f = leg()
    if columns:
        html = "<p>Confirmation # BOOK01</p><table><tr><td><p>PASSENGER</p><p>RAPID REWARDS #</p><p>TICKET #</p><p>EST. POINTS EARNED</p></td><td><p>Alex Jordan Avery</p><p>12345678901</p><p>5260000000001</p><p>123</p></td></tr></table>"
    else:
        html = "<table><tr><td><p>Confirmation # <strong>BOOK01</strong></p><p>PASSENGER</p><p>Alex Jordan Avery</p></td></tr></table>"
    identify([f], html=html + "<p>Your itinerary</p>")
    assert f.ownership == "self"
    assert f.passenger_names == ["Alex Jordan Avery"]


def test_table_keeps_all_passengers_and_incomplete_manifest_is_not_other():
    f = leg()
    identify([f], "Confirmation # BOOK01\nPASSENGER | RAPID REWARDS # | TICKET #\nMorgan Blake | 11111 | 5260000000001\n??? | 22222 | 5260000000002\nYour itinerary")
    assert f.passenger_names == ["Morgan Blake"]
    assert f.ownership == "unknown"
    shared = leg()
    identify([shared], "Confirmation # BOOK01\nPASSENGER | RAPID REWARDS # | TICKET #\nMorgan Blake | 11111 | 5260000000001\nAlex Jordan Avery | 22222 | 5260000000002\nYour itinerary")
    assert shared.ownership == "self"
    assert set(shared.passenger_names) == {"Morgan Blake", "Alex Jordan Avery"}


def test_allegiant_is_reference_scopes_passengers_to_the_correct_booking():
    flights = [leg("G4BOOK", "G4123"), leg("G4OTHR", "G4124")]
    identify(flights, "Your confirmation number is G4BOOK\nPassenger Name:\nAlex Jordan Avery\nSeat Assignment\n12A\n"
             "Your confirmation number is G4OTHR\nPassenger Name:\nMorgan Blake\nSeat Assignment\n12B")
    assert [(f.passenger_names, f.ownership) for f in flights] == [
        (["Alex Jordan Avery"], "self"), (["Morgan Blake"], "other")]


def test_agency_and_carrier_references_share_only_their_local_manifest():
    flights = [leg("AIR123", "UA123", ["AGY123"]), leg("OTHER1", "NK123", ["AGY456"])]
    text = """Passenger(s):
AVERY/ALEXJORDAN
Expedia Itinerary Number:
12345678901234
United Confirmation Code:
AIR123
Expedia Confirmation Code:
AGY123
Flight Details
Passenger(s):
MORGAN BLAKE
Spirit Confirmation Code:
OTHER1
Expedia Confirmation Code:
AGY456
Flight Details"""
    identify(flights, text)
    assert [(f.passenger_names, f.ownership) for f in flights] == [
        (["AVERY/ALEXJORDAN"], "self"), (["MORGAN BLAKE"], "other")]
    assert all(e["scope"].get("pnr") == f.pnr for f in flights for e in f.passenger_evidence if e["applies"])


def test_unscoped_agency_traveler_does_not_spread_between_booking_families():
    flights = [leg("AIR123", "UA123", ["AGY123"]), leg("OTHER1", "NK123", ["AGY456"])]
    identify(flights, "Traveler(s)\nAlex Jordan Avery\nPrice summary")
    assert [f.ownership for f in flights] == ["unknown", "unknown"]


def test_alaska_schema_provider_and_reservation_id_scope_both_named_legs():
    flights = [leg("ASBOOK", "AS123"), leg("ASBOOK", "AS124")]
    items = [{"@type": "FlightReservation", "reservationId": "ASBOOK", "underName": {"name": "Alex Jordan Avery"},
              "reservationFor": {"flightNumber": str(i), "provider": {"iataCode": "AS"}}} for i in [123, 124]]
    identify(flights, "Confirmation code:\nhttps://tracking.example.test/\nASBOOK",
             '<script type="application/ld+json">' + json.dumps(items) + '</script>')
    assert [f.ownership for f in flights] == ["self", "self"]
    assert all(f.passenger_names == ["Alex Jordan Avery"] for f in flights)


def test_baggage_policy_passenger_categories_do_not_become_named_travelers():
    f = leg("ASBOOK", "AS123")
    identify([f], "Confirmation code: ASBOOK\nTraveler(s):\nAlex Jordan Avery\nSeat: 12A\n"
             "Passenger Type\nFree\nPassengers traveling wholly in the state of Hawaii\nFree\n"
             "Passengers confirmed in First Class\nFree")
    assert f.ownership == "self"
    assert f.passenger_names == ["Alex Jordan Avery"]
