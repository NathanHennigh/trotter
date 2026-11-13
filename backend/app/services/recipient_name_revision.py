"""Exact Southwest recipient name-change evidence and read projection.

This does not authorize itinerary retirement, account identity, a transfer of
shares, or mutation of any retained item. Raw ticket identifiers never leave
the extractor. The resolver returns a derived review/supersession inventory.
"""

from __future__ import annotations
from datetime import datetime
from itertools import combinations
from typing import Any, Iterable, Mapping, Sequence
import re
from .booking_ledger import event_time
from .southwest_ticket_revision import _key, _ticket_key

JsonObject = dict[str, Any]
SOURCE = "southwest_named_ticket_name_change"
HEADERS = ["PASSENGER", "RAPID REWARDS #", "TICKET #", "EST. POINTS EARNED"]


def _passenger_evidence(facts: Any) -> list[JsonObject]:
    """Malformed historical JSON cannot provide positive ticket authority."""
    if not isinstance(facts, Mapping):
        return []
    entries = facts.get("passenger_evidence")
    if not isinstance(entries, list):
        return []
    return [entry for entry in entries if isinstance(entry, dict)]


def _normalized_person(value: Any) -> tuple[str, ...] | None:
    if not isinstance(value, str):
        return None
    value = " ".join(value.split())
    # This positive authority intentionally excludes initials, punctuation,
    # family particles and alternate airline notation. Ordinary retention is
    # unaffected when this proof is unavailable.
    if not re.fullmatch(r"[A-Za-z]{2,}(?: [A-Za-z]{2,}){1,3}", value):
        return None
    parts = tuple(value.casefold().split())
    if set(parts) & {"de", "del", "da", "di", "la", "van", "von", "der", "bin", "al", "jr", "sr"}:
        return None
    return parts


def _compatible_name_revision(left: str, right: str) -> bool:
    a, b = _normalized_person(left), _normalized_person(right)
    return bool(
        a
        and b
        and a != b
        and a[0] == b[0]
        and a[-1] == b[-1]
        and ((len(a) == 2 and len(b) > 2) or (len(b) == 2 and len(a) > 2))
    )


def _validated_flight_scope(f: Mapping[str, Any]) -> JsonObject | None:
    if not isinstance(f, Mapping):
        return None
    proof = f.get("time_provenance")
    if (
        f.get("source") != "shape_southwest_itinerary_blocks"
        or f.get("airline") != "WN"
        or f.get("ownership") not in {"self", "other"}
        or f.get("force_review")
        or not isinstance(proof, dict)
        or type(proof.get("version")) is not int
        or proof["version"] != 1
        or proof.get("status") != "normalized"
    ):
        return None
    dep, arr = event_time(f.get("dep_time")), event_time(f.get("arr_time"))
    if not dep or not arr or not 0 < (arr - dep).total_seconds() <= 24 * 3600:
        return None
    if not re.fullmatch(r"WN[1-9]\d{0,3}", str(f.get("flight_number") or "")):
        return None
    if not re.fullmatch(r"[A-Z0-9]{6}", str(f.get("pnr") or "")):
        return None
    if any(
        not re.fullmatch(r"[A-Z]{3}", str(f.get(k) or "")) for k in ("dep_airport", "arr_airport")
    ):
        return None
    if f["dep_airport"] == f["arr_airport"]:
        return None
    for field, airport, instant in (
        ("departure", f["dep_airport"], dep),
        ("arrival", f["arr_airport"], arr),
    ):
        p = proof.get(field)
        if (
            not isinstance(p, dict)
            or p.get("airport") != airport
            or event_time(p.get("utc")) != instant
        ):
            return None
        try:
            local = datetime.fromisoformat(p["local"])
        except (KeyError, TypeError, ValueError):
            return None
        if local.tzinfo is not None:
            return None
    day = proof.get("departure_local_date")
    if not isinstance(day, str) or proof["departure"]["local"][:10] != day:
        return None
    return {
        "pnr": f["pnr"],
        "travel_date": day,
        "dep_airport": f["dep_airport"],
        "arr_airport": f["arr_airport"],
        "flight_number": f["flight_number"],
        "dep_time": dep.isoformat(),
        "arr_time": arr.isoformat(),
    }


