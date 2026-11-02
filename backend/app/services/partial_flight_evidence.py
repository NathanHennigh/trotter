"""Preserve explicit facts from incomplete travel records, without making flights.

The initial template is a Philippine eTravel registration. Its journey-country
labels describe the overall journey, not the unknown endpoint of a flight leg.
No identity matching, schedule lookup, database access, or network occurs here.
"""
from __future__ import annotations

import base64
import binascii
from datetime import datetime
from email.utils import getaddresses
import hashlib
import json
import re

from bs4 import BeautifulSoup


EVIDENCE_VERSION = 1
MAX_BODY_CHARS = 500_000
_SENDER = "noreply@mail.etravel.gov.ph"
_FORWARDED = re.compile(r"(?:\b(?:begin\s+)?forwarded message\b|\boriginal message\b|\bOn .{1,150} wrote:|^\s*>)", re.I | re.M)
_AIRPORT_FLIGHT = re.compile(r"(.{5,160}?)\s*-\s*\(([A-Z]{3})\)\s*-\s*([A-Z0-9]{2})\s*(\d{1,4})")


def _authenticated(value: str) -> bool:
    # Use only Gmail's first receiving authentication result. An unrelated
    # passing signature, body text, or later duplicate does not authenticate it.
    if not re.match(r"^\s*mx\.google\.com\s*;", value or "", re.I):
        return False
    clauses = value.lower().split(";")[1:]
    return all(any(re.match(r"\s*" + method + r"=pass\b", clause)
                   and re.search(r"\b" + re.escape(field) + "=" + re.escape(expected) + r"(?=\s|$)", clause)
                   for clause in clauses)
               for method, field, expected in (
                   ("dkim", "header.i", "@etravel.gov.ph"),
                   ("dmarc", "header.from", "etravel.gov.ph")))


def _bodies(payload: dict) -> list[str] | None:
    pending, values, total, visited = [(payload, 0)], [], 0, 0
    while pending:
        part, depth = pending.pop()
        visited += 1
        if depth > 12 or visited > 128 or not isinstance(part, dict):
            return None
        # Attachments cannot introduce a second registration or quoted source.
        if part.get("filename"):
            continue
        mime = part.get("mimeType")
        content = part.get("body") or {}
        if not isinstance(content, dict):
            return None
        data = content.get("data")
        if data and mime in {"text/plain", "text/html"}:
            if not isinstance(data, str) or len(data) > MAX_BODY_CHARS * 2:
                return None
            try:
                raw = base64.b64decode(data + "=" * (-len(data) % 4), altchars=b"-_", validate=True).decode("utf-8")
            except (binascii.Error, ValueError, UnicodeDecodeError):
                return None
            total += len(raw)
            if total > MAX_BODY_CHARS or (mime == "text/plain" and _FORWARDED.search(raw)):
                return None
            if mime == "text/html":
                soup = BeautifulSoup(raw, "html.parser")
                if soup.find("blockquote") or soup.select_one(".gmail_quote, .yahoo_quoted"):
                    return None
                for tag in soup(["head", "script", "style", "noscript"]):
                    tag.decompose()
                for tag in list(soup.find_all(True)):
                    if tag.attrs is not None and (tag.has_attr("hidden")
                            or str(tag.get("aria-hidden", "")).lower() == "true"
                            or re.search(r"display\s*:\s*none|visibility\s*:\s*hidden", str(tag.get("style", "")), re.I)):
                        tag.decompose()
                raw = soup.get_text("\n", strip=True)
            values.append(raw)
        children = part.get("parts") or []
        if not isinstance(children, list) or len(children) > 128:
            return None
        pending.extend((child, depth + 1) for child in children)
    return values


