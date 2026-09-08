"""Ownership regressions: finding a route never proves whose journey it is."""

from datetime import datetime, timedelta, timezone
import json

import pytest

from app.models import MessageStatus
from app.services.parser import ParsedFlight, _dedupe_flights, _merge_same_flight_continuations, parse_email
from app.services.passenger_identity import apply_passenger_identity, names_match


USER = "Alex Avery"
OTHER = "Morgan Avery"


def flight(number="F91418", pnr="FRT123", dep="IAH", arr="MCO", day=21):
    start = datetime(2025, 2, day, 16, 16, tzinfo=timezone.utc)
    return ParsedFlight(dep, arr, start, start + timedelta(hours=2), flight_number=number, pnr=pnr)


def identify(flights, text="", html="", user=USER, aliases=None):
    apply_passenger_identity(flights, html=html, plain_text=text, user_name=user, aliases=aliases or [])
    return flights


def reservation(number, pnr, dep, arr, names=None, day=21):
    item = {
        "@type": "FlightReservation", "reservationNumber": pnr,
        "reservationFor": {"@type": "Flight", "flightNumber": number[2:],
            "airline": {"iataCode": number[:2]},
            "departureAirport": {"iataCode": dep}, "arrivalAirport": {"iataCode": arr},
            "departureTime": f"2025-02-{day:02d}T15:00:00Z", "arrivalTime": f"2025-02-{day:02d}T17:40:00Z"},
    }
    if names is not None:
        item["underName"] = [{"@type": "Person", "name": name} for name in names]
    return item


def parse_items(items, text="", user=USER):
    return parse_email(html='<script type="application/ld+json">' + json.dumps(items) + '</script>',
                       plain_text=text, attachments=[], user_name=user, aliases=[])


@pytest.mark.parametrize("passenger,expected", [
    ("ALEX AVERY", True), ("AVERY/ALEX", True), ("Avery, Alex", True),
    ("Mr. Alex Avery", True), ("Alex Jordan Avery", True), ("A Avery", True),
    ("Alex", False), ("Avery", False), ("Morgan Avery", False),
    ("M Avery", False), ("Al Avery", False), ("Alex Avery Jr", False),
])
def test_name_matching_rejects_token_subset_collisions(passenger, expected):
    assert names_match(passenger, USER) is expected


def test_explicit_conflicting_middle_names_do_not_match():
    assert not names_match("Alex Jordan Avery", "Alex Casey Avery")


def test_unicode_names_and_compound_surnames():
    assert names_match("GARCÍA/JOSÉ", "José García")
    assert names_match("Maria de la Cruz", "MARIA DE LA CRUZ")


def test_orlando_frontier_only_morgan_is_other_with_payer_alex():
    result = parse_email(html="", plain_text="""
        Your Flight Confirmation Code FRT123
        Passenger: Morgan Avery
        Payment information
        Paid by: Alex Avery
        DEPARTING FLIGHT 1418 Houston (IAH) to Orlando (MCO)
        Depart: 2/21/2025 4:16 PM | Arrive: 2/21/2025 7:40 PM Total Duration
        """, attachments=[], user_name=USER, aliases=[],
        subject="Your Flight Confirmation Code FRT123", from_email="Frontier Airlines <booking@example.test>")
    assert [(f.flight_number, f.dep_airport, f.arr_airport) for f in result.flights] == [("F91418", "IAH", "MCO")]
    assert result.flights[0].passenger_names == [OTHER]
    assert result.flights[0].ownership == "other"
    assert result.status == MessageStatus.REVIEW_REQUIRED


def test_orlando_jetblue_alex_is_self():
    result = parse_items([reservation("B62023", "JET123", "DCA", "MCO", [USER])])
    assert [(f.flight_number, f.ownership) for f in result.flights] == [("B62023", "self")]
    assert result.status == MessageStatus.ACCEPTED


@pytest.mark.parametrize("names", [[OTHER, USER], [USER, OTHER]])
def test_orlando_shared_spirit_both_legs_are_self_regardless_of_name_order(names):
    result = parse_items([
        reservation("NK1651", "SPR123", "MCO", "ATL", names, day=23),
        reservation("NK512", "SPR123", "ATL", "IAH", names, day=23),
    ])
    assert [(f.flight_number, f.ownership) for f in result.flights] == [("NK1651", "self"), ("NK512", "self")]
    assert all(set(f.passenger_names) == {USER, OTHER} for f in result.flights)


