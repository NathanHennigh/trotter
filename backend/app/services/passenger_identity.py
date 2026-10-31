"""Traveler evidence and conservative ownership, independent of route extraction.

Inbox recipients, greetings, billing contacts and forwarding headers are not
traveler evidence. Unscoped names in a message with multiple bookings remain
available for review, but do not establish ownership of any individual flight.
"""

from __future__ import annotations

import json
import re
import unicodedata
from typing import Any

from bs4 import BeautifulSoup


_TITLE = {"mr", "mrs", "ms", "miss", "dr", "prof", "mstr", "madame", "mme", "monsieur", "mlle"}
_SUFFIX = {"jr", "sr", "ii", "iii", "iv"}
_NON_NAME = set(
    "passenger passengers traveler travelers traveller travellers name names first last "
    "flight flights information details ticket tickets seat seats adult adults child children infant "
    "economy business cabin fare total paid payment card credit loyalty booked booking number "
    "departure arrival date meals baggage terminal receipt email phone contact address reservation "
    "status confirmed airline miles points boarding confirmation record locator itinerary customer "
    "support taxes amount service document document(s) your complete return departing arriving "
    "facility charge security fee fees rights notices disabilities who subtotal bundle bundles bags services none na".split()
)
_LABEL = re.compile(
    r"^\s*(?:passenger(?:\(s\)|s)?|travel(?:l?er)(?:\(s\)|s)?|guests?)"
    r"(?:\s+(?:name(?:\(s\)|s)?|information|details))?"
    r"(?:\s*[#(]?\s*(?P<count>\d+)\s*\)?)?\s*(?::|\||\s|$)\s*(?P<value>.*)$",
    re.I,
)
_PNR = re.compile(
    r"\b(?:confirmation(?:\s+(?:code|number))?|booking(?:\s+(?:reference|code|number))?|"
    r"reservation(?:\s+(?:code|number))?|record\s+locator|pnr)\s*[:#-]?\s*([A-Z0-9]{5,8})\b(?![-_/][A-Z0-9])",
    re.I,
)
_BOUNDARY = re.compile(
    r"^(?:from|to|sent|date|subject|dear|hello|hi|payment|billing|paid|buyer|purchaser|"
    r"contact|confirmation|booking|reservation|record|pnr|flight|depart|arriv|itinerary|"
    r"ticket|seat|baggage|fare|total|price|cost|tax|amount|your|thank|check|loyalty|"
    r"frequent|member|manage|outbound|inbound|return|receipt|bags|bundles|services)\b", re.I,
)


def _tokens(value: str) -> list[str]:
    value = unicodedata.normalize("NFKD", value).casefold()
    value = "".join(c for c in value if not unicodedata.combining(c))
    value = value.replace("'", "").replace("’", "")
    value = re.sub(r"[^\w\s]", " ", value, flags=re.UNICODE)
    return [part for part in value.split() if part not in _TITLE]


def names_match(passenger: str, candidate: str) -> bool:
    """Match full names, reordered names, or a compatible given-name initial.

    A first name or surname alone never matches a longer account name. Explicit
    conflicting middle names and generational suffixes are not discarded.
    """
    a, b = _tokens(passenger), _tokens(candidate)
    if not a or not b or "@" in candidate or "@" in passenger:
        return False
    # Airlines often print FAMILY/GIVENMIDDLE. Only exact concatenation of
    # explicitly supplied names is safe: ELISHA must not match ELISHABETH.
    for printed, full in ((passenger, b), (candidate, a)):
        if len(re.findall(r"[/,]", printed)) == 1 and len(full) >= 2:
            family, given = re.split(r"[/,]", printed)
            if (_tokens(family) == [full[-1]] and full[-1] not in _SUFFIX
                    and "".join(_tokens(given)) == "".join(full[:-1])):
                return True
    if len(a) < 2 or len(b) < 2:
        return a == b and len(a) == len(b)
    if sorted(a) == sorted(b):
        return True
    a_suffix = a[-1] if a[-1] in _SUFFIX else None
    b_suffix = b[-1] if b[-1] in _SUFFIX else None
    if a_suffix != b_suffix:
        return False
    if a_suffix:
        a, b = a[:-1], b[:-1]

    def compatible(x: str, y: str) -> bool:
        return x == y or (min(len(x), len(y)) == 1 and x[0] == y[0])

    # LAST/FIRST and LAST, FIRST occur in ticket receipts.
    for left in (a, a[1:] + a[:1]):
        for right in (b, b[1:] + b[:1]):
            if len(left[-1]) < 2 or left[-1] != right[-1]:
                continue
            if not compatible(left[0], right[0]):
                continue
            lm, rm = left[1:-1], right[1:-1]
            if lm and rm and (len(lm) != len(rm) or not all(compatible(x, y) for x, y in zip(lm, rm))):
                continue
            return True
    return False


