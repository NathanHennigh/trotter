"""Extract narrow, typed carrier statements without deciding flight ownership.

An addressed notice, loyalty account, or survey alone is not passenger proof.
These facts can support a separately bounded corroboration policy. Operational
dates/routes/times must still come from the existing flight parser; city labels
are preserved rather than guessed into airports. No network or model calls.

Authentication-Results must be the trusted Gmail-added header, not a header
copied out of a forwarded body. The caller binds source/user/hash/revision.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import getaddresses
from typing import Any

from bs4 import BeautifulSoup


EVIDENCE_VERSION = 1
MAX_BODY_CHARS = 500_000
MAX_SURVEY_AGE_DAYS = 21
_TEMPLATES = {
    "americanairlines@survey.na.aa.com": ("AA", "survey", "aa.com"),
    "no-reply@info.email.aa.com": ("AA", "operational", "aa.com"),
    "suncountryairlines@express.sea1.medallia.com": ("SY", "survey", "express.sea1.medallia.com"),
    "suncountry@info.suncountry.com": ("SY", "operational", "info.suncountry.com"),
}
_DATE = r"(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4}"
_SURVEY_SUBJECT = re.compile(r"^(.{1,80}?),\s*how was your flight\?(?:\s*-\s*We still want to hear from you)?$", re.I)
_FORWARDED = re.compile(r"(?:\b(?:begin\s+)?forwarded message\b|\boriginal message\b|\bOn .{1,150} wrote:|^\s*>)", re.I | re.M)
_PNR = re.compile(r"\b(?:Confirmation|Reservation)\s+code\s*:\s*([A-Z0-9]{6})\b", re.I)
_GREETING = re.compile(r"\b(?:Hi|Dear)\s+([^,\n]{1,80}),", re.I)
_AA_CLAIM = re.compile(r"\bOur records show that you flew from ([A-Z]{3}) to ([A-Z]{3}) on (" + _DATE + r")\.", re.I)
_SY_CLAIM = re.compile(
    r"\b(?:Thank you for flying with Sun Country Airlines|We recently sent you a brief survey about your flight)"
    r" from (.{2,100}?) to (.{2,100}?) on (" + _DATE + r")\.", re.I,
)
_AA_NOTICE_SUBJECT = re.compile(
    r"^Your flight to .{2,80}?\s*-\s*(?:[A-Z0-9]{6}|Departure Gate Change|Departure Time Change|Arrival Gate Change|Flight Delayed|Flight Delay)$",
    re.I,
)


@dataclass(frozen=True)
class CarrierEvidence:
    kind: str
    carrier: str
    name: str | None = None
    local_day: str | None = None
    dep_airport: str | None = None
    arr_airport: str | None = None
    pnr: str | None = None
    departure_label: str | None = None
    arrival_label: str | None = None
    facts: dict[str, Any] = field(default_factory=dict)


def _address(value: str) -> str | None:
    addresses = getaddresses([value or ""])
    if len(addresses) != 1 or not re.fullmatch(r"[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+", addresses[0][1]):
        return None
    return addresses[0][1].lower()


def _authenticated(header: str, sender: str, dmarc_domain: str) -> bool:
    # Matching a provider's name inside SPF comments or an unrelated passing
    # signature is insufficient. Both aligned DKIM and DMARC must pass.
    if not re.match(r"^\s*mx\.google\.com\s*;", header or "", re.I):
        return False
    clauses = (header or "").lower().split(";")[1:]
    domain = sender.rsplit("@", 1)[1]
    def passed(kind: str, key: str, expected: str) -> bool:
        return any(re.match(r"\s*" + kind + r"=pass\b", clause)
                   and re.search(r"\b" + re.escape(key) + r"=" + re.escape(expected) + r"(?=\s|$)", clause)
                   for clause in clauses)
    return passed("dkim", "header.i", "@" + domain) and passed("dmarc", "header.from", dmarc_domain)


def _name(raw: str) -> str | None:
    value = re.sub(r"\s+", " ", raw).strip()
    value = re.sub(r"\s+(?:Mr|Mrs|Ms|Miss|Dr)\.?$", "", value, flags=re.I)
    tokens = value.replace("-", " ").replace("'", " ").replace("’", " ").split()
    if not 1 <= len(tokens) <= 6 or not all(token.isalpha() for token in tokens):
        return None
    return value


def _normalized_body(text: str, html: str) -> str | None:
    if len(text) + len(html) > MAX_BODY_CHARS or _FORWARDED.search(text or ""):
        return None
    if html:
        soup = BeautifulSoup(html, "html.parser")
        if soup.find("blockquote") or soup.select_one(".gmail_quote, .yahoo_quoted"):
            return None
        for tag in soup(["script", "style", "head", "noscript"]):
            tag.decompose()
        for tag in list(soup.find_all(True)):
            if tag.attrs is None:
                continue
            if re.search(r"display\s*:\s*none|visibility\s*:\s*hidden", str(tag.get("style", "")), re.I) or str(tag.get("aria-hidden", "")).lower() == "true":
                tag.decompose()
        text += "\n" + soup.get_text("\n", strip=True)
    if _FORWARDED.search(text):
        return None
    return re.sub(r"\s+", " ", text).strip()


def _survey_day(value: str, received_at: datetime | None) -> str | None:
    try:
        day = datetime.strptime(re.sub(r"\s+", " ", value).title(), "%B %d, %Y").date()
    except ValueError:
        return None
    # Missing receipt metadata cannot establish a post-travel assertion.
    if received_at is None:
        return None
    received_day = (received_at.astimezone(timezone.utc) if received_at.tzinfo else received_at).date()
    if not 0 <= (received_day - day).days <= MAX_SURVEY_AGE_DAYS:
        return None
    return day.isoformat()


def _evidence(kind: str, carrier: str, sender: str, **values: Any) -> CarrierEvidence:
    facts = values.pop("facts", {})
    facts.update({"authenticated_sender": sender, "authentication": "gmail_aligned_dkim_dmarc",
                  "evidence_version": EVIDENCE_VERSION, "ownership_authority": False})
    # A reminder and its first invitation describe one claim, not two votes.
    identity = {"kind": kind, "carrier": carrier, **values}
    facts["claim_key"] = hashlib.sha256(json.dumps(identity, sort_keys=True).lower().encode()).hexdigest()
    return CarrierEvidence(kind=kind, carrier=carrier, facts=facts, **values)


def may_have_carrier_travel_evidence(subject: str, sender: str) -> bool:
    """Cheap candidate screen only, not authentication or ownership approval."""
    template = _TEMPLATES.get(_address(sender) or "")
    if not template or re.match(r"^\s*(?:re|fw|fwd)\s*:", subject or "", re.I):
        return False
    subject = re.sub(r"\s+", " ", subject or "").strip()
    carrier, category, _ = template
    if category == "survey":
        return bool(_SURVEY_SUBJECT.fullmatch(subject))
    if carrier == "AA":
        return bool(re.fullmatch(r"It's time to check in\s*-\s*[A-Z0-9]{6}", subject, re.I)
                    or re.fullmatch(r"Your connecting flight to .{2,80}", subject, re.I)
                    or _AA_NOTICE_SUBJECT.fullmatch(subject))
    return bool(re.fullmatch(r"An important message regarding flight SY\s*\d{1,4}", subject, re.I))


def extract_carrier_travel_evidence(
    *, subject: str, sender: str, recipient: str, text: str, html: str,
    received_at: datetime | None = None, authentication_results: str = "",
) -> tuple[CarrierEvidence, ...]:
    """Return corroborating facts only; never create flights or infer ownership."""
    if not may_have_carrier_travel_evidence(subject, sender):
        return ()
    address = _address(sender)
    template = _TEMPLATES.get(address or "")
    if not template or not _address(recipient) or re.match(r"^\s*(?:re|fw|fwd)\s*:", subject, re.I):
        return ()
    carrier, category, dmarc_domain = template
    if not _authenticated(authentication_results, address, dmarc_domain):
        return ()
    subject = re.sub(r"\s+", " ", subject).strip()
    survey = _SURVEY_SUBJECT.fullmatch(subject) if category == "survey" else None
    checkin = carrier == "AA" and category == "operational" and bool(re.fullmatch(r"It's time to check in\s*-\s*[A-Z0-9]{6}", subject, re.I))
    connecting = carrier == "AA" and category == "operational" and bool(re.fullmatch(r"Your connecting flight to .{2,80}", subject, re.I))
    notice = carrier == "AA" and category == "operational" and bool(_AA_NOTICE_SUBJECT.fullmatch(subject))
    disruption = carrier == "SY" and category == "operational" and bool(re.fullmatch(r"An important message regarding flight SY\s*\d{1,4}", subject, re.I))
    # Most mail exits before HTML parsing, including promotions and receipts.
    if not any((survey, checkin, connecting, disruption, notice)):
        return ()
    body = _normalized_body(text or "", html or "")
    if not body:
        return ()
    greetings = {_name(m.group(1)) for m in _GREETING.finditer(body)}
    if None in greetings or len(greetings) > 1:
        return ()

    if survey:
        name = _name(survey.group(1))
        if not name or (greetings and any(n.casefold() != name.casefold() for n in greetings)):
            return ()
        claim_re = _AA_CLAIM if carrier == "AA" else _SY_CLAIM
        claims = {tuple(re.sub(r"\s+", " ", value).strip() for value in m.groups()) for m in claim_re.finditer(body)}
        if len(claims) != 1:
            return ()
        dep, arr, date_text = next(iter(claims))
        day = _survey_day(date_text, received_at)
        if not day or dep.casefold() == arr.casefold():
            return ()
        endpoints = {"dep_airport": dep.upper(), "arr_airport": arr.upper()} if carrier == "AA" else {"departure_label": dep, "arrival_label": arr}
        return (_evidence("post_travel", carrier, address, name=name, local_day=day, **endpoints,
            facts={"assertion": "carrier_reports_completed_travel", "name_form": "subject_name",
                   "route_scope": "journey", "received_date_verified": True}),)

    pnrs = {m.group(1).upper() for m in _PNR.finditer(body)}
    if len(pnrs) != 1:
        return ()
    pnr = next(iter(pnrs))
    if checkin and subject.rsplit("-", 1)[-1].strip().upper() != pnr:
        return ()
    if notice:
        suffix = subject.rsplit("-", 1)[-1].strip().upper()
        if re.fullmatch(r"[A-Z0-9]{6}", suffix) and suffix != pnr:
            return ()
        if not re.search(r"\b(?:Your flight to|Flight\s+\d{1,4}\s+to\s+[A-Z]{3})\b", body, re.I):
            return ()
        return (_evidence("operational_notice", carrier, address, pnr=pnr,
            facts={"assertion": "booking_operational_notice"}),)
    if connecting:
        destinations = {m.group(1).upper() for m in re.finditer(r"\bYour connecting flight to ([A-Z]{3})\b", body)}
        if len(destinations) != 1:
            return ()
        return (_evidence("connecting_notice", carrier, address, pnr=pnr,
            arr_airport=next(iter(destinations)),
            facts={"assertion": "explicit_connecting_notice", "explicit_connection": True}),)
    if checkin and not re.search(r"\bYour trip is almost here and we're excited to see you on board\.", body, re.I):
        return ()
    if disruption and not re.search(r"\bOne or more of your flights has been affected by a schedule change\.", body, re.I):
        return ()
    if not greetings:
        return (_evidence("operational_notice", carrier, address, pnr=pnr,
            facts={"assertion": "booking_operational_notice"}),)
    name = next(iter(greetings))
    if len(name.split()) < 2:
        return ()
    return (_evidence("operational_personal", carrier, address, name=name, pnr=pnr,
        facts={"assertion": "personally_addressed_checkin" if checkin else "personally_addressed_disruption",
               "name_form": "given_sequence" if checkin else "full_salutation"}),)
