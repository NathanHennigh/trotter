"""Exact, named issued-ticket replacement evidence; no route similarity inference."""
from __future__ import annotations

from datetime import datetime, timezone
import html
import re

from .booking_references import extract_primary_reference
from .passenger_identity import _name, _ordered_name_tokens


_SOURCE = "alaska_named_airfare_ticket"
_TICKET = re.compile(r"Ticket\s+(\d{13})(?:\s*\(\s*Previous\s+Ticket\s+(\d{13})\s*\))?", re.I)
_LOYALTY = re.compile(r"Atmos(?:™)?\s+Rewards\s+Member:\s*#\d+", re.I)


def _person(value):
    if not isinstance(value, str) or not _name(value):
        return None
    tokens = _ordered_name_tokens(value)
    # Ticket replacement must not use initial, prefix, or omitted-middle matching.
    return tuple(tokens) if len(tokens) >= 2 and all(token.isalpha() and len(token) > 1 for token in tokens) else None


def _time(value):
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _leg(flight):
    dep, arr = _time(getattr(flight, "dep_time", None)), _time(getattr(flight, "arr_time", None))
    origin, destination = getattr(flight, "dep_airport", None), getattr(flight, "arr_airport", None)
    number = str(getattr(flight, "flight_number", None) or "").replace(" ", "").upper()
    if (not dep or not arr or arr <= dep or not re.fullmatch(r"AS\d{1,4}", number)
            or not re.fullmatch(r"[A-Z]{3}", origin or "") or not re.fullmatch(r"[A-Z]{3}", destination or "")
            or origin == destination):
        return None
    return {"dep_airport":origin, "arr_airport":destination, "flight_number":number,
            "dep_time":dep.isoformat(), "arr_time":arr.isoformat()}


def _named_self(flight, passenger):
    get = flight.get if isinstance(flight, dict) else lambda key, default=None: getattr(flight,key,default)
    if get("ownership") != "self" or get("force_review", False):
        return False
    raw_evidence = get("passenger_evidence")
    if not isinstance(raw_evidence,list) or any(not isinstance(item,dict) for item in raw_evidence):
        return False
    evidence = [item for item in raw_evidence
                if item.get("role") == "traveler" and item.get("applies") is not False]
    return bool(evidence) and all(item.get("complete") is True and not item.get("scope_ambiguous")
                                  and _person(item.get("name")) == passenger for item in evidence)


def extract_ticket_revision(subject: str, text: str, flights: list) -> dict | None:
    """Read one complete Alaska named airfare card, including an older plain ticket.

    A successor requires the literal Previous Ticket field. The original receipt
    is also retained so reconciliation can require an exact old-ticket chain.
    Multi-person/card/booking or partial documents deliberately return no authority.
    """
    lines = [re.sub(r"\s+", " ", line).strip() for line in html.unescape(text or "").splitlines() if line.strip()]
    joined = "\n".join(lines)
    if not flights or not re.search(r"\balaska\b", joined, re.I) or not re.search(r"\bTrip details\b", joined, re.I):
        return None
    references = {getattr(flight,"pnr",None) for flight in flights}
    if len(references) != 1:
        return None
    pnr = next(iter(references))
    if not isinstance(pnr,str) or extract_primary_reference("Confirmation code: " + pnr) != pnr:
        return None
    from .booking_references import extract_reference_fields
    if {field.code for field in extract_reference_fields(joined)} != {pnr}:
        return None
    headings = [int(value) for value in re.findall(r"(?im)^Flight\s+(\d+)\s*[.·]\s*", joined)]
    legs = [_leg(flight) for flight in flights]
    if (any(leg is None for leg in legs) or not headings or sorted(headings) != list(range(1,len(headings)+1))
            or len(headings) != len(legs) or len({tuple(sorted(leg.items())) for leg in legs}) != len(legs)):
        return None
    starts = [i for i,line in enumerate(lines) if re.fullmatch(r"Summary of airfare charges",line,re.I)]
    if len(starts) != 1:
        return None
    card = lines[starts[0]+1:starts[0]+81]
    ends = [i for i,line in enumerate(card) if re.fullmatch(r"Total charges for air travel",line,re.I)]
    if not ends:
        return None
    card = card[:ends[0]]
    if not card or not re.fullmatch(r"Fare breakdown\s*Air travel charges",card[0],re.I):
        return None
    ticket_rows = [(i,_TICKET.fullmatch(line)) for i,line in enumerate(card) if re.match(r"Ticket\b",line,re.I)]
    if len(ticket_rows) != 1 or not ticket_rows[0][1]:
        return None
    at, match = ticket_rows[0]
    before = at-2 if at and _LOYALTY.fullmatch(card[at-1]) else at-1
    if before != 1:  # Card header, exact passenger, optional loyalty row, then ticket.
        return None
    name = card[before]
    person = _person(name)
    if not person or not all(_named_self(flight,person) for flight in flights):
        return None
    current, previous = match.groups()
    if not current.startswith("027") or (previous and (previous == current or not previous.startswith("027"))):
        return None
    return {"version":1, "source":_SOURCE, "ticket_number":current, "previous_ticket_number":previous,
            "pnr":pnr, "passenger_name":name, "document_complete":True, "legs":legs}


