"""Carrier claims remain corroboration, never stand-alone ownership proof."""
from dataclasses import asdict
from datetime import datetime, timedelta, timezone

import pytest

from app.services.carrier_travel_evidence import (
    extract_carrier_travel_evidence as extract,
    may_have_carrier_travel_evidence,
)


DAY = datetime(2025, 8, 18, 15, tzinfo=timezone.utc)
AA_SURVEY = "americanairlines@survey.na.aa.com"
AA_OP = "no-reply@info.email.aa.com"
SY_SURVEY = "suncountryairlines@express.sea1.medallia.com"
SY_OP = "suncountry@info.suncountry.com"


def auth(sender):
    domain = sender.split("@")[1]
    dmarc = "aa.com" if domain.endswith(".aa.com") else domain
    return (f"mx.google.com; dkim=pass header.i=@{domain} header.s=test; "
            f"spf=pass smtp.mailfrom={sender}; dmarc=pass header.from={dmarc}")


def message(sender=AA_SURVEY, **changes):
    result = dict(subject="ALEX, how was your flight?", sender=sender,
        recipient="alex@example.com", text="Our records show that you flew from IAH to TQO on August 16, 2025.",
        html="", received_at=DAY, authentication_results=auth(sender))
    result.update(changes)
    return result


def checkin(**changes):
    return message(AA_OP, subject="It's time to check in - EXACT1", text=(
        "Confirmation code: EXACT1 Hi Alex Morgan Ms, "
        "Your trip is almost here and we're excited to see you on board."), **changes)


def test_aa_post_travel_assertion_is_not_a_flight_or_ownership_assignment():
    row, = extract(**message())
    assert (row.kind, row.carrier, row.name, row.local_day) == ("post_travel", "AA", "ALEX", "2025-08-16")
    assert (row.dep_airport, row.arr_airport, row.pnr) == ("IAH", "TQO", None)
    assert row.facts["route_scope"] == "journey"
    assert row.facts["ownership_authority"] is False
    assert not any("time" in key or "ownership" == key for key in asdict(row))


def test_sy_city_labels_are_preserved_without_guessing_airports():
    row, = extract(**message(SY_SURVEY, subject="Alex, how was your flight?", text=(
        "Hi Alex, Thank you for flying with Sun Country Airlines from Dallas/Ft. Worth, TX "
        "to Punta Cana, Dominican Republic on August 16, 2025.")))
    assert row.departure_label == "Dallas/Ft. Worth, TX"
    assert row.arrival_label == "Punta Cana, Dominican Republic"
    assert row.dep_airport is row.arr_airport is None


def test_generic_dallas_label_is_never_inferred_to_be_dfw():
    row, = extract(**message(SY_SURVEY, subject="Alex, how was your flight?", text=(
        "Hi Alex, Thank you for flying with Sun Country Airlines from Dallas "
        "to London on August 16, 2025.")))
    assert row.departure_label == "Dallas" and row.dep_airport is None


def test_reminder_is_same_claim_not_an_additional_vote():
    first = message(SY_SURVEY, subject="Alex, how was your flight?", text=(
        "Hi Alex, Thank you for flying with Sun Country Airlines from Dallas/Ft. Worth, TX "
        "to Punta Cana, Dominican Republic on August 16, 2025."))
    reminder = {**first, "subject": "Alex, how was your flight? - We still want to hear from you",
        "received_at": DAY + timedelta(days=2), "text": first["text"].replace(
            "Thank you for flying with Sun Country Airlines", "We recently sent you a brief survey about your flight")}
    assert extract(**first)[0].facts["claim_key"] == extract(**reminder)[0].facts["claim_key"]


def test_checkin_keeps_given_names_separate_from_full_passenger_name():
    row, = extract(**checkin())
    assert row.name == "Alex Morgan"
    assert row.pnr == "EXACT1" and row.kind == "operational_personal"
    assert row.facts["name_form"] == "given_sequence"
    assert row.local_day is row.dep_airport is row.arr_airport is None


