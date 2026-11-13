"""The Bilt optimization must skip only unused HTML serialization."""
from email.utils import parseaddr
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from app.services.bilt_booking import is_bilt_confirmation_metadata
from app.services.flight_evidence import assess_flight_evidence


SUBJECT = "Your flight booking is confirmed!"
SENDER = "Bilt <notifications@members.bilt.com>"
BODY = (Path(__file__).parent / "fixtures/bilt-confirmation-evidence.txt").read_text(encoding="utf8")
HTML = "<html><body>" + "".join(f"<div>{line}</div>" for line in BODY.splitlines()) + "</body></html>"


@pytest.mark.parametrize("sender,subject,expected", [
    (SENDER, SUBJECT, True),
    ('"Bilt Rewards" <notifications@members.bilt.com>', SUBJECT, True),
    ("NOTIFICATIONS@MEMBERS.BILT.COM", "  YOUR  FLIGHT booking is confirmed ", True),
    ("notifications@members.bilt.com.attacker.example", SUBJECT, False),
    ('"notifications@members.bilt.com" <other@example.com>', SUBJECT, False),
    ("offers@members.bilt.com", SUBJECT, False),
    (SENDER, "Fwd: " + SUBJECT, False),
    (SENDER, '"' + SUBJECT + '"', False),
    (SENDER, "Your hotel booking is confirmed!", False),
    ("", SUBJECT, False),
    (None, SUBJECT, False),
    (SENDER, None, False),
])
def test_metadata_predicate_retains_exact_existing_mailbox_and_subject(sender, subject, expected):
    assert is_bilt_confirmation_metadata(subject=subject, sender=sender) is expected


@pytest.mark.parametrize("sender", [
    "Bilt <notifications@members.bilt.com",
    "Bilt <notifications@members.bilt.com>, Other <other@example.com>",
    "not an address",
    "Bilt <notifications@members.bilt.com>\r\nX-Extra: arbitrary",
])
def test_malformed_headers_preserve_existing_standard_library_parseaddr_semantics(sender):
    # Python releases differ in malformed-address strictness. The optimization
    # must preserve the adapter's existing parseaddr contract on each release.
    expected = parseaddr(sender)[1].lower() == "notifications@members.bilt.com"
    assert is_bilt_confirmation_metadata(subject=SUBJECT, sender=sender) is expected


@pytest.mark.parametrize("sender,subject", [
    ("Updates <updates@example.com>", "Account news"),
    ("notifications@members.bilt.com.attacker.example", SUBJECT),
    ("Bilt <other@example.com>", SUBJECT),
    ("offers@members.bilt.com", SUBJECT),
    (SENDER, "Fwd: " + SUBJECT),
    (SENDER, '"' + SUBJECT + '"'),
    (SENDER, "Your hotel booking is confirmed!"),
    ("", SUBJECT),
])
def test_nonmatching_metadata_does_not_serialize_soup_but_visible_safety_remains(monkeypatch, sender, subject):
    def forbidden_serialization(*unused, **kwargs):
        raise AssertionError("Nonmatching Bilt metadata must not serialize sanitized HTML")

    monkeypatch.setattr(BeautifulSoup, "__str__", forbidden_serialization)
    html = '<html><body><div hidden>' + HTML + '</div><p>Account news only.</p></body></html>'
    evidence = assess_flight_evidence(subject=subject, sender=sender, body=html)
    assert "transactional_bilt_confirmation" not in evidence.signals
    assert evidence.airport_codes == ()
    assert evidence.flight_numbers == ()


@pytest.mark.parametrize("hidden_markup", [
    '<div hidden>DO_NOT_USE</div>',
    '<div aria-hidden="true">DO_NOT_USE</div>',
    '<div style="display:none">DO_NOT_USE</div>',
    '<template>DO_NOT_USE</template>',
    '<script>DO_NOT_USE</script>',
])
def test_exact_bilt_still_receives_sanitized_structural_html(monkeypatch, hidden_markup):
    original = BeautifulSoup.__str__
    serialized = []

    def record_serialization(soup, *args, **kwargs):
        value = original(soup, *args, **kwargs)
        serialized.append(value)
        return value

    monkeypatch.setattr(BeautifulSoup, "__str__", record_serialization)
    evidence = assess_flight_evidence(subject=SUBJECT, sender=SENDER, body=HTML + hidden_markup)
    assert evidence.verdict == "parse"
    assert "transactional_bilt_confirmation" in evidence.signals
    assert evidence.airport_codes == ("SFO", "LAX")
    assert evidence.flight_numbers == ("UA1234",)
    assert serialized and all("DO_NOT_USE" not in value for value in serialized)


@pytest.mark.parametrize("body", [
    "<html><body>Book a hotel and earn rewards.</body></html>",
    "<html><body><div hidden>" + HTML + "</div>Account news.</body></html>",
    "<html><body><template>" + HTML + "</template>Account news.</body></html>",
])
def test_matching_metadata_alone_does_not_admit_nonbooking_or_hidden_flights(body):
    evidence = assess_flight_evidence(subject=SUBJECT, sender=SENDER, body=body)
    assert "transactional_bilt_confirmation" not in evidence.signals
    assert evidence.airport_codes == ()
    assert evidence.flight_numbers == ()
