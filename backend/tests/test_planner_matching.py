"""Consent, privacy, exact geography, and durable matching without paid calls."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.models import DreamItem, DreamSourcePost, Segment, Trip
from app.planner_models import PlannerContribution, PlannerIdea, PlannerMember, PlannerTrip
from app.services import planner as service
from app.services import planner_matching as matching
from test_planner import api, add, create, invite, join, login, plan_for, save, seed_dream as _seed_dream


def seed_dream(api, **kwargs):
    item = _seed_dream(api, **kwargs)
    item.created_at = datetime(2026, 10, 25, 12, tzinfo=timezone.utc)
    item.updated_at = item.created_at
    api.db.commit()
    return item


@pytest.fixture
def clock(monkeypatch):
    current = [datetime(2026, 10, 26, 12, tzinfo=timezone.utc)]
    monkeypatch.setattr(service, "now", lambda: current[0])
    return current


def choices(api):
    response = api.client.get("/planner/dreams/destinations")
    assert response.status_code == 200, response.text
    assert response.headers["Cache-Control"] == "private, no-store"
    return response.json()["destinations"]


def scope_id(api, country="Morocco", city=None):
    return next(row["id"] for row in choices(api) if row["country"] == country and row["city"] == city)


def scoped_trip(api, *, city=None, **kwargs):
    return create(api, match_scope_id=scope_id(api, city=city), **kwargs)[0]


def suggested(api, trip, **params):
    response = api.client.get(f"/planner/trips/{trip['id']}/dream-suggestions", params=params)
    assert response.status_code == 200, response.text
    assert response.headers["Cache-Control"] == "private, no-store"
    return response.json()


def consent(api, trip, enabled=True):
    response = api.client.put(f"/planner/trips/{trip['id']}/dream-sharing", json={"scope_id": trip["match_scope"]["id"], "enabled": enabled})
    assert response.status_code == 200, response.text
    return response.json()


def share_all(api, trip):
    response = api.client.post(f"/planner/trips/{trip['id']}/dream-suggestions/import", json={"scope_id": trip["match_scope"]["id"], "all": True})
    assert response.status_code == 200, response.text
    return response.json()


def future_save(api, clock, **kwargs):
    item = seed_dream(api, **kwargs)
    item.created_at = clock[0] + timedelta(minutes=1)
    item.updated_at = item.created_at
    api.db.commit()
    return item


def discover(api):
    service.discover_jobs(session_factory=api.factory)
    api.db.expire_all()


def test_private_scopes_use_canonical_exact_geography_with_private_pagination(api, clock):
    first = seed_dream(api, city="Marrakech", country="MA")
    second = seed_dream(api, title="Museum", city="Marrakesh", country="Morocco")
    seed_dream(api, title="Elsewhere", city="Marrakesh Coast", country="Morocco")
    seed_dream(api, country="Morocco Islands", city="Marrakesh")
    other = seed_dream(api, owner=api.friend, country="France", city="Paris")
    mine = choices(api)
    assert not any(row["country"] == "France" for row in mine)
    assert next(row for row in mine if row["city"] == "Marrakesh" and row["country"] == "Morocco")["count"] == 2
    trip = scoped_trip(api, city="Marrakesh")
    assert trip["dream_sharing"]["enabled"] is False
    page = suggested(api, trip, limit=1)
    assert page["total"] == 2 and page["next_cursor"] == str(first.id)
    assert page["suggestions"][0]["image_url"] == f"/dream-items/{first.id}/thumbnail"
    assert "PRIVATE" not in str(page)
    next_page = suggested(api, trip, cursor=page["next_cursor"])
    assert [row["dream_item_id"] for row in next_page["suggestions"]] == [str(second.id)]
    invitation, _ = invite(api, trip)
    join(api, invitation["token"])
    assert suggested(api, trip)["total"] == 0
    assert choices(api)[0]["country"] == "France"
    assert api.client.post(f"/planner/trips/{trip['id']}/dream-suggestions/import", json={"scope_id": trip["match_scope"]["id"], "dream_item_ids": [str(first.id)]}).status_code == 404
    login(api, api.stranger)
    assert api.client.get(f"/planner/trips/{trip['id']}/dream-suggestions").status_code == 404
    assert api.client.put(f"/planner/trips/{trip['id']}/dream-sharing", json={"scope_id": trip["match_scope"]["id"], "enabled": True}).status_code == 404


def test_existing_bulk_import_explicit_idempotent_and_does_not_change_accepted_plan(api, clock):
    first = seed_dream(api)
    second = seed_dream(api, title="Garden")
    trip = scoped_trip(api)
    trip = add(api, trip, title="Existing plan stop")
    trip = save(api, trip)
    saved_plan, version = trip["plan"], trip["version"]
    consent(api, trip)
    discover(api)
    assert api.db.query(PlannerIdea).filter_by(trip_id=trip["id"], deleted_at=None).count() == 1
    imported = share_all(api, trip)
    assert imported["idea_count"] == 3 and imported["plan"] == saved_plan and imported["version"] == version
    assert "PRIVATE" not in str(imported)
    assert suggested(api, trip)["total"] == 0
    assert share_all(api, trip)["idea_count"] == 3
    assert api.client.post(f"/planner/trips/{trip['id']}/dream-suggestions/import", json={"scope_id": trip["match_scope"]["id"], "dream_item_ids": [str(first.id), str(second.id)]}).status_code == 200
    assert api.db.query(PlannerContribution).filter_by(trip_id=trip["id"]).count() == 3


def test_future_saves_late_categorization_and_out_of_order_commits_background_sync(api, clock):
    old = seed_dream(api)
    old.created_at = clock[0] - timedelta(days=1)
    api.db.commit()
    trip = scoped_trip(api, city="Marrakesh")
    consent(api, trip)
    pending = future_save(api, clock, title=None, city=None, country=None)
    new = future_save(api, clock, title="Garden")
    future_save(api, clock, title="Wrong city", city="Rabat")
    future_save(api, clock, title="Wrong user", owner=api.friend)
    discover(api)
    assert [i.title for i in api.db.query(PlannerIdea).filter_by(trip_id=trip["id"]).all()] == ["Garden"]
    pending.place_name, pending.city, pending.country = "Museum", "Marrakech", "MA"
    # A commit with an older update timestamp must still be discovered.
    pending.updated_at = clock[0] - timedelta(days=2)
    api.db.commit()
    discover(api)
    assert {i.title for i in api.db.query(PlannerIdea).filter_by(trip_id=trip["id"]).all()} == {"Museum", "Garden"}
    new.google_place_id = "late-location"
    api.db.commit()
    discover(api)
    discover(api)  # round-robin refresh wraps without relying on timestamps.
    assert api.db.query(PlannerIdea).filter_by(trip_id=trip["id"], title="Garden").one().google_place_id == "late-location"
    assert api.db.query(PlannerContribution).filter_by(trip_id=trip["id"]).count() == 2
    assert suggested(api, trip)["total"] == 1  # old private save remains an explicit suggestion.


def test_original_capture_time_prevents_old_reel_siblings_from_becoming_future_saves(api, clock):
    old = seed_dream(api)
    source = DreamSourcePost(user_id=api.owner.id, source_url=old.source_url,
        created_at=clock[0] - timedelta(days=30))
    api.db.add(source)
    api.db.flush()
    old.source_post_id = source.id
    old.created_at = clock[0] - timedelta(days=30)
    api.db.commit()
    trip = scoped_trip(api)
    consent(api, trip)
    sibling = future_save(api, clock, title="Later parsed old reel")
    sibling.source_post_id = source.id
    api.db.commit()
    discover(api)
    assert api.db.query(PlannerIdea).filter_by(trip_id=trip["id"]).count() == 0
    assert suggested(api, trip)["total"] == 2


def test_optout_removal_and_trip_end_stop_future_sharing_independently(api, clock):
    seed_dream(api)
    friend_old = seed_dream(api, owner=api.friend)
    trip = scoped_trip(api)
    consent(api, trip)
    link, _ = invite(api, trip)
    join(api, link["token"])
    consent(api, trip)
    login(api, api.owner)
    second_trip = scoped_trip(api)
    consent(api, second_trip)
    consent(api, trip, False)
    future_save(api, clock, title="Only second trip")
    future_save(api, clock, owner=api.friend, title="Friend contribution")
    discover(api)
    assert {i.title for i in api.db.query(PlannerIdea).filter_by(trip_id=trip["id"]).all()} == {"Friend contribution"}
    assert {i.title for i in api.db.query(PlannerIdea).filter_by(trip_id=second_trip["id"]).all()} == {"Only second trip"}
    assert api.client.delete(f"/planner/trips/{trip['id']}/members/{api.friend.id}").status_code == 200
    future_save(api, clock, owner=api.friend, title="After removal")
    clock[0] += timedelta(days=30)
    future_save(api, clock, title="After trip ended")
    discover(api)
    assert api.db.get(PlannerMember, (trip["id"], api.friend.id)).dream_auto_share is False
    assert api.db.query(PlannerIdea).filter_by(trip_id=trip["id"]).count() == 1
    assert api.db.query(PlannerIdea).filter_by(trip_id=second_trip["id"]).count() == 1
    ended = api.client.get(f"/planner/trips/{second_trip['id']}").json()["dream_sharing"]
    assert ended["enabled"] is True and ended["active"] is False and ended["paused_reason"] == "trip_ended"


def test_scope_change_revokes_everyones_consent_and_rejects_stale_actions(api, clock):
    seed_dream(api)
    seed_dream(api, country="France", city="Paris")
    trip = scoped_trip(api)
    consent(api, trip)
    link, _ = invite(api, trip)
    join(api, link["token"])
    consent(api, trip)
    login(api, api.owner)
    new_scope = scope_id(api, country="France")
    changed = api.client.patch(f"/planner/trips/{trip['id']}", json={"expected_version": trip["version"], "match_scope_id": new_scope})
    assert changed.status_code == 200, changed.text
    assert changed.json()["version"] == trip["version"] + 1
    assert all(not m.dream_auto_share for m in api.db.query(PlannerMember).filter_by(trip_id=trip["id"]).populate_existing())
    for route, method, body in (("dream-sharing", api.client.put, {"enabled": True}),
        ("dream-suggestions/import", api.client.post, {"all": True})):
        assert method(f"/planner/trips/{trip['id']}/{route}", json={"scope_id": trip["match_scope"]["id"], **body}).status_code == 409
    assert api.client.patch(f"/planner/trips/{trip['id']}", json={"expected_version": changed.json()["version"], "match_scope_id": "f"*64}).status_code == 422
    cleared = api.client.patch(f"/planner/trips/{trip['id']}", json={"expected_version": changed.json()["version"], "match_scope_id": None})
    assert cleared.status_code == 200 and cleared.json()["match_scope"] is None


def test_removal_tombstone_survives_new_sources_provider_resolution_and_retries(api, clock):
    seed_dream(api)
    trip = scoped_trip(api)
    consent(api, trip)
    first = future_save(api, clock, title="Future venue")
    discover(api)
    idea = api.db.query(PlannerIdea).filter_by(trip_id=trip["id"]).one()
    assert api.client.delete(f"/planner/trips/{trip['id']}/ideas/{idea.id}").status_code == 200
    first.google_place_id = "provider-resolved-after-deletion"
    second = future_save(api, clock, title="Future venue", city="Marrakesh", country="MA")
    second.google_place_id = first.google_place_id
    api.db.commit()
    for _ in range(3):
        discover(api)
    assert api.db.query(PlannerIdea).filter_by(trip_id=trip["id"], deleted_at=None).count() == 0
    assert all(row["title"] != "Future venue" for row in suggested(api, trip)["suggestions"])
    share_all(api, trip)
    assert api.db.query(PlannerIdea).filter_by(trip_id=trip["id"], deleted_at=None).count() == 1  # only old Serenya explicitly shared


def test_two_members_match_same_canonical_place_vote_and_edit_conflicts(api, clock):
    seed_dream(api)
    friend_save = seed_dream(api, owner=api.friend, city="Marrakesh", country="MA")
    trip = share_all(api, scoped_trip(api))
    link, _ = invite(api, trip, role="editor")
    joined = join(api, link["token"])
    assert suggested(api, trip)["total"] == 1
    trip = share_all(api, trip)
    assert trip["idea_count"] == 1 and len(trip["ideas"][0]["contributors"]) == 2
    idea_id = trip["ideas"][0]["id"]
    assert api.client.put(f"/planner/trips/{trip['id']}/ideas/{idea_id}/vote", json={"value": 1}).status_code == 200
    saved = save(api, trip)
    login(api, api.owner)
    voted = api.client.put(f"/planner/trips/{trip['id']}/ideas/{idea_id}/vote", json={"value": -1})
    assert voted.status_code == 200 and voted.json()["ideas"][0]["score"] == 0
    assert api.client.put(f"/planner/trips/{trip['id']}/plan", json={"expected_version": trip["version"], "plan": plan_for(trip)}).status_code == 409
    assert api.client.get(f"/planner/trips/{trip['id']}").json()["plan"] == saved["plan"]


def test_bookings_duration_uses_elapsed_time_across_dst(api, clock):
    # US fallback: local 00:30 to 02:30 is three elapsed hours, not two.
    from app.routers.planner import booking_choices
    flight_trip = Trip(user_id=api.owner.id, title="Private flights")
    api.db.add(flight_trip)
    api.db.flush()
    api.db.add(Segment(trip_id=flight_trip.id, mode="flight", dep_airport="JFK", arr_airport="LGA", flight_number="QA1",
        dep_time=datetime(2026, 11, 1, 4, 30, tzinfo=timezone.utc), arr_time=datetime(2026, 11, 1, 7, 30, tzinfo=timezone.utc)))
    api.db.commit()
    trip, _ = create(api, start_date="2026-11-01", end_date="2026-11-02", timezone="America/New_York")
    result = api.client.get(f"/planner/trips/{trip['id']}/bookings")
    assert result.status_code == 200, result.text
    assert result.json()["bookings"][0]["start_time"] == "00:30"
    assert result.json()["bookings"][0]["duration_minutes"] == 180


def test_removed_confirmed_branch_does_not_suppress_another_branch(api, clock):
    from app.models import DreamGoogleIdentity, DreamLocation
    first = seed_dream(api, title="Caffe Nero", country="United Kingdom", city="London")
    first.google_place_id = "branch-a"
    api.db.commit()
    trip, _ = create(api, match_scope_id=scope_id(api, "United Kingdom"), dream_item_ids=[str(first.id)])
    consent(api, trip)
    assert api.client.delete(f"/planner/trips/{trip['id']}/ideas/{trip['ideas'][0]['id']}").status_code == 200
    other = future_save(api, clock, title="Caffe Nero", country="UK", city="London")
    location = DreamLocation(item_id=other.id, user_id=api.owner.id, fingerprint="branch", pin_fingerprint="branch", status="resolved", provider="google_places")
    api.db.add(location)
    api.db.flush()
    api.db.add(DreamGoogleIdentity(location_id=location.id, confirmed_place_id="branch-b"))
    renamed = future_save(api, clock, title="Caffe Nero New Name", country="UK", city="London")
    renamed.google_place_id = "branch-a"
    api.db.commit()
    # Without a GET-triggered sync, inspect the exact private suggestion query first.
    model = api.db.get(PlannerTrip, trip["id"])
    member = api.db.get(PlannerMember, (trip["id"], api.owner.id))
    assert [i["dream_item_id"] for i in matching.suggestions(api.db, model, member)["suggestions"]] == [str(other.id)]
    api.db.rollback()
    discover(api)
    active = api.db.query(PlannerIdea).filter_by(trip_id=trip["id"], deleted_at=None).all()
    assert len(active) == 1 and active[0].google_place_id == "branch-b"


def test_unresolved_explicit_neighborhoods_remain_distinct_and_alias_refresh_survives(api, clock):
    first = seed_dream(api, title="Independent Cafe", country="United Kingdom", city="London")
    second = seed_dream(api, title="Independent Cafe", country="UK", city="London")
    first.region_or_neighborhood, second.region_or_neighborhood = "Soho", "Paddington"
    api.db.commit()
    trip, _ = create(api, match_scope_id=scope_id(api, "United Kingdom"))
    shared = share_all(api, trip)
    assert shared["idea_count"] == 2
    assert {idea["region_or_neighborhood"] for idea in shared["ideas"]} == {"Soho", "Paddington"}
    consent(api, trip)
    future = future_save(api, clock, title="Next cafe", country="UK", city="London")
    discover(api)
    future.country, future.google_place_id = "United Kingdom", "late-provider"
    api.db.commit()
    discover(api)
    discover(api)
    assert api.db.query(PlannerIdea).filter_by(trip_id=trip["id"], title="Next cafe").one().google_place_id == "late-provider"


def test_matching_import_is_atomic_at_capacity_and_pending_sync_resumes(api, clock, monkeypatch):
    seed_dream(api, title="First")
    seed_dream(api, title="Second")
    trip = scoped_trip(api)
    trip = add(api, trip, title="Existing")
    monkeypatch.setattr(service, "MAX_IDEAS", 2)
    response = api.client.post(f"/planner/trips/{trip['id']}/dream-suggestions/import", json={"scope_id": trip["match_scope"]["id"], "all": True})
    assert response.status_code == 422
    assert api.db.query(PlannerIdea).filter_by(trip_id=trip["id"], deleted_at=None).count() == 1
    consent(api, trip)
    future_save(api, clock, title="Future one")
    future_save(api, clock, title="Future two")
    discover(api)
    active = api.db.query(PlannerIdea).filter_by(trip_id=trip["id"], deleted_at=None).all()
    assert len(active) == 2
    assert api.client.delete(f"/planner/trips/{trip['id']}/ideas/{trip['ideas'][0]['id']}").status_code == 200
    discover(api)
    assert {idea.title for idea in api.db.query(PlannerIdea).filter_by(trip_id=trip["id"], deleted_at=None)} == {"Future one", "Future two"}


def test_reenable_requires_fresh_future_capture_and_personal_deletion_leaves_shared_place(api, clock):
    seed_dream(api)
    trip = scoped_trip(api)
    consent(api, trip)
    initial = future_save(api, clock, title="Shared earlier")
    discover(api)
    consent(api, trip, False)
    while_off = future_save(api, clock, title="Private while off")
    clock[0] += timedelta(hours=1)
    consent(api, trip)
    later = future_save(api, clock, title="Shared after consent")
    api.db.delete(initial)
    api.db.commit()
    discover(api)
    assert {idea.title for idea in api.db.query(PlannerIdea).filter_by(trip_id=trip["id"], deleted_at=None)} == {"Shared earlier", "Shared after consent"}
    suggestions = suggested(api, trip)
    assert str(while_off.id) in {item["dream_item_id"] for item in suggestions["suggestions"]}
    assert api.db.query(PlannerContribution).filter_by(trip_id=trip["id"], dream_item_id=None).count() == 1


@pytest.mark.parametrize("placed", [False, True])
def test_late_alias_resolution_respects_tombstone_without_breaking_accepted_plan(api, clock, placed):
    original = seed_dream(api, title="Caffe Nero")
    original.google_place_id = "removed-provider"
    api.db.commit()
    trip = share_all(api, scoped_trip(api))
    consent(api, trip)
    tombstone_id = trip["ideas"][0]["id"]
    assert api.client.delete(f"/planner/trips/{trip['id']}/ideas/{tombstone_id}").status_code == 200
    alias = future_save(api, clock, title="Nero Coffee")
    discover(api)
    current = api.client.get(f"/planner/trips/{trip['id']}").json()
    assert current["idea_count"] == 1
    alias_id = current["ideas"][0]["id"]
    if placed:
        current = save(api, current)
    alias.google_place_id = "removed-provider"
    api.db.commit()
    discover(api)
    discover(api)
    result = api.client.get(f"/planner/trips/{trip['id']}").json()
    if placed:
        assert result["idea_count"] == 1 and result["plan"] == current["plan"]
        assert result["plan"]["days"][0]["stops"][0]["idea_id"] == alias_id
    else:
        assert result["idea_count"] == 0 and result["plan"] is None
        api.db.expire_all()
        assert api.db.get(PlannerIdea, alias_id).merged_into_id == tombstone_id
        assert api.db.query(PlannerContribution).filter_by(trip_id=trip["id"], idea_id=tombstone_id).count() == 2
