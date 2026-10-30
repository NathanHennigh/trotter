"""Parse-miss explanations derived from the shared flight evidence decision."""
from __future__ import annotations

import re
from dataclasses import dataclass

_ANCILLARY_WORD = re.compile(
    r"\b(?:first bag|second bag|baggage policy|bag charges|checked bag|add bags?|choose your seats?|sit together|seat upgrades?|comfier seat|seat bid|tsa wait times?|travel information on tsa|flight status update|service from)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ParseMissEvidence:
    reason: str
    score: int
    signals: list[str]

    @property
    def should_review(self) -> bool:
        return self.reason != "ignored_nonflight_promo" and self.score >= 5

    def as_dict(self) -> dict:
        return {
            "reason": self.reason,
            "score": self.score,
            "signals": self.signals,
            "should_review": self.should_review,
        }


def assess_parse_miss(*, subject: str, sender: str, body: str) -> ParseMissEvidence:
    """Use the same eligibility decision as ingestion; no contradictory scorer."""
    from .flight_evidence import assess_flight_evidence
    gate = assess_flight_evidence(subject=subject, sender=sender, body=body)
    signals = list(gate.signals)
    if _ANCILLARY_WORD.search(subject + "\n" + body):
        signals.append("ancillary_noise")
    if gate.verdict != "skip":
        return ParseMissEvidence(
            reason="strong_flight_evidence_but_no_segments" if gate.verdict == "parse"
            else "partial_flight_evidence_but_no_segments",
            score=max(5, gate.score), signals=signals,
        )
    noisy = any("noise" in signal or signal in {"newsletter_sender", "noisy_sender"} for signal in signals)
    return ParseMissEvidence(
        reason="ignored_nonflight_promo" if noisy else "weak_flight_evidence_but_candidate_query_matched",
        score=min(4, gate.score), signals=signals,
    )
