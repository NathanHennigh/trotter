"""Retain explicitly labeled incomplete airline facts, without making flights.

No geocoding, schedule lookup, name inference, or cross-message joins. Incomplete
facts are not booking observations and cannot acquire import authority merely
because a traveler name or another carrier message later matches.
"""
from __future__ import annotations

from datetime import datetime
from email.utils import getaddresses
import hashlib
import json
import re

VERSION = 1
DATE = r"(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4}"


def _date(value):
    try:
        return datetime.strptime(value, "%B %d, %Y").date().isoformat()
    except ValueError:
        return None


def _claims(text, domain):
    from .flight_evidence import _valid_iata
    flat = " ".join(text.split())
    if domain == "united.com" or domain.endswith(".united.com"):
        pattern = re.compile(r"\bFlight\s*:\s*(UA\s*\d{1,4})\s+Date\s*:\s*(" + DATE + r")\s+From\s*:\s*"
            r"[^():]{2,80}\(\s*([A-Z]{3})\s*\)\s+To\s*:\s*[^():]{2,80}\(\s*([A-Z]{3})\s*\)", re.I)
        legs = []
        for m in pattern.finditer(flat):
            number, day, dep, arr = m.groups()
            if _date(day) and _valid_iata(dep.upper()) and _valid_iata(arr.upper()) and dep.upper() != arr.upper():
                leg = {"flight_number": number.upper().replace(" ", ""), "dep_airport": dep.upper(),
                    "arr_airport": arr.upper(), "departure_local_date": _date(day),
                    "missing_fields": ["departure_time", "arrival_time", "verified_passenger_identity"]}
                if leg not in legs:
                    legs.append(leg)
        return {"carrier": "UA", "legs": legs} if legs else None
    if domain != "suncountry.com" and not domain.endswith(".suncountry.com"):
        return None
    # Only the Trip Details section owns itinerary bounds. Policy dates, bag
    # prices and airport advice farther down the email cannot supply leg facts.
    section = re.search(r"\bTrip Details\b(.{1,1800}?)\bTraveler Details\b", flat, re.I)
    if not section:
        return None
    numbers = re.search(r"\b(SY\d{1,4})\s*,\s*(SY\d{1,4})\s+STOPS\s+1\s*\(([A-Z]{3})\)", section[1])
    endpoints = list(re.finditer(r"\b(\d{1,2}:\d{2}\s*[AP]M)\s+[^()]{2,80}\(([A-Z]{3})\)\s+(" + DATE + r")", section[1], re.I))
    if not numbers or len(endpoints) != 2:
        return None
    first, last = endpoints
    dep, via, arr = first[2], numbers[3], last[2]
    if len({dep, via, arr}) != 3 or not all(_valid_iata(code) for code in (dep, via, arr)):
        return None
    try:
        start = datetime.strptime(first[3] + " " + first[1].replace(" ", ""), "%B %d, %Y %I:%M%p")
        end = datetime.strptime(last[3] + " " + last[1].replace(" ", ""), "%B %d, %Y %I:%M%p")
    except ValueError:
        return None
    if not 0 <= (end.date() - start.date()).days <= 2:
        return None
    return {"carrier": "SY", "legs": [
        {"flight_number": numbers[1], "dep_airport": dep, "arr_airport": via,
         "departure_local_date": start.date().isoformat(), "departure_local_time": start.strftime("%H:%M"),
         "missing_fields": ["arrival_time", "verified_passenger_identity"]},
        {"flight_number": numbers[2], "dep_airport": via, "arr_airport": arr,
         "arrival_local_date": end.date().isoformat(), "arrival_local_time": end.strftime("%H:%M"),
         "missing_fields": ["departure_time", "verified_passenger_identity"]}],
        "itinerary_bounds_are_leg_schedules": False}


def extract_partial_airline_evidence(message):
    from .partial_flight_evidence import _bodies, _FORWARDED
    payload = message.get("payload")
    if not isinstance(payload, dict):
        return None
    headers = payload.get("headers", [])
    if not isinstance(headers, list) or len(headers) > 128:
        return None
    senders = [row.get("value", "") for row in headers if isinstance(row, dict) and str(row.get("name", "")).lower() == "from"]
    if len(senders) != 1 or not isinstance(senders[0], str):
        return None
    addresses = getaddresses(senders)
    if len(addresses) != 1 or "@" not in addresses[0][1]:
        return None
    domain = addresses[0][1].rsplit("@", 1)[1].lower()
    # These are exactly the domains supported by _claims. Reject other mail
    # before MIME decoding/HTML parsing; the caller still checks eTravel itself.
    if not (domain == "united.com" or domain.endswith(".united.com")
            or domain == "suncountry.com" or domain.endswith(".suncountry.com")):
        return None
    bodies = _bodies(payload)
    if not bodies or any(_FORWARDED.search(body) for body in bodies):
        return None
    claims = [value for body in bodies if (value := _claims(body, domain))]
    if not claims or any(value != claims[0] for value in claims[1:]):
        return None
    original = {key: message.get(key) for key in ("id", "payload", "internalDate")}
    return {"version": VERSION, "kind": "airline_partial_itinerary", "provider": "labeled_airline_facts",
        "source_sha256": hashlib.sha256(json.dumps(original, sort_keys=True, ensure_ascii=False,
            separators=(",", ":")).encode()).hexdigest(),
        "ownership_authority": False, "flight_creation_authority": False,
        "authentication": "sender_label_only_not_identity_authority",
        "missing_fields": sorted({field for leg in claims[0]["legs"] for field in leg["missing_fields"]}),
        **claims[0]}
