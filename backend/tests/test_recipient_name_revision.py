"""Explicit ticket name changes preserve originals and one current recipient."""

from copy import deepcopy
from datetime import datetime, timezone
from itertools import permutations
import json

from fastapi import HTTPException
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import (
    Base,
    BookingObservation,
    TravelInboxItem,
    TravelInboxAssignment,
    FlightShare,
    Segment,
    User,
)
from app.routers.travel_inbox import list_travel_inbox, get_travel_inbox_item
from app.services.booking_import import apply_booking_message
from app.services.booking_legacy_repair import _state
from app.services.flight_times import normalize_flight_times
from app.services.parser import ParsedFlight, ParseResult
from app.services.recipient_name_revision import (
    extract_name_revision_proofs,
    attach_name_revision_evidence,
    _compatible_name_revision,
)
from app.services import travel_sharing

OLD_TICKET = "5261234500001"
NEW_TICKET = "5261234500002"
OWNER_TICKET = "5261234500003"


def receipt(kind="old"):
    is_new = kind == "new"
    names = ["Jordan Casey Blake"] if is_new else ["Alex Morgan", "Jordan Blake"]
    tickets = [NEW_TICKET] if is_new else [OWNER_TICKET, OLD_TICKET]
    roster = "\n".join(
        f"PASSENGER\nRAPID REWARDS #\nTICKET #\nEST. POINTS EARNED\n{name}\nJoin\nor\nLog in\n{ticket}\n0"
        for name, ticket in zip(names, tickets)
    )
    text = f"""Southwest Airlines
Your confirmed trip receipt.
Confirmation #
ABC123
{roster}
Rapid Rewards® points are only estimations. Terms apply.
Your itinerary
Flight 1:
Sunday, 08/01/2027
FLIGHT
# 0101
DEPARTS
HOU 09:00
AM
ARRIVES
PUJ 02:25
PM
Flight 2:
Sunday, 08/08/2027
FLIGHT
# 0202
DEPARTS
PUJ 03:05
PM
ARRIVES
BWI 07:00
PM
Stop:
Change planes
FLIGHT
# 0303
DEPARTS
BWI 09:20
PM
ARRIVES
HOU 11:35
PM
Payment information
"""
    if is_new:
        text += f"Credit from ticket: #{OLD_TICKET} to #{NEW_TICKET}\n{NEW_TICKET}: NAME CHANGE HOU WN PUJ WN BWI WN HOU END\n"
    flights = []
    for day, origin, destination, number, departure, arrival in [
        ("2027-08-01", "HOU", "PUJ", "WN101", "09:00", "14:25"),
        ("2027-08-08", "PUJ", "BWI", "WN202", "15:05", "19:00"),
        ("2027-08-08", "BWI", "HOU", "WN303", "21:20", "23:35"),
    ]:
        flight = ParsedFlight(
            origin,
            destination,
            datetime.fromisoformat(f"{day}T{departure}:00+00:00"),
            datetime.fromisoformat(f"{day}T{arrival}:00+00:00"),
            airline="WN",
            flight_number=number,
            pnr="ABC123",
            source="shape_southwest_itinerary_blocks",
            ownership="other" if is_new else "self",
            passenger_names=names,
            passenger_evidence=[
                {
                    "name": name,
                    "source": "text_passenger_label",
                    "role": "traveler",
                    "complete": True,
                    "applies": True,
                    "scope_ambiguous": False,
                    "scope": {"pnr": "ABC123"},
                }
                for name in names
            ],
        )
        normalize_flight_times(flight)
        flights.append(flight)
    if kind == "reminder":
        text = "Your complete itinerary. Your trip is almost here."
    return text, flights


@pytest.fixture
def session(monkeypatch):
    monkeypatch.setattr("app.services.builder.enrich_segment", lambda *a, **k: None)
    monkeypatch.setenv("ENCRYPTION_KEY", "11" * 32)
    monkeypatch.setenv("TROTTER_API_URL", "https://api.example.test")
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        owner = User(name="Alex Morgan", email="owner@example.test")
        other = User(name="Unrelated Person", email="other@example.test")
        db.add_all([owner, other])
        db.flush()
        yield db, owner, other
    engine.dispose()


def ingest(db, user, kind, *, mutate=None):
    text, flights = receipt(kind)
    if mutate:
        text, flights = mutate(text, flights)
    apply_booking_message(
        db,
        user.id,
        ParseResult(flights=flights),
        source_message_id=kind,
        subject=(
            "Your trip is almost here!" if kind == "reminder" else "Your Southwest trip receipt"
        ),
        plain_text=text,
        received_at={
            "old": "2027-07-01T12:00:00Z",
            "new": "2027-07-15T12:00:00Z",
            "reminder": "2027-07-16T12:00:00Z",
        }[kind],
    )
    db.commit()


