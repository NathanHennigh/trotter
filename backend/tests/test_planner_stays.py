"""Editable accommodation and custom gaps retain shared-plan integrity."""
from copy import deepcopy

from app.planner_models import PlannerIdea, PlannerJob, PlannerRevision, PlannerTrip
from app.services import planner as service
from test_planner import api, add, create, login, save


def plan_with_stay(trip, hotel_id):
    return {"days": [{"date": "2026-11-12", "stops": [{"id": "journal-time", "kind": "break",
        "title": "Coffee and journal", "notes": "Meet by the courtyard", "start_time": "09:00",
        "duration_minutes": 30, "locked": False, "user_created": True}],
        "stay": {"status": "selected", "idea_id": hotel_id, "city": "Marrakech"}},
        {"date": "2026-11-13", "stops": [], "stay": {"status": "needed", "city": "Marrakech"}},
        {"date": "2026-11-14", "stops": [], "stay": {"status": "not_needed"}}],
        "warnings": [], "unplaced_idea_ids": []}


def test_custom_gap_notes_and_selected_stay_roundtrip_history_and_deletion_protection(api):
    trip, _ = create(api, transport_modes=["walk", "transit"])
    trip = add(api, trip, title="Courtyard Riad", category="accommodation")
    hotel_id = trip["ideas"][0]["id"]
    trip = save(api, trip, plan_with_stay(trip, hotel_id))
    stored_plan = trip["plan"]
    assert stored_plan["days"][0]["stay"]["idea_id"] == hotel_id
    stop = stored_plan["days"][0]["stops"][0]
    assert stop["user_created"] is True and stop["notes"] == "Meet by the courtyard"
    assert not stop["locked"] and stop["title"] == "Coffee and journal"
    assert api.db.query(PlannerJob).count() == 0
    assert api.client.get(f"/planner/trips/{trip['id']}").json()["plan"] == stored_plan
    history = api.client.get(f"/planner/trips/{trip['id']}/history").json()["revisions"]
    assert history[0]["plan"]["days"][0]["stay"] == stored_plan["days"][0]["stay"]
    assert api.client.delete(f"/planner/trips/{trip['id']}/ideas/{hotel_id}").status_code == 409
    edited = deepcopy(stored_plan)
    edited["days"][0]["stay"] = {"status": "needed", "city": "Marrakech"}
    edited["days"][0]["stops"][0].update(title="Walk and take photos", notes="Start when everyone is ready")
    trip = save(api, trip, edited)
    assert trip["plan"]["days"][0]["stops"][0]["title"] == "Walk and take photos"
    assert api.client.delete(f"/planner/trips/{trip['id']}/ideas/{hotel_id}").status_code == 200
    original = api.db.get(PlannerRevision, history[0]["id"])
    assert original.plan["days"][0]["stops"][0]["title"] == "Coffee and journal"


def test_stay_ownership_category_and_date_shortening_guard(api):
    trip, _ = create(api)
    trip = add(api, trip, title="Riad", category="hotel")
    hotel_id = trip["ideas"][0]["id"]
    plan = plan_with_stay(trip, hotel_id)
    plan["days"][1]["stay"] = {"status": "selected", "idea_id": hotel_id}
    trip = save(api, trip, plan)
    shrink = api.client.patch(f"/planner/trips/{trip['id']}", json={"expected_version": trip["version"], "end_date": "2026-11-12"})
    assert shrink.status_code == 422
    assert api.client.get(f"/planner/trips/{trip['id']}").json()["version"] == trip["version"]
    login(api, api.friend)
    private, _ = create(api)
    private = add(api, private, title="Private hotel", category="hotel")
    private_id = private["ideas"][0]["id"]
    login(api, api.owner)
    bad = deepcopy(trip["plan"])
    bad["days"][0]["stay"]["idea_id"] = private_id
    response = api.client.put(f"/planner/trips/{trip['id']}/plan", json={"expected_version": trip["version"], "plan": bad})
    assert response.status_code == 422


