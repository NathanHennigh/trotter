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
PARSER_VERSION = 18

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
        booking|
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
    "DENVER", "MANAGUA", "CONFIRMED", "CONFIMED",
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
    .{0,400}?
    Departure\s+Date\s*:\s*(?P<date>\d{1,2}\s*[- ]\s*[A-Za-z]{3,9},?\s*[- ]\s*\d{4})
    .{0,400}?
    Depart\s+from\s+.{0,200}?\((?P<dep_airport>[A-Z]{3})\)\s*:\s*(?P<dep_time>\d{1,2}:\d{2})
    .{0,400}?
    Arrive\s+in\s+.{0,200}?\((?P<arr_airport>[A-Z]{3})\)\s*:\s*(?P<arr_time>\d{1,2}:\d{2})
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
    .{0,500}?
    (?P<dep_time>\d{1,2}:\d{2})\s*h\s*,\s*
    (?P<dep_date>[A-Za-z]+\s+\d{1,2}\s+[A-Za-z]+\s+\d{4})
    \s+.{0,200}?\((?P<dep_airport>[A-Z]{3})\)
    .{0,500}?
    (?P<arr_time>\d{1,2}:\d{2})\s*h\s*,\s*
    (?P<arr_date>[A-Za-z]+\s+\d{1,2}\s+[A-Za-z]+\s+\d{4})
    \s+.{0,200}?\((?P<arr_airport>[A-Z]{3})\)
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
    \bFlight(?:\s+\d+)?\s*\W*:\W*
    (?P<dow>Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s*
    (?P<date>\d{1,2}/\d{1,2}/\d{4})
    (?P<body>.{0,5000}?)(?=\bFlight(?:\s+\d+)?\s*\W*:|Payment\s+information|Fare\s+rules|$)
    """,
    re.IGNORECASE | re.VERBOSE | re.DOTALL,
)
_SOUTHWEST_SEGMENT = re.compile(
    r"""
    \bFLIGHT\s*\#\s*(?P<number>\d{1,4}[A-Z]?)
    .{0,500}?
    DEPARTS\s+\W*(?P<dep_airport>[A-Z]{3})\W+
    (?P<dep_time>\d{1,2}:\d{2})\W*(?P<dep_ampm>AM|PM)
    .{0,500}?
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
    .{0,400}?
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
    (?:\s+Operated\s+by\s+.{1,100}?)?
    \s+
    (?P<dep_airport>[A-Z]{3})\s+to\s+(?P<arr_airport>[A-Z]{3})
    """,
    re.IGNORECASE | re.VERBOSE | re.DOTALL,
)
_DELTA_TRIP_DETAILS_SEGMENT = re.compile(
    r"""
    \bDEPARTURE\s+
    (?P<dep_airport>[A-Z]{3})\s+
    (?P<dep_time>\d{1,2}:\d{2}\s*(?:AM|PM|am|pm))\s+
    (?P<dep_date>(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun),?\s+
        (?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+
        \d{1,2})
    \s+
    (?P<airline>DL)\s*(?P<number>\d{1,4}[A-Z]?)
    \s+
    DESTINATION\s+
    (?P<arr_airport>[A-Z]{3})\s+
    (?P<arr_time>\d{1,2}:\d{2}\s*(?:AM|PM|am|pm))\s+
    (?P<arr_date>(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun),?\s+
        (?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+
        \d{1,2})
    """,
    re.IGNORECASE | re.VERBOSE | re.DOTALL,
)
_MONTH_DATE_WITH_YEAR = (
    r"(?:(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday|Mon|Tue|Wed|Thu|Fri|Sat|Sun)\.?,?\s*)?"
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}"
)
_SLASH_DATE_WITH_YEAR = r"\d{1,2}/\d{1,2}/\d{2,4}"
# Variants without a required year (year inferred from received_at). Used by
# v5 generic patterns and provider extractors that quote dates like
# "Tue, Mar 24" without the calendar year.
_DOW_PREFIX = (
    r"(?:(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun|Monday|Tuesday|Wednesday|"
    r"Thursday|Friday|Saturday|Sunday),?\s+)?"
)
_FULL_MONTH_DATE = (
    rf"{_DOW_PREFIX}"
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+"
    r"\d{1,2},?\s+\d{4}"
)
_PARTIAL_MONTH_DATE = (
    rf"{_DOW_PREFIX}"
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2}"
)
_MONTH_DATE_LINE_RE = re.compile(rf"^{_MONTH_DATE_WITH_YEAR}$", re.IGNORECASE)
_AA_TRIP_CONFIRMATION_ROW = re.compile(
    rf"""
    (?P<date>{_MONTH_DATE_WITH_YEAR})
    \s+
    (?P<dep_airport>[A-Z]{{3}})
    \s+
    (?P<arr_airport>[A-Z]{{3}})
    \s+
    (?P<dep_time>\d{{1,2}}:\d{{2}}\s*(?:AM|PM|am|pm))
    \s+
    (?P<arr_time>\d{{1,2}}:\d{{2}}\s*(?:AM|PM|am|pm))
    .{{0,180}}?
    (?:American\s+Airlines|AA)\s+
    (?P<number>\d{{1,4}}[A-Z]?)
    \b
    """,
    re.IGNORECASE | re.VERBOSE | re.DOTALL,
)
_UNITED_ETICKET_ROW = re.compile(
    r"""
    (?P<date>(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun),?\s+\d{1,2}[A-Z]{3}\d{2})
    \s+
    UA\s*(?P<number>\d{1,4}[A-Z]?)
    \s+
    [A-Z]
    \s+
    [A-Z][A-Za-z .,'/-]{1,60}?
    \((?P<dep_airport>[A-Z]{3})(?:\s+-\s+[^)]*)?\)
    \s+
    (?P<dep_time>\d{1,2}:\d{2}\s*(?:AM|PM|am|pm))
    \s+
    [A-Z][A-Za-z .,'/-]{1,60}?
    \((?P<arr_airport>[A-Z]{3})(?:\s+-\s+[^)]*)?\)
    \s+
    (?P<arr_time>\d{1,2}:\d{2}\s*(?:AM|PM|am|pm))
    """,
    re.IGNORECASE | re.VERBOSE | re.DOTALL,
)
_FRONTIER_CONFIRMATION_ROW = re.compile(
    r"""
    \b(?:DEPARTING|RETURNING)\s+FLIGHT\s+
    (?P<number>\d{1,4}[A-Z]?)
    \b
    .{0,120}?
    \((?P<dep_airport>[A-Z]{3})\)
    \s+to\s+
    .{0,80}?
    \((?P<arr_airport>[A-Z]{3})\)
    .{0,80}?
    Depart:\s*
    (?P<dep_date>\d{1,2}/\d{1,2}/\d{2,4})
    \s+
    (?P<dep_time>\d{1,2}:\d{2}\s*(?:AM|PM|am|pm))
    \s*\|\s*
    Arrive:\s*
    (?P<arr_date>\d{1,2}/\d{1,2}/\d{2,4})
    \s+
    (?P<arr_time>\d{1,2}:\d{2}\s*(?:AM|PM|am|pm))
    """,
    re.IGNORECASE | re.VERBOSE | re.DOTALL,
)
_AIRLINE_DEPARTS_ARRIVES_ROW = re.compile(
    rf"""
    \b(?P<airline_name>[A-Z][A-Za-z .&'-]{{2,45}}?)\s+
    Flight\s+
    (?P<number>\d{{1,4}}[A-Z]?)
    \b
    .{{0,360}}?
    departs\s+
    (?P<dep_airport>[A-Z]{{3}})
    \s+
    (?P<dep_time>\d{{1,2}}:\d{{2}}\s*(?:AM|PM|am|pm))
    \s+
    (?P<dep_date>{_MONTH_DATE_WITH_YEAR})
    \s+
    arrives\s+
    (?P<arr_airport>[A-Z]{{3}})
    \s+
    (?P<arr_time>\d{{1,2}}:\d{{2}}\s*(?:AM|PM|am|pm))
    \s+
    (?P<arr_date>{_MONTH_DATE_WITH_YEAR})
    """,
    re.IGNORECASE | re.VERBOSE | re.DOTALL,
)
_LABEL_ROUTE_TIME_FLIGHT_ROW = re.compile(
    r"""
    (?P<dep_airport>[A-Z]{3})
    \s+\*?\s*
    [A-Z][A-Za-z .,'/-]{2,50}?
    \s+\*?\s*
    (?P<arr_airport>[A-Z]{3})
    \s+\*?\s*
    [A-Z][A-Za-z .,'/-]{2,50}?
    \s+\*?\s*
    (?P<dep_time>\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)?)
    \s+\*?\s*
    (?P<dep_date>(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday|Mon|Tue|Wed|Thu|Fri|Sat|Sun)\.?,?\s+
        \d{1,2}\s+
        (?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+
        \d{2,4})
    \s+\*?\s*
    (?P<arr_time>\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)?)
    \s+\*?\s*
    (?P<arr_date>(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday|Mon|Tue|Wed|Thu|Fri|Sat|Sun)\.?,?\s+
        \d{1,2}\s+
        (?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+
        \d{2,4})
    .{0,120}?
    Flight\s+\*?\s*
    (?P<airline>[A-Z0-9]{2})\s*(?P<number>\d{1,4}[A-Z]?)
    \b
    """,
    re.VERBOSE | re.DOTALL,
)
_SPIRIT_CONFIRMATION_ROW = re.compile(
    r"""
    (?P<date>(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s+
        (?:January|February|March|April|May|June|July|August|September|October|November|December)
        \s+\d{1,2},?\s+\d{4})
    .{0,300}?
    FlightFrom["'>\s\w=-]*
    (?P<dep_place>[A-Z][A-Za-z .,'/-]{2,80}?)
    \s*</td>\s*<td[^>]*>
    (?P<dep_time>\d{1,2}:\d{2}\s*(?:AM|PM|am|pm))
    .{0,400}?
    FlightTo["'>\s\w=-]*
    (?P<arr_place>[A-Z][A-Za-z .,'/-]{2,80}?)
    \s*</td>\s*<td[^>]*>
    (?P<arr_time>\d{1,2}:\d{2}\s*(?:AM|PM|am|pm))
    """,
    re.IGNORECASE | re.VERBOSE | re.DOTALL,
)
_SPIRIT_CONFIRMATION_TEXT_ROW = re.compile(
    r"""
    (?P<date>(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s+
        (?:January|February|March|April|May|June|July|August|September|October|November|December)
        \s+\d{1,2},?\s+\d{4})
    \s+
    TIME
    \s+
    (?P<dep_place>[A-Z][A-Za-z .,'/-]{2,80}?)
    \s+
    (?P<dep_time>\d{1,2}:\d{2}\s*(?:AM|PM|am|pm))
    \s+
    \d{1,2}\s*h(?:\s*\d{1,2}\s*min)?
    \s+
    (?P<arr_place>[A-Z][A-Za-z .,'/-]{2,80}?)
    \s+
    (?P<arr_time>\d{1,2}:\d{2}\s*(?:AM|PM|am|pm))
    """,
    re.IGNORECASE | re.VERBOSE | re.DOTALL,
)
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
    \b(?P<dep_airport>[A-Z]{{3}})\b
    (?P<between>.{{0,140}}?)
    \b(?P<arr_airport>[A-Z]{{3}})\b
    (?P<suffix>.{{0,220}}?)
    (?P<airline>[A-Z0-9]{{2}})\s*(?P<number>\d{{1,4}}[A-Z]?)
    """,
    re.VERBOSE | re.DOTALL,
)
_V5_CODE_ROUTE_LINE = re.compile(
    r"""
    ^(?P<dep_airport>[A-Z]{3})\s+
    (?P<arr_airport>[A-Z]{3})\s+
    (?P<dep_time>\d{1,2}:\d{2}\s*(?:AM|PM|am|pm))\s+
    (?P<arr_time>\d{1,2}:\d{2}\s*(?:AM|PM|am|pm))
    .{0,180}?
    (?P<airline>[A-Z0-9]{2})\s+(?P<number>\d{1,4}[A-Z]?)
    \b
    """,
    re.VERBOSE,
)
_PRICELINE_ALERT_ROW = re.compile(
    rf"""
    \b(?P<airline_name>[A-Z][A-Za-z .&'-]{{2,45}}?)\s+
    Flight\s+(?P<number>\d{{1,4}}[A-Z]?)\b
    .{{0,400}}?
    Departs:\s*(?:Departs\s+)?
    [A-Z][A-Za-z ./'-]{{2,80}}?\((?P<dep_airport>[A-Z]{{3}})\)\s+
    (?P<dep_date>{_MONTH_DATE_WITH_YEAR})\s+at\s+
    (?P<dep_time>\d{{1,2}}:\d{{2}}\s*(?:AM|PM|am|pm))
    .{{0,400}}?
    Arrives:\s*(?:Arrives\s+)?
    [A-Z][A-Za-z ./'-]{{2,80}}?\((?P<arr_airport>[A-Z]{{3}})\)\s+
    (?P<arr_date>{_MONTH_DATE_WITH_YEAR})\s+at\s+
    (?P<arr_time>\d{{1,2}}:\d{{2}}\s*(?:AM|PM|am|pm))
    """,
    re.IGNORECASE | re.VERBOSE | re.DOTALL,
)
_TRAVELOCITY_ROUTE_ROW = re.compile(
    rf"""
    \b(?P<section>Departure|Return)\s+
    (?P<date>(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun),?\s+
        (?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{{1,2}})
    \s+
    (?P<airline_name>[A-Z][A-Za-z .&'-]{{2,45}}?)\s+
    (?P<number>\d{{1,4}}[A-Z]?)
    \s+
    [A-Z][A-Za-z ./'-]{{1,70}}?\((?P<dep_airport>[A-Z]{{3}})\)\s+
    (?P<dep_time>\d{{1,2}}:\d{{2}}\s*(?:AM|PM|am|pm))
    .{{0,400}}?
    [A-Z][A-Za-z ./'-]{{1,70}}?\((?P<arr_airport>[A-Z]{{3}})\)\s+
    (?P<arr_time>\d{{1,2}}:\d{{2}}\s*(?:AM|PM|am|pm))
    (?P<tail>.{{0,700}}?)
    (?=\b(?:Departure|Return|Traveler|Price summary|$))
    """,
    re.IGNORECASE | re.VERBOSE | re.DOTALL,
)
_ALLEGIENT_ITINERARY_ROW = re.compile(
    rf"""
    \b(?:Departing|Returning)\s+Flight\s+Information\s+
    Date\s+(?P<date>{_MONTH_DATE_WITH_YEAR})\s+
    Flight\s+\#\s*(?P<number>\d{{1,4}}[A-Z]?)\s+
    Departure\s+Airport\s+
    [A-Z][A-Za-z ./'-]{{2,90}}?\((?P<dep_airport>[A-Z]{{3}})\)\s+
    Map\s+Departs\s+(?P<dep_time>\d{{1,2}}:\d{{2}}\s*(?:AM|PM|am|pm))\s+
    Arrival\s+Airport\s+
    [A-Z][A-Za-z ./'-]{{2,90}}?\((?P<arr_airport>[A-Z]{{3}})\)\s+
    Map\s+Arrives\s+(?P<arr_time>\d{{1,2}}:\d{{2}}\s*(?:AM|PM|am|pm))
    """,
    re.IGNORECASE | re.VERBOSE | re.DOTALL,
)
_AA_TEXT_ITINERARY_ROW = re.compile(
    rf"""
    AMERICAN\s+AIRLINES\s+
    (?P<number>\d{{1,4}}[A-Z]?)\s+
    (?P<dep_airport>[A-Z]{{3}})\s+
    [A-Z][A-Za-z ./'-]{{2,45}}?\s+
    (?P<dep_date>{_MONTH_DATE_WITH_YEAR})\s+
    (?P<dep_time>\d{{1,2}}:\d{{2}}\s*(?:AM|PM|am|pm))\s+
    (?P<arr_airport>[A-Z]{{3}})\s+
    [A-Z][A-Za-z ./'-]{{2,45}}?\s+
    (?P<arr_date>{_MONTH_DATE_WITH_YEAR})\s+
    (?P<arr_time>\d{{1,2}}:\d{{2}}\s*(?:AM|PM|am|pm))
    """,
    re.IGNORECASE | re.VERBOSE | re.DOTALL,
)
_ALASKA_PARTNER_CONFIRMATION_ROW = re.compile(
    rf"""
    Flight:\s*(?P<airline_name>[A-Z][A-Za-z .&'-]{{2,45}}?)\s+
    (?P<number>\d{{1,4}}[A-Z]?)\s+
    .{{0,400}}?
    Departs:\s*
    [A-Z][A-Za-z .,'/-]{{2,90}}?\((?P<dep_airport>[A-Z]{{3}})\)\s+
    on\s+(?P<dep_date>{_PARTIAL_MONTH_DATE}(?:,?\s+\d{{4}})?)\s+at\s+
    (?P<dep_time>\d{{1,2}}:\d{{2}}\s*(?:AM|PM|am|pm))
    .{{0,400}}?
    Arrives:\s*
    [A-Z][A-Za-z .,'/-]{{2,90}}?\((?P<arr_airport>[A-Z]{{3}})\)\s+
    on\s+(?P<arr_date>{_PARTIAL_MONTH_DATE}(?:,?\s+\d{{4}})?)\s+at\s+
    (?P<arr_time>\d{{1,2}}:\d{{2}}\s*(?:AM|PM|am|pm))
    """,
    re.IGNORECASE | re.VERBOSE | re.DOTALL,
)
_UNITED_RESERVATION_SEGMENT = re.compile(
    r"""
    \bUnited\s+Airlines\b
    (?:\s+Operated\s+By:.{0,140}?)?\s+
    (?:\d{4}\s+)?
    (?P<number>\d{1,4})\s+
    (?P<dep_place>.{1,200}?)\s+
    (?P<dep_time>\d{1,2}:\d{2}\s*(?:AM|PM|am|pm))\s+
    (?P<arr_place>.{1,200}?)\s+
    (?P<arr_time>\d{1,2}:\d{2}\s*(?:AM|PM|am|pm))
    \s+Duration:
    """,
    re.IGNORECASE | re.VERBOSE | re.DOTALL,
)
_DELTA_FORWARDED_ITINERARY_ROW = re.compile(
    r"""
    (?P<dep_place>[A-Z][A-Za-z .,'/-]{2,80}?)\s+\((?P<dep_airport>[A-Z]{3})\)
    \s+►\s+
    (?P<arr_place>[A-Z][A-Za-z .,'/-]{2,80}?)\s+\((?P<arr_airport>[A-Z]{3})\)
    \s+DL\s*(?P<number>\d{1,4}[A-Z]?)
    \s+Departs\s+(?P<dep_date>\d{1,2}/\d{1,2}/\d{2,4})\s*@\s*
    (?P<dep_time>\d{1,2}:\d{2}\s*(?:AM|PM|am|pm))
    \s+Arrives\s+(?P<arr_date>\d{1,2}/\d{1,2}/\d{2,4})\s*@\s*
    (?P<arr_time>\d{1,2}:\d{2}\s*(?:AM|PM|am|pm))
    """,
    re.IGNORECASE | re.VERBOSE | re.DOTALL,
)
_AMADEUS_BOARDING_ROW = re.compile(
    r"""
    Flight:\s*(?P<airline>[A-Z0-9]{2})\s*(?P<number>\d{1,4}[A-Z]?)\s*-\s*
    [A-Z][A-Za-z ./'-]{2,70}?\((?P<dep_airport>[A-Z]{3})\)\s*-\s*
    [A-Z][A-Za-z ./'-]{2,70}?\((?P<arr_airport>[A-Z]{3})\)\s*-\s*
    (?P<date>\d{1,2}\s+[A-Z]{3}\s+\d{4})\s*-\s*
    (?P<dep_time>\d{1,2}:\d{2})
    .{0,400}?
    Flight\s+Arrival:\s*(?P<arr_time>\d{1,2}:\d{2})
    """,
    re.IGNORECASE | re.VERBOSE | re.DOTALL,
)
_SUN_COUNTRY_TRIP_ROW = re.compile(
    r"""
    Trip\s+Details\s+
    (?P<dep_place>[A-Z][A-Za-z ./,'-]{2,80}?)\s+to\s+
    (?P<arr_place>[A-Z][A-Za-z ./,'-]{2,80}?)\s+
    SY\s*(?P<number>\d{1,4}[A-Z]?)\s+
    (?:Nonstop\s+)?
    (?P<dep_time>\d{1,2}:\d{2}\s*(?:AM|PM|am|pm))\s+
    [A-Z][A-Za-z ./,'-]{2,80}?\((?P<dep_airport>[A-Z]{3})\)\s+
    (?P<dep_date>(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4})
    .{0,400}?
    (?P<arr_time>\d{1,2}:\d{2}\s*(?:AM|PM|am|pm))\s+
    [A-Z][A-Za-z ./,'-]{2,80}?\((?P<arr_airport>[A-Z]{3})\)\s+
    (?P<arr_date>(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4})
    """,
    re.IGNORECASE | re.VERBOSE | re.DOTALL,
)
_EVA_CHECKIN_ROW = re.compile(
    r"""
    (?P<dep_place>[A-Z][A-Za-z ./'()-]{2,80}?)\s+-\s+
    (?P<arr_place>[A-Z][A-Za-z ./'()-]{2,80}?)\s+
    BR\s*(?P<number>\d{1,4}[A-Z]?)\s+
    (?P<dep_date>\d{4}/\d{1,2}/\d{1,2})\s+
    (?P<dep_time>\d{1,2}:\d{2})\s+
    (?P<arr_date>\d{4}/\d{1,2}/\d{1,2})\s+
    (?P<arr_time>\d{1,2}:\d{2})
    """,
    re.IGNORECASE | re.VERBOSE,
)
_FRONTIER_SIMPLE_CONFIRMATION_ROW = re.compile(
    r"""
    Depart:\s*
    (?P<date>(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun),?\s+
        (?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4})
    \s+Flight\s+Departure\s+Arrival\s+Duration\s+
    F9\s*(?P<number>\d{1,4}[A-Z]?)\s+
    (?P<dep_time>\d{1,2}:\d{2}\s*(?:AM|PM|am|pm))\s+
    [A-Z][A-Za-z ./,'-]{2,80}?\((?P<dep_airport>[A-Z]{3})\)\s+
    (?P<arr_time>\d{1,2}:\d{2}\s*(?:AM|PM|am|pm))\s+
    [A-Z][A-Za-z ./,'-]{2,80}?\((?P<arr_airport>[A-Z]{3})\)
    """,
    re.IGNORECASE | re.VERBOSE | re.DOTALL,
)
_DELTA_RECEIPT_ROW = re.compile(
    r"""
    (?P<date>(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun),?\s+\d{1,2}[A-Z]{3})
    \s+DEPART\s+ARRIVE\s+DELTA\s+
    (?P<number>\d{1,4}[A-Z]?)
    .{0,300}?
    (?P<dep_place>[A-Z][A-Z ./,'-]{2,80}?)\s+
    (?P<dep_time>\d{1,2}:\d{2}\s*(?:AM|PM|am|pm))\s+
    (?P<arr_place>[A-Z][A-Z ./,'-]{2,80}?)\s+
    (?P<arr_time>\d{1,2}:\d{2}\s*(?:AM|PM|am|pm))
    """,
    re.IGNORECASE | re.VERBOSE | re.DOTALL,
)
_EXPEDIA_FLIGHT_ROW = re.compile(
    r"""
    (?P<airline_name>[A-Z][A-Za-z .&'-]{2,45}?)\s+
    (?P<number>\d{1,4}[A-Z]?)\s+
    \d{1,2}:\d{2}\s*(?:AM|PM|am|pm)
    .{0,300}?
    \((?P<dep_airport>[A-Z]{3})-[^)]+\)\s+to\s+
    .{0,200}?
    \((?P<arr_airport>[A-Z]{3})-[^)]+\)
    .{0,300}?
    (?P<date>(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun),?\s+
        (?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2})
    ,?\s+
    (?P<dep_time>\d{1,2}:\d{2}\s*(?:AM|PM|am|pm))\s*-\s*
    (?P<arr_time>\d{1,2}:\d{2}\s*(?:AM|PM|am|pm))
    (?P<tail>.{0,80}?)
    (?=\d+h\s+\d+m\s+flight\s+duration|Layover|Manage|$)
    """,
    re.IGNORECASE | re.VERBOSE | re.DOTALL,
)
_BA_ETICKET_ITINERARY_ROW = re.compile(
    r"""
    (?P<airline>[A-Z0-9]{2})\s*(?P<number>\d{1,4}[A-Z]?)\s*:\s*
    [A-Z][A-Za-z .&'-]{2,45}?\s*\|\s*.{0,200}?Confirmed
    .{0,400}?
    Depart:\s*(?P<dep_date>\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})\s+
    (?P<dep_time>\d{1,2}:\d{2})\s*-\s*
    (?P<dep_place>[A-Z][A-Za-z ./'()-]{2,90}?)
    (?:\s+-\s+Terminal\s+\S+)?
    \s+Arrive:\s*(?P<arr_date>\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})\s+
    (?P<arr_time>\d{1,2}:\d{2})\s*-\s*
    (?P<arr_place>[A-Z][A-Za-z ./'()-]{2,90}?)
    (?=\s+-{3,}|Passenger|$)
    """,
    re.IGNORECASE | re.VERBOSE | re.DOTALL,
)
_LIFEMILES_FLIGHT_ROW = re.compile(
    r"""
    Flight\s+\d+
    .{0,40}?
    (?P<airline>[A-Z0-9]{2})\s*(?P<number>\d{1,4}[A-Z]?)
    .{0,80}?
    (?P<dep_place>[A-Z][A-Za-z ./'-]{2,60}?)\((?P<dep_airport>[A-Z]{3})\)\s*-\s*
    (?P<arr_place>[A-Z][A-Za-z ./'-]{2,60}?)\((?P<arr_airport>[A-Z]{3})\)
    .{0,120}?
    Departure:\s*(?P<dep_date>[A-Za-z]+,\s*\d{1,2}\s*(?:st|nd|rd|th)?[,]?\s*\d{4})\s+
    (?P<dep_time>\d{1,2}:\d{2})
    .{0,300}?
    Arrival:\s*(?P<arr_date>[A-Za-z]+,\s*\d{1,2}\s*(?:st|nd|rd|th)?[,]?\s*\d{4})\s+
    (?P<arr_time>\d{1,2}:\d{2})
    """,
    re.IGNORECASE | re.VERBOSE | re.DOTALL,
)
_IBERIA_PURCHASE_DETAIL_ROW = re.compile(
    r"""
    from\s+(?P<dep_place>[A-Z][A-Za-z .,'-]{2,60}?)\s+to\s+
    (?P<arr_place>[A-Z][A-Za-z .,'-]{2,60}?)\s+
    (?P<date>(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s+
        (?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4})
    \s+
    IB\s*(?P<number>\d{1,4}[A-Z]?)
    .{0,400}?
    Departure\s+(?P<dep_time>\d{1,2}:\d{2})\s*h\s+
    (?P<dep_label>[A-Z][A-Za-z .,'()-]{2,60}?)\s+
    .{0,400}?
    Arrival\s+(?P<arr_time>\d{1,2}:\d{2})\s*h\s+
    (?P<arr_label>[A-Z][A-Za-z .,'()-]{2,60}?)
    (?=\s+from\s+|\s+[A-Z][A-Z0-9]{1,3}\d|\s+NATHAN|\s+Booking|\s+Flight|\s*$)
    """,
    re.IGNORECASE | re.VERBOSE | re.DOTALL,
)


# Generic v5 patterns that catch reminder / boarding-pass / aggregator
# itinerary lines without any per-airline knowledge. Each one expresses a
# common structural shape; v5 evidence scoring decides if the surrounding
# context is strong enough to accept the segment.
# "Flight 1915, EWR VPS Jul 23, 2019 at 12:00 PM"  (Allegiant reminder style)
# "Flight UA123, SFO-LAX, Aug 5, 2024 at 09:30 AM"  (other carriers)
# Optional airline IATA prefix on the flight number; route shown as IATA pair
# joined by space, dash, arrow, or aircraft glyph.
_V5_COMPACT_REMINDER_LINE = re.compile(
    rf"""
    \bFlight\s+(?P<airline>[A-Z]{{2}})?\s*(?P<number>\d{{1,4}}[A-Z]?)
    [\s,. ]+
    (?P<dep_airport>[A-Z]{{3}})
    \s*(?:to|-|--?>|→|✈|✈)?\s+
    (?P<arr_airport>[A-Z]{{3}})
    [\s,]{{1,40}}?
    (?P<date>{_FULL_MONTH_DATE})
    [\s,]{{1,30}}?
    (?:at\s+)?
    (?P<time>\d{{1,2}}:\d{{2}}\s*(?:AM|PM|am|pm))
    """,
    re.IGNORECASE | re.VERBOSE,
)
# "[code], JFK TO AMS, 6:00PM Sun, Dec 22, 2019"  (Delta E-Boarding Pass style)
# Single-time boarding-pass rows that omit the flight number entirely. The
# arrival time is inferred (dep + 1h) downstream because these emails never
# carry it; the pairing of route + departure + date is unambiguous on its own.
_V5_BOARDING_ROUTE_LINE = re.compile(
    rf"""
    \b(?P<dep_airport>[A-Z]{{3}})
    \s+TO\s+
    (?P<arr_airport>[A-Z]{{3}})
    [\s,]{{1,15}}
    (?P<time>\d{{1,2}}:\d{{2}}\s*(?:AM|PM|am|pm))
    \s+
    (?P<date>{_FULL_MONTH_DATE})
    """,
    re.IGNORECASE | re.VERBOSE,
)
# "Tue, Jun 7 · Tangier to Palma 12:25 PM–2:50 PM · 1h 25m TNG (...)"
# (Google Iberia booking confirmation style)
# Bullet-separated layout where the date may or may not include a year and
# the IATA codes appear on a later line.
_V5_BULLET_FORMAT = re.compile(
    rf"""
    (?P<date>{_PARTIAL_MONTH_DATE}(?:,?\s+\d{{4}})?)
    \s*[•·]\s*
    (?P<dep_city>[A-Z][A-Za-z .,'/-]{{2,60}}?)
    \s+to\s+
    (?P<arr_city>[A-Z][A-Za-z .,'/-]{{2,60}}?)
    \s+
    (?P<dep_time>\d{{1,2}}:\d{{2}}\s*(?:AM|PM|am|pm))
    \s*[–—\-]\s*
    (?P<arr_time>\d{{1,2}}:\d{{2}}\s*(?:AM|PM|am|pm))
    .{{0,200}}?
    \b(?P<dep_airport>[A-Z]{{3}})\b
    .{{0,400}}?
    \b(?P<arr_airport>[A-Z]{{3}})\b
    """,
    re.IGNORECASE | re.VERBOSE | re.DOTALL,
)
# Subject-line itineraries: "<name> Booking No: <PNR> DD/MM/YYYY <DEP> ✈ <ARR>"
# (AirAsia confirmation subject style). When the body is too sparse to parse,
# this pattern lifts a flight from the subject. Date may be DD/MM/YYYY (most
# international carriers) or MM/DD/YYYY (some US carriers); we record both
# interpretations and prefer the one whose month is valid.
_V5_SUBJECT_ITINERARY = re.compile(
    r"""
    (?:Booking\s+No\.?:?\s*(?P<pnr>[A-Z0-9]{5,8})\s+)?
    (?P<date>\d{1,2}[/-]\d{1,2}[/-]\d{2,4})
    \s+
    (?P<dep_airport>[A-Z]{3})
    \s*(?:to|->|--?>|–|→|✈|✈)\s*
    (?P<arr_airport>[A-Z]{3})
    """,
    re.VERBOSE | re.UNICODE,
)
_V5_SUBJECT_PLACE_ROUTE = re.compile(
    r"""
    \bfrom\s+
    (?P<dep_place>[A-Z][A-Za-z ./'-]{2,120}?)
    \s+to\s+
    (?P<arr_place>[A-Z][A-Za-z ./'-]{2,120}?)
    \s+on\s+
    (?P<date>\d{1,2}[A-Za-z]{3}\d{2,4})
    \b
    """,
    re.IGNORECASE | re.VERBOSE,
)
# Vertical multi-line itinerary used by Justfly, Ethiopian Airlines, and any
# template that lays out airline / Flight / time / DOW Mon Day / city (IATA)
# on consecutive lines. Tolerates BeautifulSoup-extracted text where the IATA
# code may sit on its own line inside the parens.
_V5_AIRLINE_VERTICAL = re.compile(
    r"""
    (?P<airline_name>[A-Z][A-Za-z &'.-]{2,40}?)
    \s*\n\s*
    Flight\s+(?P<number>\d{1,4}[A-Z]?)
    \s*\n
    (?:\s*Terminal\s+\S+\s*\n)?
    \s*(?P<dep_time>\d{1,2}:\d{2}\s*(?:am|pm|AM|PM))
    \s*\n
    \s*(?P<dep_dow>[A-Za-z]{3,9})\.?,?\s+(?P<dep_month>[A-Za-z]{3,9})\.?\s+(?P<dep_day>\d{1,2})
    \s*\n
    [^\n]*?\(\s*(?P<dep_airport>[A-Z]{3})\s*\)
    \s*\n
    \s*(?P<arr_time>\d{1,2}:\d{2}\s*(?:am|pm|AM|PM))
    \s*\n
    \s*(?P<arr_dow>[A-Za-z]{3,9})\.?,?\s+(?P<arr_month>[A-Za-z]{3,9})\.?\s+(?P<arr_day>\d{1,2})
    \s*\n
    [^\n]*?\(\s*(?P<arr_airport>[A-Z]{3})\s*\)
    """,
    re.IGNORECASE | re.VERBOSE,
)
# Google's aggregator template emits a vertical bullet layout:
#   <city1> – <city2> · <DOW>, <Mon> <Day>
#   <dep_time>–<arr_time>
#   <airline_name>
#   <num> · <IATA1>–<IATA2>
# Year is rarely included in the bullet line; we fall back to received_at.
_V5_GOOGLE_VERTICAL_BULLET = re.compile(
    rf"""
    (?P<dep_city>[A-Z][^\n]{{2,80}}?)
    \s*[–—-]\s*
    (?P<arr_city>[A-Z][^\n]{{2,80}}?)
    \s*[•·]\s*
    (?P<date>{_PARTIAL_MONTH_DATE}(?:,?\s+\d{{4}})?)
    \s*\n
    \s*(?P<dep_time>\d{{1,2}}:\d{{2}}\s*(?:AM|PM|am|pm))
    \s*[–—-]\s*
    (?P<arr_time>\d{{1,2}}:\d{{2}}\s*(?:AM|PM|am|pm))
    \s*\n
    \s*(?P<airline_name>[A-Z][A-Za-z &'.-]{{2,40}})
    \s*\n
    \s*(?P<number>\d{{1,4}}[A-Z]?)
    \s*[•·]\s*
    (?P<dep_airport>[A-Z]{{3}})
    \s*[–—-]\s*
    (?P<arr_airport>[A-Z]{{3}})
    """,
    re.VERBOSE,
)
# United "is processing" reservation receipt. Vertical layout where each
# segment looks like:
#   [United Airlines]   UA <num>
#   <some metadata lines>
#   <dep_time>
#   <city, state, country> (<IATA>)            or  ... (<IATA - Terminal>)
#   <arr_time>
#   <city, state, country> (<IATA>)
# Date sits in a header line above this block (e.g., "Wed, Oct 10, 2018"); we
# attach the nearest prior full date.
_V5_UNITED_PROCESSING_VERTICAL = re.compile(
    r"""
    \bUA\s*(?P<number>\d{1,4}[A-Z]?)\b
    [^\n]*\n
    (?:[^\n]*\n){0,8}?
    \s*(?P<dep_time>\d{1,2}:\d{2}\s*(?:am|pm|AM|PM))\s*\n
    [^\n]*?\(\s*(?P<dep_airport>[A-Z]{3})(?:\s*-\s*[^)\n]*)?\s*\)\s*\n
    (?:[^\n]*\n){0,3}?
    \s*(?P<arr_time>\d{1,2}:\d{2}\s*(?:am|pm|AM|PM))\s*\n
    [^\n]*?\(\s*(?P<arr_airport>[A-Z]{3})(?:\s*-\s*[^)\n]*)?\s*\)
    """,
    re.IGNORECASE | re.VERBOSE,
)
# United boarding-pass body. Body lacks any time/date — only:
#   Flight UA1612
#   Dallas-Ft. Worth (DFW) to Newark-Liberty Intl (EWR)
# We extract route + flight#, then synthesize dep_time from received_at
# (boarding passes are sent within hours of departure). Result is a low-
# confidence segment good enough to cross-reference with an existing trip.
_V5_AIRLINE_FLIGHT_ROUTE_LINE = re.compile(
    r"""
    \bFlight\s+(?P<airline>[A-Z]{2})\s*(?P<number>\d{1,4}[A-Z]?)
    \s*\n
    [^\n]*?\(\s*(?P<dep_airport>[A-Z]{3})\s*\)
    \s*to\s*
    [^\n]*?\(\s*(?P<arr_airport>[A-Z]{3})\s*\)
    """,
    re.IGNORECASE | re.VERBOSE,
)

_V5_LEGACY_TERMINAL_ITINERARY = re.compile(
    r"""
    (?P<head>
        (?:
            United\s+Airlines|Lufthansa\s+German\s+Airlines|Republic\s+Airways|
            United\s+Express|DBA\s+United\s+Express|Operated\s+By
        )
        .{0,180}?
    )
    (?P<dep_place>[A-Z][A-Za-z ./'-]{2,120}?,\s*[A-Z]{2})
    \s+Terminal\s*:\s*[^ \n]+
    \s+(?P<dep_date>(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+\d{1,2}[A-Z]{3})
    \s+(?P<dep_time>\d{1,2}:\d{2}\s*(?:AM|PM|am|pm))
    \s+
    (?P<arr_place>[A-Z][A-Za-z ./'-]{2,120}?,\s*[A-Z]{2})
    \s+Terminal\s*:\s*[^ \n]+
    \s+(?P<arr_date>(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+\d{1,2}[A-Z]{3})
    \s+(?P<arr_time>\d{1,2}:\d{2}\s*(?:AM|PM|am|pm))
    """,
    re.IGNORECASE | re.VERBOSE | re.DOTALL,
)
_V5_BA_ETICKET_ITINERARY = re.compile(
    r"""
    Your\s+Itinerary
    .{0,260}?
    (?P<airline_name>[A-Z][A-Za-z .&'-]{2,45})\s*\|\s*[^|\n]{2,80}?\|\s*Confirmed
    \s+
    (?P<dep_date>\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+\d{4})
    \s+
    (?P<dep_time>\d{1,2}:\d{2})
    \s+
    (?P<dep_place>[A-Z][A-Za-z .()'/-]{2,120})
    \s+
    (?:Terminal\s+\S+\s+)?
    (?P<arr_date>\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+\d{4})
    \s+
    (?P<arr_time>\d{1,2}:\d{2})
    \s+
    (?P<arr_place>[A-Z][A-Za-z .()'/-]{2,120})
    """,
    re.IGNORECASE | re.VERBOSE | re.DOTALL,
)
_V5_FRONTIER_DEPARTING_ROW = re.compile(
    r"""
    \bDeparting\s+Flight\s+(?P<number>\d{1,4}[A-Z]?)
    \s+
    (?P<date>(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4})
    \s+
    (?P<dep_airport>[A-Z]{3})\s+
    (?P<dep_time>\d{1,2}:\d{2}\s*(?:AM|PM|am|pm))
    \s+
    (?P<arr_airport>[A-Z]{3})\s+
    (?P<arr_time>\d{1,2}:\d{2}\s*(?:AM|PM|am|pm))
    """,
    re.IGNORECASE | re.VERBOSE,
)
_V5_SOUTHWEST_SPARSE_TRIP = re.compile(
    r"""
    (?P<month>January|February|March|April|May|June|July|August|September|October|November|December)
    \s+
    (?P<day>\d{1,2})
    \s+
    (?P<dep_airport>[A-Z]{3})
    \s+
    (?P<arr_airport>[A-Z]{3})
    \s+
    [A-Z][A-Za-z .(),'/-]{2,80}?\s+to\s+[A-Z][A-Za-z .(),'/-]{2,80}?
    \s+
    Full\s+itinerary
    """,
    re.IGNORECASE | re.VERBOSE,
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
    source_received_at: Optional[datetime] = None


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

    raw_context = "\n".join(part for part in [from_email, subject, plain_text, html] if part)
    if _is_minimal_justfly_confirmation(raw_context):
        return ParseResult()

    # 1. JSON-LD (most reliable)
    if html:
        flights = extract_jsonld_flights(html)
        if flights:
            if not _jsonld_should_yield_to_text(flights, subject=subject, from_email=from_email):
                _stamp_source_received_at(flights, received_at)
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
                _stamp_source_received_at(flights, received_at)
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
    if _is_minimal_airasia_confirmation(v5_text):
        # Sparse-body AirAsia confirmations sometimes still encode the full
        # itinerary in their subject. Try the subject-line fallback before
        # giving up; otherwise the early return drops a real flight on the
        # floor.
        if subject:
            subject_flight = _extract_subject_itinerary_flight(subject, received_at=received_at)
            if subject_flight:
                _stamp_source_received_at([subject_flight], received_at)
                return ParseResult(
                    flights=[subject_flight],
                    passenger_name=subject_flight.passenger_name,
                    status=check_identity(subject_flight.passenger_name, user_name, aliases),
                    source="subject",
                )
        return ParseResult()
    if v5_text:
        v5_flights = extract_v5_flights(
            v5_text,
            pnr=_extract_pnr(v5_text.upper()),
            received_at=received_at,
        )
        if v5_flights:
            _stamp_source_received_at(v5_flights, received_at)
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
            _stamp_source_received_at(flights, received_at)
            passenger_name = flights[0].passenger_name
            return ParseResult(
                flights=flights,
                passenger_name=passenger_name,
                status=check_identity(passenger_name, user_name, aliases),
                source="heuristic",
            )

    # Last resort: some confirmation emails (AirAsia and similar carriers)
    # encode the entire itinerary in the subject line and leave the body too
    # sparse for the body extractors. Try a subject-only parse before giving
    # up — generic shape, not airline-specific.
    if subject:
        subject_flight = _extract_subject_itinerary_flight(subject, received_at=received_at)
        if subject_flight:
            _stamp_source_received_at([subject_flight], received_at)
            return ParseResult(
                flights=[subject_flight],
                passenger_name=subject_flight.passenger_name,
                status=check_identity(subject_flight.passenger_name, user_name, aliases),
                source="subject",
            )

    return ParseResult()


def _stamp_source_received_at(flights: list[ParsedFlight], received_at: Optional[datetime]) -> None:
    if not received_at:
        return
    for flight in flights:
        flight.source_received_at = received_at


def _extract_subject_itinerary_flight(
    subject: str, *, received_at: Optional[datetime]
) -> Optional[ParsedFlight]:
    """Lift a flight from a structured subject line.

    Some carriers (AirAsia, occasional Cebu/Lion variants) put the entire
    itinerary in the subject:
        ``<name> (CONFIRMED) Booking No: <PNR> DD/MM/YYYY <DEP> ✈ <ARR>``

    The body is too sparse to parse, so when every body extractor has
    already failed we try the subject. The date is ambiguous (DD/MM vs
    MM/DD) — we pick whichever interpretation produces a valid month/day
    that's also closer in time to ``received_at``. We don't synthesize a
    flight number because the subject rarely has one; downstream
    cross-referencing relies on route + date.
    """
    match = _V5_SUBJECT_ITINERARY.search(subject)
    if match:
        dep_airport = match.group("dep_airport").upper()
        arr_airport = match.group("arr_airport").upper()
        if not _valid_route(dep_airport, arr_airport):
            return None
        dep_date = _parse_ambiguous_short_date(match.group("date"), received_at)
        if not dep_date:
            return None
        return ParsedFlight(
            dep_airport=dep_airport,
            arr_airport=arr_airport,
            dep_time=dep_date,
            arr_time=dep_date + timedelta(hours=1),
            airline=None,
            flight_number=None,
            pnr=match.group("pnr").upper() if match.group("pnr") else None,
            source="subject",
        )

    place_match = _V5_SUBJECT_PLACE_ROUTE.search(subject)
    if not place_match:
        return None
    dep_airport = _airport_code_from_place_fragment(place_match.group("dep_place"))
    arr_airport = _airport_code_from_place_fragment(place_match.group("arr_place"))
    if not dep_airport or not arr_airport or not _valid_route(dep_airport, arr_airport):
        return None
    dep_date = _parse_compact_day_month_year(place_match.group("date"))
    if not dep_date:
        return None
    return ParsedFlight(
        dep_airport=dep_airport,
        arr_airport=arr_airport,
        dep_time=dep_date,
        arr_time=dep_date + timedelta(hours=1),
        airline=None,
        flight_number=None,
        pnr=None,
        source="subject",
    )


def _parse_ambiguous_short_date(
    date_str: str, received_at: Optional[datetime]
) -> Optional[datetime]:
    """Parse ``DD/MM/YYYY`` or ``MM/DD/YYYY`` and pick the more plausible reading.

    If only one interpretation produces a valid calendar date, use it. If
    both are valid, prefer the one closer to ``received_at`` (booking
    emails are typically dated within a few months of the flight).
    """
    parts = re.split(r"[/-]", date_str.strip())
    if len(parts) != 3:
        return None
    try:
        a, b, c = (int(part) for part in parts)
    except ValueError:
        return None
    if c < 100:
        c += 2000
    candidates: list[datetime] = []
    for day, month in ((a, b), (b, a)):
        if 1 <= month <= 12 and 1 <= day <= 31:
            try:
                candidates.append(datetime(c, month, day, tzinfo=timezone.utc))
            except ValueError:
                continue
    if not candidates:
        return None
    if len(candidates) == 1 or not received_at:
        return candidates[0]
    return min(candidates, key=lambda dt: abs((dt - received_at).total_seconds()))


def _parse_compact_day_month_year(value: str) -> Optional[datetime]:
    clean = value.strip()
    for fmt in ("%d%b%y", "%d%b%Y", "%d%B%y", "%d%B%Y"):
        try:
            return datetime.strptime(clean, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


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


def _is_minimal_airasia_confirmation(text: str) -> bool:
    lower = text.lower()
    if "airasia" not in lower or "booking no" not in lower:
        return False
    if "flight number" in lower or "departure date" in lower or "depart from" in lower:
        return False
    if re.search(r"\b\d{1,2}:\d{2}\b", text):
        return False
    return "email booking confimed" in lower or "booking confirmed" in lower


def _is_minimal_justfly_confirmation(text: str) -> bool:
    lower = text.lower()
    if "justfly" not in lower:
        return False
    if "confirmation number" not in lower and "booking number" not in lower:
        return False
    # These emails are account/booking shells. If they contain actual itinerary
    # rows, let the normal parser inspect them.
    itinerary_signals = (
        "flight details",
        "depart:",
        "departs:",
        "arrive:",
        "arrives:",
        "departure airport",
        "arrival airport",
        "duration:",
    )
    if any(signal in lower for signal in itinerary_signals):
        return False
    if re.search(r"\b[A-Z0-9]{2}\s*\d{1,4}\b", text) and re.search(r"\b[A-Z]{3}\s*(?:to|-|→|&gt;)\s*[A-Z]{3}\b", text):
        return False
    return True


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

    frontier_fast = _extract_frontier_confirmation_flights(text, pnr)
    frontier_fast.extend(_extract_frontier_simple_confirmation_flights(text, pnr))
    if frontier_fast:
        return _dedupe_flights(frontier_fast)

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
    text = _unwrap_forwarded(text)
    lines = _normalized_lines(text)
    evidence: list[_FlightEvidence] = []
    evidence.extend(_v5_labeled_itinerary_rows(text))
    evidence.extend(_v5_aa_trip_confirmation_rows(text))
    evidence.extend(_v5_code_route_lines(lines))
    evidence.extend(_v5_compact_checkin_rows(text))
    evidence.extend(_v5_route_rows(text, received_at))
    evidence.extend(_v5_city_time_rows(lines))
    evidence.extend(_v5_compact_route_rows(text))
    evidence.extend(_v5_labeled_depart_arrive_rows(text))
    evidence.extend(_v5_inline_blocks(text))
    evidence.extend(_v5_compact_reminder_lines(text))
    evidence.extend(_v5_boarding_route_lines(text, received_at))
    evidence.extend(_v5_bullet_format_rows(text, received_at))
    evidence.extend(_v5_airline_vertical_rows(text, received_at))
    evidence.extend(_v5_google_vertical_bullet_rows(text, received_at))
    evidence.extend(_v5_united_processing_vertical_rows(text, received_at))
    evidence.extend(_v5_airline_flight_route_rows(text, received_at))
    evidence.extend(_v5_legacy_terminal_itinerary_rows(text, received_at))
    evidence.extend(_v5_ba_eticket_rows(text))
    evidence.extend(_v5_frontier_departing_rows(text))
    evidence.extend(_v5_southwest_sparse_trip_rows(text, received_at))
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


def _v5_aa_trip_confirmation_rows(text: str) -> list[_FlightEvidence]:
    """Extract compact route rows like ``AUS DFW ... AA 2563``.

    These rows are common in airline itinerary emails and are safer than the
    broad inline-block fallback because the route codes appear before the
    clocks and the airline number is explicit.
    """
    rows: list[_FlightEvidence] = []
    for match in _AA_TRIP_CONFIRMATION_ROW.finditer(text):
        dep_airport = match.group("dep_airport").upper()
        arr_airport = match.group("arr_airport").upper()
        if not _valid_route(dep_airport, arr_airport):
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
                airline="AA",
                flight_number=f"AA{match.group('number').upper()}",
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


def _v5_code_route_lines(lines: list[str]) -> list[_FlightEvidence]:
    """Extract compact route rows while carrying the most recent visible date."""
    rows: list[_FlightEvidence] = []
    current_date: Optional[datetime] = None
    for line in lines:
        if _MONTH_DATE_LINE_RE.fullmatch(line):
            current_date = _parse_date_time(line, "12:00 AM")
            continue
        if not current_date:
            continue
        match = _V5_CODE_ROUTE_LINE.match(line)
        if not match:
            continue
        airline = match.group("airline").upper()
        dep_airport = match.group("dep_airport").upper()
        arr_airport = match.group("arr_airport").upper()
        if airline not in _KNOWN_AIRLINES or not _valid_route(dep_airport, arr_airport):
            continue
        dep_time = _parse_date_time(current_date.strftime("%B %d, %Y"), match.group("dep_time"))
        arr_time = _parse_date_time(current_date.strftime("%B %d, %Y"), match.group("arr_time"))
        if not dep_time or not arr_time:
            continue
        if arr_time <= dep_time:
            arr_time += timedelta(days=1)
        rows.append(
            _FlightEvidence(
                dep_airport=dep_airport,
                arr_airport=arr_airport,
                dep_time=dep_time,
                arr_time=arr_time,
                airline=airline,
                flight_number=f"{airline}{match.group('number').upper()}",
                score=_v5_score(line, has_airline=True) + 1,
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
        if match.end() < len(text) and text[match.end()] == ":":
            # Avoid treating the hour in ``12:48 PM`` as airline ``AM12``.
            continue
        if "operated by" in match.group(0).lower():
            # Operator labels such as ``ENVOY AIR`` contain airport-looking
            # words but are not route endpoints.
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


def _v5_compact_reminder_lines(text: str) -> list[_FlightEvidence]:
    """Extract single-line reminders like ``Flight 1915, EWR VPS Jul 23, 2019 at 12:00 PM``.

    Only the departure time is in the line; we synthesize the arrival time as
    dep + 1h so the segment is usable. The trip builder downstream computes
    real geometry from airport coordinates, so the placeholder duration is
    only ever shown as "approximate" inside the parser-emitted ParsedFlight.
    """
    rows: list[_FlightEvidence] = []
    for match in _V5_COMPACT_REMINDER_LINE.finditer(text):
        airline_raw = match.group("airline")
        airline = airline_raw.upper() if airline_raw else None
        if airline and airline not in _KNOWN_AIRLINES:
            airline = None
        dep_airport = match.group("dep_airport").upper()
        arr_airport = match.group("arr_airport").upper()
        if not _valid_route(dep_airport, arr_airport):
            continue
        dep_time = _parse_date_time(match.group("date"), match.group("time"))
        if not dep_time:
            continue
        arr_time = dep_time + timedelta(hours=1)
        block = _compact_space(match.group(0))
        flight_number = match.group("number").upper()
        if airline and not flight_number.startswith(airline):
            flight_number = f"{airline}{flight_number}"
        rows.append(
            _FlightEvidence(
                dep_airport=dep_airport,
                arr_airport=arr_airport,
                dep_time=dep_time,
                arr_time=arr_time,
                airline=airline,
                flight_number=flight_number,
                score=_v5_score(block, has_airline=bool(airline)),
            )
        )
    return rows


def _v5_boarding_route_lines(
    text: str, received_at: Optional[datetime]
) -> list[_FlightEvidence]:
    """Extract boarding-pass rows like ``JFK TO AMS, 6:00PM Sun, Dec 22, 2019``.

    These have no flight number and no arrival time. The route + departure
    timestamp is enough to cross-reference an existing trip, which is what
    the user wants for boarding-pass-style emails. Arrival time is set to
    dep + 1h as a non-zero placeholder; the builder rebuilds geometry from
    real coordinates anyway.
    """
    rows: list[_FlightEvidence] = []
    for match in _V5_BOARDING_ROUTE_LINE.finditer(text):
        dep_airport = match.group("dep_airport").upper()
        arr_airport = match.group("arr_airport").upper()
        if not _valid_route(dep_airport, arr_airport):
            continue
        dep_time = _parse_date_time(match.group("date"), match.group("time"))
        if not dep_time:
            continue
        arr_time = dep_time + timedelta(hours=1)
        block = _compact_space(match.group(0))
        rows.append(
            _FlightEvidence(
                dep_airport=dep_airport,
                arr_airport=arr_airport,
                dep_time=dep_time,
                arr_time=arr_time,
                airline=None,
                flight_number=None,
                score=_v5_score(block, has_airline=False),
            )
        )
    return rows


def _v5_bullet_format_rows(
    text: str, received_at: Optional[datetime]
) -> list[_FlightEvidence]:
    """Extract bullet-separated itineraries like
    ``Tue, Jun 7 · Tangier to Palma 12:25 PM–2:50 PM ... TNG ... PMI``.

    The aggregator templates Google/Kayak/Skyscanner use rarely include a
    year in the bullet line, so dates fall back to ``received_at`` for year
    inference via ``_parse_partial_date_time``. IATA codes appear later in
    the row; we accept the first pair within 200 chars.
    """
    rows: list[_FlightEvidence] = []
    for match in _V5_BULLET_FORMAT.finditer(text):
        dep_airport = match.group("dep_airport").upper()
        arr_airport = match.group("arr_airport").upper()
        if not _valid_route(dep_airport, arr_airport):
            continue
        date_str = match.group("date")
        dep_time = _parse_date_time(date_str, match.group("dep_time"))
        arr_time = _parse_date_time(date_str, match.group("arr_time"))
        if (not dep_time or not arr_time) and received_at:
            month_day = re.search(
                r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+(\d{1,2})",
                date_str,
                re.IGNORECASE,
            )
            if month_day:
                dep_time = _parse_partial_date_time(
                    month_day.group(1), month_day.group(2), match.group("dep_time"), received_at
                )
                arr_time = _parse_partial_date_time(
                    month_day.group(1), month_day.group(2), match.group("arr_time"), received_at
                )
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
                airline=None,
                flight_number=None,
                score=_v5_score(block, has_airline=False),
            )
        )
    return rows


def _v5_airline_vertical_rows(
    text: str, received_at: Optional[datetime]
) -> list[_FlightEvidence]:
    """Vertical multi-line itineraries (Justfly, Ethiopian, etc.).

    The shape is well-anchored: airline, ``Flight <num>``, optional terminal,
    departure time, departure DOW+date, departure airport, arrival time,
    arrival DOW+date, arrival airport — each on its own line.
    """
    rows: list[_FlightEvidence] = []
    for match in _V5_AIRLINE_VERTICAL.finditer(text):
        dep_airport = match.group("dep_airport").upper()
        arr_airport = match.group("arr_airport").upper()
        if not _valid_route(dep_airport, arr_airport):
            continue
        airline = _airline_code_from_name(match.group("airline_name"))
        dep_time = _parse_partial_date_time(
            match.group("dep_month"), match.group("dep_day"),
            match.group("dep_time"), received_at,
        )
        arr_time = _parse_partial_date_time(
            match.group("arr_month"), match.group("arr_day"),
            match.group("arr_time"), received_at,
        )
        if not dep_time or not arr_time:
            continue
        if arr_time <= dep_time:
            arr_time += timedelta(days=1)
        flight_number = match.group("number").upper()
        if airline and not flight_number.startswith(airline):
            flight_number = f"{airline}{flight_number}"
        block = _compact_space(match.group(0))
        rows.append(
            _FlightEvidence(
                dep_airport=dep_airport,
                arr_airport=arr_airport,
                dep_time=dep_time,
                arr_time=arr_time,
                airline=airline,
                flight_number=flight_number,
                score=_v5_score(block, has_airline=bool(airline)),
            )
        )
    return rows


def _v5_google_vertical_bullet_rows(
    text: str, received_at: Optional[datetime]
) -> list[_FlightEvidence]:
    """Google's bullet-vertical aggregator confirmation layout."""
    rows: list[_FlightEvidence] = []
    for match in _V5_GOOGLE_VERTICAL_BULLET.finditer(text):
        dep_airport = match.group("dep_airport").upper()
        arr_airport = match.group("arr_airport").upper()
        if not _valid_route(dep_airport, arr_airport):
            continue
        date_str = match.group("date")
        dep_time = _parse_date_time(date_str, match.group("dep_time"))
        arr_time = _parse_date_time(date_str, match.group("arr_time"))
        if (not dep_time or not arr_time) and received_at:
            month_day = re.search(
                r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+(\d{1,2})",
                date_str,
                re.IGNORECASE,
            )
            if month_day:
                dep_time = _parse_partial_date_time(
                    month_day.group(1), month_day.group(2), match.group("dep_time"), received_at
                )
                arr_time = _parse_partial_date_time(
                    month_day.group(1), month_day.group(2), match.group("arr_time"), received_at
                )
        if not dep_time or not arr_time:
            continue
        if arr_time <= dep_time:
            arr_time += timedelta(days=1)
        airline = _airline_code_from_name(match.group("airline_name"))
        flight_number = match.group("number").upper()
        if airline and not flight_number.startswith(airline):
            flight_number = f"{airline}{flight_number}"
        block = _compact_space(match.group(0))
        rows.append(
            _FlightEvidence(
                dep_airport=dep_airport,
                arr_airport=arr_airport,
                dep_time=dep_time,
                arr_time=arr_time,
                airline=airline,
                flight_number=flight_number,
                score=_v5_score(block, has_airline=bool(airline)),
            )
        )
    return rows


def _v5_united_processing_vertical_rows(
    text: str, received_at: Optional[datetime]
) -> list[_FlightEvidence]:
    """United 'reservation is processing' multi-line block per segment.

    Date is in a header line above the segment ('Wed, Oct 10, 2018'); we
    use the nearest prior full date for both endpoints.
    """
    rows: list[_FlightEvidence] = []
    for match in _V5_UNITED_PROCESSING_VERTICAL.finditer(text):
        dep_airport = match.group("dep_airport").upper()
        arr_airport = match.group("arr_airport").upper()
        if not _valid_route(dep_airport, arr_airport):
            continue
        header_date = _nearest_prior_full_date(text, match.start())
        if not header_date:
            continue
        dep_time_part = match.group("dep_time")
        arr_time_part = match.group("arr_time")
        dep_time = _parse_date_time(header_date.strftime("%b %d, %Y"), dep_time_part)
        arr_time = _parse_date_time(header_date.strftime("%b %d, %Y"), arr_time_part)
        if not dep_time or not arr_time:
            continue
        if arr_time <= dep_time:
            arr_time += timedelta(days=1)
        flight_number = f"UA{match.group('number').upper()}"
        block = _compact_space(match.group(0))
        rows.append(
            _FlightEvidence(
                dep_airport=dep_airport,
                arr_airport=arr_airport,
                dep_time=dep_time,
                arr_time=arr_time,
                airline="UA",
                flight_number=flight_number,
                score=_v5_score(block, has_airline=True),
            )
        )
    return rows


def _v5_airline_flight_route_rows(
    text: str, received_at: Optional[datetime]
) -> list[_FlightEvidence]:
    """Boarding-pass bodies that only list ``Flight UA1612\\nDallas (DFW) to Newark (EWR)``.

    These emails are sent within hours of departure, so we synthesize
    ``dep_time = received_at`` and ``arr_time = received_at + 2h`` as a
    placeholder. The downstream trip builder rebuilds geometry from real
    coordinates anyway, and the route + flight# is enough to
    cross-reference with an existing parsed trip.
    """
    rows: list[_FlightEvidence] = []
    if not received_at:
        return rows
    for match in _V5_AIRLINE_FLIGHT_ROUTE_LINE.finditer(text):
        airline = match.group("airline").upper()
        if airline not in _KNOWN_AIRLINES:
            continue
        dep_airport = match.group("dep_airport").upper()
        arr_airport = match.group("arr_airport").upper()
        if not _valid_route(dep_airport, arr_airport):
            continue
        flight_number = f"{airline}{match.group('number').upper()}"
        dep_time = received_at
        arr_time = received_at + timedelta(hours=2)
        block = _compact_space(match.group(0))
        rows.append(
            _FlightEvidence(
                dep_airport=dep_airport,
                arr_airport=arr_airport,
                dep_time=dep_time,
                arr_time=arr_time,
                airline=airline,
                flight_number=flight_number,
                score=_v5_score(block, has_airline=True),
            )
        )
    return rows


def _v5_legacy_terminal_itinerary_rows(
    text: str,
    received_at: Optional[datetime],
) -> list[_FlightEvidence]:
    rows: list[_FlightEvidence] = []
    if not received_at:
        return rows
    search_text = _compact_space(text)
    for match in _V5_LEGACY_TERMINAL_ITINERARY.finditer(search_text):
        dep_airport = _airport_code_from_place_fragment(match.group("dep_place"))
        arr_airport = _airport_code_from_place_fragment(match.group("arr_place"))
        if not dep_airport or not arr_airport or not _valid_route(dep_airport, arr_airport):
            continue

        dep_time = _parse_compact_dow_day_month_time(
            match.group("dep_date"),
            match.group("dep_time"),
            received_at,
        )
        arr_time = _parse_compact_dow_day_month_time(
            match.group("arr_date"),
            match.group("arr_time"),
            received_at,
        )
        if not dep_time or not arr_time:
            continue
        if arr_time <= dep_time:
            arr_time += timedelta(days=1)

        airline = _infer_airline_from_context(match.group("head")) or "UA"
        flight_number = _legacy_terminal_flight_number(match.group("head"), airline)
        rows.append(
            _FlightEvidence(
                dep_airport=dep_airport,
                arr_airport=arr_airport,
                dep_time=dep_time,
                arr_time=arr_time,
                airline=airline,
                flight_number=flight_number,
                score=_v5_score(match.group(0), has_airline=bool(airline)) + 1,
            )
        )
    return rows


def _legacy_terminal_flight_number(head: str, airline: Optional[str]) -> Optional[str]:
    numbers = re.findall(r"\b(\d{3,4}[A-Z]?)\b", head)
    if not numbers:
        return None
    number = numbers[-1].upper()
    return f"{airline}{number}" if airline else number


def _v5_ba_eticket_rows(text: str) -> list[_FlightEvidence]:
    rows: list[_FlightEvidence] = []
    for match in _V5_BA_ETICKET_ITINERARY.finditer(text):
        airline = _airline_code_from_name(match.group("airline_name"))
        dep_airport = _airport_code_from_place_fragment(match.group("dep_place"))
        arr_airport = _airport_code_from_place_fragment(match.group("arr_place"))
        if not dep_airport or not arr_airport or not _valid_route(dep_airport, arr_airport):
            continue
        dep_time = _parse_date_time(match.group("dep_date"), match.group("dep_time"))
        arr_time = _parse_date_time(match.group("arr_date"), match.group("arr_time"))
        if not dep_time or not arr_time:
            continue
        if arr_time <= dep_time:
            arr_time += timedelta(days=1)
        rows.append(
            _FlightEvidence(
                dep_airport=dep_airport,
                arr_airport=arr_airport,
                dep_time=dep_time,
                arr_time=arr_time,
                airline=airline,
                flight_number=None,
                score=8,
                source="v5_ba_eticket",
            )
        )
    return rows


def _v5_frontier_departing_rows(text: str) -> list[_FlightEvidence]:
    rows: list[_FlightEvidence] = []
    for match in _V5_FRONTIER_DEPARTING_ROW.finditer(text):
        dep_airport = match.group("dep_airport").upper()
        arr_airport = match.group("arr_airport").upper()
        if not _valid_route(dep_airport, arr_airport):
            continue
        dep_time = _parse_date_time(match.group("date"), match.group("dep_time"))
        arr_time = _parse_date_time(match.group("date"), match.group("arr_time"))
        if not dep_time or not arr_time:
            continue
        if arr_time <= dep_time:
            arr_time += timedelta(days=1)
        rows.append(
            _FlightEvidence(
                dep_airport=dep_airport,
                arr_airport=arr_airport,
                dep_time=dep_time,
                arr_time=arr_time,
                airline="F9",
                flight_number=f"F9{match.group('number').upper()}",
                score=9,
                source="v5_frontier_departing",
            )
        )
    return rows


def _v5_southwest_sparse_trip_rows(
    text: str,
    received_at: Optional[datetime],
) -> list[_FlightEvidence]:
    if not received_at:
        return []
    rows: list[_FlightEvidence] = []
    for match in _V5_SOUTHWEST_SPARSE_TRIP.finditer(text):
        dep_airport = match.group("dep_airport").upper()
        arr_airport = match.group("arr_airport").upper()
        if not _valid_route(dep_airport, arr_airport):
            continue
        dep_time = _parse_partial_date_time(
            match.group("month"),
            match.group("day"),
            "12:00 AM",
            received_at,
        )
        if not dep_time:
            continue
        rows.append(
            _FlightEvidence(
                dep_airport=dep_airport,
                arr_airport=arr_airport,
                dep_time=dep_time,
                arr_time=dep_time + timedelta(hours=1),
                airline="WN",
                flight_number=None,
                score=7,
                source="v5_southwest_sparse",
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
    flights.extend(_extract_delta_trip_details_flights(text, pnr, received_at))
    flights.extend(_extract_aa_trip_confirmation_flights(text, pnr))
    flights.extend(_extract_united_eticket_flights(text, pnr))
    flights.extend(_extract_frontier_confirmation_flights(text, pnr))
    flights.extend(_extract_airline_departs_arrives_flights(text, pnr))
    flights.extend(_extract_labeled_route_time_flights(text, pnr))
    flights.extend(_extract_spirit_confirmation_flights(text, pnr))
    flights.extend(_extract_aa_inline_receipt_flights(text, pnr))
    flights.extend(_extract_aa_hold_table_flights(text, pnr, received_at))
    flights.extend(_extract_partner_award_flights(text, pnr, received_at))
    flights.extend(_extract_airline_route_flight_flights(text, pnr, received_at))
    flights.extend(_extract_arrives_route_flights(text, pnr, received_at))
    flights.extend(_extract_city_table_itinerary_flights(text, pnr))
    flights.extend(_extract_priceline_alert_flights(text, pnr))
    flights.extend(_extract_travelocity_route_flights(text, pnr, received_at))
    flights.extend(_extract_allegiant_itinerary_flights(text, pnr))
    flights.extend(_extract_aa_text_itinerary_flights(text, pnr))
    flights.extend(_extract_alaska_partner_confirmation_flights(text, pnr, received_at))
    flights.extend(_extract_united_reservation_table_flights(text, pnr))
    flights.extend(_extract_delta_forwarded_itinerary_flights(text, pnr))
    flights.extend(_extract_amadeus_boarding_flights(text, pnr))
    flights.extend(_extract_sun_country_trip_flights(text, pnr))
    flights.extend(_extract_eva_checkin_flights(text, pnr))
    flights.extend(_extract_frontier_simple_confirmation_flights(text, pnr))
    flights.extend(_extract_delta_receipt_flights(text, pnr, received_at))
    flights.extend(_extract_expedia_flight_flights(text, pnr, received_at))
    flights.extend(_extract_ba_eticket_itinerary_flights(text, pnr))
    flights.extend(_extract_lifemiles_flights(text, pnr))
    flights.extend(_extract_iberia_purchase_detail_flights(text, pnr))
    return _dedupe_flights(flights)


def _extract_delta_trip_details_flights(
    text: str,
    pnr: Optional[str],
    received_at: Optional[datetime],
) -> list[ParsedFlight]:
    flights: list[ParsedFlight] = []
    if not received_at:
        return flights
    for match in _DELTA_TRIP_DETAILS_SEGMENT.finditer(text):
        airline = match.group("airline").upper()
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


def _extract_aa_trip_confirmation_flights(text: str, pnr: Optional[str]) -> list[ParsedFlight]:
    flights: list[ParsedFlight] = []
    for match in _AA_TRIP_CONFIRMATION_ROW.finditer(text):
        dep_airport = match.group("dep_airport").upper()
        arr_airport = match.group("arr_airport").upper()
        if not _valid_route(dep_airport, arr_airport):
            continue
        dep_time = _parse_date_time(match.group("date"), match.group("dep_time"))
        arr_time = _parse_date_time(match.group("date"), match.group("arr_time"))
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
                airline="AA",
                flight_number=f"AA{match.group('number').upper()}",
                pnr=pnr,
                source="heuristic",
            )
        )
    return flights


def _extract_united_eticket_flights(text: str, pnr: Optional[str]) -> list[ParsedFlight]:
    flights: list[ParsedFlight] = []
    for match in _UNITED_ETICKET_ROW.finditer(text):
        dep_airport = match.group("dep_airport").upper()
        arr_airport = match.group("arr_airport").upper()
        if not _valid_route(dep_airport, arr_airport):
            continue
        dep_time = _parse_united_compact_date_time(match.group("date"), match.group("dep_time"))
        arr_time = _parse_united_compact_date_time(match.group("date"), match.group("arr_time"))
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
                airline="UA",
                flight_number=f"UA{match.group('number').upper()}",
                pnr=pnr,
                source="heuristic",
            )
        )
    return flights


def _extract_frontier_confirmation_flights(text: str, pnr: Optional[str]) -> list[ParsedFlight]:
    flights: list[ParsedFlight] = []
    if "frontier" not in text.lower():
        return flights
    search_text = _frontier_search_window(text)
    for match in _FRONTIER_CONFIRMATION_ROW.finditer(search_text):
        dep_airport = match.group("dep_airport").upper()
        arr_airport = match.group("arr_airport").upper()
        if not _valid_route(dep_airport, arr_airport):
            continue
        dep_time = _parse_date_time(match.group("dep_date"), match.group("dep_time"))
        arr_time = _parse_date_time(match.group("arr_date"), match.group("arr_time"))
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
                airline="F9",
                flight_number=f"F9{match.group('number').upper()}",
                pnr=pnr,
                source="heuristic",
            )
        )
    return flights


def _extract_airline_departs_arrives_flights(text: str, pnr: Optional[str]) -> list[ParsedFlight]:
    flights: list[ParsedFlight] = []
    for match in _AIRLINE_DEPARTS_ARRIVES_ROW.finditer(text):
        airline = _airline_code_from_name(match.group("airline_name"))
        dep_airport = match.group("dep_airport").upper()
        arr_airport = match.group("arr_airport").upper()
        if (airline not in _KNOWN_AIRLINES and airline != "AT") or not _valid_route(dep_airport, arr_airport):
            continue
        dep_time = _parse_date_time(match.group("dep_date"), match.group("dep_time"))
        arr_time = _parse_date_time(match.group("arr_date"), match.group("arr_time"))
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


def _extract_labeled_route_time_flights(text: str, pnr: Optional[str]) -> list[ParsedFlight]:
    flights: list[ParsedFlight] = []
    for match in _LABEL_ROUTE_TIME_FLIGHT_ROW.finditer(text):
        airline = match.group("airline").upper()
        dep_airport = match.group("dep_airport").upper()
        arr_airport = match.group("arr_airport").upper()
        if airline not in _KNOWN_AIRLINES or not _valid_route(dep_airport, arr_airport):
            continue
        dep_time = _parse_date_time(match.group("dep_date"), match.group("dep_time"))
        arr_time = _parse_date_time(match.group("arr_date"), match.group("arr_time"))
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


def _extract_spirit_confirmation_flights(text: str, pnr: Optional[str]) -> list[ParsedFlight]:
    flights: list[ParsedFlight] = []
    if "spirit" not in text.lower():
        return flights
    for match in list(_SPIRIT_CONFIRMATION_ROW.finditer(text)) + list(_SPIRIT_CONFIRMATION_TEXT_ROW.finditer(text)):
        dep_airport = _airport_code_from_place(match.group("dep_place"))
        arr_airport = _airport_code_from_place(match.group("arr_place"))
        if not dep_airport or not arr_airport or not _valid_route(dep_airport, arr_airport):
            continue
        dep_time = _parse_date_time(match.group("date"), match.group("dep_time"))
        arr_time = _parse_date_time(match.group("date"), match.group("arr_time"))
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
                airline="NK",
                pnr=pnr,
                source="heuristic",
            )
        )
    return flights


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
    lower = text.lower()
    if "flight number" not in lower or "departure date" not in lower:
        return flights
    search_text = text
    new_schedule_at = lower.rfind("new schedule")
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


def _extract_priceline_alert_flights(text: str, pnr: Optional[str]) -> list[ParsedFlight]:
    flights: list[ParsedFlight] = []
    lower = text.lower()
    if "priceline" not in lower and ("departs:" not in lower or "arrives:" not in lower):
        return flights
    search_text = _compact_space(text)
    for match in _PRICELINE_ALERT_ROW.finditer(search_text):
        airline = _airline_code_from_name(match.group("airline_name"))
        dep_airport = match.group("dep_airport").upper()
        arr_airport = match.group("arr_airport").upper()
        if not airline or not _valid_route(dep_airport, arr_airport):
            continue
        dep_time = _parse_date_time(match.group("dep_date"), match.group("dep_time"))
        arr_time = _parse_date_time(match.group("arr_date"), match.group("arr_time"))
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


def _extract_travelocity_route_flights(
    text: str,
    pnr: Optional[str],
    received_at: Optional[datetime],
) -> list[ParsedFlight]:
    flights: list[ParsedFlight] = []
    search_text = _compact_space(text)
    for match in _TRAVELOCITY_ROUTE_ROW.finditer(search_text):
        airline = _airline_code_from_name(match.group("airline_name"))
        dep_airport = match.group("dep_airport").upper()
        arr_airport = match.group("arr_airport").upper()
        if not airline or not _valid_route(dep_airport, arr_airport):
            continue
        dep_time = _parse_short_date_time(match.group("date"), match.group("dep_time"), received_at)
        arr_time = _parse_short_date_time(match.group("date"), match.group("arr_time"), received_at)
        if not dep_time or not arr_time:
            continue
        if "+1 day" in (match.group("tail") or "").lower() or arr_time <= dep_time:
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


def _extract_allegiant_itinerary_flights(text: str, pnr: Optional[str]) -> list[ParsedFlight]:
    flights: list[ParsedFlight] = []
    search_text = _compact_space(text)
    for match in _ALLEGIENT_ITINERARY_ROW.finditer(search_text):
        dep_airport = match.group("dep_airport").upper()
        arr_airport = match.group("arr_airport").upper()
        if not _valid_route(dep_airport, arr_airport):
            continue
        dep_time = _parse_date_time(match.group("date"), match.group("dep_time"))
        arr_time = _parse_date_time(match.group("date"), match.group("arr_time"))
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
                airline="G4",
                flight_number=f"G4{match.group('number').upper()}",
                pnr=pnr,
                source="heuristic",
            )
        )
    return flights


def _extract_aa_text_itinerary_flights(text: str, pnr: Optional[str]) -> list[ParsedFlight]:
    flights: list[ParsedFlight] = []
    search_text = _compact_space(text)
    for match in _AA_TEXT_ITINERARY_ROW.finditer(search_text):
        dep_airport = match.group("dep_airport").upper()
        arr_airport = match.group("arr_airport").upper()
        if not _valid_route(dep_airport, arr_airport):
            continue
        dep_time = _parse_date_time(match.group("dep_date"), match.group("dep_time"))
        arr_time = _parse_date_time(match.group("arr_date"), match.group("arr_time"))
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
                airline="AA",
                flight_number=f"AA{match.group('number').upper()}",
                pnr=pnr,
                source="heuristic",
            )
        )
    return flights


def _extract_alaska_partner_confirmation_flights(
    text: str, pnr: Optional[str], received_at: Optional[datetime] = None
) -> list[ParsedFlight]:
    flights: list[ParsedFlight] = []
    lower = text.lower()
    if (
        "flight information" not in lower
        and "confirmation letter" not in lower
        and "alaska" not in lower
    ):
        return flights
    if "flight:" not in lower or "departs:" not in lower or "arrives:" not in lower:
        return flights
    search_text = _compact_space(text)
    for match in _ALASKA_PARTNER_CONFIRMATION_ROW.finditer(search_text):
        airline = _airline_code_from_name(match.group("airline_name"))
        dep_airport = match.group("dep_airport").upper()
        arr_airport = match.group("arr_airport").upper()
        if not airline or not _valid_route(dep_airport, arr_airport):
            continue
        dep_time = _parse_date_time(match.group("dep_date"), match.group("dep_time"))
        arr_time = _parse_date_time(match.group("arr_date"), match.group("arr_time"))
        # Alaska's partner confirmation often omits the year ("Tue, Mar 24 at
        # 6:00 am"). Fall back to received_at-anchored partial-date parsing.
        if (not dep_time or not arr_time) and received_at:
            dep_md = re.search(
                r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+(\d{1,2})",
                match.group("dep_date"),
                re.IGNORECASE,
            )
            arr_md = re.search(
                r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+(\d{1,2})",
                match.group("arr_date"),
                re.IGNORECASE,
            )
            if dep_md and arr_md:
                dep_time = _parse_partial_date_time(
                    dep_md.group(1), dep_md.group(2), match.group("dep_time"), received_at
                )
                arr_time = _parse_partial_date_time(
                    arr_md.group(1), arr_md.group(2), match.group("arr_time"), received_at
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


def _extract_united_reservation_table_flights(text: str, pnr: Optional[str]) -> list[ParsedFlight]:
    flights: list[ParsedFlight] = []
    lower = text.lower()
    if "united airlines" not in lower or "duration:" not in lower:
        return flights
    search_text = _compact_space(text)
    anchor = search_text.lower().find("itinerary for record locator")
    if anchor < 0:
        anchor = search_text.lower().find("united airlines")
    if anchor >= 0:
        search_text = search_text[max(0, anchor - 800):anchor + 16000]
    for match in _UNITED_RESERVATION_SEGMENT.finditer(search_text):
        dep_airport = _airport_code_from_place(match.group("dep_place"))
        arr_airport = _airport_code_from_place(match.group("arr_place"))
        if not dep_airport or not arr_airport or not _valid_route(dep_airport, arr_airport):
            continue
        header = _nearest_prior_full_date(search_text, match.start()) or _nearest_prior_united_compact_date(search_text, match.start())
        if not header:
            continue
        dep_time = _parse_date_time(header.strftime("%b %d, %Y"), match.group("dep_time"))
        arr_time = _parse_date_time(header.strftime("%b %d, %Y"), match.group("arr_time"))
        if not dep_time or not arr_time:
            continue
        if arr_time <= dep_time:
            arr_time += timedelta(days=1)
        number = match.group("number")
        flights.append(
            ParsedFlight(
                dep_airport=dep_airport,
                arr_airport=arr_airport,
                dep_time=dep_time,
                arr_time=arr_time,
                airline="UA",
                flight_number=f"UA{number.upper()}",
                pnr=pnr,
                source="heuristic",
            )
        )
    return flights


def _extract_delta_forwarded_itinerary_flights(text: str, pnr: Optional[str]) -> list[ParsedFlight]:
    flights: list[ParsedFlight] = []
    if "delta" not in text.lower() and "►" not in text:
        return flights
    normalized = _compact_space(text).replace("&#9658;", "►")
    for match in _DELTA_FORWARDED_ITINERARY_ROW.finditer(normalized):
        dep_airport = match.group("dep_airport").upper()
        arr_airport = match.group("arr_airport").upper()
        if not _valid_route(dep_airport, arr_airport):
            continue
        dep_time = _parse_date_time(match.group("dep_date"), match.group("dep_time"))
        arr_time = _parse_date_time(match.group("arr_date"), match.group("arr_time"))
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
                airline="DL",
                flight_number=f"DL{match.group('number').upper()}",
                pnr=pnr,
                source="heuristic",
            )
        )
    return flights


def _extract_amadeus_boarding_flights(text: str, pnr: Optional[str]) -> list[ParsedFlight]:
    flights: list[ParsedFlight] = []
    search_text = _compact_space(text)
    for match in _AMADEUS_BOARDING_ROW.finditer(search_text):
        airline = match.group("airline").upper()
        dep_airport = match.group("dep_airport").upper()
        arr_airport = match.group("arr_airport").upper()
        if (airline not in _KNOWN_AIRLINES and airline != "AT") or not _valid_route(dep_airport, arr_airport):
            continue
        dep_time = _parse_date_time(match.group("date"), match.group("dep_time"))
        arr_time = _parse_date_time(match.group("date"), match.group("arr_time"))
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


def _extract_sun_country_trip_flights(text: str, pnr: Optional[str]) -> list[ParsedFlight]:
    flights: list[ParsedFlight] = []
    search_text = _compact_space(text)
    for match in _SUN_COUNTRY_TRIP_ROW.finditer(search_text):
        dep_airport = match.group("dep_airport").upper()
        arr_airport = match.group("arr_airport").upper()
        if not _valid_route(dep_airport, arr_airport):
            continue
        dep_time = _parse_date_time(match.group("dep_date"), match.group("dep_time"))
        arr_time = _parse_date_time(match.group("arr_date"), match.group("arr_time"))
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
                airline="SY",
                flight_number=f"SY{match.group('number').upper()}",
                pnr=pnr,
                source="heuristic",
            )
        )
    return flights


def _extract_eva_checkin_flights(text: str, pnr: Optional[str]) -> list[ParsedFlight]:
    flights: list[ParsedFlight] = []
    if "eva" not in text.lower() and "br0" not in text.lower():
        return flights
    search_text = _compact_space(text)
    for match in _EVA_CHECKIN_ROW.finditer(search_text):
        dep_airport = _airport_code_from_place(match.group("dep_place"))
        arr_airport = _airport_code_from_place(match.group("arr_place"))
        if not dep_airport or not arr_airport or not _valid_route(dep_airport, arr_airport):
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
                airline="BR",
                flight_number=f"BR{match.group('number').upper()}",
                pnr=pnr,
                source="heuristic",
            )
        )
    return flights


def _extract_frontier_simple_confirmation_flights(text: str, pnr: Optional[str]) -> list[ParsedFlight]:
    flights: list[ParsedFlight] = []
    if "frontier" not in text.lower() and " f9 " not in text.lower():
        return flights
    search_text = _frontier_search_window(text)
    for match in _FRONTIER_SIMPLE_CONFIRMATION_ROW.finditer(search_text):
        dep_airport = match.group("dep_airport").upper()
        arr_airport = match.group("arr_airport").upper()
        if not _valid_route(dep_airport, arr_airport):
            continue
        dep_time = _parse_date_time(match.group("date"), match.group("dep_time"))
        arr_time = _parse_date_time(match.group("date"), match.group("arr_time"))
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
                airline="F9",
                flight_number=f"F9{match.group('number').upper()}",
                pnr=pnr,
                source="heuristic",
            )
        )
    return flights


def _frontier_search_window(text: str) -> str:
    search_text = _compact_space(re.sub(r"<[^>]+>", " ", text) if "<" in text and ">" in text else text)
    lower = search_text.lower()
    anchors = [
        lower.find("departing flight"),
        lower.find("returning flight"),
        lower.find("flight departure arrival duration"),
        lower.find("flight confirmation code"),
    ]
    anchors = [anchor for anchor in anchors if anchor >= 0]
    if not anchors:
        return search_text[:12000]
    start = max(0, min(anchors) - 1000)
    return search_text[start:start + 16000]


def _extract_delta_receipt_flights(
    text: str,
    pnr: Optional[str],
    received_at: Optional[datetime],
) -> list[ParsedFlight]:
    flights: list[ParsedFlight] = []
    lower = text.lower()
    if "depart arrive delta" not in lower:
        return flights
    search_text = _compact_space(text)
    for match in _DELTA_RECEIPT_ROW.finditer(search_text):
        dep_airport = _airport_code_from_place(match.group("dep_place"))
        arr_airport = _airport_code_from_place(match.group("arr_place"))
        if not dep_airport or not arr_airport or not _valid_route(dep_airport, arr_airport):
            continue
        dep_time = _parse_delta_receipt_datetime(match.group("date"), match.group("dep_time"), received_at)
        arr_time = _parse_delta_receipt_datetime(match.group("date"), match.group("arr_time"), received_at)
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
                airline="DL",
                flight_number=f"DL{match.group('number').upper()}",
                pnr=pnr,
                source="heuristic",
            )
        )
    return flights


def _extract_expedia_flight_flights(
    text: str,
    pnr: Optional[str],
    received_at: Optional[datetime],
) -> list[ParsedFlight]:
    flights: list[ParsedFlight] = []
    lower = text.lower()
    if "flight duration" not in lower:
        return flights
    search_text = _compact_space(text)
    for match in _EXPEDIA_FLIGHT_ROW.finditer(search_text):
        airline = _airline_code_from_name(match.group("airline_name"))
        dep_airport = match.group("dep_airport").upper()
        arr_airport = match.group("arr_airport").upper()
        if not airline or not _valid_route(dep_airport, arr_airport):
            continue
        dep_time = _parse_short_date_time(match.group("date"), match.group("dep_time"), received_at)
        arr_time = _parse_short_date_time(match.group("date"), match.group("arr_time"), received_at)
        if not dep_time or not arr_time:
            continue
        if "+1" in (match.group("tail") or "") or arr_time <= dep_time:
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


def _extract_ba_eticket_itinerary_flights(text: str, pnr: Optional[str]) -> list[ParsedFlight]:
    flights: list[ParsedFlight] = []
    lower = text.lower()
    if "british airways" not in lower and "your e-ticket receipt" not in lower:
        return flights
    search_text = _compact_space(text)
    for match in _BA_ETICKET_ITINERARY_ROW.finditer(search_text):
        airline = match.group("airline").upper()
        dep_airport = _airport_code_from_place(match.group("dep_place"))
        arr_airport = _airport_code_from_place(match.group("arr_place"))
        if airline not in _KNOWN_AIRLINES or not dep_airport or not arr_airport:
            continue
        if not _valid_route(dep_airport, arr_airport):
            continue
        dep_time = _parse_date_time(match.group("dep_date"), match.group("dep_time"))
        arr_time = _parse_date_time(match.group("arr_date"), match.group("arr_time"))
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


def _extract_lifemiles_flights(text: str, pnr: Optional[str]) -> list[ParsedFlight]:
    flights: list[ParsedFlight] = []
    lower = text.lower()
    if "departure:" not in lower or "arrival:" not in lower:
        return flights
    if "lifemiles" not in lower and "flight 1" not in lower:
        return flights
    source_text = re.sub(r"<[^>]+>", " ", text) if "<" in text and ">" in text else text
    search_text = _compact_space(source_text)
    details_idx = search_text.lower().find("flight details")
    if details_idx >= 0:
        search_text = search_text[details_idx:details_idx + 8000]
    else:
        search_text = search_text[:12000]
    for match in _LIFEMILES_FLIGHT_ROW.finditer(search_text):
        airline = match.group("airline").upper()
        dep_airport = match.group("dep_airport").upper()
        arr_airport = match.group("arr_airport").upper()
        if airline not in _KNOWN_AIRLINES or not _valid_route(dep_airport, arr_airport):
            continue
        dep_time = _parse_date_time(match.group("dep_date"), match.group("dep_time"))
        arr_time = _parse_date_time(match.group("arr_date"), match.group("arr_time"))
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


def _extract_iberia_purchase_detail_flights(text: str, pnr: Optional[str]) -> list[ParsedFlight]:
    flights: list[ParsedFlight] = []
    lower = text.lower()
    if "iberia" not in lower or "purchase" not in lower:
        return flights
    search_text = _compact_space(text)
    for match in _IBERIA_PURCHASE_DETAIL_ROW.finditer(search_text):
        dep_airport = _airport_code_from_place(match.group("dep_place"))
        arr_airport = _airport_code_from_place(match.group("arr_place"))
        dep_label_airport = _airport_code_from_place(match.group("dep_label"))
        arr_label_airport = _airport_code_from_place(match.group("arr_label"))
        if not dep_airport or not arr_airport or not _valid_route(dep_airport, arr_airport):
            continue
        if dep_label_airport and dep_label_airport != dep_airport:
            continue
        if arr_label_airport and arr_label_airport != arr_airport:
            continue
        dep_time = _parse_date_time(match.group("date"), match.group("dep_time"))
        arr_time = _parse_date_time(match.group("date"), match.group("arr_time"))
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
                airline="IB",
                flight_number=f"IB{match.group('number').upper()}",
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
    lower = text.lower()
    if "redeemed" not in lower and "lifemiles" not in lower and "award" not in lower:
        return flights
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
    "united": "UA",
    "delta air lines": "DL",
    "delta airlines": "DL",
    "frontier airlines": "F9",
    "frontier": "F9",
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
    "emirates airlines": "EK",
    "emirates": "EK",
    "royal air maroc": "AT",
}

