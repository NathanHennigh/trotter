"""Per-leg chronology and document-local identity, using anonymized templates."""
from datetime import datetime, timezone
from copy import deepcopy
from datetime import timedelta

import pytest

from app.services.flight_times import normalize_flight_times
from app.services.parser import (
    _document_leg_pointer, _shape_numbered_flight_cards,
    _shape_ota_multi_confirmation, _better_flight, parse_email,
)


OTA = """Your confirmation codes
EVA Air
TEST01
Travel Portal
PORTAL1
Outbound to Manila
Economy Cabin
April 26, 2025
1d 3h 25m
1 stop
EVA Air - BR51
Houston
IAH
1:00 a.m.
16h 30m
Taipei
TPE
6:30 a.m.
This flight arrives the next day.
8h 35m layover in Taipei
EVA Air - BR277
Taipei
TPE
3:05 p.m.
2h 20m
Manila
MNL
5:25 p.m.
This trip includes a long layover.
Return to Houston
Economy Cabin
May 09, 2025
22h 40m
1 stop
EVA Air - BR272
Manila
MNL
12:40 p.m.
2h 15m
Taipei
TPE
2:55 p.m.
6h 25m layover in Taipei
EVA Air - BR52
Taipei
TPE
9:20 p.m.
14h
Houston
IAH
10:20 p.m.
This trip includes a long layover.
Fare Details
Alex Avery
Base Fare: $100.00
Taxes and Fees: $20.00
Ticket #: 6950000000001
Jordan Avery
Base Fare: $100.00
Taxes and Fees: $20.00
Ticket #: 6950000000002
Total US$240.00
Payment Info
"""


def shape(text):
    return _shape_ota_multi_confirmation(text, fallback_pnr=None,
        received_at=datetime(2025, 1, 13, tzinfo=timezone.utc))


def legs(text=OTA):
    return {flight.flight_number: flight for flight in shape(text)}


@pytest.mark.parametrize("changed", [False, True])
def test_next_day_connection_and_return_have_their_own_proven_dates(changed):
    text = OTA.replace("8h 35m", "8h 45m").replace("3:05 p.m.", "3:15 p.m.").replace("5:25 p.m.", "5:35 p.m.") if changed else OTA
    flights = legs(text)
    assert list(flights) == ["BR51", "BR277", "BR272", "BR52"]
    expected = [("2025-04-26", "IAH", "TPE"), ("2025-04-27", "TPE", "MNL"),
                ("2025-05-09", "MNL", "TPE"), ("2025-05-09", "TPE", "IAH")]
    for flight, (day, origin, destination) in zip(flights.values(), expected):
        normalize_flight_times(flight)
        assert flight.time_provenance["status"] == "normalized"
        assert (flight.time_provenance["departure_local_date"], flight.dep_airport, flight.arr_airport) == (day, origin, destination)
    departure = flights["BR277"].time_provenance["date_evidence"]["departure_evidence"]
    assert departure["layover_minutes"] == (525 if changed else 515)
    assert departure["previous_leg_key"] == flights["BR51"].source_leg["key"]


def test_public_parse_preserves_passenger_scope_and_all_four_legs():
    result = parse_email(html="", plain_text=OTA, attachments=[], user_name="Alex Avery", aliases=[],
        received_at=datetime(2025, 1, 13, tzinfo=timezone.utc), subject="Your travel receipt")
    assert len(result.flights) == 4
    assert all(f.ownership == "self" and f.pnr == "TEST01" for f in result.flights)
    assert next(f for f in result.flights if f.flight_number == "BR277").time_provenance["departure_local_date"] == "2025-04-27"


@pytest.mark.parametrize("label", ["Here's your EVA Air confirmation code:", "Here’s your EVA Air confirmation code:", "Your EVA Air confirmation code:"])
def test_labeled_carrier_reference_supports_same_layout_without_code_table(label):
    text = OTA.replace("Your confirmation codes\nEVA Air\nTEST01\nTravel Portal\nPORTAL1\n", "")
    text += "\n" + label + "\nTEST01"
    assert len(shape(text)) == 4
    assert legs(text)["BR277"].dep_time.date().isoformat() == "2025-04-27"