def full_names_match(passenger: str, candidate: str) -> bool:
    """Ownership recovery requires full given and family names, never initials."""
    return (isinstance(passenger, str) and isinstance(candidate, str)
            and all(len(parts) >= 2 and all(len(token) > 1 and token.isalpha() for token in parts)
                    for parts in (_tokens(passenger), _tokens(candidate)))
            and names_match(passenger, candidate))


def _ambiguous_compact_given_name(passenger: str, candidate: str) -> bool:
    """A fused middle name is not proof that this is a different traveler.

    This deliberately does not establish a match: ALEXANDRA may be a different
    given name, while ALEXJORDAN may be the account holder with a middle name.
    Only explicit aliases or independent booking evidence can resolve that.
    """
    def parts(value: str):
        if len(re.findall(r"[/,]", value)) == 1:
            family, given = re.split(r"[/,]", value)
            family_tokens, given_tokens = _tokens(family), _tokens(given)
        else:
            tokens = _tokens(value)
            family_tokens, given_tokens = tokens[-1:], tokens[:-1]
        if (len(family_tokens) != 1 or not given_tokens
                or family_tokens[0] in _SUFFIX
                or any(len(token) < 2 or not token.isalpha() or token in _SUFFIX
                       for token in [*family_tokens, *given_tokens])):
            return None
        return family_tokens[0], "".join(given_tokens), len(given_tokens)

    left, right = parts(passenger), parts(candidate)
    if not left or not right or left[0] != right[0]:
        return False
    # At least one side must actually be fused; conflicting separately printed
    # middle names retain their existing, explicit non-match behavior.
    return (left[1] != right[1] and min(left[2], right[2]) == 1
            and (left[1].startswith(right[1]) or right[1].startswith(left[1])))


def _name(value: str) -> str | None:
    value = re.sub(r"^\s*\d+\s*[.)-]?\s+", "", value).strip(" \t:*|-")
    value = re.sub(r"\s+Not\s+a\s+.{0,80}?Member\b.*$", "", value, flags=re.I)
    value = re.sub(r"\s*\((?:adult|child|infant|adt|chd|inf)\)\s*", " ", value, flags=re.I)
    value = re.sub(r"\s+", " ", value).strip()
    parts = _tokens(value)
    if not parts or len(parts) > 8 or len(value) > 100:
        return None
    if any(p in _NON_NAME or not p.isalpha() for p in parts):
        return None
    if any(c in value for c in "@<>:="):
        return None
    if re.fullmatch(r"[A-Z]{3}(?:\s+to\s+|\s*[-–→]\s*)[A-Z]{3}", value, re.I):
        return None
    if re.fullmatch(r"purchase\s+summary", value, re.I):
        return None
    return value


def _names(value: str) -> list[str]:
    # Preserve side-by-side traveler columns; non-name seat/ticket cells fail
    # validation, so they cannot become an account identity.
    pieces = re.split(r"\s*(?:\||;|\s+and\s+|\s+&\s+)\s*", value, flags=re.I)
    if len(pieces) == 1 and "," in value:
        commas = value.split(",")
        if all(len(_tokens(part)) >= 2 for part in commas):
            pieces = commas
    return [name for part in pieces if (name := _name(part))]


def _person_names(value: Any) -> list[str]:
    if isinstance(value, list):
        return [name for item in value for name in _person_names(item)]
    if isinstance(value, dict):
        value = value.get("name") or " ".join(str(value.get(key) or "") for key in ("givenName", "familyName"))
    if not isinstance(value, str):
        return []
    name = _name(value)
    return [name] if name else []