def _has_complete_named_evidence(f: Mapping[str, Any], name: str) -> bool:
    wanted = _normalized_person(name)
    if not wanted:
        return False
    rows = [
        r
        for r in _passenger_evidence(f)
        if isinstance(r, dict)
        and r.get("role") == "traveler"
        and _normalized_person(r.get("name")) == wanted
        and r.get("applies") is not False
    ]
    if not rows:
        return False
    for r in rows:
        if (
            r.get("applies") is not True
            or r.get("complete") is not True
            or r.get("scope_ambiguous") is not False
        ):
            return False
        scope = r.get("scope")
        if not isinstance(scope, dict) or (
            scope.get("pnr") != f["pnr"] and scope.get("pnrs") != [f["pnr"]]
        ):
            return False
        if any(
            scope.get(k) and scope[k] != f[k]
            for k in ("dep_airport", "arr_airport", "flight_number")
        ):
            return False
        local_day = (f.get("time_provenance") or {}).get("departure_local_date")
        if any(
            scope.get(key) not in (None, local_day) for key in ("departure_date", "travel_date")
        ):
            return False
    return True


def extract_name_revision_proofs(text: str, flights: Sequence[Any]) -> list[JsonObject]:
    """Return one fingerprint-only proof per named traveler and exact leg."""
    fs = [vars(f) if not isinstance(f, dict) else f for f in flights]
    if not fs or len(fs) > 8:
        return []
    scopes = [_validated_flight_scope(f) for f in fs]
    if any(s is None for s in scopes) or len({_key(s) for s in scopes}) != len(scopes):
        return []
    pnrs = {s["pnr"] for s in scopes}
    if len(pnrs) != 1:
        return []
    lines = [" ".join(x.split()) for x in (text or "").splitlines() if x.strip()]
    if not any("Southwest" in x for x in lines):
        return []
    starts = [i for i, x in enumerate(lines) if x == "Your itinerary"]
    ends = [i for i, x in enumerate(lines) if x == "Payment information"]
    if len(starts) != 1 or len(ends) != 1 or starts[0] >= ends[0]:
        return []
    start, end = starts[0], ends[0]
    roster = lines[:start]
    cards = lines[start + 1 : end]
    refs = [roster[i + 1] for i, x in enumerate(roster[:-1]) if x == "Confirmation #"]
    if refs != list(pnrs):
        return []
    headers = [i for i, x in enumerate(roster) if x == "PASSENGER"]
    if not headers or len(headers) > 8:
        return []
    people = []
    for n, i in enumerate(headers):
        stop = headers[n + 1] if n + 1 < len(headers) else start
        rows = roster[i:stop]
        if rows[:4] != HEADERS or len(rows) < 8:
            return []
        name = rows[4]
        tail = rows[5:]
        if not _normalized_person(name):
            return []
        if tail[:3] == ["Join", "or", "Log in"]:
            tail = tail[3:]
        elif tail and re.fullmatch(r"\d{5,12}", tail[0]):
            tail = tail[1:]
        else:
            return []
        if (
            len(tail) < 2
            or not re.fullmatch(r"526\d{10}", tail[0])
            or not re.fullmatch(r"\d{1,3}(?:,\d{3})*", tail[1])
        ):
            return []
        trailing = tail[2:]
        if n + 1 < len(headers):
            if trailing:
                return []
        elif len(trailing) != 1 or not trailing[0].startswith(
            "Rapid Rewards® points are only estimations."
        ):
            return []
        people.append((name, tail[0]))
    if len({_normalized_person(n) for n, t in people}) != len(people) or len(
        {t for n, t in people}
    ) != len(people):
        return []
    if any(not _has_complete_named_evidence(f, n) for f in fs for n, t in people):
        return []
    # Use the existing bounded card grammar, then independently require EVERY
    # printed number, section date and local endpoint to match one exact fact.
    from .parser import _southwest_itinerary_card_sections, _shape_southwest_itinerary_blocks

    bounded = "Your itinerary\n" + "\n".join(cards) + "\nPayment information"
    sections = _southwest_itinerary_card_sections(bounded)
    if not sections:
        return []
    for _, _, _, date_line in sections:
        try:
            day = datetime.strptime(date_line, "%A, %m/%d/%Y")
        except ValueError:
            return []
        if day.strftime("%A").casefold() != date_line.split(",")[0].casefold():
            return []
    printed = _shape_southwest_itinerary_blocks(bounded, pnr=refs[0])
    raw_numbers = re.findall(r"(?m)^#\s*0*([1-9]\d{0,3})$", "\n".join(cards))
    if len(printed) != len(fs) or len(raw_numbers) != len(fs):
        return []
    used = set()
    for p in printed:
        matches = [
            i
            for i, f in enumerate(fs)
            if f["flight_number"] == p.flight_number
            and f["dep_airport"] == p.dep_airport
            and f["arr_airport"] == p.arr_airport
            and f["time_provenance"]["departure"]["local"]
            == p.dep_time.replace(tzinfo=None).isoformat()
            and f["time_provenance"]["arrival"]["local"]
            == p.arr_time.replace(tzinfo=None).isoformat()
        ]
        if len(matches) != 1 or matches[0] in used:
            return []
        used.add(matches[0])
    joined = "\n".join(lines)
    chains = re.findall(r"(?m)^Credit from ticket:\s*#(526\d{10})\s+to\s+#(526\d{10})$", joined)
    name_changes = re.findall(r"(?m)^(526\d{10}):\s*NAME CHANGE\b[^\n]*$", joined)
    change = None
    if "NAME CHANGE" in joined or "Credit from ticket:" in joined:
        if (
            len(chains) != 1
            or len(name_changes) != 1
            or len(people) != 1
            or chains[0][0] == chains[0][1]
            or chains[0][1] != people[0][1]
            or name_changes != [people[0][1]]
        ):
            return []
        change = chains[0]
    proofs = []
    card_key = _key(
        {"roster": roster, "cards": cards, "change": change, "name_change": name_changes}
    )
    for scope in scopes:
        for name, ticket in people:
            p = {
                "version": 1,
                "source": SOURCE,
                "document_complete": True,
                "passenger_name": " ".join(name.split()),
                "ticket_key": _ticket_key(ticket),
                "previous_ticket_key": _ticket_key(change[0]) if change else None,
                "name_change": bool(change),
                "scope": scope,
                "source_card_key": card_key,
            }
            p["source_proof_key"] = _key(p)
            proofs.append(p)
    return proofs