@pytest.mark.parametrize("reverse", [False, True])
def test_mixed_jsonld_message_keeps_each_passengers_own_flight(reverse):
    items = [reservation("F91418", "FRT123", "IAH", "MCO", [OTHER]),
             reservation("B62023", "JET123", "DCA", "MCO", [USER])]
    result = parse_items(list(reversed(items)) if reverse else items)
    assert {f.flight_number: f.ownership for f in result.flights} == {"F91418": "other", "B62023": "self"}
    assert len(result.flights) == 2
    assert result.status == MessageStatus.REVIEW_REQUIRED


def test_mixed_text_bookings_are_associated_per_booking():
    flights = [flight(), flight("B62023", "JET123", "DCA")]
    identify(flights, """Booking reference: FRT123
Passenger: Morgan Avery
Flight F91418 IAH to MCO
Departure: February 21, 2025
Booking reference: JET123
Passenger: Alex Avery
Flight B62023 DCA to MCO
""")
    assert [(f.flight_number, f.passenger_names, f.ownership) for f in flights] == [
        ("F91418", [OTHER], "other"), ("B62023", [USER], "self")]


def test_passengers_in_different_html_table_rows_are_all_preserved():
    f = flight()
    identify([f], html="""<p>Booking reference: FRT123</p><table>
      <tr><th>Passenger Name</th><th>Seat</th></tr>
      <tr><td>Morgan Avery</td><td>12A</td></tr>
      <tr><td>Alex Avery</td><td>12B</td></tr></table>""")
    assert set(f.passenger_names) == {USER, OTHER}
    assert f.ownership == "self"


def test_unscoped_traveler_in_multiple_bookings_is_review_only():
    flights = [flight(), flight("B62023", "JET123", "DCA")]
    identify(flights, "Passengers:\nAlex Avery")
    assert all(f.ownership == "unknown" for f in flights)
    assert all(f.passenger_evidence and not f.passenger_names for f in flights)


@pytest.mark.parametrize("text", [
    "To: Alex Avery\nFrom: Alex Avery\nDear Alex Avery",
    "Billing contact\nName: Alex Avery\nPaid by: Alex Avery",
    "Forwarded message\nTo: Alex Avery\nCustomer: Alex Avery",
    "Passengers:\n", "", "Passenger: Avery", "Passenger: Alex",
])
def test_missing_or_nontraveler_identity_never_establishes_self(text):
    f = flight()
    identify([f], text)
    assert f.ownership == "unknown"


def test_forwarding_does_not_override_explicit_traveler():
    f = flight()
    identify([f], "From: Alex Avery\nTo: Alex Avery\nForwarded message\nPassenger: Morgan Avery")
    assert f.passenger_names == [OTHER]
    assert f.ownership == "other"


def test_incomplete_manifest_cannot_establish_other():
    f = flight()
    identify([f], "Passengers (2):\nMorgan Avery\nTicket details")
    assert f.passenger_names == [OTHER]
    assert f.ownership == "unknown"


def test_no_account_identity_stays_unknown():
    f = flight()
    identify([f], "Passenger: Alex Avery", user="")
    assert f.ownership == "unknown"


def test_saved_alias_matches_without_fuzzy_guessing():
    f = flight()
    identify([f], "Traveler: Al Avery", aliases=["Al Avery"])
    assert f.ownership == "self"


def test_initial_cannot_choose_between_different_explicit_travelers():
    f = flight()
    identify([f], "Passengers:\nA Avery\nAdrian Avery")
    assert f.ownership == "unknown"


def test_jsonld_customer_is_not_passenger():
    item = reservation("B62023", "JET123", "DCA", "MCO")
    item["customer"] = {"name": USER}
    result = parse_items([item])
    assert result.flights[0].ownership == "unknown"


def test_jsonld_flight_without_name_uses_explicit_body_passengers():
    result = parse_items([reservation("B62023", "JET123", "DCA", "MCO")], "Passengers:\nMorgan Avery\nAlex Avery")
    assert result.flights[0].ownership == "self"
    assert set(result.flights[0].passenger_names) == {USER, OTHER}


def test_ics_early_return_still_resolves_body_passengers():
    ics = b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nDTSTART:20250221T150000Z\r\nDTEND:20250221T174000Z\r\nSUMMARY:B62023 DCA to MCO\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
    result = parse_email(html="", plain_text="Passenger: Alex Avery", attachments=[("flight.ics", ics)], user_name=USER, aliases=[])
    assert result.flights and result.source == "ics"
    assert all(f.ownership == "self" for f in result.flights)