@pytest.mark.parametrize("change", [
    ("8h 35m layover in Taipei", "8h 45m layover in Taipei"),
    ("8h 35m layover in Taipei", "8h 35m layover in Manila"),
    ("8h 35m layover in Taipei", ""),
    ("8h 35m layover in Taipei", "8h 35m total journey duration"),
    ("8h 35m layover in Taipei", "8h 35m layover in Taipei\n8h 35m layover in Taipei"),
    ("16h 30m", "17h 30m"),
])
def test_unproven_connection_does_not_activate_a_guessed_date(change):
    values = legs(OTA.replace(*change))
    connection = values.get("BR277")
    assert connection is None or getattr(connection, "force_review", False)


def test_heading_near_connection_cannot_override_proven_next_day_arrival():
    compact = "\n".join(line for line in OTA.splitlines() if line not in {"Houston", "Taipei", "Manila"})
    assert legs(compact)["BR277"].dep_time.date().isoformat() == "2025-04-27"
    bad = legs(compact.replace("8h 35m layover in Taipei", "8h 45m layover in Taipei"))["BR277"]
    assert bad.force_review
    assert bad.time_provenance["date_evidence"]["reason"] == "unresolved_connection_date"


def test_explicit_new_heading_is_not_overridden_by_previous_connection():
    text = OTA.replace("EVA Air - BR277", "Return to Manila\nMay 01, 2025\nEVA Air - BR277")
    assert legs(text)["BR277"].dep_time.date().isoformat() == "2025-05-01"


def test_overnight_layover_resolves_the_following_local_day():
    text = OTA.replace("8h 35m layover", "25h 35m layover").replace("3:05 p.m.", "8:05 a.m.").replace("5:25 p.m.", "10:25 a.m.")
    assert legs(text)["BR277"].dep_time.isoformat() == "2025-04-28T08:05:00+00:00"


def test_source_pointer_is_independent_of_parsed_values_and_unrelated_prose():
    original = legs()["BR277"]
    again = legs(OTA.replace("Outbound to Manila", "An unrelated heading\nOutbound to Manila"))["BR277"]
    assert original.source_leg["key"] == again.source_leg["key"]
    assert original.source_leg["key"] != legs()["BR51"].source_leg["key"]
    assert len(original.source_leg["key"]) == 64 and not original.source_leg["ambiguous"]
    assert _document_leg_pointer(["Flight 2", "IAH"], template="test", sequence=1)["key"] == _document_leg_pointer(["Flight 2", "IAH"], template="test", sequence=2)["key"]


NUMBERED = """Flight 1 of 2 UA677
Class: Economy
Sun, Dec 15, 2024
Sun, Dec 15, 2024
7:30 AM
11:25 AM
Houston (IAH)
Washington (DCA)
Flight 2 of 2 UA2275
Class: Economy
Thu, Dec 19, 2024
Fri, Dec 20, 2024
10:24 PM
1:00 AM
Dulles (IAD)
Houston (IAH)
"""


def test_numbered_cards_keep_per_leg_printed_dates_and_unique_pointers():
    flights = _shape_numbered_flight_cards(NUMBERED, pnr="TEST01")
    assert [f.dep_time.date().isoformat() for f in flights] == ["2024-12-15", "2024-12-19"]
    assert flights[1].arr_time.date().isoformat() == "2024-12-20"
    assert len({f.source_leg["key"] for f in flights}) == 2


def test_identical_representations_of_the_same_source_leg_remain_usable():
    flights = _shape_numbered_flight_cards(NUMBERED + NUMBERED, pnr="TEST01")
    assert len(flights) == 4
    assert not any(f.source_leg["ambiguous"] for f in flights)
    assert flights[0].source_leg["key"] == flights[2].source_leg["key"]


def test_same_raw_leg_block_under_different_date_headings_is_ambiguous():
    text = """Your confirmation codes
ANA
TEST01
Return to Houston
October 03, 2025
ANA - NH6450
Tokyo
NRT
5:00 p.m.
11h 55m
Houston
IAH
2:55 p.m.
"""
    flights = shape(text + text[text.index("Return to Houston"):].replace("October 03", "October 04"))
    assert len(flights) == 2
    assert flights[0].source_leg["key"] == flights[1].source_leg["key"]
    assert all(f.source_leg["ambiguous"] for f in flights)


