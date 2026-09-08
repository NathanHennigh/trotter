from datetime import datetime, timezone
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import get_db
from app.models import Base, BookingObservation, TravelInboxEvidence, TravelInboxItem, User
from app.routers.auth import get_current_user
from app.routers.travel_inbox import router


@pytest.fixture
def api():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    db = factory()
    owner = User(email="owner@example.com", name="Nathan Smith")
    other = User(email="private-owner@example.com", name="Another Owner")
    db.add_all([owner, other])
    db.commit()
    db.refresh(owner)
    db.refresh(other)
    app = FastAPI()
    app.include_router(router)
    def test_db():
        with factory() as session:
            yield session
    app.dependency_overrides[get_db] = test_db
    app.dependency_overrides[get_current_user] = lambda: owner
    with TestClient(app, raise_server_exceptions=False) as client:
        yield {"engine": engine, "db": db, "owner": owner, "other": other, "app": app, "client": client}
    db.close()
    engine.dispose()


def seed_item(api, number, *, user=None, created_at=None, passenger="Rachel Smith"):
    user = user or api["owner"]
    source = BookingObservation(
        user_id=user.id, evidence_key=f"observation-{number}".ljust(64, "0"), source_message_id=f"message-{number}",
        source_event_at=datetime(2025, 1, 29, tzinfo=timezone.utc), pnr="ABC123", travel_date="2025-02-18",
        dep_airport="IAH", arr_airport="DCA", flight_number="UA1540", ownership="other",
        facts={"pnr": "ABC123", "dep_airport": "IAH", "arr_airport": "DCA", "flight_number": "UA1540",
               "airline": "UA", "dep_time": "2025-02-18T12:00:00", "arr_time": "2025-02-18T15:00:00",
               "ownership": "other", "passenger_names": [passenger, "Private Companion Manifest"],
               "passenger_evidence": [{"name": passenger, "source": "passenger_field"}],
               "original_private_manifest": "Private Companion Manifest"},
    )
    item = TravelInboxItem(
        id=str(UUID(int=number)), user_id=user.id, record_key=f"record-{number}".ljust(64, "0"),
        flight_key=f"flight-{number}".ljust(64, "0"), passenger_name=passenger,
        passenger_key=passenger.casefold(), reason="other_traveler",
        created_at=created_at or datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    api["db"].add_all([source, item])
    api["db"].flush()
    api["db"].add(TravelInboxEvidence(item_id=item.id, observation_id=source.id))
    api["db"].commit()
    return item


@pytest.mark.parametrize("path", ["/travel-inbox", "/travel-inbox/00000000-0000-0000-0000-000000000001"])
def test_inbox_reads_require_authentication(api, path):
    api["app"].dependency_overrides.pop(get_current_user)
    assert api["client"].get(path).status_code in (401, 403)


def test_list_and_detail_are_owner_scoped_and_return_no_shared_manifest(api):
    own = seed_item(api, 1)
    private = seed_item(api, 2, user=api["other"], passenger="Secret Other Owner Passenger")
    response = api["client"].get("/travel-inbox")
    assert response.status_code == 200, response.text
    assert [item["id"] for item in response.json()["items"]] == [own.id]
    assert response.json()["next_cursor"] is None
    item = response.json()["items"][0]
    assert {"id", "passenger_name", "reason", "status", "flight", "observation_count", "created_at"}.issubset(item)
    assert "evidence" not in item
    assert "Secret Other Owner Passenger" not in response.text
    assert "Private Companion Manifest" not in response.text
    detail = api["client"].get(f"/travel-inbox/{own.id}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["id"] == own.id
    assert detail.json()["evidence"]
    assert "Private Companion Manifest" not in detail.text
    assert "original_private_manifest" not in detail.text
    for item_id in (private.id, str(UUID(int=999))):
        hidden = api["client"].get(f"/travel-inbox/{item_id}")
        assert hidden.status_code == 404
        assert hidden.json() == {"detail": "Travel inbox item not found"}


def test_keyset_pagination_uses_timestamp_then_id_and_keeps_cursor_owned(api):
    tied = datetime(2026, 1, 2, tzinfo=timezone.utc)
    older = seed_item(api, 9, created_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    middle = seed_item(api, 1, created_at=tied)
    newest = seed_item(api, 2, created_at=tied)
    private = seed_item(api, 100, user=api["other"], created_at=tied)
    first = api["client"].get("/travel-inbox", params={"limit": 1})
    assert first.status_code == 200, first.text
    assert [item["id"] for item in first.json()["items"]] == [newest.id]
    assert first.json()["next_cursor"] == newest.id
    second = api["client"].get("/travel-inbox", params={"limit": 1, "before_id": first.json()["next_cursor"]})
    assert [item["id"] for item in second.json()["items"]] == [middle.id]
    third = api["client"].get("/travel-inbox", params={"limit": 1, "before_id": second.json()["next_cursor"]})
    assert [item["id"] for item in third.json()["items"]] == [older.id]
    assert third.json()["next_cursor"] is None
    for cursor in (private.id, str(UUID(int=999))):
        hidden = api["client"].get("/travel-inbox", params={"before_id": cursor})
        assert hidden.status_code == 404
        assert hidden.json() == {"detail": "Travel inbox cursor not found"}


@pytest.mark.parametrize("limit", [0, -1, 101])
def test_page_limit_is_bounded(api, limit):
    assert api["client"].get("/travel-inbox", params={"limit": limit}).status_code == 422


def test_read_paths_never_write_or_backfill_missing_items(api):
    own = seed_item(api, 1)
    unprojected = BookingObservation(
        user_id=api["owner"].id, evidence_key="u" * 64, source_message_id="not-backfilled",
        pnr="OTHER1", travel_date="2025-05-18", dep_airport="IAH", arr_airport="LAX",
        flight_number="UA999", ownership="unknown", facts={"must_stay_unprojected": True},
    )
    api["db"].add(unprojected)
    api["db"].commit()
    statements = []
    def record_sql(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement.strip().split()[0].upper())
    event.listen(api["engine"], "before_cursor_execute", record_sql)
    try:
        listing = api["client"].get("/travel-inbox")
        detail = api["client"].get(f"/travel-inbox/{own.id}")
        assert listing.status_code == detail.status_code == 200
    finally:
        event.remove(api["engine"], "before_cursor_execute", record_sql)
    assert not {"INSERT", "UPDATE", "DELETE", "REPLACE", "CREATE", "DROP", "ALTER"}.intersection(statements)
    assert api["db"].query(TravelInboxItem).count() == 1
    assert api["db"].query(TravelInboxEvidence).count() == 1
    assert api["db"].query(BookingObservation).count() == 2


@pytest.mark.parametrize("method,path", [
    ("post", "/travel-inbox"),
    ("put", "/travel-inbox/00000000-0000-0000-0000-000000000001"),
    ("delete", "/travel-inbox/00000000-0000-0000-0000-000000000001"),
    ("post", "/travel-inbox/00000000-0000-0000-0000-000000000001/share"),
    ("post", "/travel-inbox/00000000-0000-0000-0000-000000000001/invite"),
])
def test_no_write_sharing_or_invitation_endpoints_exist(api, method, path):
    assert api["client"].request(method, path, json={}).status_code in (404, 405)
