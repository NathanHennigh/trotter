"""Project exact named ticket exchanges while retaining every original fact."""
from ..models import BookingObservation, ItineraryHistory, Segment, Trip
from .booking_ledger import (_key, booking_code, event_time, flight_scope,
                             snapshot_user_itinerary, user_decision_for_flight)
from .ticket_revision_evidence import ticket_supersedes

VERSION = 2


def enabled(user_id):
    from .flight_import_rollout import enabled as account_enabled
    return account_enabled("BOOKING_LEG_RECONCILIATION_ENABLED", user_id)


def requires_reconciliation_for_creation(user_id, flight):
    """New ticket-card recovery needs its exact exchange reconciler enabled.

    Older supported extractors retain their normal import behavior. Newly
    recovered Alaska cards can contain an original or replacement ticket, and
    either can arrive first. Missing/multi-person ticket details do not bypass
    this template rollout boundary or grant inferred exchange authority.
    """
    from .southwest_ticket_revision import SOURCE
    ticket = getattr(flight, "booking_ticket", None)
    explicit_southwest_change = (isinstance(ticket, dict) and ticket.get("source") == SOURCE
                                and ticket.get("change_confirmed") is True)
    return (not enabled(user_id) and (getattr(flight, "source", None) == "shape_alaska_trip_detail_blocks"
                                     or explicit_southwest_change))


def holds_new_ticket_projection(db, user_id, flight):
    if not requires_reconciliation_for_creation(user_id, flight):
        return False
    from .booking_ledger import _same_cancellation_leg
    scope = flight_scope(flight)
    # Existing/adopted rows retain normal matching and protection checks. This
    # gate supplies no retrospective deletion or new ownership authority.
    return not any(_same_cancellation_leg(scope, flight_scope(segment)) for segment in
        db.query(Segment).join(Trip).filter(Trip.user_id == user_id,
            Segment.pnr == booking_code(flight.pnr)).all())


def _scope(observation):
    return {"travel_date": observation.travel_date, "dep_airport": observation.dep_airport,
            "arr_airport": observation.arr_airport, "flight_number": observation.flight_number}


def _successors(db, user_id, original):
    ticket = (original.facts or {}).get("booking_ticket")
    if not ticket or original.user_id != user_id or not original.source_message_id:
        return []
    candidates = db.query(BookingObservation).filter_by(user_id=user_id,
        pnr=original.pnr, ownership="self").order_by(BookingObservation.id).all()
    return [row for row in candidates if row.source_message_id
        and ticket_supersedes(original.facts, row.facts,
            previous_event_at=original.source_event_at, successor_event_at=row.source_event_at)]


def superseded_ticket_flight(db, user_id, flight):
    if not enabled(user_id) or user_decision_for_flight(db, user_id, flight):
        return False
    original = db.get(BookingObservation, getattr(flight, "observation_id", None))
    if getattr(flight, "booking_ticket", None):
        return bool(original and _successors(db, user_id, original))
    if (getattr(flight, "ownership", None) != "self"
            or (getattr(flight, "booking_lifecycle", None) or {}).get("kind") != "operational_notice"):
        return False
    scope = flight_scope(flight)
    if not all(scope.values()):
        return False
    originals = db.query(BookingObservation).filter_by(user_id=user_id,
        pnr=booking_code(getattr(flight, "pnr", None)), ownership="self", **scope).all()
    return any(_successors(db, user_id, row) for row in originals)