@pytest.mark.parametrize("body", [OTA, NUMBERED + "\nPassenger: Alex Avery\nConfirmation: TEST01"])
def test_worker_preparation_keeps_plain_html_and_compact_copies_unambiguous(body):
    import base64
    import html
    from app.services.flight_message import prepare_flight_message

    def part(kind, value):
        return {"mimeType": kind, "body": {"data": base64.urlsafe_b64encode(value.encode()).decode()}}

    message = {"id": "same-source", "internalDate": "1735689600000", "payload": {
        "mimeType": "multipart/alternative", "headers": [
            {"name": "Subject", "value": "Your flight itinerary and receipt"},
            {"name": "From", "value": "Travel <receipts@example.test>"},
            {"name": "Date", "value": "Wed, 1 Jan 2025 00:00:00 +0000"}],
        "parts": [part("text/plain", body), part("text/html", "<div>" + "".join(
            "<p>" + html.escape(line) + "</p>" for line in body.splitlines()) + "</div>")]}}
    prepared = prepare_flight_message(message, user_name="Alex Avery", aliases=[], force_parse=True)
    flights = [f for f in prepared["parse_result"].flights if f.source_leg]
    assert flights
    assert not any(f.source_leg["ambiguous"] for f in flights)


def duplicate_copies():
    complete = legs()["BR51"]
    partial = deepcopy(complete)
    partial.arr_time -= timedelta(days=1)
    partial.force_review = True
    partial.time_provenance = {"date_evidence": {"kind": "flight_endpoint_scope",
        "status": "needs_review", "reason": "flight_endpoint_crosses_next_flight"}}
    return complete, partial


@pytest.mark.parametrize("reverse", [False, True])
def test_verified_overnight_copy_wins_over_exact_held_endpoint_copy_in_both_orders(reverse):
    complete, partial = duplicate_copies()
    copies = [complete, partial] if reverse else [partial, complete]
    assert _better_flight(*copies) is complete
    normalize_flight_times(complete)
    assert complete.time_provenance["status"] == "normalized"
    assert complete.arr_time.isoformat() == "2025-04-26T22:30:00+00:00"


@pytest.mark.parametrize("field,value", [
    ("pnr", "OTHER1"), ("pnr", None), ("flight_number", "BR53"),
    ("dep_airport", "DFW"), ("arr_airport", "MNL"),
    ("dep_time", datetime(2025, 4, 26, 2, tzinfo=timezone.utc)),
    ("source", "another_parser"),
])
def test_complete_copy_preference_never_crosses_an_exact_leg_identity(field, value):
    complete, partial = duplicate_copies()
    setattr(complete, field, value)
    # Preserve the pre-existing generic quality rule for all non-exact cases.
    assert _better_flight(partial, complete) is partial


@pytest.mark.parametrize("kind,reason", [
    ("printed_elapsed", "printed_flight_duration_conflict"),
    ("printed_connection", "unresolved_connection_date"),
    ("flight_endpoint_scope", "different_explicit_conflict"),
])
def test_other_explicit_conflicts_are_not_dismissed_as_compact_copy_artifacts(kind, reason):
    complete, partial = duplicate_copies()
    partial.time_provenance["date_evidence"].update(kind=kind, reason=reason)
    assert _better_flight(partial, complete) is partial


def test_complete_candidate_with_its_own_hold_has_no_preference():
    complete, partial = duplicate_copies()
    complete.force_review = True
    assert _better_flight(partial, complete) is partial


def test_preparation_uses_complete_original_when_compact_copy_loses_an_endpoint():
    import base64
    import html
    from app.services.flight_message import prepare_flight_message

    def part(kind, text):
        return {"mimeType": kind, "body": {"data": base64.urlsafe_b64encode(text.encode()).decode()}}

    broken = OTA.replace("Taipei\nTPE\n6:30 a.m.", "Taipei\n6:30 a.m.")
    message = {"id": "two-representations", "internalDate": "1735689600000", "payload": {
        "mimeType": "multipart/alternative", "headers": [{"name": "Subject", "value": "Your flight receipt"}],
        "parts": [part("text/plain", broken), part("text/html", "<div>" + "".join(
            "<p>" + html.escape(line) + "</p>" for line in OTA.splitlines()) + "</div>")]}}
    result = prepare_flight_message(message, user_name="Alex Avery", aliases=[], force_parse=True)["parse_result"]
    outbound, = [f for f in result.flights if f.flight_number == "BR51"]
    assert outbound.time_provenance["status"] == "normalized"
    assert outbound.time_provenance["arrival"]["local"] == "2025-04-27T06:30:00"
    assert not getattr(outbound, "force_review", False)
