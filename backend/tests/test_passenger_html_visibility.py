"""A malformed email head may contain its visible body, never an inert roster."""
from datetime import datetime, timedelta, timezone
import json

import pytest

from app.services.parser import ParsedFlight
from app.services.passenger_identity import apply_passenger_identity


def leg(pnr="ABC123", number="WN123"):
    departure = datetime(2027, 2, 10, 15, tzinfo=timezone.utc)
    return ParsedFlight("DAL", "LGA", departure, departure + timedelta(hours=3),
                        airline="WN", flight_number=number, pnr=pnr)


def roster(name, pnr="ABC123"):
    return (f"<p>Confirmation # {pnr}</p><table><tr><td><p>PASSENGER</p></td>"
            f"<td><p>{name}</p></td></tr></table><h2>Your itinerary</h2>")


def identify(html, *, user="Alex Casey Avery", flights=None):
    flights = flights or [leg()]
    apply_passenger_identity(flights, html=html, plain_text="", user_name=user, aliases=[])
    return flights


@pytest.mark.parametrize("name", ["Alex Avery", "Alex Casey Avery", "Alex C Avery"])
@pytest.mark.parametrize("close_head", [True, False])
def test_named_passenger_table_survives_explicit_body_in_malformed_head(name, close_head):
    html = "<html><head><title>Flight receipt</title>" + ("</head>" if close_head else "")
    html += "<body>" + roster(name) + "</body></html>"
    result = identify(html, flights=[leg(), leg(number="WN456")])
    assert [item.ownership for item in result] == ["self", "self"]
    assert all(item.passenger_names == [name] for item in result)
    assert all(all(proof['scope'] == {'pnr': 'ABC123'} for proof in item.passenger_evidence)
               for item in result)


@pytest.mark.parametrize("name", ["Morgan Avery", "Alex Jordan Avery", "Al Casey Avery"])
def test_visible_other_passenger_never_matches_greeting_or_conflicting_name(name):
    result = identify("<html><head><body><p>Hi Alex Casey,</p>" + roster(name) + "</body></html>")[0]
    assert result.passenger_names == [name]
    assert result.ownership == "other"


@pytest.mark.parametrize("hidden_roster", [
    "<head><title>Passenger: Alex Casey Avery</title></head>",
    "<head><meta name='passenger' content='Alex Casey Avery'></head>",
    "<head><script>var fragment='<body>Passenger: Alex Casey Avery</body>';</script></head>",
    "<head><style>.example { content: 'Passenger: Alex Casey Avery'; }</style></head>",
    "<head><template><body>" + roster("Alex Casey Avery") + "</body></template></head>",
    "<head><noscript><body>" + roster("Alex Casey Avery") + "</body></noscript></head>",
    "<body><template>" + roster("Alex Casey Avery") + "</template></body>",
    "<body hidden>" + roster("Alex Casey Avery") + "</body>",
    "<head style='display:none'><body>" + roster("Alex Casey Avery") + "</body></head>",
    "<body><div aria-hidden='true'>" + roster("Alex Casey Avery") + "</div></body>",
])
def test_inert_head_template_or_hidden_roster_is_not_promoted(hidden_roster):
    result = identify("<html>" + hidden_roster + "</html>")[0]
    assert result.ownership == "unknown"
    assert result.passenger_names == []
    assert result.passenger_evidence == []


def test_explicit_body_greeting_and_payer_remain_unknown():
    result = identify("<html><head><body><p>Hi Alex Casey Avery</p>"
                      "<p>Billing contact: Alex Casey Avery</p></body></html>")[0]
    assert result.ownership == "unknown"
    assert result.passenger_names == []


def test_hidden_self_cannot_override_visible_other():
    html = ("<html><head><body><template>" + roster("Alex Casey Avery") + "</template>"
            + roster("Morgan Avery") + "</body></html>")
    result = identify(html)[0]
    assert result.ownership == "other"
    assert result.passenger_names == ["Morgan Avery"]


def test_rescued_body_preserves_booking_scopes():
    html = ("<html><head><body>" + roster("Morgan Avery", "OTH456")
            + roster("Alex Casey Avery", "ABC123") + "</body></html>")
    result = identify(html, flights=[leg("OTH456"), leg("ABC123", "WN456")])
    assert [(item.pnr, item.ownership, item.passenger_names) for item in result] == [
        ("OTH456", "other", ["Morgan Avery"]), ("ABC123", "self", ["Alex Casey Avery"])]


def structured_self():
    item = {"@type": "FlightReservation", "reservationNumber": "ABC123",
            "underName": {"@type": "Person", "name": "Alex Casey Avery"},
            "reservationFor": {"@type": "Flight", "flightNumber": "123",
                               "airline": {"iataCode": "WN"}}}
    return '<script type="application/ld+json">' + json.dumps(item) + '</script>'


@pytest.mark.parametrize("container", ["head", "body"])
def test_normal_structured_reservation_name_is_preserved(container):
    result = identify(f"<html><{container}>" + structured_self() + f"</{container}></html>")[0]
    assert result.ownership == "self"
    assert result.passenger_names == ["Alex Casey Avery"]


@pytest.mark.parametrize("prefix,suffix", [
    ("<body><template>", "</template></body>"),
    ("<body><noscript>", "</noscript></body>"),
    ("<body><svg>", "</svg></body>"),
    ("<body><div hidden>", "</div></body>"),
    ("<html hidden><head>", "</head><body></body></html>"),
    ("<body><div style='display:none'>", "</div></body>"),
    ("<body><div aria-hidden='true'>", "</div></body>"),
])
def test_inert_structured_name_cannot_override_visible_other(prefix, suffix):
    result = identify(prefix + structured_self() + suffix + roster("Morgan Avery"))[0]
    assert result.ownership == "other"
    assert result.passenger_names == ["Morgan Avery"]


def test_explicitly_hidden_structured_script_has_no_identity_authority():
    html = structured_self().replace('<script ', '<script hidden ')
    result = identify(html)[0]
    assert result.ownership == "unknown" and result.passenger_names == []
