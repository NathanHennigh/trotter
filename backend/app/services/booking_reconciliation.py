"""Conservative evidence joins. Missing names never erase affirmative evidence.

Hashes identify facts; they do not establish chronology. A join is limited to
one account, explicitly linked booking references, route, flight and local day.
"""
from __future__ import annotations

from dataclasses import dataclass
from copy import deepcopy

from .booking_ledger import booking_code, event_time
from .passenger_identity import full_names_match


def original_source(row):
    facts = row.facts or {}
    return not facts.get('user_decision') and facts.get('source') not in {
        'user_review', 'travel_name_recovery', 'booking_repair_reconciliation', 'flight_share', 'accepted_flight_share'}


def observation_codes(row):
    return {code for code in [booking_code(row.pnr),
        *(booking_code(value) for value in (row.facts or {}).get('pnr_aliases') or [])] if code}


def local_day(row):
    return ((row.facts or {}).get('time_provenance') or {}).get('departure_local_date') or row.travel_date


def flight_key(row):
    return (local_day(row), booking_code(row.dep_airport), booking_code(row.arr_airport),
            ''.join(str(row.flight_number or '').split()).upper())


def evidence(row):
    value = (row.facts or {}).get('passenger_evidence') or []
    return [value] if isinstance(value, dict) else value if isinstance(value, list) else []


def matches(row, names):
    return [entry for entry in evidence(row) if isinstance(entry, dict)
            and entry.get('role') == 'traveler' and entry.get('applies') is True
            and not entry.get('scope_ambiguous')
            and any(full_names_match(entry.get('name'), name) for name in names)]


def ambiguous(row):
    return bool((row.facts or {}).get('force_review')) or any(isinstance(entry, dict)
        and entry.get('role') == 'traveler' and entry.get('scope_ambiguous') for entry in evidence(row))


def event_bounds(row):
    stamp = event_time(row.source_event_at)
    if stamp:
        return stamp, stamp
    provenance = (row.facts or {}).get('source_time_provenance') or {}
    lower, upper = event_time(provenance.get('earliest')), event_time(provenance.get('latest'))
    return (lower, upper) if lower and upper and lower <= upper else (None, None)


def strictly_newer(left, right):
    low, _ = event_bounds(left)
    _, high = event_bounds(right)
    return bool(low and high and low > high)


def current_document_versions(rows):
    """A higher parser revision of the SAME original message replaces its parse,
    not the underlying message. Immutable previous observations remain stored.
    """
    versions = {}
    for row in rows:
        key = row.source_message_id or f'observation:{row.id}'
        versions[key] = max(versions.get(key, 0), int((row.facts or {}).get('parser_version') or 0))
    return [row for row in rows if int((row.facts or {}).get('parser_version') or 0)
            == versions[row.source_message_id or f'observation:{row.id}']]


def identical_schedule(left, right):
    return all(event_time((left.facts or {}).get(key)) == event_time((right.facts or {}).get(key))
               for key in ('dep_time', 'arr_time'))


@dataclass
class ResolvedEvidence:
    schedule: object | None = None
    passenger_evidence: list | None = None
    source_ids: list | None = None
    review_reason: str | None = None


def resolve_group(rows, names):
    """Choose schedule by real chronology; inherit names only across an unnamed
    identical booking leg. Newer explicit other/ambiguous evidence stays held.
    """
    rows = current_document_versions([row for row in rows if original_source(row)])
    if not rows:
        return ResolvedEvidence()
    tops = [row for row in rows if not any(strictly_newer(other, row) for other in rows)]
    if any(ambiguous(row) for row in tops):
        return ResolvedEvidence(review_reason='ambiguous_latest_evidence')
    if any(not identical_schedule(left, right) for left in tops for right in tops):
        return ResolvedEvidence(review_reason='unresolved_source_chronology')
    # Equal or unknown event times are harmless only when schedule facts agree.
    # Prefer normalized facts; id only chooses a representative of equal facts.
    schedule = max(tops, key=lambda row: (bool((row.facts or {}).get('time_provenance')), -row.id))
    matching = [(row, matches(row, names)) for row in rows if not ambiguous(row)]
    matching = [(row, entries) for row, entries in matching if entries]
    if not matching:
        return ResolvedEvidence()
    for row in tops:
        if matches(row, names):
            continue
        named = [entry for entry in evidence(row) if isinstance(entry, dict)
                 and entry.get('role') == 'traveler' and entry.get('applies') is True]
        if named or any(str(value or '').strip() for value in (row.facts or {}).get('passenger_names') or []):
            return ResolvedEvidence(review_reason='conflicting_latest_passenger')
    entries = [entry for _, group in matching for entry in group]
    if any(not full_names_match(left.get('name'), right.get('name')) for left in entries for right in entries):
        return ResolvedEvidence(review_reason='ambiguous_matching_names')
    merged = []
    for source, entries in matching:
        for entry in entries:
            proof = {**deepcopy(entry), 'source_observation_id': source.id}
            if proof not in merged:
                merged.append(proof)
    return ResolvedEvidence(schedule, merged, sorted({schedule.id, *(row.id for row, _ in matching)}))


def observation_groups(rows):
    """Connected components of explicit reference aliases, never fuzzy routes."""
    groups = []
    for row in rows:
        if not original_source(row):
            continue
        key, codes = flight_key(row), observation_codes(row)
        if not all(key) or not codes:
            groups.append([row]); continue
        matching = [group for group in groups if flight_key(group[0]) == key
                    and codes.intersection(set().union(*(observation_codes(item) for item in group)))]
        combined = [row]
        for group in matching:
            combined.extend(group); groups.remove(group)
        groups.append(combined)
    return groups
