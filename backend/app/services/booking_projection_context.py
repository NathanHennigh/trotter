"""Worker boundaries and durable provenance for newly recovered projections."""
from contextlib import contextmanager
from contextvars import ContextVar

from ..models import Segment, Trip

_baselines = ContextVar("booking_projection_run_baselines", default={})
CREATION_MARKER = "booking_projection_creation"
CREATION_VERSION = 1


@contextmanager
def projection_run(db, user_id):
    """Remember only rows present before this account's worker processing.

    Nested work for the same account shares the original boundary. Other
    accounts/tasks have independent ContextVar state. Exit/exception resets it.
    """
    existing = _baselines.get()
    if user_id in existing:
        yield
        return
    ids = frozenset(value for (value,) in db.query(Segment.id).join(Trip).filter(Trip.user_id == user_id))
    token = _baselines.set({**existing, user_id: ids})
    try:
        yield
    finally:
        _baselines.reset(token)


def is_new_projection(user_id, segment_id):
    baseline = _baselines.get().get(user_id)
    return baseline is not None and segment_id not in baseline


def _observation_scope(observation):
    from .builder import _normalize_flight_number
    return {"travel_date": observation.travel_date, "dep_airport": observation.dep_airport,
            "arr_airport": observation.arr_airport,
            "flight_number": _normalize_flight_number(observation.flight_number)}


def record_projection_creation(db, user_id, segment, flight):
    """Stamp only an actual INSERT within this account's worker.

    The builder calls this after inserting, never when adopting or updating an
    existing row. Keep the original observation link immutable across later
    reminders, worker restarts, and bounded recovery batches. This prospective
    integrity guarantee is independent of optional positive-recovery switches:
    changing batch size must not turn held conflicting evidence into travel.
    """
    # This trusted INSERT hook also handles SQLite's reuse of a deleted maximum
    # row ID. Existing/adopted rows never call it, regardless of their ID.
    if user_id not in _baselines.get():
        return
    from .booking_ledger import booking_code, flight_scope
    from ..models import BookingObservation
    observation = db.get(BookingObservation, getattr(flight, "observation_id", None))
    scope = flight_scope(segment)
    if (not observation or observation.user_id != user_id or not all(scope.values())
            or not observation.source_message_id or not observation.pnr
            or observation.facts.get("force_review")
            or getattr(flight, "ownership", None) != "self"
            or getattr(flight, "force_review", False)
            or observation.pnr != booking_code(segment.pnr)
            or scope != _observation_scope(observation)):
        return
    segment.meta_json = {**(segment.meta_json or {}), CREATION_MARKER: {
        "version": CREATION_VERSION, "user_id": user_id, "segment_id": segment.id,
        "observation_id": observation.id, "evidence_key": observation.evidence_key,
        "source_message_id": observation.source_message_id, "pnr": observation.pnr,
        "scope": scope,
    }}


def _has_durable_creation(db, user_id, segment):
    from .booking_ledger import booking_code, flight_scope
    from ..models import BookingObservation
    meta = segment.meta_json or {}
    marker = meta.get(CREATION_MARKER)
    if (not isinstance(marker, dict) or type(marker.get("version")) is not int
            or marker["version"] != CREATION_VERSION or marker.get("user_id") != user_id
            or marker.get("segment_id") != segment.id
            or type(marker.get("observation_id")) is not int
            or marker["observation_id"] not in (meta.get("observation_ids") or [])
            or marker.get("source_message_id") not in (meta.get("source_message_ids") or [])
            or not marker.get("pnr") or marker["pnr"] != booking_code(segment.pnr)
            or marker.get("scope") != flight_scope(segment)):
        return False
    observation = db.get(BookingObservation, marker["observation_id"])
    return bool(observation and observation.user_id == user_id
        and observation.evidence_key == marker.get("evidence_key")
        and observation.source_message_id == marker["source_message_id"]
        and observation.pnr == marker["pnr"] and not observation.facts.get("force_review")
        and observation.ownership in {"self", "unknown"}
        and _observation_scope(observation) == marker["scope"])


def can_retire_new_projection(db, user_id, segment, *, protected_trip_ids=None):
    if not (is_new_projection(user_id, segment.id) or _has_durable_creation(db, user_id, segment)):
        return False
    trip = db.get(Trip, segment.trip_id)
    if trip is None or trip.user_id != user_id:
        return False
    if protected_trip_ids is None:
        from .builder import _protected_trip_ids
        protected_trip_ids = _protected_trip_ids(db, user_id)
    # A later publication or explicit grouping decision withdraws automatic
    # membership authority, including for other members of that same journey.
    if segment.trip_id in protected_trip_ids:
        return False
    from .booking_ledger import user_decision_for_flight
    from .travel_name_recovery import active_shares_for_item
    from ..models import FlightShare, TravelInboxAssignment, TravelInboxEvidence, TravelInboxItem
    meta = segment.meta_json or {}
    if (meta.get("source") in {"manual", "user_review", "accepted_flight_share", "flight_share"}
            or any(meta.get(key) for key in ("personal_note", "manual", "manually_edited", "user_edited", "pnr_aliases"))
            or user_decision_for_flight(db, user_id, segment)):
        return False
    if any(segment.id in (share.accepted_segment_ids or []) for share in
           db.query(FlightShare).filter_by(recipient_user_id=user_id)):
        return False
    ids = meta.get("observation_ids") or []
    items = db.query(TravelInboxItem).join(TravelInboxEvidence).filter(
        TravelInboxItem.user_id == user_id, TravelInboxEvidence.observation_id.in_(ids)).all()
    return not any(db.get(TravelInboxAssignment, item.id) or active_shares_for_item(db, user_id, item.id)
                   for item in items)
