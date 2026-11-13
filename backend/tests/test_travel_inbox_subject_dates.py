"""Untrusted subject dates stay in evidence, not the owner's display projection."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import event, select

from app.models import Base, BookingCancellation, BookingObservation, TravelInboxEvidence
from app.routers.travel_inbox import router as inbox_router
from app.services.travel_inbox import serialize_item
from app.services.travel_sharing import inbox_item_view
from test_travel_sharing import api, create, seed


REASON = "subject_only_itinerary_requires_review"


def held(api, **kwargs):
    item, observation = seed(api, force_review=True, **kwargs)
    observation.facts = {**observation.facts, "source": "subject",
        "time_provenance": {"version": 1, "status": "normalized",
            "extraction_review_reason": REASON,
            "departure_local_date": observation.travel_date}}
    api.db.commit()
    return item, observation


def snapshot(api):
    api.db.expire_all()
    return {table.name: [deepcopy(dict(row)) for row in api.db.execute(
        select(table).order_by(*table.primary_key.columns)).mappings()]
        for table in Base.metadata.sorted_tables}


def link_copy(api, item, old, *, event_days=1, facts=None):
    row = BookingObservation(user_id=old.user_id, evidence_key=uuid4().hex.ljust(64, "b"),
        source_message_id="independent-source-" + uuid4().hex,
        source_event_at=old.source_event_at + timedelta(days=event_days),
        pnr=old.pnr, travel_date=old.travel_date, dep_airport=old.dep_airport,
        arr_airport=old.arr_airport, flight_number=old.flight_number,
        ownership=old.ownership, facts=deepcopy(facts if facts is not None else old.facts))
    api.db.add(row)
    api.db.flush()
    api.db.add(TravelInboxEvidence(item_id=item.id, observation_id=row.id))
    api.db.commit()
    return row


def assert_hidden(view):
    assert view["flight"]["travel_date"] == ""
    assert view["flight"]["dep_time"] is None
    assert view["flight"]["arr_time"] is None


@pytest.mark.parametrize("date,origin,destination", [
    ("2027-03-06", "KUL", "SIN"), ("2027-06-03", "KUL", "SIN"),
    ("2027-04-29", "SIN", "KUL"), ("2027-05-29", "SIN", "KUL"),
])
def test_subject_placeholders_are_hidden_on_both_apis_without_any_write(api, date, origin, destination):
    api.app.include_router(inbox_router)
    item, observation = held(api, date=date, origin=origin, destination=destination,
        number=None, dep="00:00:00", arr="01:00:00")
    foreign, _ = held(api, owner=api.stranger)
    before = snapshot(api)
    statements = []
    def record_sql(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement.strip().split()[0].upper())
    event.listen(api.engine, "before_cursor_execute", record_sql)
    try:
        for _ in range(3):
            listing = api.client.get("/travel-inbox")
            detail = api.client.get(f"/travel-inbox/{item.id}")
            sharing = api.client.get("/travel-sharing/inbox")
            assert listing.status_code == detail.status_code == sharing.status_code == 200
            views = [listing.json()["items"][0], detail.json(), sharing.json()["items"][0]]
            for view in views:
                assert_hidden(view)
                assert view["id"] == item.id
                assert view["status"] == "needs_review"
                assert view["passenger_name"] == "Recipient Person"
                assert view["flight"]["pnr"] == observation.pnr
                assert (view["flight"]["dep_airport"], view["flight"]["arr_airport"]) == (origin, destination)
            assert detail.json()["evidence"][0]["observation_id"] == observation.id
            assert not views[-1]["shareable"] and not views[-1]["requires_assignment"]
            assert api.client.get(f"/travel-inbox/{foreign.id}").status_code == 404
    finally:
        event.remove(api.engine, "before_cursor_execute", record_sql)
    assert not {"INSERT", "UPDATE", "DELETE", "REPLACE", "CREATE", "DROP", "ALTER"}.intersection(statements)
    assert snapshot(api) == before
    assert observation.travel_date == date and observation.facts["dep_time"].endswith("T00:00:00")


@pytest.mark.parametrize("force,proof", [
    (False, {"extraction_review_reason": REASON}),
    (None, {"extraction_review_reason": REASON}),
    (1, {"extraction_review_reason": REASON}),
    ("true", {"extraction_review_reason": REASON}),
    (True, None), (True, []), (True, "subject"), (True, {}),
    (True, {"extraction_review_reason": REASON.upper()}),
    (True, {"extraction_review_reason": REASON + "_extra"}),
    (True, {"extraction_review_reason": "summary_flight_number_not_supported"}),
])
def test_suppression_requires_exact_held_reason(api, force, proof):
    item, row = held(api)
    row.facts = {**row.facts, "force_review": force, "time_provenance": proof}
    api.db.commit()
    before = snapshot(api)
    view = serialize_item(api.db, api.sender.id, item, include_evidence=True)
    assert view["flight"]["travel_date"] == row.travel_date
    assert view["flight"]["dep_time"] == row.facts["dep_time"]
    assert view["flight"]["arr_time"] == row.facts["arr_time"]
    assert snapshot(api) == before


@pytest.mark.parametrize("complete_newer", [True, False])
def test_source_chronology_restores_only_a_complete_successor(api, complete_newer):
    item, weak = held(api)
    facts = {**weak.facts, "source": "dated_receipt", "force_review": False,
        "dep_time": "2026-09-09T13:15:00", "arr_time": "2026-09-09T16:20:00",
        "time_provenance": {"version": 1, "status": "normalized"}}
    complete = link_copy(api, item, weak, event_days=1 if complete_newer else -1, facts=facts)
    before = snapshot(api)
    for _ in range(3):
        view = inbox_item_view(api.db, api.sender.id, item)
        if complete_newer:
            assert view["status"] == "retained" and view["shareable"]
            assert view["flight"]["travel_date"] == complete.travel_date
            assert view["flight"]["dep_time"] == facts["dep_time"]
            assert view["flight"]["arr_time"] == facts["arr_time"]
        else:
            assert_hidden(view)
            assert view["status"] == "needs_review" and not view["shareable"]
        assert snapshot(api) == before


@pytest.mark.parametrize("named", [True, False])
@pytest.mark.parametrize("status", ["active", "hold", "canceled"])
def test_later_decision_never_relabels_subject_placeholders_as_complete(api, named, status):
    item, weak = held(api, passenger="Recipient Person" if named else None)
    link_copy(api, item, weak, facts={"user_decision": {"ownership": "self", "status": status},
        "dep_time": "2026-09-09T10:00:00", "arr_time": "2026-09-09T13:00:00"})
    before = snapshot(api)
    view = inbox_item_view(api.db, api.sender.id, item)
    assert_hidden(view)
    expected = "needs_review" if named or status == "hold" else "belongs_to_you" if status == "active" else "canceled"
    assert view["status"] == expected
    assert not view["shareable"] and not view["requires_assignment"]
    assert snapshot(api) == before


@pytest.mark.parametrize("canceled", [True, False])
def test_held_or_canceled_named_item_cannot_create_share(api, canceled):
    item, weak = held(api)
    if canceled:
        api.db.add(BookingCancellation(user_id=api.sender.id, evidence_key="c" * 64,
            source_message_id="explicit-cancellation", source_event_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
            pnr=weak.pnr, scopes=[{"travel_date": weak.travel_date, "dep_airport": weak.dep_airport,
                "arr_airport": weak.arr_airport, "flight_number": weak.flight_number}],
            facts={"strict_lifecycle": True, "flights": [{"dep_airport": weak.dep_airport,
                "arr_airport": weak.arr_airport, "flight_number": weak.flight_number,
                "dep_time": weak.facts["dep_time"], "passenger_names": [item.passenger_name]}]}))
        api.db.commit()
    before = snapshot(api)
    view = inbox_item_view(api.db, api.sender.id, item)
    assert_hidden(view)
    assert view["status"] == ("canceled" if canceled else "needs_review")
    assert not view["shareable"] and not view["requires_assignment"]
    response = create(api, [item])
    assert response.status_code == 422
    assert snapshot(api) == before
