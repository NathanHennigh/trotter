"""Synthetic Bilt templates; no copied booking references or private mail."""
from pathlib import Path

import pytest

from app.services.bilt_booking import bilt_confirmation_evidence
from app.services.flight_evidence import assess_flight_evidence
from app.services.parse_audit import assess_parse_miss
from app.tasks.import_tasks import _should_skip_expensive_parse

SUBJECT = "Your flight booking is confirmed!"
SENDER = "Bilt <notifications@members.bilt.com>"
BODY = (Path(__file__).parent / "fixtures/bilt-confirmation-evidence.txt").read_text(encoding="utf-8")


@pytest.mark.parametrize("body", [BODY, "<html><body>" + "".join(f"<div>{line}</div>" for line in BODY.splitlines()) + "</body></html>"])
def test_transactional_bilt_passes_all_import_gates_and_remains_reviewable_if_parser_misses(body):
    evidence = assess_flight_evidence(subject=SUBJECT, sender=SENDER, body=body)
    assert evidence.verdict == "parse"
    assert evidence.airport_codes == ("SFO", "LAX")
    assert evidence.flight_numbers == ("UA1234",)
    assert "transactional_bilt_confirmation" in evidence.signals
    for tier in ["fast_known_senders", "fast_strong_keywords", "fast_bilt_confirmations", "incremental_precise", "initial_broad_recent", "exhaustive_backfill", "stale_reparse"]:
        assert not _should_skip_expensive_parse(tier=tier, prefilter=True, evidence=evidence)
    miss = assess_parse_miss(subject=SUBJECT, sender=SENDER, body=body)
    assert miss.should_review
    assert miss.reason == "strong_flight_evidence_but_no_segments"
    # Recognizing a receipt supplies no passenger or ownership claim.
    assert set(bilt_confirmation_evidence(subject=SUBJECT, sender=SENDER, body=body).__dict__) == {"airport_codes", "flight_numbers"}


@pytest.mark.parametrize("subject,body", [
    ("Your hotel booking is confirmed!", "Hotel reservation QZ8K2M. Check-in Nov 10, 2026. Book flights to SFO and LAX."),
    ("Bilt newsletter: flight deals for your next trip", "Book now and save. UA1234 SFO to LAX on Nov 10. Earn bonus points."),
    ("Bilt newsletter: see a sample flight booking", BODY),
    (SUBJECT, "Explore the Bilt Travel Portal. Book now and earn points on flights and hotels."),
])
def test_bilt_hotel_and_newsletter_do_not_receive_transactional_exception(subject, body):
    assert bilt_confirmation_evidence(subject=subject, sender=SENDER, body=body) is None
    evidence = assess_flight_evidence(subject=subject, sender=SENDER, body=body)
    assert evidence.verdict == "skip"
    assert _should_skip_expensive_parse(tier="fast_strong_keywords", prefilter=True, evidence=evidence)
    assert not assess_parse_miss(subject=subject, sender=SENDER, body=body).should_review


@pytest.mark.parametrize("body", [
    BODY.replace("Airline\nconfirmation\n\nQZ8K2M", "Rewards reference QZ8K2M"),
    BODY.replace("UA1234", "Rewards offer"),
    BODY.replace("LAX", "ZZZ"),
    BODY.replace("10 Nov 2026", "31 Feb 2026"),
    BODY.replace("10:55am", "29:55am"),
])
def test_incomplete_or_invalid_bilt_itinerary_is_not_exempted(body):
    assert bilt_confirmation_evidence(subject=SUBJECT, sender=SENDER, body=body) is None


@pytest.mark.parametrize("sender", ["notifications@members.bilt.com.attacker.example", "offers@members.bilt.com", "Bilt <other@example.com>"])
def test_bilt_exception_requires_exact_transactional_mailbox(sender):
    assert bilt_confirmation_evidence(subject=SUBJECT, sender=sender, body=BODY) is None