_PLACE_AIRPORT_OVERRIDES = {
    "DALLAS FORT WORTH TX": "DFW",
    "DALLAS FORT WORTH": "DFW",
    "DALLAS FT WORTH TX": "DFW",
    "DALLAS FT WORTH": "DFW",
    "DALLAS DALLAS/FORT WORTH INTL APT US TERMINAL E": "DFW",
    "DALLAS DALLAS/FORT WORTH INTL APT US": "DFW",
    "DALLAS FT WORTH TX DALLAS": "DFW",
    "DALLAS FORT WORTH TX DALLAS": "DFW",
    "DALLAS/FORT WORTH TX": "DFW",
    "DALLAS": "DFW",
    "FORT LAUDERDALE FL": "FLL",
    "MANAGUA NICARAGUA": "MGA",
    "MEXICO CITY MEXICO": "MEX",
    "HOUSTON": "IAH",
    "HOUSTON TX": "IAH",
    "HOUSTON GEORGE BUSH INTERCONTINENTAL": "IAH",
    "HOUSTON GEORGE BUSH INTERCONTINENTAL AP": "IAH",
    "NASHVILLE": "BNA",
    "NASHVILLE INTERNATIONAL": "BNA",
    "NASHVILLE INTERNATIONAL TN": "BNA",
    "NASHVILLE TN": "BNA",
    "NASHVILLE TENNESSEE": "BNA",
    "CHICAGO O HARE INTERNATIONAL APT US TERMINAL": "ORD",
    "CHICAGO O HARE INTERNATIONAL APT US TERMINAL 1": "ORD",
    "CHICAGO O HARE INTERNATIONAL APT US TERMINAL 2": "ORD",
    "CHICAGO O HARE INTERNATIONAL APT US": "ORD",
    "CHICAGO O HARE INTERNATIONAL": "ORD",
    "CHICAGO O HARE": "ORD",
    "CHICAGO OHARE": "ORD",
    "FRANKFURT INTERNATIONAL APT DE TERMINAL": "FRA",
    "FRANKFURT INTERNATIONAL APT DE TERMINAL 1": "FRA",
    "FRANKFURT INTERNATIONAL APT DE": "FRA",
    "NAIROBI JOMO KENYATTA INTERNATIONAL AP KE": "NBO",
    "NAIROBI JOMO KENYATTA INTERNATIONAL APT KE": "NBO",
    "NEWARK LIBERTY INTERNATIONAL APT US TERMINAL": "EWR",
    "NEWARK LIBERTY INTERNATIONAL APT US TERMINAL B": "EWR",
    "NEWARK LIBERTY INTERNATIONAL APT US TERMINAL C": "EWR",
    "NEWARK LIBERTY INTERNATIONAL APT US": "EWR",
    "ORLANDO": "MCO",
    "ORLANDO FL": "MCO",
    "ORLANDO FLORIDA": "MCO",
    "ATLANTA GA": "ATL",
    "BALTIMORE MD": "BWI",
    "NEW YORK NY LAGUARDIA": "LGA",
    "NEW YORK LAGUARDIA": "LGA",
    "NYC KENNEDY": "JFK",
    "SAN FRANCISCO CA": "SFO",
    "TANGIER": "TNG",
    "TANGIER MOROCCO": "TNG",
    "MADRID": "MAD",
    "MADRID SPAIN": "MAD",
    "PALMA DE MALLORCA": "PMI",
    "PALMA DE MALLORCA SPAIN": "PMI",
    "PALMA": "PMI",
    "TAIPEI": "TPE",
    "TAIPEI TAOYUAN": "TPE",
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
        if not _VALID_IATA or code in _VALID_IATA:
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


def _airport_code_from_place_fragment(fragment: str) -> Optional[str]:
    direct = _airport_code_from_place(fragment)
    if direct:
        return direct

    words = _normalize_place_key(fragment).split()
    for size in range(min(len(words), 12), 1, -1):
        for start in range(0, len(words) - size + 1):
            candidate = " ".join(words[start : start + size])
            code = _airport_code_from_place(candidate)
            if code:
                return code
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
    clean_date = re.sub(r"\b([A-Za-z]{3,})\.", r"\1", clean_date)
    clean_date = re.sub(r"\b(\d{1,2})\s*(?:st|nd|rd|th)\b", r"\1", clean_date, flags=re.IGNORECASE)
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
        "%m/%d/%Y %I:%M %p",
        "%m/%d/%y %I:%M %p",
        "%Y/%m/%d %H:%M",
        "%A %d %b %y %H:%M",
        "%A %d %b %Y %H:%M",
        "%a %d %b %y %H:%M",
        "%a %d %b %Y %H:%M",
        "%B %d %Y %I:%M %p",
        "%b %d %Y %I:%M %p",
        "%d %b %Y %I:%M %p",
        "%d %B %Y %I:%M %p",
        "%A %d %B %Y %H:%M",
        "%A %d %B %Y %I:%M %p",
        "%a %d %b %Y %I:%M %p",
        "%a %d %B %Y %I:%M %p",
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


def _parse_united_compact_date_time(date_part: str, time_part: str) -> Optional[datetime]:
    clean_date = re.sub(r",", "", date_part.strip().upper())
    clean_time = re.sub(r"(?i)(\d)(AM|PM)$", r"\1 \2", time_part.strip())
    clean_time = clean_time.replace("am", "AM").replace("pm", "PM")
    raw = f"{clean_date} {clean_time}"
    for fmt in ("%a %d%b%y %I:%M %p", "%d%b%y %I:%M %p"):
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _parse_delta_receipt_datetime(
    date_part: str,
    time_part: str,
    received_at: Optional[datetime],
) -> Optional[datetime]:
    if not received_at:
        return None
    clean_date = re.sub(r",", "", date_part.strip().upper())
    clean_time = re.sub(r"(?i)(\d)(AM|PM)$", r"\1 \2", time_part.strip())
    clean_time = clean_time.replace("am", "AM").replace("pm", "PM")
    raw = f"{clean_date}{received_at.year} {clean_time}"
    for fmt in ("%a %d%b%Y %I:%M %p", "%d%b%Y %I:%M %p"):
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


def _parse_compact_dow_day_month_time(
    date_part: str,
    time_part: str,
    received_at: Optional[datetime],
) -> Optional[datetime]:
    if not received_at:
        return None
    clean_date = date_part.strip().upper()
    clean_time = re.sub(r"(?i)(\d)(AM|PM)$", r"\1 \2", time_part.strip())
    clean_time = clean_time.replace("am", "AM").replace("pm", "PM")
    match = re.search(
        r"(?P<dow>MON|TUE|WED|THU|FRI|SAT|SUN)\s+(?P<day>\d{1,2})(?P<month>[A-Z]{3})",
        clean_date,
    )
    if not match:
        return None

    candidates: list[datetime] = []
    for year in (received_at.year, received_at.year - 1, received_at.year + 1):
        raw = f"{match.group('dow')} {match.group('day')}{match.group('month')}{year} {clean_time}"
        for fmt in ("%a %d%b%Y %I:%M %p", "%a %d%b%Y %H:%M"):
            try:
                candidate = datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
            if abs((candidate - received_at).days) <= 370:
                candidates.append(candidate)
    if not candidates:
        return None
    return min(candidates, key=lambda candidate: abs(candidate - received_at))


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
    value = re.sub(r"(\d{1,2})([A-Za-z]{3,5})", r"\1 \2", matches[-1].group(0))
    return _parse_date_time(value, "12:00 AM")


def _nearest_prior_united_compact_date(text: str, pos: int, *, max_lookback: int = 700) -> Optional[datetime]:
    window = text[max(0, pos - max_lookback) : pos]
    matches = list(
        re.finditer(
            r"\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+\d{1,2}"
            r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)"
            r"\s+\d{4}\b",
            window,
            re.IGNORECASE,
        )
    )
    if not matches:
        return None
    value = re.sub(r"(\d{1,2})([A-Za-z]{3,5})", r"\1 \2", matches[-1].group(0))
    return _parse_date_time(value, "12:00 AM")


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


