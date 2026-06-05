"""Cheap, explainable flight-shape evidence for import funnel measurement."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache


EVIDENCE_VERSION = 1
_AIRPORT_PAIR = re.compile(
    r"\b(?P<dep>[A-Z]{3})\s*(?:-|--|->|>|TO|–|—)\s*(?P<arr>[A-Z]{3})\b",
    re.IGNORECASE,
)
_PAREN_AIRPORT = re.compile(r"\((?P<code>[A-Z]{3})\)")
_FLIGHT_NUMBER = re.compile(
    r"\b(?P<airline>AA|UA|DL|WN|AS|B6|NK|F9|G4|SY|BA|AF|LH|KL|IB|AZ|TK|EK|QR|SQ|CX|NH|JL|KE|MH|TG|CI|OZ|CA|MU|QF|NZ|AC|WS|VS|ET|SA|MS|RJ|EY|GF|SV|AI|VN|BR|AY|SK|LO|OS|SN|TP|JU|FR|U2|VY|PC|HV|W6|DY|Z2|Y4|AM)\s?(?P<airline_number>\d{1,4}[A-Z]?)\b"
    r"|\bflight\s+(?P<number>\d{1,4}[A-Z]?)\b",
    re.IGNORECASE,
)
_PNR = re.compile(
    r"\b(?:record locator|confirmation code|confirmation number|booking reference|reservation code|pnr)\b|confirmation\s*#",
    re.IGNORECASE,
)
_TICKET = re.compile(r"\b(?:e-?ticket|ticket number|passenger receipt)\b", re.IGNORECASE)
_BOARDING = re.compile(r"\b(?:boarding pass|boarding documents|check[-\s]?in|mobile boarding)\b", re.IGNORECASE)
_FLIGHT_WORD = re.compile(r"\b(?:flight|airline|itinerary|departure|arrival|route|trip)\b", re.IGNORECASE)
_DATE_TIME = re.compile(
    r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2}"
    r"|\b\d{1,2}:\d{2}\s*(?:AM|PM|a\.m\.|p\.m\.)\b"
    r"|\b\d{1,2}/\d{1,2}/\d{2,4}\b",
    re.IGNORECASE,
)
_PROMO = re.compile(
    r"\b(?:newsletter|sale|deal alert|deals|save up to|book now|points offer|credit card|fare alert|price alert|news\s*&?\s*deals|sponsored|advertisement|new travel offer|premium stays|eligible to apply|card 2\.0|shopping|bonus miles just for shopping|appointment is scheduled|appointment is confirmed|service appointment|daily digest|parking|bowl info|milestones)\b",
    re.IGNORECASE,
)
_NON_FLIGHT = re.compile(
    r"\b(?:hotel only|vacation rental|rental car|cruise|bus ticket|train ticket|order confirmation|tracking number|order is ready|ready for pick up|pickup order|purchase receipt|delivery date|updated delivery|shipment|delivered|invoice|class action|court ordered notice|groceries|grocery|cyber resilient|fraud report|security notice|delivery order|choose your seats?|comfier seat|seat bid|add bags?|tsa wait times?)\b",
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


@dataclass(frozen=True)
class FlightEvidence:
    version: int
    verdict: str
    score: int
    signals: tuple[str, ...]
    airport_codes: tuple[str, ...]
    flight_numbers: tuple[str, ...]

    def as_dict(self) -> dict:
        return {
            "version": self.version,
            "verdict": self.verdict,
            "score": self.score,
            "signals": list(self.signals),
            "airport_codes": list(self.airport_codes),
            "flight_numbers": list(self.flight_numbers),
        }


def assess_flight_evidence(*, subject: str, sender: str, body: str, sender_confidence: str = "unknown") -> FlightEvidence:
    """Score flight-like structure without deciding import behavior yet."""
    text = "\n".join(part for part in (subject, sender, body[:200_000]) if part)
    route_text = "\n".join(part for part in (subject, body[:200_000]) if part)
    compact = " ".join(text.split())
    upper = compact.upper()
    route_upper = " ".join(route_text.split()).upper()
    signals: list[str] = []
    score = 0

    airport_codes = _route_airport_codes(route_upper)
    if len(airport_codes) >= 2:
        score += 5
        signals.append("route_airport_pair")
    elif airport_codes:
        score += 1
        signals.append("airport_context")

    flight_numbers = _flight_numbers(upper)
    if flight_numbers:
        score += 3
        signals.append("flight_number")
    if _PNR.search(compact):
        score += 3
        signals.append("booking_identifier")
    if _TICKET.search(compact):
        score += 2
        signals.append("ticket_language")
    if _BOARDING.search(compact):
        score += 3
        signals.append("boarding_or_checkin")
    if _FLIGHT_WORD.search(compact):
        score += 1
        signals.append("flight_language")
    if _DATE_TIME.search(compact):
        score += 1
        signals.append("date_or_time")

    if sender_confidence == "airline":
        score += 2
        signals.append("airline_sender")
    elif sender_confidence == "mixed":
        signals.append("mixed_sender")

    if _PROMO.search(compact):
        score -= 4
        signals.append("promo_noise")
    if _NON_FLIGHT.search(compact):
        score -= 4
        signals.append("non_flight_travel_noise")
    if _NOISY_SENDER.search(sender) or _NOISY_SENDER.search(subject):
        score -= 2
        signals.append("noisy_sender")
    if _NEWSLETTER_SENDER.search(sender):
        score -= 5
        signals.append("newsletter_sender")

    has_route = "route_airport_pair" in signals
    has_date = "date_or_time" in signals
    has_booking = "booking_identifier" in signals
    has_flight_number = "flight_number" in signals
    noisy = bool({"promo_noise", "non_flight_travel_noise", "noisy_sender", "newsletter_sender"} & set(signals))
    if noisy and not (has_route and has_date and (has_booking or has_flight_number)):
        score = min(score, 3)
    if "newsletter_sender" in signals and not (has_route and has_date and has_booking and has_flight_number):
        score = min(score, 2)

    if score >= 7:
        verdict = "parse"
    elif score >= 4:
        verdict = "review"
    else:
        verdict = "skip"
    return FlightEvidence(
        version=EVIDENCE_VERSION,
        verdict=verdict,
        score=max(0, score),
        signals=tuple(signals),
        airport_codes=tuple(airport_codes),
        flight_numbers=tuple(flight_numbers),
    )


def _route_airport_codes(upper: str) -> list[str]:
    codes: list[str] = []
    for match in _AIRPORT_PAIR.finditer(upper):
        for code in (match.group("dep"), match.group("arr")):
            if _valid_iata(code) and code not in codes:
                codes.append(code)
    if codes:
        return codes

    parenthesized = [match.group("code") for match in _PAREN_AIRPORT.finditer(upper)]
    for code in parenthesized:
        if _valid_iata(code) and code not in codes:
            codes.append(code)
        if len(codes) == 2:
            break
    return codes


def _flight_numbers(upper: str) -> list[str]:
    numbers: list[str] = []
    for match in _FLIGHT_NUMBER.finditer(upper):
        if match.group("airline"):
            number = f"{match.group('airline').upper()}{match.group('airline_number').upper()}"
        else:
            number = f"FLIGHT{match.group('number').upper()}"
        number = re.sub(r"\s+", "", number)
        if any(char.isdigit() for char in number) and number not in numbers:
            numbers.append(number)
        if len(numbers) == 5:
            break
    return numbers


@lru_cache(maxsize=1)
def _iata_codes() -> frozenset[str]:
    try:
        import airportsdata

        return frozenset(str(code).upper() for code in airportsdata.load("IATA"))
    except Exception:
        return frozenset()


def _valid_iata(code: str) -> bool:
    codes = _iata_codes()
    return len(code) == 3 and (not codes or code in codes)
