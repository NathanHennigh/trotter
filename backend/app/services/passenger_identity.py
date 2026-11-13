"""Traveler evidence and conservative ownership, independent of route extraction.

Inbox recipients, greetings, billing contacts and forwarding headers are not
traveler evidence. Unscoped names in a message with multiple bookings remain
available for review, but do not establish ownership of any individual flight.
"""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime
from hashlib import sha256
from typing import Any

from bs4 import Comment

from .booking_references import extract_reference_fields
from .html_visibility import permitted_jsonld_scripts, visible_html_soup


_TITLE = {"mr", "mrs", "ms", "miss", "dr", "prof", "mstr", "madame", "mme", "monsieur", "mlle"}
_SUFFIX = {"jr", "sr", "ii", "iii", "iv"}
_NON_NAME = set(
    "passenger passengers traveler travelers traveller travellers name names first last info "
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
_BOUNDARY = re.compile(
    r"^(?:from|to|sent|date|subject|dear|hello|hi|payment|billing|paid|buyer|purchaser|"
    r"contact|confirmation|booking|reservation|record|pnr|flight|depart|arriv|itinerary|"
    r"ticket|seat|baggage|fare|total|price|cost|tax|amount|your|thank|check|loyalty|"
    r"frequent|member|manage|outbound|inbound|return|receipt|bags|bundles|services|rapid rewards|"
    r"est\. points|known traveler)\b", re.I,
)


def _tokens(value: str) -> list[str]:
    value = unicodedata.normalize("NFKD", value).casefold()
    value = "".join(c for c in value if not unicodedata.combining(c))
    value = value.replace("'", "").replace("’", "")
    value = re.sub(r"[^\w\s]", " ", value, flags=re.UNICODE)
    return [part for part in value.split() if part not in _TITLE]


def _ordered_name_tokens(value: str) -> list[str]:
    """Canonicalize explicit family/given notation without sorting name parts."""
    if len(re.findall(r'[/,]', value)) != 1:
        return _tokens(value)
    family_text, given_text = re.split(r'[/,]', value)
    family, given = _tokens(family_text), _tokens(given_text)
    if not family or not given:
        return []
    # A comma before a suffix is natural-order punctuation, not family/given.
    if ',' in value and len(given) == 1 and given[0] in _SUFFIX:
        previous = family[-1] if family[-1] in _SUFFIX else None
        if previous and previous != given[0]:
            return []
        return family if previous else family + given
    family_suffix = family.pop() if family[-1] in _SUFFIX else None
    given_suffix = given.pop() if given[-1] in _SUFFIX else None
    if not family or not given or (family_suffix and given_suffix and family_suffix != given_suffix):
        return []
    suffix = family_suffix or given_suffix
    return given + family + ([suffix] if suffix else [])


def identity_candidates(user_name: str | None, aliases: list[str] | None) -> list[str]:
    """Prefer explicitly confirmed full names over their ambiguous short form."""
    candidates = list(dict.fromkeys(name.strip() for name in [user_name, *(aliases or [])]
                                   if isinstance(name, str) and name.strip() and '@' not in name))

    def parts(name):
        tokens = _ordered_name_tokens(name)
        suffix = tokens[-1] if tokens and tokens[-1] in _SUFFIX else None
        tokens = tokens[:-1] if suffix else tokens
        if (len(tokens) < 2 or len(tokens[0]) < 2 or len(tokens[-1]) < 2
                or any(not token.isalpha() or token in _SUFFIX for token in tokens)):
            return None
        return tokens[-1], suffix, tokens[:-1]

    parsed = [parts(name) for name in candidates]
    # Do not infer that compound family-name particles are middle names.
    particles = {'de', 'del', 'da', 'di', 'du', 'la', 'le', 'van', 'von', 'der', 'den', 'bin', 'ibn', 'al'}
    full_names = [value for value in parsed if value and len(value[2]) >= 2
                  and all(len(token) > 1 for token in value[2])
                  and not particles.intersection(value[2][1:])]

    def less_specific(value, full):
        if not value or value[:2] != full[:2] or value[2][0] != full[2][0]:
            return False
        given, known = value[2], full[2]
        return len(given) == 1 or (len(given) == len(known) and given != known
            and all(left == right or (len(left) == 1 and left == right[0])
                    for left, right in zip(given[1:], known[1:])))

    return [name for name, value in zip(candidates, parsed)
            if not any(less_specific(value, full) for full in full_names)]


def _compact_given_matches(left: list[str], right: list[str]) -> bool:
    """Compare fused given names only against explicitly supplied components."""
    for compact, full in ((left, right), (right, left)):
        if (len(compact) != 1 or not 2 <= len(full) <= 8
                or any(len(token) < 2 or not token.isalpha() for token in full)):
            continue
        if compact[0] == ''.join(full):
            return True
    return False


def names_match(passenger: str, candidate: str) -> bool:
    """Match full names, reordered names, or a compatible given-name initial.

    A first name or surname alone never matches a longer account name. Explicit
    conflicting middle names and generational suffixes are not discarded.
    """
    a, b = _ordered_name_tokens(passenger), _ordered_name_tokens(candidate)
    if not a or not b or "@" in candidate or "@" in passenger:
        return False
    if len(a) < 2 or len(b) < 2:
        return a == b and len(a) == len(b)
    if a == b:
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
            if _compact_given_matches(left[:-1], right[:-1]):
                return True
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
    airline = flight.get("airline") or flight.get("provider") or {}
    airline_code = airline.get("iataCode", "") if isinstance(airline, dict) else ""
    number = str(flight.get("flightNumber") or "").upper().replace(" ", "")
    if number and airline_code and not number.startswith(airline_code.upper()):
        number = airline_code.upper() + number
    scope = {
        "pnr": str(item.get("reservationNumber") or item.get("reservationId") or "").upper().strip(),
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

    for script in permitted_jsonld_scripts(html or ""):
        try:
            visit(json.loads(script.string or ""))
        except (ValueError, TypeError):
            continue
    return evidence


class _VisibleRosterText(str):
    """Visible text with non-textual boundaries for self-contained roster cards."""
    def __new__(cls, text: str, roster_boundaries: set[int]):
        result = super().__new__(cls, text)
        result.roster_boundaries = frozenset(roster_boundaries)
        return result


def _html_lines(html: str) -> str:
    soup = visible_html_soup(html or "")
    # Normalizing a Comment with replace_with(str) turns it into visible text.
    # Conditional template markers and names inside comments are never roster
    # evidence, even when they occur between genuine table-cell text nodes.
    for comment in list(soup.find_all(string=lambda node: isinstance(node, Comment))):
        comment.extract()
    for row in list(soup.find_all("tr")):
        cells = row.find_all(["td", "th"], recursive=False)
        if cells and not row.find("table"):
            values = []
            for cell in cells:
                # Preserve displayed paragraphs inside a cell. A responsive
                # table can put all headings in one cell and all values in the
                # next; flattening it loses the passenger label entirely.
                for node in list(cell.find_all(string=True)):
                    node.replace_with(re.sub(r"\s+", " ", str(node)))
                for block in list(cell.find_all(["p", "div", "br"])):
                    block.insert_before("\n")
                    block.insert_after("\n")
                values.append("\n".join(re.sub(r"\s+", " ", part).strip()
                                        for part in cell.get_text(" ").splitlines() if part.strip()))
            # An empty icon/padding cell must not prefix this explicit roster heading.
            nonempty = [value for value in values if value]
            if (values and not values[0] and len(nonempty) == 1
                    and re.fullmatch(r"Traveler Information\s*:?", nonempty[0], re.I)):
                values = nonempty
            separator = "\n" if any("\n" in value for value in values) else " | "
            row.replace_with("\n" + separator.join(values) + "\n")
    # A visible checklist heading followed by its instruction subheading and
    # numbered steps starts a new section, not another traveler. Preserve that
    # DOM boundary without interpreting an arbitrary leaf-table end as exclusive
    # roster authority. Literal source text cannot manufacture the boundary.
    marker = "__VISIBLE_ROSTER_CARD_END__"
    existing = soup.get_text("\n")
    if "Travel Checklist" not in existing or "Before your trip:" not in existing:
        return existing
    while marker in existing:
        marker += "_"
    for table in reversed(list(soup.find_all("table"))):
        lines = [re.sub(r"\s+", " ", line).strip(" *\t")
                 for line in table.get_text("\n").splitlines() if line.strip()]
        if len(lines) < 4 or lines[:2] != ["Travel Checklist", "Before your trip:"]:
            continue
        numbered = [int(match.group(1)) for line in lines[2:14]
                    if (match := re.match(r"^(\d+)\.\s*(?:\|\s*)?\S.+", line))]
        if numbered[:2] != [1, 2]:
            continue
        table.insert_before("\n" + marker + "\n")
    output = []; boundaries = set(); line_number = 0
    for line in soup.get_text("\n").splitlines():
        if line.strip() == marker:
            boundaries.add(line_number)
        else:
            output.append(line)
            if line.strip():
                line_number += 1
    return _VisibleRosterText("\n".join(output), boundaries)


def _html_itinerary_passengers(html: str, flights: list) -> list[dict]:
    """Bind a named timetable cell to its exact already-parsed dated leg."""
    if (not html or len(html) > 200_000
            or not all(word in html.lower() for word in ("<table", "departs", "arrives", "passengers"))):
        return []
    soup = visible_html_soup(html)
    for comment in list(soup.find_all(string=lambda node: isinstance(node, Comment))):
        comment.extract()
    codes = {field.code for field in extract_reference_fields(soup.get_text("\n"))}
    if len(codes) != 1:
        return []
    pnr = next(iter(codes))
    headings = ["date", "departs", "arrives", "flt #", "route", "passengers", "seat", "terminal"]
    result = []
    all_tables_complete = True
    coherent = True
    matched_flights = set()

    def text(cell):
        return re.sub(r"\s+", " ", cell.get_text(" ", strip=True)).strip()

    def local_times(flight):
        proof = getattr(flight, "time_provenance", {}) or {}
        if not isinstance(proof, dict):
            return None
        if proof.get("status") == "normalized":
            try:
                return tuple(datetime.fromisoformat(proof[key]["local"]) for key in ("departure", "arrival"))
            except (KeyError, TypeError, ValueError):
                return None
        values = (getattr(flight, "dep_time", None), getattr(flight, "arr_time", None))
        return values if all(isinstance(v, datetime) for v in values) else None

    def clock(value):
        if not re.fullmatch(r"\d{1,2}:[0-5]\d\s*[AP]M", value, re.I):
            return None
        try:
            return datetime.strptime(re.sub(r"\s+", "", value.upper()), "%I:%M%p").time()
        except ValueError:
            return None

    for table in soup.find_all("table"):
        rows = [row for row in table.find_all("tr") if row.find_parent("table") is table]
        if not rows:
            continue
        header = rows[0].find_all(["th", "td"], recursive=False)
        if [text(cell).lower() for cell in header] != headings:
            continue
        if (not 2 <= len(rows) <= 100
                or any(str(cell.get(attr, "1")) != "1" for cell in header for attr in ("rowspan", "colspan"))):
            all_tables_complete = False
            coherent = False
            continue
        entries, complete = [], True
        for row in rows[1:]:
            cells = row.find_all(["td", "th"], recursive=False)
            if (len(cells) != len(headings) or any(cell.find("table") for cell in cells)
                    or any(str(cell.get(attr, "1")) != "1" for cell in cells for attr in ("rowspan", "colspan"))):
                complete = False
                coherent = False
                continue
            day, departure, arrival, number, route = (text(cell) for cell in cells[:5])
            date_match = re.fullmatch(r"(Mon|Tue|Wed|Thu|Fri|Sat|Sun),?\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s*(\d{1,2})(?:,?\s+(\d{4}))?", day, re.I)
            route_match = re.fullmatch(r"([A-Z]{3})\s+to\s+([A-Z]{3})", route, re.I)
            number_match = re.fullmatch(r"([A-Z0-9]{2})\s*(\d{1,4})(?:\s+Operated by\s+[A-Z .&'-]{2,100})?", number, re.I)
            dep_clock, arr_clock = clock(departure), clock(arrival)
            if not (date_match and route_match and number_match and dep_clock and arr_clock):
                complete = False
                coherent = False
                continue
            flight_number = number_match[1].upper() + str(int(number_match[2]))
            if int(number_match[2]) == 0:
                complete = False
                coherent = False
                continue
            matching = []
            for flight in flights:
                times = local_times(flight)
                if (not times or getattr(flight, "force_review", False) or str(flight.pnr or "").upper() != pnr
                        or str(flight.flight_number or "").upper().replace(" ", "") != flight_number
                        or (flight.dep_airport, flight.arr_airport) != tuple(v.upper() for v in route_match.groups())):
                    continue
                local_dep, local_arr = times
                if (local_dep.strftime("%a").lower() != date_match[1].lower()
                        or local_dep.strftime("%b").lower() != date_match[2].lower()
                        or local_dep.day != int(date_match[3])
                        or date_match[4] and local_dep.year != int(date_match[4])
                        or local_dep.time().replace(tzinfo=None) != dep_clock
                        or local_arr.time().replace(tzinfo=None) != arr_clock):
                    continue
                matching.append(flight)
            if len(matching) != 1:
                complete = False
                coherent = False
                continue
            matched_flights.add(id(matching[0]))
            for br in cells[5].find_all("br"):
                br.replace_with(" | ")
            raw_name = text(cells[5])
            parts = re.split(r"\s*(?:\||;|\s+and\s+|\s+&\s+)\s*", raw_name, flags=re.I)
            names = _names(raw_name)
            if not names or any(not _name(part) or len(_tokens(part)) < 2 for part in parts):
                complete = False
            flight = matching[0]
            scope = {"pnr":pnr, "flight_number":flight_number, "dep_airport":flight.dep_airport,
                     "arr_airport":flight.arr_airport, "departure_date":flight.dep_time.date().isoformat()}
            entries.extend(dict(name=name, source="html_itinerary_passenger_column", role="traveler",
                                scope=scope, scope_ambiguous=False) for name in names)
        result.extend({**entry, "complete":complete} for entry in entries)
        all_tables_complete = all_tables_complete and complete
    if not coherent:
        # This new identity path cannot promote selected rows while another
        # printed leg is absent/ambiguous. Existing identity paths and the
        # original message remain intact for review.
        return []
    matched = [flight for flight in flights if id(flight) in matched_flights]
    for aggregate in flights:
        if id(aggregate) in matched_flights or str(aggregate.pnr or "").upper() != pnr:
            continue
        times = local_times(aggregate)
        if not times:
            continue
        outer_start, outer_end = (value.replace(tzinfo=None) for value in times)
        number = str(aggregate.flight_number or "").upper().replace(" ", "")
        legs = [(flight, local_times(flight)) for flight in matched
            if str(flight.flight_number or "").upper().replace(" ", "") == number]
        legs = [(flight, start.replace(tzinfo=None), end.replace(tzinfo=None))
            for flight, pair in legs if pair for start, end in [pair]]
        queue = [(flight, end, 1) for flight, start, end in legs
            if flight.dep_airport == aggregate.dep_airport and start.date() == outer_start.date()]
        visited = set()
        while queue:
            current, arrival, depth = queue.pop()
            if id(current) in visited:
                continue
            visited.add(id(current))
            if depth > 1 and current.arr_airport == aggregate.arr_airport and arrival.date() == outer_end.date():
                # Explicit clocked stop rows and an unmatched through-summary
                # compete on the same dated journey, even if their clocks
                # differ. Grant no new ownership until extraction is coherent;
                # this does not merge, retire, or create any flight candidates.
                return []
            queue.extend((flight, end, depth + 1) for flight, start, end in legs
                if id(flight) not in visited and flight.dep_airport == current.arr_airport and start >= arrival)
    if not all_tables_complete:
        for entry in result:
            entry["complete"] = False
    return result


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


def _ticketed_traveler_details(lines: list[str], start: int,
                              markers: list[tuple[int, str]]) -> list[dict] | None:
    """Read each named eTicket/seat-route row before Purchase Summary.

    A ticket row is metadata inside this manifest, not its end. Require the
    printed route on every record; malformed or truncated records cannot make
    the first readable traveler an exclusive roster.
    """
    if (not re.fullmatch(r"travel(?:l?er)s?\s+details\s*[:|]?", lines[start], re.I)
            or start + 2 >= len(lines)
            or not re.match(r"eTicket\s+number\s*:", lines[start + 2], re.I)):
        return None
    ticket_route = re.compile(r"eTicket\s+number\s*:\s*(\d{13})(?:\s*\(Credited\))?\s*\|?\s*Seats\s*:\s*"
                              r"([A-Z]{3})\s*[-–]\s*([A-Z]{3})\s+(?:-{2,8}|\d{1,3}[A-Z])", re.I)
    seat_route = re.compile(r"([A-Z]{3})\s*[-–]\s*([A-Z]{3})\s+(?:-{2,8}|\d{1,3}[A-Z])", re.I)
    frequent = re.compile(r"Frequent\s+Flyer\s*:\s*UA-[A-Z0-9*]{3,24}\s+Member(?:\s*\|\s*(.+))?", re.I)
    ancillary = re.compile(r"Preferred\s+zone\s+seat\s*\(\d{13}\)\s*\|\s*([A-Z]{3})\s*[-–]\s*([A-Z]{3})", re.I)
    cursor, end, complete, terminated = start + 1, start, True, False
    by_route: dict[tuple[str, str], list[str]] = {}
    ticket_keys: dict[tuple[str, str], dict[str, set[str]]] = {}
    while cursor < min(len(lines), start + 80):
        if re.fullmatch(r"Purchase\s+Summary\s*:?", lines[cursor], re.I):
            terminated = True
            break
        if cursor + 1 >= len(lines):
            complete = False
            break
        metadata, consumed = lines[cursor + 1], 2
        if (re.fullmatch(r"eTicket\s+number\s*:\s*\d{13}(?:\s*\(Credited\))?", metadata, re.I)
                and cursor + 2 < len(lines)):
            metadata += " " + lines[cursor + 2]
            consumed = 3
        route = ticket_route.fullmatch(metadata)
        if not route or route[2].upper() == route[3].upper():
            complete = False
            break
        routes = [(route[2].upper(), route[3].upper())]
        name = _name(lines[cursor])
        end = cursor + consumed - 1
        cursor += consumed
        # United prints further seat routes in the adjacent column of the
        # frequent-flyer row. Those are still this named person's issued ticket;
        # a paid seat reference is ancillary and never another issued ticket.
        while cursor < min(len(lines), start + 80):
            line = lines[cursor]
            if re.fullmatch(r"Purchase\s+Summary\s*:?", line, re.I):
                break
            if (cursor + 1 < len(lines) and _name(line)
                    and re.match(r"eTicket\s+number\s*:", lines[cursor + 1], re.I)):
                break
            ff, extra, paid = frequent.fullmatch(line), seat_route.fullmatch(line), ancillary.fullmatch(line)
            if ff and ff[1]:
                extra = seat_route.fullmatch(ff[1])
                if extra is None:
                    complete = False
                    break
            if extra:
                pair = (extra[1].upper(), extra[2].upper())
                if pair[0] == pair[1] or len(routes) >= 8:
                    complete = False
                    break
                if pair not in routes:
                    routes.append(pair)
            elif paid:
                if (paid[1].upper(), paid[2].upper()) not in routes:
                    complete = False
                    break
            elif not ff:
                complete = False
                break
            end = cursor
            cursor += 1
        if name and len(_tokens(name)) >= 2:
            for route_key in routes:
                by_route.setdefault(route_key, []).append(name)
                ticket_keys.setdefault(route_key, {}).setdefault(name, set()).add(_issued_ticket_key(route[1]))
        else:
            complete = False
        if not complete:
            break
    pnrs = {pnr for _, pnr in markers}
    scope, ambiguous = {}, False
    if len(pnrs) == 1:
        scope["pnr"] = next(iter(pnrs))
    elif len(pnrs) > 1:
        preceding = [(at, pnr) for at, pnr in markers if at <= start]
        if preceding and start - preceding[-1][0] <= 8:
            scope["pnr"] = preceding[-1][1]
        else:
            ambiguous = True
    return [dict(names=list(dict.fromkeys(names)), complete=complete and terminated,
                 scope={**scope, "dep_airport": route[0], "arr_airport": route[1]},
                 issued_ticket_keys={name: next(iter(keys)) for name, keys in ticket_keys.get(route, {}).items()
                    if complete and terminated and len(pnrs) == 1 and scope.get("pnr") and not ambiguous and len(keys) == 1
                    and None not in keys and not any(keys & others for other, others in ticket_keys[route].items() if other != name)},
                 ambiguous=ambiguous, index=start, end=end)
            for route, names in by_route.items()]


def _emirates_loyalty_footer(lines: list[str], at: int) -> bool:
    """Recognize the exact loyalty field and following seat-management footer."""
    return (at + 2 < len(lines)
            and bool(re.fullmatch(r"Emirates\s+Skywards\s+number\s*:?", lines[at], re.I))
            and bool(re.fullmatch(r"EK\d{6,12}", lines[at + 1], re.I))
            and bool(re.fullmatch(r"Choose\s+your\s+seat", lines[at + 2].strip(" |"), re.I)))


def _passenger_table(lines: list[str], start: int) -> tuple[list[str], bool, int] | None:
    """Read passenger/loyalty/ticket tables without turning headings into names.

    Plain MIME can stack every column heading before its row values; HTML
    extraction retains pipes between cells. Both forms keep the name column
    distinct and retain all passengers, including an unreadable manifest row.
    """
    def heading(value: str) -> str:
        return re.sub(r"[^a-z ]", "", value.casefold()).strip()

    columns = {"passenger", "passenger name", "rapid rewards", "ticket", "ticket number",
               "est points earned", "estimated points earned", "seat", "seats"}
    first = [heading(part) for part in lines[start].split("|")]
    horizontal = len(first) > 1
    if not first or first[0] not in {"passenger", "passenger name"}:
        return None
    headers = first[:]
    cursor = start + 1
    if horizontal:
        if any(value not in columns for value in headers):
            return None
    else:
        while cursor < len(lines) and heading(lines[cursor]) in columns - {"passenger", "passenger name"}:
            headers.append(heading(lines[cursor]))
            cursor += 1
    if len(headers) < 2 or not set(headers).intersection({"rapid rewards", "ticket", "ticket number"}):
        return None
    names, complete, end = [], True, cursor - 1
    while cursor < min(len(lines), start + 100):
        if _LABEL.match(lines[cursor]) or _BOUNDARY.match(lines[cursor]):
            break
        cells = lines[cursor].split("|") if horizontal else lines[cursor:cursor + len(headers)]
        if len(cells) != len(headers):
            complete = False
            break
        name = _name(cells[0])
        if name and len(_tokens(name)) >= 2:
            names.append(name)
        else:
            complete = False
        end = cursor + (0 if horizontal else len(headers) - 1)
        cursor = end + 1
    return names, complete, end


def _numbered_card_travelers(lines: list[str], start: int, flights: list,
                             markers: list[tuple[int, str]]) -> list[dict] | None:
    """Keep name/seat/class rows inside their explicit dated flight card.

    Decorative empty HTML cells may prefix the label and seat row with a pipe.
    Only the recognized card extractor and exact seat/class grammar qualify;
    arbitrary numbered rows, a payer, or a later card cannot extend a roster.
    """
    clean = lambda value: value.strip(" |\t")
    if not re.fullmatch(r"travel(?:l?er)(?:\(s\)|s)?\s*:", clean(lines[start]), re.I):
        return None
    candidates = [f for f in flights if getattr(f, "source", None) == "shape_alaska_trip_detail_blocks"]
    if not candidates:
        return None
    seat_class = re.compile(r"\d{1,3}[A-Z][★*]?\s*[.·|]\s*Class\s*:\s*[A-Z]"
                            r"(?:\s+(?:COACH|FIRST|BUSINESS|PREMIUM|ECONOMY))?", re.I)
    stop = min(len(lines), start + 40)
    if not any(seat_class.fullmatch(clean(value)) for value in lines[start + 1:stop]):
        return None
    headings = [at for at in range(max(0, start - 45), start)
                if re.match(r"^Flight\s+\d{1,2}\b", clean(lines[at]), re.I)]
    if not headings:
        return None
    card_start = headings[-1]
    header = " ".join(clean(value) for value in lines[card_start:start]).upper()
    matches = {}
    for flight in candidates:
        number = str(flight.flight_number or "").upper().replace(" ", "")
        if not re.fullmatch(r"[A-Z0-9]{2}\d{1,4}", number):
            continue
        if not re.search(r"(?<![A-Z0-9])" + re.escape(number[:2]) + r"\s*"
                         + re.escape(number[2:]) + r"(?![A-Z0-9])", header):
            continue
        if not all(code and re.search(r"\b" + re.escape(code.upper()) + r"\b", header)
                   for code in (flight.dep_airport, flight.arr_airport)):
            continue
        key = (number, flight.dep_airport, flight.arr_airport, flight.pnr,
               flight.dep_time.isoformat() if flight.dep_time else None,
               flight.arr_time.isoformat() if flight.arr_time else None)
        matches[key] = flight
    # A recognized but ambiguous card must not fall back to unscoped names.
    if len(matches) != 1:
        return []
    (number, dep, arr, pnr, _, _), flight = next(iter(matches.items()))
    preceding = [code for at, code in markers if at <= card_start]
    known = {str(pnr or "").upper(), *(str(code).upper() for code in getattr(flight, "pnr_aliases", []) or [])}
    if preceding and preceding[-1] not in known:
        return []
    scope = {"flight_number": number, "dep_airport": dep, "arr_airport": arr}
    if pnr:
        scope["pnr"] = pnr
    if flight.dep_time:
        scope["departure_date"] = flight.dep_time.date().isoformat()
    names, complete, end, cursor = [], True, start, start + 1
    terminated = False
    boundary = re.compile(r"^(?:next\s+flight|flight\s+\d|summary\s+of\s+airfare|fare\s+breakdown|"
                          r"payment|billing|confirmation|booking|reservation|contact|additional\s+charges)\b", re.I)
    while cursor < stop:
        current = clean(lines[cursor])
        if (boundary.match(current) or re.match(r"^[★*]\s*Premium Class seat\b", current, re.I)
                or re.fullmatch(r"Special information related to your trip:\s*(?:(?:CTCE|CTCM)(?:,\s*(?:CTCE|CTCM))*)?", current, re.I)):
            terminated = True
            break
        name = _name(current)
        if not name or len(_tokens(name)) < 2:
            complete = False
            break
        names.append(name)
        end = cursor
        cursor += 1
        if cursor >= stop or not seat_class.fullmatch(clean(lines[cursor])):
            complete = False
            break
        end = cursor
        cursor += 1
    return [dict(names=list(dict.fromkeys(names)), complete=complete and terminated,
                 scope=scope, ambiguous=False, index=start, end=end)] if names else []


def _priceline_ticket_travelers(lines: list[str], start: int, flights: list) -> list[dict] | None:
    """Bind an issued-ticket roster to its bounded, dated journey cards."""
    clean = lambda value: value.strip(" |\t")
    label = clean(lines[start])
    cursor = start + 1
    if label.casefold() == "passengers" and cursor < len(lines) and re.fullmatch(
            r"and\s+Tickets\s*:", clean(lines[cursor]), re.I):
        cursor += 1
    elif not re.fullmatch(r"Passengers\s+and\s+(?:Tickets|Ticket Numbers)\s*:", label, re.I):
        return None
    journeys = {}
    for flight in flights:
        leg = getattr(flight, "source_leg", {}) or {}
        scope = leg.get("journey_scope")
        if (getattr(flight, "source", None) != "shape_priceline_trip_cards"
                or leg.get("template") != "priceline_trip_cards" or leg.get("ambiguous") is not False
                or not isinstance(scope, dict) or set(scope) != {"dep_airport", "arr_airport", "departure_date"}):
            continue
        key = (scope["dep_airport"], scope["arr_airport"], scope["departure_date"])
        journeys[key] = scope
    # A recognized roster never supplies global authority to legacy guesses.
    if not journeys:
        return []
    trip_ids = []
    for at, line in enumerate(lines):
        trip_label = re.fullmatch(r"Priceline\s+Trip\s+Number\s*:\s*(.*)", clean(line), re.I)
        if not trip_label:
            continue
        value = clean(trip_label[1]) or (clean(lines[at + 1]) if at + 1 < len(lines) else "")
        trip_ids.append(value if re.fullmatch(r"\d{3}-\d{3}-\d{3}-\d{2}", value) else None)
    trip_id = trip_ids[0] if trip_ids and None not in trip_ids and len(set(trip_ids)) == 1 else None
    ticket = re.compile(r"([A-Z]{3})\s*>\s*([A-Z]{3})\s*:\s*(\d{13})", re.I)
    boundary = re.compile(r"^(?:(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2}\b|"
                          r"Payment|Billing|Summary of Charges|Important Information|Contact)", re.I)
    entries, complete, terminated = [], True, False
    stop = min(len(lines), start + 60)
    while cursor < stop:
        if boundary.match(clean(lines[cursor])):
            terminated = True
            break
        name = _name(clean(lines[cursor]))
        if not name or len(_tokens(name)) < 2:
            complete = False
            break
        cursor += 1
        routes = []
        while cursor < stop:
            matched, count = None, 0
            for size in range(1, min(5, stop - cursor) + 1):
                matched = ticket.fullmatch(" ".join(clean(value) for value in lines[cursor:cursor + size]))
                if matched:
                    count = size
                    break
            if not matched:
                break
            dep, arr = matched.group(1).upper(), matched.group(2).upper()
            scopes = [scope for (origin, destination, _), scope in journeys.items() if (origin, destination) == (dep, arr)]
            if len(scopes) == 1:
                routes.append((scopes[0], matched.group(3)))
            cursor += count
        if not routes:
            complete = False
            break
        entries.extend((name, scope, ticket_number) for scope, ticket_number in routes)
    from .agency_ticket_evidence import make_agency_ticket
    return [dict(names=[name], complete=complete and terminated,
                 scope={"journey_scope":scope}, ambiguous=False, index=start, end=cursor - 1,
                 agency_ticket=make_agency_ticket(trip_id, ticket_number, name, scope) if trip_id else None)
            for name, scope, ticket_number in entries]


def _invoice_summary_boundary(lines: list[str], at: int) -> bool:
    """An explicit invoice heading and airfare amount end the named table."""
    cursor = at + 1
    if re.fullmatch(r"INVOICE", lines[at], re.I):
        if cursor >= len(lines) or not re.fullmatch(r"SUMMARY", lines[cursor], re.I):
            return False
        cursor += 1
    elif not re.fullmatch(r"INVOICE\s+SUMMARY", lines[at], re.I):
        return False
    if cursor >= len(lines):
        return False
    amount = r"\$\d[\d,]*\.\d{2}"
    return bool(re.fullmatch(r"Airfare\s*\|\s*" + amount, lines[cursor], re.I)
                or (re.fullmatch(r"Airfare", lines[cursor], re.I)
                    and cursor + 1 < len(lines) and re.fullmatch(amount, lines[cursor + 1])))


def _text_evidence(text: str, source: str, flights: list) -> list[dict]:
    roster_boundaries = getattr(text, "roster_boundaries", frozenset())
    lines = [re.sub(r"\s+", " ", line).strip(" *\t") for line in text.splitlines() if line.strip()]
    # A primary and its explicitly attached airline/agency alias describe one
    # booking, not two competing traveler scopes. Never join unrelated primary
    # bookings merely because their references occur in the same email.
    reference_owners: dict[str, set[str]] = {}
    for flight in flights:
        primary = str(flight.pnr or "").upper()
        if not primary:
            continue
        for code in [primary, *(getattr(flight, "pnr_aliases", []) or [])]:
            reference_owners.setdefault(str(code).upper(), set()).add(primary)
    markers = []
    for field in extract_reference_fields("\n".join(lines)):
        owners = reference_owners.get(field.code, set())
        canonical = next(iter(owners)) if len(owners) == 1 else field.code
        markers.append((field.line, canonical))
    pnrs = {pnr for _, pnr in markers}
    reference_lines = {index for index, _ in markers}
    blocks: list[dict] = []
    for index, line in enumerate(lines):
        ticket_travelers = _priceline_ticket_travelers(lines, index, flights)
        if ticket_travelers is not None:
            blocks.extend(ticket_travelers)
            continue
        card_travelers = _numbered_card_travelers(lines, index, flights, markers)
        if card_travelers is not None:
            blocks.extend(card_travelers)
            continue
        # An abbreviated section title is not a person's name. Only its
        # adjacent explicit NAME column opens a roster; descriptive sentences
        # such as "Passenger info is available" do not gain name authority.
        if re.match(r"^(?:passenger(?:\(s\)|s)?|travel(?:l?er)(?:\(s\)|s)?|guests?)\s+info\b", line, re.I):
            if (not re.fullmatch(r"(?:passenger(?:\(s\)|s)?|travel(?:l?er)(?:\(s\)|s)?|guests?)\s+info\s*:?", line, re.I)
                    or index + 1 >= len(lines)
                    or not re.fullmatch(r"names?\s*:?", lines[index + 1], re.I)):
                continue
            line = re.sub(r"\binfo\b", "information", line, count=1, flags=re.I)
        match = _LABEL.match(line)
        if not match:
            continue
        # This add-on section title is not a roster or a pair of travelers.
        if re.fullmatch(r"passenger\s+options\s*&\s*extras\s+detail\s*:?", line, re.I):
            continue
        # Fare/baggage policy tables describe categories, not named manifests.
        if re.match(r"(?:passengers?|travel(?:l?er)s?)\s+(?:type|travel(?:l)?ing|confirmed|with|who|are)\b", line, re.I):
            continue
        # A wrapped seller-of-travel refund clause can start a MIME line with
        # "passenger". Its predicate is not a manifest label or a person.
        if re.match(r"passenger\s+otherwise\s+advises\s+the\s+travel\s+promoter\b", line, re.I):
            continue
        ticketed = _ticketed_traveler_details(lines, index, markers)
        if ticketed is not None:
            blocks.extend(ticketed)
            continue
        repeated = _traveler_detail_blocks(lines, index, markers)
        if repeated is not None:
            blocks.extend(repeated)
            continue
        raw = match.group("value").strip()
        table = _passenger_table(lines, index)
        # This wrapped carrier-liability clause describes travelers in general,
        # never a named manifest; no later offer heading belongs to its roster.
        if re.match(r"^passengers?\s+on\s+a\s+journey\s+involving\b",
                    " ".join(lines[index:index + 3]), re.I):
            continue
        names = table[0] if table is not None else (_names(raw) if raw else [])
        if re.match(r"passenger\s+(?:notices|rights|service charge|facility charge)\b", line, re.I):
            continue
        complete = table[1] if table is not None else not (names and any(not _name(part) for part in raw.split(";") if part.strip()))
        end = table[2] if table is not None else index
        # An explicit header may be followed by column labels before names.
        for follow in range(index + 1, min(len(lines), index + 40)):
            if table is not None:
                break
            if follow in roster_boundaries:
                break
            current = lines[follow]
            if not names and re.fullmatch(r"Subtotal\s*:\s*[$£€]?\d[\d,.]*", current, re.I):
                continue
            # These are metadata *inside* a passenger list, never evidence of
            # a person. Stop at every other section boundary as before.
            if names and re.fullmatch(r"Seat\s*:[^|\n]{0,30}\s+Class\s*:[^|\n]{1,40}", current, re.I):
                continue
            if names and re.match(r"Not a FRONTIER Miles(?:\s*(?:sm|®|™))?\s+Member\?", current, re.I):
                continue
            if names and re.fullmatch(r"BUNDLE\s+IT\s*\|?", current, re.I):
                break
            if (names and re.fullmatch(r"Passenger\s+Name(?:\s*\|\s*Seats\s*\|\s*Bags\s*\|\s*Special\s+Services)?", line, re.I)
                    and _invoice_summary_boundary(lines, follow)):
                break
            if names and re.match(r"(?:<?https?://|<\[link\])", current, re.I):
                continue
            if (names and re.fullmatch(r"Passengers\s*:?", line, re.I)
                    and re.match(r"Emirates\s+Skywards\b", current, re.I)):
                complete = complete and _emirates_loyalty_footer(lines, follow)
                break
            if (_LABEL.match(current) or _BOUNDARY.match(current) or follow in reference_lines
                    or re.fullmatch(r"(?:[A-Z][A-Z '&.-]*\s+)?itinerary\s+(?:number|id)\s*[:#]?", current, re.I)):
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
                 scope=block["scope"], scope_ambiguous=block["ambiguous"],
                 **({"issued_ticket_key":block["issued_ticket_keys"][name], "issued_ticket_version":1}
                    if block.get("issued_ticket_keys", {}).get(name) else {}),
                 **({"agency_ticket":block["agency_ticket"]} if block.get("agency_ticket") else {}))
            for block in blocks for name in block["names"]]
    return labeled + _fare_ticket_evidence(lines, source, flights)