def _unresolved_named_revision(text: str, flights: Sequence[Any]) -> list[JsonObject]:
    """Recognize a typed name-change claim only to withhold sharing authority.

    This marker supplies no previous ticket, identity equivalence or retirement
    authority. A complete named ticket header and its own NAME CHANGE fare line
    are required; generic legal prose and transferable credits cannot create it.
    """
    lines = [" ".join(line.split()) for line in (text or "").splitlines() if line.strip()]
    joined = "\n".join(lines)
    references = re.findall(r"(?m)^Confirmation #\n([A-Z0-9]{6})$", joined)
    if (
        len(references) != 1
        or lines.count("Your itinerary") != 1
        or lines.count("Payment information") != 1
    ):
        return []
    roster = joined.split("\nYour itinerary\n", 1)[0]
    rows = re.findall(
        r"(?m)^PASSENGER\nRAPID REWARDS #\nTICKET #\nEST\. POINTS EARNED\n([^\n]+)\n(?:\d{5,12}|Join\nor\nLog in)\n(526\d{10})\n(?:\d{1,3}(?:,\d{3})*)$",
        roster,
    )
    changes = re.findall(r"(?m)^(526\d{10}):\s*NAME CHANGE\b[^\n]*$", joined)
    if len(changes) != 1:
        return []
    names = [name for name, ticket in rows if ticket == changes[0] and _normalized_person(name)]
    if len(names) != 1:
        return []
    result = []
    for flight in flights:
        facts = flight if isinstance(flight, dict) else vars(flight)
        if (
            facts.get("source") != "shape_southwest_itinerary_blocks"
            or facts.get("airline") != "WN"
            or facts.get("pnr") != references[0]
            or not _has_complete_named_evidence(facts, names[0])
        ):
            continue
        result.append(
            {
                "version": 1,
                "source": SOURCE,
                "passenger_name": " ".join(names[0].split()),
                "pnr": references[0],
                "reason": "unresolved_named_ticket_revision",
                "source_claim_key": _key({"roster": roster, "fare_lines": changes, "text": joined}),
            }
        )
    return result


