"""Bounded, opt-in corroboration of complete original AA/SY flight notices.

Carrier statements are not passenger manifests. They remain in their own
immutable index; UNKNOWN observations never become SELF proof. No mailbox,
network, schedule inference, fuzzy name matching or cross-account joins occur.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from email.utils import getaddresses, parsedate_to_datetime
from functools import lru_cache
import hashlib
import json
import re
import unicodedata

from sqlalchemy import and_, or_

from ..models import (BookingCancellation, BookingObservation, CarrierTravelEvidence,
    FlightShare, Message, MessageStatus, TravelInboxAssignment, TravelInboxEvidence,
    TravelInboxItem, User)
from . import booking_enrichment as strict
from .booking_ledger import booking_code, event_time, flight_facts, _key
from .carrier_travel_evidence import EVIDENCE_VERSION, extract_carrier_travel_evidence
from .passenger_identity import _ordered_name_tokens, full_names_match, identity_candidates


LIMIT = 128
JOURNEY_DAYS = 45
MARKER = "carrier_evidence"
_RECONCILING = "carrier_travel_reconciling"


def enabled(user_id=None):
    from .flight_import_rollout import enabled as account_enabled
    return account_enabled("CARRIER_TRAVEL_CORROBORATION_ENABLED", user_id)


@dataclass(frozen=True)
class CarrierDecision:
    allowed: bool = False
    reason: str = "no_carrier_corroboration"
    proof_observation_ids: tuple[int, ...] = ()
    carrier_evidence_ids: tuple[int, ...] = ()

    def audit(self, observation_id=None):
        return {"observation_id": observation_id, "allowed": self.allowed, "reason": self.reason,
                "proof_observation_ids": [], "carrier_evidence_ids": list(self.carrier_evidence_ids)}


def _stamp(value):
    if isinstance(value, str):
        try:
            value = parsedate_to_datetime(value)
        except (TypeError, ValueError, OverflowError):
            pass
    return event_time(value)


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, default=lambda item: _stamp(item).isoformat()).encode()).hexdigest()


def _bounded(query):
    values = query.limit(LIMIT + 1).all()
    return values if len(values) <= LIMIT else None


def _single_address(value):
    values = getaddresses([value or ""])
    return values[0][1].lower() if len(values) == 1 and "@" in values[0][1] else None


def _uncertain_cancellation(message):
    return message.parse_error in {"ambiguous_cancellation_scope", "ambiguous_cancellation_time",
        "unresolved_cancellation_scope", "cancellation_document_requires_review"}


def _source_inputs(payload, user):
    raw = (payload.get("full_msg") or {}).get("payload", {}).get("headers") or []
    headers = {}
    # Gmail prepends its receiving authentication header. Never prefer a later
    # sender-supplied duplicate or authentication-looking text in a body.
    for header in raw:
        headers.setdefault(str(header.get("name", "")).lower(), header.get("value", ""))
    delivered = _single_address(headers.get("delivered-to"))
    recipient = _single_address(headers.get("to"))
    if delivered != (user.email or "").lower() or recipient != delivered:
        return None
    received = _stamp(payload.get("received_at"))
    if not received:
        return None
    return dict(subject=payload.get("subject", ""), sender=payload.get("from_email", ""),
                recipient=recipient, text=payload.get("plain_text", ""), html=payload.get("html", ""),
                received_at=received, authentication_results=headers.get("authentication-results", ""))


def record_payload(db, user_id, payload):
    """Bind typed statements to original source content after normal processing.

    Operational fields come only from complete normal ParsedFlights and their
    already-persisted observations. A zero-evidence current marker supersedes
    old source authority without deleting its immutable historical rows.
    """
    if not enabled(user_id):
        return []
    user = db.get(User, user_id)
    source = payload.get("msg_id")
    if not user or not source or (payload.get("full_msg") or {}).get("id") != source:
        return []
    message = db.query(Message).filter_by(user_id=user_id, provider_msg_id=source).one_or_none()
    if not message:
        return []
    inputs = _source_inputs(payload, user)
    # Include the exact original boundary even when trust validation fails.
    fingerprint = _hash(inputs) if inputs else _hash({"invalid_original": payload.get("full_msg") or {}})
    received = inputs["received_at"] if inputs else _stamp(payload.get("received_at"))
    statements = extract_carrier_travel_evidence(**inputs) if inputs and not _uncertain_cancellation(message) else ()
    observations = _bounded(db.query(BookingObservation).filter_by(user_id=user_id, source_message_id=source))
    rows = []
    if observations is not None and received:
        current = [row for row in observations if strict._original(row)
                   and strict._revision(row.facts) == message.parse_version]
        parsed = payload.get("parse_result")
        for statement in statements:
            data = asdict(statement)
            facts = dict(data.pop("facts"))
            for label in ("departure_label", "arrival_label"):
                facts[label] = data.pop(label)
            if statement.kind == "post_travel":
                variants = [(data, facts)]
            else:
                variants = []
                for flight in getattr(parsed, "flights", []) if parsed else []:
                    scope, code = strict._scope(flight), booking_code(getattr(flight, "pnr", None))
                    raw_facts = flight_facts(flight)
                    if (code != statement.pnr or not all(scope.values())
                            or booking_code(getattr(flight, "airline", None)) != statement.carrier
                            or not (scope["flight_number"] or "").startswith(statement.carrier)
                            or getattr(flight, "force_review", False)
                            or not strict._normalized(raw_facts, scope)
                            or statement.arr_airport and statement.arr_airport != scope["arr_airport"]):
                        continue
                    bound = [row for row in current if row.pnr == code and strict._row_scope(row) == scope
                             and event_time(row.facts.get("dep_time")) == event_time(raw_facts.get("dep_time"))
                             and event_time(row.facts.get("arr_time")) == event_time(raw_facts.get("arr_time"))]
                    if not bound:
                        continue
                    variants.append(({**data, "local_day": scope["travel_date"],
                        "dep_airport": scope["dep_airport"], "arr_airport": scope["arr_airport"]},
                        {**facts, "flight_number": scope["flight_number"], "parse_version": message.parse_version,
                         "observation_ids": sorted(row.id for row in bound)}))
            for values, details in variants:
                stored = dict(user_id=user_id, source_message_id=source, source_sha256=fingerprint,
                              evidence_version=EVIDENCE_VERSION, received_at=received, **values, facts=details)
                key = _hash(stored)
                row = db.query(CarrierTravelEvidence).filter_by(user_id=user_id, evidence_key=key).one_or_none()
                if row is None:
                    row = CarrierTravelEvidence(evidence_key=key, **stored)
                    db.add(row)
                    db.flush()
                if row.id not in {item.id for item in rows}:
                    rows.append(row)
    parsed = payload.get("parse_result")
    no_flights = not bool(getattr(parsed, "flights", []))
    message.parse_evidence = {**(message.parse_evidence or {}), MARKER: {
        "version": EVIDENCE_VERSION, "source_sha256": fingerprint,
        "analyzed_no_flights": no_flights and not _uncertain_cancellation(message),
        "evidence_ids": sorted(row.id for row in rows)}}
    if rows and all(row.kind == "post_travel" for row in rows) and no_flights:
        # A retained survey is a successfully processed supporting source, not
        # an itinerary extraction failure. Keep it out of repeated scan work.
        message.status, message.ignored = MessageStatus.ACCEPTED, True
        message.parse_error = "carrier_travel_assertion_retained"
        message.parse_evidence = {**message.parse_evidence, "resolved": True,
                                 "reason": "carrier_travel_assertion_retained"}
    db.flush()
    return rows


def _current_evidence(db, user_id, rows):
    source_ids = {row.source_message_id for row in rows}
    if not source_ids:
        return []
    messages = _bounded(db.query(Message).filter(Message.user_id == user_id, Message.provider_msg_id.in_(source_ids)))
    if messages is None or len({row.provider_msg_id for row in messages}) != len(messages):
        return None
    by_source = {row.provider_msg_id: row for row in messages}
    current = []
    for row in rows:
        message = by_source.get(row.source_message_id)
        marker = (message.parse_evidence or {}).get(MARKER, {}) if message else {}
        if not isinstance(marker, dict) or not isinstance(marker.get("evidence_ids", []), list):
            return None
        identity = {key: getattr(row, key) for key in ("user_id", "source_message_id", "source_sha256",
                    "evidence_version", "received_at", "kind", "carrier", "name", "local_day",
                    "dep_airport", "arr_airport", "pnr", "facts")}
        if not isinstance(row.facts, dict) or _hash(identity) != row.evidence_key:
            return None
        if (not message or message.status not in {MessageStatus.ACCEPTED, MessageStatus.REVIEW_REQUIRED}
                or _uncertain_cancellation(message)
                or marker.get("version") != EVIDENCE_VERSION
                or row.evidence_version != EVIDENCE_VERSION
                or marker.get("source_sha256") != row.source_sha256
                or row.id not in marker.get("evidence_ids", [])):
            continue
        if row.kind != "post_travel" and row.facts.get("parse_version") != message.parse_version:
            continue
        current.append(row)
    return current


@lru_cache(maxsize=1)
def _airports():
    import airportsdata
    return airportsdata.load("IATA")


def _words(value):
    value = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode().lower()
    words = re.sub(r"[^a-z0-9]+", " ", value).split()
    return ["fort" if word == "ft" else word for word in words]


def _label_matches(label, airport):
    """Compare a supplied city label to an existing airport; never create one."""
    item = _airports().get(airport)
    if not item or not label:
        return False
    parts = [part.strip() for part in label.split(",")]
    if _words(parts[0]) != _words(item.get("city")):
        return False
    if len(parts) == 1:
        return True
    if len(parts) != 2:
        return False
    from .builder import _COUNTRY_NAMES
    region = parts[1]
    candidates = {item.get("subd", ""), item.get("country", ""), _COUNTRY_NAMES.get(item.get("country"), "")}
    # Postal region abbreviations are exact vocabulary, not a guessed city or
    # an external geocoder. Unknown country/region labels fail closed.
    states = dict(value.split(":", 1) for value in (
        "AL:Alabama|AK:Alaska|AZ:Arizona|AR:Arkansas|CA:California|CO:Colorado|CT:Connecticut|DE:Delaware|"
        "FL:Florida|GA:Georgia|HI:Hawaii|ID:Idaho|IL:Illinois|IN:Indiana|IA:Iowa|KS:Kansas|KY:Kentucky|"
        "LA:Louisiana|ME:Maine|MD:Maryland|MA:Massachusetts|MI:Michigan|MN:Minnesota|MS:Mississippi|MO:Missouri|"
        "MT:Montana|NE:Nebraska|NV:Nevada|NH:New Hampshire|NJ:New Jersey|NM:New Mexico|NY:New York|"
        "NC:North Carolina|ND:North Dakota|OH:Ohio|OK:Oklahoma|OR:Oregon|PA:Pennsylvania|RI:Rhode Island|"
        "SC:South Carolina|SD:South Dakota|TN:Tennessee|TX:Texas|UT:Utah|VT:Vermont|VA:Virginia|"
        "WA:Washington|WV:West Virginia|WI:Wisconsin|WY:Wyoming|DC:District of Columbia"
    ).split("|"))
    if item.get("country") == "US" and _words(states.get(region.upper(), "")) == _words(item.get("subd")):
        return True
    return any(_words(region) == _words(value) for value in candidates if value)


def _given_sequences(names):
    result = []
    for name in names:
        tokens = _ordered_name_tokens(name)
        if (len(tokens) >= 3 and all(len(token) > 1 and token.isalpha() for token in tokens)
                and not {"de", "del", "van", "von", "bin", "al", "jr", "sr", "ii", "iii"}.intersection(tokens[1:])):
            result.append(tokens[:-1])
    return result


def _survey_name_matches(value, names):
    words = _ordered_name_tokens(value or "")
    for name in names:
        known = _ordered_name_tokens(name)
        if len(known) >= 2 and (words == known[:1] or words == known[:-1]
                or len(words) == 1 and words[0] == "".join(known[:-1])):
            return True
    return False


def _personal_matches(row, names):
    if row.kind != "operational_personal":
        return False
    if row.carrier == "SY":
        return row.facts.get("name_form") == "full_salutation" and any(full_names_match(row.name, name) for name in names)
    return (row.facts.get("name_form") == "given_sequence"
            and _ordered_name_tokens(row.name or "") in _given_sequences(names))


def _row_leg(row):
    return {"travel_date": row.local_day, "dep_airport": row.dep_airport,
            "arr_airport": row.arr_airport, "flight_number": strict._number(row.facts.get("flight_number"))}


def _validate_operational(db, user_id, evidence):
    ids = {value for row in evidence if row.kind != "post_travel" for value in row.facts.get("observation_ids", [])}
    if not ids or len(ids) > LIMIT:
        return None
    observations = _bounded(db.query(BookingObservation).filter(BookingObservation.user_id == user_id,
                                                                 BookingObservation.id.in_(ids)))
    if observations is None or {row.id for row in observations} != ids:
        return None
    by_id = {row.id: row for row in observations}
    for evidence_row in evidence:
        if evidence_row.kind == "post_travel":
            continue
        for oid in evidence_row.facts.get("observation_ids", []):
            row = by_id[oid]
            facts = row.facts
            if (not strict._original(row) or row.pnr != evidence_row.pnr
                    or row.source_message_id != evidence_row.source_message_id
                    or strict._row_scope(row) != _row_leg(evidence_row)
                    or strict._revision(facts) != evidence_row.facts.get("parse_version")
                    or booking_code(facts.get("pnr")) != row.pnr
                    or booking_code(facts.get("dep_airport")) != row.dep_airport
                    or booking_code(facts.get("arr_airport")) != row.arr_airport
                    or strict._number(facts.get("flight_number")) != strict._number(row.flight_number)
                    or booking_code(facts.get("airline")) != evidence_row.carrier
                    or facts.get("ownership") != row.ownership
                    or not strict._normalized(facts, strict._row_scope(row))
                    or not event_time(row.source_event_at)
                    or event_time(facts.get("source_received_at")) != event_time(row.source_event_at)
                    or _key({"message": row.source_message_id, "event_at": event_time(row.source_event_at), "facts": facts}) != row.evidence_key):
                return None
    return observations


def _protection_reason(db, user_id, code, scope, related, names):
    for row in related:
        data = row.facts if isinstance(row.facts, dict) else {}
        decision = data.get("user_decision")
        if decision and (not isinstance(decision, dict) or decision.get("status") != "active" or decision.get("ownership") != "self"):
            return "manual_decision"
        if data.get("force_review") or any(entry.get("scope_ambiguous") for entry in strict._entries(data) if isinstance(entry, dict)):
            return "ambiguous_passenger_scope"
        # These are scoped original traveler names, not account-header names.
        if row.ownership == "other" or any(not any(full_names_match(name, own) for own in names)
                                         for name in data.get("passenger_names", []) if isinstance(name, str)):
            return "conflicting_passenger"
    cancellations = _bounded(db.query(BookingCancellation).filter_by(user_id=user_id, pnr=code))
    if cancellations is None:
        return "cancellation_history_limit"
    if any(not row.scopes or any(strict._same_protected_leg(scope, value) for value in row.scopes if isinstance(value, dict)) for row in cancellations):
        return "cancellation_evidence"
    item_rows = _bounded(db.query(TravelInboxItem.id).join(TravelInboxEvidence).filter(
        TravelInboxItem.user_id == user_id, TravelInboxEvidence.observation_id.in_([row.id for row in related])).distinct())
    if item_rows is None:
        return "retained_item_limit"
    items = {row[0] for row in item_rows}
    if items:
        assignments = _bounded(db.query(TravelInboxAssignment).filter(TravelInboxAssignment.user_id == user_id,
                                                                      TravelInboxAssignment.item_id.in_(items)))
        if assignments is None or any(not any(full_names_match(row.passenger_name, name) for name in names) for row in assignments):
            return "retained_assignment"
        shares = _bounded(db.query(FlightShare).filter(FlightShare.sender_id == user_id, FlightShare.status.in_(["pending", "accepted"])))
        if shares is None:
            return "share_history_limit"
        now = event_time(datetime.now(timezone.utc))
        if any(items.intersection(row.item_ids or []) and (row.status == "accepted" or not event_time(row.expires_at)
                or event_time(row.expires_at) > now) for row in shares):
            return "active_share"
    return None


def _competing_original_booking(db, user_id, carrier, code, scope, *, arrival_only=False):
    # A PNR-less survey cannot select between separately booked passengers.
    # Receipts outside the narrow typed templates are equally important here.
    # Check every original on this dated route, regardless of flight-number
    # formatting or schedule changes; this guard supplies no identity authority.
    query = db.query(BookingObservation).filter_by(user_id=user_id,
        travel_date=scope["travel_date"], arr_airport=scope["arr_airport"])
    if not arrival_only:
        query = query.filter_by(dep_airport=scope["dep_airport"])
    rows = _bounded(query)
    if rows is None:
        return "competing_original_history_limit"
    for row in rows:
        if not strict._original(row):
            continue
        facts = row.facts if isinstance(row.facts, dict) else {}
        row_carrier = booking_code(facts.get("airline"))
        number = strict._number(row.flight_number) or ""
        if row_carrier != carrier and not number.startswith(carrier):
            continue
        if booking_code(row.pnr) and booking_code(row.pnr) != code:
            return "competing_original_booking"
    return None


def evaluate(db, user_id, flight):
    """Additional, typed authority for an UNKNOWN complete original flight."""
    reject = lambda reason: CarrierDecision(reason=reason)
    if not enabled(user_id):
        return reject("feature_not_enabled_for_account")
    facts, scope = flight_facts(flight), strict._scope(flight)
    code, carrier = booking_code(getattr(flight, "pnr", None)), booking_code(getattr(flight, "airline", None))
    source = getattr(flight, "source_message_id", None)
    if getattr(flight, "ownership", "unknown") != "unknown":
        return reject("target_not_unknown")
    if (carrier not in {"AA", "SY"} or not code or not all(scope.values())
            or not re.fullmatch(re.escape(carrier or "") + r"\d+[A-Z]?", scope.get("flight_number") or "")):
        return reject("incomplete_carrier_leg")
    if facts.get("force_review") or facts.get("source") in strict._SYNTHETIC or not strict._normalized(facts, scope):
        return reject("target_held_or_time_unresolved")
    try:
        day = date.fromisoformat(scope["travel_date"])
    except (TypeError, ValueError):
        return reject("target_day_unresolved")
    user = db.get(User, user_id)
    names = identity_candidates(user.name or "", user.travel_name_aliases or []) if user else []
    if not names:
        return reject("account_names_unresolved")
    rows = _bounded(db.query(CarrierTravelEvidence).filter(CarrierTravelEvidence.user_id == user_id,
        CarrierTravelEvidence.carrier == carrier,
        CarrierTravelEvidence.local_day >= (day - timedelta(days=JOURNEY_DAYS)).isoformat(),
        CarrierTravelEvidence.local_day <= (day + timedelta(days=JOURNEY_DAYS)).isoformat()))
    if rows is None:
        return reject("carrier_evidence_limit")
    rows = _current_evidence(db, user_id, rows)
    if rows is None:
        return reject("source_metadata_limit")
    operations = [row for row in rows if row.kind != "post_travel"]
    target_rows = [row for row in operations if row.pnr == code and row.source_message_id == source and _row_leg(row) == scope]
    if not target_rows:
        return reject("target_source_not_current")
    validated = _validate_operational(db, user_id, operations)
    if validated is None:
        return reject("inconsistent_operational_evidence")
    related = _bounded(db.query(BookingObservation).filter_by(user_id=user_id, pnr=code, travel_date=scope["travel_date"]))
    if related is None:
        return reject("booking_history_limit")
    # Historical rows remain relevant for manual/share protection, but obsolete
    # parser observations cannot establish new personal authority.
    exact = [row for row in related if strict._same_protected_leg(scope, strict._row_scope(row))]
    reason = _protection_reason(db, user_id, code, scope, exact, names)
    if reason:
        return reject(reason)
    reason = _competing_original_booking(db, user_id, carrier, code, scope)
    if reason:
        return reject(reason)
    current_target = [row for row in validated if row.pnr == code and strict._row_scope(row) == scope]
    if not current_target:
        return reject("no_current_operational_leg")
    target_key = _key({"message": source, "event_at": event_time(getattr(flight, "source_received_at", None)), "facts": facts})
    if not any(row.source_message_id == source and row.evidence_key == target_key for row in current_target):
        return reject("target_observation_not_current")
    top_time = max((event_time(row.source_event_at) for row in current_target), default=None)
    if not top_time:
        return reject("source_time_unresolved")
    tops = [row for row in current_target if event_time(row.source_event_at) == top_time]
    if len({(event_time(row.facts.get("dep_time")), event_time(row.facts.get("arr_time"))) for row in tops}) != 1:
        return reject("source_time_conflict")
    if {row.pnr for row in operations if _row_leg(row) == scope} != {code}:
        return reject("competing_booking")
    if any(row.kind == "operational_personal" and row.pnr == code and not _personal_matches(row, names) for row in operations):
        return reject("conflicting_personal_carrier_name")
    personal = [row for row in operations if row.pnr == code and _personal_matches(row, names)]
    surveys = [row for row in rows if row.kind == "post_travel" and _survey_name_matches(row.name, names)]
    for survey in surveys:
        survey_day = date.fromisoformat(survey.local_day)
        if not 0 <= (day - survey_day).days <= JOURNEY_DAYS:
            continue
        if carrier == "SY":
            if survey.local_day != scope["travel_date"]:
                continue
            if not (_label_matches(survey.facts.get("departure_label"), scope["dep_airport"])
                    and _label_matches(survey.facts.get("arrival_label"), scope["arr_airport"])):
                continue
            if any(row.kind == "post_travel" and row.local_day == survey.local_day
                    and _label_matches(row.facts.get("departure_label"), scope["dep_airport"])
                    and _label_matches(row.facts.get("arrival_label"), scope["arr_airport"])
                    and not _survey_name_matches(row.name, names) for row in rows):
                return reject("conflicting_post_travel_name")
            named = [row for row in personal if _row_leg(row) == scope]
            if not named or event_time(survey.received_at) < max(event_time(row.facts["arr_time"]) for row in tops):
                continue
            proof = [survey, named[0], *target_rows]
        else:
            if any(row.kind == "post_travel" and row.local_day == survey.local_day
                    and row.dep_airport == survey.dep_airport and row.arr_airport == survey.arr_airport
                    and not _survey_name_matches(row.name, names) for row in rows):
                return reject("conflicting_post_travel_name")
            connecting = [row for row in operations if row.kind == "connecting_notice" and row.pnr == code
                          and row.local_day == survey.local_day and row.arr_airport == survey.arr_airport
                          and row.dep_airport != survey.dep_airport]
            returns = [row for row in personal if row.dep_airport == survey.arr_airport
                       and 0 <= (date.fromisoformat(row.local_day) - survey_day).days <= JOURNEY_DAYS]
            if not connecting or not returns:
                continue
            if (len({tuple(_row_leg(row).values()) for row in connecting}) != 1
                    or len({tuple(_row_leg(row).values()) for row in returns}) != 1):
                return reject("ambiguous_journey_anchors")
            if {row.pnr for row in operations if row.local_day == survey.local_day and row.arr_airport == survey.arr_airport} != {code}:
                return reject("competing_journey_booking")
            competing = _competing_original_booking(db, user_id, carrier, code,
                {"travel_date": survey.local_day, "dep_airport": survey.dep_airport,
                 "arr_airport": survey.arr_airport}, arrival_only=True)
            if competing:
                return reject("journey_" + competing)
            candidates = [row for row in connecting + returns if _row_leg(row) == scope]
            if not candidates:
                continue
            connection_ids = set(connecting[0].facts.get("observation_ids", []))
            completed = [row for row in validated if row.id in connection_ids]
            if not completed or event_time(survey.received_at) < max(event_time(row.facts["arr_time"]) for row in completed):
                continue
            proof = [survey, connecting[0], returns[0], *target_rows]
        # Ownership of an outbound cannot be borrowed from a return that was
        # explicitly assigned/cancelled/shared or names another traveler in a
        # different document. Inspect every proof leg, not just today's target.
        checked = set()
        for anchor in proof:
            if anchor.kind == "post_travel":
                continue
            anchor_scope = _row_leg(anchor)
            anchor_key = tuple(anchor_scope.values())
            if anchor_key in checked:
                continue
            checked.add(anchor_key)
            anchor_rows = _bounded(db.query(BookingObservation).filter_by(user_id=user_id,
                                  pnr=code, travel_date=anchor.local_day))
            if anchor_rows is None:
                return reject("anchor_history_limit")
            anchor_related = [row for row in anchor_rows if strict._same_protected_leg(anchor_scope, strict._row_scope(row))]
            protected = _protection_reason(db, user_id, code, anchor_scope, anchor_related, names)
            if protected:
                return reject("anchor_" + protected)
            competing = _competing_original_booking(db, user_id, carrier, code, anchor_scope)
            if competing:
                return reject("anchor_" + competing)
        # Evidence conflict elsewhere within this exact bounded booking cannot
        # be outvoted by several copies of a post-travel survey.
        booking_rows = [row for row in validated if row.pnr == code]
        if any(row.ownership == "other" or row.facts.get("force_review") or any(
                not any(full_names_match(name, own) for own in names) for name in row.facts.get("passenger_names", [])
                if isinstance(name, str)) for row in booking_rows):
            return reject("conflicting_booking_passenger")
        return CarrierDecision(True, "carrier_travel_corroborated", (), tuple(sorted({row.id for row in proof})))
    return reject("no_compatible_independent_carrier_assertions")


def _clear_resolved_message(db, user_id, source):
    """Clear only an identity hold whose every current original leg resolved."""
    from .booking_import import _retained_flight
    from ..models import Segment, Trip
    message = db.query(Message).filter_by(user_id=user_id, provider_msg_id=source).one_or_none()
    if (not message or message.status != MessageStatus.REVIEW_REQUIRED
            or message.parse_error != "passenger_identity_unresolved"):
        return
    observations = _bounded(db.query(BookingObservation).filter_by(user_id=user_id, source_message_id=source))
    if observations is None:
        return
    originals = [row for row in observations if strict._original(row) and strict._revision(row.facts) == message.parse_version]
    if not originals:
        return
    proofs = set()
    for row in originals:
        restored = _retained_flight(row, ownership=row.ownership)
        if restored is None or row.ownership not in {"unknown", "self"}:
            return
        restored.source_message_id = source
        if row.ownership == "unknown":
            result = evaluate(db, user_id, restored)
            if not result.allowed:
                return
            proofs.update(result.carrier_evidence_ids)
        active = _bounded(db.query(Segment).join(Trip).filter(Trip.user_id == user_id,
            Segment.pnr == row.pnr, Segment.dep_airport == row.dep_airport, Segment.arr_airport == row.arr_airport))
        if active is None or not any(strict._scope(segment) == strict._row_scope(row)
                                    and (segment.meta_json or {}).get("ownership") == "self" for segment in active):
            return
    message.status, message.parse_error, message.ignored = MessageStatus.ACCEPTED, None, False
    message.parse_evidence = {**(message.parse_evidence or {}), "carrier_recovery": {
        "version": EVIDENCE_VERSION, "reason": "carrier_travel_corroborated",
        "carrier_evidence_ids": sorted(proofs), "all_current_original_legs_resolved": True}}


def existing_projection_trip(db, user_id, flights):
    """Reuse the trip of an already linked carrier leg, without skipping updates.

    The builder normally creates a trip for the incoming time window before it
    discovers that an original observation already belongs to a saved segment.
    Replaying a single recovered leg of a round trip would therefore create and
    immediately delete a temporary trip. Only current carrier-authorized, exact
    original links can reuse their trip here; the normal upsert, protection and
    reclustering paths still handle every field and every real change.
    """
    from ..models import Segment, Trip

    if not enabled(user_id) or len(flights) != 1:
        return None
    flight = flights[0]
    observation_id = getattr(flight, "observation_id", None)
    source = getattr(flight, "source_message_id", None)
    entries = getattr(flight, "passenger_evidence", None) or []
    if (getattr(flight, "ownership", None) != "self" or not observation_id or not source
            or not isinstance(entries, list) or not any(isinstance(item, dict)
                and item.get("reason") == "carrier_travel_corroborated"
                and item.get("carrier_evidence_ids") for item in entries)):
        return None
    code, scope = booking_code(getattr(flight, "pnr", None)), strict._scope(flight)
    if not code or not all(scope.values()):
        return None
    candidates = _bounded(db.query(Segment).join(Trip).filter(
        Trip.user_id == user_id, Segment.pnr == code,
        Segment.dep_airport == scope["dep_airport"], Segment.arr_airport == scope["arr_airport"]))
    if candidates is None:
        return None
    linked = []
    for segment in candidates:
        meta = segment.meta_json or {}
        if (meta.get("ownership") == "self" and strict._scope(segment) == scope
                and observation_id in (meta.get("observation_ids") or [])
                and source in (meta.get("source_message_ids") or [])):
            linked.append(segment)
    return db.get(Trip, linked[0].trip_id) if len(linked) == 1 else None


def reconcile(db, user_id, rows):
    """Reevaluate only dated/booking candidates affected by this source event."""
    from .booking_import import _retained_flight, _merge_successful_replay
    from .builder import BuildSegmentsResult, build_segments_and_trips_detailed
    result = BuildSegmentsResult()
    if not enabled(user_id) or not rows or db.info.get(_RECONCILING):
        return result
    conditions = []
    for row in rows:
        if row.user_id != user_id or not row.local_day or row.carrier not in {"AA", "SY"}:
            continue
        day = date.fromisoformat(row.local_day)
        parts = [BookingObservation.travel_date >= (day - timedelta(days=JOURNEY_DAYS)).isoformat(),
                 BookingObservation.travel_date <= (day + timedelta(days=JOURNEY_DAYS)).isoformat(),
                 BookingObservation.facts["airline"].as_string() == row.carrier]
        if row.pnr:
            parts.append(BookingObservation.pnr == row.pnr)
        conditions.append(and_(*parts))
    if not conditions:
        return result
    targets = _bounded(db.query(BookingObservation).filter(BookingObservation.user_id == user_id,
        BookingObservation.ownership == "unknown", or_(*conditions)).order_by(BookingObservation.source_event_at, BookingObservation.id))
    if targets is None:
        result.review_reasons.append("carrier_replay_limit")
        return result
    db.info[_RECONCILING] = True
    try:
        resolved_sources = set()
        for observation in targets:
            flight = _retained_flight(observation)
            if flight is None:
                continue
            flight.source_message_id = observation.source_message_id
            decision = evaluate(db, user_id, flight)
            if not decision.allowed:
                continue
            replay = build_segments_and_trips_detailed(db, user_id, [flight],
                source_message_id=observation.source_message_id, source_event_at=observation.source_event_at)
            _merge_successful_replay(result, replay)
            if not replay.held:
                resolved_sources.add(observation.source_message_id)
        for source in sorted(resolved_sources):
            _clear_resolved_message(db, user_id, source)
    finally:
        db.info.pop(_RECONCILING, None)
    return result
