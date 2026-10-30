"""Transport modes remain durable and compatible with legacy planner clients."""
from copy import deepcopy

import pytest

from app.planner_models import PlannerJob, PlannerTrip
from app.services import planner as service
from test_planner import api, add, create, invite, join, login, save


def patch(api, trip, **changes):
    return api.client.patch(f"/planner/trips/{trip['id']}", json={"expected_version": trip["version"], **changes})


def test_create_all_modes_roundtrips_and_replays_exactly(api):
    trip, request = create(api, transport_modes=["walk", "drive", "transit"])
    assert trip["transport_modes"] == ["walk", "drive", "transit"] and trip["transport"] == "walk"
    replay = api.client.post("/planner/trips", json=request)
    assert replay.status_code == 201 and replay.json()["id"] == trip["id"]
    fetched = api.client.get(f"/planner/trips/{trip['id']}").json()
    listed = api.client.get("/planner/trips").json()["trips"][0]
    assert fetched["transport_modes"] == listed["transport_modes"] == trip["transport_modes"]
    stored = api.db.get(PlannerTrip, trip["id"])
    assert service.engine_payload(api.db, stored, api.owner.id)["trip"]["transport_modes"] == trip["transport_modes"]
    changed_request = {**request, "transport_modes": ["walk"]}
    assert api.client.post("/planner/trips", json=changed_request).status_code == 409


@pytest.mark.parametrize("mode", ["walk", "drive", "transit"])
def test_legacy_create_maps_primary_mode_and_keeps_previous_idempotency_hash(api, mode):
    trip, request = create(api, transport=mode)
    assert trip["transport_modes"] == [mode] and trip["transport"] == mode
    stored = api.db.get(PlannerTrip, trip["id"])
    legacy_payload = {**request, "dream_item_ids": []}
    assert stored.request_hash == service.digest(legacy_payload)


def test_settings_preserve_array_until_explicit_transport_change_and_never_rewrite_plan(api):
    trip, _ = create(api, transport_modes=["drive", "walk", "transit"])
    assert trip["transport"] == "drive"  # Array is authoritative over the legacy default.
    trip = save(api, add(api, trip))
    plan = deepcopy(trip["plan"])
    renamed = patch(api, trip, title="New title")
    assert renamed.status_code == 200, renamed.text
    renamed = renamed.json()
    assert renamed["transport_modes"] == trip["transport_modes"]
    edited = patch(api, renamed, transport_modes=["transit", "walk"], transport="drive")
    assert edited.status_code == 200, edited.text
    edited = edited.json()
    assert edited["transport_modes"] == ["transit", "walk"] and edited["transport"] == "transit"
    assert edited["version"] == renamed["version"] + 1 and edited["plan"] == plan
    assert api.db.query(PlannerJob).count() == 0
    assert patch(api, renamed, transport_modes=["walk"]).status_code == 409
    legacy_edit = patch(api, edited, transport="drive")
    assert legacy_edit.status_code == 200
    assert legacy_edit.json()["transport_modes"] == ["drive"] and legacy_edit.json()["transport"] == "drive"
    assert legacy_edit.json()["plan"] == plan


@pytest.mark.parametrize("modes", [[], ["walk", "walk"], ["fly"], None, ["walk", "drive", "transit", "walk"], "walk"])
def test_invalid_arrays_rejected_without_mutating_trip(api, modes):
    trip, request = create(api)
    response = patch(api, trip, transport_modes=modes)
    assert response.status_code == 422, response.text
    create_response = api.client.post("/planner/trips", json={**request, "transport_modes": modes})
    assert create_response.status_code == 422
    stored = api.client.get(f"/planner/trips/{trip['id']}").json()
    assert stored["version"] == trip["version"] and stored["transport_modes"] == ["walk"]


def test_member_permissions_apply_to_transport_settings(api):
    trip, _ = create(api, transport_modes=["walk", "transit"])
    invitation, _ = invite(api, trip)
    joined = join(api, invitation["token"])
    assert joined["transport_modes"] == ["walk", "transit"]
    assert patch(api, trip, transport_modes=["drive"]).status_code == 403
    login(api, api.stranger)
    assert patch(api, trip, transport_modes=["drive"]).status_code == 404
