"""Exact issued-ticket identity fingerprints; raw identifiers never persist."""
from __future__ import annotations

from hashlib import sha256
import json
import re


def agency_fingerprint(value: dict) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=False).encode("utf-8")).hexdigest()


def agency_traveler_key(name: str) -> str:
    return agency_fingerprint({"version": 1, "kind": "traveler",
                               "name": " ".join(name.split()).casefold()})


def agency_identity_key(proof: dict) -> str:
    return agency_fingerprint({key: proof[key] for key in (
        "version", "provider", "document_key", "ticket_key", "traveler_key", "journey_scope")})


def agency_source_proof_key(identity_key: str, source_leg_key: str) -> str:
    return agency_fingerprint({"version": 1, "kind": "source_proof", "identity_key": identity_key,
                               "source_leg_key": source_leg_key})


def make_agency_ticket(trip_id: str, ticket_number: str, passenger_name: str,
                       journey_scope: dict) -> dict | None:
    """Only caller-validated explicit named fields can reach this constructor."""
    if (not re.fullmatch(r"\d{3}-\d{3}-\d{3}-\d{2}", trip_id)
            or not re.fullmatch(r"\d{13}", ticket_number)
            or not passenger_name.strip()
            or set(journey_scope) != {"dep_airport", "arr_airport", "departure_date"}):
        return None
    proof = {"version": 1, "provider": "priceline",
        "document_key": agency_fingerprint({"version": 1, "kind": "agency_document", "provider": "priceline", "trip_id": trip_id}),
        "ticket_key": agency_fingerprint({"version": 1, "kind": "issued_ticket", "provider": "priceline", "ticket_number": ticket_number}),
        "traveler_key": agency_traveler_key(passenger_name), "journey_scope": dict(journey_scope)}
    proof["identity_key"] = agency_identity_key(proof)
    return proof