_FORWARD_PRELUDE_RE = re.compile(
    r"""
    (?:
        ^[ \t]*Sent\s+from\s+my\s+\S+[^\n]*\n  # iPhone/Android signature line
        |
        ^[ \t]*Begin\s+forwarded\s+message\s*:?[^\n]*\n
        |
        ^[ \t]*Get\s+Outlook\s+for\s+\S+[^\n]*\n
        |
        ^[ \t]*-{3,}\s*Forwarded\s+message\s*-{3,}[^\n]*\n
        |
        ^[ \t]*-{3,}\s*Original\s+message\s*-{3,}[^\n]*\n
        |
        ^[ \t]*On\s+[^\n]{1,80}\s+wrote\s*:[ \t]*\n
    )
    """,
    re.IGNORECASE | re.VERBOSE | re.MULTILINE,
)

_FORWARD_HEADER_LINE_RE = re.compile(
    r"^[ \t>]*"
    r"(?:From|Sent|To|Cc|Bcc|Date|Subject|Reply-To)\s*:[^\n]*\n",
    re.IGNORECASE | re.MULTILINE,
)


def _unwrap_forwarded(text: str) -> str:
    """Strip forwarded/quoted message header chrome, leaving the inner body intact.

    Forwarded confirmations show up in many shapes — Gmail desktop's
    ``--- Forwarded message ---`` separator, iPhone's ``Begin forwarded
    message:`` block, Outlook's ``From: ... Sent: ... To: ... Subject: ...``
    header stack, and quoted-reply preludes like ``On <date>, <person>
    wrote:``. Each one wraps the actual itinerary body in metadata lines
    that distract the heuristics. We strip the wrapping blocks but keep
    the substantive content below them.
    """
    text = _FORWARD_PRELUDE_RE.sub("\n", text)
    # Collapse any remaining run of leading "From:/Sent:/To:/Subject:" header
    # lines (with optional ``>`` quote prefixes) into a single newline. We
    # cap the loop so a malformed input can't spin.
    for _ in range(8):
        new_text = _FORWARD_HEADER_LINE_RE.sub("", text, count=12)
        if new_text == text:
            break
        text = new_text
    # Strip leading ``> `` quote markers so v5/heuristic regexes can match
    # the underlying itinerary text.
    text = re.sub(r"^[ \t]*>+[ \t]?", "", text, flags=re.MULTILINE)
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