def attach_name_revision_evidence(text: str, flights: Sequence[Any]) -> list[JsonObject]:
    """Attach per-name private proof only; no identity or schedule modification."""
    proofs = extract_name_revision_proofs(text, flights)
    unresolved = _unresolved_named_revision(text, flights) if not proofs else []
    for flight in flights:
        facts = vars(flight) if not isinstance(flight, dict) else flight
        scope = _validated_flight_scope(facts)
        for evidence in _passenger_evidence(facts):
            if not isinstance(evidence, dict):
                continue
            matched = [
                p
                for p in proofs
                if p["scope"] == scope
                and _normalized_person(p["passenger_name"])
                == _normalized_person(evidence.get("name"))
            ]
            if len(matched) == 1:
                evidence["recipient_ticket"] = matched[0]
            elif unresolved:
                hints = [
                    hint
                    for hint in unresolved
                    if hint["pnr"] == facts.get("pnr")
                    and _normalized_person(hint["passenger_name"])
                    == _normalized_person(evidence.get("name"))
                ]
                if hints:
                    evidence["recipient_ticket_review"] = hints[0]
    return proofs


def _valid_proof(proof: Any, observation: Mapping[str, Any], name: str) -> bool:
    f = observation.get("facts") or {}
    scope = _validated_flight_scope(f)
    if not isinstance(proof, dict) or set(proof) != {
        "version",
        "source",
        "document_complete",
        "passenger_name",
        "ticket_key",
        "previous_ticket_key",
        "name_change",
        "scope",
        "source_card_key",
        "source_proof_key",
    }:
        return False
    if (
        type(proof.get("version")) is not int
        or proof["version"] != 1
        or proof.get("source") != SOURCE
        or proof.get("document_complete") is not True
        or type(proof.get("name_change")) is not bool
        or _normalized_person(proof.get("passenger_name")) != _normalized_person(name)
        or not _has_complete_named_evidence(f, name)
        or proof.get("scope") != scope
        or scope is None
    ):
        return False
    if observation.get("ownership") != f.get("ownership"):
        return False
    if any(
        observation.get(k) != scope[k]
        for k in ("pnr", "travel_date", "dep_airport", "arr_airport", "flight_number")
    ):
        return False
    for k in ("ticket_key", "source_card_key", "source_proof_key"):
        if not re.fullmatch(r"[a-f0-9]{64}", str(proof.get(k) or "")):
            return False
    prev = proof.get("previous_ticket_key")
    if proof["name_change"] != bool(prev) or (
        prev and (not re.fullmatch(r"[a-f0-9]{64}", str(prev)) or prev == proof["ticket_key"])
    ):
        return False
    return proof["source_proof_key"] == _key(
        {k: v for k, v in proof.items() if k != "source_proof_key"}
    )


def _proven_event(row: Mapping[str, Any]) -> datetime | None:
    p = (row.get("facts") or {}).get("source_time_provenance")
    t = event_time(row.get("source_event_at"))
    return (
        t
        if (
            t
            and isinstance(p, dict)
            and type(p.get("version")) is int
            and p["version"] == 1
            and p.get("kind") in {"direct", "forwarded"}
            and all(event_time(p.get(k)) == t for k in ("event_at", "earliest", "latest"))
        )
        else None
    )


def _operational_corroboration(row: Mapping[str, Any], scope: Mapping[str, Any]) -> bool:
    f = row.get("facts") or {}
    life = f.get("booking_lifecycle") or {}
    if (
        row.get("ownership") != "unknown"
        or f.get("ownership") != "unknown"
        or f.get("force_review")
        or f.get("user_decision")
        or type(life.get("version")) is not int
        or life.get("version") != 1
        or life.get("kind") != "operational_notice"
        or life.get("can_reinstate") is not False
    ):
        return False
    # No UNKNOWN row creates authority. An exact existing leg reminder is
    # neutral once two named issued receipts independently prove the edge.
    return _validated_flight_scope(dict(f, ownership="self")) == scope and all(
        row.get(k) == scope[k]
        for k in ("pnr", "travel_date", "dep_airport", "arr_airport", "flight_number")
    )