def jsonld_passenger_evidence(item: dict) -> list[dict]:
    """Read reservation beneficiaries; deliberately ignore customer/booker/payer."""
    raw = item.get("underName")
    names = _person_names(raw)
    expected = len(raw) if isinstance(raw, list) else 1
    flight = item.get("reservationFor") or {}
    if not isinstance(flight, dict):
        flight = {}
    airline = flight.get("airline") or {}
    airline_code = airline.get("iataCode", "") if isinstance(airline, dict) else ""
    number = str(flight.get("flightNumber") or "").upper().replace(" ", "")
    if number and airline_code and not number.startswith(airline_code.upper()):
        number = airline_code.upper() + number
    scope = {
        "pnr": str(item.get("reservationNumber") or "").upper().strip(),
        "flight_number": number,
        "dep_airport": (flight.get("departureAirport") or {}).get("iataCode"),
        "arr_airport": (flight.get("arrivalAirport") or {}).get("iataCode"),
        "departure_date": str(flight.get("departureTime") or "")[:10],
    }
    return [dict(name=name, source="jsonld_underName", role="traveler", complete=len(names) == expected,
                 scope={key: value for key, value in scope.items() if value}) for name in names]


def _jsonld_evidence(html: str) -> list[dict]:
    evidence: list[dict] = []

    def visit(item: Any) -> None:
        if isinstance(item, list):
            for child in item:
                visit(child)
        elif isinstance(item, dict):
            if item.get("@type") == "FlightReservation":
                evidence.extend(jsonld_passenger_evidence(item))
            for key in ("@graph", "subReservation", "object"):
                visit(item.get(key))

    for script in BeautifulSoup(html or "", "html.parser").find_all("script", type="application/ld+json"):
        try:
            visit(json.loads(script.string or ""))
        except (ValueError, TypeError):
            continue
    return evidence


def _html_lines(html: str) -> str:
    soup = BeautifulSoup(html or "", "html.parser")
    for tag in soup(["script", "style", "head"]):
        tag.decompose()
    for row in list(soup.find_all("tr")):
        cells = row.find_all(["td", "th"], recursive=False)
        if cells and not row.find("table"):
            row.replace_with("\n" + " | ".join(cell.get_text(" ", strip=True) for cell in cells) + "\n")
    return soup.get_text("\n")


def _traveler_detail_blocks(lines: list[str], start: int, markers: list[tuple[int, str]]) -> list[dict] | None:
    """Read repeated name / flight / ancillary rows as one traveler manifest.

    A flight row between names does not end this particular layout. Names must
    directly precede an explicit flight-and-route row, so payment contacts and
    greetings can never become travelers. Unknown or truncated rows make the
    manifest incomplete: its first person cannot establish exclusive ownership.
    """
    if not re.fullmatch(r"travel(?:l?er)s?\s+details\s*[:|]?", lines[start], re.I):
        return None

    def clean(value: str) -> str:
        return re.sub(r"\[image:[^\]]*\]", "", value, flags=re.I).replace("*", "").strip(" |•\t")

    route = re.compile(r"^([A-Z0-9]{2}\s*\d{1,4})\s*\(([A-Z]{3})\s*[-–→]\s*([A-Z]{3})\)$", re.I)
    end_section = re.compile(r"^(?:payments?|purchase summary|billing|contact|confirmation|booking|reservation|record locator|pnr|fare|total|receipt)\b", re.I)
    ancillary = re.compile(r"^(?:seat|under seat item|personal item|carry[ -]?on(?: bag)?|checked bag(?:gage)?|baggage)\s*:", re.I)
    stop = min(len(lines), start + 160)
    if start + 2 >= len(lines) or not route.fullmatch(clean(lines[start + 2])):
        return None

    entries: list[tuple[str, tuple[str, str, str]]] = []
    incomplete_routes: list[tuple[str, str, str]] = []
    complete, terminated = True, False
    current_name: str | None = None
    end = start
    at = start + 1
    while at < stop:
        current = clean(lines[at])
        if end_section.match(current) or _LABEL.match(current):
            terminated = True
            break
        flight_row = route.fullmatch(current)
        if flight_row and current_name:
            entries.append((current_name, tuple(value.upper().replace(" ", "") for value in flight_row.groups())))
        elif current_name and ancillary.match(current):
            pass
        elif at + 1 < stop and (next_route := route.fullmatch(clean(lines[at + 1]))):
            name = _name(current)
            if name and len(_tokens(name)) >= 2:
                current_name = name
            else:
                incomplete_routes.append(tuple(value.upper().replace(" ", "") for value in next_route.groups()))
                complete = False
                break
        else:
            complete = False
            break
        end = at
        at += 1
    if not entries and not incomplete_routes:
        # The layout was recognized but no trustworthy traveler was found. Do
        # not fall back to a partial generic list and label someone else's name
        # as a complete manifest.
        return []
    complete = complete and terminated
    pnrs = {pnr for _, pnr in markers}
    booking_scope: dict[str, str] = {}
    ambiguous = False
    if len(pnrs) == 1:
        booking_scope["pnr"] = next(iter(pnrs))
    elif len(pnrs) > 1:
        preceding = [(at, pnr) for at, pnr in markers if at <= start]
        if preceding and start - preceding[-1][0] <= 8:
            booking_scope["pnr"] = preceding[-1][1]
        else:
            ambiguous = True
    by_route: dict[tuple[str, str, str], list[str]] = {}
    for name, leg in entries:
        by_route.setdefault(leg, []).append(name)
    for leg in incomplete_routes:
        by_route.setdefault(leg, [])
    return [dict(names=list(dict.fromkeys(names)), complete=complete,
                 scope={**booking_scope, "flight_number": leg[0], "dep_airport": leg[1], "arr_airport": leg[2]},
                 ambiguous=ambiguous, index=start, end=end)
            for leg, names in by_route.items()]


