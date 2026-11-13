"""Read a complete, dated Priceline trip-card document without date guesses.

The caller supplies one lossless visible MIME alternative and its airline name
catalog. ``None`` permits another layout; ``[]`` holds a recognized document.
Clocks returned here retain the parser's airport-local, UTC-tagged convention.
"""
from __future__ import annotations

import hashlib
import html
import re
from collections.abc import Mapping
from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache

from .flight_times import _endpoint, _zone


_WEEKDAYS = {name: i for i, name in enumerate(("mon", "tue", "wed", "thu", "fri", "sat", "sun"))}
_MONTHS = {name: i + 1 for i, name in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"))}
_DAY = r"(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*"
_MONTH = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*"
_FULL_DATE = rf"({_DAY}),?\s+({_MONTH})\s+(\d{{1,2}}),?\s+(\d{{4}})"
_RANGE = re.compile(rf"^{_FULL_DATE}\s*-\s*{_FULL_DATE}$", re.I)
_SECTION = re.compile(rf"^({_DAY}),?\s+({_MONTH})\s+(\d{{1,2}})(?:\s+[A-Za-z ,./()|-]+(?:[1-9]\d?\s+one[- ]way\s+tickets?(?:\(s\))?)?)?$", re.I)
_CLOCK = r"(\d{1,2}:[0-5]\d\s*[AP]M)"
_CLOCKS = re.compile(rf"^{_CLOCK}\s*-\s*{_CLOCK}$", re.I)
_FLIGHT = re.compile(r"^([A-Za-z][A-Za-z .&'-]+)\s+Flight\s+(\d{1,4}[A-Z]?)$", re.I)
_DURATION = re.compile(r"^(\d{1,2})h\s*(\d{1,2})m(?:,\s*[\d,]+\s+miles)?$", re.I)
_LAYOVER = re.compile(r"^(\d{1,2})h\s*(\d{1,2})m\s+layover\s+in\s+\S.*$", re.I)
_STOP = re.compile(r"^(?:This itinerary departs|Important Information|Summary of Charges)\b", re.I)
_TRIP_LABEL = re.compile(r"\bPriceline\s+Trip\s+Number\s*:", re.I)
_CONFIRMATION = re.compile(r"\bYour\s+Flight\s+Confirmation\b", re.I)


@lru_cache(maxsize=1)
def _airport_cities():
    import airportsdata
    return {code: re.sub(r"\s+", " ", row.get("city", "")).strip().casefold()
            for code, row in airportsdata.load("IATA").items()}


def _lines(text: str) -> list[str]:
    text = html.unescape(text).replace("\xa0", " ")
    text = text.translate(str.maketrans({"–": "-", "—": "-", "−": "-"}))
    result = []
    for raw in text.splitlines():
        value = re.sub(r"^[>\s]+", "", raw).strip().strip("*|").strip()
        value = re.sub(r"\s+", " ", value)
        if value and not re.match(r"^<?https?://", value, re.I):
            result.append(value)
    # Responsive HTML can put the two complete dates and separator in three
    # adjacent text nodes. Join only that exact structure, never nearby dates.
    joined = []
    index = 0
    while index < len(result):
        if (index + 2 < len(result) and re.fullmatch(_FULL_DATE, result[index], re.I)
                and result[index + 1] == "-" and re.fullmatch(_FULL_DATE, result[index + 2], re.I)):
            joined.append(" ".join(result[index:index + 3]))
            index += 3
        else:
            joined.append(result[index])
            index += 1
    return joined


def _printed_date(parts) -> date | None:
    weekday, month, day, year = parts
    try:
        value = date(int(year), _MONTHS[month[:3].lower()], int(day))
    except (ValueError, KeyError):
        return None
    return value if value.weekday() == _WEEKDAYS.get(weekday[:3].lower()) else None


def _clock(value: str) -> time | None:
    try:
        return datetime.strptime(re.sub(r"\s+", "", value.upper()), "%I:%M%p").time()
    except ValueError:
        return None


def _minutes(match) -> int | None:
    if match is None:
        return None
    hours, minutes = (int(value) for value in match.groups())
    total = hours * 60 + minutes
    return total if minutes < 60 and 0 < total <= 48 * 60 else None


def _airport(lines: list[str], label: str) -> str | None:
    matches = []
    for index, value in enumerate(lines):
        match = re.fullmatch(rf"{label}:\s*(.*)", value, re.I)
        if not match:
            continue
        field = match[1] or (lines[index + 1] if index + 1 < len(lines) else "")
        codes = re.findall(r"\(([A-Z]{3})\)", field)
        matches.append(codes[0] if len(codes) == 1 else None)
    return matches[0] if len(matches) == 1 else None


def _cards(lines: list[str], anchor: date, airline_codes: Mapping[str, str]):
    starts = [i for i, value in enumerate(lines) if _CLOCKS.fullmatch(value)]
    flight_count = sum(bool(re.search(r"\bFlight\s+\d", value, re.I)) for value in lines)
    if not starts or len(starts) != flight_count or len(starts) > 12:
        return None
    result = []
    previous = None
    for number, start in enumerate(starts):
        card = lines[start:starts[number + 1] if number + 1 < len(starts) else len(lines)]
        flights = [match for value in card if (match := _FLIGHT.fullmatch(value))]
        durations = [match for value in card if (match := _DURATION.fullmatch(value))]
        layovers = [match for value in card if (match := _LAYOVER.fullmatch(value))]
        if len(flights) != 1 or len(durations) != 1 or len(layovers) > 1:
            return None
        # A malformed duration/layover must not disappear beside a valid line.
        if sum(bool(re.search(r"\blayover\b", value, re.I)) for value in card) != len(layovers):
            return None
        carrier = airline_codes.get(flights[0][1].strip().lower())
        dep_airport, arr_airport = _airport(card, "Depart"), _airport(card, "Arrive")
        elapsed = _minutes(durations[0])
        layover = _minutes(layovers[0]) if layovers else None
        layover_place = (re.split(r"\blayover\s+in\s+", layovers[0][0], flags=re.I)[1]
                         if layovers else None)
        clocks = _CLOCKS.fullmatch(card[0])
        dep_clock, arr_clock = _clock(clocks[1]), _clock(clocks[2])
        if (not carrier or not re.fullmatch(r"[A-Z0-9]{2}", carrier) or not elapsed
                or not dep_airport or not arr_airport or dep_airport == arr_airport
                or not dep_clock or not arr_clock or (layovers and layover is None)):
            return None
        dep_zone, arr_zone = _zone(dep_airport), _zone(arr_airport)
        if dep_zone is None or arr_zone is None:
            return None
        if layover_place and layover_place.casefold() != _airport_cities().get(arr_airport):
            return None
        if previous is None:
            departure_local = datetime.combine(anchor, dep_clock, timezone.utc)
        else:
            if previous["arr_airport"] != dep_airport or previous["layover_minutes"] is None:
                return None
            expected = previous["arrival_utc"] + timedelta(minutes=previous["layover_minutes"])
            departure_local = expected.astimezone(dep_zone).replace(tzinfo=timezone.utc)
            if departure_local.time() != dep_clock:
                return None
        departure, _, dep_error = _endpoint(departure_local, dep_airport, "airport_local")
        if dep_error:
            return None
        arrival = departure + timedelta(minutes=elapsed)
        arrival_local = arrival.astimezone(arr_zone).replace(tzinfo=timezone.utc)
        arrival_check, _, arr_error = _endpoint(arrival_local, arr_airport, "airport_local")
        day_offset = (arrival_local.date() - departure_local.date()).days
        overnight = sum(value.lower() == "overnight flight" for value in card)
        if (arr_error or arrival_check != arrival or arrival_local.time() != arr_clock
                or day_offset not in (-1, 0, 1, 2) or overnight > 1
                or (overnight and day_offset != 1)):
            return None
        if number == len(starts) - 1 and layover is not None:
            return None
        item = {"dep_airport": dep_airport, "arr_airport": arr_airport,
                "dep_time": departure_local, "arr_time": arrival_local,
                "airline": carrier, "flight_number": carrier + flights[0][2].upper(),
                "duration_minutes": elapsed, "layover_minutes": layover,
                "preceding_layover_minutes": previous["layover_minutes"] if previous else None,
                "arrival_utc": arrival, "departure_utc": departure,
                "overnight_marker": bool(overnight), "raw_card": "\n".join(card),
                "layover_place": layover_place}
        result.append(item)
        previous = item
    return result


def has_priceline_flight_itinerary(text: str) -> bool:
    """Recognize dated flight cards for review even if their dates conflict.

    This lightweight gate grants no parsing, passenger or projection authority.
    It can run on a single cleaned visible HTML alternative before loose scoring.
    """
    lines = _lines(text)
    return bool(_TRIP_LABEL.search("\n".join(lines))
                and any(_RANGE.fullmatch(value) for value in lines)
                and any(_CLOCKS.fullmatch(value) for value in lines)
                and any(_FLIGHT.fullmatch(value) for value in lines))


def extract_priceline_itinerary(text: str, *, airline_codes: Mapping[str, str]) -> list[dict] | None:
    """Return only cards proved by explicit dates, elapsed times and connections.

    Recognition is intentionally separate from success: malformed known cards
    cannot escape into a loose date/route cross-product parser.
    """
    lines = _lines(text)
    joined = "\n".join(lines)
    if not _TRIP_LABEL.search(joined):
        return None
    ranges = [(i, match) for i, value in enumerate(lines) if (match := _RANGE.fullmatch(value))]
    # Some reminder versions omit the confirmation title. Their complete date
    # range and numbered clock cards still identify this exact document family.
    has_cards = (any(_FLIGHT.fullmatch(value) for value in lines)
                 and (any(_CLOCKS.fullmatch(value) for value in lines)
                      or (any(re.match(r"Depart:", value, re.I) for value in lines)
                          and any(re.match(r"Arrive:", value, re.I) for value in lines))))
    if not (_CONFIRMATION.search(joined) or (ranges and has_cards)):
        return None
    if len(ranges) != 1:
        return []
    range_index, match = ranges[0]
    start_date, end_date = _printed_date(match.groups()[:4]), _printed_date(match.groups()[4:])
    if not start_date or not end_date or not 0 <= (end_date - start_date).days <= 366:
        return []
    end_index = next((i for i in range(range_index + 1, len(lines)) if _STOP.match(lines[i])), len(lines))
    region = lines[range_index + 1:end_index]
    expected_dates = [start_date] if start_date == end_date else [start_date, end_date]
    sections = []
    for i, value in enumerate(region):
        heading = _SECTION.fullmatch(value)
        if not heading:
            continue
        choices = [day for day in expected_dates
                   if _printed_date((*heading.groups(), str(day.year))) == day]
        if len(choices) != 1:
            return []
        if sections and i == sections[-1]["last_heading"] + 1 and choices[0] == sections[-1]["date"]:
            sections[-1]["last_heading"] = i
        else:
            sections.append({"start": i, "last_heading": i, "date": choices[0]})
    if [section["date"] for section in sections] != expected_dates:
        return []
    if any(re.search(r"\bFlight\s+\d", value, re.I) for value in region[:sections[0]["start"]]):
        return []
    result = []
    last_arrival = None
    for index, section in enumerate(sections):
        stop = sections[index + 1]["start"] if index + 1 < len(sections) else len(region)
        cards = _cards(region[section["last_heading"] + 1:stop], section["date"], airline_codes)
        if not cards or (last_arrival and cards[0]["departure_utc"] <= last_arrival):
            return []
        scope = {"dep_airport": cards[0]["dep_airport"], "arr_airport": cards[-1]["arr_airport"],
                 "departure_date": section["date"].isoformat()}
        for leg_index, card in enumerate(cards):
            proof = {"kind": "priceline_printed_duration_and_connection", "status": "verified",
                     "document_date_range": [start_date.isoformat(), end_date.isoformat()],
                     "section_departure_date": section["date"].isoformat(),
                     "departure_date": card["dep_time"].date().isoformat(),
                     "arrival_date": card["arr_time"].date().isoformat(),
                     "printed_duration_minutes": card["duration_minutes"],
                     "preceding_printed_layover_minutes": card["preceding_layover_minutes"],
                     "printed_departure_clock": card["dep_time"].strftime("%H:%M"),
                     "printed_arrival_clock": card["arr_time"].strftime("%H:%M"),
                     "following_printed_layover_place": card["layover_place"],
                     "overnight_marker": card["overnight_marker"]}
            # Document identity is raw source-bound, independent of the dates,
            # route or clock interpretation produced by this parser version.
            key = "\n".join([lines[range_index], region[section["start"]], card["raw_card"]])
            result.append({**{name: card[name] for name in ("dep_airport", "arr_airport", "dep_time", "arr_time", "airline", "flight_number")},
                           "pnr": None, "pnr_aliases": [], "source": "shape_priceline_trip_cards",
                           "time_provenance": {"date_evidence": proof},
                           "source_leg": {"version": 1, "template": "priceline_trip_cards", "sequence": len(result) + 1,
                                          "journey_leg_sequence": leg_index + 1, "journey_leg_count": len(cards),
                                          "key": hashlib.sha256(key.encode()).hexdigest(), "ambiguous": False,
                                          "journey_scope": dict(scope), "date_proof": dict(proof)}})
        last_arrival = cards[-1]["arrival_utc"]
    return result