def _ambiguous_name_holds(items, tickets, protected):
    """Hold possible middle-name duplicates without choosing a person by spelling.

    Each group is one owner's exact booked leg. Ticket fingerprints from
    different extractors can only be compared within their own namespace.
    """
    held = set()
    for left, right in combinations(items, 2):
        if left["flight_key"] != right["flight_key"] or not _compatible_name_revision(
            left["passenger_name"], right["passenger_name"]
        ):
            continue
        a, b = left["id"], right["id"]
        evidence_a, evidence_b = tickets[a], tickets[b]
        comparable = [(x, y) for x, y in zip(evidence_a, evidence_b) if x and y]
        if comparable and all(len(x) == len(y) == 1 and x != y for x, y in comparable):
            continue  # Two independently ticketed travelers.
        if a in protected or b in protected:
            held.update({a, b} - protected)
            continue
        certain_a = any(evidence_a) and all(len(keys) <= 1 for keys in evidence_a)
        certain_b = any(evidence_b) and all(len(keys) <= 1 for keys in evidence_b)
        if certain_a == certain_b:
            held.update((a, b))
        else:
            held.add(b if certain_a else a)
    return held


def resolve_recipient_revisions(
    items: Sequence[JsonObject],
    observations: Sequence[JsonObject],
    links: Sequence[JsonObject],
    *,
    user_id: int,
    user_names: Sequence[str],
    protected_ids: Iterable[str] = (),
    conflicting_successor_ids: Iterable[str] = (),
    issued_ticket_keys: Mapping[str, set[str]] | None = None,
) -> JsonObject:
    """Derive current/superseded/review without editing an item or source.

    A prior
    protected item always remains visible; new linkage stays held. Unknown or
    competing evidence cannot remove a recipient from the visible inventory.
    """
    selected = {i["id"]: i for i in items if i.get("user_id") == user_id}
    rows = {o["id"]: o for o in observations if o.get("user_id") == user_id}
    per = {i: [] for i in selected}
    for link in links:
        if link.get("item_id") in per and link.get("observation_id") in rows:
            per[link["item_id"]].append(rows[link["observation_id"]])
    proofs = {}
    protected = set(protected_ids)
    raw_intents = set()
    invalid_intents = set()
    decision_conflicts = set()
    from .passenger_identity import full_names_match

    for iid, item in selected.items():
        if any((r.get("facts") or {}).get("user_decision") for r in per[iid]):
            protected.add(iid)
            decision_conflicts.add(iid)
        found = []
        if any(full_names_match(item.get("passenger_name") or "", n) for n in user_names if n):
            proofs[iid] = found
            continue
        for row in per[iid]:
            for e in _passenger_evidence(row.get("facts")):
                p = e.get("recipient_ticket") if isinstance(e, dict) else None
                review = e.get("recipient_ticket_review") if isinstance(e, dict) else None
                if isinstance(review, dict) and review.get("source") == SOURCE:
                    raw_intents.add(iid)
                    invalid_intents.add(iid)
                if (
                    isinstance(p, dict)
                    and p.get("source") == SOURCE
                    and (p.get("name_change") is True or p.get("previous_ticket_key"))
                ):
                    raw_intents.add(iid)
                expected_ownership = {"companion": "self", "other_traveler": "other"}.get(
                    item.get("reason")
                )
                if (
                    _valid_proof(p, row, item.get("passenger_name"))
                    and row.get("ownership") == expected_ownership
                ):
                    s = p["scope"]
                    fk = _key(
                        {
                            "pnr": s["pnr"],
                            "date": s["travel_date"],
                            "from": s["dep_airport"],
                            "to": s["arr_airport"],
                            "number": s["flight_number"],
                        }
                    )
                    if fk == item.get("flight_key"):
                        found.append((p, row))
                elif (
                    isinstance(p, dict)
                    and p.get("source") == SOURCE
                    and (p.get("name_change") is True or p.get("previous_ticket_key"))
                ):
                    invalid_intents.add(iid)
        proofs[iid] = found
    pending = set(raw_intents)
    edges = []
    reasons = {i: "malformed_or_unresolved_name_change" for i in raw_intents}
    for nid, new in selected.items():
        for np, nr in proofs[nid]:
            if not np["name_change"]:
                continue
            pending.add(nid)
            candidates = []
            for oid, old in selected.items():
                if (
                    oid == nid
                    or old.get("flight_key") != new.get("flight_key")
                    or not _compatible_name_revision(
                        old.get("passenger_name"), new.get("passenger_name")
                    )
                ):
                    continue
                if old.get("reason") not in {"companion", "other_traveler"} or new.get(
                    "reason"
                ) not in {"companion", "other_traveler"}:
                    continue
                for op, orr in proofs[oid]:
                    earlier, later = _proven_event(orr), _proven_event(nr)
                    if (
                        op["ticket_key"] == np["previous_ticket_key"]
                        and op["scope"] == np["scope"]
                        and earlier
                        and later
                        and earlier < later < event_time(np["scope"]["dep_time"])
                    ):
                        candidates.append(oid)
            candidates = set(candidates)
            if len(candidates) == 1:
                edges.append(
                    (next(iter(candidates)), nid, np["ticket_key"], np["previous_ticket_key"])
                )
            else:
                reasons[nid] = "missing_or_ambiguous_named_predecessor"
    # Any competing ticket within one recipient, or two successor identities,
    # denies this association. Operational rows without ticket proof do not
    # supply authority and do not erase an already proven exact receipt.
    allowed = []
    for oid, nid, newkey, oldkey in set(edges):
        if nid in invalid_intents:
            reasons[nid] = "malformed_or_unresolved_name_change"
            continue
        if oid in protected:
            reasons[nid] = "protected_predecessor"
            continue
        if nid in decision_conflicts or nid in conflicting_successor_ids:
            reasons[nid] = "successor_decision_or_conflict"
            continue
        if {p["ticket_key"] for p, r in proofs[oid]} != {oldkey} or {
            p["ticket_key"] for p, r in proofs[nid]
        } != {newkey}:
            reasons[nid] = "conflicting_issued_ticket"
            continue
        if (
            len({n for o, n, k, pk in edges if o == oid}) != 1
            or len({o for o, n, k, pk in edges if n == nid}) != 1
        ):
            reasons[nid] = "competing_name_change"
            continue
        scope = next(p["scope"] for p, r in proofs[nid] if p["ticket_key"] == newkey)
        if any(
            (
                r.get("ownership") not in {"self", "other"}
                or (r.get("facts") or {}).get("force_review")
            )
            and not _operational_corroboration(r, scope)
            for r in per[oid] + per[nid]
        ):
            reasons[nid] = "unresolved_source"
            continue
        allowed.append((oid, nid))
        pending.discard(nid)
        reasons.pop(nid, None)
    suppressed = {o for o, n in allowed}
    candidates = [
        item for iid, item in selected.items()
        if iid not in pending and iid not in suppressed
        and item.get("reason") in {"companion", "other_traveler"} and item.get("flight_key")
        and _normalized_person(item.get("passenger_name"))
        and not any(full_names_match(item["passenger_name"], n) for n in user_names if n)
        and any(all(r.get(k) for k in ("pnr", "travel_date", "dep_airport", "arr_airport", "flight_number"))
                for r in per[iid])
    ]
    tickets = {i: ((issued_ticket_keys or {}).get(i, set()), {p["ticket_key"] for p, _ in found})
               for i, found in proofs.items()}
    for iid in _ambiguous_name_holds(candidates, tickets, protected):
        pending.add(iid)
        reasons[iid] = "ambiguous_passenger_name"
    return {
        "current_item_ids": sorted(set(selected) - suppressed - pending),
        "superseded": sorted(
            [{"item_id": o, "current_item_id": n} for o, n in allowed], key=lambda x: x["item_id"]
        ),
        "held_item_ids": sorted(pending),
        "hold_reasons": reasons,
        "physical_items_unchanged": True,
    }


