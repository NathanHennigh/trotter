"""Synthetic registrations: retain partial facts without inventing flight legs."""
import base64
from copy import deepcopy
import json

import pytest

from app.services.partial_flight_evidence import extract_partial_flight_evidence


AUTH = "mx.google.com; dkim=pass header.i=@etravel.gov.ph; dmarc=pass header.from=etravel.gov.ph"
TEXT = """Kindly present your passport to the
Immigration Officer
for eTravel registration confirmation and QR Code to
Customs Officer
for clearance.
ALEX JORDAN
Reference Number
PRIVATE-TOKEN
Flight Details
ARRIVAL - VIA AIR
Apr 27,2025
United States of America -> Philippines
Ninoy Aquino International Airport T1 - (MNL) - BR277
WITHOUT BAGGAGE DECLARATION
WITHOUT CURRENCY DECLARATION
*** This is valid only until Apr 28,2025 ***
"""


def source(text=TEXT, html=False):
    if html:
        text = "<html><body>" + "".join(f"<div>{line}</div>" for line in text.splitlines()) + "</body></html>"
    return {"id": "synthetic-source", "payload": {"mimeType": "text/html" if html else "text/plain",
        "headers": [{"name": "From", "value": "eTravel <noreply@mail.etravel.gov.ph>"},
                    {"name": "Subject", "value": "Registration Completed"},
                    {"name": "Authentication-Results", "value": AUTH}],
        "body": {"data": base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")}}}


@pytest.mark.parametrize("html", [False, True])
def test_arrival_retains_only_stated_facts(html):
    msg = source(html=html)
    original = deepcopy(msg)
    value = extract_partial_flight_evidence(msg)
    assert msg == original
    assert value["flight_number"] == "BR277"
    assert value["carrier"] == "BR"
    assert value["local_date"] == "2025-04-27"
    assert value["local_date_role"] == "arrival"
    assert value["known_airport"] == {"code": "MNL", "role": "arrival", "label": "Ninoy Aquino International Airport T1"}
    assert value["traveler_name_as_printed"] == "ALEX JORDAN"
    assert value["journey_countries"] == {"from": "United States of America", "to": "Philippines"}
    assert not value["journey_countries_are_leg_endpoints"]
    assert value["missing_fields"] == ["departure_airport", "departure_time", "arrival_time", "verified_passenger_identity"]
    assert not value["ownership_authority"] and not value["flight_creation_authority"]
    assert len(value["source_sha256"]) == 64
    assert value == extract_partial_flight_evidence(msg)
    assert "PRIVATE-TOKEN" not in json.dumps(value)
    assert "TPE" not in json.dumps(value)


def test_departure_preserves_direction_and_does_not_infer_us_airport():
    text = TEXT.replace("ARRIVAL", "DEPARTURE").replace("Apr 27,2025", "May 9,2025").replace(
        "United States of America -> Philippines", "Philippines -> United States of America").replace("BR277", "BR272")
    value = extract_partial_flight_evidence(source(text))
    assert value["local_date"] == "2025-05-09"
    assert value["local_date_role"] == "departure"
    assert value["known_airport"]["role"] == "departure"
    assert value["missing_fields"][0] == "arrival_airport"
    assert value["flight_number"] == "BR272"
    assert "IAH" not in json.dumps(value)


@pytest.mark.parametrize("header,other", [
    ("From", "eTravel <fake@example.com>"),
    ("From", "eTravel <noreply@mail.etravel.gov.ph>, fake@example.com"),
    ("Subject", "Fwd: Registration Completed"),
    ("Authentication-Results", "sender.example; dkim=pass header.i=@etravel.gov.ph; dmarc=pass header.from=etravel.gov.ph"),
    ("Authentication-Results", AUTH.replace("dkim=pass", "dkim=fail")),
    ("Authentication-Results", AUTH.replace("dmarc=pass", "dmarc=fail")),
    ("Authentication-Results", AUTH.replace("@etravel.gov.ph", "@amazonses.com")),
    ("Authentication-Results", AUTH.replace("header.from=etravel.gov.ph", "header.from=evil.etravel.gov.ph")),
])
def test_requires_exact_original_template_and_aligned_auth(header, other):
    msg = source()
    next(row for row in msg["payload"]["headers"] if row["name"] == header)["value"] = other
    assert extract_partial_flight_evidence(msg) is None


def test_later_authentication_header_cannot_override_first():
    msg = source()
    msg["payload"]["headers"].insert(2, {"name": "Authentication-Results", "value": AUTH.replace("dkim=pass", "dkim=fail")})
    assert extract_partial_flight_evidence(msg) is None


@pytest.mark.parametrize("old,new", [
    ("Apr 27,2025", "Apr 31,2025"), ("ARRIVAL - VIA AIR", "ARRIVAL - VIA SEA"),
    ("(MNL)", "(UNKNOWN)"), ("BR277", "BR0"), ("BR277", "12277"),
    ("Reference Number", "Booking code"), ("ALEX JORDAN", "ALEX 12345"),
    ("United States of America -> Philippines", "United States of America / Philippines"),
    ("Flight Details", "Flight Details\nFlight Details"),
])
def test_malformed_or_ambiguous_claims_not_promoted(old, new):
    assert extract_partial_flight_evidence(source(TEXT.replace(old, new))) is None


def test_conflicting_multipart_claims_not_combined():
    msg = source()
    msg["payload"]["mimeType"] = "multipart/alternative"
    msg["payload"].pop("body")
    msg["payload"]["parts"] = [source()["payload"], source(TEXT.replace("BR277", "BR272"))["payload"]]
    assert extract_partial_flight_evidence(msg) is None


def test_identical_multipart_alternatives_are_one_claim():
    msg = source()
    msg["payload"]["mimeType"] = "multipart/alternative"
    msg["payload"].pop("body")
    msg["payload"]["parts"] = [source()["payload"], source(html=True)["payload"]]
    assert extract_partial_flight_evidence(msg)["flight_number"] == "BR277"


@pytest.mark.parametrize("wrapper", ["<blockquote>{}</blockquote>", '<div class="gmail_quote">{}</div>', "<div>Forwarded message</div>{}"])
def test_forwarded_or_quoted_body_is_not_original(wrapper):
    msg = source(html=True)
    html = base64.urlsafe_b64decode(msg["payload"]["body"]["data"] + "===").decode()
    msg["payload"]["body"]["data"] = base64.urlsafe_b64encode(wrapper.format(html).encode()).decode()
    assert extract_partial_flight_evidence(msg) is None


def test_other_pii_and_hidden_alternative_are_not_extracted():
    msg = source(html=True)
    html = base64.urlsafe_b64decode(msg["payload"]["body"]["data"] + "===").decode()
    html += '<div hidden>Flight Details BR272 Passport: SECRET-PASSPORT DOB: SECRET-DOB</div><img src="https://example.com/qr?token=SECRET-QR">'
    msg["payload"]["body"]["data"] = base64.urlsafe_b64encode(html.encode()).decode()
    value = extract_partial_flight_evidence(msg)
    assert value["flight_number"] == "BR277"
    assert not any(word in json.dumps(value) for word in ["SECRET", "PRIVATE-TOKEN", "https:", "DOB", "Passport"])


def test_multiline_html_tag_end_is_not_a_quoted_email():
    msg = source(html=True)
    html = base64.urlsafe_b64decode(msg["payload"]["body"]["data"] + "===").decode()
    html = html.replace("<div>", '<div\n class="row"\n>')
    msg["payload"]["body"]["data"] = base64.urlsafe_b64encode(html.encode()).decode()
    assert extract_partial_flight_evidence(msg)["flight_number"] == "BR277"


def test_source_hash_changes_with_original_content():
    a = extract_partial_flight_evidence(source())
    b = extract_partial_flight_evidence(source(TEXT.replace("PRIVATE-TOKEN", "OTHER-TOKEN")))
    assert a["source_sha256"] != b["source_sha256"]
    assert {k:v for k,v in a.items() if k != "source_sha256"} == {k:v for k,v in b.items() if k != "source_sha256"}


@pytest.mark.parametrize("field,value", [
    ("labelIds", ["INBOX", "UNREAD"]), ("historyId", "12345"),
    ("snippet", "A different Gmail preview"), ("_trotter_documents", [{"text": "local extraction cache"}]),
])
def test_mutable_mailbox_and_local_cache_fields_do_not_change_source_hash(field, value):
    msg = source()
    original = extract_partial_flight_evidence(msg)
    msg[field] = value
    assert extract_partial_flight_evidence(msg) == original


@pytest.mark.parametrize("field,value", [("id", "another-original"), ("internalDate", "1745712000000")])
def test_original_message_identity_and_timestamp_are_bound(field, value):
    msg = source()
    original = extract_partial_flight_evidence(msg)
    msg[field] = value
    assert extract_partial_flight_evidence(msg)["source_sha256"] != original["source_sha256"]


@pytest.mark.parametrize("msg", [None, {}, {"payload": []}])
def test_invalid_payload_is_safe(msg):
    assert extract_partial_flight_evidence(msg) is None


def test_bad_base64_and_oversized_payloads_are_bounded():
    msg = source()
    msg["payload"]["body"]["data"] = "?not-base64?"
    assert extract_partial_flight_evidence(msg) is None
    msg["payload"]["body"]["data"] = "A" * 1_000_001
    assert extract_partial_flight_evidence(msg) is None


def test_new_template_fields_need_explicit_support():
    msg = source(TEXT.replace("WITHOUT BAGGAGE DECLARATION", "Arrival: 10:00\nWITHOUT BAGGAGE DECLARATION"))
    assert extract_partial_flight_evidence(msg) is None


def test_invalid_mime_body_is_safe():
    msg = source()
    msg["payload"]["body"] = ["invalid"]
    assert extract_partial_flight_evidence(msg) is None