def test_sy_disruption_retains_full_salutation_without_declaring_traveler():
    row, = extract(**message(SY_OP, subject="An important message regarding flight SY739", text=(
        "Reservation code: EXACT1 Dear Alex Avery, One or more of your flights has been affected by a schedule change. "
        "CANCEL FLIGHT Reservation Code: EXACT1")))
    assert row.name == "Alex Avery" and row.facts["name_form"] == "full_salutation"
    assert row.facts["ownership_authority"] is False


def test_explicit_connection_is_not_an_inferred_missing_leg():
    row, = extract(**message(AA_OP, subject="Your connecting flight to Tulum", text=(
        "Your connecting flight to TQO Confirmation code: EXACT1 Your flight to TQO departs in 1 hour.")))
    assert row.kind == "connecting_notice" and row.arr_airport == "TQO"
    assert row.name is row.dep_airport is row.local_day is None
    assert row.facts["explicit_connection"]


@pytest.mark.parametrize("suffix", ["EXACT1", "Departure Gate Change", "Departure Time Change"])
def test_unnamed_operational_notice_is_only_a_reconciliation_trigger(suffix):
    row, = extract(**message(AA_OP, subject=f"Your flight to Dallas/Fort Worth - {suffix}",
        text="Your flight to DFW Confirmation code: EXACT1. Your flight is now departing from gate D17."))
    assert row.kind == "operational_notice" and row.pnr == "EXACT1"
    assert row.name is row.local_day is row.dep_airport is row.arr_airport is None
    assert row.facts["ownership_authority"] is False


def test_unnamed_sy_operational_notice_remains_nonauthoritative():
    row, = extract(**message(SY_OP, subject="An important message regarding flight SY739", text=(
        "Reservation code: EXACT1 One or more of your flights has been affected by a schedule change.")))
    assert row.kind == "operational_notice" and row.name is None


def test_aa_operational_notice_rejects_conflicting_subject_reference():
    assert extract(**message(AA_OP, subject="Your flight to Tulum - OTHER1", text=(
        "Your flight to TQO Confirmation code: EXACT1"))) == ()


@pytest.mark.parametrize("heading", ["Flight 172 to TQO departs from gate D14", "Reminder: Flight 172 to TQO"])
def test_aa_operational_actual_numbered_headings(heading):
    row, = extract(**message(AA_OP, subject="Your flight to Tulum - Departure Gate Change", text=(
        heading + " Confirmation code: EXACT1 UPDATED Saturday, August 16, 2025 MIA TQO")))
    assert row.kind == "operational_notice" and row.name is None


def test_html_and_plain_duplicates_produce_one_claim():
    m = message()
    m["html"] = "<html><head><title>Different ignored title</title></head><body><p>" + m["text"] + "</p></body></html>"
    assert len(extract(**m)) == 1


@pytest.mark.parametrize("change", [
    {"sender": "Someone <no-reply@info.email.aa.com.evil.test>"},
    {"sender": "no-reply@info.email.aa.com, other@example.com"},
    {"sender": "friend@example.com"},
    {"recipient": ""}, {"recipient": "alex@example.com, other@example.com"},
    {"authentication_results": ""},
    {"authentication_results": auth(AA_SURVEY).replace("mx.google.com", "evil.test")},
    {"authentication_results": auth(AA_SURVEY).replace("dkim=pass", "dkim=fail")},
    {"authentication_results": auth(AA_SURVEY).replace("dmarc=pass", "dmarc=fail")},
    {"authentication_results": auth(AA_SURVEY).replace("@survey.na.aa.com", "@sendgrid.info")},
    {"authentication_results": auth(AA_SURVEY).replace("header.from=aa.com", "header.from=aa.com.evil.test")},
    {"authentication_results": auth(AA_SURVEY).replace("dkim=pass", "arc=pass (dkim=pass)")},
    {"subject": "Fwd: ALEX, how was your flight?"},
    {"subject": "Re: ALEX, how was your flight?"},
    {"subject": "Tell us about your flight"},
    {"text": "Our records show that you flew from IAH to TQO on August 16, 2025.\nForwarded message"},
    {"text": "> Our records show that you flew from IAH to TQO on August 16, 2025."},
    {"html": "<blockquote>Forwarded content</blockquote>"},
    {"html": "<div class='gmail_quote'>Earlier message</div>"},
    {"text": "We hope you enjoyed your trip!"},
    {"text": "Our records show that you will fly from IAH to TQO on August 16, 2025."},
    {"received_at": None}, {"received_at": DAY - timedelta(days=3)},
    {"received_at": DAY + timedelta(days=30)},
    {"text": "Our records show that you flew from IAH to TQO on February 30, 2025."},
    {"text": "Our records show that you flew from IAH to IAH on August 16, 2025."},
    {"html": "<p>Our records show that you flew from IAH to LAX on August 16, 2025.</p>"},
    {"text": "Hi Jordan, Our records show that you flew from IAH to TQO on August 16, 2025."},
    {"text": "x" * 500_001},
])
def test_untrusted_ambiguous_or_nontravel_sources_provide_no_evidence(change):
    assert extract(**message(**change)) == ()