def _validated(facts):
    if not isinstance(facts,dict):
        return None
    ticket = facts.get("booking_ticket")
    if not isinstance(ticket,dict) or ticket.get("version") != 1 or ticket.get("source") != _SOURCE or ticket.get("document_complete") is not True:
        return None
    person = _person(ticket.get("passenger_name"))
    if not person or not _named_self(facts,person) or facts.get("pnr") != ticket.get("pnr"):
        return None
    number = ticket.get("ticket_number")
    previous = ticket.get("previous_ticket_number")
    if not isinstance(number,str) or not re.fullmatch(r"027\d{10}",number):
        return None
    if previous is not None and (not isinstance(previous,str) or not re.fullmatch(r"027\d{10}",previous) or previous == number):
        return None
    pnr = ticket.get("pnr")
    if not isinstance(pnr,str) or extract_primary_reference("Confirmation code: " + pnr) != pnr:
        return None
    legs = ticket.get("legs")
    if not isinstance(legs,list) or not legs:
        return None
    keys, departures = set(), []
    for leg in legs:
        if not isinstance(leg,dict):
            return None
        if any(not isinstance(leg.get(key),str) for key in ('flight_number','dep_airport','arr_airport')):
            return None
        dep, arr = _time(leg.get("dep_time")), _time(leg.get("arr_time"))
        if (not dep or not arr or arr <= dep or not re.fullmatch(r"AS\d{1,4}",leg.get("flight_number") or "")
                or not re.fullmatch(r"[A-Z]{3}",leg.get("dep_airport") or "")
                or not re.fullmatch(r"[A-Z]{3}",leg.get("arr_airport") or "")
                or leg.get("dep_airport") == leg.get("arr_airport")):
            return None
        key = (leg['dep_airport'],leg['arr_airport'],leg['flight_number'],dep,arr)
        if key in keys:
            return None
        keys.add(key)
        departures.append(dep)
    own = (facts.get('dep_airport'),facts.get('arr_airport'),facts.get('flight_number'),
           _time(facts.get('dep_time')),_time(facts.get('arr_time')))
    if own not in keys:
        return None
    return ticket, person, min(departures)


def ticket_supersedes(previous_facts: dict, successor_facts: dict, *, previous_event_at, successor_event_at) -> bool:
    """Authorize only explicit same-person/booking ticket exchange before travel.

    Callers must additionally scope both observations to the same account and
    preserve manual/unrelated projections. Ingestion order is not event order.
    """
    from .southwest_ticket_revision import SOURCE, supersedes as southwest_supersedes
    if (isinstance(previous_facts,dict) and isinstance(previous_facts.get("booking_ticket"),dict)
            and previous_facts["booking_ticket"].get("source") == SOURCE):
        return southwest_supersedes(previous_facts, successor_facts,
            previous_event_at=previous_event_at, successor_event_at=successor_event_at)
    old, new = _validated(previous_facts), _validated(successor_facts)
    earlier, later = _time(previous_event_at), _time(successor_event_at)
    if not old or not new or not earlier or not later:
        return False
    old_ticket, old_person, old_departure = old
    new_ticket, new_person, new_departure = new
    return bool(old_person == new_person and old_ticket['pnr'] == new_ticket['pnr']
                and old_ticket['ticket_number'] == new_ticket.get('previous_ticket_number')
                and old_ticket['ticket_number'] != new_ticket['ticket_number']
                and earlier < later < min(old_departure,new_departure))