def test_dedupe_preserves_both_names_and_distinct_travel_dates():
    a, b, later = flight(), flight(), flight(day=22)
    a.passenger_names, b.passenger_names = [OTHER], [USER]
    a.passenger_evidence = [{"name": OTHER, "source": "test", "complete": True}]
    b.passenger_evidence = [{"name": USER, "source": "test", "complete": True}]
    result = _dedupe_flights([a, b, later])
    assert len(result) == 2
    assert set(result[0].passenger_names) == {USER, OTHER}
    assert len(result[0].passenger_evidence) == 2


def test_continuation_keeps_different_passengers_separate():
    a, b = flight(), flight(dep="MCO", arr="ATL")
    b.dep_time = a.arr_time + timedelta(hours=1)
    b.arr_time = b.dep_time + timedelta(hours=1)
    for f, name in ((a, USER), (b, OTHER)):
        f.passenger_names = [name]
        f.passenger_evidence = [{"name": name, "source": "test"}]
    merged = _merge_same_flight_continuations([a, b])
    assert len(merged) == 2
    assert {name for f in merged for name in f.passenger_names} == {USER, OTHER}
    assert sum(len(f.passenger_evidence) for f in merged) == 2


def test_same_physical_flight_different_bookings_preserves_both_observations():
    assert len(_dedupe_flights([flight(pnr="OTHER1"), flight(pnr="MYBOOK")])) == 2


def test_frontier_indexed_manifest_with_loyalty_copy():
    f = flight()
    identify([f], """Confirmation Code: FRT123
PASSENGERS | Subtotal: $0.00
ADULT(S)
1- Morgan Blake Not a FRONTIER Miles sm Member? Sign Up!
BUNDLES
""")
    assert f.passenger_names == ["Morgan Blake"]
    assert f.ownership == "other"


def test_spirit_guest_manifest_excludes_contact_and_baggage_sections():
    f = flight("NK1651", "SPR123", "MCO", "ATL", day=23)
    identify([f], html="""<p>Confirmation: SPR123</p><h2>GUEST INFORMATION</h2><table>
      <tr><th>NAME</th><th>ASSISTANCE</th><th>FREE SPIRIT #</th></tr>
      <tr><td>Morgan Taylor Blake</td><td>None</td><td></td></tr>
      <tr><td>Alex Avery</td><td>None</td><td></td></tr></table>
      <h2>CONTACT INFORMATION</h2><p>Someone Else | billing@example.test</p>""")
    assert f.ownership == "self"
    assert set(f.passenger_names) == {"Morgan Taylor Blake", USER}


def test_agency_combined_fare_ticket_holder_applies_to_both_listed_bookings():
    flights = [flight("UA1540", "UNI123", "IAH", "DCA", day=18), flight("B62023", "JET123", "DCA", "MCO")]
    identify(flights, """Your confirmation codes
United | UNI123
JetBlue | JET123
Fare Details
Alex Avery
Base Fare: | $200
Taxes and Fees: | $40
Ticket #: 0160000000001, 2790000000002
Total | $240
Payment Info
Card Holder: Someone Else
""")
    assert [f.ownership for f in flights] == ["self", "self"]
    assert all(f.passenger_names == [USER] for f in flights)


def test_agency_payer_cannot_substitute_for_missing_ticket_holder():
    f = flight()
    identify([f], "Fare Details\nBase Fare: $100\nTicket #: 0160000000001\nPayment Info\nAlex Avery")
    assert f.ownership == "unknown"


def test_ambiguous_ticket_holder_across_unlisted_bookings_stays_unknown():
    flights = [flight(), flight("B62023", "JET123", "DCA")]
    identify(flights, "Fare Details\nAlex Avery\nTicket #: 0160000000001\nPayment Info")
    assert all(f.ownership == "unknown" for f in flights)


def test_side_by_side_passengers_and_partially_unreadable_manifest():
    f = flight()
    identify([f], "Passengers: Morgan Blake | Alex Avery")
    assert f.ownership == "self"
    unknown = flight()
    identify([unknown], "Passengers: Morgan Blake; ???")
    assert unknown.ownership == "unknown"


@pytest.mark.parametrize("reference", ["United\nCAN123", "United | CAN123", "United CAN123"])
def test_canceled_airline_reference_is_attached_without_using_agency_code(reference):
    result = parse_items([reservation("UA1685", "", "IAH", "DCA")],
                         "Canceled\n" + reference + "\nCapital One Travel\nH-BOOK02\nManage Your Trip")
    assert result.flights[0].pnr == "CAN123"
    assert result.flights[0].ownership == "unknown"


def test_conflicting_airline_codes_are_not_guessed_for_cancellation():
    result = parse_items([reservation("UA1685", "", "IAH", "DCA")],
                         "Canceled\nUnited\nCAN123\nUnited\nOTH123\nManage Your Trip")
    assert result.flights[0].pnr is None
