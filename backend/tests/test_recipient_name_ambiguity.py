"""A missing middle name on one booked leg is insufficient proof of identity."""
from datetime import datetime
import gzip
import json
import os

from fastapi import HTTPException
import pytest
from sqlalchemy import DateTime, create_engine
from sqlalchemy.orm import Session

from app.models import Base, FlightShare, TravelInboxItem, User
from app.services import travel_sharing
from app.services.passenger_identity import _issued_ticket_key
from app.services.travel_inbox import serialize_item
from test_travel_inbox import flight, record, session
from test_travel_inbox_ticket_identity import state


SHORT, LONG = "Jordan Blake", "Jordan Casey Blake"
FIRST, SECOND = "0161234567890", "0161234567891"


def add_source(db, owner, name, ticket, *, number="NK1651", pnr="DEMO12"):
    f = flight(name=name, pnr=pnr, number=number)
    if ticket:
        f.passenger_evidence[0].update(
            scope={"pnr": pnr}, scope_ambiguous=False,
            issued_ticket_key=_issued_ticket_key(ticket), issued_ticket_version=1,
        )
    record(db, owner, f, message=f"{pnr}-{number}-{name}")


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("short_ticket,long_ticket,shareable", [
    (None, None, set()),
    (None, FIRST, {LONG}),
    (FIRST, None, {SHORT}),
    (FIRST, SECOND, {SHORT, LONG}),
    (FIRST, FIRST, set()),  # Without a verified revision neither name wins a tie.
])
def test_recipients_on_one_leg(session, reverse, short_ticket, long_ticket, shareable):
    db, owner = session
    sources = [(SHORT, short_ticket), (LONG, long_ticket)]
    for name, ticket in reversed(sources) if reverse else sources:
        add_source(db, owner, name, ticket)
    before = state(db)
    views = travel_sharing.inbox(db, owner)["items"]
    assert len(views) == 2 and {v["passenger_name"] for v in views} == {SHORT, LONG}
    assert {v["passenger_name"] for v in views if v["shareable"]} == shareable
    for v in views:
        if v["passenger_name"] in shareable:
            continue
        item = db.get(TravelInboxItem, v["id"])
        assert serialize_item(db, owner.id, item)["recipient_revision"] == {
            "state": "needs_review", "reason": "ambiguous_passenger_name",
        }
        with pytest.raises(HTTPException) as blocked:
            travel_sharing.create_share(db, owner, [item.id], "recipient@example.test", item.passenger_name)
        assert blocked.value.status_code == 422 and "versions" in blocked.value.detail
    assert db.query(FlightShare).count() == 0 and state(db) == before


@pytest.mark.parametrize("pnr,number", [("DEMO12", "NK1652"), ("OTHER1", "NK1651")])
def test_name_variants_on_different_bookings_or_legs_stay_shareable(session, pnr, number):
    db, owner = session
    add_source(db, owner, SHORT, None)
    add_source(db, owner, LONG, None, pnr=pnr, number=number)
    views = travel_sharing.inbox(db, owner)["items"]
    assert len(views) == 2 and all(v["shareable"] for v in views)


def test_prior_named_invitation_is_still_usable_and_new_variant_is_held(session, monkeypatch):
    monkeypatch.setenv("ENCRYPTION_KEY", "11" * 32)
    monkeypatch.setenv("TROTTER_API_URL", "https://api.example.test")
    db, owner = session
    add_source(db, owner, SHORT, None)
    original = db.query(TravelInboxItem).one()
    travel_sharing.create_share(db, owner, [original.id], "recipient@example.test", SHORT)
    add_source(db, owner, LONG, None)
    views = travel_sharing.inbox(db, owner)["items"]
    assert {v["id"] for v in views if v["shareable"]} == {original.id}
    assert db.query(FlightShare).one().item_ids == [original.id]


@pytest.mark.skipif(not os.getenv("TROTTER_RECIPIENT_REPLAY_FIXTURE"), reason="private saved cases not provided")
def test_saved_recipient_sharing_cases(monkeypatch):
    """Replay audited decisions through the real list and invitation code in memory."""
    with gzip.open(os.environ["TROTTER_RECIPIENT_REPLAY_FIXTURE"], "rt", encoding="utf8") as f:
        fixture = json.load(f)
    assert fixture["cases"] and len({c["item_id"] for c in fixture["cases"]}) == len(fixture["cases"])
    monkeypatch.setenv("ENCRYPTION_KEY", "11" * 32)
    monkeypatch.setenv("TROTTER_API_URL", "https://api.example.test")
    engine = create_engine("sqlite:///:memory:")
    try:
        Base.metadata.create_all(engine)
        with Session(engine) as db:
            for table in Base.metadata.sorted_tables:
                for row in fixture["tables"].get(table.name, []):
                    values = {
                        key: datetime.fromisoformat(value) if value and isinstance(table.c[key].type, DateTime) else value
                        for key, value in row.items()
                    }
                    db.execute(table.insert().values(**values))
            db.commit()
            owner = db.get(User, fixture["owner_id"])
            before = state(db)
            visible = {v["id"]: v for v in travel_sharing.inbox(db, owner)["items"]}
            failures = []
            for case in fixture["cases"]:
                item = db.get(TravelInboxItem, case["item_id"])
                view = visible.get(case["item_id"], {})
                expected = case["shareable"]
                if view.get("shareable") is not expected:
                    failures.append(case["case"] + "/list")
                with db.begin_nested() as attempt:
                    try:
                        travel_sharing.create_share(db, owner, [item.id], "recipient@example.test", item.passenger_name)
                        allowed = True
                    except HTTPException as exc:
                        if exc.status_code != 422 or "versions of this passenger" not in exc.detail:
                            failures.append(case["case"] + "/unexpected-rejection")
                        allowed = False
                    if allowed != expected:
                        failures.append(case["case"] + "/invitation")
                    attempt.rollback()
            if failures:
                pytest.fail(", ".join(failures), pytrace=False)
            if state(db) != before:
                pytest.fail("Saved evidence changed during sharing checks", pytrace=False)
    finally:
        engine.dispose()
