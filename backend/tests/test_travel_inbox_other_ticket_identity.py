"""Exact issued-ticket format corroboration also applies to OTHER receipts."""
from copy import deepcopy
from datetime import datetime, timezone
from itertools import permutations

import pytest

from app.models import BookingObservation, FlightShare, TravelInboxAssignment, TravelInboxEvidence, TravelInboxItem, User
from app.services.passenger_identity import _issued_ticket_key
from app.services.travel_inbox import serialize_item
from test_travel_inbox import session, flight, record
from test_travel_inbox_ticket_identity import FIRST, SECOND, TICKET, DIFFERENT, issued, state


def other(name=FIRST, ticket=TICKET):
    value = flight(name=name, ownership="other", pnr="TEST12")
    for evidence in value.passenger_evidence:
        evidence.update(scope={"pnr": value.pnr}, scope_ambiguous=False)
        if ticket:
            evidence.update(issued_ticket_key=_issued_ticket_key(ticket), issued_ticket_version=1)
    return value


def full_item(row):
    return {column.name: deepcopy(getattr(row, column.name)) for column in row.__table__.columns}


@pytest.mark.parametrize("order", list(permutations(range(3))))
def test_three_other_receipts_reuse_first_item_with_three_links_and_stable_repeats(session, order):
    db, user = session
    names = (FIRST, SECOND, FIRST)
    saved = None
    for index in order:
        record(db, user, other(names[index]), message=f"receipt-{index}")
        item = db.query(TravelInboxItem).one()
        saved = saved or full_item(item)
        assert full_item(item) == saved
    assert item.reason == "other_traveler"
    assert db.query(TravelInboxEvidence).count() == 3
    settled = state(db)
    for _ in range(3):
        for index in reversed(order):
            record(db, user, other(names[index]), message=f"receipt-{index}")
        assert state(db) == settled
    public = serialize_item(db, user.id, item, include_evidence=True)
    assert "issued_ticket" not in str(public) and TICKET not in str(public)


@pytest.mark.parametrize("direction", ["other_to_companion", "companion_to_other"])
def test_name_format_reuse_never_crosses_stored_role(session, direction):
    db, user = session
    left, right = (other(FIRST), issued(SECOND)) if direction == "other_to_companion" else (issued(FIRST), other(SECOND))
    record(db, user, left, message="first")
    old = db.query(TravelInboxItem).one()
    saved = full_item(old)
    record(db, user, right, message="second")
    assert db.query(TravelInboxItem).count() == 2
    assert full_item(old) == saved
    assert {item.reason for item in db.query(TravelInboxItem)} == {"companion", "other_traveler"}
    assert db.query(TravelInboxEvidence).filter_by(item_id=old.id).count() == 1


@pytest.mark.parametrize("protection", ["assignment", "pending", "accepted", "declined", "revoked", "decision"])
def test_protected_other_item_is_unchanged_and_new_format_is_held(session, protection):
    db, user = session
    record(db, user, other(), message="first")
    old = db.query(TravelInboxItem).one()
    if protection == "assignment":
        db.add(TravelInboxAssignment(item_id=old.id, user_id=user.id, passenger_name="Reviewed Person"))
    elif protection == "decision":
        observation = db.query(BookingObservation).one()
        observation.facts = {**observation.facts, "user_decision": {"ownership": "other", "status": "active"}}
    else:
        db.add(FlightShare(sender_id=user.id, recipient_email="recipient@example.test", passenger_name=FIRST,
            client_request_id="request", request_hash="a" * 64, token_hash="b" * 64, token_encrypted=b"encrypted",
            item_ids=[old.id], flights=[], status=protection, expires_at=datetime(2030, 1, 1, tzinfo=timezone.utc)))
    db.flush()
    saved, old_item = state(db), full_item(old)
    assignments = [full_item(row) for row in db.query(TravelInboxAssignment)]
    record(db, user, other(SECOND), message="second")
    assert full_item(old) == old_item
    assert state(db)["flight_shares"] == saved["flight_shares"]
    assert [full_item(row) for row in db.query(TravelInboxAssignment)] == assignments
    assert db.query(TravelInboxEvidence).filter_by(item_id=old.id).count() == 1
    assert {(item.passenger_name, item.reason) for item in db.query(TravelInboxItem)} == {
        (FIRST, "other_traveler"), (None, "unassigned")}


