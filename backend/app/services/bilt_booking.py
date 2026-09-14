"""Narrow evidence that a Bilt notification contains a booked flight itinerary.

This permits parsing, never passenger ownership or active-trip acceptance.
The same sender also sends hotel bookings and newsletters.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from email.utils import parseaddr
from functools import lru_cache

from bs4 import BeautifulSoup

BILT_FLIGHT_SENDER = "notifications@members.bilt.com"
BILT_FLIGHT_SUBJECTS = ("your flight booking is confirmed!", "your flight booking is confirmed")
_REFERENCE = re.compile(r"\bAirline\s+confirmation\s*[:#]?\s*([A-Z0-9]{6})\b", re.I)
_FLIGHT = re.compile(r"(?im)^\s*([A-Z][A-Z0-9]|[0-9][A-Z])\s*(\d{1,4}[A-Z]?)\s*$")
_AIRPORT = re.compile(r"(?m)^\s*([A-Z]{3})\s*$")
_DATE = re.compile(r"\b\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{4}\b", re.I)
_CLOCK = re.compile(r"\b(?:0?[1-9]|1[0-2]):[0-5]\d\s*(?:am|pm)\b", re.I)


@dataclass(frozen=True)
class BiltConfirmationEvidence:
    airport_codes: tuple[str, ...]
    flight_numbers: tuple[str, ...]


@lru_cache(maxsize=1)
def _airport_codes() -> frozenset[str]:
    import airportsdata
    return frozenset(airportsdata.load("IATA"))


def bilt_confirmation_evidence(*, subject: str, sender: str, body: str) -> BiltConfirmationEvidence | None:
    if parseaddr(sender or "")[1].lower() != BILT_FLIGHT_SENDER:
        return None
    if " ".join((subject or "").lower().split()) not in BILT_FLIGHT_SUBJECTS:
        return None
    text = body or ""
    if re.search(r"<(?:html|body|div|table|p|span)\b", text, re.I):
        soup = BeautifulSoup(text[:200_000], "html.parser")
        for node in soup(["script", "style", "head"]):
            node.decompose()
        text = soup.get_text("\n", strip=True)
    text = text[:200_000]
    if not _REFERENCE.search(text) or not re.search(r"\b(?:Outbound|Inbound)\s+Itinerary\b", text, re.I):
        return None
    numbers = tuple(dict.fromkeys(
        a.upper() + n.upper() for a, n in _FLIGHT.findall(text)
        if not re.fullmatch(r"\d+H\d+M", (a + n).upper())
    ))
    if not numbers:
        return None
    airports = tuple(dict.fromkeys(code for code in _AIRPORT.findall(text) if code in _airport_codes()))
    if len(airports) < 2 or len(_CLOCK.findall(text)) < 2:
        return None
    dates = []
    for value in _DATE.findall(text):
        try:
            dates.append(datetime.strptime(value, "%d %b %Y").date())
        except ValueError:
            continue
    if len(dates) < 2:
        return None
    return BiltConfirmationEvidence(airports, numbers)


def is_bilt_flight_confirmation(*, subject: str, sender: str, body: str) -> bool:
    return bilt_confirmation_evidence(subject=subject, sender=sender, body=body) is not None