def _text_evidence(text: str, source: str, flights: list) -> list[dict]:
    lines = [re.sub(r"\s+", " ", line).strip(" *\t") for line in text.splitlines() if line.strip()]
    markers: list[tuple[int, str]] = []
    for index, line in enumerate(lines):
        # Labels and their code are often separate HTML cells/lines.
        found = _PNR.search(line.replace("|", " "))
        if not found and re.search(
            r"(?:confirmation(?:\s+(?:code|number))?|booking(?:\s+(?:reference|code|number))?|"
            r"reservation(?:\s+(?:code|number))?|record\s+locator|pnr)\s*[:#-]?$", line, re.I,
        ):
            found = _PNR.search(" ".join(lines[index:index + 2]))
        if (found and found.group(1).lower() not in _NON_NAME
                and (not found.group(1).isalpha() or found.group(1).isupper())):
            markers.append((index, found.group(1).upper()))
    pnrs = {pnr for _, pnr in markers}
    blocks: list[dict] = []
    for index, line in enumerate(lines):
        match = _LABEL.match(line)
        if not match:
            continue
        repeated = _traveler_detail_blocks(lines, index, markers)
        if repeated is not None:
            blocks.extend(repeated)
            continue
        raw = match.group("value").strip()
        names = _names(raw) if raw else []
        if re.match(r"passenger\s+(?:notices|rights|service charge|facility charge)\b", line, re.I):
            continue
        complete = not (names and any(not _name(part) for part in raw.split(";") if part.strip()))
        end = index
        # An explicit header may be followed by column labels before names.
        for follow in range(index + 1, min(len(lines), index + 40)):
            current = lines[follow]
            if not names and re.fullmatch(r"Subtotal\s*:\s*[$£€]?\d[\d,.]*", current, re.I):
                continue
            # These are metadata *inside* a passenger list, never evidence of
            # a person. Stop at every other section boundary as before.
            if names and re.fullmatch(r"Seat\s*:[^|\n]{0,30}\s+Class\s*:[^|\n]{1,40}", current, re.I):
                continue
            if names and re.match(r"Not a FRONTIER Miles\w* Member\?", current, re.I):
                continue
            if names and re.match(r"(?:<?https?://|<\[link\])", current, re.I):
                continue
            if _LABEL.match(current) or _BOUNDARY.match(current):
                break
            if re.fullmatch(r"(?:adult|child|infant)(?:\(s\)|s)?", current, re.I):
                continue
            if not names and re.fullmatch(r"(?:name|names|first name|last name)(?:\s*\|.*)?", current, re.I):
                continue
            extracted = _names(current)
            if not extracted:
                if not re.search(r"\d|\b(?:adult|child|infant|economy|business)\b", current, re.I):
                    complete = False
                break
            names.extend(extracted)
            end = follow
        if not names:
            continue
        count = match.group("count")
        if count and int(count) != len(names):
            complete = False
        # Indexed singular labels describe one record, not a complete manifest.
        if count and re.match(r"(?:passenger|traveler|traveller)\s*[#\d]", line, re.I):
            complete = False
        scope: dict[str, str] = {}
        ambiguous = False
        if len(pnrs) == 1:
            scope["pnr"] = next(iter(pnrs))
        elif len(pnrs) > 1:
            distances: dict[str, int] = {}
            for at, pnr in markers:
                distance = index - at if at <= index else max(0, at - end)
                distances[pnr] = min(distance, distances.get(pnr, 100000))
            ordered = sorted(distances.items(), key=lambda pair: pair[1])
            if ordered[0][1] <= 8 and ordered[0][1] < ordered[1][1]:
                scope["pnr"] = ordered[0][0]
            else:
                ambiguous = True
        blocks.append(dict(names=list(dict.fromkeys(names)), complete=complete, scope=scope,
                           ambiguous=ambiguous, index=index, end=end))

    # Without a booking code, distinct traveler sections need local flight scope.
    flight_numbers = {str(f.flight_number or "").upper().replace(" ", "") for f in flights} - {""}
    flight_pnrs = {str(f.pnr or "").upper() for f in flights} - {""}
    for block in blocks:
        if not block["scope"] and (len(blocks) > 1 or len(flight_pnrs) > 1):
            if len(blocks) > 1 and len(flight_numbers) < 2:
                block["ambiguous"] = True
                continue
            nearby: dict[str, int] = {}
            for index, line in enumerate(lines):
                for number in flight_numbers:
                    pattern = re.escape(number[:2]) + r"\s*" + re.escape(number[2:])
                    if re.search(r"(?<![A-Z0-9])" + pattern + r"(?![A-Z0-9])", line.upper()):
                        distance = block["index"] - index if index <= block["index"] else max(0, index - block["end"])
                        nearby[number] = min(distance, nearby.get(number, 100000))
            ordered = sorted(nearby.items(), key=lambda pair: pair[1])
            if ordered and ordered[0][1] <= 5 and (len(ordered) == 1 or ordered[0][1] < ordered[1][1]):
                block["scope"]["flight_number"] = ordered[0][0]
            else:
                block["ambiguous"] = True
    # Repeated detail headers still form one manifest for an exact booking leg.
    # An unreadable person in another such section invalidates exclusivity, but
    # must not weaken a separate booking's complete traveler evidence.
    incomplete_scopes = {json.dumps(block["scope"], sort_keys=True) for block in blocks
                         if not block["complete"] and block["scope"].get("flight_number")
                         and not block["ambiguous"]}
    for block in blocks:
        if json.dumps(block["scope"], sort_keys=True) in incomplete_scopes:
            block["complete"] = False
    labeled = [dict(name=name, source=source, role="traveler", complete=block["complete"],
                 scope=block["scope"], scope_ambiguous=block["ambiguous"])
            for block in blocks for name in block["names"]]
    return labeled + _fare_ticket_evidence(lines, source, flights)


