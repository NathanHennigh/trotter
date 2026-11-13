"""Exact single-traveler Southwest ticket exchanges, without locator guessing."""
from __future__ import annotations

from hashlib import sha256
from datetime import datetime
import html
import json
import re

from .ticket_revision_evidence import _named_self, _person, _time

SOURCE = "southwest_named_ticket_exchange"


def _key(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def _ticket_key(number):
    return _key({"version": 1, "carrier": "WN", "ticket": number})


def _matches(pattern, value):
    return isinstance(value,str) and re.fullmatch(pattern,value) is not None


def extract(subject, text, flights):
    """Require one complete printed flight and an exact named ticket manifest.

    A credit transfer alone is not revision authority: the document must also
    explicitly confirm an itinerary change. Multi-person or multi-leg receipts
    remain ordinary retained evidence until their exchange scope is supported.
    """
    if len(flights) != 1:
        return None
    flight = flights[0]
    if getattr(flight, "airline", None) != "WN":
        return None
    if not re.fullmatch(r"WN[1-9]\d{0,3}", str(getattr(flight, "flight_number", "") or "").replace(" ", "").upper()):
        return None
    lines = [re.sub(r"\s+", " ", line).strip() for line in html.unescape(text or "").splitlines() if line.strip()]
    joined = "\n".join(lines)
    if not re.search(r"\bSouthwest\b", joined, re.I):
        return None
    starts = [i for i,line in enumerate(lines) if line.lower() == "your itinerary"]
    ends = [i for i,line in enumerate(lines) if line.lower() == "payment information"]
    if len(starts) != 1 or len(ends) != 1 or starts[0] >= ends[0]:
        return None
    roster, card = lines[:starts[0]], lines[starts[0]+1:ends[0]]
    if sum(line == "PASSENGER" for line in roster) != 1:
        return None
    evidence = getattr(flight, "passenger_evidence", None)
    if not isinstance(evidence,list) or any(not isinstance(row,dict) for row in evidence):
        return None
    names = {_person(row.get("name")) for row in evidence if row.get("role") == "traveler" and row.get("applies") is not False}
    if len(names) != 1 or None in names:
        return None
    person = next(iter(names))
    if not _named_self(flight, person) or sum(_person(line) == person for line in roster) != 1:
        return None
    codes = re.findall(r"(?im)^Confirmation\s*#\s*\n([A-Z0-9]{6})$", joined)
    code = getattr(flight, "pnr", None)
    if not _matches(r"[A-Z0-9]{6}", code) or codes != [code]:
        return None
    issued = re.findall(r"(?m)^526\d{10}$", "\n".join(roster))
    if len(issued) != 1:
        return None
    current = issued[0]
    chain = re.findall(r"(?im)^Credit from ticket:\s*#(526\d{10})\s+to\s+#(526\d{10})$", joined)
    changed = bool(re.search(r"\bWe['’]ve confirmed the change to your trip\.", joined, re.I)
                   and re.search(r"\bupdated itinerary\b", joined, re.I))
    if "credit from ticket" in joined.lower() and (len(chain) != 1 or not changed):
        return None
    if changed and len(chain) != 1:
        return None
    previous = None
    if chain:
        previous, successor = chain[0]
        if successor != current or previous == current:
            return None
    number = str(getattr(flight, "flight_number", "") or "").replace(" ", "").upper()
    number_rows = re.findall(r"(?im)^#\s*0*(\d{1,4})$", "\n".join(card))
    if not re.fullmatch(r"WN[1-9]\d{0,3}", number) or number_rows != [str(int(number[2:]))]:
        return None
    dep, arr = _time(getattr(flight,"dep_time",None)), _time(getattr(flight,"arr_time",None))
    origin, destination = getattr(flight,"dep_airport",None), getattr(flight,"arr_airport",None)
    provenance = getattr(flight,"time_provenance",None)
    if (not dep or not arr or not 0 < (arr-dep).total_seconds() <= 24*3600
            or not _matches(r"[A-Z]{3}",origin) or not _matches(r"[A-Z]{3}",destination)
            or origin == destination or not isinstance(provenance,dict)
            or provenance.get("status") != "normalized"):
        return None
    for field, airport, instant in (("departure",origin,dep),("arrival",destination,arr)):
        proof = provenance.get(field)
        if not isinstance(proof,dict) or proof.get("airport") != airport or _time(proof.get("utc")) != instant:
            return None
    days = re.findall(r"(?im)^(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s+(\d{2})/(\d{2})/(\d{4})$", "\n".join(card))
    if len(days) != 1 or f"{days[0][2]}-{days[0][0]}-{days[0][1]}" != provenance.get("departure_local_date"):
        return None
    local_day = provenance["departure_local_date"]
    for label, field, airport in (("DEPARTS","departure",origin),("ARRIVES","arrival",destination)):
        printed = re.findall(rf"(?im)^{label}\s*\n([A-Z]{{3}})\s+(\d{{1,2}}:\d{{2}})\s*(AM|PM)\s*$", "\n".join(card))
        if len(printed) != 1 or printed[0][0] != airport:
            return None
        try:
            clock = datetime.strptime(printed[0][1]+printed[0][2],"%I:%M%p").strftime("%H:%M:%S")
        except ValueError:
            return None
        if provenance[field].get("local") != f"{local_day}T{clock}":
            return None
    leg = {"dep_airport":origin,"arr_airport":destination,"flight_number":number,
           "dep_time":dep.isoformat(),"arr_time":arr.isoformat()}
    return {"version":1,"source":SOURCE,"document_complete":True,"pnr":code,
        "passenger_name":" ".join(person),"ticket_key":_ticket_key(current),
        "previous_ticket_key":_ticket_key(previous) if previous else None,
        "change_confirmed":changed,"source_card_key":_key({"card":card,"roster":roster}),"legs":[leg]}


def validated(facts):
    if not isinstance(facts,dict) or facts.get("airline") != "WN":
        return None
    ticket = facts.get("booking_ticket")
    if (not isinstance(ticket,dict) or type(ticket.get("version")) is not int or ticket["version"] != 1
            or ticket.get("source") != SOURCE or ticket.get("document_complete") is not True):
        return None
    person = _person(ticket.get("passenger_name"))
    if not person or not _named_self(facts,person) or facts.get("pnr") != ticket.get("pnr"):
        return None
    if not _matches(r"[A-Z0-9]{6}",ticket.get("pnr")):
        return None
    for key in ("ticket_key","source_card_key"):
        if not _matches(r"[0-9a-f]{64}",ticket.get(key)):
            return None
    previous = ticket.get("previous_ticket_key")
    if previous is not None and (not _matches(r"[0-9a-f]{64}",previous)
                                 or previous == ticket["ticket_key"] or ticket.get("change_confirmed") is not True):
        return None
    legs = ticket.get("legs")
    if not isinstance(legs,list) or len(legs) != 1 or not isinstance(legs[0],dict):
        return None
    leg = legs[0]
    dep, arr = _time(leg.get("dep_time")), _time(leg.get("arr_time"))
    if (not dep or not arr or not 0 < (arr-dep).total_seconds() <= 24*3600
            or not _matches(r"WN[1-9]\d{0,3}",leg.get("flight_number"))
            or any(not _matches(r"[A-Z]{3}",leg.get(key)) for key in ("dep_airport","arr_airport"))
            or leg["dep_airport"] == leg["arr_airport"]):
        return None
    if any(facts.get(key) != leg[key] for key in ("dep_airport","arr_airport","flight_number")):
        return None
    if _time(facts.get("dep_time")) != dep or _time(facts.get("arr_time")) != arr:
        return None
    provenance = facts.get("time_provenance")
    if (not isinstance(provenance,dict) or type(provenance.get("version")) is not int
            or provenance["version"] != 1 or provenance.get("status") != "normalized"):
        return None
    for field, airport, instant in (("departure",leg["dep_airport"],dep),("arrival",leg["arr_airport"],arr)):
        proof = provenance.get(field)
        if (not isinstance(proof,dict) or proof.get("airport") != airport
                or _time(proof.get("utc")) != instant or not isinstance(proof.get("local"),str)):
            return None
    if (not isinstance(provenance.get("departure_local_date"),str)
            or provenance["departure"]["local"][:10] != provenance["departure_local_date"]):
        return None
    return ticket, person, dep


def supersedes(previous_facts, successor_facts, *, previous_event_at, successor_event_at):
    old, new = validated(previous_facts), validated(successor_facts)
    earlier, later = _time(previous_event_at), _time(successor_event_at)
    if not old or not new or not earlier or not later:
        return False
    old_ticket, old_person, old_departure = old
    new_ticket, new_person, new_departure = new
    return bool(old_person == new_person and old_ticket["pnr"] == new_ticket["pnr"]
        and old_ticket["ticket_key"] == new_ticket.get("previous_ticket_key")
        and earlier < later < min(old_departure,new_departure))
