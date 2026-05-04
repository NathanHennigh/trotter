"""Email parser: JSON-LD, ICS, and heuristic flight extraction."""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Optional

from bs4 import BeautifulSoup
from rapidfuzz import fuzz

from ..models import MessageStatus

logger = logging.getLogger(__name__)
PARSER_VERSION = 9

# ──────────────────────────── regex patterns ────────────────────────────────

# Two-letter airline IATA code followed immediately or with a space by 1-4 digits
_AIRLINE_FLIGHT = re.compile(r"\b([A-Z]{2})\s*(\d{1,4})\b")
# Three-letter IATA airport code (all-uppercase word)
_AIRPORT = re.compile(r"\b([A-Z]{3})\b")
# Six-char alphanumeric PNR (uppercase)
_PNR = re.compile(r"\b([A-Z][A-Z0-9]{5})\b")
_PNR_LABEL = re.compile(
    r"""
    \b
    (?:
        record\ locator|
        confirmation(?:\s+(?:code|number))?|
        booking\ reference|
        booking\ code|
        booking\ number|
        reservation\ code|
        reservation\ number|
        airline\ confirmation|
        pnr
    )
    (?:\s+is)?[:\s#-]*
    ([A-Z0-9]{5,8})
    \b
    """,
    re.IGNORECASE | re.VERBOSE,
)
_CAPITAL_ONE_AIRLINE_CONFIRMATION = re.compile(
    r"""
    \b
    (?:
        confirmation\s+codes?\s+
        (?:American\s+Airlines|United|ANA|EVA\s+Air|Iberia|Southwest|AirAsia|Volaris|Aeromexico)
        |
        (?:American\s+Airlines|United|ANA|EVA\s+Air|Iberia|Southwest|AirAsia|Volaris|Aeromexico)
        \s+confirmation\s+code
    )
    \s*[:#-]?\s*
    ([A-Z0-9]{5,8})
    \b
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Airline IATA codes that we know are airlines and not airports
_KNOWN_AIRLINES = {
    "AA", "UA", "DL", "WN", "AS", "B6", "NK", "F9", "G4", "SY",
    "BA", "AF", "LH", "KL", "IB", "AZ", "TK", "EK", "QR", "SQ",
    "CX", "NH", "JL", "KE", "MH", "TG", "CI", "OZ", "CA", "MU",
    "QF", "NZ", "AC", "WS", "VS", "ET", "SA", "MS", "RJ",
    "EY", "GF", "SV", "AI", "VN", "BR", "AY", "SK", "LO", "OS",
    "SN", "TP", "JU", "FR", "U2", "VY", "PC", "HV", "W6", "DY",
    "Z2", "Y4", "AM",
}

# Common uppercase 3-letter non-airport tokens to exclude from airport detection.
# Only contains abbreviations that are NEVER airport codes (months, timezones, etc.).
# Do NOT add valid IATA codes here — use the IATA whitelist instead.
_NOT_AIRPORTS = {
    "THE", "AND", "FOR", "ARE", "NOT", "BUT", "YOU", "ALL", "CAN",
    "HER", "WAS", "ONE", "OUR", "OUT", "DAY", "GET", "HAS", "HIM",
    "HOW", "OLD", "SEE", "TWO", "WAY", "WHO", "BOY", "DID", "ITS",
    "LET", "PUT", "SAY", "SHE", "TOO", "USE", "USA", "NEW", "NOW",
    "GMT", "UTC", "EST", "PST", "CST", "MST", "PDT", "EDT", "CDT",
    "MDT", "INC", "LLC", "LTD", "PLC", "CEO", "CFO", "CTO", "COO",
    "PDF", "HTML", "HTTP", "WWW", "COM", "NET", "ORG", "REF", "PNR",
    "VIA", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV",
    "DEC", "JAN", "FEB", "MAR", "SUN", "MON", "TUE", "WED", "THU",
    "FRI", "SAT", "BCC", "FWD", "FYI", "TBD", "TBC", "ETA", "ETD",
}

_PNR_STOPWORDS = _NOT_AIRPORTS | {
    "PLEASE", "TRAVEL", "ONLINE", "UNITED", "THANKS", "RECEIPT", "TICKET",
    "FLIGHT", "CHANGE", "CANCEL", "REWARD", "MOBILE", "EMAILS", "NOTICE",
    "CODES", "BELOW", "NUMBER", "CHECK", "AMERICAN", "AIRLINES", "CAPITAL",
}

# Valid IATA airport codes from airportsdata — the primary whitelist.
def _load_valid_iata_codes() -> frozenset:
    try:
        import airportsdata
        data = airportsdata.load("IATA")
        return frozenset(data.keys())
    except Exception:
        return frozenset()

_VALID_IATA: frozenset = _load_valid_iata_codes()

# Strip URLs before airport extraction so path segments like /rts/go2.aspx don't match.
_URL_RE = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)

# Codes that appear inside parentheses: airlines mark airports as "City (IAH)" — very reliable.
_AIRPORT_IN_PARENS = re.compile(r"\(([A-Z]{3})\)")
_AIRPORT_WORD = r"(?:[A-Z][A-Z.'-]*\s+){0,8}?"
_AIRPORT_TOKEN = rf"(?:{_AIRPORT_WORD}\(?\b([A-Z]{{3}})\b\)?)"
_ROUTE_PAIR_PATTERNS = [
    re.compile(rf"\bFROM\s+{_AIRPORT_TOKEN}\s+(?:TO|->|-->|-)\s+{_AIRPORT_TOKEN}\b"),
    re.compile(rf"\b{_AIRPORT_TOKEN}\s+(?:TO|->|-->|-)\s+{_AIRPORT_TOKEN}\b"),
]
_DEPARTURE_AIRPORT = re.compile(
    rf"\b(?:FROM|DEPART(?:S|ED|ING|URE)?(?:\s+(?:FROM|AIRPORT))?|ORIGIN)\s+{_AIRPORT_TOKEN}\b"
)
_ARRIVAL_AIRPORT = re.compile(
    rf"\b(?:TO|ARRIV(?:E|ES|ED|ING|AL)(?:\s+(?:AT|AIRPORT))?|DESTINATION)\s+{_AIRPORT_TOKEN}\b"
)
_VIA_AIRPORT = re.compile(rf"\bVIA\s+{_AIRPORT_TOKEN}\b")
_DAY_MONTH_DATE = r"(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun),?\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}"
_CLOCK_TIME = r"\d{1,2}:\d{2}\s*(?:AM|PM)"
_STRUCTURED_FLIGHT_BLOCK = re.compile(
    rf"""
    \bFlight\s+\d+\s+of\s+\d+\s+
    (?P<airline>[A-Z0-9]{{2}})\s*(?P<number>\d{{1,4}}[A-Z]?)\b
    .{{0,220}}?
    (?P<dep_date>{_DAY_MONTH_DATE})
    \s+
    (?P<arr_date>{_DAY_MONTH_DATE})
    .{{0,80}}?
    (?P<dep_clock>{_CLOCK_TIME})
    .{{0,80}}?
    (?P<arr_clock>{_CLOCK_TIME})
    .{{0,220}}?
    \((?P<dep_airport>[A-Z]{{3}})\)
    .{{0,140}}?
    \((?P<arr_airport>[A-Z]{{3}})\)
    """,
    re.VERBOSE | re.DOTALL,
)
_COMPACT_ROUTE_SEGMENT = re.compile(
    r"""
    \b(?P<airline_name>[A-Z][A-Za-z0-9 .&'-]{1,35}?)\s*-\s*
    (?P<airline>[A-Z0-9]{2})\s*(?P<number>\d{1,4}[A-Z]?)\b
    \s+(?P<dep_city>[A-Z][A-Za-z .,'/-]{1,45}?)\s+(?P<dep_airport>[A-Z]{3})
    \s+(?P<dep_time>\d{1,2}:\d{2}\s*(?:a\.m\.|p\.m\.|am|pm|AM|PM))
    \s+(?P<duration_h>\d{1,2})h(?:\s+(?P<duration_m>\d{1,2})m)?
    \s+(?P<arr_city>[A-Z][A-Za-z .,'/-]{1,45}?)\s+(?P<arr_airport>[A-Z]{3})
    \s+(?P<arr_time>\d{1,2}:\d{2}\s*(?:a\.m\.|p\.m\.|am|pm|AM|PM))
    """,
    re.IGNORECASE | re.VERBOSE,
)
_AIRASIA_NOTICE_BLOCK = re.compile(
    r"""
    Flight\s+number\s*:\s*(?P<airline>[A-Z0-9]{2})\s*(?P<number>\d{1,4}[A-Z]?)
    .*?
    Departure\s+Date\s*:\s*(?P<date>\d{1,2}\s*[- ]\s*[A-Za-z]{3,9},?\s*[- ]\s*\d{4})
    .*?
    Depart\s+from\s+.*?\((?P<dep_airport>[A-Z]{3})\)\s*:\s*(?P<dep_time>\d{1,2}:\d{2})
    .*?
    Arrive\s+in\s+.*?\((?P<arr_airport>[A-Z]{3})\)\s*:\s*(?P<arr_time>\d{1,2}:\d{2})
    """,
    re.VERBOSE | re.DOTALL,
)
_NAMED_AIRLINE_SEGMENT = re.compile(
    r"""
    \b(?P<airline_name>[A-Z][A-Za-z ]{2,35})\s+Flight\s+(?P<number>\d{1,4}[A-Z]?)
    (?:\s+Terminal\s+\S+)?
    \s+(?P<dep_time>\d{1,2}:\d{2}\s*(?:am|pm|AM|PM))
    \s+(?P<dep_dow>[A-Za-z]{3})\.?\s+(?P<dep_month>[A-Za-z]{3,9})\s+(?P<dep_day>\d{1,2})
    \s+.*?\((?P<dep_airport>[A-Z]{3})\)
    \s+(?P<arr_time>\d{1,2}:\d{2}\s*(?:am|pm|AM|PM))
    \s+(?P<arr_dow>[A-Za-z]{3})\.?\s+(?P<arr_month>[A-Za-z]{3,9})\s+(?P<arr_day>\d{1,2})
    \s+.*?\((?P<arr_airport>[A-Z]{3})\)
    """,
    re.IGNORECASE | re.VERBOSE,
)
_IBERIA_DETAIL_SEGMENT = re.compile(
    r"""
    \b(?P<flight_number>IB\d{1,4}[A-Z]?)\b
    .*?
    (?P<dep_time>\d{1,2}:\d{2})\s*h\s*,\s*
    (?P<dep_date>[A-Za-z]+\s+\d{1,2}\s+[A-Za-z]+\s+\d{4})
    \s+.*?\((?P<dep_airport>[A-Z]{3})\)
    .*?
    (?P<arr_time>\d{1,2}:\d{2})\s*h\s*,\s*
    (?P<arr_date>[A-Za-z]+\s+\d{1,2}\s+[A-Za-z]+\s+\d{4})
    \s+.*?\((?P<arr_airport>[A-Z]{3})\)
    """,
    re.IGNORECASE | re.VERBOSE | re.DOTALL,
)
_PRICELINE_ROUTE_SEGMENT = re.compile(
    r"""
    (?P<dep_airport>[A-Z]{3})\s+(?P<arr_airport>[A-Z]{3})
    (?:\s|>)+(?P<dep_time>\d{1,2}:\d{2}\s*(?:AM|PM|am|pm))\s*-\s*
    (?P<arr_time>\d{1,2}:\d{2}\s*(?:AM|PM|am|pm))
    (?P<body>.{0,220}?)
    (?P<airline_name>[A-Z][A-Za-z ]{2,35})\s+Flight\s+(?P<number>\d{1,4}[A-Z]?)
    """,
    re.IGNORECASE | re.VERBOSE | re.DOTALL,
)
_PRICELINE_DAY_HEADER = re.compile(
    r"\b(?P<dow>Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+(?P<month>[A-Za-z]{3,9})\s+(?P<day>\d{1,2})\b",
    re.IGNORECASE,
)
_SOUTHWEST_FLIGHT_SECTION = re.compile(
    r"""
    \bFlight(?:\s+\d+)?\s*:\s*
    (?P<dow>Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s*
    (?P<date>\d{1,2}/\d{1,2}/\d{4})
    (?P<body>.*?)(?=\bFlight(?:\s+\d+)?\s*:|Payment\s+information|Fare\s+rules|$)
    """,
    re.IGNORECASE | re.VERBOSE | re.DOTALL,
)
_SOUTHWEST_SEGMENT = re.compile(
    r"""
    \bFLIGHT\s*\#\s*(?P<number>\d{1,4}[A-Z]?)
    .*?
    DEPARTS\s+\W*(?P<dep_airport>[A-Z]{3})\W+
    (?P<dep_time>\d{1,2}:\d{2})\W*(?P<dep_ampm>AM|PM)
    .*?
    ARRIVES\s+\W*(?P<arr_airport>[A-Z]{3})\W+
    (?P<arr_time>\d{1,2}:\d{2})\W*(?P<arr_ampm>AM|PM)
    """,
    re.IGNORECASE | re.VERBOSE | re.DOTALL,
)
_AA_INLINE_RECEIPT_SEGMENT = re.compile(
    r"""
    \b(?P<dep_airport>[A-Z]{3})\s+
    (?P<dep_city>[A-Z][A-Za-z ./'-]{2,45}?)\s+
    (?P<dep_time>\d{1,2}:\d{2}\s*(?:AM|PM|am|pm))
    \s+
    (?P<airline>[A-Z0-9]{2})\s*(?P<number>\d{1,4}[A-Z]?)
    .{0,180}?
    \b(?P<arr_airport>[A-Z]{3})\s+
    (?P<arr_city>[A-Z][A-Za-z ./'-]{2,45}?)\s+
    (?P<arr_time>\d{1,2}:\d{2}\s*(?:AM|PM|am|pm))
    """,
    re.IGNORECASE | re.VERBOSE | re.DOTALL,
)
_AA_HOLD_TABLE_SEGMENT = re.compile(
    r"""
    \b(?P<airline_name>[A-Z][A-Za-z .&'-]{2,45}?)\s+
    (?P<number>\d{1,4}[A-Z]?)\s+
    (?P<dep_place>[A-Z][A-Za-z ./'-]{2,55}?\([A-Z]{3}\))\s+
    (?P<dep_date>(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun),?\s+
        (?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2})
    \s+
    (?P<dep_time>\d{1,2}:\d{2}\s*(?:AM|PM|am|pm))
    \s+
    (?P<arr_place>[A-Z][A-Za-z ./'-]{2,55}?\([A-Z]{3}\))\s+
    (?P<arr_date>(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun),?\s+
        (?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2})
    \s+
    (?P<arr_time>\d{1,2}:\d{2}\s*(?:AM|PM|am|pm))
    """,
    re.IGNORECASE | re.VERBOSE | re.DOTALL,
)
_PARTNER_AWARD_SEGMENT = re.compile(
    r"""
    \b(?P<airline_name>[A-Z][A-Za-z .&'-]{2,45}?)\W+
    (?:Flight\W+)?
    (?P<number>\d{1,4}[A-Z]?)
    .{0,220}?
    (?P<dep_date>(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun),?\s+
        (?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2})
    \s+
    (?P<dep_time>\d{1,2}:\d{2}\s*(?:AM|PM|am|pm))
    .{0,90}?
    \b(?P<dep_airport>[A-Z]{3})\b
    .{0,180}?
    (?P<arr_date>(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun),?\s+
        (?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2})
    \s+
    (?P<arr_time>\d{1,2}:\d{2}\s*(?:AM|PM|am|pm))
    .{0,90}?
    \b(?P<arr_airport>[A-Z]{3})\b
    """,
    re.IGNORECASE | re.VERBOSE | re.DOTALL,
)
_AIRLINE_ROUTE_FLIGHT_SEGMENT = re.compile(
    r"""
    \b(?P<dep_airport>[A-Z]{3})\s+
    (?P<arr_airport>[A-Z]{3})\s+
    Flight\s+(?P<number>\d{1,4}[A-Z]?)\s+
    (?P<dep_date>(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun),?\s+
        (?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2})
    \s+
    (?P<dep_time>\d{1,2}:\d{2}\s*(?:AM|PM|am|pm))
    .*?
    (?P<arr_date>(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun),?\s+
        (?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2})
    \s+
    (?P<arr_time>\d{1,2}:\d{2}\s*(?:AM|PM|am|pm))
    """,
    re.IGNORECASE | re.VERBOSE | re.DOTALL,
)
_ARRIVES_ROUTE_SEGMENT = re.compile(
    r"""
    \b(?P<month>Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+
    (?P<day>\d{1,2})(?:st|nd|rd|th)?
    \s+
    (?P<dep_airport>[A-Z]{3})
    \s+
    (?P<dep_time>\d{1,2}:\d{2}\s*(?:AM|PM|am|pm))
    \s+
    (?P<airline>[A-Z0-9]{2})\s*(?P<number>\d{1,4}[A-Z]?)
    \s+
    Arrives
    \s+
    (?:
        [A-Z][A-Za-z ./'-]{1,60}?\s+\((?P<arr_airport_paren>[A-Z]{3})\)
        |
        (?P<arr_airport>[A-Z]{3})
    )
    \s+
    (?P<arr_time>\d{1,2}:\d{2}\s*(?:AM|PM|am|pm))
    """,
    re.IGNORECASE | re.VERBOSE,
)
_ROUTE_TABLE_ITINERARY_ROW = re.compile(
    r"""
    (?P<date>(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun),?\s+
        (?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+
        \d{1,2})
    \s+
    (?P<dep_time>\d{1,2}:\d{2}\s*(?:AM|PM|am|pm))
    \s+
    (?P<arr_time>\d{1,2}:\d{2}\s*(?:AM|PM|am|pm))
    \s+
    (?P<airline>[A-Z0-9]{2})\s*(?P<number>\d{1,4}[A-Z]?)
    (?:\s+Operated\s+by\s+.+?)?
    \s+
    (?P<dep_airport>[A-Z]{3})\s+to\s+(?P<arr_airport>[A-Z]{3})
    """,
    re.IGNORECASE | re.VERBOSE | re.DOTALL,
)
_MONTH_DATE_WITH_YEAR = (
    r"(?:(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday|Mon|Tue|Wed|Thu|Fri|Sat|Sun)\.?,?\s*)?"
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}"
)
_SLASH_DATE_WITH_YEAR = r"\d{1,2}/\d{1,2}/\d{2,4}"
_LABELED_ITINERARY_SEGMENT = re.compile(
    rf"""
    \b(?:Depart|Return)\s*:\s*
    (?P<date>{_MONTH_DATE_WITH_YEAR})
    \s+
    (?P<dep_time>\d{{1,2}}:\d{{2}}\s*(?:a\.?m\.?|p\.?m\.?|AM|PM|am|pm))
    \s+
    (?P<dep_airport>[A-Z]{{3}})
    \s+
    (?P<arr_time>\d{{1,2}}:\d{{2}}\s*(?:a\.?m\.?|p\.?m\.?|AM|PM|am|pm))
    \s+
    (?P<arr_airport>[A-Z]{{3}})
    \s+
    \d{{1,2}}\s*h(?:\s*\d{{1,2}}\s*m)?
    \s+
    (?P<airline_name>[A-Z][A-Za-z&. -]{{2,45}}?)
    \s+
    (?P<airline>[A-Z0-9]{{2}})\s*(?P<number>\d{{1,4}}[A-Z]?)
    """,
    re.IGNORECASE | re.VERBOSE | re.DOTALL,
)
_COMPACT_CHECKIN_ROW = re.compile(
    rf"""
    (?P<date>{_MONTH_DATE_WITH_YEAR})
    \s+
    (?P<dep_airport>[A-Z]{{3}})
    \s+[A-Z][A-Za-z .,'/-]{{2,60}}?
    \s+
    (?P<dep_time>\d{{1,2}}:\d{{2}}\s*(?:AM|PM|am|pm))
    \s+
    (?P<airline>[A-Z0-9]{{2}})\s*(?P<number>\d{{1,4}}[A-Z]?)
    \s+
    (?P<arr_airport>[A-Z]{{3}})
    \s+[A-Z][A-Za-z .,'/-]{{2,60}}?
    \s+
    (?P<arr_time>\d{{1,2}}:\d{{2}}\s*(?:AM|PM|am|pm))
    """,
    re.IGNORECASE | re.VERBOSE | re.DOTALL,
)
_GENERIC_ITINERARY_BLOCK = re.compile(
    rf"""
    (?P<date>{_MONTH_DATE_WITH_YEAR}|{_SLASH_DATE_WITH_YEAR})
    (?P<prefix>.{{0,220}}?)
    (?P<dep_time>\d{{1,2}}:\d{{2}}\s*(?:a\.m\.|p\.m\.|am|pm|AM|PM))
    \s+
    (?P<arr_time>\d{{1,2}}:\d{{2}}\s*(?:a\.m\.|p\.m\.|am|pm|AM|PM))
    (?P<middle>.{{0,220}}?)
    (?P<dep_airport>[A-Z]{{3}})
    (?P<between>.{{0,140}}?)
    (?P<arr_airport>[A-Z]{{3}})
    (?P<suffix>.{{0,220}}?)
    (?P<airline>[A-Z0-9]{{2}})\s*(?P<number>\d{{1,4}}[A-Z]?)
    """,
    re.VERBOSE | re.DOTALL,
)


# ──────────────────────────── data classes ──────────────────────────────────

@dataclass
class ParsedFlight:
    dep_airport: str
    arr_airport: str
    dep_time: datetime
    arr_time: datetime
    airline: Optional[str] = None
    flight_number: Optional[str] = None
    pnr: Optional[str] = None
    passenger_name: Optional[str] = None
    source: str = "unknown"
    confidence: Optional[int] = None
    aircraft: Optional[dict] = None


@dataclass
class ParseResult:
    flights: list[ParsedFlight] = field(default_factory=list)
    passenger_name: Optional[str] = None
    status: MessageStatus = MessageStatus.REVIEW_REQUIRED
    source: str = "unknown"


@dataclass
class _FlightEvidence:
    dep_airport: str
    arr_airport: str
    dep_time: datetime
    arr_time: datetime
    airline: Optional[str]
    flight_number: Optional[str]
    score: int
    source: str = "v5"


@dataclass
class _HtmlTableBlock:
    headers: list[str]
    rows: list[list[str]]


# ──────────────────────────── public API ────────────────────────────────────

def parse_email(
    html: str,
    plain_text: str,
    attachments: list[tuple[str, bytes]],
    user_name: str,
    aliases: list[str],
    received_at: Optional[datetime] = None,
    subject: Optional[str] = None,
    from_email: Optional[str] = None,
) -> ParseResult:
    """Parse email content and return the best available ParseResult.

    Priority: JSON-LD  >  ICS attachments  >  heuristic text.
    """
    if isinstance(received_at, str):
        received_at = _parse_received_at(received_at)

    # 1. JSON-LD (most reliable)
    if html:
        flights = extract_jsonld_flights(html)
        if flights:
            if not _jsonld_should_yield_to_text(flights, subject=subject, from_email=from_email):
                passenger_name = flights[0].passenger_name
                return ParseResult(
                    flights=flights,
                    passenger_name=passenger_name,
                    status=check_identity(passenger_name, user_name, aliases),
                    source="jsonld",
                )

    # 2. ICS attachments
    for filename, data in attachments:
        try:
            flights = extract_ics_flights(data.decode("utf-8", errors="replace"))
            if flights:
                passenger_name = flights[0].passenger_name
                return ParseResult(
                    flights=flights,
                    passenger_name=passenger_name,
                    status=check_identity(passenger_name, user_name, aliases),
                    source="ics",
                )
        except Exception as exc:
            logger.debug("ICS parse failed for %s: %s", filename, exc)

    # 3. Heuristic (best-effort)
    html_text = _html_to_parser_text(html) if html else ""
    base_text = plain_text or html_text
    table_text = _html_table_text_only(html) if html and plain_text else ""
    if html:
        table_text = table_text or ""
    header_context = "\n".join(part for part in [from_email, subject] if part)
    v5_parts = [header_context, base_text, table_text]
    if html_text and html_text != base_text:
        v5_parts.append(html_text)
    v5_text = "\n".join(part for part in v5_parts if part)
    if v5_text:
        v5_flights = extract_v5_flights(
            v5_text,
            pnr=_extract_pnr(v5_text.upper()),
            received_at=received_at,
        )
        if v5_flights:
            passenger_name = v5_flights[0].passenger_name
            return ParseResult(
                flights=v5_flights,
                passenger_name=passenger_name,
                status=check_identity(passenger_name, user_name, aliases),
                source="heuristic",
            )

    text_parts = [header_context, base_text]
    if html_text and html_text != base_text:
        text_parts.append(html_text)
    text = "\n".join(part for part in text_parts if part)
    if text:
        flights = extract_heuristic_flights(text, received_at=received_at)
        if flights:
            passenger_name = flights[0].passenger_name
            return ParseResult(
                flights=flights,
                passenger_name=passenger_name,
                status=check_identity(passenger_name, user_name, aliases),
                source="heuristic",
            )

    return ParseResult()


# ──────────────────────────── JSON-LD parser ────────────────────────────────

def extract_jsonld_flights(html: str) -> list[ParsedFlight]:
    """Find all <script type=application/ld+json> blocks and extract FlightReservations."""
    soup = BeautifulSoup(html, "html.parser")
    flights: list[ParsedFlight] = []
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except (json.JSONDecodeError, Exception):
            continue
        items = data if isinstance(data, list) else [data]
        for item in items:
            flights.extend(_parse_jsonld_item(item))
    return flights


def _html_to_parser_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    table_text = _extract_html_table_text(soup)
    body_text = soup.get_text(separator="\n")
    return "\n".join(part for part in [table_text, body_text] if part)


def _html_table_text_only(html: str) -> str:
    return _extract_html_table_text(BeautifulSoup(html, "html.parser"))


def _extract_html_table_text(soup: BeautifulSoup) -> str:
    lines: list[str] = []
    for table in soup.find_all("table"):
        rows: list[list[str]] = []
        for tr in table.find_all("tr"):
            cells = [
                _compact_space(cell.get_text(" "))
                for cell in tr.find_all(["th", "td"])
                if _compact_space(cell.get_text(" "))
            ]
            if cells:
                rows.append(cells)
        if not rows:
            continue

        block = _table_block_from_rows(rows)
        if block.headers:
            lines.append(" ".join(block.headers))
        for row in block.rows:
            if not row:
                continue
            lines.append(" | ".join(row))
            lines.extend(row)
            if block.headers and len(block.headers) == len(row):
                lines.extend(f"{header}: {value}" for header, value in zip(block.headers, row))
    return "\n".join(lines)


def _table_block_from_rows(rows: list[list[str]]) -> _HtmlTableBlock:
    if not rows:
        return _HtmlTableBlock(headers=[], rows=[])
    first = rows[0]
    header_tokens = {"date", "depart", "departs", "departure", "arrive", "arrives", "arrival", "flight", "flt", "route", "from", "to", "duration"}
    looks_like_header = sum(1 for cell in first if any(token in cell.lower() for token in header_tokens)) >= 2
    if looks_like_header:
        return _HtmlTableBlock(headers=first, rows=rows[1:])
    return _HtmlTableBlock(headers=[], rows=rows)


def _parse_jsonld_item(item: dict) -> list[ParsedFlight]:
    type_ = item.get("@type", "")
    flights: list[ParsedFlight] = []
    if type_ == "FlightReservation":
        f = _reservation_to_flight(item)
        if f:
            flights.append(f)
    elif type_ in ("ReservationPackage", "TravelAction"):
        for sub in item.get("subReservation", []):
            flights.extend(_parse_jsonld_item(sub))
    return flights


def _reservation_to_flight(item: dict) -> Optional[ParsedFlight]:
    res_for = item.get("reservationFor", {})
    if not res_for or res_for.get("@type") != "Flight":
        return None

    dep = res_for.get("departureAirport", {}).get("iataCode", "").upper().strip()
    arr = res_for.get("arrivalAirport", {}).get("iataCode", "").upper().strip()
    if not dep or not arr:
        return None

    try:
        dep_time = _parse_iso(res_for.get("departureTime", ""))
        arr_time = _parse_iso(res_for.get("arrivalTime", ""))
    except (ValueError, TypeError):
        return None

    airline_obj = res_for.get("airline", {})
    airline = airline_obj.get("iataCode", "").upper().strip() or None

    raw_fn = str(res_for.get("flightNumber", "")).strip()
    if raw_fn and airline and not raw_fn.upper().startswith(airline):
        flight_number: Optional[str] = f"{airline}{raw_fn}"
    else:
        flight_number = raw_fn.upper() or None

    pnr = item.get("reservationNumber", "").upper().strip() or None

    under_name = item.get("underName", {})
    passenger_name: Optional[str] = None
    if isinstance(under_name, dict):
        passenger_name = under_name.get("name", "").strip() or None

    return ParsedFlight(
        dep_airport=dep,
        arr_airport=arr,
        dep_time=dep_time,
        arr_time=arr_time,
        airline=airline,
        flight_number=flight_number,
        pnr=pnr,
        passenger_name=passenger_name,
        source="jsonld",
    )


# ──────────────────────────── ICS parser ────────────────────────────────────

def extract_ics_flights(ics_content: str) -> list[ParsedFlight]:
    """Parse an ICS calendar string and return any flight-like VEVENTs."""
    try:
        from icalendar import Calendar
    except ImportError:
        logger.warning("icalendar not installed; ICS parsing skipped")
        return []

    flights: list[ParsedFlight] = []
    try:
        cal = Calendar.from_ical(ics_content)
        for component in cal.walk():
            if component.name == "VEVENT":
                f = _vevent_to_flight(component)
                if f:
                    flights.append(f)
    except Exception as exc:
        logger.debug("ICS calendar parse error: %s", exc)
    return flights


def _vevent_to_flight(vevent) -> Optional[ParsedFlight]:
    summary = str(vevent.get("SUMMARY", ""))
    description = str(vevent.get("DESCRIPTION", ""))
    location = str(vevent.get("LOCATION", "")).strip()

    dtstart = vevent.get("DTSTART")
    dtend = vevent.get("DTEND")
    if not dtstart or not dtend:
        return None

    dep_time = dtstart.dt
    arr_time = dtend.dt

    # Require datetime (not date-only)
    if not isinstance(dep_time, datetime):
        return None

    if dep_time.tzinfo is None:
        dep_time = dep_time.replace(tzinfo=timezone.utc)
    if arr_time.tzinfo is None:
        arr_time = arr_time.replace(tzinfo=timezone.utc)

    # Prefer structured fields (summary then location) to avoid noise in description
    airports = _extract_airports(summary.upper())
    if len(airports) < 2:
        airports = _extract_airports(location.upper())
    if len(airports) < 2:
        # Fall back to full combined text
        combined = f"{summary} {description} {location}"
        airports = _extract_airports(combined.upper())

    if len(airports) < 2:
        return None

    dep_airport = airports[0]
    arr_airport = airports[-1]

    # Extract airline + flight number from summary
    airline: Optional[str] = None
    flight_number: Optional[str] = None
    m = _AIRLINE_FLIGHT.search(summary.upper())
    if m and m.group(1) in _KNOWN_AIRLINES:
        airline = m.group(1)
        flight_number = f"{airline}{m.group(2)}"

    return ParsedFlight(
        dep_airport=dep_airport,
        arr_airport=arr_airport,
        dep_time=dep_time,
        arr_time=arr_time,
        airline=airline,
        flight_number=flight_number,
        source="ics",
    )


# ──────────────────────────── heuristic parser ──────────────────────────────

def extract_heuristic_flights(text: str, received_at: Optional[datetime] = None) -> list[ParsedFlight]:
    """Best-effort regex extraction of flight info from plain text."""
    if isinstance(received_at, str):
        received_at = _parse_received_at(received_at)
    text = _unwrap_forwarded(text)
    upper = text.upper()
    flights: list[ParsedFlight] = []
    pnr = _extract_pnr(upper)

    structured = _extract_structured_flight_blocks(text, pnr=pnr)
    if structured:
        return structured

    v5_flights = extract_v5_flights(text, pnr=pnr, received_at=received_at)
    if v5_flights:
        return v5_flights

    itinerary_flights = _extract_itinerary_block_flights(text, pnr=pnr, received_at=received_at)
    if itinerary_flights:
        return itinerary_flights

    for m in _AIRLINE_FLIGHT.finditer(upper):
        if m.group(1) not in _KNOWN_AIRLINES:
            continue
        if m.group(2).startswith("0") and len(m.group(2)) <= 2:
            continue

        airline = m.group(1)
        flight_number = f"{airline}{m.group(2)}"

        # Look at surrounding context for airports and dates
        start = max(0, m.start() - 300)
        end = min(len(upper), m.end() + 300)
        ctx = upper[start:end]
        ctx_orig = text[start:end]

        airports = _extract_airports(ctx)
        if len(airports) < 2:
            continue

        dep_airport = airports[0]
        arr_airport = airports[1]  # second found, not last — avoids junk codes from disclaimers

        dep_time = _first_datetime(ctx_orig)
        arr_time = _last_datetime(ctx_orig)
        if not dep_time or not arr_time:
            continue

        flights.append(ParsedFlight(
            dep_airport=dep_airport,
            arr_airport=arr_airport,
            dep_time=dep_time,
            arr_time=arr_time,
            airline=airline,
            flight_number=flight_number,
            pnr=pnr,
            source="heuristic",
        ))

    return flights


def _extract_itinerary_block_flights(
    text: str,
    *,
    pnr: Optional[str],
    received_at: Optional[datetime],
) -> list[ParsedFlight]:
    """Parse compact itinerary blocks before falling back to loose scanning.

    This layer intentionally requires the full evidence bundle in one local
    block: date, departure time, arrival time, route airports, and flight
    number. That makes it broad enough for portals while keeping marketing
    emails out.
    """
    flights: list[ParsedFlight] = []
    flights.extend(_extract_provider_itinerary_flights(text, pnr=pnr, received_at=received_at))
    flights.extend(_extract_generic_itinerary_block_flights(text, pnr=pnr))
    return _dedupe_flights(flights)


def extract_v5_flights(
    text: str,
    *,
    pnr: Optional[str],
    received_at: Optional[datetime],
) -> list[ParsedFlight]:
    """Generic flight segment extractor based on local evidence scoring.

    v5 does not care which airline or booking site sent the message. It turns
    table-like text into small windows, resolves airports from IATA codes and
    airport/city names, and only accepts a candidate when date, time, route,
    and flight-number evidence agree inside the same local block.
    """
    lines = _normalized_lines(text)
    evidence: list[_FlightEvidence] = []
    evidence.extend(_v5_labeled_itinerary_rows(text))
    evidence.extend(_v5_compact_checkin_rows(text))
    evidence.extend(_v5_route_rows(text, received_at))
    evidence.extend(_v5_city_time_rows(lines))
    evidence.extend(_v5_compact_route_rows(text))
    evidence.extend(_v5_labeled_depart_arrive_rows(text))
    evidence.extend(_v5_inline_blocks(text))
    accepted = [item for item in evidence if item.score >= 7]
    return _dedupe_flights(
        [
            ParsedFlight(
                dep_airport=item.dep_airport,
                arr_airport=item.arr_airport,
                dep_time=item.dep_time,
                arr_time=item.arr_time,
                airline=item.airline,
                flight_number=item.flight_number,
                pnr=pnr,
                source=item.source,
                confidence=min(100, max(0, item.score * 10)),
            )
            for item in accepted
        ]
    )


def _jsonld_should_yield_to_text(
    flights: list[ParsedFlight],
    *,
    subject: Optional[str],
    from_email: Optional[str],
) -> bool:
    context = f"{subject or ''}\n{from_email or ''}".lower()
    if not re.search(r"\b(seatbid|upgrade|biddeal|legroom|extra space|comfier seat)\b", context):
        return False
    return all((flight.arr_time - flight.dep_time) < timedelta(minutes=20) for flight in flights)


def _extract_pnr(text: str) -> Optional[str]:
    for match in _CAPITAL_ONE_AIRLINE_CONFIRMATION.finditer(text):
        candidate = match.group(1).upper()
        if candidate not in _PNR_STOPWORDS and candidate not in _KNOWN_AIRLINES:
            return candidate
    for match in _PNR_LABEL.finditer(text):
        candidate = match.group(1).upper()
        if candidate not in _PNR_STOPWORDS and candidate not in _KNOWN_AIRLINES:
            return candidate
    return None


def _v5_route_rows(text: str, received_at: Optional[datetime]) -> list[_FlightEvidence]:
    rows: list[_FlightEvidence] = []
    if not received_at:
        return rows
    for match in _ROUTE_TABLE_ITINERARY_ROW.finditer(text):
        airline = match.group("airline").upper()
        if airline not in _KNOWN_AIRLINES:
            continue
        dep_airport = match.group("dep_airport").upper()
        arr_airport = match.group("arr_airport").upper()
        if not _valid_route(dep_airport, arr_airport):
            continue
        dep_time = _parse_short_date_time(match.group("date"), match.group("dep_time"), received_at)
        arr_time = _parse_short_date_time(match.group("date"), match.group("arr_time"), received_at)
        if not dep_time or not arr_time:
            continue
        if arr_time <= dep_time:
            arr_time += timedelta(days=1)
        block = _compact_space(match.group(0))
        rows.append(
            _FlightEvidence(
                dep_airport=dep_airport,
                arr_airport=arr_airport,
                dep_time=dep_time,
                arr_time=arr_time,
                airline=airline,
                flight_number=f"{airline}{match.group('number').upper()}",
                score=_v5_score(block, has_airline=True),
            )
        )
    return rows


def _v5_labeled_itinerary_rows(text: str) -> list[_FlightEvidence]:
    rows: list[_FlightEvidence] = []
    for match in _LABELED_ITINERARY_SEGMENT.finditer(text):
        airline = match.group("airline").upper()
        if airline not in _KNOWN_AIRLINES:
            airline = _airline_code_from_name(match.group("airline_name")) or airline
        dep_airport = match.group("dep_airport").upper()
        arr_airport = match.group("arr_airport").upper()
        if airline not in _KNOWN_AIRLINES or not _valid_route(dep_airport, arr_airport):
            continue
        dep_time = _parse_date_time(match.group("date"), match.group("dep_time"))
        arr_time = _parse_date_time(match.group("date"), match.group("arr_time"))
        if not dep_time or not arr_time:
            continue
        if arr_time <= dep_time:
            arr_time += timedelta(days=1)
        block = _compact_space(match.group(0))
        rows.append(
            _FlightEvidence(
                dep_airport=dep_airport,
                arr_airport=arr_airport,
                dep_time=dep_time,
                arr_time=arr_time,
                airline=airline,
                flight_number=f"{airline}{match.group('number').upper()}",
                score=_v5_score(block, has_airline=True) + 1,
            )
        )
    return rows


def _v5_compact_checkin_rows(text: str) -> list[_FlightEvidence]:
    rows: list[_FlightEvidence] = []
    for match in _COMPACT_CHECKIN_ROW.finditer(text):
        airline = match.group("airline").upper()
        dep_airport = match.group("dep_airport").upper()
        arr_airport = match.group("arr_airport").upper()
        if airline not in _KNOWN_AIRLINES or not _valid_route(dep_airport, arr_airport):
            continue
        dep_time = _parse_date_time(match.group("date"), match.group("dep_time"))
        arr_time = _parse_date_time(match.group("date"), match.group("arr_time"))
        if not dep_time or not arr_time:
            continue
        if arr_time <= dep_time:
            arr_time += timedelta(days=1)
        block = _compact_space(match.group(0))
        rows.append(
            _FlightEvidence(
                dep_airport=dep_airport,
                arr_airport=arr_airport,
                dep_time=dep_time,
                arr_time=arr_time,
                airline=airline,
                flight_number=f"{airline}{match.group('number').upper()}",
                score=_v5_score(block, has_airline=True),
            )
        )
    return rows


def _v5_city_time_rows(lines: list[str]) -> list[_FlightEvidence]:
    rows: list[_FlightEvidence] = []
    previous_airline: Optional[str] = None
    date_pattern = re.compile(
        r"^(?:MONDAY|TUESDAY|WEDNESDAY|THURSDAY|FRIDAY|SATURDAY|SUNDAY),?\s+"
        r"(?:JANUARY|FEBRUARY|MARCH|APRIL|MAY|JUNE|JULY|AUGUST|SEPTEMBER|OCTOBER|NOVEMBER|DECEMBER)"
        r"\s+\d{1,2},?\s+\d{4}$",
        re.IGNORECASE,
    )
    for idx, line in enumerate(lines):
        if not date_pattern.match(line):
            continue
        prior_line = lines[idx - 1].lower() if idx > 0 else ""
        if re.search(r"\b(booking|purchase|reservation)\s+date\b", prior_line):
            continue
        date_base = _parse_date_time(line, "12:00 AM")
        if not date_base:
            continue
        next_date_idx = next(
            (
                next_idx
                for next_idx in range(idx + 1, len(lines))
                if date_pattern.match(lines[next_idx])
            ),
            len(lines),
        )
        end_idx = min(next_date_idx, idx + 80)
        cursor = idx + 1
        while cursor < end_idx - 3:
            segment = _city_time_segment_from_lines(
                lines,
                date_base=date_base,
                start=cursor,
                end=end_idx,
                previous_airline=previous_airline,
            )
            if not segment:
                cursor += 1
                continue
            item, next_cursor = segment
            rows.append(item)
            if item.airline:
                previous_airline = item.airline
            cursor = min(end_idx, next_cursor)
    return rows


def _city_time_segment_from_lines(
    lines: list[str],
    *,
    date_base: datetime,
    start: int,
    end: int,
    previous_airline: Optional[str],
) -> Optional[tuple[_FlightEvidence, int]]:
    for dep_place_idx in range(start, end - 3):
        dep_airport = _airport_code_from_place(lines[dep_place_idx])
        dep_clock = _parse_time_line(lines[dep_place_idx + 1])
        if not dep_airport or not dep_clock:
            continue
        for arr_place_idx in range(dep_place_idx + 2, min(end - 1, dep_place_idx + 9)):
            arr_airport = _airport_code_from_place(lines[arr_place_idx])
            arr_clock = _parse_time_line(lines[arr_place_idx + 1])
            if not arr_airport or not arr_clock or not _valid_route(dep_airport, arr_airport):
                continue
            context_start = max(0, dep_place_idx - 10)
            context_end = min(len(lines), arr_place_idx + 12)
            context = "\n".join(lines[context_start:context_end])
            airline, flight_number = _flight_number_from_lines(
                lines,
                start=arr_place_idx + 2,
                end=context_end,
                context=context,
            )
            if not airline and previous_airline and flight_number:
                airline = previous_airline
                flight_number = f"{airline}{flight_number}" if not flight_number.startswith(airline) else flight_number
            if not flight_number:
                continue
            dep_time = datetime.combine(date_base.date(), dep_clock, tzinfo=timezone.utc)
            arr_time = datetime.combine(dep_time.date(), arr_clock, tzinfo=timezone.utc)
            if "+" in lines[arr_place_idx + 1] or arr_time <= dep_time:
                arr_time += timedelta(days=1)
            item = _FlightEvidence(
                dep_airport=dep_airport,
                arr_airport=arr_airport,
                dep_time=dep_time,
                arr_time=arr_time,
                airline=airline,
                flight_number=flight_number,
                score=_v5_score(context, has_airline=bool(airline)),
            )
            return item, arr_place_idx + 2
    return None


def _v5_compact_route_rows(text: str) -> list[_FlightEvidence]:
    rows: list[_FlightEvidence] = []
    previous_arrival: Optional[datetime] = None
    for match in _COMPACT_ROUTE_SEGMENT.finditer(text):
        airline = match.group("airline").upper()
        dep_airport = match.group("dep_airport").upper()
        arr_airport = match.group("arr_airport").upper()
        if airline not in _KNOWN_AIRLINES or not _valid_route(dep_airport, arr_airport):
            continue

        section_date = _nearest_prior_full_date(text, match.start(), max_lookback=260)
        if not section_date and previous_arrival:
            section_date = previous_arrival
        if not section_date:
            continue
        dep_day = section_date
        if previous_arrival:
            dep_clock = _parse_time_only(match.group("dep_time"))
            if dep_clock:
                candidate = datetime.combine(previous_arrival.date(), dep_clock, tzinfo=timezone.utc)
                if section_date.date() <= previous_arrival.date() and candidate >= previous_arrival - timedelta(minutes=5):
                    dep_day = candidate
        dep_time = _parse_date_time(dep_day.strftime("%B %d, %Y"), match.group("dep_time"))
        arr_time = _parse_date_time(dep_day.strftime("%B %d, %Y"), match.group("arr_time"))
        if not dep_time or not arr_time:
            continue
        duration = timedelta(
            hours=int(match.group("duration_h")),
            minutes=int(match.group("duration_m") or 0),
        )
        tail = text[match.end() : match.end() + 90].lower()
        if re.search(r"arrives\s+the\s+next\s+day", tail) or arr_time <= dep_time:
            arr_time = dep_time + duration
        previous_arrival = arr_time
        block = _compact_space(text[max(0, match.start() - 120) : match.end() + 120])
        rows.append(
            _FlightEvidence(
                dep_airport=dep_airport,
                arr_airport=arr_airport,
                dep_time=dep_time,
                arr_time=arr_time,
                airline=airline,
                flight_number=f"{airline}{match.group('number').upper()}",
                score=_v5_score(block, has_airline=True),
            )
        )
    return rows


def _v5_labeled_depart_arrive_rows(text: str) -> list[_FlightEvidence]:
    rows: list[_FlightEvidence] = []
    for section in _SOUTHWEST_FLIGHT_SECTION.finditer(text):
        section_date = _parse_southwest_date(section.group("date"))
        if not section_date:
            continue
        context = text[max(0, section.start() - 500) : section.end()]
        airline = _infer_airline_from_context(context)
        if not airline:
            continue
        previous_arrival: Optional[datetime] = None
        for match in _SOUTHWEST_SEGMENT.finditer(section.group("body")):
            dep_airport = match.group("dep_airport").upper()
            arr_airport = match.group("arr_airport").upper()
            if not _valid_route(dep_airport, arr_airport):
                continue
            dep_time = _parse_date_time(
                section_date.strftime("%B %d, %Y"),
                _marked_clock(match, "dep"),
            )
            arr_time = _parse_date_time(
                section_date.strftime("%B %d, %Y"),
                _marked_clock(match, "arr"),
            )
            if not dep_time or not arr_time:
                continue
            if previous_arrival:
                while dep_time < previous_arrival - timedelta(minutes=5):
                    dep_time += timedelta(days=1)
                    arr_time += timedelta(days=1)
            if arr_time <= dep_time:
                arr_time += timedelta(days=1)
            previous_arrival = arr_time
            number = match.group("number").upper()
            block = _compact_space(context[max(0, match.start() - 80) : match.end() + 80])
            rows.append(
                _FlightEvidence(
                    dep_airport=dep_airport,
                    arr_airport=arr_airport,
                    dep_time=dep_time,
                    arr_time=arr_time,
                    airline=airline,
                    flight_number=f"{airline}{number}" if airline else number,
                    score=_v5_score(block, has_airline=bool(airline)),
                )
            )
    return rows


def _v5_inline_blocks(text: str) -> list[_FlightEvidence]:
    rows: list[_FlightEvidence] = []
    for match in _GENERIC_ITINERARY_BLOCK.finditer(text):
        airline = match.group("airline").upper()
        dep_airport = match.group("dep_airport").upper()
        arr_airport = match.group("arr_airport").upper()
        if airline not in _KNOWN_AIRLINES or not _valid_route(dep_airport, arr_airport):
            continue
        dep_time = _parse_date_time(match.group("date"), match.group("dep_time"))
        arr_time = _parse_date_time(match.group("date"), match.group("arr_time"))
        if not dep_time or not arr_time:
            continue
        block = _compact_space(match.group(0))
        if arr_time <= dep_time or "+1 day arrival" in block.lower():
            arr_time += timedelta(days=1)
        rows.append(
            _FlightEvidence(
                dep_airport=dep_airport,
                arr_airport=arr_airport,
                dep_time=dep_time,
                arr_time=arr_time,
                airline=airline,
                flight_number=f"{airline}{match.group('number').upper()}",
                score=_v5_score(block, has_airline=True),
            )
        )
    return rows


def _v5_score(block: str, *, has_airline: bool) -> int:
    normalized = block.lower()
    score = 8
    if has_airline:
        score += 1
    if re.search(r"\b(itinerary|confirmation|reservation|ticket|flight|flt|depart|arriv|route)\b", normalized):
        score += 2
    if re.search(r"\b(nonstop|layover|duration|terminal|passenger|operated by)\b", normalized):
        score += 1
    if re.search(r"\b(first bag|second bag|weight per bag|bag charges|baggage policy)\b", normalized):
        score -= 6
    if re.search(r"\b(hotel|check-in|check-out|rental car|privacy policy|terms and conditions)\b", normalized):
        score -= 3
    if re.search(r"\b(sale|deal|promo|save up to|destinations)\b", normalized):
        score -= 2
    return score


def _extract_structured_flight_blocks(text: str, pnr: Optional[str]) -> list[ParsedFlight]:
    flights: list[ParsedFlight] = []
    for match in _STRUCTURED_FLIGHT_BLOCK.finditer(text):
        airline = match.group("airline").upper()
        if airline not in _KNOWN_AIRLINES:
            continue
        dep_airport = match.group("dep_airport").upper()
        arr_airport = match.group("arr_airport").upper()
        if _VALID_IATA and (dep_airport not in _VALID_IATA or arr_airport not in _VALID_IATA):
            continue

        dep_time = _parse_labeled_datetime(match.group("dep_date"), match.group("dep_clock"))
        arr_time = _parse_labeled_datetime(match.group("arr_date"), match.group("arr_clock"))
        if not dep_time or not arr_time:
            continue

        number = match.group("number").upper()
        flights.append(
            ParsedFlight(
                dep_airport=dep_airport,
                arr_airport=arr_airport,
                dep_time=dep_time,
                arr_time=arr_time,
                airline=airline,
                flight_number=f"{airline}{number}",
                pnr=pnr,
                source="heuristic",
            )
        )
    return flights


def _extract_provider_itinerary_flights(
    text: str,
    *,
    pnr: Optional[str],
    received_at: Optional[datetime],
) -> list[ParsedFlight]:
    flights: list[ParsedFlight] = []
    flights.extend(_extract_airasia_notice_flights(text, pnr))
    flights.extend(_extract_iberia_detail_flights(text, pnr))
    flights.extend(_extract_compact_route_flights(text, pnr))
    flights.extend(_extract_named_airline_flights(text, pnr, received_at))
    flights.extend(_extract_priceline_route_flights(text, pnr, received_at))
    flights.extend(_extract_southwest_itinerary_flights(text, pnr))
    flights.extend(_extract_route_table_itinerary_flights(text, pnr, received_at))
    flights.extend(_extract_aa_inline_receipt_flights(text, pnr))
    flights.extend(_extract_aa_hold_table_flights(text, pnr, received_at))
    flights.extend(_extract_partner_award_flights(text, pnr, received_at))
    flights.extend(_extract_airline_route_flight_flights(text, pnr, received_at))
    flights.extend(_extract_arrives_route_flights(text, pnr, received_at))
    flights.extend(_extract_city_table_itinerary_flights(text, pnr))
    return _dedupe_flights(flights)


def _extract_generic_itinerary_block_flights(text: str, pnr: Optional[str]) -> list[ParsedFlight]:
    flights: list[ParsedFlight] = []
    for match in _GENERIC_ITINERARY_BLOCK.finditer(text):
        airline = match.group("airline").upper()
        dep_airport = match.group("dep_airport").upper()
        arr_airport = match.group("arr_airport").upper()
        if airline not in _KNOWN_AIRLINES or not _valid_route(dep_airport, arr_airport):
            continue

        # Reject blocks where the airport codes only appear in baggage/policy tables.
        block = " ".join(match.group(0).split())
        if re.search(r"\b(first bag|second bag|weight per bag|baggage|bag charges)\b", block, re.IGNORECASE):
            continue
        if not re.search(r"\b(flight|nonstop|depart|arriv|duration|travel time)\b", block, re.IGNORECASE):
            continue

        dep_time = _parse_date_time(match.group("date"), match.group("dep_time"))
        arr_time = _parse_date_time(match.group("date"), match.group("arr_time"))
        if not dep_time or not arr_time:
            continue

        if "+1 day arrival" in block.lower() or arr_time <= dep_time:
            arr_time += timedelta(days=1)

        flights.append(
            ParsedFlight(
                dep_airport=dep_airport,
                arr_airport=arr_airport,
                dep_time=dep_time,
                arr_time=arr_time,
                airline=airline,
                flight_number=f"{airline}{match.group('number').upper()}",
                pnr=pnr,
                source="heuristic",
            )
        )
    return flights


def _extract_airasia_notice_flights(text: str, pnr: Optional[str]) -> list[ParsedFlight]:
    flights: list[ParsedFlight] = []
    search_text = text
    new_schedule_at = text.lower().rfind("new schedule")
    if new_schedule_at >= 0:
        search_text = text[new_schedule_at:]
    for match in _AIRASIA_NOTICE_BLOCK.finditer(search_text):
        airline = match.group("airline").upper()
        dep_airport = match.group("dep_airport").upper()
        arr_airport = match.group("arr_airport").upper()
        if not _valid_route(dep_airport, arr_airport):
            continue
        dep_time = _parse_date_time(match.group("date"), match.group("dep_time"))
        arr_time = _parse_date_time(match.group("date"), match.group("arr_time"))
        if not dep_time or not arr_time:
            continue
        if arr_time < dep_time:
            arr_time += timedelta(days=1)
        flights.append(
            ParsedFlight(
                dep_airport=dep_airport,
                arr_airport=arr_airport,
                dep_time=dep_time,
                arr_time=arr_time,
                airline=airline,
                flight_number=f"{airline}{match.group('number').upper()}",
                pnr=pnr,
                source="heuristic",
            )
        )
    return flights


def _extract_iberia_detail_flights(text: str, pnr: Optional[str]) -> list[ParsedFlight]:
    flights: list[ParsedFlight] = []
    for match in _IBERIA_DETAIL_SEGMENT.finditer(text):
        dep_airport = match.group("dep_airport").upper()
        arr_airport = match.group("arr_airport").upper()
        if not _valid_route(dep_airport, arr_airport):
            continue
        dep_time = _parse_date_time(match.group("dep_date"), match.group("dep_time"))
        arr_time = _parse_date_time(match.group("arr_date"), match.group("arr_time"))
        if not dep_time or not arr_time:
            continue
        flights.append(
            ParsedFlight(
                dep_airport=dep_airport,
                arr_airport=arr_airport,
                dep_time=dep_time,
                arr_time=arr_time,
                airline="IB",
                flight_number=match.group("flight_number").upper(),
                pnr=pnr,
                source="heuristic",
            )
        )
    return flights


def _extract_compact_route_flights(text: str, pnr: Optional[str]) -> list[ParsedFlight]:
    flights: list[ParsedFlight] = []
    previous_arrival: Optional[datetime] = None
    for match in _COMPACT_ROUTE_SEGMENT.finditer(text):
        airline = match.group("airline").upper()
        dep_airport = match.group("dep_airport").upper()
        arr_airport = match.group("arr_airport").upper()
        if airline not in _KNOWN_AIRLINES or not _valid_route(dep_airport, arr_airport):
            continue

        section_date = _nearest_prior_full_date(text, match.start())
        if not section_date and previous_arrival:
            section_date = previous_arrival
        if not section_date:
            continue
        dep_day = section_date
        if previous_arrival:
            dep_clock = _parse_time_only(match.group("dep_time"))
            if dep_clock:
                candidate = datetime.combine(previous_arrival.date(), dep_clock, tzinfo=timezone.utc)
                if section_date.date() <= previous_arrival.date() and candidate >= previous_arrival - timedelta(minutes=5):
                    dep_day = candidate
        dep_time = _parse_date_time(dep_day.strftime("%B %d, %Y"), match.group("dep_time"))
        arr_time = _parse_date_time(dep_day.strftime("%B %d, %Y"), match.group("arr_time"))
        if not dep_time or not arr_time:
            continue
        duration = timedelta(
            hours=int(match.group("duration_h")),
            minutes=int(match.group("duration_m") or 0),
        )
        segment_tail = text[match.end() : match.end() + 90].lower()
        if re.search(r"arrives\s+the\s+next\s+day", segment_tail) or arr_time <= dep_time:
            arr_time = dep_time + duration
        previous_arrival = arr_time
        flights.append(
            ParsedFlight(
                dep_airport=dep_airport,
                arr_airport=arr_airport,
                dep_time=dep_time,
                arr_time=arr_time,
                airline=airline,
                flight_number=f"{airline}{match.group('number').upper()}",
                pnr=pnr,
                source="heuristic",
            )
        )
    return flights


def _extract_named_airline_flights(
    text: str,
    pnr: Optional[str],
    received_at: Optional[datetime],
) -> list[ParsedFlight]:
    flights: list[ParsedFlight] = []
    for match in _NAMED_AIRLINE_SEGMENT.finditer(text):
        airline = _airline_code_from_name(match.group("airline_name"))
        dep_airport = match.group("dep_airport").upper()
        arr_airport = match.group("arr_airport").upper()
        if not airline or not _valid_route(dep_airport, arr_airport):
            continue
        dep_time = _parse_partial_date_time(
            match.group("dep_month"),
            match.group("dep_day"),
            match.group("dep_time"),
            received_at,
        )
        arr_time = _parse_partial_date_time(
            match.group("arr_month"),
            match.group("arr_day"),
            match.group("arr_time"),
            received_at,
        )
        if not dep_time or not arr_time:
            continue
        if arr_time < dep_time:
            arr_time = arr_time.replace(year=dep_time.year)
            if arr_time < dep_time:
                arr_time += timedelta(days=1)
        flights.append(
            ParsedFlight(
                dep_airport=dep_airport,
                arr_airport=arr_airport,
                dep_time=dep_time,
                arr_time=arr_time,
                airline=airline,
                flight_number=f"{airline}{match.group('number').upper()}",
                pnr=pnr,
                source="heuristic",
            )
        )
    return flights


def _extract_priceline_route_flights(
    text: str,
    pnr: Optional[str],
    received_at: Optional[datetime],
) -> list[ParsedFlight]:
    flights: list[ParsedFlight] = []
    previous_arrival: Optional[datetime] = None
    for match in _PRICELINE_ROUTE_SEGMENT.finditer(text):
        airline = _airline_code_from_name(match.group("airline_name"))
        dep_airport = match.group("dep_airport").upper()
        arr_airport = match.group("arr_airport").upper()
        if not airline or not _valid_route(dep_airport, arr_airport):
            continue
        header = _nearest_prior_day_header(text, match.start())
        if not header:
            continue
        dep_time = _parse_partial_date_time(header.group("month"), header.group("day"), match.group("dep_time"), received_at)
        arr_time = _parse_partial_date_time(header.group("month"), header.group("day"), match.group("arr_time"), received_at)
        if not dep_time or not arr_time:
            continue
        if previous_arrival:
            while dep_time < previous_arrival - timedelta(minutes=5):
                dep_time += timedelta(days=1)
                arr_time += timedelta(days=1)
        if "overnight flight" in match.group("body").lower() or arr_time < dep_time:
            arr_time += timedelta(days=1)
        previous_arrival = arr_time
        flights.append(
            ParsedFlight(
                dep_airport=dep_airport,
                arr_airport=arr_airport,
                dep_time=dep_time,
                arr_time=arr_time,
                airline=airline,
                flight_number=f"{airline}{match.group('number').upper()}",
                pnr=pnr,
                source="heuristic",
            )
        )
    return flights


def _extract_southwest_itinerary_flights(text: str, pnr: Optional[str]) -> list[ParsedFlight]:
    flights: list[ParsedFlight] = []
    for section in _SOUTHWEST_FLIGHT_SECTION.finditer(text):
        section_date = _parse_southwest_date(section.group("date"))
        if not section_date:
            continue
        previous_arrival: Optional[datetime] = None
        for match in _SOUTHWEST_SEGMENT.finditer(section.group("body")):
            dep_airport = match.group("dep_airport").upper()
            arr_airport = match.group("arr_airport").upper()
            if not _valid_route(dep_airport, arr_airport):
                continue
            dep_time = _parse_date_time(section_date.strftime("%B %d, %Y"), _marked_clock(match, "dep"))
            arr_time = _parse_date_time(section_date.strftime("%B %d, %Y"), _marked_clock(match, "arr"))
            if not dep_time or not arr_time:
                continue
            if previous_arrival:
                while dep_time < previous_arrival - timedelta(minutes=5):
                    dep_time += timedelta(days=1)
                    arr_time += timedelta(days=1)
            if arr_time < dep_time:
                arr_time += timedelta(days=1)
            previous_arrival = arr_time
            flights.append(
                ParsedFlight(
                    dep_airport=dep_airport,
                    arr_airport=arr_airport,
                    dep_time=dep_time,
                    arr_time=arr_time,
                    airline="WN",
                    flight_number=f"WN{match.group('number').upper()}",
                    pnr=pnr,
                    source="heuristic",
                )
            )
    return _dedupe_repeated_flight_copies(flights)


def _extract_aa_inline_receipt_flights(text: str, pnr: Optional[str]) -> list[ParsedFlight]:
    flights: list[ParsedFlight] = []
    for match in _AA_INLINE_RECEIPT_SEGMENT.finditer(text):
        airline = match.group("airline").upper()
        if airline not in _KNOWN_AIRLINES:
            continue
        dep_airport = match.group("dep_airport").upper()
        arr_airport = match.group("arr_airport").upper()
        if not _valid_route(dep_airport, arr_airport):
            continue
        section_date = _nearest_prior_full_date(text, match.start())
        if not section_date:
            continue
        dep_time = _parse_date_time(section_date.strftime("%B %d, %Y"), match.group("dep_time"))
        arr_time = _parse_date_time(section_date.strftime("%B %d, %Y"), match.group("arr_time"))
        if not dep_time or not arr_time:
            continue
        if arr_time <= dep_time:
            arr_time += timedelta(days=1)
        flights.append(
            ParsedFlight(
                dep_airport=dep_airport,
                arr_airport=arr_airport,
                dep_time=dep_time,
                arr_time=arr_time,
                airline=airline,
                flight_number=f"{airline}{match.group('number').upper()}",
                pnr=pnr,
                source="heuristic",
            )
        )
    return flights


def _extract_aa_hold_table_flights(
    text: str,
    pnr: Optional[str],
    received_at: Optional[datetime],
) -> list[ParsedFlight]:
    flights: list[ParsedFlight] = []
    for match in _AA_HOLD_TABLE_SEGMENT.finditer(text):
        airline = _airline_code_from_name(match.group("airline_name"))
        if airline not in _KNOWN_AIRLINES:
            continue
        dep_airport = _airport_code_from_place(match.group("dep_place"))
        arr_airport = _airport_code_from_place(match.group("arr_place"))
        if not dep_airport or not arr_airport or not _valid_route(dep_airport, arr_airport):
            continue
        dep_time = _parse_short_date_time(match.group("dep_date"), match.group("dep_time"), received_at)
        arr_time = _parse_short_date_time(match.group("arr_date"), match.group("arr_time"), received_at)
        if not dep_time or not arr_time:
            continue
        if arr_time <= dep_time:
            arr_time += timedelta(days=1)
        flights.append(
            ParsedFlight(
                dep_airport=dep_airport,
                arr_airport=arr_airport,
                dep_time=dep_time,
                arr_time=arr_time,
                airline=airline,
                flight_number=f"{airline}{match.group('number').upper()}",
                pnr=pnr,
                source="heuristic",
            )
        )
    return flights


def _extract_partner_award_flights(
    text: str,
    pnr: Optional[str],
    received_at: Optional[datetime],
) -> list[ParsedFlight]:
    flights: list[ParsedFlight] = []
    for match in _PARTNER_AWARD_SEGMENT.finditer(text):
        airline = _airline_code_from_name(match.group("airline_name"))
        dep_airport = match.group("dep_airport").upper()
        arr_airport = match.group("arr_airport").upper()
        if airline not in _KNOWN_AIRLINES or not _valid_route(dep_airport, arr_airport):
            continue
        dep_time = _parse_short_date_time(match.group("dep_date"), match.group("dep_time"), received_at)
        arr_time = _parse_short_date_time(match.group("arr_date"), match.group("arr_time"), received_at)
        if not dep_time or not arr_time:
            continue
        if arr_time <= dep_time:
            arr_time += timedelta(days=1)
        flights.append(
            ParsedFlight(
                dep_airport=dep_airport,
                arr_airport=arr_airport,
                dep_time=dep_time,
                arr_time=arr_time,
                airline=airline,
                flight_number=f"{airline}{match.group('number').upper()}",
                pnr=pnr,
                source="heuristic",
            )
        )
    return flights


def _extract_airline_route_flight_flights(
    text: str,
    pnr: Optional[str],
    received_at: Optional[datetime],
) -> list[ParsedFlight]:
    flights: list[ParsedFlight] = []
    airline = _infer_airline_from_context(text)
    if airline not in _KNOWN_AIRLINES:
        return flights
    for match in _AIRLINE_ROUTE_FLIGHT_SEGMENT.finditer(text):
        dep_airport = match.group("dep_airport").upper()
        arr_airport = match.group("arr_airport").upper()
        if not _valid_route(dep_airport, arr_airport):
            continue
        dep_time = _parse_short_date_time(match.group("dep_date"), match.group("dep_time"), received_at)
        arr_time = _parse_short_date_time(match.group("arr_date"), match.group("arr_time"), received_at)
        if not dep_time or not arr_time:
            continue
        if arr_time <= dep_time:
            arr_time += timedelta(days=1)
        flights.append(
            ParsedFlight(
                dep_airport=dep_airport,
                arr_airport=arr_airport,
                dep_time=dep_time,
                arr_time=arr_time,
                airline=airline,
                flight_number=f"{airline}{match.group('number').upper()}",
                pnr=pnr,
                source="heuristic",
            )
        )
    return flights


def _extract_arrives_route_flights(
    text: str,
    pnr: Optional[str],
    received_at: Optional[datetime],
) -> list[ParsedFlight]:
    flights: list[ParsedFlight] = []
    if not received_at:
        return flights
    for match in _ARRIVES_ROUTE_SEGMENT.finditer(text):
        airline = match.group("airline").upper()
        if airline not in _KNOWN_AIRLINES:
            continue
        dep_airport = match.group("dep_airport").upper()
        arr_airport = (match.group("arr_airport_paren") or match.group("arr_airport")).upper()
        if not _valid_route(dep_airport, arr_airport):
            continue
        dep_time = _parse_partial_date_time(
            match.group("month"),
            match.group("day"),
            match.group("dep_time"),
            received_at,
        )
        arr_time = _parse_partial_date_time(
            match.group("month"),
            match.group("day"),
            match.group("arr_time"),
            received_at,
        )
        if not dep_time or not arr_time:
            continue
        if arr_time <= dep_time:
            arr_time += timedelta(days=1)
        flights.append(
            ParsedFlight(
                dep_airport=dep_airport,
                arr_airport=arr_airport,
                dep_time=dep_time,
                arr_time=arr_time,
                airline=airline,
                flight_number=f"{airline}{match.group('number').upper()}",
                pnr=pnr,
                source="heuristic",
            )
        )
    return flights


def _extract_route_table_itinerary_flights(
    text: str,
    pnr: Optional[str],
    received_at: Optional[datetime],
) -> list[ParsedFlight]:
    flights: list[ParsedFlight] = []
    if not received_at:
        return flights
    for match in _ROUTE_TABLE_ITINERARY_ROW.finditer(text):
        airline = match.group("airline").upper()
        if airline not in _KNOWN_AIRLINES:
            continue
        dep_airport = match.group("dep_airport").upper()
        arr_airport = match.group("arr_airport").upper()
        if not _valid_route(dep_airport, arr_airport):
            continue
        dep_time = _parse_short_date_time(match.group("date"), match.group("dep_time"), received_at)
        arr_time = _parse_short_date_time(match.group("date"), match.group("arr_time"), received_at)
        if not dep_time or not arr_time:
            continue
        if arr_time <= dep_time:
            arr_time += timedelta(days=1)
        flights.append(
            ParsedFlight(
                dep_airport=dep_airport,
                arr_airport=arr_airport,
                dep_time=dep_time,
                arr_time=arr_time,
                airline=airline,
                flight_number=f"{airline}{match.group('number').upper()}",
                pnr=pnr,
                source="heuristic",
            )
        )
    return flights


def _extract_city_table_itinerary_flights(text: str, pnr: Optional[str]) -> list[ParsedFlight]:
    flights: list[ParsedFlight] = []
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    date_pattern = re.compile(
        r"^(?:MONDAY|TUESDAY|WEDNESDAY|THURSDAY|FRIDAY|SATURDAY|SUNDAY),?\s+"
        r"(?:JANUARY|FEBRUARY|MARCH|APRIL|MAY|JUNE|JULY|AUGUST|SEPTEMBER|OCTOBER|NOVEMBER|DECEMBER)"
        r"\s+\d{1,2},?\s+\d{4}$",
        re.IGNORECASE,
    )
    for idx, line in enumerate(lines):
        if not date_pattern.match(line):
            continue
        context = "\n".join(lines[max(0, idx - 25) : min(len(lines), idx + 25)])
        airline = _infer_airline_from_context(context)
        try:
            dep_city = lines[idx + 3]
            dep_clock = lines[idx + 4]
            arr_city = lines[idx + 6]
            arr_clock_raw = lines[idx + 7]
        except IndexError:
            continue
        dep_airport = _airport_code_from_place(dep_city)
        arr_airport = _airport_code_from_place(arr_city)
        if not dep_airport or not arr_airport or not _valid_route(dep_airport, arr_airport):
            continue

        number: Optional[str] = None
        for candidate in lines[idx + 8 : idx + 15]:
            if re.fullmatch(r"\d{1,4}[A-Z]?", candidate, flags=re.IGNORECASE):
                number = candidate.upper()
                break
        if not number:
            continue

        arr_next_day = "+" in arr_clock_raw
        arr_clock = arr_clock_raw.replace("+", "").strip()
        dep_time = _parse_date_time(line, dep_clock)
        arr_time = _parse_date_time(line, arr_clock)
        if not dep_time or not arr_time:
            continue
        if arr_next_day or arr_time <= dep_time:
            arr_time += timedelta(days=1)

        flights.append(
            ParsedFlight(
                dep_airport=dep_airport,
                arr_airport=arr_airport,
                dep_time=dep_time,
                arr_time=arr_time,
                airline=airline,
                flight_number=f"{airline}{number}" if airline else number,
                pnr=pnr,
                source="heuristic",
            )
        )
    return flights


def _parse_labeled_datetime(date_part: str, time_part: str) -> Optional[datetime]:
    raw = f"{date_part} {time_part}"
    formats = [
        "%a, %b %d, %Y %I:%M %p",
        "%a, %B %d, %Y %I:%M %p",
        "%a %b %d, %Y %I:%M %p",
        "%a %B %d, %Y %I:%M %p",
        "%b %d, %Y %I:%M %p",
        "%B %d, %Y %I:%M %p",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


# ──────────────────────────── identity check ────────────────────────────────

def check_identity(
    passenger_name: Optional[str],
    user_name: str,
    aliases: list[str],
) -> MessageStatus:
    """Return ACCEPTED if passenger_name fuzzy-matches user (token_set_ratio >= 85)."""
    if not passenger_name:
        return MessageStatus.REVIEW_REQUIRED

    candidates = [c for c in [user_name] + aliases if c]
    if not candidates:
        return MessageStatus.ACCEPTED  # nothing to check against

    for candidate in candidates:
        score = fuzz.token_set_ratio(passenger_name.lower(), candidate.lower())
        if score >= 85:
            return MessageStatus.ACCEPTED

    return MessageStatus.REVIEW_REQUIRED


# ──────────────────────────── helpers ───────────────────────────────────────

_AIRLINE_NAME_TO_CODE = {
    "american airlines": "AA",
    "american": "AA",
    "united airlines": "UA",
    "delta air lines": "DL",
    "delta airlines": "DL",
    "iberia": "IB",
    "ana": "NH",
    "airasia": "Z2",
    "air asia": "Z2",
    "volaris": "Y4",
    "aeromexico": "AM",
    "aeromexico connect": "AM",
    "spirit airlines": "NK",
    "spirit": "NK",
    "southwest airlines": "WN",
    "southwest": "WN",
    "jetblue airways": "B6",
    "jetblue": "B6",
    "qantas": "QF",
    "eva air": "BR",
    "ethiopian airlines": "ET",
}

_PLACE_AIRPORT_OVERRIDES = {
    "DALLAS FORT WORTH TX": "DFW",
    "DALLAS/FORT WORTH TX": "DFW",
    "FORT LAUDERDALE FL": "FLL",
    "MANAGUA NICARAGUA": "MGA",
    "MEXICO CITY MEXICO": "MEX",
    "HOUSTON TX": "IAH",
    "NASHVILLE": "BNA",
    "NASHVILLE TN": "BNA",
    "NASHVILLE TENNESSEE": "BNA",
    "ORLANDO": "MCO",
    "ORLANDO FL": "MCO",
    "ORLANDO FLORIDA": "MCO",
    "ATLANTA GA": "ATL",
    "BALTIMORE MD": "BWI",
}
_CITY_AIRPORT_LOOKUP: Optional[dict[str, str]] = None


def _valid_route(dep_airport: str, arr_airport: str) -> bool:
    if dep_airport == arr_airport:
        return False
    if _VALID_IATA and (dep_airport not in _VALID_IATA or arr_airport not in _VALID_IATA):
        return False
    return True


def _airline_code_from_name(name: str) -> Optional[str]:
    normalized = re.sub(r"\s+", " ", name).strip().lower()
    if normalized in _AIRLINE_NAME_TO_CODE:
        return _AIRLINE_NAME_TO_CODE[normalized]
    for key, code in _AIRLINE_NAME_TO_CODE.items():
        if key in normalized:
            return code
    return None


def _infer_airline_from_context(context: str) -> Optional[str]:
    normalized = re.sub(r"\s+", " ", context).strip().lower()
    compact = re.sub(r"[^a-z0-9]+", "", normalized)
    for key, code in sorted(_AIRLINE_NAME_TO_CODE.items(), key=lambda item: len(item[0]), reverse=True):
        if re.search(rf"\b{re.escape(key)}\b", normalized):
            return code
        compact_key = re.sub(r"[^a-z0-9]+", "", key)
        if len(compact_key) >= 6 and compact_key in compact:
            return code
    return None


def _flight_number_from_lines(
    lines: list[str],
    *,
    start: int,
    end: int,
    context: str,
) -> tuple[Optional[str], Optional[str]]:
    airline = _infer_airline_from_context(context)
    for line in lines[start:end]:
        match = _AIRLINE_FLIGHT.search(line.upper())
        if match and match.group(1) in _KNOWN_AIRLINES:
            code = match.group(1)
            return code, f"{code}{match.group(2).upper()}"
    for line in lines[start:end]:
        if re.fullmatch(r"\d{1,4}[A-Z]?", line.strip(), flags=re.IGNORECASE):
            number = line.strip().upper()
            return airline, f"{airline}{number}" if airline else number
    return None, None


def _parse_time_line(line: str) -> Optional[datetime.time]:
    clean = line.replace("+", "").strip()
    if not re.fullmatch(r"\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)", clean):
        return None
    return _parse_time_only(clean)


def _nearest_place_airport(lines: list[str], *, start: int, end: int) -> Optional[str]:
    for line in reversed(lines[start:end]):
        if _parse_time_line(line):
            continue
        code = _airport_code_from_place(line)
        if code:
            return code
        airports = _extract_airports(line)
        if len(airports) == 1:
            return airports[0]
    return None


def _airport_code_from_place(place: str) -> Optional[str]:
    direct = re.search(r"\(([A-Z]{3})\)", place.upper())
    if direct:
        code = direct.group(1)
        if _VALID_IATA and code not in _VALID_IATA:
            return None
        return code
    normalized = _normalize_place_key(place)
    if normalized in _PLACE_AIRPORT_OVERRIDES:
        return _PLACE_AIRPORT_OVERRIDES[normalized]
    lookup = _city_airport_lookup()
    if normalized in lookup:
        return lookup[normalized]
    without_region = re.sub(r"\s+[A-Z]{2}$", "", normalized)
    if without_region != normalized:
        return lookup.get(without_region)
    return None


def _city_airport_lookup() -> dict[str, str]:
    global _CITY_AIRPORT_LOOKUP
    if _CITY_AIRPORT_LOOKUP is not None:
        return _CITY_AIRPORT_LOOKUP
    candidates: dict[str, set[str]] = {}
    try:
        import airportsdata

        for code, airport in airportsdata.load("IATA").items():
            city = airport.get("city") or ""
            name = airport.get("name") or ""
            if not city:
                continue
            subd = airport.get("subd") or ""
            country = airport.get("country") or ""
            for key in {
                _normalize_place_key(city),
                _normalize_place_key(name),
                _normalize_place_key(f"{city} {subd}"),
                _normalize_place_key(f"{city} {country}"),
                _normalize_place_key(f"{city} {subd} {country}"),
                _normalize_place_key(f"{city} {name}"),
            }:
                if key:
                    candidates.setdefault(key, set()).add(code)
    except Exception:
        candidates = {}
    _CITY_AIRPORT_LOOKUP = {
        key: next(iter(codes))
        for key, codes in candidates.items()
        if len(codes) == 1
    }
    _CITY_AIRPORT_LOOKUP.update(_PLACE_AIRPORT_OVERRIDES)
    return _CITY_AIRPORT_LOOKUP


def _normalize_place_key(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9/ ]+", " ", ascii_value.upper())).strip()


def _normalized_lines(text: str) -> list[str]:
    text = _URL_RE.sub(" ", text)
    text = unicodedata.normalize("NFKC", text)
    return [_compact_space(line) for line in text.splitlines() if _compact_space(line)]


def _compact_space(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("\xa0", " ")).strip()


def _dedupe_flights(flights: list[ParsedFlight]) -> list[ParsedFlight]:
    by_key: dict[tuple[str, str, str, str], ParsedFlight] = {}
    for flight in flights:
        key = (
            flight.dep_airport,
            flight.arr_airport,
            flight.dep_time.isoformat(),
            flight.flight_number or "",
        )
        by_key[key] = _better_flight(by_key.get(key), flight)

    by_identity: dict[tuple[str, str, str], ParsedFlight] = {}
    for flight in by_key.values():
        if not flight.flight_number:
            identity = (flight.dep_airport, flight.arr_airport, flight.dep_time.isoformat())
        else:
            identity = (flight.dep_airport, flight.arr_airport, flight.flight_number)
        by_identity[identity] = _better_flight(by_identity.get(identity), flight)

    return sorted(by_identity.values(), key=lambda item: item.dep_time)


def _better_flight(current: Optional[ParsedFlight], candidate: ParsedFlight) -> ParsedFlight:
    if current is None:
        return candidate

    def quality(flight: ParsedFlight) -> tuple[int, float, int, float]:
        duration = max(0.0, (flight.arr_time - flight.dep_time).total_seconds())
        plausible = 20 * 60 <= duration <= 20 * 60 * 60
        confidence = getattr(flight, "confidence", None) or 0
        return (
            1 if plausible else 0,
            -duration if plausible else duration,
            confidence,
            -flight.dep_time.timestamp(),
        )

    return candidate if quality(candidate) > quality(current) else current


def _dedupe_repeated_flight_copies(flights: list[ParsedFlight]) -> list[ParsedFlight]:
    by_key: dict[tuple[str, str, str, str], ParsedFlight] = {}
    for flight in sorted(flights, key=lambda item: item.dep_time):
        key = (
            flight.dep_airport,
            flight.arr_airport,
            flight.flight_number or "",
            flight.pnr or "",
        )
        by_key.setdefault(key, flight)
    return sorted(by_key.values(), key=lambda item: item.dep_time)


def _parse_received_at(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = parsedate_to_datetime(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _parse_time_only(value: str) -> Optional[datetime.time]:
    clean = (
        value.strip()
        .replace("*", "")
        .replace("a.m.", "AM")
        .replace("p.m.", "PM")
        .replace("am", "AM")
        .replace("pm", "PM")
    )
    clean = re.sub(r"(?i)(\d)(AM|PM)$", r"\1 \2", clean)
    for fmt in ("%I:%M %p", "%H:%M"):
        try:
            return datetime.strptime(clean, fmt).time()
        except ValueError:
            continue
    return None


def _parse_date_time(date_part: str, time_part: str) -> Optional[datetime]:
    clean_date = re.sub(r"\s*-\s*", " ", date_part.strip())
    clean_date = re.sub(r",", "", clean_date)
    clean_time = (
        time_part.strip()
        .replace("*", "")
        .replace("a.m.", "AM")
        .replace("p.m.", "PM")
        .replace("am", "AM")
        .replace("pm", "PM")
    )
    clean_time = re.sub(r"(?i)(\d)(AM|PM)$", r"\1 \2", clean_time)
    raw = f"{clean_date} {clean_time}"
    formats = [
        "%B %d %Y %I:%M %p",
        "%b %d %Y %I:%M %p",
        "%d %b %Y %I:%M %p",
        "%d %B %Y %I:%M %p",
        "%A %d %B %Y %H:%M",
        "%A %d %B %Y %I:%M %p",
        "%A %B %d %Y %H:%M",
        "%A %B %d %Y %I:%M %p",
        "%a %b %d %Y %I:%M %p",
        "%a %B %d %Y %I:%M %p",
        "%B %d %Y %H:%M",
        "%b %d %Y %H:%M",
        "%d %b %Y %H:%M",
        "%d %B %Y %H:%M",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _parse_short_date_time(
    date_part: str,
    time_part: str,
    received_at: Optional[datetime],
) -> Optional[datetime]:
    if not received_at:
        return None
    match = re.search(
        r"(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun),?\s+"
        r"(?P<month>Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+"
        r"(?P<day>\d{1,2})",
        date_part,
        re.IGNORECASE,
    )
    if not match:
        return None
    return _parse_partial_date_time(match.group("month"), match.group("day"), time_part, received_at)


def _parse_southwest_date(value: str) -> Optional[datetime]:
    for fmt in ("%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(value.strip(), fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _parse_partial_date_time(
    month: str,
    day: str,
    time_part: str,
    received_at: Optional[datetime],
) -> Optional[datetime]:
    if not received_at:
        return None
    year = received_at.year
    clean_time = time_part.upper().strip().replace("*", "")
    clean_time = re.sub(r"(?i)(\d)(AM|PM)$", r"\1 \2", clean_time)
    for fmt in ("%b %d %Y %I:%M %p", "%B %d %Y %I:%M %p"):
        try:
            dt = datetime.strptime(f"{month} {day} {year} {clean_time}", fmt).replace(tzinfo=timezone.utc)
            if dt < received_at - timedelta(days=30):
                dt = dt.replace(year=year + 1)
            return dt
        except ValueError:
            continue
    return None


def _nearest_prior_full_date(text: str, pos: int, *, max_lookback: int = 700) -> Optional[datetime]:
    window = text[max(0, pos - max_lookback) : pos]
    matches = list(
        re.finditer(
            r"\b(?:(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)"
            r"|(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday))?\.?,?\s*"
            r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)"
            r"[a-z]*\.?\s+\d{1,2},?\s+\d{4}\b",
            window,
            re.IGNORECASE,
        )
    )
    if not matches:
        return None
    return _parse_date_time(matches[-1].group(0), "12:00 AM")


def _marked_clock(match: re.Match, prefix: str) -> str:
    return f"{match.group(prefix + '_time')} {match.group(prefix + '_ampm')}"


def _nearest_prior_day_header(text: str, pos: int):
    window = text[max(0, pos - 450) : pos]
    matches = list(_PRICELINE_DAY_HEADER.finditer(window))
    return matches[-1] if matches else None

def _extract_airports(text: str) -> list[str]:
    """Return ordered-unique valid IATA airport codes from route context.

    Extraction prefers route pairs, departure/arrival labels, then
    parenthesized airport pairs. It avoids treating every valid IATA token as
    an airport endpoint.
    """
    clean = _URL_RE.sub(" ", text)
    upper = clean.upper()

    def _is_valid(code: str) -> bool:
        if code in _NOT_AIRPORTS or code in _KNOWN_AIRLINES:
            return False
        if _VALID_IATA and code not in _VALID_IATA:
            return False
        return True

    seen: set[str] = set()
    result: list[str] = []

    # Prefer true route language over arbitrary IATA-looking tokens.

    def _add(code: str) -> None:
        if code not in seen and _is_valid(code):
            seen.add(code)
            result.append(code)

    for pattern in _ROUTE_PAIR_PATTERNS:
        for m in pattern.finditer(upper):
            _add(m.group(1))
            _add(m.group(2))

    if len(result) >= 2:
        for m in _VIA_AIRPORT.finditer(upper):
            _add(m.group(1))
        return result

    dep_match = _DEPARTURE_AIRPORT.search(upper)
    arr_match = _ARRIVAL_AIRPORT.search(upper)
    if dep_match and arr_match:
        _add(dep_match.group(1))
        _add(arr_match.group(1))
        for m in _VIA_AIRPORT.finditer(upper):
            _add(m.group(1))
        return result

    paren_codes = [
        m.group(1)
        for m in _AIRPORT_IN_PARENS.finditer(upper)
        if _is_valid(m.group(1))
    ]
    if len(set(paren_codes)) >= 2:
        for code in paren_codes:
            _add(code)

    return result


def _unwrap_forwarded(text: str) -> str:
    """Strip forwarded-message header blocks."""
    text = re.sub(r"-{3,}\s*Forwarded message\s*-{3,}", "", text, flags=re.IGNORECASE)
    text = re.sub(r">{1,}\s*From:.*", "", text, flags=re.IGNORECASE | re.MULTILINE)
    return text


def _parse_iso(dt_str: str) -> datetime:
    """Parse an ISO-8601 datetime string including offset and Z suffix."""
    dt_str = dt_str.strip()
    if dt_str.endswith("Z"):
        dt_str = dt_str[:-1] + "+00:00"
    return datetime.fromisoformat(dt_str)


# ISO and "Month DD, YYYY HH:MM AM/PM" patterns
_DT_PATTERNS = [
    re.compile(
        r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2})?(?:[+-]\d{2}:?\d{2}|Z)?",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\.?\s+\d{1,2},?\s+\d{4}\s+\d{1,2}:\d{2}\s*(?:AM|PM)?",
        re.IGNORECASE,
    ),
]

_DT_FORMATS = [
    "%Y-%m-%dT%H:%M:%S%z",
    "%Y-%m-%dT%H:%M%z",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%B %d, %Y %I:%M %p",
    "%B %d %Y %I:%M %p",
    "%b %d, %Y %I:%M %p",
    "%b %d %Y %I:%M %p",
]


def _parse_flexible(s: str) -> Optional[datetime]:
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    for fmt in _DT_FORMATS:
        try:
            dt = datetime.strptime(s, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            pass
    return None


def _all_datetimes(text: str) -> list[datetime]:
    found: list[datetime] = []
    for pat in _DT_PATTERNS:
        for m in pat.finditer(text):
            dt = _parse_flexible(m.group(0))
            if dt:
                found.append(dt)
    return found


def _first_datetime(text: str) -> Optional[datetime]:
    dts = _all_datetimes(text)
    return dts[0] if dts else None


def _last_datetime(text: str) -> Optional[datetime]:
    dts = _all_datetimes(text)
    return dts[-1] if dts else None
