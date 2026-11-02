"""Only explicitly supported, not-yet-examined carrier sources are revisited."""
from copy import deepcopy

import pytest

from app.models import Message, MessageStatus
from app.services.carrier_travel_evidence import EVIDENCE_VERSION
from app.services.parser import PARSER_VERSION
from app.tasks.import_tasks import _message_skip_reason


@pytest.fixture(autouse=True)
def opted_in_fixture_account(monkeypatch):
    monkeypatch.setenv("FLIGHT_IMPORT_RECOVERY_USER_IDS", "1")


def resolved(**values):
    data = dict(user_id=1, provider_msg_id="original", status=MessageStatus.ACCEPTED,
        parse_version=PARSER_VERSION, ignored=True, parse_error="non_flight_noise",
        subject="ALEX, how was your flight?", from_email="American Airlines <AmericanAirlines@survey.na.aa.com>",
        parse_evidence={"resolved": True, "reason": "non_flight_noise"})
    data.update(values)
    return Message(**data)


def test_supported_resolved_source_is_examined_once_without_parser_version_bump(monkeypatch):
    monkeypatch.setenv("CARRIER_TRAVEL_CORROBORATION_ENABLED", "true")
    message = resolved()
    original = deepcopy(message.parse_evidence)
    assert _message_skip_reason(message, PARSER_VERSION) is None
    assert message.parse_evidence == original
    message.parse_evidence = {**original, "carrier_evidence": {"version": EVIDENCE_VERSION, "evidence_ids": []}}
    # An empty result (including failed authentication) is not fetched forever.
    assert _message_skip_reason(message, PARSER_VERSION) == "non_flight_noise"


@pytest.mark.parametrize("values", [
    {"from_email": "American Airlines <attacker@example.test>"},
    {"subject": "Discounts for your next trip"},
    {"subject": "Fwd: ALEX, how was your flight?"},
    {"status": MessageStatus.IGNORED},
])
def test_unsupported_or_explicitly_ignored_messages_keep_the_existing_gate(monkeypatch, values):
    monkeypatch.setenv("CARRIER_TRAVEL_CORROBORATION_ENABLED", "true")
    assert _message_skip_reason(resolved(**values), PARSER_VERSION) == "non_flight_noise"


def test_default_off_does_not_revisit_resolved_sources(monkeypatch):
    monkeypatch.delenv("CARRIER_TRAVEL_CORROBORATION_ENABLED", raising=False)
    assert _message_skip_reason(resolved(), PARSER_VERSION) == "non_flight_noise"


def test_failed_or_stale_parse_remains_eligible_through_normal_gate(monkeypatch):
    monkeypatch.setenv("CARRIER_TRAVEL_CORROBORATION_ENABLED", "true")
    message = resolved(status=MessageStatus.REVIEW_REQUIRED, ignored=False,
        parse_error="passenger_identity_unresolved", parse_evidence={"resolved": False})
    assert _message_skip_reason(message, PARSER_VERSION) is None
    assert _message_skip_reason(resolved(parse_version=PARSER_VERSION - 1), PARSER_VERSION) is None


def test_examined_survey_is_not_refetched_as_an_incomplete_flight(monkeypatch):
    monkeypatch.setenv("CARRIER_TRAVEL_CORROBORATION_ENABLED", "true")
    message = resolved(status=MessageStatus.REVIEW_REQUIRED, ignored=False,
        parse_error="strong_flight_evidence_but_no_segments", parse_evidence={"resolved": False,
            "carrier_evidence": {"version": EVIDENCE_VERSION, "analyzed_no_flights": True, "evidence_ids": []}})
    assert _message_skip_reason(message, PARSER_VERSION) == "carrier_support_examined"
    assert _message_skip_reason(message, PARSER_VERSION, force_parse=True) is None
    assert _message_skip_reason(message, PARSER_VERSION + 1) is None
    message.parse_evidence["carrier_evidence"]["version"] = 0
    assert _message_skip_reason(message, PARSER_VERSION) is None


def test_examined_operational_notice_is_still_retried_if_its_flight_is_held(monkeypatch):
    monkeypatch.setenv("CARRIER_TRAVEL_CORROBORATION_ENABLED", "true")
    message = resolved(subject="It's time to check in - TEST01", from_email="no-reply@info.email.aa.com",
        status=MessageStatus.REVIEW_REQUIRED, ignored=False,
        parse_error="passenger_identity_unresolved", parse_evidence={"resolved": False,
            "carrier_evidence": {"version": EVIDENCE_VERSION, "analyzed_no_flights": True, "evidence_ids": []}})
    assert _message_skip_reason(message, PARSER_VERSION) is None


@pytest.mark.parametrize("cohort", ["", "bad", "2", "1,invalid"])
def test_supported_carrier_source_for_unlisted_account_is_not_refetched(monkeypatch, cohort):
    monkeypatch.setenv("CARRIER_TRAVEL_CORROBORATION_ENABLED", "true")
    monkeypatch.setenv("FLIGHT_IMPORT_RECOVERY_USER_IDS", cohort)
    assert _message_skip_reason(resolved(user_id=1), PARSER_VERSION) == "non_flight_noise"


def test_carrier_gate_uses_message_owner_not_another_opted_in_account(monkeypatch):
    monkeypatch.setenv("CARRIER_TRAVEL_CORROBORATION_ENABLED", "true")
    monkeypatch.setenv("FLIGHT_IMPORT_RECOVERY_USER_IDS", "1")
    assert _message_skip_reason(resolved(user_id=1), PARSER_VERSION) is None
    assert _message_skip_reason(resolved(user_id=2), PARSER_VERSION) == "non_flight_noise"