def _issued_ticket_key(number: str) -> str | None:
    if not re.fullmatch(r"\d{13}", number) or not int(number[:3]) or not int(number[3:]):
        return None
    return sha256(("named-issued-ticket:v1:" + number).encode("ascii")).hexdigest()


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
    source_pnrs = {field.code for field in extract_reference_fields("\n".join(lines))}
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
        exact_tickets: list[str] = []
        ticket_fields_complete = True
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
            keys = {_issued_ticket_key(number) for number in exact_tickets}
            evidence.append(dict(name=person,
                source=source + ("_fare_ticket_holder" if tickets else "_named_fare_holder"),
                role="traveler", complete=True, scope=scope,
                scope_ambiguous=multiple and not combined, ticket_count=len(tickets),
                **({"issued_ticket_key":next(iter(keys)), "issued_ticket_version":1}
                   if len(pnrs) == 1 and source_pnrs == pnrs and ticket_fields_complete
                   and len(keys) == 1 and None not in keys
                   and set(tickets) == set(exact_tickets) else {})))

        for line in lines[start + 1:start + 60]:
            if re.match(r"(?:payment|card payment|travel credits|total|airline fare rules|helpful links)\b", line, re.I):
                break
            name = _name(line)
            if name and len(_tokens(name)) >= 2:
                flush()
                person, tickets, exact_tickets, fare, taxes, ticket_fields_complete = name, [], [], False, False, True
                continue
            if not person:
                continue
            if re.search(r"\bticket\s*(?:#|number|no\.)", line, re.I):
                tickets.extend(re.findall(r"\b\d{13}\b", line))
                exact = re.fullmatch(r"(?:e)?Ticket\s*(?:#\s*:?|number\s*:?|no\.\s*:?)\s*(\d{13})", line, re.I)
                if exact:
                    exact_tickets.append(exact[1])
                else:
                    ticket_fields_complete = False
            if re.match(r"Base Fare\s*:", line, re.I) and re.search(r"\d[.,]\d{2}", line):
                fare = True
            if re.match(r"Taxes (?:and|&) Fees\s*:", line, re.I) and re.search(r"\d[.,]\d{2}", line):
                taxes = True
        flush()
    duplicate_keys = {item["issued_ticket_key"] for item in evidence if item.get("issued_ticket_key")
        and len({other["name"].casefold() for other in evidence
                 if other.get("issued_ticket_key") == item["issued_ticket_key"]}) > 1}
    for item in evidence:
        if item.get("issued_ticket_key") in duplicate_keys:
            item.pop("issued_ticket_key", None)
            item.pop("issued_ticket_version", None)
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
    if scope.get("journey_scope"):
        leg = getattr(flight, "source_leg", {}) or {}
        if (getattr(flight, "source", None) != "shape_priceline_trip_cards"
                or leg.get("template") != "priceline_trip_cards" or leg.get("ambiguous") is not False
                or leg.get("journey_scope") != scope["journey_scope"]):
            return False
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
        _html_itinerary_passengers(html, flights),
    )
    candidates = identity_candidates(user_name, aliases)
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
        if getattr(flight, "source", None) == "shape_priceline_trip_cards":
            from .agency_ticket_evidence import agency_source_proof_key
            # Issued-ticket scope is separate from a guessed PNR. Attach only a
            # unique, complete, exact named SELF ticket; conflicting people or
            # multiple tickets cannot authorize later schedule replacement.
            leg = dict(getattr(flight, "source_leg", {}) or {})
            leg.pop("agency_ticket", None)
            all_proofs = [item["agency_ticket"] for item in applicable
                          if item.get("complete") and isinstance(item.get("agency_ticket"), dict)]
            proofs = {}
            if flight.ownership == "self":
                for item in applicable:
                    proof = item.get("agency_ticket")
                    if (not item.get("complete") or not isinstance(proof, dict)
                            or not any(full_names_match(item["name"], candidate) for candidate in candidates)):
                        continue
                    conflicts = [other for other in all_proofs
                        if all(other.get(key) == proof.get(key) for key in ("provider", "document_key", "ticket_key", "journey_scope"))
                        and other.get("traveler_key") != proof.get("traveler_key")]
                    if not conflicts:
                        proofs[proof["identity_key"]] = proof
            if len(proofs) == 1 and re.fullmatch(r"[a-f0-9]{64}", str(leg.get("key") or "")):
                proof = dict(next(iter(proofs.values())))
                proof["source_proof_key"] = agency_source_proof_key(proof["identity_key"], leg["key"])
                leg["agency_ticket"] = proof
            flight.source_leg = leg