def _fare_ticket_evidence(lines: list[str], source: str, flights: list) -> list[dict]:
    """A named fare with issued ticket numbers identifies the ticket holder.

    Some agency receipts put travelers under Fare Details, separately from the
    payer under Payment Info. A combined ticket list may cover several airline
    bookings, but only when those codes are explicitly listed in one receipt.
    """
    starts = [index for index, line in enumerate(lines) if re.fullmatch(r"fare details", line, re.I)]
    if not starts:
        return []
    pnrs = {str(f.pnr).upper() for f in flights if f.pnr}
    listed_codes: set[str] = set()
    for index, line in enumerate(lines):
        if re.fullmatch(r"(?:your\s+)?confirmation codes", line, re.I):
            for entry in lines[index + 1:index + 9]:
                code = entry.split("|")[-1].strip().upper()
                if code in pnrs:
                    listed_codes.add(code)
    evidence = []
    for start in starts:
        person: str | None = None
        tickets: list[str] = []
        fare = taxes = False

        def flush() -> None:
            if not person or not (tickets or (fare and taxes)):
                return
            multiple = len(pnrs) > 1
            combined = (len(starts) == 1 and listed_codes == pnrs
                        and (not tickets or len(tickets) >= len(pnrs)))
            # A combined, named fare table identifies its travelers even when
            # a low-cost airline has no 13-digit ticket number. All booking
            # codes must be explicitly listed; arbitrary adjacent bookings
            # never inherit a traveler from this section.
            scope = {"pnrs": sorted(pnrs)} if pnrs and (not multiple or combined) else {}
            evidence.append(dict(name=person,
                source=source + ("_fare_ticket_holder" if tickets else "_named_fare_holder"),
                role="traveler", complete=True, scope=scope,
                scope_ambiguous=multiple and not combined, ticket_count=len(tickets)))

        for line in lines[start + 1:start + 60]:
            if re.match(r"(?:payment|card payment|travel credits|total|airline fare rules|helpful links)\b", line, re.I):
                break
            name = _name(line)
            if name and len(_tokens(name)) >= 2:
                flush()
                person, tickets, fare, taxes = name, [], False, False
                continue
            if not person:
                continue
            if re.search(r"\bticket\s*(?:#|number|no\.)", line, re.I):
                tickets.extend(re.findall(r"\b\d{13}\b", line))
            if re.match(r"Base Fare\s*:", line, re.I) and re.search(r"\d[.,]\d{2}", line):
                fare = True
            if re.match(r"Taxes (?:and|&) Fees\s*:", line, re.I) and re.search(r"\d[.,]\d{2}", line):
                taxes = True
        flush()
    return evidence