def recipient_revision_for_item(
    db: Any, item: Any, observations: Sequence[Any], *, siblings=None
) -> JsonObject | None:
    """Read adapter; restricted to the item's exact owner/flight key."""
    has_ticket_evidence = any(
        isinstance(e, dict) and (e.get("recipient_ticket") or e.get("recipient_ticket_review"))
        for r in observations
        for e in _passenger_evidence(r.facts)
    )
    if not has_ticket_evidence and not _normalized_person(item.passenger_name):
        return None
    from ..models import (
        BookingObservation,
        TravelInboxEvidence,
        TravelInboxItem,
        TravelInboxAssignment,
        FlightShare,
        User,
    )
    from .passenger_identity import identity_candidates

    if siblings is None:
        siblings = db.query(TravelInboxItem).filter_by(user_id=item.user_id, flight_key=item.flight_key).all()
    if not has_ticket_evidence and not any(
        _compatible_name_revision(item.passenger_name, sibling.passenger_name) for sibling in siblings
    ):
        return None
    ids = [s.id for s in siblings]
    links = db.query(TravelInboxEvidence).filter(TravelInboxEvidence.item_id.in_(ids)).all()
    observations = (
        db.query(BookingObservation)
        .filter(
            BookingObservation.user_id == item.user_id,
            BookingObservation.id.in_([l.observation_id for l in links]),
        )
        .all()
    )
    assignments = (
        db.query(TravelInboxAssignment)
        .filter(
            TravelInboxAssignment.user_id == item.user_id, TravelInboxAssignment.item_id.in_(ids)
        )
        .all()
    )
    protected = {a.item_id for a in assignments}
    conflicts = set()
    sibling_by_id = {s.id: s for s in siblings}
    normalized = lambda value: " ".join(str(value or "").split()).casefold()
    for assignment in assignments:
        if normalized(assignment.passenger_name) != normalized(
            sibling_by_id[assignment.item_id].passenger_name
        ):
            conflicts.add(assignment.item_id)
    for share in db.query(FlightShare).filter_by(sender_id=item.user_id):
        linked = set(share.item_ids or []) & set(ids)
        protected.update(linked)
        for iid in linked:
            rowids = {l.observation_id for l in links if l.item_id == iid}
            scopes = [
                _validated_flight_scope(o.facts or {}) for o in observations if o.id in rowids
            ]
            scopes = [s for s in scopes if s]
            exact = any(
                isinstance(f, dict)
                and all(f.get(k) == s[k] for k in ("dep_airport", "arr_airport", "flight_number"))
                and event_time(f.get("dep_time")) == event_time(s["dep_time"])
                and event_time(f.get("arr_time")) == event_time(s["arr_time"])
                and f.get("travel_date") == event_time(s["dep_time"]).date().isoformat()
                for f in share.flights or []
                for s in scopes
            )
            if (
                normalized(share.passenger_name) != normalized(sibling_by_id[iid].passenger_name)
                or not exact
            ):
                conflicts.add(iid)

    def raw(row):
        return {c.name: getattr(row, c.name) for c in row.__table__.columns}

    from .travel_inbox import _named_issued_ticket

    issued = {iid: set() for iid in ids}
    observations_by_id = {o.id: o for o in observations}
    for link in links:
        sibling = sibling_by_id[link.item_id]
        observation = observations_by_id.get(link.observation_id)
        if observation is None or not sibling.passenger_name:
            continue
        ownership = {"companion": "self", "other_traveler": "other"}.get(sibling.reason)
        key = _named_issued_ticket(observation, sibling.passenger_name, ownership=ownership)
        if key:
            issued[sibling.id].add(key)

    user = db.get(User, item.user_id)
    result = resolve_recipient_revisions(
        [raw(s) for s in siblings],
        [raw(o) for o in observations],
        [raw(l) for l in links],
        user_id=item.user_id,
        user_names=identity_candidates(user.name, user.travel_name_aliases or []),
        protected_ids=protected,
        conflicting_successor_ids=conflicts,
        issued_ticket_keys=issued,
    )
    if item.id in result["held_item_ids"]:
        return {
            "state": "needs_review",
            "reason": result["hold_reasons"].get(item.id, "unresolved_name_change"),
        }
    for edge in result["superseded"]:
        if edge["item_id"] == item.id:
            return {"state": "superseded", "current_item_id": edge["current_item_id"]}
    previous = [e["item_id"] for e in result["superseded"] if e["current_item_id"] == item.id]
    return {"state": "current", "previous_item_ids": previous} if previous else None
