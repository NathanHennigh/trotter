import base64
from copy import deepcopy

import pytest

from app.services.partial_flight_evidence import extract_partial_flight_evidence


def message(text, sender="info@enews.united.com"):
    return {"id": "partial-fixture", "payload": {"mimeType": "text/plain",
        "headers": [{"name": "From", "value": sender}],
        "body": {"data": base64.urlsafe_b64encode(text.encode()).decode()}}}


UA = "Flight: UA321 Date: July 31, 2026 From: San Francisco (SFO) To: Orange County (SNA)"
SY = """Trip Details Anchorage, AK to Dallas, TX
SY474, SY501 STOPS 1 (MSP)
8:55PM Anchorage, AK (ANC) July 19, 2025
9h 02m
8:57AM Dallas, TX (DFW) July 20, 2025
All timing information is reflected in local time
Traveler Details Alex Avery
SY474 (ANC-MSP) SY501 (MSP-DFW)
Policy: departures September 3, 2025, 3 hours before departure
"""


def test_numbered_notice_keeps_date_route_without_manufacturing_clocks():
    value = extract_partial_flight_evidence(message(UA))
    assert value["legs"] == [{"flight_number": "UA321", "dep_airport": "SFO", "arr_airport": "SNA",
        "departure_local_date": "2026-07-31", "missing_fields": ["departure_time", "arrival_time", "verified_passenger_identity"]}]
    assert value["ownership_authority"] is value["flight_creation_authority"] is False
    assert extract_partial_flight_evidence(message(UA)) == value


def test_connection_retains_outer_bounds_never_invents_intermediate_clocks():
    value = extract_partial_flight_evidence(message(SY, "suncountry@info.suncountry.com"))
    left, right = value["legs"]
    assert left["flight_number"] == "SY474" and right["flight_number"] == "SY501"
    assert (left["dep_airport"], left["arr_airport"], right["arr_airport"]) == ("ANC", "MSP", "DFW")
    assert left["departure_local_date"] == "2025-07-19" and right["arrival_local_date"] == "2025-07-20"
    assert "arrival_local_time" not in left and "departure_local_time" not in right
    assert not value["flight_creation_authority"]


@pytest.mark.parametrize("text,sender", [(UA, "info@united.com.example.org"),
    ("Forwarded message\n" + UA, "info@united.com"),
    (UA.replace("July 31", "February 31"), "info@united.com"),
    (SY.replace("STOPS 1", "STOPS 2"), "info@suncountry.com")])
def test_unsupported_source_or_structure_does_not_guess(text, sender):
    assert extract_partial_flight_evidence(message(text, sender)) is None


def test_conflicting_multipart_alternatives_are_held_without_combining():
    first, second = message(UA), message(UA.replace("July 31", "July 30"))
    first["payload"] = {"mimeType": "multipart/alternative", "headers": first["payload"]["headers"],
        "parts": [deepcopy(first["payload"]), second["payload"]]}
    assert extract_partial_flight_evidence(first) is None


def test_visible_forwarded_html_without_blockquote_is_not_direct_carrier_evidence():
    value = message("<div>---------- Forwarded message ---------</div><p>" + UA + "</p>")
    value["payload"]["mimeType"] = "text/html"
    assert extract_partial_flight_evidence(value) is None
