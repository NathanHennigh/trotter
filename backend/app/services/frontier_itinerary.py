"""Read explicitly numbered Frontier connection cards without summary flights.

None means another layout may apply. An empty list holds a recognized but
incomplete/contradictory multi-flight document rather than guessing its legs.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import re

from .booking_references import extract_reference_fields
from .flight_times import _endpoint


_HEADER = re.compile(r"\b(?:DEPARTING|RETURNING)\s+FLIGHT\s+(\d{1,4}(?:\s*(?:&|and|,)\s*\d{1,4})*)\b", re.I)
_MULTI = re.compile(r"\b(?:DEPARTING|RETURNING)\s+FLIGHT\s+\d{1,4}\s*(?:&|and|,)", re.I)
_DATE = r"\d{1,2}/\d{1,2}/\d{4}"
_CLOCK = r"\d{1,2}:[0-5]\d\s*[AP]M"
_SCHEDULE = rf"Depart:\s*({_DATE})\s+({_CLOCK})\s*\|\s*Arrive:\s*({_DATE})\s+({_CLOCK})"
_SUMMARY = re.compile(rf"^(.{{1,100}}?)\(([A-Z]{{3}})\)\s+to\s+(.{{1,100}}?)\(([A-Z]{{3}})\)\s+{_SCHEDULE}", re.I)
_LEG = re.compile(rf"\b([A-Z]{{3}})\s+to\s+([A-Z]{{3}})\s+{_SCHEDULE}", re.I)
_TOTAL = re.compile(r"\bTotal\s+Duration:\s*(\d{1,2})\s*hr(?:s)?\s*(\d{1,2})\s*min\b", re.I)
_LAYOVER = re.compile(r"\bLayover:\s*(\d{1,2})\s*hr(?:s)?\s*(\d{1,2})\s*min\b", re.I)
_STOP = re.compile(r"\b1\s+Stop\s*-\s*.{1,100}?\(([A-Z]{3})\)", re.I)
_END = re.compile(r"\b(?:PASSENGERS|Receipt\s+and\s+Payment|BUNDLE\s+IT|SERVICES)\b", re.I)


def _time(day, clock):
    try:
        return datetime.strptime(day + ' ' + re.sub(r'\s+', '', clock.upper()), '%m/%d/%Y %I:%M%p').replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _duration(match):
    if match is None:
        return None
    hours, minutes = map(int, match.groups())
    return hours * 60 + minutes if minutes < 60 and 0 < hours * 60 + minutes <= 48 * 60 else None


def _dated_leg(dep, arr, values):
    dep_time, arr_time = _time(values[0], values[1]), _time(values[2], values[3])
    if not dep_time or not arr_time or dep == arr:
        return None
    departure, _, dep_error = _endpoint(dep_time, dep, 'airport_local')
    arrival, _, arr_error = _endpoint(arr_time, arr, 'airport_local')
    if dep_error or arr_error or not departure < arrival or (arrival - departure).total_seconds() > 24 * 3600:
        return None
    return {'dep_airport': dep, 'arr_airport': arr, 'dep_time': dep_time, 'arr_time': arr_time,
            'departure_utc': departure, 'arrival_utc': arrival}


def extract_frontier_connection_cards(text: str) -> list[dict] | None:
    """Use one lossless visible alternative, with no received-date inference."""
    compact = re.sub(r'\s+', ' ', text or '').strip()
    if not re.search(r'\bFrontier\b', compact, re.I) or not _MULTI.search(compact):
        return None
    if len(compact) > 200_000:
        return []
    references = {field.code for field in extract_reference_fields(text)}
    if len(references) != 1:
        return []
    pnr = references.pop()
    headers = list(_HEADER.finditer(compact))
    if not headers or len(headers) > 8:
        return []
    output = []
    for sequence, header in enumerate(headers):
        card = compact[header.end():headers[sequence + 1].start() if sequence + 1 < len(headers) else len(compact)].strip()
        end = _END.search(card)
        if end:
            card = card[:end.start()].strip()
        numbers = re.findall(r'\d{1,4}', header.group(1))
        if len(numbers) not in (1, 2) or len(set(numbers)) != len(numbers) or any(int(n) == 0 for n in numbers):
            return []
        summary = _SUMMARY.match(card)
        if not summary:
            return []
        summary_leg = _dated_leg(summary[2].upper(), summary[4].upper(), summary.groups()[4:])
        totals = list(_TOTAL.finditer(card))
        if len(totals) != 1:
            return []
        total = _duration(totals[0])
        if not summary_leg or total is None:
            return []
        summary_elapsed = (summary_leg['arrival_utc'] - summary_leg['departure_utc']).total_seconds() / 60
        if summary_elapsed != total:
            return []
        if len(numbers) == 1:
            if _STOP.search(card) or _LEG.search(card[summary.end():]):
                return []
            legs = [summary_leg]
            layover = None
        else:
            details = list(_LEG.finditer(card[summary.end():]))
            stops, layovers = list(_STOP.finditer(card)), list(_LAYOVER.finditer(card))
            if len(details) != 2 or len(stops) != 1 or len(layovers) != 1:
                return []
            stop, layover = stops[0], _duration(layovers[0])
            if layover is None:
                return []
            legs = [_dated_leg(m[1].upper(), m[2].upper(), m.groups()[2:]) for m in details]
            if not all(legs):
                return []
            first, second = legs
            if (first['dep_airport'] != summary_leg['dep_airport'] or second['arr_airport'] != summary_leg['arr_airport']
                    or first['arr_airport'] != second['dep_airport'] or first['arr_airport'] != stop[1].upper()
                    or first['departure_utc'] != summary_leg['departure_utc'] or second['arrival_utc'] != summary_leg['arrival_utc']
                    or (second['departure_utc'] - first['arrival_utc']).total_seconds() != layover * 60):
                return []
        raw_card_key = sha256((header.group(0) + '\n' + card).encode()).hexdigest()
        for position, leg in enumerate(legs):
            proof = {'kind': 'frontier_explicit_numbered_connection', 'status': 'verified',
                'summary_route': [summary_leg['dep_airport'], summary_leg['arr_airport']],
                'summary_departure_local': summary_leg['dep_time'].isoformat(),
                'summary_arrival_local': summary_leg['arr_time'].isoformat(),
                'printed_total_minutes': total, 'printed_layover_minutes': layover,
                'flight_numbers': ['F9' + str(int(n)) for n in numbers], 'leg_sequence': position + 1,
                'leg_count': len(legs), 'printed_departure_date': leg['dep_time'].date().isoformat(),
                'printed_arrival_date': leg['arr_time'].date().isoformat(),
                'printed_legs': [{'flight_number': 'F9' + str(int(numbers[i])),
                    'dep_airport': value['dep_airport'], 'arr_airport': value['arr_airport'],
                    'departure_local': value['dep_time'].isoformat(), 'arrival_local': value['arr_time'].isoformat()}
                    for i, value in enumerate(legs)]}
            output.append({**{k:v for k,v in leg.items() if not k.endswith('_utc')},
                'airline': 'F9', 'flight_number': 'F9' + str(int(numbers[position])), 'pnr': pnr,
                'source': 'shape_frontier_numbered_connection_cards',
                'time_provenance': {'date_evidence': proof},
                'source_leg': {'version': 1, 'template': 'frontier_numbered_connection_cards',
                    'sequence': position + 1, 'key': sha256(f'{raw_card_key}:{position + 1}'.encode()).hexdigest(),
                    'ambiguous': False, 'document_card_key': raw_card_key, 'connection_itinerary': proof,
                    'booking_references': {'primary': pnr, 'aliases': []}}})
    return output