def _exact_southwest_legacy_match(segment, observation, successor, observations):
    """Bind a prior projection only to a fully proven exchanged physical leg."""
    from .southwest_ticket_revision import validated
    facts = observation.facts
    if not validated(facts) or _scope(observation) != flight_scope(segment):
        return False
    meta = segment.meta_json or {}
    if meta.get("pnr_aliases"):
        return False
    ids = set(meta.get("observation_ids") or [])
    if ids:
        attached = [observations.get(value) for value in ids]
        if (any(row is None for row in attached)
                or observation.source_message_id not in {row.source_message_id for row in attached}
                or set(meta.get("source_message_ids") or []) != {row.source_message_id for row in attached}
                or any(row.ownership != "self" or row.pnr != observation.pnr
                       or _scope(row) != _scope(observation)
                       or not isinstance(row.facts,dict) or row.facts.get("force_review")
                       or row.facts.get("user_decision") or row.facts.get("booking_ticket")
                       or any(row.facts.get(field) != facts.get(field)
                              for field in ("pnr","dep_airport","arr_airport","flight_number"))
                       or any(event_time(row.facts.get(field)) != event_time(facts.get(field))
                              for field in ("dep_time","arr_time"))
                       for row in attached)):
            return False
    current_event = event_time(meta.get("source_received_at"))
    if (current_event and current_event >= event_time(successor.source_event_at)
            and not (ids and any(event_time(row.source_event_at) == current_event
                                 and ((row.facts or {}).get("booking_lifecycle") or {}).get("kind") == "operational_notice"
                                 for row in attached))):
        return False
    full = all(event_time(getattr(segment, field)) == event_time(facts.get(field))
               for field in ("dep_time", "arr_time"))
    if full:
        return True
    if meta.get("time_provenance"):
        return False
    provenance = facts.get("time_provenance")
    if not isinstance(provenance, dict) or provenance.get("status") != "normalized":
        return False
    return all(isinstance(provenance.get(endpoint), dict)
               and event_time(provenance[endpoint].get("local")) is not None
               and event_time(getattr(segment, field)) == event_time(provenance[endpoint]["local"])
               for field, endpoint in (("dep_time", "departure"), ("arr_time", "arrival")))


def _competing_southwest_successors(observations):
    """Conflicting exact exchanges share one proven old named ticket/leg.

    Different issued tickets alone are not a conflict when their physical leg
    is unchanged. A later schedule on the same successor ticket also retains
    the ordinary chronology policy.
    """
    from .southwest_ticket_revision import validated
    def consistent(row):
        proof = validated(row.facts)
        return bool(proof and row.ownership == "self" and row.pnr == row.facts.get("pnr")
            and row.travel_date == row.facts["time_provenance"]["departure_local_date"]
            and all(getattr(row, field) == row.facts.get(field)
                    for field in ("dep_airport", "arr_airport", "flight_number")))
    observations = [row for row in observations if consistent(row)]
    groups = {}
    for old in observations:
        proof = validated(old.facts)
        if not proof:
            continue
        successors = [row for row in observations if ticket_supersedes(old.facts, row.facts,
            previous_event_at=old.source_event_at, successor_event_at=row.source_event_at)]
        if len({row.facts["booking_ticket"]["ticket_key"] for row in successors}) < 2:
            continue
        # Number changes alone on the exact same dated route remain normal
        # later schedule updates. Distinct routes/dates require review.
        routes = {(row.travel_date, row.dep_airport, row.arr_airport) for row in successors}
        if len(routes) < 2:
            continue
        key = (proof[0]["ticket_key"], proof[1], old.pnr, tuple(_scope(old).values()))
        group = groups.setdefault(key, {"old": {}, "new": {}})
        group["old"][old.id] = old
        group["new"].update({row.id: row for row in successors})
    return list(groups.values())


