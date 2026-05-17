"""Developer-only helpers for flight discovery/parser audit scripts.

This module intentionally does not participate in production ingestion. It
normalizes local AI classifier output and buckets messages so missed cases can
be reviewed and turned into deterministic parser/discovery fixtures.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from hashlib import sha256
from typing import Any


AI_AUDIT_LABELS = {
    "flight_confirmation",
    "boarding_pass",
    "itinerary",
    "flight_change",
    "cancellation",
    "reminder",
    "receipt",
    "not_flight",
    "other_travel",
    "unsure",
}

ACTUAL_FLIGHT_LABELS = {"flight_confirmation", "boarding_pass", "itinerary", "receipt"}
CHANGE_LABELS = {"flight_change", "cancellation"}

GROUND_OR_LODGING_DOMAINS = {
    "airbnb.com",
    "agoda.com",
    "booking.greyhound.com",
    "booking.com",
    "busbud.com",
    "chasetravel.com",
    "e.hotwire.com",
    "emails.hertz.com",
    "flixbus.com",
    "gregoryscoffee.com",
    "greyhound.com",
    "hertz.com",
    "hotwire.com",
    "marriott.com",
    "megabus.com",
    "oakyapp.com",
    "res-marriott.com",
}

GROUND_OR_LODGING_RE = re.compile(
    r"""
    \b(
        airbnb|agoda|hotel|hotels|stay|courtyard|marriott|hertz|vehicle|rental\s+car|
        flixbus|greyhound|busbud|megabus|amtrak|train|bus\s+ticket|coach
    )\b
    """,
    re.IGNORECASE | re.VERBOSE,
)

ANCILLARY_FLIGHT_EVIDENCE_RE = re.compile(
    r"""
    \b(
        check[ -]?in|boarding\s+pass|mobile\s+boarding|gate\s+(?:assigned|changed)|
        puerta\s+de\s+embarque|embarcar[aá]|boarding\s+documents?|print\s+all\s+pages|
        flight\s+status|arrive\s+\d+\s+hours?\s+prior|tsa|airport\s+monitors
    )\b
    """,
    re.IGNORECASE | re.VERBOSE,
)

ANCILLARY_FLIGHT_RECEIPT_RE = re.compile(
    r"""
    \b(
        checked\s+bag|bag\s+(?:purchase|tag|fee)|free\s+checked\s+bags?|refund|
        refund\s+is\s+complete|purchase\s+receipt|payment|we\s+charged|
        online\s+validation\s+of\s+your\s+documents|upload\s+your\s+documents|
        compulsory\s+documents|application\s+code|generated\s+for\s+the\s+e-ticket|
        reimbursement
    )\b
    """,
    re.IGNORECASE | re.VERBOSE,
)

NON_AIRLINE_ETICKET_DOMAINS = {
    "migracion.gob.do",
}


@dataclass(frozen=True)
class FlightAuditAiResult:
    label: str = "unsure"
    confidence: float = 0.0
    has_actual_flight: bool = False
    is_marketing: bool = False
    is_cancellation: bool = False
    is_change_notice: bool = False
    detected_airlines: list[str] = field(default_factory=list)
    detected_flight_numbers: list[str] = field(default_factory=list)
    detected_airports: list[str] = field(default_factory=list)
    detected_dates: list[str] = field(default_factory=list)
    reason: str = ""
    raw_error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "confidence": self.confidence,
            "has_actual_flight": self.has_actual_flight,
            "is_marketing": self.is_marketing,
            "is_cancellation": self.is_cancellation,
            "is_change_notice": self.is_change_notice,
            "detected_airlines": self.detected_airlines,
            "detected_flight_numbers": self.detected_flight_numbers,
            "detected_airports": self.detected_airports,
            "detected_dates": self.detected_dates,
            "reason": self.reason,
            "raw_error": self.raw_error,
        }


def normalize_ai_classifier_response(raw_response: str) -> FlightAuditAiResult:
    """Parse and clamp a local AI classifier response into the audit schema."""
    payload, error = _extract_json_object(raw_response)
    if payload is None:
        return FlightAuditAiResult(raw_error=error or "invalid_json")

    label = _clean_label(payload.get("label"))
    confidence = _clamp_float(payload.get("confidence"), default=0.0)
    is_cancellation = bool(payload.get("is_cancellation")) or label == "cancellation"
    is_change_notice = bool(payload.get("is_change_notice")) or label == "flight_change"
    has_actual_flight = bool(payload.get("has_actual_flight")) or label in ACTUAL_FLIGHT_LABELS
    if payload.get("is_marketing"):
        has_actual_flight = False
    if label in {"not_flight", "other_travel", "unsure"}:
        has_actual_flight = bool(payload.get("has_actual_flight"))

    return FlightAuditAiResult(
        label=label,
        confidence=confidence,
        has_actual_flight=has_actual_flight,
        is_marketing=bool(payload.get("is_marketing")),
        is_cancellation=is_cancellation,
        is_change_notice=is_change_notice,
        detected_airlines=_clean_string_list(payload.get("detected_airlines")),
        detected_flight_numbers=_clean_string_list(payload.get("detected_flight_numbers")),
        detected_airports=_clean_string_list(payload.get("detected_airports"), uppercase=True),
        detected_dates=_clean_string_list(payload.get("detected_dates")),
        reason=str(payload.get("reason") or "")[:300],
    )


def classify_audit_bucket(
    *,
    in_v4_discovery: bool,
    prefilter_result: bool,
    parser_flight_count: int,
    ai_result: FlightAuditAiResult,
    parse_miss_score: int = 0,
    sender_domain: str = "",
    subject: str = "",
    safe_snippet: str = "",
) -> str:
    """Return the review bucket for a scanned email."""
    parser_found = parser_flight_count > 0
    ground_or_lodging = looks_like_ground_or_lodging(
        sender_domain=sender_domain,
        subject=subject,
        safe_snippet=safe_snippet,
    )
    ai_likely_flight = (
        ai_result.has_actual_flight
        and not ai_result.is_marketing
        and ai_result.label not in {"not_flight", "other_travel"}
        and ai_result.confidence >= 0.65
    )
    change_or_cancel = ai_result.label in CHANGE_LABELS or ai_result.is_cancellation or ai_result.is_change_notice

    if parser_found and in_v4_discovery and not change_or_cancel:
        if ai_result.label == "not_flight" and ai_result.confidence >= 0.75:
            return "possible_false_positive"
        return "parsed_ok"

    if change_or_cancel:
        return "change_or_cancellation"

    if ground_or_lodging and not parser_found:
        return "other_travel"

    if ai_result.label == "reminder" and not parser_found:
        return "duplicate_or_reminder"

    if not parser_found and looks_like_ancillary_flight_evidence(subject=subject, safe_snippet=safe_snippet):
        return "duplicate_or_reminder"

    if not parser_found and looks_like_ancillary_flight_receipt(
        sender_domain=sender_domain,
        subject=subject,
        safe_snippet=safe_snippet,
    ):
        return "duplicate_or_reminder"

    if ai_likely_flight and not in_v4_discovery:
        return "likely_flight_discovery_missed"

    if ai_likely_flight and in_v4_discovery and not parser_found:
        return "likely_flight_parser_missed"

    if parser_found and not in_v4_discovery:
        return "likely_flight_discovery_missed"

    if ai_result.label == "other_travel":
        return "other_travel"

    if ai_result.label == "not_flight" and ai_result.confidence >= 0.70:
        return "not_flight"

    if parse_miss_score >= 8 or prefilter_result or ai_result.confidence >= 0.45:
        return "possible_flight_needs_review"

    return "not_flight"


def looks_like_ground_or_lodging(*, sender_domain: str, subject: str, safe_snippet: str) -> bool:
    domain = (sender_domain or "").lower()
    if domain in GROUND_OR_LODGING_DOMAINS:
        return True
    if any(domain.endswith(f".{known}") for known in GROUND_OR_LODGING_DOMAINS):
        return True
    text = f"{subject}\n{safe_snippet}"
    return bool(GROUND_OR_LODGING_RE.search(text))


def looks_like_ancillary_flight_evidence(*, subject: str, safe_snippet: str) -> bool:
    text = f"{subject}\n{safe_snippet}"
    return bool(ANCILLARY_FLIGHT_EVIDENCE_RE.search(text))


def looks_like_ancillary_flight_receipt(*, sender_domain: str, subject: str, safe_snippet: str) -> bool:
    domain = (sender_domain or "").lower()
    if domain in NON_AIRLINE_ETICKET_DOMAINS:
        return True
    text = f"{subject}\n{safe_snippet}"
    return bool(ANCILLARY_FLIGHT_RECEIPT_RE.search(text))


def make_safe_snippet(*parts: str, max_length: int = 360) -> str:
    """Return a short redacted text sample suitable for local audit reports."""
    text = " ".join(part for part in parts if part)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"https?://\S+|www\.\S+", "[url]", text, flags=re.IGNORECASE)
    text = re.sub(r"[\w.+-]+@[\w.-]+\.\w+", "[email]", text)
    text = re.sub(r"\b[A-Z0-9]{6}\b", "[code]", text)
    return text[:max_length]


def body_hash(*parts: str) -> str:
    text = "\n".join(part for part in parts if part)
    return sha256(text.encode("utf-8", errors="ignore")).hexdigest()


def _extract_json_object(raw_response: str) -> tuple[dict[str, Any] | None, str | None]:
    text = (raw_response or "").strip()
    if not text:
        return None, "empty_response"
    try:
        parsed = json.loads(text)
        return (parsed, None) if isinstance(parsed, dict) else (None, "json_not_object")
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        return None, "json_object_not_found"
    try:
        parsed = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        return None, f"json_parse_error: {exc}"
    return (parsed, None) if isinstance(parsed, dict) else (None, "json_not_object")


def _clean_label(value: Any) -> str:
    label = str(value or "unsure").strip().lower()
    return label if label in AI_AUDIT_LABELS else "unsure"


def _clamp_float(value: Any, *, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, number))


def _clean_string_list(value: Any, *, uppercase: bool = False) -> list[str]:
    if not isinstance(value, list):
        return []
    cleaned: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if not text:
            continue
        cleaned.append((text.upper() if uppercase else text)[:80])
    return cleaned[:20]