@pytest.mark.parametrize("suffix", [
    " Reservation code: OTHER1", " Hi Jordan Avery,", " Dear Alex 123,",
])
def test_operational_name_or_reference_conflicts_fail_closed(suffix):
    m = checkin()
    m["text"] += suffix
    assert extract(**m) == ()


def test_subject_body_checkin_reference_must_agree():
    m = checkin()
    m["subject"] = "It's time to check in - OTHER1"
    assert extract(**m) == ()


def test_salutation_alone_is_not_enough_even_from_authenticated_carrier():
    m = checkin()
    m["text"] = "Confirmation code: EXACT1 Hi Alex Morgan, Enjoy our loyalty offers."
    assert extract(**m) == ()


def test_single_given_name_checkin_is_not_eligible():
    m = checkin()
    m["text"] = m["text"].replace("Alex Morgan Ms", "Alex")
    assert extract(**m) == ()


def test_normal_flight_notice_is_not_an_explicit_connection():
    assert extract(**message(AA_OP, subject="Your connecting flight to Tulum", text=(
        "Your flight to TQO Confirmation code: EXACT1"))) == ()


def test_unrelated_sources_do_not_build_an_html_tree(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("unrelated source reached HTML parser")
    monkeypatch.setattr("app.services.carrier_travel_evidence.BeautifulSoup", fail)
    assert extract(**message(subject="A great loyalty offer", html="<html>Offer</html>")) == ()
    assert extract(**message(sender="store@example.com", html="<html>Offer</html>")) == ()


@pytest.mark.parametrize("sender, subject, expected", [
    (AA_SURVEY, "Alex, how was your flight?", True),
    (SY_SURVEY, "Alex, how was your flight? - We still want to hear from you", True),
    (AA_OP, "It's time to check in - EXACT1", True),
    (AA_OP, "Your connecting flight to Tulum", True),
    (AA_OP, "Your flight to Tulum - Departure Gate Change", True),
    (AA_OP, "Your flight to Tulum - EXACT1", True),
    (AA_OP, "Your flight to Tulum - Save money now", False),
    (SY_OP, "An important message regarding flight SY739", True),
    (AA_OP, "Fwd: It's time to check in - EXACT1", False),
    (AA_SURVEY, "Re: Alex, how was your flight?", False),
    (AA_SURVEY, "Earn loyalty points", False),
    ("other@example.com", "Alex, how was your flight?", False),
    ("americanairlines@survey.na.aa.com.evil.test", "Alex, how was your flight?", False),
])
def test_cheap_candidate_screen_never_parses_html(monkeypatch, sender, subject, expected):
    def fail(*args, **kwargs):
        raise AssertionError("candidate screen reached HTML parser")
    monkeypatch.setattr("app.services.carrier_travel_evidence.BeautifulSoup", fail)
    assert may_have_carrier_travel_evidence(subject, sender) is expected


def test_input_is_unchanged_and_extraction_is_idempotent():
    m = message()
    before = dict(m)
    assert extract(**m) == extract(**m)
    assert m == before
