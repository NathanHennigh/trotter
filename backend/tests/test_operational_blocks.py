import pytest

from app.services.flight_evidence import assess_flight_evidence
from app.tasks.import_tasks import _should_skip_expensive_parse


@pytest.mark.parametrize("body", [
    "Flight: UA321 Date: July 31, 2026 From: San Francisco (SFO) To: Orange County (SNA)",
    "Flight Details Confirmation # AB7C2D Departure Date Thursday, September 17, 2026 at 12:27 PM Departure Airport Orange County (SNA) Arrival Des Moines (DSM) at 5:44 PM",
])
def test_embedded_operational_fields_survive_marketing_and_heavy_gate(body):
    evidence = assess_flight_evidence(subject="Information for your journey", sender="United <mail@enews.united.com>",
        body="Credit card. Save up to 20% on rental car. " + body + " Deals. Book now. Add bags.")
    assert evidence.verdict == "parse"
    assert "labeled_operational_block" in evidence.signals
    assert not _should_skip_expensive_parse(tier="exhaustive_backfill", prefilter=True, evidence=evidence)


def test_amex_numbered_schedule_not_discarded_for_credit_card_receipt():
    evidence = assess_flight_evidence(subject="Flight Schedule Change for Trip ID: 1234-5678", sender="travel@example.com",
        body="Flight Itinerary Change Delta 439 July 12, 2025 6:15am Dallas (DFW) 7:25am Los Angeles (LAX). RECORD LOCATORS Delta Air Lines ABC123. TRAVELERS Passenger 1: Alex Avery Ticket Number 0061234567890. Credit Card Information.")
    assert evidence.verdict == "parse"
    assert "DL439" in evidence.flight_numbers


@pytest.mark.parametrize("body", [
    "Flight: UA321 Date: July 31, 2026 From: YOU To: CAN. Book now.",
    "Flight Details Confirmation number. Departure September 17, 2026. Add bags. Rental car.",
    "Flight UA321! Book now. " + "Deals " * 400 + "Date July 31. SFO to SNA. Credit card.",
    '<div hidden>Flight: UA321 Date: July 31, 2026 From: San Francisco (SFO) To: Orange County (SNA)</div>Deals. Book now.',
])
def test_marketing_does_not_borrow_missing_or_hidden_fields(body):
    evidence = assess_flight_evidence(subject="Deals", sender="offers@enews.united.com", body=body)
    assert "labeled_operational_block" not in evidence.signals
    assert evidence.verdict == "skip"
