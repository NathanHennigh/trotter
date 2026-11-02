"""Opt-in, bounded additional authority for an unnamed notice's exact-leg link.

The importer uses this only when its existing verified-link check is false;
it never vetoes established imports or corrections. It is not another importer.
It never fetches mail, edits evidence, guesses names, links aliases or supplies
schedule facts. A successful result identifies original passenger proof only;
the caller still applies ordinary manual/cancellation rules and source times.

Old observations remain immutable. Missing source metadata, excessive history,
or a newer source parse without this leg is uncertainty, not permission. The
short-lived source context covers the current import before its Message row is
updated in the same transaction. Callers must hold the normal user import lock.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import re

from ..models import BookingCancellation, BookingObservation, FlightShare, Message, MessageStatus, TravelInboxEvidence, TravelInboxItem, User
from .booking_ledger import booking_code, event_time, flight_scope
from .passenger_identity import full_names_match, identity_candidates


LIMIT = 128
_CONTEXT = "booking_strict_enrichment"
_DIRECT = frozenset({
    "jsonld_underName", "text_passenger_label", "html_passenger_label",
    "text_passenger_label_fare_ticket_holder", "html_passenger_label_fare_ticket_holder",
    "text_passenger_label_named_fare_holder", "html_passenger_label_named_fare_holder",
    "boarding_pass_traveler", "pdf_ticket_passenger",
})
_SYNTHETIC = frozenset({
    "user_review", "travel_name_recovery", "booking_repair_reconciliation",
    "flight_share", "accepted_flight_share", "booking_enrichment",
})


def enabled(user_id=None):
    from .flight_import_rollout import enabled as account_enabled
    return account_enabled("BOOKING_STRICT_ENRICHMENT_ENABLED", user_id)


@dataclass(frozen=True)
class EnrichmentDecision:
    allowed: bool = False
    reason: str = "no_direct_passenger_proof"
    proof_observation_ids: tuple[int, ...] = ()

    def audit(self, observation_id=None):
        return {"observation_id": observation_id, "allowed": self.allowed,
                "reason": self.reason, "proof_observation_ids": list(self.proof_observation_ids)}


@contextmanager
def current_source(db, user_id, source_message_id, parser_version):
    previous = db.info.get(_CONTEXT)
    context = {"user_id": user_id, "source_message_id": source_message_id,
               "parser_version": parser_version, "audit": []}
    db.info[_CONTEXT] = context
    try:
        yield context
    finally:
        if previous is None:
            db.info.pop(_CONTEXT, None)
        else:
            db.info[_CONTEXT] = previous


def record_audit(db, user_id, decision, observation_id):
    context = db.info.get(_CONTEXT)
    if context and context["user_id"] == user_id:
        audit = decision.audit(observation_id)
        audit.update(mode="additive", inheritance_applied=decision.allowed)
        if audit not in context["audit"] and len(context["audit"]) < LIMIT:
            context["audit"].append(audit)


def _number(value):
    from .builder import _normalize_flight_number
    return _normalize_flight_number(value)


def _scope(value):
    try:
        result = flight_scope(value)
    except (AttributeError, TypeError, ValueError):
        return dict.fromkeys(("travel_date", "dep_airport", "arr_airport", "flight_number"))
    result["dep_airport"] = booking_code(result["dep_airport"])
    result["arr_airport"] = booking_code(result["arr_airport"])
    result["flight_number"] = _number(result["flight_number"])
    return result


def _row_scope(row):
    return {"travel_date": row.travel_date, "dep_airport": booking_code(row.dep_airport),
            "arr_airport": booking_code(row.arr_airport), "flight_number": _number(row.flight_number)}


def _same_protected_leg(left, right):
    return (all(left.get(k) == right.get(k) for k in ("travel_date", "dep_airport", "arr_airport"))
            and (not right.get("flight_number") or _number(right["flight_number"]) == left["flight_number"]))


def _entries(facts):
    value = facts.get("passenger_evidence") or []
    return [value] if isinstance(value, dict) else value if isinstance(value, list) else []


def _original(row):
    return (isinstance(row.facts, dict) and not row.facts.get("user_decision")
            and row.facts.get("source") not in _SYNTHETIC)


def _direct(entry, scope, code, source_codes):
    if (not isinstance(entry, dict) or entry.get("source") not in _DIRECT
            or entry.get("role") != "traveler" or entry.get("applies") is not True
            or entry.get("scope_ambiguous") or entry.get("source_observation_id")
            or not entry.get("complete")):
        return False
    own = entry.get("scope")
    if not isinstance(own, dict) or not own:
        return False
    if own.get("pnr") and booking_code(own["pnr"]) != code:
        return False
    if own.get("pnrs") and (not isinstance(own["pnrs"], list)
                            or {booking_code(value) for value in own["pnrs"]} != {code}):
        return False
    for key in ("dep_airport", "arr_airport"):
        if own.get(key) and booking_code(own[key]) != scope[key]:
            return False
    if own.get("flight_number") and _number(own["flight_number"]) != scope["flight_number"]:
        return False
    if own.get("departure_date") and own["departure_date"] != scope["travel_date"]:
        return False
    if own.get("pnr") or own.get("pnrs"):
        return True
    # A flight number alone cannot choose between two passengers' bookings in
    # the same document, even when the route and date happen to coincide.
    return bool(own.get("flight_number") and source_codes == {code})


def _revision(facts):
    if not isinstance(facts, dict):
        return 0
    try:
        return int(facts.get("parser_version") or 0)
    except (TypeError, ValueError):
        return 0


def _normalized(facts, scope):
    provenance = facts.get("time_provenance")
    if not isinstance(provenance, dict) or provenance.get("status") != "normalized" or provenance.get("version") != 1:
        return False
    try:
        dep, arr = event_time(facts.get("dep_time")), event_time(facts.get("arr_time"))
        return bool(dep and arr and 0 < (arr - dep).total_seconds() <= 48 * 3600
            and provenance["departure_local_date"] == scope["travel_date"]
            and provenance["departure"]["local"][:10] == scope["travel_date"]
            and booking_code(provenance["departure"]["airport"]) == scope["dep_airport"]
            and booking_code(provenance["arrival"]["airport"]) == scope["arr_airport"]
            and event_time(provenance["departure"]["utc"]) == dep
            and event_time(provenance["arrival"]["utc"]) == arr)
    except (TypeError, KeyError, ValueError):
        return False


def evaluate(db, user_id, flight):
    """Return authority for UNKNOWN promotion, without any database mutation.

    Every evidence/history/share query is capped at 128 plus an overflow row.
    Offline backtests explicitly opt their copied account into the cohort. The
    result contains no email bodies or passenger names.
    """
    from .booking_ledger import _key, flight_facts
    from .booking_reconciliation import event_bounds, strictly_newer

    reject = lambda reason: EnrichmentDecision(reason=reason)
    if not enabled(user_id):
        return reject("feature_not_enabled_for_account")
    if getattr(flight, "ownership", "unknown") != "unknown":
        return reject("target_not_unknown")
    facts = flight_facts(flight)
    code, scope = booking_code(getattr(flight, "pnr", None)), _scope(flight)
    carrier = booking_code(getattr(flight, "airline", None))
    if (not code or not all(scope.values()) or not carrier
            or not re.fullmatch(r"[A-Z0-9]{2}", carrier)
            or not re.fullmatch(re.escape(carrier) + r"\d+[A-Z]?", scope["flight_number"] or "")):
        return reject("incomplete_exact_leg")
    if facts.get("force_review") or facts.get("source") in _SYNTHETIC:
        return reject("target_held_or_synthetic")
    if not _normalized(facts, scope) or not event_time(getattr(flight, "source_received_at", None)):
        return reject("target_time_unresolved")
    user = db.get(User, user_id)
    if not user:
        return reject("unknown_account")
    names = identity_candidates(user.name or "", user.travel_name_aliases or [])
    if not names:
        return reject("account_names_unresolved")
    rows = db.query(BookingObservation).filter_by(user_id=user_id, pnr=code,
        travel_date=scope["travel_date"]).order_by(BookingObservation.id).limit(LIMIT + 1).all()
    if len(rows) > LIMIT:
        return reject("booking_history_limit")
    for row in rows:
        decision = (row.facts or {}).get("user_decision") if isinstance(row.facts, dict) else None
        if decision and not isinstance(decision, dict):
            return reject("inconsistent_saved_evidence")
        if decision and _same_protected_leg(scope, _row_scope(row)) and (
                decision.get("status") != "active" or decision.get("ownership") != "self"):
            return reject("manual_decision")
    related = [row for row in rows if _row_scope(row) == scope and isinstance(row.facts, dict)]
    # Synthetic projections remain in `related` for manual/share protection,
    # but are not original mail and cannot demand Message metadata, establish
    # source chronology, lend names, or invalidate an independent original.
    originals = [row for row in related if _original(row)]
    for row in originals:
        data = row.facts
        if (booking_code(data.get("pnr")) != row.pnr
                or booking_code(data.get("dep_airport")) != scope["dep_airport"]
                or booking_code(data.get("arr_airport")) != scope["arr_airport"]
                or _number(data.get("flight_number")) != scope["flight_number"]
                or data.get("ownership") != row.ownership
                or event_time(data.get("source_received_at")) != event_time(row.source_event_at)
                or _key({"message": row.source_message_id, "event_at": event_time(row.source_event_at),
                         "facts": data}) != row.evidence_key):
            return reject("inconsistent_saved_evidence")
    source_ids = {row.source_message_id for row in originals if row.source_message_id}
    target_source = getattr(flight, "source_message_id", None)
    if target_source:
        source_ids.add(target_source)
    if not source_ids:
        return reject("missing_original_source")
    # Read versions across ALL scopes for these sources; a reparse can remove
    # or move the leg that supplied an older positive ownership decision.
    versions = db.query(BookingObservation).filter(BookingObservation.user_id == user_id,
        BookingObservation.source_message_id.in_(source_ids)).order_by(BookingObservation.id).limit(LIMIT + 1).all()
    if len(versions) > LIMIT:
        return reject("source_history_limit")
    latest = {}
    for row in versions:
        if not _original(row):
            continue
        latest[row.source_message_id] = max(latest.get(row.source_message_id, 0),
            _revision(row.facts) if isinstance(row.facts, dict) else 0)
    messages = db.query(Message).filter(Message.user_id == user_id,
        Message.provider_msg_id.in_(source_ids)).limit(LIMIT + 1).all()
    if len(messages) > LIMIT or len({row.provider_msg_id for row in messages}) != len(messages):
        return reject("source_metadata_ambiguous")
    metadata = {row.provider_msg_id: row for row in messages}
    context = db.info.get(_CONTEXT) or {}

    # Do not make contradictory/uncertain current sources disappear by filtering
    # them out of the proof set. An empty reparse or a moved leg also invalidates
    # an older scope, even if another receipt could otherwise supply ownership.
    for source in source_ids:
        in_progress = context.get("user_id") == user_id and context.get("source_message_id") == source
        message = metadata.get(source)
        revision = context["parser_version"] if in_progress else (message.parse_version if message else 0)
        if not revision or revision != latest.get(source, revision):
            return reject("source_revision_unresolved")
        if not in_progress and (not message or message.ignored or message.status not in {
                MessageStatus.ACCEPTED, MessageStatus.REVIEW_REQUIRED}
                or message.status == MessageStatus.REVIEW_REQUIRED
                and message.parse_error != "passenger_identity_unresolved"):
            return reject("source_state_unresolved")
        if not any(row.source_message_id == source and _revision(row.facts) == revision for row in originals):
            return reject("source_scope_superseded")

    def current(source, data, *, allow_review=False):
        revision = _revision(data)
        if not source or not revision or revision != latest.get(source, revision):
            return False
        if context.get("user_id") == user_id and context.get("source_message_id") == source:
            return revision == context["parser_version"]
        message = metadata.get(source)
        return bool(message and message.parse_version == revision and not message.ignored
                    and (message.status == MessageStatus.ACCEPTED
                         or allow_review and message.status == MessageStatus.REVIEW_REQUIRED
                         and message.parse_error == "passenger_identity_unresolved"))

    if not target_source or not current(target_source, facts, allow_review=True):
        return reject("target_source_not_current")
    current_rows = [row for row in originals if current(row.source_message_id, row.facts, allow_review=True)]
    if not current_rows:
        return reject("no_current_original_evidence")
    # A contradictory current passenger manifest is kept for review, even if an
    # older source claimed this traveler. No majority vote or fuzzy merge.
    proofs = []
    for row in current_rows:
        data = row.facts
        if data.get("force_review") or any(isinstance(entry, dict) and entry.get("scope_ambiguous")
                                          for entry in _entries(data)):
            return reject("ambiguous_passenger_scope")
        source_codes = set()
        for other in versions:
            if (_original(other) and other.source_message_id == row.source_message_id
                    and _revision(other.facts) == _revision(data)):
                source_codes.add(booking_code(other.pnr))
                aliases = other.facts.get("pnr_aliases") or []
                if not isinstance(aliases, list):
                    source_codes.add(None)
                else:
                    source_codes.update(booking_code(value) for value in aliases)
        direct = [entry for entry in _entries(data) if _direct(entry, scope, code, source_codes)]
        own = [entry for entry in direct if any(full_names_match(entry.get("name"), name) for name in names)]
        if row.ownership == "other" or (data.get("passenger_names") and not own) or (direct and not own):
            return reject("conflicting_passenger")
        if (row.ownership == "self" and data.get("ownership") == "self" and own
                and current(row.source_message_id, data)
                and booking_code(data.get("airline")) == carrier and _normalized(data, scope)
                and event_time(row.source_event_at)
                and not data.get("recovery_observation_ids") and not data.get("reconciles_observation_ids")):
            proofs.append(row)
    if not proofs:
        return reject("no_direct_passenger_proof")
    if any(booking_code(row.facts.get("airline")) != carrier for row in current_rows):
        return reject("carrier_conflict")
    tops = [row for row in current_rows if not any(strictly_newer(other, row) for other in current_rows)]
    if any(not all(event_bounds(row)) for row in tops):
        return reject("source_chronology_unresolved")
    schedules = {(event_time(row.facts.get("dep_time")), event_time(row.facts.get("arr_time"))) for row in tops}
    if len(schedules) != 1:
        return reject("source_chronology_conflict")
    cancellations = db.query(BookingCancellation).filter_by(user_id=user_id, pnr=code).limit(LIMIT + 1).all()
    if len(cancellations) > LIMIT:
        return reject("cancellation_history_limit")
    if any(_same_protected_leg(scope, value) for row in cancellations for value in (row.scopes or [])
           if isinstance(value, dict)):
        return reject("cancellation_evidence")
    item_ids = [item_id for (item_id,) in db.query(TravelInboxItem.id).join(TravelInboxEvidence).filter(
        TravelInboxItem.user_id == user_id, TravelInboxEvidence.observation_id.in_([row.id for row in related])
    ).distinct().limit(LIMIT + 1).all()]
    if len(item_ids) > LIMIT:
        return reject("retained_item_limit")
    if item_ids:
        shares = db.query(FlightShare).filter(FlightShare.sender_id == user_id,
            FlightShare.status.in_(["pending", "accepted"])).limit(LIMIT + 1).all()
        if len(shares) > LIMIT:
            return reject("share_history_limit")
        now = event_time(datetime.now(timezone.utc))
        if any(set(item_ids).intersection(share.item_ids or []) and (share.status == "accepted"
                or not event_time(share.expires_at) or event_time(share.expires_at) > now) for share in shares):
            return reject("active_share")
    return EnrichmentDecision(True, "verified_original_same_booking_dated_leg",
                              tuple(sorted(row.id for row in proofs)))