def _hold_competing_successors(db, user_id, observations, flights, protected_trips):
    from .booking_projection_context import can_retire_new_projection
    from .southwest_ticket_revision import validated
    def normalized_scope(row, scope, pnr):
        facts = row.facts
        if (not isinstance(facts, dict) or row.pnr != pnr or facts.get("pnr") != pnr
                or _scope(row) != scope or not row.source_message_id
                or row.ownership not in {"self", "unknown"} or facts.get("force_review") or facts.get("user_decision")
                or any(facts.get(key) != scope[key] for key in ("dep_airport", "arr_airport", "flight_number"))):
            return False
        proof = facts.get("time_provenance")
        if (not isinstance(proof, dict) or type(proof.get("version")) is not int or proof["version"] != 1
                or proof.get("status") != "normalized" or proof.get("departure_local_date") != scope["travel_date"]):
            return False
        dep, arr = event_time(facts.get("dep_time")), event_time(facts.get("arr_time"))
        return bool(dep and arr and 0 < (arr-dep).total_seconds() <= 24*3600 and all(
            isinstance(proof.get(endpoint), dict) and proof[endpoint].get("airport") == scope[airport]
            and event_time(proof[endpoint].get("utc")) == event_time(facts.get(clock))
            for endpoint, airport, clock in (("departure", "dep_airport", "dep_time"), ("arrival", "arr_airport", "arr_time"))))
    affected = set()
    held_retirements = 0
    for group in _competing_southwest_successors(observations):
        successors = list(group["new"].values())
        scopes = [_scope(row) for row in successors]
        old_scopes = [_scope(row) for row in group["old"].values()]
        pnr = successors[0].pnr
        latest_exchange = max(event_time(row.source_event_at) for row in successors)
        independent = {row.id for row in observations if row.id not in group["old"] and row.id not in group["new"]
            and (proof := validated(row.facts)) and not proof[0].get("previous_ticket_key")
            and row.pnr == pnr and _scope(row) in scopes
            and ((row.facts or {}).get("booking_lifecycle") or {}).get("can_reinstate") is True
            and event_time(row.source_event_at) is not None and event_time(row.source_event_at) > latest_exchange}
        conflict = {"reason": "competing_ticket_successors", "pnr": pnr,
            "previous_observation_ids": sorted(group["old"]),
            "successor_observation_ids": sorted(group["new"]),
            "scopes": sorted(scopes, key=lambda value: tuple(str(v) for v in value.values()))}
        for flight in flights:
            if (booking_code(flight.pnr) == pnr and getattr(flight, "ownership", None) in {"self", "unknown"}
                    and flight_scope(flight) in scopes + old_scopes
                    and getattr(flight, "observation_id", None) not in independent
                    and not user_decision_for_flight(db, user_id, flight)):
                flight.ticket_successor_conflict = True
        for segment in db.query(Segment).join(Trip).filter(Trip.user_id == user_id, Segment.pnr == pnr).all():
            scope = flight_scope(segment)
            if scope not in scopes:
                continue
            meta = segment.meta_json or {}
            ids = set(meta.get("observation_ids") or [])
            linked = db.query(BookingObservation).filter(BookingObservation.user_id == user_id,
                BookingObservation.id.in_(ids)).all() if ids else []
            exact = [row for row in linked if normalized_scope(row, scope, pnr) and all(
                event_time(getattr(segment, field)) == event_time(row.facts.get(field))
                for field in ("dep_time", "arr_time"))]
            # Adopted rows can be annotated, but only exact new projections
            # supported solely by this conflict or its reminders may retire.
            exclusive = bool(linked) and {row.id for row in linked} == ids and all(
                normalized_scope(row, scope, pnr) and (row.id in group["new"] or row.ownership == "unknown"
                    or ((row.facts or {}).get("booking_lifecycle") or {}).get("kind") == "operational_notice")
                for row in linked)
            if exact and exclusive and can_retire_new_projection(db, user_id, segment,
                    protected_trip_ids=protected_trips):
                snapshot_user_itinerary(db, user_id, reason="competing_ticket_successors",
                    segment_ids={segment.id}, trip_ids={segment.trip_id})
                affected.add(segment.trip_id)
                db.delete(segment)
                held_retirements += 1
            elif conflict not in (meta.get("booking_conflicts") or []):
                snapshot_user_itinerary(db, user_id, reason="before_ticket_conflict_annotation",
                    segment_ids={segment.id}, trip_ids={segment.trip_id})
                segment.meta_json = {**meta, "booking_conflicts": [*(meta.get("booking_conflicts") or []), conflict]}
    db.flush()
    return affected, held_retirements


