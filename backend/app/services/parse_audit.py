"""Parse-miss evidence for flight-like emails."""

from __future__ import annotations

import re
from dataclasses import dataclass


_AIRPORT_CODE = re.compile(r"\b[A-Z]{3}\b")
_FLIGHT_NUMBER = re.compile(r"\b[A-Z0-9]{2}\s*\d{1,4}[A-Z]?\b")
_CLOCK = re.compile(r"\b\d{1,2}:\d{2}\s*(?:AM|PM|am|pm|a\.m\.|p\.m\.)\b")
_DATE = re.compile(
    r"\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun|Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)?"
    r",?\s*(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)"
    r"[a-z]*\.?\s+\d{1,2}(?:,?\s+\d{2,4})?\b"
    r"|\b\d{1,2}/\d{1,2}/\d{2,4}\b",
    re.IGNORECASE,
)
_ROUTE_WORD = re.compile(r"\b(?:from|to|depart|departs|departure|arrive|arrives|arrival|route|nonstop|layover|connection)\b", re.IGNORECASE)
_FLIGHT_WORD = re.compile(r"\b(?:flight|itinerary|ticket|e-?ticket|confirmation|reservation|record locator|booking reference|boarding pass|check in|check-in)\b", re.IGNORECASE)
_PROMO_WORD = re.compile(r"\b(?:sale|deal|promo|save up to|newsletter|hotel only|rental car|credit card offer)\b", re.IGNORECASE)
_BAGGAGE_WORD = re.compile(r"\b(?:first bag|second bag|baggage policy|bag charges|checked bag)\b", re.IGNORECASE)


@dataclass(frozen=True)
class ParseMissEvidence:
    reason: str
    score: int
    signals: list[str]

    def as_dict(self) -> dict:
        return {
            "reason": self.reason,
            "score": self.score,
            "signals": self.signals,
        }


def assess_parse_miss(*, subject: str, sender: str, body: str) -> ParseMissEvidence:
    """Explain why an unparsed message is worth keeping for review.

    This is intentionally generic: it records the evidence bundle, not a
    provider-specific parser decision. Strong misses can be reprocessed by
    later parser versions or inspected in the review endpoint.
    """
    text = "\n".join(part for part in [subject, sender, body] if part)
    compact = re.sub(r"\s+", " ", text)
    upper = compact.upper()
    signals: list[str] = []
    score = 0

    airport_hits = sorted(set(_AIRPORT_CODE.findall(upper)))
    airport_hits = [code for code in airport_hits if code not in {"THE", "AND", "FOR", "YOU", "COM", "HTML"}]
    if len(airport_hits) >= 2:
        score += 3
        signals.append("multiple_airport_codes")
    elif len(airport_hits) == 1:
        score += 1
        signals.append("airport_code")

    if _FLIGHT_NUMBER.search(upper):
        score += 3
        signals.append("flight_number")
    if _DATE.search(compact):
        score += 2
        signals.append("date")
    if _CLOCK.search(compact):
        score += 2
        signals.append("time")
    if _ROUTE_WORD.search(compact):
        score += 2
        signals.append("route_language")
    if _FLIGHT_WORD.search(compact):
        score += 2
        signals.append("flight_language")
    if _BAGGAGE_WORD.search(compact):
        score -= 2
        signals.append("baggage_noise")
    if _PROMO_WORD.search(compact):
        score -= 2
        signals.append("promo_noise")

    if score >= 8:
        reason = "strong_flight_evidence_but_no_segments"
    elif score >= 5:
        reason = "partial_flight_evidence_but_no_segments"
    else:
        reason = "weak_flight_evidence_but_candidate_query_matched"

    return ParseMissEvidence(reason=reason, score=max(0, score), signals=signals)
