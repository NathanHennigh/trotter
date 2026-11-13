"""Unsupported senders do no MIME work; supported partial claims keep all guards."""
import base64
from copy import deepcopy

import pytest

from app.services import partial_flight_evidence as partial


UA = "Flight: UA321 Date: July 31, 2026 From: San Francisco (SFO) To: Orange County (SNA)"


def message(sender="info@united.com", text=UA, html=False):
    return {"id": "domain-gate-fixture", "payload": {
        "headers": [{"name": "From", "value": sender}],
        "mimeType": "text/html" if html else "text/plain",
        "body": {"data": base64.urlsafe_b64encode(text.encode()).decode()}}}


def forbid_bodies(monkeypatch):
    def forbidden(unused):
        raise AssertionError("Unsupported sender reached MIME decoding/HTML parsing")
    monkeypatch.setattr(partial, "_bodies", forbidden)


def spy_bodies(monkeypatch):
    original, calls = partial._bodies, []
    def tracked(payload):
        calls.append(payload)
        return original(payload)
    monkeypatch.setattr(partial, "_bodies", tracked)
    return calls


@pytest.mark.parametrize("sender", ["info@example.org", "info@americanexpress.com",
    "United Airlines <info@example.org>", "info@notunited.com", "info@united.com.example.org",
    "info@notsuncountry.com", "info@suncountry.com.example.org", "info@united.com.",
    "info@suncountry.com.", "Forwarder <person@gmail.com>"])
def test_unsupported_domains_do_not_decode_even_flight_looking_html(monkeypatch, sender):
    forbid_bodies(monkeypatch)
    source = message(sender, "<html><body>" + UA + "</body></html>", html=True)
    before = deepcopy(source)
    assert partial.extract_partial_flight_evidence(source) is None
    assert source == before


@pytest.mark.parametrize("headers", [[], [{"name": "Subject", "value": "Flight"}],
    [{"name": "From", "value": None}], [{"name": "From", "value": 123}],
    [{"name": "From", "value": ""}], [{"name": "From", "value": "not an address"}],
    [{"name": "From", "value": "a@united.com, b@united.com"}],
    [{"name": "From", "value": "a@united.com"}, {"name": "fRoM", "value": "a@united.com"}],
    [{"name": "From", "value": "a@example.org"}, {"name": "From", "value": "a@united.com"}],
    [{"name": "X-Test", "value": "unused"}] * 129, "malformed", {"From": "a@united.com"}])
def test_missing_ambiguous_or_malformed_headers_preserve_no_evidence(monkeypatch, headers):
    forbid_bodies(monkeypatch)
    source = message(); source["payload"]["headers"] = headers
    assert partial.extract_partial_flight_evidence(source) is None


@pytest.mark.parametrize("sender", ["info@united.com", "info@UNITED.COM", "info@enews.united.com",
    "info@a.b.united.com", "info@suncountry.com", "info@SUNCOUNTRY.COM", "info@info.suncountry.com",
    "info@a.b.suncountry.com"])
def test_supported_domain_family_still_enters_existing_body_guards(monkeypatch, sender):
    calls = spy_bodies(monkeypatch)
    value = partial.extract_partial_flight_evidence(message(sender))
    assert len(calls) == 1
    if "united.com" in sender.lower():
        assert value["legs"][0]["flight_number"] == "UA321"
        assert value["flight_creation_authority"] is value["ownership_authority"] is False
    else:
        assert value is None  # A United card never becomes a Sun Country claim.


@pytest.mark.parametrize("text,html", [("Forwarded message\n" + UA, False),
    ("<blockquote>" + UA + "</blockquote>", True),
    ('<div class="gmail_quote">' + UA + "</div>", True)])
def test_supported_forwarded_or_quoted_body_is_still_rejected(monkeypatch, text, html):
    calls = spy_bodies(monkeypatch)
    assert partial.extract_partial_flight_evidence(message(text=text, html=html)) is None
    assert len(calls) == 1


def test_supported_conflicting_alternatives_still_rejected(monkeypatch):
    calls = spy_bodies(monkeypatch)
    source = message()
    source["payload"] = {"headers": source["payload"]["headers"], "mimeType": "multipart/alternative",
        "parts": [message()["payload"], message(text=UA.replace("July 31", "July 30"))["payload"]]}
    assert partial.extract_partial_flight_evidence(source) is None
    assert len(calls) == 1


@pytest.mark.parametrize("body", [{"data": "invalid base64 !"}, "malformed", {"data": 1}])
def test_supported_malformed_body_keeps_existing_rejection(monkeypatch, body):
    calls = spy_bodies(monkeypatch)
    source = message(); source["payload"]["body"] = body
    assert partial.extract_partial_flight_evidence(source) is None
    assert len(calls) == 1


def government_message():
    text = """Kindly present your passport to the Immigration Officer
for eTravel registration confirmation
ALEX JORDAN
Reference Number
SYNTHETIC-REGISTRATION
Flight Details
ARRIVAL - VIA AIR
Apr 27,2025
United States of America -> Philippines
Ninoy Aquino International Airport T1 - (MNL) - BR277
WITHOUT BAGGAGE DECLARATION
WITHOUT CURRENCY DECLARATION
"""
    source = message("eTravel <noreply@mail.etravel.gov.ph>", text)
    source["payload"]["headers"].extend([
        {"name": "Subject", "value": "Registration Completed"},
        {"name": "Authentication-Results", "value": "mx.google.com; dkim=pass header.i=@etravel.gov.ph; dmarc=pass header.from=etravel.gov.ph"}])
    return source


def test_authenticated_etravel_fallback_keeps_evidence_with_one_body_parse(monkeypatch):
    calls = spy_bodies(monkeypatch)
    source = government_message(); before = deepcopy(source)
    value = partial.extract_partial_flight_evidence(source)
    assert len(calls) == 1 and source == before
    assert value["kind"] == "government_travel_registration" and value["flight_number"] == "BR277"
    assert value["known_airport"]["code"] == "MNL" and value["local_date"] == "2025-04-27"
    assert value["flight_creation_authority"] is value["ownership_authority"] is False
    assert len(value["source_sha256"]) == 64


@pytest.mark.parametrize("field,value", [("Subject", "Fwd: Registration Completed"),
    ("Authentication-Results", "mx.google.com; dkim=fail; dmarc=fail")])
def test_unproven_government_registration_does_no_body_work(monkeypatch, field, value):
    forbid_bodies(monkeypatch)
    source = government_message()
    next(h for h in source["payload"]["headers"] if h["name"] == field)["value"] = value
    assert partial.extract_partial_flight_evidence(source) is None
