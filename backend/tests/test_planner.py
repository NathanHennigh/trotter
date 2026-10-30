"""Privacy, collaboration, concurrency and paid-job safety for the planner."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI, Response
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import get_db
from app.models import Base, Dream, DreamItem, DreamLocation, Segment, Trip, User
from app.planner_models import (PlannerContribution, PlannerIdea, PlannerInvite, PlannerJob,
                                PlannerMember, PlannerRevision, PlannerSourceShare, PlannerTrip, PlannerVote)
from app.routers.auth import get_current_user
from app.routers.planner import router
from app.services import planner as service


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setenv("ENCRYPTION_KEY", "11" * 32)
    monkeypatch.setenv("TROTTER_API_URL", "https://api.trotter.example")
    monkeypatch.setenv("PLANNER_DAILY_BUDGET_USD", "1")
    monkeypatch.setattr(service, "notify_jobs", lambda ids: None)
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    @event.listens_for(engine, "connect")
    def foreign_keys(conn, _):
        conn.execute("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    db = factory()
    people = [User(email=f"{name}@example.com", name=name.title()) for name in ("owner", "friend", "stranger")]
    db.add_all(people)
    db.commit()
    for person in people:
        db.refresh(person)
    app = FastAPI()
    app.include_router(router)
    def request_db():
        with factory() as session:
            yield session
    app.dependency_overrides[get_db] = request_db
    app.dependency_overrides[get_current_user] = lambda: people[0]
    with TestClient(app, raise_server_exceptions=True) as client:
        yield SimpleNamespace(db=db, factory=factory, engine=engine, app=app, client=client,
                              owner=people[0], friend=people[1], stranger=people[2])
    db.close()
    engine.dispose()


def login(api, user):
    api.app.dependency_overrides[get_current_user] = lambda: user


def test_email_invitation_accepts_explicitly_linked_google_email_on_apple_account(api):
    from app.models import AuthIdentity
    original_email = api.friend.email
    api.friend.email = "relay@privaterelay.appleid.com"
    api.db.add_all([
        AuthIdentity(user_id=api.friend.id, provider="apple", subject="apple-friend", email=api.friend.email),
        AuthIdentity(user_id=api.friend.id, provider="google", subject="google-friend", email=original_email),
    ])
    api.db.commit()
    planned, _ = create(api)
    invitation, _ = invite(api, planned, recipient_email=original_email)
    login(api, api.stranger)
    assert api.client.post("/planner/invites/accept", json={"token": invitation["token"]}).status_code == 403
    accepted = join(api, invitation["token"], api.friend)
    assert accepted["id"] == planned["id"]


def create(api, **changes):
    values = {"title": "Morocco, together", "destination": "Morocco", "start_date": "2026-11-12",
        "end_date": "2026-11-14", "timezone": "Africa/Casablanca", "pace": "balanced", "transport": "walk",
        "client_request_id": str(uuid4())}
    values.update(changes)
    response = api.client.post("/planner/trips", json=values)
    assert response.status_code == 201, response.text
    return response.json(), values


def add(api, trip, **changes):
    values = {"title": "Serenya", "city": "Marrakech", "country": "Morocco", "client_request_id": str(uuid4())}
    values.update(changes)
    response = api.client.post(f"/planner/trips/{trip['id']}/ideas", json=values)
    assert response.status_code == 200, response.text
    return response.json()


def invite(api, trip, **changes):
    values = {"role": "contributor", "client_request_id": str(uuid4())}
    values.update(changes)
    response = api.client.post(f"/planner/trips/{trip['id']}/invites", json=values)
    assert response.status_code == 200, response.text
    return response.json(), values


def join(api, token, user=None):
    login(api, user or api.friend)
    response = api.client.post("/planner/invites/accept", json={"token": token})
    assert response.status_code == 200, response.text
    return response.json()


def seed_dream(api, *, owner=None, title="Serenya", city="Marrakech", country="Morocco", source=None, note="SECRET PRIVATE NOTE"):
    owner = owner or api.owner
    group = Dream(user_id=owner.id, title=str(uuid4()), country=country, city=city)
    api.db.add(group)
    api.db.flush()
    item = DreamItem(user_id=owner.id, dream_id=group.id, source_url=source or f"https://www.instagram.com/reel/{uuid4().hex}/",
        place_name=title, city=city, country=country, summary="PRIVATE SUMMARY", personal_note=note,
        caption="PRIVATE CAPTION", category="restaurant", status="parsed", needs_review=False)
    api.db.add(item)
    api.db.commit()
    return item


def plan_for(trip):
    idea = trip["ideas"][0]
    return {"days": [{"date": "2026-11-12", "stops": [{"id": "stop-one", "idea_id": idea["id"],
        "title": idea["title"], "start_time": "10:00", "duration_minutes": 60, "locked": False, "kind": "place"}]},
        {"date": "2026-11-13", "stops": []}, {"date": "2026-11-14", "stops": []}], "warnings": [], "unplaced_idea_ids": []}


def save(api, trip, plan=None):
    response = api.client.put(f"/planner/trips/{trip['id']}/plan", json={"expected_version": trip["version"], "plan": plan or plan_for(trip)})
    assert response.status_code == 200, response.text
    return response.json()


def test_create_replay_and_cross_user_isolation(api):
    trip, payload = create(api)
    replay = api.client.post("/planner/trips", json=payload)
    assert replay.json()["id"] == trip["id"]
    changed = {**payload, "title": "Different"}
    assert api.client.post("/planner/trips", json=changed).status_code == 409
    login(api, api.stranger)
    assert api.client.get(f"/planner/trips/{trip['id']}").status_code == 404
    assert api.client.get("/planner/trips").json() == {"trips": []}
    assert api.client.post(f"/planner/trips/{trip['id']}/ideas", json={"title": "x", "client_request_id": str(uuid4())}).status_code == 404


def test_selected_dream_import_privacy_and_dedup(api):
    first = seed_dream(api)
    second = seed_dream(api, source="https://www.instagram.com/reel/another/")
    elsewhere = seed_dream(api, city="Rabat")
    private = seed_dream(api, owner=api.friend)
    trip, _ = create(api, dream_item_ids=[str(first.id), str(second.id), str(elsewhere.id)])
    assert len(trip["ideas"]) == 2
    matched = next(i for i in trip["ideas"] if i["city"] == "Marrakech")
    assert matched["source_count"] == 2
    assert matched["image_url"].startswith(f"/planner/trips/{trip['id']}/ideas/")
    assert "PRIVATE" not in str(trip)
    response = api.client.post(f"/planner/trips/{trip['id']}/ideas/import", json={"dream_item_ids": [str(private.id)]})
    assert response.status_code == 404
    assert api.client.get(f"/planner/trips/{trip['id']}").json()["idea_count"] == 2


def test_manual_coordinates_import_and_google_coordinates_not_persisted(api):
    manual = seed_dream(api)
    google = seed_dream(api, title="Other")
    api.db.add_all([DreamLocation(item_id=manual.id, user_id=api.owner.id, fingerprint="f", pin_fingerprint="p",
        status="manual", provider="manual", latitude=31.63, longitude=-7.98),
        DreamLocation(item_id=google.id, user_id=api.owner.id, fingerprint="f", pin_fingerprint="p",
        status="resolved", provider="google_places", latitude=32, longitude=-8)])
    api.db.commit()
    trip, _ = create(api, dream_item_ids=[str(manual.id), str(google.id)])
    assert next(i for i in trip["ideas"] if i["title"] == "Serenya")["latitude"] == 31.63
    assert next(i for i in trip["ideas"] if i["title"] == "Other")["latitude"] is None


def test_invites_roles_idempotence_and_vote_change(api):
    trip, _ = create(api)
    trip = add(api, trip)
    link, payload = invite(api, trip)
    assert "/planner/open#token=" in link["share_url"]
    assert api.client.post(f"/planner/trips/{trip['id']}/invites", json=payload).json()["token"] == link["token"]
    preview = api.client.post("/planner/invites/resolve", json={"token": link["token"]})
    assert preview.headers["cache-control"] == "no-store"
    assert "email" not in preview.text and "ideas" not in preview.json()
    joined = join(api, link["token"])
    again = api.client.post("/planner/invites/accept", json={"token": link["token"]}).json()
    assert again["member_count"] == 2
    assert joined["role"] == "contributor" and joined["invites"] == []
    path = f"/planner/trips/{trip['id']}/ideas/{trip['ideas'][0]['id']}/vote"
    assert api.client.put(path, json={"value": 1}).json()["ideas"][0]["score"] == 1
    down = api.client.put(path, json={"value": -1}).json()
    assert down["ideas"][0]["score"] == -1 and down["version"] == trip["version"]
    assert api.client.put(path, json={"value": 0}).json()["ideas"][0]["score"] == 0
    assert api.client.put(f"/planner/trips/{trip['id']}/plan", json={"expected_version": 1, "plan": plan_for(trip)}).status_code == 403
    assert api.client.post(f"/planner/trips/{trip['id']}/invites", json=payload).status_code == 403


def test_email_invite_expiry_revocation_and_removed_member_cannot_rejoin(api):
    trip, _ = create(api)
    bound, _ = invite(api, trip, recipient_email=api.friend.email)
    login(api, api.stranger)
    assert api.client.post("/planner/invites/accept", json={"token": bound["token"]}).status_code == 403
    join(api, bound["token"])
    login(api, api.owner)
    alternative, _ = invite(api, trip)
    assert api.client.delete(f"/planner/trips/{trip['id']}/members/{api.friend.id}").status_code == 200
    login(api, api.friend)
    for token in (bound["token"], alternative["token"]):
        assert api.client.post("/planner/invites/accept", json={"token": token}).status_code == 410
    assert api.client.get(f"/planner/trips/{trip['id']}").status_code == 404
    login(api, api.owner)
    fresh, _ = invite(api, trip)
    join(api, fresh["token"])
    login(api, api.owner)
    api.client.delete(f"/planner/trips/{trip['id']}/invites/{fresh['invite']['id']}")
    assert api.client.post("/planner/invites/resolve", json={"token": fresh["token"]}).status_code == 410
    old = api.db.get(PlannerInvite, alternative["invite"]["id"])
    old.expires_at = service.now() - timedelta(days=1)
    api.db.commit()
    assert api.client.post("/planner/invites/resolve", json={"token": alternative["token"]}).status_code == 410


def test_editor_direct_changes_history_conflicts_and_no_ai(api, monkeypatch):
    from app.services import planner_engine
    monkeypatch.setattr(planner_engine, "generate_plan", lambda *a, **k: pytest.fail("Manual editing invoked AI"))
    trip, _ = create(api)
    trip = add(api, trip)
    saved = save(api, trip)
    assert saved["version"] == 2
    assert api.client.put(f"/planner/trips/{trip['id']}/plan", json={"expected_version": 1, "plan": plan_for(trip)}).status_code == 409
    history = api.client.get(f"/planner/trips/{trip['id']}/history").json()["revisions"]
    modified = deepcopy(saved["plan"])
    modified["days"][0]["stops"][0]["start_time"] = "11:00"
    changed = save(api, saved, modified)
    restored = api.client.post(f"/planner/trips/{trip['id']}/restore", json={"expected_version": changed["version"], "revision_id": history[0]["id"]})
    assert restored.status_code == 200, restored.text
    assert restored.json()["plan"]["days"][0]["stops"][0]["start_time"] == "10:00"
    assert len(api.client.get(f"/planner/trips/{trip['id']}/history").json()["revisions"]) == 3
    assert api.client.delete(f"/planner/trips/{trip['id']}/ideas/{trip['ideas'][0]['id']}").status_code == 409
    bad = plan_for(trip)
    bad["days"][0]["stops"][0]["idea_id"] = "another-trip-place"
    assert api.client.put(f"/planner/trips/{trip['id']}/plan", json={"expected_version": 4, "plan": bad}).status_code == 422


def test_date_changes_normalize_plan_days_and_preserve_history(api):
    trip, _ = create(api)
    trip = save(api, add(api, trip))
    path = f"/planner/trips/{trip['id']}"
    extended = api.client.patch(path, json={"expected_version": trip["version"], "end_date": "2026-11-16"})
    assert extended.status_code == 200, extended.text
    ext = extended.json()
    assert ext["version"] == trip["version"] + 1
    assert len(ext["plan"]["days"]) == 5
    edited = save(api, ext, ext["plan"])
    shrunk = api.client.patch(path, json={"expected_version": edited["version"], "end_date": "2026-11-13"})
    assert shrunk.status_code == 200, shrunk.text
    assert len(shrunk.json()["plan"]["days"]) == 2
    assert api.client.patch(path, json={"expected_version": shrunk.json()["version"], "start_date": "2026-11-13"}).status_code == 422


def test_generation_idempotence_draft_acceptance_and_worker_replay(api, monkeypatch):
    from app.services import planner_engine
    trip, _ = create(api)
    trip = add(api, trip)
    calls = []
    def compose(payload, *, use_ai):
        calls.append(payload)
        return {"plan": plan_for(trip), "source": "ai", "usage": {"cost_usd": .02, "input_tokens": 100, "output_tokens": 100}}
    monkeypatch.setattr(planner_engine, "generate_plan", compose)
    body = {"expected_version": 1, "client_request_id": str(uuid4())}
    response = api.client.post(f"/planner/trips/{trip['id']}/generate", json=body)
    assert response.status_code == 202, response.text
    job = response.json()
    assert api.client.post(f"/planner/trips/{trip['id']}/generate", json=body).json()["id"] == job["id"]
    service.process_job(job["id"], session_factory=api.factory)
    service.process_job(job["id"], session_factory=api.factory)
    assert len(calls) == 1
    detail = api.client.get(f"/planner/trips/{trip['id']}").json()
    assert detail["generation"]["status"] == "completed" and detail["plan"] is None and detail["draft"]
    accepted = api.client.post(f"/planner/trips/{trip['id']}/draft/accept", json={"expected_version": 1, "revision_id": detail["draft"]["id"]})
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["plan"] and accepted.json()["draft"] is None


def test_generation_cannot_overwrite_concurrent_manual_change(api, monkeypatch):
    from app.services import planner_engine
    trip, _ = create(api)
    trip = add(api, trip)
    def compose(payload, *, use_ai):
        save(api, trip)
        return {"plan": plan_for(trip), "source": "ai", "usage": {"cost_usd": .02}}
    monkeypatch.setattr(planner_engine, "generate_plan", compose)
    job = api.client.post(f"/planner/trips/{trip['id']}/generate", json={"expected_version": 1, "client_request_id": str(uuid4())}).json()
    service.process_job(job["id"], session_factory=api.factory)
    result = api.client.get(f"/planner/trips/{trip['id']}").json()
    assert result["generation"]["status"] == "failed" and result["draft"] is None and result["plan"]


def test_generation_reserves_budget_and_stale_jobs_are_not_replayed(api, monkeypatch):
    monkeypatch.setenv("PLANNER_DAILY_BUDGET_USD", ".20")
    trip, _ = create(api)
    job = api.client.post(f"/planner/trips/{trip['id']}/generate", json={"expected_version": 1, "client_request_id": str(uuid4())}).json()
    second, _ = create(api)
    denied = api.client.post(f"/planner/trips/{second['id']}/generate", json={"expected_version": 1, "client_request_id": str(uuid4())})
    assert denied.status_code == 429
    row = api.db.get(PlannerJob, job["id"])
    row.status, row.started_at = "running", service.now() - timedelta(minutes=20)
    api.db.commit()
    dispatched = []
    monkeypatch.setattr(service, "notify_jobs", dispatched.extend)
    service.discover_jobs(session_factory=api.factory)
    api.db.expire_all()
    assert api.db.get(PlannerJob, job["id"]).status == "failed" and dispatched == []


def test_sources_include_eventual_siblings_but_never_unrelated_private_saves(api):
    source = "https://www.instagram.com/reel/shared-collection/"
    first = seed_dream(api, source=source)
    private = seed_dream(api, title="Private place")
    trip, _ = create(api)
    api.db.add(PlannerSourceShare(trip_id=trip["id"], user_id=api.owner.id, source_url=source, source_key=service.digest(source)))
    api.db.commit()
    first_result = api.client.get(f"/planner/trips/{trip['id']}").json()
    assert [i["title"] for i in first_result["ideas"]] == ["Serenya"]
    sibling = seed_dream(api, title="Le Jardin", source="https://www.instagram.com/reel/temporary/")
    sibling.source_url, sibling.source_place_key = source, "second"
    api.db.commit()
    result = api.client.get(f"/planner/trips/{trip['id']}").json()
    assert {i["title"] for i in result["ideas"]} == {"Serenya", "Le Jardin"}
    assert private.place_name not in str(result)
    deleted = next(i for i in result["ideas"] if i["title"] == "Le Jardin")
    assert api.client.delete(f"/planner/trips/{trip['id']}/ideas/{deleted['id']}").status_code == 200
    assert len(api.client.get(f"/planner/trips/{trip['id']}").json()["ideas"]) == 1


def test_shared_photo_authorized_independently_of_personal_dream_access(api, monkeypatch):
    from app.routers import dreams
    item = seed_dream(api)
    trip, _ = create(api, dream_item_ids=[str(item.id)])
    link, _ = invite(api, trip)
    join(api, link["token"])
    seen = []
    def thumbnail(item, db, author, width):
        seen.append((item.id, author.id, width))
        return Response(b"pixels", media_type="image/png")
    monkeypatch.setattr(dreams, "dream_thumbnail_response", thumbnail)
    response = api.client.get(trip["ideas"][0]["image_url"])
    assert response.status_code == 200 and seen == [(item.id, api.owner.id, 240)]
    login(api, api.stranger)
    assert api.client.get(trip["ideas"][0]["image_url"]).status_code == 404


def test_delete_trip_cascades_only_shared_plan_data(api):
    item = seed_dream(api)
    trip, _ = create(api, dream_item_ids=[str(item.id)])
    link, _ = invite(api, trip)
    join(api, link["token"])
    path = f"/planner/trips/{trip['id']}?expected_version=1"
    assert api.client.delete(path).status_code == 403
    login(api, api.owner)
    assert api.client.delete(path).status_code == 200
    api.db.expire_all()
    assert api.db.get(DreamItem, item.id) is not None
    assert api.db.query(PlannerTrip).count() == api.db.query(PlannerContribution).count() == api.db.query(PlannerMember).count() == 0


def test_import_bookings_has_explicit_consent_and_no_private_reference(api):
    flight_trip = Trip(user_id=api.owner.id, title="Personal flight")
    api.db.add(flight_trip)
    api.db.flush()
    flight = Segment(trip_id=flight_trip.id, mode="flight", dep_airport="RAK", arr_airport="CMN",
        dep_time=datetime(2026,11,12,10,tzinfo=timezone.utc), arr_time=datetime(2026,11,12,11,tzinfo=timezone.utc),
        pnr="PRIVATE-PNR", flight_number="AT402")
    api.db.add(flight)
    api.db.commit()
    trip, _ = create(api)
    assert trip["plan"] is None
    choices = api.client.get(f"/planner/trips/{trip['id']}/bookings").json()
    assert choices["bookings"][0]["segment_id"] == str(flight.id)
    assert "PRIVATE-PNR" not in str(choices)
    imported = api.client.post(f"/planner/trips/{trip['id']}/bookings/import", json={"expected_version": 1, "segment_ids": [str(flight.id)]})
    assert imported.status_code == 200, imported.text
    stop = imported.json()["plan"]["days"][0]["stops"][0]
    assert stop["kind"] == "booking" and stop["locked"]
    assert "PRIVATE-PNR" not in imported.text


def test_late_google_identity_merges_sources_votes_and_preserves_current_stop_ids(api):
    original = seed_dream(api)
    trip, _ = create(api, dream_item_ids=[str(original.id)])
    original_idea_id = trip["ideas"][0]["id"]
    saved = save(api, trip)
    other = seed_dream(api, owner=api.friend, title="Serenya Riad")
    other.google_place_id = "same-verified-google-place"
    api.db.commit()
    link, _ = invite(api, saved)
    join(api, link["token"])
    added = api.client.post(f"/planner/trips/{trip['id']}/ideas/import", json={"dream_item_ids": [str(other.id)]}).json()
    other_idea_id = next(i["id"] for i in added["ideas"] if i["id"] != original_idea_id)
    api.client.put(f"/planner/trips/{trip['id']}/ideas/{other_idea_id}/vote", json={"value": 1})
    login(api, api.owner)
    original.google_place_id = "same-verified-google-place"
    api.db.add(PlannerSourceShare(trip_id=trip["id"], user_id=api.owner.id, source_url=original.source_url,
                                source_key=service.digest(original.source_url)))
    api.db.commit()
    merged = api.client.get(f"/planner/trips/{trip['id']}").json()
    assert len(merged["ideas"]) == 1 and merged["ideas"][0]["id"] == original_idea_id
    assert merged["ideas"][0]["google_place_id"] == "same-verified-google-place"
    assert merged["ideas"][0]["score"] == 1 and merged["ideas"][0]["source_count"] == 2
    assert merged["plan"]["days"][0]["stops"][0]["idea_id"] == original_idea_id
    assert merged["version"] == saved["version"]
    assert save(api, merged, merged["plan"])["plan"]


def test_history_restore_resolves_a_merged_idea_alias(api):
    first = seed_dream(api)
    trip, _ = create(api, dream_item_ids=[str(first.id)])
    saved = save(api, trip)
    old = api.client.get(f"/planner/trips/{trip['id']}/history").json()["revisions"][0]
    empty = deepcopy(saved["plan"])
    empty["days"][0]["stops"] = []
    current = save(api, saved, empty)
    target = seed_dream(api, title="Serenya Riad")
    target.google_place_id = "shared-identity"
    api.db.commit()
    api.client.post(f"/planner/trips/{trip['id']}/ideas/import", json={"dream_item_ids": [str(target.id)]})
    first.google_place_id = "shared-identity"
    api.db.add(PlannerSourceShare(trip_id=trip["id"], user_id=api.owner.id, source_url=first.source_url,
                                source_key=service.digest(first.source_url)))
    api.db.commit()
    merged = api.client.get(f"/planner/trips/{trip['id']}").json()
    restored = api.client.post(f"/planner/trips/{trip['id']}/restore", json={"expected_version": current["version"], "revision_id": old["id"]})
    assert restored.status_code == 200, restored.text
    assert restored.json()["plan"]["days"][0]["stops"][0]["idea_id"] == merged["ideas"][0]["id"]