def reconcile_ticket_revisions(db, user_id, flights):
    """Retire only rows linked to exchanged tickets; preserve manual/alias data."""
    if not enabled(user_id):
        return set(), 0, 0
    from .booking_legacy_repair import _protected
    from .builder import _first_active_pnr_alias, _protected_trip_ids
    from .travel_name_recovery import active_shares_for_item
    from ..models import TravelInboxAssignment, TravelInboxEvidence, TravelInboxItem

    codes = {booking_code(flight.pnr) for flight in flights if getattr(flight, "booking_ticket", None)
             or (getattr(flight, "ownership", None) in {"self", "unknown"}
                 and getattr(flight, "airline", None) == "WN")} - {None}
    if not codes:
        return set(), 0, 0
    affected, retired, held_retirements = set(), 0, 0
    protected_trips = _protected_trip_ids(db, user_id)
    for code in codes:
        observations = db.query(BookingObservation).filter_by(user_id=user_id, pnr=code, ownership="self").all()
        conflict_affected, held_count = _hold_competing_successors(db, user_id, observations, flights, protected_trips)
        affected.update(conflict_affected)
        held_retirements += held_count
        replacements = {row.id: (row, successors[0]) for row in observations
                        if (successors := _successors(db, user_id, row))}
        if not replacements:
            continue
        segments = db.query(Segment).join(Trip).filter(Trip.user_id == user_id, Segment.pnr == code).all()
        observations_by_id = {row.id: row for row in observations}
        legacy_bindings = {}
        for oid, (old, new) in replacements.items():
            exact = [segment for segment in segments if _exact_southwest_legacy_match(segment, old, new, observations_by_id)]
            if len(exact) == 1:
                legacy_bindings.setdefault(exact[0].id, set()).add(oid)
        for segment in segments:
            meta = segment.meta_json or {}
            ids = set(meta.get("observation_ids") or [])
            scope = flight_scope(segment)
            matched = {value for value in ids.intersection(replacements)
                       if _scope(replacements[value][0]) == scope}
            matched.update(legacy_bindings.get(segment.id, set()))
            attached = db.query(BookingObservation).filter(BookingObservation.user_id == user_id,
                BookingObservation.id.in_(ids)).all()
            if (not matched and attached and {row.id for row in attached} == ids
                    and all(row.pnr == code and row.ownership == "self" and _scope(row) == scope
                            and not (row.facts or {}).get("force_review")
                            and ((row.facts or {}).get("booking_lifecycle") or {}).get("kind") == "operational_notice"
                            for row in attached)):
                # A stale reminder may arrive before the old ticket. Once the
                # exact exchanged ticket appears, its dated legs identify that
                # operational-only projection without a route/date guess.
                matched = {value for value, (old, _) in replacements.items() if _scope(old) == scope}
            from .southwest_ticket_revision import SOURCE
            southwest = any(replacements[value][0].facts["booking_ticket"].get("source") == SOURCE for value in matched)
            if not matched or segment.trip_id in protected_trips or _protected(db, user_id, segment):
                continue
            if southwest and any(row.id not in matched and row.ownership == "self" and _scope(row) == scope
                   and not (row.facts or {}).get("force_review")
                   and ((row.facts or {}).get("booking_lifecycle") or {}).get("can_reinstate") is True
                   and event_time(row.source_event_at) is not None
                   and any(event_time(row.source_event_at) >= event_time(replacements[value][1].source_event_at)
                           for value in matched)
                   for row in observations):
                # A later independently confirmed purchase is not the old
                # exchanged ticket merely because its physical route matches.
                continue
            schedule = (segment.dep_airport, segment.arr_airport, segment.flight_number,
                        event_time(segment.dep_time), event_time(segment.arr_time))
            if any((leg.get("dep_airport"), leg.get("arr_airport"), leg.get("flight_number"),
                    event_time(leg.get("dep_time")), event_time(leg.get("arr_time"))) == schedule
                   for value in matched for leg in replacements[value][1].facts["booking_ticket"]["legs"]):
                # An exchanged ticket can keep one physical leg unchanged.
                # The builder will attach its successor evidence to this ID.
                continue
            # An unchanged physical leg may also carry a current ticket.
            linked = db.query(BookingObservation).filter(BookingObservation.user_id == user_id,
                BookingObservation.id.in_(ids - matched)).all()
            if any(row.ownership == "self" and not (row.facts or {}).get("force_review")
                   and _scope(row) == scope
                   and (row.facts or {}).get("booking_ticket") for row in linked):
                continue
            items = db.query(TravelInboxItem).join(TravelInboxEvidence).filter(
                TravelInboxItem.user_id == user_id, TravelInboxEvidence.observation_id.in_(ids)).all()
            if any(db.get(TravelInboxAssignment, item.id) or active_shares_for_item(db, user_id, item.id)
                   for item in items):
                continue
            old, new = replacements[min(matched)]
            snapshot_user_itinerary(db, user_id, reason="before_explicit_ticket_exchange",
                                    segment_ids={segment.id}, trip_ids={segment.trip_id})
            link = {"segment_id": segment.id, "previous_observation_ids": sorted(matched),
                "successor_observation_id": new.id, "previous_ticket": old.facts["booking_ticket"],
                "successor_ticket": new.facts["booking_ticket"]}
            digest = _key(link)
            if not db.query(ItineraryHistory).filter_by(user_id=user_id, evidence_key=digest).first():
                db.add(ItineraryHistory(user_id=user_id, entity_type="ticket_exchange", entity_id=segment.id,
                    reason="explicit_previous_ticket", evidence_key=digest, snapshot=link))
            affected.add(segment.trip_id)
            alias = _first_active_pnr_alias(db, user_id, segment, code)
            if alias:
                segment.pnr = alias
                segment.meta_json = {**meta, "pnr_aliases": [value for value in meta.get("pnr_aliases", [])
                                                            if value not in {code, alias}]}
            else:
                db.delete(segment)
                retired += 1
    db.flush()
    return affected, retired, held_retirements