def _facts(body: str) -> dict | None:
    lines = [re.sub(r"\s+", " ", line).strip() for line in body.splitlines() if line.strip()]
    flat = " ".join(lines)
    if ("Kindly present your passport to the Immigration Officer" not in flat
            or "eTravel registration confirmation" not in flat
            or _FORWARDED.search(body)
            or lines.count("Flight Details") != 1 or lines.count("Reference Number") != 1):
        return None
    name_pos, flight_pos = lines.index("Reference Number"), lines.index("Flight Details")
    if name_pos < 1 or flight_pos != name_pos + 2 or len(lines) <= flight_pos + 6:
        return None
    name = lines[name_pos - 1]
    name_words = re.split(r"[\s'’\-]+", name)
    if not 1 <= len(name_words) <= 8 or len(name) > 120 or not all(word.isalpha() for word in name_words):
        return None
    direction = {"ARRIVAL - VIA AIR": "arrival", "DEPARTURE - VIA AIR": "departure"}.get(lines[flight_pos + 1])
    if not direction:
        return None
    printed_date = lines[flight_pos + 2]
    local_day = None
    for fmt in ("%b %d,%Y", "%B %d,%Y"):
        try:
            local_day = datetime.strptime(re.sub(r",\s*", ",", printed_date), fmt).date().isoformat()
            break
        except ValueError:
            pass
    if not local_day:
        return None
    countries = lines[flight_pos + 3].split(" -> ")
    if len(countries) != 2 or any(not re.fullmatch(r"[A-Za-z][A-Za-z ()'’.-]{1,99}", item) for item in countries):
        return None
    known = _AIRPORT_FLIGHT.fullmatch(lines[flight_pos + 4])
    if (not known
            or not re.fullmatch(r"(?:WITH|WITHOUT) BAGGAGE DECLARATION", lines[flight_pos + 5])
            or not re.fullmatch(r"(?:WITH|WITHOUT) CURRENCY DECLARATION", lines[flight_pos + 6])):
        return None
    label, airport, carrier, number = known.groups()
    if carrier.isdigit() or int(number) == 0:
        return None
    opposite = "departure" if direction == "arrival" else "arrival"
    return {
        "traveler_name_as_printed": name,
        "direction": direction,
        "local_date": local_day,
        "local_date_role": direction,
        "flight_number": carrier + number,
        "carrier": carrier,
        "known_airport": {"code": airport, "role": direction, "label": label},
        "journey_countries": {"from": countries[0], "to": countries[1]},
        "journey_countries_are_leg_endpoints": False,
        "missing_fields": [opposite + "_airport", "departure_time", "arrival_time", "verified_passenger_identity"],
    }


def extract_partial_flight_evidence(full_msg: dict) -> dict | None:
    """Return only explicit, authenticated eTravel facts; never a ParsedFlight.

    The caller may retain this under Message.parse_evidence. Authentication
    proves the original sender, not who owns the travel or that travel occurred.
    Registration references, QR tokens, document numbers and other PII are not
    included. Unsupported, conflicting, or malformed sources return None.
    """
    if not isinstance(full_msg, dict) or not isinstance(full_msg.get("payload"), dict):
        return None
    payload = full_msg["payload"]
    raw_headers = payload.get("headers") or []
    if not isinstance(raw_headers, list) or len(raw_headers) > 128:
        return None
    headers = {}
    for row in raw_headers:
        if not isinstance(row, dict) or not isinstance(row.get("name"), str) or not isinstance(row.get("value"), str):
            return None
        key = row["name"].lower()
        if key in {"from", "subject"} and key in headers:
            return None
        headers.setdefault(key, row["value"])
    addresses = getaddresses([headers.get("from", "")])
    if (len(addresses) != 1 or addresses[0][1].lower() != _SENDER
            or headers.get("subject", "").strip() != "Registration Completed"
            or not _authenticated(headers.get("authentication-results", ""))):
        return None
    bodies = _bodies(payload)
    if not bodies:
        return None
    claims = [_facts(body) for body in bodies]
    # Multipart alternatives must state the same facts, without combining fields.
    if any(claim is None for claim in claims) or any(claim != claims[0] for claim in claims[1:]):
        return None
    # Gmail labels/history and local document caches can change without any
    # change to the original evidence. Bind only the original source boundary.
    original = {key: full_msg.get(key) for key in ("id", "payload", "internalDate")}
    fingerprint = hashlib.sha256(json.dumps(original, ensure_ascii=False, sort_keys=True,
                                            separators=(",", ":")).encode()).hexdigest()
    return {
        "version": EVIDENCE_VERSION,
        "kind": "government_travel_registration",
        "provider": "philippines_etravel",
        "source_sha256": fingerprint,
        "authentication": "gmail_aligned_dkim_dmarc",
        "ownership_authority": False,
        "flight_creation_authority": False,
        **claims[0],
    }