def items(db, user):
    return db.query(TravelInboxItem).filter_by(user_id=user.id).all()


def test_ticket_evidence_is_scoped_fingerprinted_and_has_no_itinerary_retirement_authority():
    text, flights = receipt("new")
    proofs = attach_name_revision_evidence(text, flights)
    assert len(proofs) == 3 and all(p["name_change"] for p in proofs)
    assert OLD_TICKET not in json.dumps(proofs) and NEW_TICKET not in json.dumps(proofs)
    assert len({p["ticket_key"] for p in proofs}) == 1
    assert len({p["scope"]["flight_number"] for p in proofs}) == 3
    assert all(not getattr(f, "booking_ticket", None) for f in flights)


@pytest.mark.parametrize(
    "mutation",
    [
        "credit_only",
        "wrong_current",
        "same_tickets",
        "two_chains",
        "missing_leg",
        "duplicate_leg",
        "wrong_weekday",
        "wrong_date_scope",
        "wrong_route_scope",
        "unknown_owner",
        "incomplete_name",
        "unscoped_name",
        "unnormalized",
        "other_booking",
    ],
)
def test_incomplete_or_conflicting_source_cannot_establish_a_revision(mutation):
    text, flights = receipt("new")
    if mutation == "credit_only":
        text = text.replace("NAME CHANGE", "TICKET CREDIT")
    if mutation == "wrong_current":
        text = text.replace(f"to #{NEW_TICKET}", f"to #{OWNER_TICKET}")
    if mutation == "same_tickets":
        text = text.replace(f"from ticket: #{OLD_TICKET}", f"from ticket: #{NEW_TICKET}")
    if mutation == "two_chains":
        text += f"Credit from ticket: #{OWNER_TICKET} to #{NEW_TICKET}\n"
    if mutation == "missing_leg":
        flights.pop()
    if mutation == "duplicate_leg":
        flights.append(deepcopy(flights[0]))
    if mutation == "wrong_weekday":
        text = text.replace("Sunday, 08/01/2027", "Monday, 08/01/2027")
    if mutation == "wrong_date_scope":
        flights[0].passenger_evidence[0]["scope"]["departure_date"] = "2027-08-02"
    if mutation == "wrong_route_scope":
        flights[0].passenger_evidence[0]["scope"]["dep_airport"] = "ORD"
    if mutation == "unknown_owner":
        flights[0].ownership = "unknown"
    if mutation == "incomplete_name":
        flights[0].passenger_evidence[0]["complete"] = False
    if mutation == "unscoped_name":
        flights[0].passenger_evidence[0]["scope"] = {}
    if mutation == "unnormalized":
        flights[0].time_provenance = {}
    if mutation == "other_booking":
        text = "Confirmation #\nOTHER1\n" + text
    assert extract_name_revision_proofs(text, flights) == []


@pytest.mark.parametrize(
    "names",
    [
        ("Jordan Blake", "Avery Casey Blake"),
        ("Jordan Blake", "Jordan Casey Brown"),
        ("Jordan Lee Blake", "Jordan Casey Blake"),
        ("Jordan de Blake", "Jordan Blake"),
        ("Anna Bella Blake", "Annabella Blake"),
        ("J Blake", "Jordan Blake"),
    ],
)
def test_name_similarity_without_exact_permitted_components_is_never_authority(names):
    assert not _compatible_name_revision(*names)


@pytest.mark.parametrize("order", list(permutations(("old", "new", "reminder"))))
def test_source_order_read_projection_and_repeated_imports_preserve_all_originals(session, order):
    db, user, other = session
    unrelated = deepcopy(_state(db, other.id))
    saved = {}
    for kind in order:
        ingest(db, user, kind)
        for item in items(db, user):
            row = {c.name: getattr(item, c.name) for c in item.__table__.columns}
            if item.id in saved:
                assert row == saved[item.id]
            else:
                saved[item.id] = row
    assert len(saved) == 6 and db.query(Segment).count() == 3
    first = deepcopy(_state(db, user.id))
    visible = travel_sharing.inbox(db, user)["items"]
    assert len(visible) == 3 and {v["passenger_name"] for v in visible} == {"Jordan Casey Blake"}
    assert (
        sum(v["shareable"] for v in visible) == 2
    )  # Existing cross-UTC-date guard remains intact.
    assert _state(db, user.id) == first
    for old in [i for i in items(db, user) if i.passenger_name == "Jordan Blake"]:
        detail = get_travel_inbox_item(item_id=old.id, current_user=user, db=db)
        assert (
            detail["status"] == "needs_review"
            and detail["evidence"]
            and detail["recipient_revision"]["state"] == "superseded"
        )
        with pytest.raises(HTTPException):
            travel_sharing._validate_item(db, old)
        with pytest.raises(HTTPException):
            travel_sharing.assign(db, user, old.id, old.passenger_name)
    for kind in reversed(order):
        ingest(db, user, kind)
    settled = deepcopy(_state(db, user.id))
    for _ in range(3):
        for kind in order:
            ingest(db, user, kind)
        assert _state(db, user.id) == settled
    assert all(settled["observations"][k] == v for k, v in first["observations"].items())
    assert _state(db, other.id) == unrelated


