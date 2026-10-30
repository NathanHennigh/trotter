"""Result explanations persist as bounded planning metadata through editing."""
from copy import deepcopy

from app.planner_models import PlannerJob, PlannerRevision, PlannerTrip
from app.services import planner as service, planner_engine
from test_planner import api, add, create, save


def test_reason_survives_save_read_history_and_is_removed_after_manual_placement(api, monkeypatch):
    monkeypatch.setenv("PLANNER_FACTS_ENABLED", "false")
    trip, _ = create(api, transport_modes=["walk"])
    for index in range(3):
        trip = add(api, trip, title=f"Local {index}", latitude=31.63 + index * .001, longitude=-7.99)
    trip = add(api, trip, title="Desert", latitude=31.2, longitude=-8.3)
    trip = add(api, trip, title="Stay option", category="hotel")
    desert = next(idea for idea in trip["ideas"] if idea["title"] == "Desert")
    hotel = next(idea for idea in trip["ideas"] if idea["category"] == "hotel")
    api.db.expire_all()
    payload = service.engine_payload(api.db, api.db.get(PlannerTrip, trip["id"]), api.owner.id)
    plan = planner_engine.generate_plan(payload, use_ai=False)["plan"]
    expected = {"code": "transport_required", "transport_mode": "walk"}
    assert plan["unplaced_reasons"][desert["id"]] == expected
    assert hotel["id"] not in plan["unplaced_reasons"]
    trip = save(api, trip, plan)
    assert api.client.get(f"/planner/trips/{trip['id']}").json()["plan"]["unplaced_reasons"][desert["id"]] == expected
    history = api.client.get(f"/planner/trips/{trip['id']}/history").json()["revisions"][0]
    assert api.db.get(PlannerRevision, history["id"]).plan["unplaced_reasons"][desert["id"]] == expected
    edited = deepcopy(trip["plan"])
    edited["days"][-1]["stops"].append({"id": "manual-desert", "idea_id": desert["id"], "title": desert["title"],
        "start_time": "17:00", "duration_minutes": 60, "kind": "place", "locked": False})
    trip = save(api, trip, edited)
    assert desert["id"] not in trip["plan"]["unplaced_reasons"]
    assert api.db.get(PlannerRevision, history["id"]).plan["unplaced_reasons"][desert["id"]] == expected
    assert api.db.query(PlannerJob).count() == 0