def test_stay_aliases_restore_to_active_idea_and_protect_current_references(api):
    trip, _ = create(api)
    trip = add(api, trip, title="Old name", category="hotel")
    old_id = trip["ideas"][0]["id"]
    trip = save(api, trip, plan_with_stay(trip, old_id))
    history = api.client.get(f"/planner/trips/{trip['id']}/history").json()["revisions"][0]
    api.db.expire_all()
    model = api.db.get(PlannerTrip, trip["id"])
    assert old_id in service.plan_references(api.db, model)
    blank = deepcopy(trip["plan"])
    blank["days"][0]["stay"] = {"status": "needed"}
    trip = save(api, trip, blank)
    trip = add(api, trip, title="Resolved hotel", category="hotel")
    canonical = next(idea for idea in trip["ideas"] if idea["id"] != old_id)
    old = api.db.get(PlannerIdea, old_id)
    old.merged_into_id, old.deleted_at = canonical["id"], service.now()
    api.db.commit()
    restored = api.client.post(f"/planner/trips/{trip['id']}/restore", json={"expected_version": trip["version"], "revision_id": history["id"]})
    assert restored.status_code == 200, restored.text
    assert restored.json()["plan"]["days"][0]["stay"]["idea_id"] == canonical["id"]
    assert api.db.get(PlannerRevision, history["id"]).plan["days"][0]["stay"]["idea_id"] == old_id


def test_manual_plan_edits_refresh_leg_estimates_without_paid_work_or_history_mutation(api, monkeypatch):
    from app.services import planner_engine, planner_facts
    def no_paid_work(*args, **kwargs):
        raise AssertionError("Manual plan operations must never generate or fetch paid facts")
    monkeypatch.setattr(planner_engine, "generate_plan", no_paid_work)
    monkeypatch.setattr(planner_engine, "collect_facts", no_paid_work)
    monkeypatch.setattr(planner_facts, "_read_coordinate_cache", lambda ideas: (None, {}))
    trip, _ = create(api, transport_modes=["walk"])
    trip = add(api, trip, title="Start", latitude=31.63, longitude=-7.98)
    trip = add(api, trip, title="End", latitude=31.67, longitude=-7.98)
    first, second = trip["ideas"]
    plan = {"days": [{"date": "2026-11-12", "stops": [
        {"id": "first", "idea_id": first["id"], "title": first["title"], "start_time": "10:00", "duration_minutes": 60, "kind": "place", "locked": False},
        {"id": "second", "idea_id": second["id"], "title": second["title"], "start_time": "14:00", "duration_minutes": 60, "kind": "place", "locked": False,
         "travel_minutes": 1, "travel_source": "google", "travel_from_stop_id": "first", "travel_mode": "walk"}]},
        {"date": "2026-11-13", "stops": []}, {"date": "2026-11-14", "stops": []}], "warnings": [], "unplaced_idea_ids": []}
    trip = save(api, trip, plan)
    leg = trip["plan"]["days"][0]["stops"][1]
    assert leg["travel_source"] == "estimate" and leg["travel_minutes"] > 1
    assert leg["travel_from_stop_id"] == "first" and leg["travel_mode"] == "walk"
    revision = api.client.get(f"/planner/trips/{trip['id']}/history").json()["revisions"][0]
    persisted = deepcopy(api.db.get(PlannerRevision, revision["id"]).plan)
    modified = deepcopy(trip["plan"])
    modified["days"][0]["stops"] = [modified["days"][0]["stops"][1]]
    edited = save(api, trip, modified)
    new_first = edited["plan"]["days"][0]["stops"][0]
    assert new_first.get("travel_minutes") is None and new_first.get("travel_from_stop_id") is None
    api.client.get(f"/planner/trips/{trip['id']}")
    api.db.expire_all()
    assert api.db.get(PlannerRevision, revision["id"]).plan == persisted
    assert api.db.query(PlannerJob).count() == 0
