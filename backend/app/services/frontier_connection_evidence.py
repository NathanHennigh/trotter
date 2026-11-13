"""Validate a same-original summary interpretation before correcting its leg.

This never matches another document, passenger, booking, or an unlinked legacy
row. The caller retains all existing projection protections after this proof.
"""
from __future__ import annotations

from datetime import datetime
from hashlib import sha256
import re

from .flight_times import _endpoint


_CODE = re.compile(r'^[A-Z]{3}$')
_NUMBER = re.compile(r'^F9[1-9]\d{0,3}$')
_KEY = re.compile(r'^[0-9a-f]{64}$')


def _wall(value):
    # The parser's local-wall convention is explicit +00:00 tagging; this is
    # not a UTC instant or permission to reinterpret an arbitrary offset.
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:00\+00:00', value):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.second == parsed.microsecond == 0 else None


def _consistent_row(row, facts):
    """Require the immutable indexed scope and its recorded facts to agree."""
    provenance = facts.get('time_provenance')
    return (isinstance(provenance, dict)
        and all(facts.get(key) == getattr(row, key, None)
                for key in ('dep_airport', 'arr_airport', 'flight_number', 'pnr', 'ownership'))
        and facts.get('airline') == 'F9'
        and isinstance(row.travel_date, str)
        and row.travel_date == provenance.get('departure_local_date'))


def _leg(value):
    if not isinstance(value, dict):
        return None
    dep, arr = value.get('dep_airport'), value.get('arr_airport')
    number = value.get('flight_number')
    if not all(isinstance(v, str) for v in (dep, arr, number)) or not _CODE.fullmatch(dep) or not _CODE.fullmatch(arr) or not _NUMBER.fullmatch(number) or dep == arr:
        return None
    departure, arrival = _wall(value.get('departure_local')), _wall(value.get('arrival_local'))
    if not departure or not arrival:
        return None
    start, _, start_error = _endpoint(departure, dep, 'airport_local')
    end, _, end_error = _endpoint(arrival, arr, 'airport_local')
    if start_error or end_error or not start < end or (end - start).total_seconds() > 24 * 3600:
        return None
    return dep, arr, number, start, end


def summary_schedule(current, *, allow_sibling=False):
    """Return the exact old aggregate schedule only for a proven first card."""
    from .booking_ledger import booking_code, event_time
    facts = current.facts if isinstance(current.facts, dict) else {}
    pointer = facts.get('source_leg') or {}
    provenance = facts.get('time_provenance') or {}
    if (facts.get('source') != 'shape_frontier_numbered_connection_cards'
            or not isinstance(pointer, dict) or type(pointer.get('version')) is not int or pointer['version'] != 1
            or pointer.get('ambiguous') is not False
            or pointer.get('template') != 'frontier_numbered_connection_cards'
            or type(pointer.get('sequence')) is not int or pointer['sequence'] not in ((1, 2) if allow_sibling else (1,))
            or not isinstance(provenance, dict) or provenance.get('status') != 'normalized' or facts.get('force_review')
            or facts.get('pnr_aliases') or pointer.get('booking_references') != {'primary': current.pnr, 'aliases': []}
            or not booking_code(current.pnr) or not _consistent_row(current, facts)):
        return None
    card_key = pointer.get('document_card_key')
    if not isinstance(card_key, str) or not _KEY.fullmatch(card_key) or pointer.get('key') != sha256(f"{card_key}:{pointer['sequence']}".encode()).hexdigest():
        return None
    proof = pointer.get('connection_itinerary')
    if not isinstance(proof, dict) or provenance.get('date_evidence') != proof:
        return None
    if (proof.get('kind') != 'frontier_explicit_numbered_connection' or proof.get('status') != 'verified'
            or type(proof.get('leg_count')) is not int or proof['leg_count'] != 2
            or type(proof.get('leg_sequence')) is not int or proof['leg_sequence'] != pointer['sequence']):
        return None
    printed = proof.get('printed_legs')
    if not isinstance(printed, list) or len(printed) != 2:
        return None
    first, second = (_leg(value) for value in printed)
    if not first or not second or first[1] != second[0] or first[2] == second[2]:
        return None
    position = pointer['sequence'] - 1
    if (proof.get('printed_departure_date') != printed[position]['departure_local'][:10]
            or proof.get('printed_arrival_date') != printed[position]['arrival_local'][:10]
            or provenance.get('departure_local_date') != proof['printed_departure_date']):
        return None
    total, gap = proof.get('printed_total_minutes'), proof.get('printed_layover_minutes')
    if (type(total) is not int or type(gap) is not int or not 0 < total <= 48 * 60 or not 0 < gap < total
            or proof.get('flight_numbers') != [first[2], second[2]]
            or proof.get('summary_route') != [first[0], second[1]]
            or (second[3] - first[4]).total_seconds() != gap * 60
            or (second[4] - first[3]).total_seconds() != total * 60):
        return None
    summary = _leg({'dep_airport': first[0], 'arr_airport': second[1], 'flight_number': first[2],
        'departure_local': proof.get('summary_departure_local'), 'arrival_local': proof.get('summary_arrival_local')})
    if not summary or summary[3] != first[3] or summary[4] != second[4]:
        return None
    interpreted = (current.dep_airport, current.arr_airport, current.flight_number,
        event_time(facts.get('dep_time')), event_time(facts.get('arr_time')))
    selected = (first, second)[position]
    if interpreted != (*selected[:3], event_time(selected[3]), event_time(selected[4])):
        return None
    return (*summary[:3], event_time(summary[3]), event_time(summary[4]))


def same_original_summary_rows(current, rows, names):
    """Select only immutable, named old observations of this exact summary."""
    from .booking_ledger import booking_code, event_time
    from .booking_reconciliation import ambiguous, matches, original_source
    def complete_names(row):
        entries = matches(row, names)
        # Duplicate presentations may include an unfinished roster as well as
        # a complete exact-name entry. This proves only the existing owner.
        return any(entry.get('complete') is True for entry in entries)
    expected = summary_schedule(current)
    if (not expected or current.ownership != 'self' or ambiguous(current) or not complete_names(current)
            or not original_source(current) or not event_time(current.source_event_at)):
        return []
    result = []
    for row in rows:
        facts = row.facts if isinstance(row.facts, dict) else {}
        if (row.id == current.id or row.user_id != current.user_id or row.source_message_id != current.source_message_id
                or event_time(row.source_event_at) != event_time(current.source_event_at)
                or booking_code(row.pnr) != booking_code(current.pnr)
                or row.ownership != 'self' or ambiguous(row) or not complete_names(row) or not original_source(row)
                or facts.get('source_leg') or facts.get('force_review') or facts.get('pnr_aliases')
                or not _consistent_row(row, facts)
                or facts['time_provenance'].get('status') != 'normalized'):
            continue
        schedule = (row.dep_airport, row.arr_airport, row.flight_number,
            event_time(facts.get('dep_time')), event_time(facts.get('arr_time')))
        if schedule == expected:
            result.append(row)
    return result
