"""Cheap, explainable flight-shape evidence for import funnel measurement."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from .bilt_booking import bilt_confirmation_evidence, is_bilt_confirmation_metadata


EVIDENCE_VERSION = 3
_AIRPORT_PAIR = re.compile(
    r"\b(?P<dep>[A-Z]{3})\s*(?:-|--|->|>|\bTO\b|–|—)\s*(?P<arr>[A-Z]{3})\b",
    re.IGNORECASE,
)
_PAREN_AIRPORT = re.compile(r"\((?P<code>[A-Z]{3})\)")
_FLIGHT_NUMBER = re.compile(
    r"\b(?P<airline>AA|UA|DL|WN|AS|B6|NK|F9|G4|SY|BA|AF|LH|KL|IB|AZ|TK|EK|QR|SQ|CX|NH|JL|KE|MH|TG|CI|OZ|CA|MU|QF|NZ|AC|WS|VS|ET|SA|MS|RJ|EY|GF|SV|AI|VN|BR|AY|SK|LO|OS|SN|TP|JU|FR|U2|VY|PC|HV|W6|DY|Z2|Y4|AM)\s?(?P<airline_number>\d{1,4}[A-Z]?)\b"
    r"|\bflight(?:\s+number)?\s*[:#]?\s*#?\s*(?P<number>\d{1,4}[A-Z]?)\b",
    re.IGNORECASE,
)
_CARRIER_CODES = {
    "AMERICAN AIRLINES": "AA", "UNITED AIRLINES": "UA", "DELTA AIR LINES": "DL",
    "DELTA AIRLINES": "DL", "DELTA": "DL", "SOUTHWEST AIRLINES": "WN", "SPIRIT AIRLINES": "NK",
    "FRONTIER AIRLINES": "F9", "ALASKA AIRLINES": "AS", "JETBLUE": "B6",
    "AEROMEXICO": "AM", "IBERIA": "IB", "EVA AIR": "BR",
    "ALL NIPPON AIRWAYS": "NH", "SINGAPORE AIRLINES": "SQ", "EMIRATES": "EK",
    "QATAR AIRWAYS": "QR", "BRITISH AIRWAYS": "BA", "AIR FRANCE": "AF",
    "LUFTHANSA": "LH", "TURKISH AIRLINES": "TK",
}
_CARRIER_FLIGHT_NUMBER = re.compile(
    r"\b(?P<carrier>" + "|".join(re.escape(name).replace(r"\ ", r"\s+") for name in _CARRIER_CODES)
    + r")\s+(?:FLIGHT\s*#?\s*)?(?P<number>\d{1,4}[A-Z]?)\b(?!\s*\(\d{3}\))", re.I,
)
_PNR = re.compile(
    r"\b(?:record locators?|confirmation code|confirmation number|booking reference|reservation code|pnr)\b|confirmation\s*#",
    re.IGNORECASE,
)
_TICKET = re.compile(r"\b(?:e-?ticket|ticket number|passenger receipt)\b", re.IGNORECASE)
_BOARDING = re.compile(r"\b(?:boarding pass|boarding documents|check[-\s]?in|mobile boarding)\b", re.IGNORECASE)
_FLIGHT_WORD = re.compile(r"\b(?:flight|airline|itinerary|departure|arrival|route|trip)\b", re.IGNORECASE)
_DATE_TIME = re.compile(
    r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2}"
    r"|\b\d{1,2}:\d{2}\s*(?:AM|PM|a\.m\.|p\.m\.)\b"
    r"|\b\d{1,2}/\d{1,2}/\d{2,4}\b"
    r"|\b\d{4}[-/]\d{1,2}[-/]\d{1,2}\b"
    r"|\b\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\b",
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


def operational_block_signals(body: str) -> tuple[str, ...]:
    """Recognize local labeled itinerary facts, never passenger authority.

    A marketing footer cannot veto an actual itinerary. Conversely, scattered
    airport/flight words in a newsletter cannot manufacture one: require the
    fields together in a bounded block. This also retains incomplete operational
    records (for example in-flight entertainment notices) for review only.
    """
    text = re.sub(r"https?://\S+", " ", body[:200_000], flags=re.I)
    text = " ".join(text.split())
    # Explicit Flight / Date / From / To fields, including messages without a
    # booking reference or clocks. These do not establish a passenger or flight.
    labeled = re.compile(
        r"\bFlight\s*:\s*[A-Z0-9]{2}\s*\d{1,4}\b.{0,60}?"
        r"\bDate\s*:\s*(?P<date>.{5,50}?)\s+From\s*:\s*"
        r".{0,80}?\(\s*(?P<dep>[A-Z]{3})\s*\).{0,30}?\bTo\s*:\s*"
        r".{0,80}?\(\s*(?P<arr>[A-Z]{3})\s*\)", re.I)
    for match in labeled.finditer(text):
        if (_DATE_TIME.search(match['date']) and _valid_iata(match['dep'].upper())
                and _valid_iata(match['arr'].upper()) and match['dep'].upper() != match['arr'].upper()):
            return ("labeled_operational_block",)
    for heading in re.finditer(r"\b(?:flight details|flight itinerary(?: change)?|flight overview|return flight)\b", text, re.I):
        block = text[heading.start():heading.start() + 1600]
        # A concrete booking value, two airports, a date and actual departure /
        # arrival fields or numbered flights. Header words alone are insufficient.
        booking = re.search(r"\b(?:confirmation(?: code| number)?\s*[:#]?|booking reference|reservation code)\s+(?:is\s+)?([A-Z0-9]{6})(?![A-Z0-9])", block, re.I)
        airports = _route_airport_codes(block.upper())
        clock = re.search(r"\b\d{1,2}:\d{2}\s*(?:am|pm)?\b", block, re.I)
        numbered = _flight_numbers(block.upper(), include_named=True)
        fields = bool(re.search(r"\bdepart(?:ure|ing)?\b", block, re.I) and re.search(r"\barriv(?:al|ing|e)\b", block, re.I))
        if booking and len(airports) >= 2 and _DATE_TIME.search(block) and clock and (fields or numbered):
            return ("labeled_operational_block",)
    return ()


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
    # Bilt has a structural HTML adapter; retain table boundaries for that pass.
    structured_body = body
    operational_body = body[:200_000]
    if re.search(r"<[a-z][^>]*>", body[:200_000], re.I):
        from .html_visibility import visible_html_soup
        soup = visible_html_soup(body[:200_000])
        structured_body = (str(soup) if is_bilt_confirmation_metadata(subject=subject, sender=sender) else "")
        operational_body = soup.get_text("\n", strip=True)
        body = soup.get_text(" ", strip=True)
    bilt = bilt_confirmation_evidence(subject=subject, sender=sender, body=structured_body)
    if bilt:
        return FlightEvidence(
            version=EVIDENCE_VERSION, verdict="parse", score=13,
            signals=("transactional_bilt_confirmation", "booking_identifier", "route_airport_pair",
                     "flight_number", "date_or_time", "flight_language"),
            airport_codes=bilt.airport_codes, flight_numbers=bilt.flight_numbers,
        )
    text = "\n".join(part for part in (subject, sender, body[:200_000]) if part)
    route_text = "\n".join(part for part in (subject, body[:200_000]) if part)
    route_text = re.sub(r"https?://\S+|\b[^\s<>@]+@[^\s<>@]+", " ", route_text, flags=re.I)
    compact = " ".join(text.split())
    upper = compact.upper()
    route_upper = " ".join(route_text.split()).upper()
    signals: list[str] = []
    score = 0

    # Sender hostnames (for example mh1.evaair.com) are not flight evidence.
    flight_numbers = _flight_numbers(route_upper, include_named=bool(_PNR.search(compact) or _TICKET.search(compact)))
    # SAT/SUN (and a few other weekday abbreviations) also name real airports.
    # A calendar range alone cannot supply a route; explicit flight or booking
    # context still permits those airport codes in a genuine itinerary.
    weekday_route_context = bool(flight_numbers or _PNR.search(route_text) or _TICKET.search(route_text)
        or re.search(r"\b(?:flight|airline|itinerary|departure|arrival|boarding)\b", route_text, re.I))
    airport_codes = _route_airport_codes(route_upper, allow_weekday_pairs=weekday_route_context)
    if len(airport_codes) >= 2:
        score += 5
        signals.append("route_airport_pair")
    elif airport_codes:
        score += 1
        signals.append("airport_context")

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
    operational_subject = bool(re.search(
        r"\b(?:check[- ]?in|boarding|gate|flight.*(?:delay(?:ed)?|updates?|changes?)|(?:delay(?:ed)?|updates?).*flight|e-?ticket|itinerary|flight confirmation)\b",
        subject, re.I,
    ))
    structured_route = has_route or bool(re.search(r"\bdepart(?:ure|ing)?\b", route_text, re.I)
                                        and re.search(r"\barriv(?:al|ing|e)\b", route_text, re.I))
    operational = (operational_subject and has_date and structured_route
                   and (has_flight_number or has_booking)
                   and not _PROMO.search(subject) and "newsletter_sender" not in signals)
    # Receipts may spell airports out in full or render them on separate lines.
    # A dated, numbered booking with ticket/check-in details is sufficient to
    # extract deterministically; footer seat offers must not veto that evidence.
    operational = operational or (has_date and has_flight_number and has_booking
        and bool({"ticket_language", "boarding_or_checkin"} & set(signals))
        and "newsletter_sender" not in signals and not _PROMO.search(subject))
    cancellation_notice = (bool(re.search(r"\bcancel(?:led|ed|lation)\b", subject, re.I))
                           and (has_booking or has_flight_number or "ticket_language" in signals)
                           and "newsletter_sender" not in signals)
    if cancellation_notice:
        signals.append("cancellation_notice")
        operational = True
    block_signals = operational_block_signals(body)
    if block_signals:
        signals.extend(block_signals)
        operational = True
    if re.search(r"\bPriceline\s+Trip\s+Number\b", operational_body, re.I):
        from .priceline_itinerary import has_priceline_flight_itinerary
        if has_priceline_flight_itinerary(operational_body):
            # Explicit card structure warrants parsing/review even when its
            # printed dates conflict. The bounded extractor decides completeness.
            signals.append("dated_agency_flight_cards")
            operational = True
    if operational:
        signals.append("operational_itinerary")
        score = max(score, 8)
    noisy = bool({"promo_noise", "non_flight_travel_noise", "noisy_sender", "newsletter_sender"} & set(signals))
    if noisy and not operational and not (has_route and has_date and (has_booking or has_flight_number)):
        score = min(score, 3)
    if "newsletter_sender" in signals and not operational and not (has_route and has_date and has_booking and has_flight_number):
        score = min(score, 2)
    if re.search(r"\b(?:mileage|miles|rewards?|account)[- ]+(?:e[- ]?)?statement\b", subject, re.I) and not has_booking:
        # Balance statements may advertise dated new routes and flight numbers.
        # They are not ticket evidence merely because an airline sent them.
        signals.append("statement_noise")
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


def _route_airport_codes(upper: str, *, allow_weekday_pairs: bool = True) -> list[str]:
    codes: list[str] = []
    for match in _AIRPORT_PAIR.finditer(upper):
        if (not allow_weekday_pairs and match.group("dep") in {"MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"}
                and match.group("arr") in {"MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"}):
            continue
        for code in (match.group("dep"), match.group("arr")):
            if _valid_iata(code) and code not in codes:
                codes.append(code)
    if codes:
        return codes

    for match in re.finditer(r"\b([A-Z]{3})\s*[-–]\s*[A-Z][A-Z ,.'-]{2,75}\s+TO\s+([A-Z]{3})\b", upper):
        dep, arr = match.groups()
        if _valid_iata(dep) and _valid_iata(arr):
            return [dep, arr]

    parenthesized = [match.group("code") for match in _PAREN_AIRPORT.finditer(upper)]
    for code in parenthesized:
        if _valid_iata(code) and code not in codes:
            codes.append(code)
        if len(codes) == 2:
            break
    return codes


def _flight_numbers(upper: str, *, include_named: bool = False) -> list[str]:
    numbers: list[str] = []
    for match in _FLIGHT_NUMBER.finditer(upper):
        if match.group("airline"):
            # In a class schedule, "9:00 AM 5:30 PM" contains AM followed by
            # the next clock. Keep actual AM flights and explicit flight fields.
            explicit_field = re.search(r"\bFLIGHT(?:\s+NUMBER)?\s*[:#]?\s*$", upper[max(0, match.start() - 24):match.start()])
            if (match.group("airline") == "AM" and match.group("airline_number").isdigit()
                    and 1 <= int(match.group("airline_number")) <= 12
                    and re.match(r":[0-5]\d\s*(?:AM|PM)\b", upper[match.end():]) and not explicit_field):
                continue
            number = f"{match.group('airline').upper()}{match.group('airline_number').upper()}"
        else:
            number = f"FLIGHT{match.group('number').upper()}"
        number = re.sub(r"\s+", "", number)
        if any(char.isdigit() for char in number) and number not in numbers:
            numbers.append(number)
        if len(numbers) == 5:
            break
    # Many real receipts spell out the carrier instead of its IATA prefix.
    # These are still only evidence signals; ticket/date/booking requirements
    # below keep an airline name and a number in an advertisement insufficient.
    for match in _CARRIER_FLIGHT_NUMBER.finditer(upper) if include_named else ():
        number = _CARRIER_CODES[" ".join(match["carrier"].upper().split())] + match["number"].upper()
        if number not in numbers:
            numbers.append(number)
    return numbers


@lru_cache(maxsize=1)
def _parser_carrier_number_evidence():
    # Imported lazily because parser imports flight evidence during startup.
    # Precision checks must recognize the same carrier aliases as extraction.
    from .parser import _AIRLINE_NAME_TO_CODE
    carriers = {**_CARRIER_CODES, **{name.upper(): code for name, code in _AIRLINE_NAME_TO_CODE.items()}}
    expression = re.compile(r"\b(?P<carrier>" + "|".join(
        re.escape(name).replace(r"\ ", r"\s+") for name in sorted(carriers, key=len, reverse=True))
        + r")\s+(?:FLIGHT\s*#?\s*)?(?P<number>\d{1,4}[A-Z]?)\b(?!\s*\(\d{3}\))", re.I)
    return carriers, expression


def has_explicit_flight_number(number: str, text: str, *, detailed_text: str = "") -> bool:
    """Generic summary extraction may not promote a stop count to a flight."""
    def normalized(value):
        found = re.fullmatch(r"([A-Z0-9]{2}|FLIGHT)\s*0*(\d{1,4})([A-Z]?)", value.upper())
        return (found[1], int(found[2]), found[3]) if found else None
    expected = normalized(str(number or ""))
    if not expected:
        return False
    carriers, carrier_numbers = _parser_carrier_number_evidence()
    def evidence(value):
        # Tracking URLs and sender hostnames are not printed flight numbers.
        value = re.sub(r"https?://\S+|\b[^\s<>@]+@[^\s<>@]+", " ", value, flags=re.I)
        values = [normalized((m["airline"] or "FLIGHT") + (m["airline_number"] or m["number"]))
                  for m in _FLIGHT_NUMBER.finditer(value)]
        values += [normalized(carriers[" ".join(m["carrier"].upper().split())] + m["number"])
                   for m in carrier_numbers.finditer(value)]
        # Some airline receipts have adjacent FLIGHT / TERMINAL column headings.
        values += [normalized("FLIGHT" + m[1]) for m in re.finditer(
            r"\bFLIGHT\s+TERMINAL\s+(\d{1,4}[A-Z]?)\b", value, re.I)]
        return [value for value in values if value]
    values = evidence(text)
    details = evidence(detailed_text) if detailed_text else []
    # MIME plain parts sometimes collapse a two-leg itinerary into "Iberia 1"
    # where 1 is a stop count. Prefer the detailed HTML's numbered carrier legs
    # when it supplies them; plaintext-only and image-only HTML remain supported.
    if any(value[0] == expected[0] for value in details):
        values = details
    return any(value[1:] == expected[1:] and value[0] in {expected[0], "FLIGHT"} for value in values)


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