def merge_passenger_evidence(*groups: list[dict]) -> list[dict]:
    merged: list[dict] = []
    seen: set[str] = set()
    for group in groups:
        for item in group:
            key = json.dumps({key: value for key, value in item.items() if key != "applies"},
                             sort_keys=True, ensure_ascii=False)
            if key not in seen:
                merged.append(dict(item))
                seen.add(key)
    return merged


def _applies(item: dict, flight, *, multiple_bookings: bool) -> bool:
    if item.get("scope_ambiguous"):
        return False
    scope = item.get("scope") or {}
    if not scope and multiple_bookings:
        return False
    checks = ("flight_number", "dep_airport", "arr_airport")
    for key in checks:
        if scope.get(key) and str(scope[key]).upper().replace(" ", "") != str(getattr(flight, key, "") or "").upper().replace(" ", ""):
            return False
    if scope.get("pnr"):
        known = {str(flight.pnr or "").upper(), *[str(p).upper() for p in getattr(flight, "pnr_aliases", [])]}
        if str(scope["pnr"]).upper() not in known:
            return False
    if scope.get("pnrs") and str(flight.pnr or "").upper() not in scope["pnrs"]:
        return False
    if scope.get("departure_date") and scope["departure_date"] != flight.dep_time.date().isoformat():
        return False
    return True


def apply_passenger_identity(flights: list, *, html: str, plain_text: str,
                             user_name: str, aliases: list[str]) -> None:
    """Annotate every flight, retaining uncertain evidence without auto-importing it."""
    if not flights:
        return
    evidence = merge_passenger_evidence(
        _jsonld_evidence(html), _text_evidence(plain_text or "", "text_passenger_label", flights),
        _text_evidence(_html_lines(html), "html_passenger_label", flights),
    )
    candidates = [name for name in [user_name, *aliases] if name and "@" not in name]
    multiple = len({str(f.pnr).upper() for f in flights if f.pnr}) > 1
    for flight in flights:
        own_evidence = list(getattr(flight, "passenger_evidence", []) or [])
        # Compatibility for established extractors and callers with a scalar name.
        existing_names = list(getattr(flight, "passenger_names", []) or [])
        if getattr(flight, "passenger_name", None):
            existing_names.append(flight.passenger_name)
        if not own_evidence:
            own_evidence = [dict(name=name, source="parsed_passenger", role="traveler", complete=False,
                                 scope={"flight_number": flight.flight_number} if flight.flight_number else {})
                            for name in existing_names]
        attached = []
        for item in merge_passenger_evidence(own_evidence, evidence):
            item["applies"] = _applies(item, flight, multiple_bookings=multiple)
            attached.append(item)
        applicable = [item for item in attached if item["applies"]]
        names = list(dict.fromkeys(item["name"] for item in applicable))
        matched = any(names_match(name, candidate) for name in names for candidate in candidates)
        # A lone initial cannot choose between two explicitly different people.
        full_match = any(len(_tokens(name)) >= 2 and all(len(t) > 1 for t in _tokens(name))
                         and names_match(name, candidate) for name in names for candidate in candidates)
        ambiguous_initial = matched and not full_match and any(
            not any(names_match(name, candidate) for candidate in candidates)
            and any(names_match(initial, name) for initial in names if any(len(t) == 1 for t in _tokens(initial)))
            for name in names
        )
        ambiguous_compact = any(_ambiguous_compact_given_name(name, candidate)
                                for name in names for candidate in candidates)
        flight.passenger_names = names
        flight.passenger_name = names[0] if names else None
        flight.passenger_evidence = attached
        if matched and not ambiguous_initial:
            flight.ownership = "self"
        elif (candidates and applicable and any(item.get("complete") for item in applicable)
              and all(len(_tokens(name)) >= 2 for name in names)
              and not ambiguous_initial and not ambiguous_compact):
            flight.ownership = "other"
        else:
            flight.ownership = "unknown"
