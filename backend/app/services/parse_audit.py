"""Parse-miss evidence for flight-like emails."""

from __future__ import annotations

import re
from dataclasses import dataclass


_AIRPORT_CODE = re.compile(r"\b[A-Z]{3}\b")
_ROUTE_PAIR = re.compile(
    r"\b[A-Z]{3}\s*(?:-|--|->|>|TO|to|from)\s*[A-Z]{3}\b"
    r"|\bfrom\s+[A-Z][A-Za-z .'-]{2,40}\s+(?:to|arriv(?:e|es|al))\s+[A-Z][A-Za-z .'-]{2,40}\b",
    re.IGNORECASE,
)
_FLIGHT_NUMBER = re.compile(
    r"\b(?:AA|UA|DL|WN|AS|B6|NK|F9|G4|SY|BA|AF|LH|KL|IB|AZ|TK|EK|QR|SQ|CX|NH|JL|KE|MH|TG|CI|OZ|CA|MU|QF|NZ|AC|WS|VS|ET|SA|MS|RJ|EY|GF|SV|AI|VN|BR|AY|SK|LO|OS|SN|TP|JU|FR|U2|VY|PC|HV|W6|DY|Z2|Y4|AM)\s*\d{1,4}[A-Z]?\b"
    r"|\bflight\s+\d{1,4}[A-Z]?\b",
    re.IGNORECASE,
)
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
_BOOKING_ANCHOR = re.compile(r"\b(?:record locator|confirmation(?:\s+(?:code|number))?|booking reference|reservation code|pnr)\b", re.IGNORECASE)
_PASSENGER_WORD = re.compile(r"\b(?:passenger|traveler|traveller)\b", re.IGNORECASE)
_PROMO_WORD = re.compile(
    r"\b(?:sale|deal|deals|promo|promotion|save up to|newsletter|news\s*&?\s*deals|fare alert|price alert|hotel only|rental car|credit card offer|points offer|redeemed points|sponsored|advertisement|new travel offer|premium stays|eligible to apply|card 2\.0|order is ready|ready for pick up|pickup order|purchase receipt|delivery date|updated delivery|shipment|delivered|invoice|class action|court ordered notice|groceries|grocery|cyber resilient|fraud report|security notice|delivery order|would you recommend|final reminder|survey|feedback|shopping|bonus miles just for shopping|appointment is scheduled|appointment is confirmed|service appointment|daily digest|parking|bowl info|milestones)\b",
    re.IGNORECASE,
)
_ANCILLARY_WORD = re.compile(
    r"\b(?:first bag|second bag|baggage policy|bag charges|checked bag|add bags?|choose your seats?|sit together|seat upgrades?|comfier seat|seat bid|tsa wait times?|travel information on tsa|flight status update|service from)\b",
    re.IGNORECASE,
)
_NOISY_SENDER = re.compile(
    r"\b(?:kayak|thepointsguy|points guy|airhint|marriott|bonvoy|airbnb|budget|rockauto|fedex|vidangel|prioritypass|uber|greyhound|uspsinformeddelivery|informeddelivery\.usps|poshmark|shopifyemail|baylor\.edu|huckberry|turbotax|alltrails|xfinity|comcast|uniuni|domain\.com|astound|mileageplusshoppingnews|seatbid@spirit|agoda reviews?|hotel|hotels|rental|deals?|newsletter|dollarflightclub|travelzoo|groupon|pourover|networksolutions|linkedin|hims|vrbo|pointsyeah|10xtravel|roame|atlascoffeeclub|hiltongrandvacations|ticketmaster|enews\.united|news\.united|loyalty\.ms\.aa|mycheapoair|capitaloneshopping|capital one shopping|capitalone@notification|alertsp\.chase|daily drop|travel\.daily|point\.me|beehiiv|creditkarma|credit karma|paypal|moongate|uncharted|defi education|lifemiles@newsletter|lifemiles@info|lifemiles@communications|lowe'?s|lowes|home depot|homedepot|order\.homedepot|instacart|bilt|linux foundation|capital one \\| venture x|capitalone@message|notifications@members\.bilt|wellsfargo)\b",
    re.IGNORECASE,
)
_NEWSLETTER_SENDER = re.compile(
    r"\b(?:mail\.thepourover\.org|news\.united\.com|em\.greyhound\.com|mileageplusshoppingnews\.com|dollarflightclub\.com|r\.groupon\.com|us\.travelzoo\.com|thepointsguy\.com|email-marriott\.com|eml\.networksolutions\.com|linkedin\.com|hims\.com|pointsyeah\.com|10xtravel\.com|loyalty\.ms\.aa\.com|enews\.united\.com|capitaloneshopping\.com|travel\.daily|mail\.beehiiv\.com|mail\.creditkarma\.com|news\.paypal\.com|newsletter\.lifemiles\.com|info\.lifemiles\.com|no-reply@point\.me|members\.bilt|customeremail\.instacartemail\.com|linuxfoundation\.org)\b",
    re.IGNORECASE,
)
_GENERIC_CODE_ONLY = re.compile(r"\b(?:verification|security|login|one[-\s]?time|password|access|gift|coupon|order|tracking|settlement)\s+(?:code|number)\b", re.IGNORECASE)


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

    has_route_pair = bool(_ROUTE_PAIR.search(compact))
    airport_hits = sorted(set(_AIRPORT_CODE.findall(upper)))
    airport_hits = [code for code in airport_hits if code not in {"THE", "AND", "FOR", "YOU", "COM", "HTML"}]
    if has_route_pair:
        score += 3
        signals.append("route_pair")
    elif len(airport_hits) >= 2:
        score += 1
        signals.append("multiple_airport_codes")
    elif len(airport_hits) == 1:
        score += 1
        signals.append("airport_code")

    if _FLIGHT_NUMBER.search(upper):
        score += 3
        signals.append("flight_number")
    if _BOOKING_ANCHOR.search(compact):
        score += 2
        signals.append("booking_identifier")
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
    if _ANCILLARY_WORD.search(compact):
        score -= 4
        signals.append("ancillary_noise")
    if _PROMO_WORD.search(compact):
        score -= 4
        signals.append("promo_noise")
    if _NOISY_SENDER.search(sender) or _NOISY_SENDER.search(subject):
        score -= 2
        signals.append("noisy_sender")
    if _NEWSLETTER_SENDER.search(sender):
        score -= 5
        signals.append("newsletter_sender")
    if _GENERIC_CODE_ONLY.search(compact):
        score -= 4
        signals.append("generic_code_noise")

    has_route = "route_pair" in signals
    has_airports = "multiple_airport_codes" in signals or has_route
    has_date = "date" in signals
    has_booking = "booking_identifier" in signals
    has_flight_number = "flight_number" in signals
    has_boarding_or_checkin = bool(re.search(r"\b(?:boarding pass|boarding documents|check in|check-in|e-?ticket|ticket number)\b", compact, re.IGNORECASE))
    has_strong_context = (
        (has_route and has_date and (has_booking or has_flight_number))
        or (has_airports and has_booking and has_boarding_or_checkin)
        or (has_route and has_flight_number and (_PASSENGER_WORD.search(compact) or has_boarding_or_checkin))
    )
    noisy = bool({"promo_noise", "ancillary_noise", "noisy_sender", "newsletter_sender", "generic_code_noise"} & set(signals))
    if noisy and not has_strong_context:
        score = min(score, 3)
    if "ancillary_noise" in signals and not (has_booking and has_boarding_or_checkin):
        score = min(score, 3)
    if "newsletter_sender" in signals and not (
        has_route and has_date and has_booking and has_flight_number
    ):
        score = min(score, 2)

    if score >= 8:
        reason = "strong_flight_evidence_but_no_segments"
    elif score >= 5:
        reason = "partial_flight_evidence_but_no_segments"
    elif noisy:
        reason = "ignored_nonflight_promo"
    else:
        reason = "weak_flight_evidence_but_candidate_query_matched"

    return ParseMissEvidence(reason=reason, score=max(0, score), signals=signals)