def test_empty_superseded_page_retains_cursor_to_reach_current_rows(session):
    db, user, _ = session
    ingest(db, user, "new")
    ingest(db, user, "old")
    cursor = None
    visible = []
    empty_pages = 0
    for _ in range(10):
        page = list_travel_inbox(limit=1, before_id=cursor, current_user=user, db=db)
        visible.extend(page["items"])
        if not page["items"]:
            empty_pages += 1
            assert page["next_cursor"]
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert (
        empty_pages == 3
        and len(visible) == 3
        and {v["passenger_name"] for v in visible} == {"Jordan Casey Blake"}
    )


@pytest.mark.parametrize("mutation", ["missing_credit", "extra_credit", "wrong_weekday"])
def test_explicit_but_unresolved_name_change_is_retained_without_sharing(session, mutation):
    db, user, _ = session
    ingest(db, user, "old")

    def mutate(text, flights):
        if mutation == "missing_credit":
            text = text.replace("Credit from ticket:", "Transferable credit:")
        if mutation == "extra_credit":
            text += f"Credit from ticket: #{OWNER_TICKET} to #{NEW_TICKET}\n"
        if mutation == "wrong_weekday":
            text = text.replace("Sunday, 08/01/2027", "Monday, 08/01/2027")
        return text, flights

    ingest(db, user, "new", mutate=mutate)
    current = travel_sharing.inbox(db, user)["items"]
    assert len(current) == 6
    new = [v for v in current if v["passenger_name"] == "Jordan Casey Blake"]
    assert len(new) == 3 and all(v["status"] == "needs_review" and not v["shareable"] for v in new)


@pytest.mark.parametrize(
    "protected_kind", ["assignment", "pending", "accepted", "declined", "revoked"]
)
def test_predecessor_protection_keeps_original_visible_without_transferring_it(
    session, protected_kind
):
    db, user, _ = session
    ingest(db, user, "old")
    old = next(
        i
        for i in items(db, user)
        if travel_sharing.inbox_item_view(db, user.id, i)["flight"]["flight_number"] == "WN101"
    )
    if protected_kind == "assignment":
        travel_sharing.assign(db, user, old.id, old.passenger_name)
    else:
        result = travel_sharing.create_share(
            db, user, [old.id], "recipient@example.test", old.passenger_name
        )
        db.get(FlightShare, result["share"]["id"]).status = protected_kind
    db.commit()
    saved = deepcopy(_state(db, user.id))
    ingest(db, user, "new")
    views = travel_sharing.inbox(db, user)["items"]
    assert old.id in {v["id"] for v in views}
    successor = next(
        v
        for v in views
        if v["passenger_name"] == "Jordan Casey Blake" and v["flight"]["flight_number"] == "WN101"
    )
    assert successor["status"] == "needs_review" and not successor["shareable"]
    for table in ("inbox", "assignments", "shares", "observations", "retained_links"):
        assert all(_state(db, user.id)[table].get(k) == v for k, v in saved[table].items())


@pytest.mark.parametrize("protection", ["assignment", "pending", "accepted"])
def test_current_successor_share_or_assignment_does_not_resurrect_predecessor(session, protection):
    db, user, _ = session
    ingest(db, user, "old")
    ingest(db, user, "new")
    item = next(
        i
        for i in items(db, user)
        if i.passenger_name == "Jordan Casey Blake"
        and travel_sharing.inbox_item_view(db, user.id, i)["flight"]["flight_number"] == "WN101"
    )
    if protection == "assignment":
        travel_sharing.assign(db, user, item.id, item.passenger_name)
    else:
        result = travel_sharing.create_share(
            db, user, [item.id], "recipient@example.test", item.passenger_name
        )
        db.get(FlightShare, result["share"]["id"]).status = protection
    db.commit()
    saved = deepcopy(_state(db, user.id))
    assert (
        len(travel_sharing.inbox(db, user)["items"]) == 3
        and travel_sharing.inbox_item_view(db, user.id, item)["shareable"]
    )
    assert _state(db, user.id) == saved