@pytest.mark.parametrize("initial_unknown", [False, True])
def test_unassigned_sources_are_never_claimed_as_named_ticket_authority(session, initial_unknown):
    db, user = session
    initial = other(FIRST)
    incoming = other(SECOND)
    (initial if initial_unknown else incoming).ownership = "unknown"
    record(db, user, initial, message="first")
    old = db.query(TravelInboxItem).one()
    saved = full_item(old)
    record(db, user, incoming, message="second")
    assert db.query(TravelInboxItem).count() == 2
    assert full_item(old) == saved
    assert db.query(TravelInboxEvidence).filter_by(item_id=old.id).count() == 1
    assert {item.reason for item in db.query(TravelInboxItem)} == {"unassigned", "other_traveler"}


@pytest.mark.parametrize("name,ticket", [("Morgan Jordan Blake", TICKET), ("Morgan Blake", TICKET),
    ("Morgan C Blake", TICKET), ("Morgan Casey Smith", TICKET), (SECOND, DIFFERENT)])
def test_different_person_or_issued_ticket_cannot_merge(session, name, ticket):
    db, user = session
    record(db, user, other(), message="first")
    old = db.query(TravelInboxItem).one()
    record(db, user, other(name, ticket), message="second")
    assert db.query(TravelInboxItem).count() == 2
    assert db.query(TravelInboxEvidence).filter_by(item_id=old.id).count() == 1
    assert all(item.reason == "other_traveler" for item in db.query(TravelInboxItem))


@pytest.mark.parametrize("mutation", ["pnr", "route", "number", "date", "account"])
def test_other_reuse_stays_within_exact_account_booking_and_leg(session, mutation):
    db, user = session
    record(db, user, other(), message="first")
    old = db.query(TravelInboxItem).one()
    incoming = other(SECOND)
    if mutation == "pnr":
        incoming.pnr = "ELSE12"
        incoming.passenger_evidence[0]["scope"] = {"pnr": "ELSE12"}
    elif mutation == "route":
        incoming.arr_airport = "DFW"
    elif mutation == "number":
        incoming.flight_number = "NK1652"
    elif mutation == "date":
        incoming.dep_time = incoming.dep_time.replace(day=24)
        incoming.arr_time = incoming.arr_time.replace(day=24)
    else:
        user = User(name="Jamie Avery", email="another@example.test")
        db.add(user)
        db.flush()
    record(db, user, incoming, message="second")
    assert db.query(TravelInboxItem).count() == 2
    assert db.query(TravelInboxEvidence).filter_by(item_id=old.id).count() == 1


@pytest.mark.parametrize("mutation", ["missing", "two_tickets", "bool_version", "wrong_scope", "row_ownership", "force_review"])
def test_uncertain_existing_ticket_evidence_holds_new_name_format(session, mutation):
    db, user = session
    record(db, user, other(), message="first")
    old = db.query(TravelInboxItem).one()
    observation = db.query(BookingObservation).one()
    facts = deepcopy(observation.facts)
    evidence = facts["passenger_evidence"][0]
    if mutation == "missing":
        evidence.pop("issued_ticket_key")
    elif mutation == "two_tickets":
        facts["passenger_evidence"].append({**evidence, "issued_ticket_key": _issued_ticket_key(DIFFERENT)})
    elif mutation == "bool_version":
        evidence["issued_ticket_version"] = True
    elif mutation == "wrong_scope":
        evidence["scope"] = {"pnr": "ELSE12"}
    elif mutation == "row_ownership":
        observation.ownership = "self"
    else:
        facts["force_review"] = True
    observation.facts = facts
    db.flush()
    saved = full_item(old)
    record(db, user, other(SECOND), message="second")
    assert full_item(old) == saved
    assert db.query(TravelInboxEvidence).filter_by(item_id=old.id).count() == 1
    assert {(item.passenger_name, item.reason) for item in db.query(TravelInboxItem)} == {
        (FIRST, "other_traveler"), (None, "unassigned")}


def test_ambiguous_legacy_other_items_are_retained_without_historical_merge(session):
    db, user = session
    record(db, user, other(), message="first")
    old = db.query(TravelInboxItem).one()
    observation = db.query(BookingObservation).one()
    legacy = TravelInboxItem(user_id=user.id, record_key="c" * 64, flight_key=old.flight_key,
        passenger_name="Blake, Morgan Casey", passenger_key="blake, morgan casey", reason="other_traveler")
    db.add(legacy)
    db.flush()
    db.add(TravelInboxEvidence(item_id=legacy.id, observation_id=observation.id))
    db.flush()
    saved = {item.id: full_item(item) for item in (old, legacy)}
    record(db, user, other(SECOND), message="second")
    assert db.query(TravelInboxItem).count() == 3
    for item in (old, legacy):
        assert full_item(item) == saved[item.id]
        assert db.query(TravelInboxEvidence).filter_by(item_id=item.id).count() == 1
    assert db.query(TravelInboxItem).filter_by(reason="unassigned").count() == 1