@pytest.mark.parametrize("target_role", ["companion", "unassigned"])
def test_immutable_item_role_cannot_borrow_another_ownerships_ticket_authority(
    session, target_role
):
    db, user, _ = session
    ingest(db, user, "old")
    ingest(db, user, "new")
    for item in items(db, user):
        if item.passenger_name == "Jordan Casey Blake":
            item.reason = target_role
    db.commit()
    views = travel_sharing.inbox(db, user)["items"]
    assert len(views) == 6 and all(
        not v["shareable"] for v in views if v["passenger_name"] == "Jordan Casey Blake"
    )


@pytest.mark.parametrize(
    "evidence",
    [None, False, "unparsed legacy evidence", {"name": "Jordan Blake"}, [None, "invalid"]],
)
def test_malformed_historical_passenger_evidence_is_read_without_new_authority(session, evidence):
    db, user, _ = session
    ingest(db, user, "old")
    ingest(db, user, "new")
    for row in db.query(BookingObservation).filter_by(user_id=user.id, source_message_id="old"):
        row.facts = dict(row.facts, passenger_evidence=deepcopy(evidence))
    db.commit()
    before = deepcopy(_state(db, user.id))
    views = travel_sharing.inbox(db, user)["items"]
    assert len(views) == 6
    assert all(
        not view["shareable"] for view in views if view["passenger_name"] == "Jordan Casey Blake"
    )
    assert _state(db, user.id) == before


def test_competing_explicit_name_change_successors_remain_visible_and_held(session):
    db, user, _ = session
    ingest(db, user, "old")
    ingest(db, user, "new")
    before = deepcopy(_state(db, user.id))
    text, flights = receipt("new")
    text = text.replace("Jordan Casey Blake", "Jordan Taylor Blake").replace(
        NEW_TICKET, "5261234500004"
    )
    for flight in flights:
        flight.passenger_names = ["Jordan Taylor Blake"]
        flight.passenger_evidence[0]["name"] = "Jordan Taylor Blake"
    apply_booking_message(
        db,
        user.id,
        ParseResult(flights=flights),
        source_message_id="competing-new",
        subject="Your Southwest trip receipt",
        plain_text=text,
        received_at="2027-07-16T12:00:00Z",
    )
    db.commit()
    views = travel_sharing.inbox(db, user)["items"]
    assert len(views) == 9
    successors = [view for view in views if view["passenger_name"] != "Jordan Blake"]
    assert len(successors) == 6 and all(
        view["status"] == "needs_review" and not view["shareable"] for view in successors
    )
    after = _state(db, user.id)
    for table in ("inbox", "observations", "retained_links"):
        assert all(after[table].get(key) == value for key, value in before[table].items())


@pytest.mark.parametrize("source", ["old", "new"])
def test_user_decision_is_never_transferred_to_another_named_ticket(session, source):
    from app.services.booking_ledger import record_user_decision

    db, user, _ = session
    ingest(db, user, "old")
    ingest(db, user, "new")
    original = (
        db.query(BookingObservation)
        .filter_by(user_id=user.id, source_message_id=source, flight_number="WN101")
        .one()
    )
    decision = record_user_decision(
        db,
        user.id,
        receipt(source)[1][0],
        ownership="other",
        status="hold",
        source_observation_id=original.id,
    )
    db.commit()
    before = deepcopy(_state(db, user.id))
    views = travel_sharing.inbox(db, user)["items"]
    pair = [view for view in views if view["flight"]["flight_number"] == "WN101"]
    assert len(pair) == 2
    assert not next(view for view in pair if view["passenger_name"] == "Jordan Casey Blake")[
        "shareable"
    ]
    assert _state(db, user.id) == before and decision.id in {
        row.id for row in db.query(BookingObservation)
    }


def test_same_tickets_in_another_account_cannot_supply_predecessor_authority(session):
    db, user, other = session
    ingest(db, user, "old")
    ingest(db, other, "new")
    before = deepcopy(_state(db, user.id))
    views = travel_sharing.inbox(db, other)["items"]
    assert len(views) == 3 and all(
        view["status"] == "needs_review" and not view["shareable"] for view in views
    )
    assert _state(db, user.id) == before
    with pytest.raises(HTTPException) as exc:
        get_travel_inbox_item(item_id=items(db, user)[0].id, current_user=other, db=db)
    assert exc.value.status_code == 404
