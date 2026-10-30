"""Planner invariants: actual choices, locality, locks and bounded provider use."""
from copy import deepcopy
import asyncio
import json

import httpx
import pytest

from app.services import planner_ai, planner_engine as engine, planner_facts as facts


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv("PLANNER_FACTS_ENABLED", "false")
    monkeypatch.setenv("PLANNER_AI_ENABLED", "true")
    for name in ("PLANNER_AI_API_KEY", "PLANNER_AI_API_KEY_FILE", "VENICE_API_KEY", "VENICE_API_KEY_FILE",
                 "GOOGLE_PLACES_API_KEY", "GOOGLE_ROUTES_API_KEY", "PLANNER_AI_MODEL",
                 "PLANNER_AI_MAX_COST_USD", "PLANNER_MAX_JOB_COST_USD", "PLANNER_AI_INPUT_USD_PER_MILLION",
                 "PLANNER_AI_OUTPUT_USD_PER_MILLION", "PLANNER_AI_MAX_COMPLETION_TOKENS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(httpx, "post", lambda *args, **kwargs: pytest.fail("Unexpected network request"))


def idea(identifier, **changes):
    return {"id": identifier, "title": "Place " + identifier, "city": "Marrakech", "country": "Morocco",
            "category": "sight", "latitude": 31.63, "longitude": -7.99, "score": 1,
            "duration_minutes": 60, "status": "ready", **changes}


def payload(*ideas, **changes):
    return {"trip": {"id": "trip", "destination": "Morocco", "start_date": "2026-11-12", "end_date": "2026-11-13",
                     "timezone": "UTC", "pace": "balanced", "transport": "walk"},
            "ideas": list(ideas) or [idea("a"), idea("b", longitude=-7.991), idea("c", longitude=-7.993)], **changes}


def place_stops(plan):
    return [stop for day in plan["days"] for stop in day["stops"] if stop.get("idea_id")]


def stop(identifier="anchor", **changes):
    return {"id": identifier, "title": "Booked tour", "start_time": "11:00", "duration_minutes": 60,
            "kind": "booking", "locked": True, **changes}


def test_automatic_schedule_uses_only_saved_places_with_valid_nonoverlapping_times():
    data = payload()
    result = engine.generate_plan(data, use_ai=False)
    planned = place_stops(result["plan"])
    assert len(planned) == 3
    assert {s["idea_id"] for s in planned} == {"a", "b", "c"}
    assert len({s["id"] for s in planned}) == 3
    assert result["source"] == "rules"
    assert result["usage"]["cost_usd"] == 0
    assert engine.validate_plan(result["plan"], data) == result["plan"]
    assert any("Opening hours" in value for value in result["plan"]["warnings"])


def test_must_do_wins_when_day_capacity_is_limited_and_unplaced_is_explicit():
    data = payload(*[idea(str(i), score=5 if i != 7 else 0, must_do=i == 7) for i in range(8)])
    data["trip"].update(end_date="2026-11-12", pace="relaxed")
    plan = engine.generate_plan(data, use_ai=False)["plan"]
    assert "7" in {s["idea_id"] for s in place_stops(plan)}
    assert len(place_stops(plan)) == 3
    assert len(plan["unplaced_idea_ids"]) == 5


def test_respects_opening_windows_and_does_not_schedule_closed_places():
    data = payload(idea("late", opening_windows={"2026-11-12": [[840, 960]], "2026-11-13": []}),
                   idea("closed", opening_windows={"2026-11-12": [], "2026-11-13": []}),
                   idea("permanent", closed=True))
    result = engine.generate_plan(data, use_ai=False)["plan"]
    planned = place_stops(result)
    assert [s["idea_id"] for s in planned] == ["late"]
    assert 840 <= engine.minutes(planned[0]["start_time"]) <= 900
    assert set(result["unplaced_idea_ids"]) == {"closed", "permanent"}


def test_keeps_different_cities_on_separate_days():
    data = payload(idea("m", score=3), idea("t", city="Taghazout", latitude=30.54, longitude=-9.71))
    data["trip"]["transport"] = "drive"
    plan = engine.generate_plan(data, use_ai=False)["plan"]
    assert [s["idea_id"] for s in plan["days"][0]["stops"] if s.get("idea_id")] == ["m"]
    assert [s["idea_id"] for s in plan["days"][1]["stops"] if s.get("idea_id")] == ["t"]
    assert any("estimate" in warning for warning in plan["warnings"])


def test_known_travel_time_can_make_stop_infeasible():
    data = payload(idea("a", opening_windows={"2026-11-12": [[540, 600]]}),
                   idea("b", opening_windows={"2026-11-12": [[615, 675]]}),
                   routes=[{"from_id": "a", "to_id": "b", "minutes": 120, "source": "google"}])
    data["trip"]["end_date"] = "2026-11-12"
    plan = engine.generate_plan(data, use_ai=False)["plan"]
    assert len(place_stops(plan)) == 1


def test_locked_bookings_and_overnight_arrivals_are_never_moved():
    anchor = stop(start_time="23:00", duration_minutes=660, notes="Confirmed")
    old = {"days": [{"date": "2026-11-12", "stops": [anchor]}, {"date": "2026-11-13", "stops": []}]}
    data = payload(existing_plan=old)
    plan = engine.generate_plan(data, use_ai=False)["plan"]
    assert next(s for s in plan["days"][0]["stops"] if s["id"] == "anchor") == anchor
    for item in plan["days"][1]["stops"]:
        assert engine.minutes(item["start_time"]) >= 600


def test_rework_day_preserves_other_days_and_locked_stops_exactly(monkeypatch):
    old_a = stop("a-stop", idea_id="a", kind="place", title="Place a", locked=False)
    anchor = stop()
    old = {"days": [{"date": "2026-11-12", "stops": [old_a]}, {"date": "2026-11-13", "stops": [anchor]}]}
    data = payload(existing_plan=old, day="2026-11-13", pace="relaxed")
    captured = []
    def ai(brief):
        captured.append(brief)
        return {"days": [{"date": "2026-11-13", "idea_ids": ["b", "c"]}], "unplaced_idea_ids": []}, {"cost_usd": .01}
    monkeypatch.setattr(planner_ai, "compose", ai)
    plan = engine.generate_plan(data)["plan"]
    assert plan["days"][0] == old["days"][0]
    assert next(s for s in plan["days"][1]["stops"] if s["id"] == "anchor") == anchor
    assert captured[0]["dates"] == ["2026-11-13"]
    assert "a" not in {item["id"] for item in captured[0]["ideas"]}


def test_ai_shortlist_is_a_day_preference_and_other_eligible_saves_remain_available(monkeypatch):
    data = payload(idea("a"), idea("b"), idea("c"))
    monkeypatch.setattr(planner_ai, "compose", lambda brief: ({"days": [{"date": "2026-11-13", "idea_ids": ["b"]}],
                                                             "unplaced_idea_ids": ["a", "c"]}, {"cost_usd": .02}))
    result = engine.generate_plan(data)
    assert result["source"] == "ai"
    assert {s["idea_id"] for s in place_stops(result["plan"])} == {"a", "b", "c"}
    assert [s["idea_id"] for s in result["plan"]["days"][1]["stops"] if s.get("idea_id")] == ["b"]
    assert result["plan"]["unplaced_idea_ids"] == []


def test_ai_failure_retains_billed_usage_and_returns_valid_baseline(monkeypatch):
    def unavailable(_):
        raise planner_ai.PlannerAIError("AI is unavailable.", usage={"cost_usd": .03, "model": "kimi-k2-5"})
    monkeypatch.setattr(planner_ai, "compose", unavailable)
    result = engine.generate_plan(payload())
    assert result["source"] == "rules"
    assert result["usage"]["cost_usd"] == .03
    assert len(place_stops(result["plan"])) == 3


def test_confident_duplicate_identity_not_repeated_but_same_name_other_city_is_not_merged():
    data = payload(idea("a", google_place_id="place1"), idea("b", google_place_id="place1"),
                   idea("c", title="Place a", city="Essaouira", latitude=31.51, longitude=-9.76))
    data["trip"]["transport"] = "drive"
    plan = engine.generate_plan(data, use_ai=False)["plan"]
    ids = {s["idea_id"] for s in place_stops(plan)}
    assert len(ids & {"a", "b"}) == 1
    assert "c" in ids


def test_missing_coordinates_never_fabricate_precise_transit_minutes():
    data = payload(idea("a", latitude=None, longitude=None), idea("b", latitude=None, longitude=None))
    data["trip"]["transport"] = "transit"
    data["trip"]["end_date"] = data["trip"]["start_date"]
    plan = engine.generate_plan(data, use_ai=False)["plan"]
    assert all("travel_minutes" not in s for s in place_stops(plan))
    assert any("unverified" in warning for warning in plan["warnings"])


@pytest.mark.parametrize("transport", ["walk", "drive", "transit"])
def test_unknown_intercity_transfer_is_not_a_thirty_minute_local_buffer(transport):
    data = payload(idea("paris", city="Paris", country="France", latitude=None, longitude=None, score=5),
                   idea("lyon", city="Lyon", country="France", latitude=None, longitude=None))
    data["trip"].update(transport=transport, timezone="Europe/Paris")
    plan = engine.generate_plan(data, use_ai=False)["plan"]
    assert {entry["idea_id"] for entry in place_stops(plan)} == {"paris"}
    assert "lyon" in plan["unplaced_idea_ids"]
    assert any("city-to-city" in warning for warning in plan["warnings"])


def test_supplied_intercity_route_reserves_real_transfer_time():
    data = payload(idea("paris", city="Paris", country="France", latitude=None, longitude=None, score=5),
                   idea("lyon", city="Lyon", country="France", latitude=None, longitude=None),
                   routes=[{"from_id": "paris", "to_id": "lyon", "minutes": 180, "source": "google"}])
    data["trip"].update(transport="transit", timezone="Europe/Paris")
    plan = engine.generate_plan(data, use_ai=False)["plan"]
    lyon = next(entry for entry in place_stops(plan) if entry["idea_id"] == "lyon")
    assert engine.minutes(lyon["start_time"]) >= 720
    # Google informed the schedule, but cross-day legs are not presented as
    # though they came from the preceding activity within this day.
    assert "travel_minutes" not in lyon
    assert "travel_from_stop_id" not in lyon


def test_rules_spread_six_local_sights_across_three_days():
    data = payload(*[idea(str(i), title=f"Paris sight {i}", city="Paris", country="France",
                          latitude=48.86, longitude=2.33 + i / 1000) for i in range(6)])
    data["trip"].update(end_date="2026-11-14", timezone="Europe/Paris")
    plan = engine.generate_plan(data, use_ai=False)["plan"]
    assert [len([s for s in day["stops"] if s.get("idea_id")]) for day in plan["days"]] == [2, 2, 2]


@pytest.mark.parametrize(("pace", "expected_count"), [("relaxed", 3), ("balanced", 4), ("packed", 6)])
def test_day_pace_retains_bounded_visit_counts(pace, expected_count):
    data = payload(*[idea(str(i), latitude=48.86, longitude=2.33 + i / 10000) for i in range(8)])
    data["trip"].update(end_date="2026-11-12", pace=pace)
    assert len(place_stops(engine.generate_plan(data, use_ai=False)["plan"])) == expected_count


def test_equal_group_votes_include_underrepresented_traveller_and_skip_downvoted_idea():
    data = payload(*[idea("9" + str(i), votes=[{"user_id": "alice", "value": 1}]) for i in range(4)],
                   idea("0-bob", votes=[{"user_id": "bob", "value": 1}]),
                   idea("downvoted", score=-1, votes=[{"user_id": "alice", "value": -1}]))
    data["trip"].update(end_date="2026-11-12", pace="relaxed")
    plan = engine.generate_plan(data, use_ai=False)["plan"]
    planned = {entry["idea_id"] for entry in place_stops(plan)}
    assert "0-bob" in planned
    assert any(identifier.startswith("9") for identifier in planned)
    assert "downvoted" in plan["unplaced_idea_ids"]


def test_pacing_does_not_postpone_places_only_open_on_first_day():
    only_first = {"2026-11-12": [[540, 1200]], "2026-11-13": [], "2026-11-14": []}
    data = payload(idea("market", opening_windows=only_first, score=1), idea("gallery", opening_windows=only_first, score=1),
                   idea("park", score=10), idea("cafe", category="cafe", score=8))
    data["trip"]["end_date"] = "2026-11-14"
    plan = engine.generate_plan(data, use_ai=False)["plan"]
    assert {s["idea_id"] for s in plan["days"][0]["stops"] if s.get("idea_id")} == {"market", "gallery"}
    assert len(place_stops(plan)) == 4


def test_fixed_break_does_not_hide_the_next_booking_transfer():
    data = payload(idea("candidate", opening_windows={"2026-11-12": [[540, 600]]}), idea("appointment"),
                   existing_plan={"days": [{"date": "2026-11-12", "stops": [
                       stop("break", title="Rest", kind="break", start_time="11:00", duration_minutes=45),
                       stop("booking", title="Place appointment", idea_id="appointment", start_time="12:00"),
                   ]}]}, routes=[{"from_id": "candidate", "to_id": "appointment", "minutes": 180, "source": "google"}])
    data["trip"]["end_date"] = "2026-11-12"
    plan = engine.generate_plan(data, use_ai=False)["plan"]
    assert "candidate" in plan["unplaced_idea_ids"]
    assert {s["id"] for s in plan["days"][0]["stops"]} >= {"break", "booking"}


def test_rework_keeps_manual_visit_duration_notes_and_selected_hotel(monkeypatch):
    data = payload(idea("museum"), idea("hotel", category="hotel"), existing_plan={"days": [{"date": "2026-11-12", "stops": [
        stop("museum-stop", idea_id="museum", title="Place museum", kind="place", locked=False,
             start_time="10:00", duration_minutes=45, notes="Meet Jo by the entrance"),
        stop("checkin", idea_id="hotel", title="Place hotel", kind="place", locked=False,
             start_time="15:00", duration_minutes=20, notes="Reservation confirmed"),
    ]}]})
    monkeypatch.setattr(planner_ai, "compose", lambda _: ({"days": [{"date": "2026-11-12", "idea_ids": ["museum"]}],
                                                         "unplaced_idea_ids": ["hotel"]}, {}))
    plan = engine.generate_plan(data)["plan"]
    entries = {entry["idea_id"]: entry for entry in place_stops(plan)}
    assert entries["museum"]["duration_minutes"] == 45
    assert entries["museum"]["notes"] == "Meet Jo by the entrance"
    assert entries["hotel"]["id"] == "checkin"
    assert entries["hotel"]["duration_minutes"] == 20
    assert entries["hotel"]["notes"] == "Reservation confirmed"


def test_partial_hours_do_not_imply_other_dates_are_verified():
    data = payload(idea("museum", opening_windows={"2026-11-12": []}))
    plan = engine.generate_plan(data, use_ai=False)["plan"]
    assert len(place_stops(plan)) == 1
    assert any("Opening hours are not known" in warning for warning in plan["warnings"])


def test_one_day_rework_does_not_invent_a_journey_to_tomorrows_fixed_booking():
    appointment = stop("kyoto-booking", title="Place kyoto", idea_id="kyoto", start_time="09:00")
    old_day = {"date": "2026-11-13", "stops": [appointment]}
    data = payload(idea("tokyo", city="Tokyo", country="Japan", latitude=None, longitude=None),
                   idea("kyoto", city="Kyoto", country="Japan", latitude=None, longitude=None),
                   day="2026-11-12", existing_plan={"days": [old_day]})
    data["trip"].update(transport="transit", timezone="Asia/Tokyo")
    plan = engine.generate_plan(data, use_ai=False)["plan"]
    assert "tokyo" in plan["unplaced_idea_ids"]
    assert plan["days"][1] == old_day


def test_local_time_validation_rejects_nonexistent_spring_clock_time():
    data = payload()
    data["trip"].update(start_date="2027-03-14", end_date="2027-03-14", timezone="America/New_York")
    plan = {"days": [{"date": "2027-03-14", "stops": [stop(start_time="02:30")]}]}
    with pytest.raises(ValueError, match="does not exist"):
        engine.validate_plan(plan, data)


def test_overnight_spring_booking_uses_elapsed_time_for_arrival():
    booking = stop(start_time="23:30", duration_minutes=600)
    data = payload(existing_plan={"days": [{"date": "2027-03-13", "stops": [booking]}]})
    data["trip"].update(start_date="2027-03-13", end_date="2027-03-14", timezone="America/New_York")
    plan = engine.generate_plan(data, use_ai=False)["plan"]
    assert all(engine.minutes(entry["start_time"]) >= 630 for entry in plan["days"][1]["stops"])
    assert any("Clocks change" in warning for warning in plan["warnings"])


def test_fall_back_booking_does_not_claim_an_extra_hour_after_arrival():
    booking = stop(start_time="23:30", duration_minutes=600)
    morning = stop("morning", idea_id="a", kind="place", start_time="09:00", locked=False)
    data = payload()
    data["trip"].update(start_date="2026-10-31", end_date="2026-11-01", timezone="America/New_York")
    plan = {"days": [{"date": "2026-10-31", "stops": [booking]}, {"date": "2026-11-01", "stops": [morning]}]}
    assert engine.validate_plan(plan, data)["days"][1]["stops"][0]["start_time"] == "09:00"


def test_repeated_fall_clock_hour_is_disclosed():
    data = payload()
    data["trip"].update(start_date="2026-11-01", end_date="2026-11-01", timezone="America/New_York")
    plan = {"days": [{"date": "2026-11-01", "stops": [stop(start_time="01:30", duration_minutes=20)]}]}
    assert any("repeated hour" in warning for warning in engine.validate_plan(plan, data)["warnings"])


def test_direct_validation_rejects_unknown_duplicate_overlapping_and_moved_locked_stops():
    data = payload()
    valid = {"days": [{"date": "2026-11-12", "stops": [stop(kind="place", idea_id="a", locked=False)]}]}
    bad = deepcopy(valid)
    bad["days"][0]["stops"][0]["idea_id"] = "somebody-elses-place"
    with pytest.raises(ValueError, match="no longer"):
        engine.validate_plan(bad, data)
    bad = deepcopy(valid)
    bad["days"][0]["stops"].append(stop("duplicate", kind="place", idea_id="a", start_time="14:00"))
    with pytest.raises(ValueError, match="only once"):
        engine.validate_plan(bad, data)
    bad = deepcopy(valid)
    bad["days"][0]["stops"].append(stop("overlap", start_time="11:30"))
    with pytest.raises(ValueError, match="overlap"):
        engine.validate_plan(bad, data)
    data["existing_plan"] = {"days": [{"date": "2026-11-12", "stops": [stop()]}]}
    with pytest.raises(ValueError, match="locked"):
        engine.validate_plan({"days": []}, data, preserve_locked=True)


def test_manual_validation_and_storage_never_call_ai_and_strip_only_google_route_content(monkeypatch):
    monkeypatch.setattr(planner_ai, "compose", lambda _: pytest.fail("Manual editing invoked AI"))
    original = {"days": [{"date": "2026-11-12", "stops": [stop(kind="place", idea_id="a", locked=False,
              travel_minutes=17, travel_source="google")]}]}
    valid = engine.validate_plan(original, payload())
    stored = engine.plan_for_storage(valid)
    assert "travel_minutes" not in stored["days"][0]["stops"][0]
    assert valid["days"][0]["stops"][0]["travel_minutes"] == 17


def test_opening_periods_support_closed_days_and_overnight_hours():
    periods = {"periods": [{"open": {"day": 4, "hour": 22}, "close": {"day": 5, "hour": 2}}]}
    result = facts.opening_windows(periods, ["2026-11-12", "2026-11-13", "2026-11-14"])
    assert result == {"2026-11-12": [[1320, 1440]], "2026-11-13": [[0, 120]], "2026-11-14": []}
    assert facts.opening_windows({}, ["2026-11-12"]) == {}
    assert facts.opening_windows({"periods": []}, ["2026-11-12"]) == {"2026-11-12": []}


def test_current_hours_are_not_reused_on_future_dates():
    current = {"periods": [{"open": {"date": {"year": 2026, "month": 11, "day": 12}, "hour": 9},
                            "close": {"date": {"year": 2026, "month": 11, "day": 12}, "hour": 17}}]}
    assert facts.opening_windows(current, ["2026-11-12", "2026-11-19"], dated=True) == {"2026-11-12": [[540, 1020]]}


def brief():
    return {"dates": ["2026-11-12"], "ideas": [{"id": "a", "title": "A place"}], "pace": "relaxed"}


def fake_response(content=None, **changes):
    return {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(content or {
        "days": [{"date": "2026-11-12", "idea_ids": ["p1"]}], "unplaced_idea_ids": []})}}],
        "usage": {"prompt_tokens": 1000, "completion_tokens": 500,
                  "completion_tokens_details": {"reasoning_tokens": 300}}, **changes}


def test_ai_cost_and_schema_are_bounded_and_reasoning_not_double_counted(monkeypatch):
    monkeypatch.setenv("PLANNER_AI_API_KEY", "synthetic-secret")
    calls = []
    def post(url, **kwargs):
        calls.append((url, kwargs))
        return httpx.Response(200, json=fake_response())
    monkeypatch.setattr(httpx, "post", post)
    proposed, usage = planner_ai.compose(brief())
    assert len(calls) == 1
    request = calls[0][1]["json"]
    assert request["max_completion_tokens"] == 4096
    assert request["venice_parameters"]["enable_web_search"] == "off"
    assert request["response_format"]["json_schema"]["strict"] is True
    assert usage["output_tokens"] == 500
    assert usage["cost_usd"] == pytest.approx(.00231)
    assert proposed["days"][0]["idea_ids"] == ["a"]


@pytest.mark.parametrize("bad", [
    {"days": [{"date": "2026-11-12", "idea_ids": ["invented"]}], "unplaced_idea_ids": []},
    {"days": [{"date": "2026-11-12", "idea_ids": ["p1", "p1"]}], "unplaced_idea_ids": []},
    {"days": [{"date": "2027-01-01", "idea_ids": ["p1"]}], "unplaced_idea_ids": []},
    {"days": [], "unplaced_idea_ids": ["p1"]},
])
def test_invalid_ai_ids_or_empty_proposals_fail_without_a_paid_retry(monkeypatch, bad):
    monkeypatch.setenv("PLANNER_AI_API_KEY", "synthetic-secret")
    calls = []
    monkeypatch.setattr(httpx, "post", lambda *a, **k: calls.append(1) or httpx.Response(200, json=fake_response(bad)))
    with pytest.raises(planner_ai.PlannerAIError) as error:
        planner_ai.compose(brief())
    assert len(calls) == 1
    assert error.value.usage["cost_usd"] > 0


def test_ai_compact_aliases_roundtrip_uuid_selections_and_unplaced(monkeypatch):
    monkeypatch.setenv("PLANNER_AI_API_KEY", "synthetic-secret")
    first, second = "11111111-1111-4111-a111-111111111111", "22222222-2222-4222-a222-222222222222"
    locked = "33333333-3333-4333-a333-333333333333"
    data = {**brief(), "ideas": [{"id": first, "title": "First"}, {"id": second, "title": "Second"}],
            "locked_stops": [{"date": "2026-11-12", "idea_id": locked, "title": "Fixed visit", "start_time": "10:00", "duration_minutes": 60}]}
    original = deepcopy(data)
    requests = []
    reply = {"days": [{"date": "2026-11-12", "idea_ids": ["p2"]}], "unplaced_idea_ids": ["p1"]}
    monkeypatch.setattr(httpx, "post", lambda *a, **k: requests.append(k["json"]) or httpx.Response(200, json=fake_response(reply)))
    result, _ = planner_ai.compose(data)
    assert result == {"days": [{"date": "2026-11-12", "idea_ids": [second]}], "unplaced_idea_ids": [first]}
    request = requests[0]
    sent = json.loads(request["messages"][1]["content"])
    assert [entry["id"] for entry in sent["ideas"]] == ["p1", "p2"]
    assert sent["locked_stops"][0]["idea_id"] == "locked1"
    assert sent["locked_stops"][0]["start_time"] == "10:00"
    assert all(value not in json.dumps(request) for value in (first, second, locked))
    assert data == original


@pytest.mark.parametrize("bad_alias", ["p0", "p2", "locked1", "11111111-1111-4111-a111-111111111111"])
def test_ai_aliases_never_accept_unknown_or_original_uuid(monkeypatch, bad_alias):
    monkeypatch.setenv("PLANNER_AI_API_KEY", "synthetic-secret")
    data = {**brief(), "ideas": [{"id": "11111111-1111-4111-a111-111111111111", "title": "First"}]}
    reply = {"days": [{"date": "2026-11-12", "idea_ids": [bad_alias]}], "unplaced_idea_ids": []}
    calls = []
    monkeypatch.setattr(httpx, "post", lambda *a, **k: calls.append(1) or httpx.Response(200, json=fake_response(reply)))
    with pytest.raises(planner_ai.PlannerAIError) as error:
        planner_ai.compose(data)
    assert error.value.usage["validation_error"] == "Unknown idea"
    assert calls == [1]


def test_ai_alias_roundtrip_keeps_real_locked_stop_identity_and_time(monkeypatch):
    monkeypatch.setenv("PLANNER_AI_API_KEY", "synthetic-secret")
    first, fixed = "11111111-1111-4111-a111-111111111111", "22222222-2222-4222-a222-222222222222"
    locked = stop("locked-stop-uuid", idea_id=fixed, title="Place " + fixed, kind="place")
    data = payload(idea(first), idea(fixed), existing_plan={"days": [{"date": "2026-11-12", "stops": [locked]}]})
    monkeypatch.setattr(httpx, "post", lambda *a, **k: httpx.Response(200, json=fake_response()))
    result = engine.generate_plan(data, use_ai=True)
    planned = place_stops(result["plan"])
    assert result["source"] == "ai"
    assert {entry["idea_id"] for entry in planned} == {first, fixed}
    kept = next(entry for entry in planned if entry["id"] == "locked-stop-uuid")
    for field in ("id", "idea_id", "start_time", "duration_minutes", "locked", "kind"):
        assert kept[field] == locked[field]


def test_ai_allowance_is_enforced_before_network_including_dynamic_schema(monkeypatch):
    monkeypatch.setenv("PLANNER_AI_API_KEY", "synthetic-secret")
    monkeypatch.setenv("PLANNER_MAX_JOB_COST_USD", "0.001")
    with pytest.raises(planner_ai.PlannerAIError, match="allowance"):
        planner_ai.compose(brief())


def test_timeout_conservatively_accounts_for_uncertain_paid_request(monkeypatch):
    monkeypatch.setenv("PLANNER_AI_API_KEY", "synthetic-secret")
    def timeout(*a, **k):
        raise httpx.ReadTimeout("provider secret must never leak")
    monkeypatch.setattr(httpx, "post", timeout)
    with pytest.raises(planner_ai.PlannerAIError) as error:
        planner_ai.compose(brief())
    assert "secret" not in str(error.value)
    assert 0 < error.value.usage["cost_usd"] <= .08
    assert error.value.usage["estimated"] is True


def test_route_provider_is_bounded_and_authorization_failure_not_retried(monkeypatch):
    f = facts.FactSet({"a": idea("a"), "b": idea("b")}, "walk", route_key="synthetic")
    f.route_deadline = facts.time.monotonic() + 10
    calls = []
    monkeypatch.setattr(httpx, "post", lambda *a, **k: calls.append(1) or httpx.Response(403, json={"secret": "do not leak"}))
    first = f.travel(f.ideas["a"], f.ideas["b"], live=True)
    second = f.travel(f.ideas["a"], f.ideas["b"], live=True)
    assert first == second
    assert first[1] == "estimate"
    assert len(calls) == 1


def test_transit_does_not_apply_current_timetable_to_future_trip(monkeypatch):
    f = facts.FactSet({"a": idea("a"), "b": idea("b")}, "transit", route_key="synthetic")
    f.route_deadline = facts.time.monotonic() + 10
    calls = []
    monkeypatch.setattr(httpx, "post", lambda *a, **k: calls.append(1) or httpx.Response(200, json={"routes": [{"duration": "600s"}]}))
    assert f.travel(f.ideas["a"], f.ideas["b"], live=True) == (None, "unknown")
    assert calls == []


def test_place_lookups_skip_already_located_stay_options_and_deduplicate_google_ids(monkeypatch):
    calls = []
    class Client:
        def __init__(self, **kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def get(self, url, **kwargs):
            place_id = url.rsplit("/", 1)[1]
            calls.append(place_id)
            return httpx.Response(200, json={"id": place_id, "location": {"latitude": 31.6, "longitude": -7.9}})
    monkeypatch.setattr(httpx, "AsyncClient", Client)
    result, warnings = asyncio.run(facts._live_places([
        idea("a", google_place_id="ChIJ_same_venue"),
        idea("duplicate", google_place_id="ChIJ_same_venue"),
        idea("hotel", category="hotel", google_place_id="ChIJ_hotel_option"),
        idea("checkin", category="hotel", google_place_id="ChIJ_chosen_hotel", schedule_as_visit=True),
    ], ["2026-11-12"], "synthetic"))
    assert calls == ["ChIJ_same_venue", "ChIJ_chosen_hotel"]
    assert set(result) == {"a", "duplicate", "checkin"}
    assert result["a"] == result["duplicate"]
    assert warnings == []


def test_unknown_saved_hotels_use_three_coordinate_only_slots_within_total_lookup_cap(monkeypatch):
    monkeypatch.setenv("PLANNER_PLACE_LOOKUP_LIMIT", "10")
    calls = []
    class Client:
        def __init__(self, **kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def get(self, url, **kwargs):
            place_id = url.rsplit("/", 1)[1]
            calls.append((place_id, kwargs["headers"]["X-Goog-FieldMask"]))
            return httpx.Response(200, json={"id": place_id, "location": {"latitude": 31.63, "longitude": -7.99}})
    monkeypatch.setattr(httpx, "AsyncClient", Client)
    saves = [idea(str(i), google_place_id=f"ChIJ_visit_{i}") for i in range(12)]
    saves += [idea(f"hotel{i}", category="hotel", google_place_id=f"ChIJ_hotel_{i}",
                   latitude=None, longitude=None, city="Rabat" if i == 0 else "Marrakesh", country="MA") for i in range(20)]
    result, _ = asyncio.run(facts._live_places(saves, ["2026-11-12"], "synthetic"))
    assert len(calls) == 10
    hotel_calls = [(identifier, mask) for identifier, mask in calls if "hotel" in identifier]
    assert len(hotel_calls) == 3
    assert all(mask == "id,location" for _, mask in hotel_calls)
    assert all(identifier != "ChIJ_hotel_0" for identifier, _ in hotel_calls)
    assert all("regularOpeningHours" in mask for identifier, mask in calls if "visit" in identifier)
    assert all(set(value) == {"latitude", "longitude"} for key, value in result.items() if key.startswith("hotel"))


def test_same_city_without_hotel_coordinates_stays_needed_until_bounded_lookup_establishes_proximity(monkeypatch):
    data = payload(idea("sight"), idea("hotel", category="hotel", google_place_id="ChIJ_hotel",
                                       latitude=None, longitude=None))
    offline_plan = engine.generate_plan(data, use_ai=False)["plan"]
    assert offline_plan["days"][0]["stay"]["status"] == "needed"
    assert "hotel" in offline_plan["unplaced_idea_ids"]
    monkeypatch.setenv("PLANNER_FACTS_ENABLED", "true")
    monkeypatch.setenv("GOOGLE_PLACES_API_KEY", "synthetic")
    monkeypatch.setattr(facts, "_coordinate_cache", lambda: None)
    calls = []
    class Client:
        def __init__(self, **kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def get(self, url, **kwargs):
            calls.append(kwargs["headers"]["X-Goog-FieldMask"])
            return httpx.Response(200, json={"id": "ChIJ_hotel", "location": {"latitude": 31.6301, "longitude": -7.99}})
    monkeypatch.setattr(httpx, "AsyncClient", Client)
    known_plan = engine.generate_plan(data, use_ai=False)["plan"]
    assert calls == ["id,location"]
    assert known_plan["days"][0]["stay"]["status"] == "suggested"
    assert known_plan["days"][0]["stay"]["idea_id"] == "hotel"
    assert "hotel" not in known_plan["unplaced_idea_ids"]


def test_coordinate_cache_is_ephemeral_allowlisted_and_reused_without_hours(monkeypatch):
    stored = {}
    class Cache:
        def mget(self, keys):
            return [stored.get(key) for key in keys]
        def pipeline(self, **kwargs):
            return self
        def set(self, key, value, *, ex):
            assert ex == 21600
            stored[key] = value
            return self
        def execute(self):
            pass
    cache = Cache()
    monkeypatch.setattr(facts, "_coordinate_cache", lambda: cache)
    target = idea("a", google_place_id="ChIJ_venue", latitude=None, longitude=None)
    _, initial = facts._read_coordinate_cache([target])
    assert initial == {}
    facts._write_coordinate_cache(cache, {"a": target}, {"a": {
        "latitude": 31.6, "longitude": -7.9, "opening_windows": {"2026-11-12": [[540, 600]]},
        "name": "Must never cache", "closed": True,
    }})
    raw = json.loads(next(iter(stored.values())))
    assert set(raw) == {"place_id", "latitude", "longitude", "expires_at"}
    monkeypatch.setenv("PLANNER_FACTS_ENABLED", "true")
    result = facts.collect_facts(payload(target), ["2026-11-12"])
    assert result.ideas["a"]["latitude"] == 31.6
    assert "opening_windows" not in result.ideas["a"]
    raw["expires_at"] = facts.time.time() - 1
    stored[next(iter(stored))] = json.dumps(raw)
    assert facts._read_coordinate_cache([target])[1] == {}


def test_coordinate_cache_failure_never_blocks_manual_facts(monkeypatch):
    def unavailable():
        raise RuntimeError("synthetic unavailable cache")
    monkeypatch.setattr(facts, "_coordinate_cache", unavailable)
    monkeypatch.setenv("PLANNER_FACTS_ENABLED", "true")
    data = payload(idea("a", google_place_id="ChIJ_venue"))
    result = facts.collect_facts(data, ["2026-11-12"])
    assert result.ideas["a"]["latitude"] == 31.63


def test_live_place_facts_do_not_replace_manual_coordinates_or_hours(monkeypatch):
    monkeypatch.setenv("PLANNER_FACTS_ENABLED", "true")
    monkeypatch.setenv("GOOGLE_PLACES_API_KEY", "synthetic")
    monkeypatch.setattr(facts, "_read_coordinate_cache", lambda *_: (None, {}))
    async def live(*args):
        return {"a": {"latitude": 25, "longitude": 10,
                      "opening_windows": {"2026-11-12": [[900, 1000]]}, "hours_source": "google"}}, []
    monkeypatch.setattr(facts, "_live_places", live)
    data = payload(idea("a", google_place_id="ChIJ_venue", opening_windows={"2026-11-12": [[540, 600]]}))
    result = facts.collect_facts(data, ["2026-11-12"])
    assert result.ideas["a"]["latitude"] == 31.63
    assert result.ideas["a"]["longitude"] == -7.99
    assert result.ideas["a"]["opening_windows"] == {"2026-11-12": [[540, 600]]}


def test_provider_no_route_does_not_turn_into_an_invented_connection(monkeypatch):
    data = payload(idea("a", score=10), idea("b"))
    data["trip"]["end_date"] = "2026-11-12"
    f = facts.FactSet({item["id"]: item for item in data["ideas"]}, "walk", route_key="synthetic")
    monkeypatch.setattr(httpx, "post", lambda *a, **k: httpx.Response(200, json={"routes": []}))
    monkeypatch.setattr(engine, "collect_facts", lambda *_: f)
    result = engine.generate_plan(data, use_ai=False)
    assert [s["idea_id"] for s in place_stops(result["plan"])] == ["a"]
    assert "b" in result["plan"]["unplaced_idea_ids"]


def test_lunch_break_does_not_consume_required_transfer_time():
    data = payload(idea("a", opening_windows={"2026-11-12": [[660, 720]]}, score=4),
                   idea("b", opening_windows={"2026-11-12": [[810, 870]]}),
                   routes=[{"from_id": "a", "to_id": "b", "minutes": 60, "source": "google"}])
    data["trip"]["end_date"] = "2026-11-12"
    plan = engine.generate_plan(data, use_ai=False)["plan"]
    for entry in plan["days"][0]["stops"]:
        if entry["kind"] == "break":
            start = engine.minutes(entry["start_time"])
            assert start >= 885 or start + entry["duration_minutes"] + 60 + 20 <= 810


def test_hotels_are_options_not_automatic_sightseeing_stops():
    data = payload(idea("riad", category="accommodation", must_do=True), idea("hotel", category="hotel"),
                   idea("restaurant", category="restaurant"))
    result = engine.generate_plan(data, use_ai=False)["plan"]
    assert {stop["idea_id"] for stop in place_stops(result)} == {"restaurant"}
    assert result["days"][0]["stay"]["idea_id"] == "riad"
    assert result["days"][0]["stay"]["status"] == "suggested"
    assert set(result["unplaced_idea_ids"]) == {"hotel"}
    assert not any("Stay options" in warning for warning in result["warnings"])


def test_unknown_city_and_coordinates_never_assume_marrakech_from_other_saves():
    data = payload(idea("known", score=5), idea("unknown", city=None, latitude=None, longitude=None, score=4))
    result = engine.generate_plan(data, use_ai=False)["plan"]
    assert {stop["idea_id"] for stop in place_stops(result)} == {"known"}
    assert result["unplaced_idea_ids"] == ["unknown"]


def test_explicitly_placed_hotel_can_be_retained_when_reworking():
    old = {"days": [{"date": "2026-11-12", "stops": [stop("hotel-check-in", idea_id="hotel", title="Place hotel",
                start_time="15:00", duration_minutes=30, kind="place", locked=False)]}]}
    data = payload(idea("hotel", category="hotel", duration_minutes=30), existing_plan=old)
    result = engine.generate_plan(data, use_ai=False)["plan"]
    assert place_stops(result)[0]["id"] == "hotel-check-in"


def test_ai_request_disables_reasoning_and_records_only_safe_diagnostics(monkeypatch):
    monkeypatch.setenv("PLANNER_AI_API_KEY", "synthetic-secret")
    calls = []
    raw = fake_response()
    raw["choices"][0]["finish_reason"] = "length"
    raw["choices"][0]["message"]["reasoning_content"] = "Private thought data"
    monkeypatch.setattr(httpx, "post", lambda *a, **k: calls.append(k["json"]) or httpx.Response(200, json=raw))
    with pytest.raises(planner_ai.PlannerAIError) as error:
        planner_ai.compose(brief())
    assert calls[0]["reasoning"] == {"enabled": False}
    assert calls[0]["venice_parameters"]["disable_thinking"] is True
    assert error.value.usage["finish_reason"] == "length"
    assert error.value.usage["reasoning_chars"] == len("Private thought data")
    assert "Private thought data" not in json.dumps(error.value.usage)


def test_ai_grouping_spreads_feasible_saves_across_all_four_days(monkeypatch):
    data = payload(*[idea(str(i)) for i in range(8)])
    data["trip"]["end_date"] = "2026-11-15"
    monkeypatch.setattr(planner_ai, "compose", lambda _: ({"days": [
        {"date": "2026-11-12", "idea_ids": [str(i) for i in range(4)]},
        {"date": "2026-11-13", "idea_ids": [str(i) for i in range(4, 8)]},
    ]}, {"cost_usd": 0}))
    plan = engine.generate_plan(data)["plan"]
    assert [sum(bool(s.get("idea_id")) for s in day["stops"]) for day in plan["days"]] == [2, 2, 2, 2]
    assert len({s["idea_id"] for s in place_stops(plan)}) == 8


def test_sparse_saves_explain_empty_days_without_inventing_activities():
    data = payload(idea("only"))
    data["trip"]["end_date"] = "2026-11-15"
    plan = engine.generate_plan(data, use_ai=False)["plan"]
    assert [s["idea_id"] for s in place_stops(plan)] == ["only"]
    assert len(plan["days"]) == 4
    assert all(day["planning_note"] and not day["stops"] for day in plan["days"][1:])
    assert all(day["stay"]["status"] == "needed" for day in plan["days"][:-1])
    assert plan["days"][-1]["stay"]["status"] == "not_needed"


def test_manual_place_clears_only_the_generated_empty_day_note():
    data = payload(idea("a"))
    day = {"date": "2026-11-12", "stops": [], "planning_note": engine.EMPTY_DAY_NOTE}
    assert engine.validate_plan({"days": [day]}, data)["days"][0]["planning_note"] == engine.EMPTY_DAY_NOTE
    day["stops"] = [stop("visit", idea_id="a", kind="place")]
    assert "planning_note" not in engine.validate_plan({"days": [day]}, data)["days"][0]
    day["planning_note"] = "Leave the evening free for friends."
    assert engine.validate_plan({"days": [day]}, data)["days"][0]["planning_note"] == day["planning_note"]


@pytest.mark.parametrize("status", ["selected", "suggested"])
def test_stays_must_reference_accommodation_not_sights_or_food(status):
    data = payload(idea("food", category="restaurant"))
    with pytest.raises(ValueError, match="accommodation save"):
        engine.validate_plan({"days": [{"date": "2026-11-12", "stops": [],
                                       "stay": {"status": status, "idea_id": "food"}}]}, data)


def test_saved_stay_uses_canonical_country_city_and_is_not_unplaced():
    data = payload(idea("sight"), idea("riad", category="hotel", country="MA", city="Marrakesh", longitude=-7.9901))
    plan = engine.generate_plan(data, use_ai=False)["plan"]
    assert plan["days"][0]["stay"]["idea_id"] == "riad"
    assert plan["unplaced_idea_ids"] == []
    assert not any("remain in Ideas" in warning or "Stay options" in warning for warning in plan["warnings"])


def test_far_saved_hotel_is_not_recommended_but_explicit_selection_is_preserved_and_warned():
    data = payload(idea("sight"), idea("rabat", category="hotel", city="Rabat", latitude=34.02, longitude=-6.84))
    plan = engine.generate_plan(data, use_ai=False)["plan"]
    assert plan["days"][0]["stay"]["status"] == "needed"
    data["existing_plan"] = {"days": [{"date": "2026-11-12", "stops": [],
                                      "stay": {"status": "selected", "idea_id": "rabat"}}]}
    plan = engine.generate_plan(data, use_ai=False)["plan"]
    assert plan["days"][0]["stay"]["status"] == "selected"
    assert plan["days"][0]["stay"]["idea_id"] == "rabat"
    assert "away" in plan["days"][0]["stay"]["reason"]
    assert any("transfer" in warning for warning in plan["warnings"])
    assert "rabat" not in plan["unplaced_idea_ids"]


@pytest.mark.parametrize("manual_flags", [{"user_created": True}, {}])
def test_unlocked_custom_and_legacy_text_survive_rework(manual_flags):
    note = stop("slow-morning", title="Slow morning", start_time="09:00", duration_minutes=120,
                kind="break", locked=False, notes="Sleep in with the group", **manual_flags)
    data = payload(idea("sight"), existing_plan={"days": [{"date": "2026-11-12", "stops": [note]}]})
    plan = engine.generate_plan(data, use_ai=False)["plan"]
    assert next(s for s in plan["days"][0]["stops"] if s["id"] == note["id"]) == note
    assert all(engine.minutes(s["start_time"]) >= 660 for s in place_stops(plan) if s in plan["days"][0]["stops"])


def test_meals_are_timed_as_meals_not_morning_sightseeing():
    data = payload(idea("lunch", category="restaurant"), idea("dinner", category="food"),
                   idea("extra-meal", category="restaurant"), idea("coffee", title="Atlas Coffee", category="food"))
    data["trip"]["end_date"] = "2026-11-12"
    plan = engine.generate_plan(data, use_ai=False)["plan"]
    meals = [s for s in place_stops(plan) if s["idea_id"] != "coffee"]
    assert len(meals) == 2
    assert all(690 <= engine.minutes(s["start_time"]) <= 900 or
               1050 <= engine.minutes(s["start_time"]) <= 1260 for s in meals)


def test_multimode_estimates_walk_nearby_and_drive_farther_without_provider_calls(monkeypatch):
    data = payload(idea("a"), idea("b", longitude=-7.995), idea("c", longitude=-7.94))
    data["trip"]["transport_modes"] = ["walk", "drive"]
    old = {"days": [{"date": "2026-11-12", "stops": [
        stop("first", idea_id="a", kind="place", start_time="09:00"),
        stop("rest", kind="break", start_time="10:00", duration_minutes=30, locked=False),
        stop("second", idea_id="b", kind="place", start_time="11:00"),
        stop("third", idea_id="c", kind="place", start_time="13:00"),
    ]}]}
    monkeypatch.setattr(engine, "collect_facts", lambda *a, **k: pytest.fail("Paid fact collection on edit"))
    refreshed = engine.refresh_plan_travel(old, data)
    first, rest, second, third = refreshed["days"][0]["stops"]
    assert "travel_minutes" not in first and "travel_minutes" not in rest
    assert second["travel_from_stop_id"] == "first" and second["travel_mode"] == "walk"
    assert third["travel_from_stop_id"] == "second" and third["travel_mode"] == "drive"
    assert second["travel_source"] == third["travel_source"] == "estimate"
    assert second["travel_minutes"] > 0 and third["travel_minutes"] > 0
    assert "travel_minutes" not in old["days"][0]["stops"][2]


def test_unknown_booking_resets_leg_and_night_location_but_break_does_not():
    data = payload(idea("a"), idea("hotel", category="hotel"), idea("b", longitude=-7.995))
    old = {"days": [{"date": "2026-11-12", "stops": [
        stop("first", idea_id="a", start_time="09:00"),
        stop("flight", title="Flight", start_time="14:00"),
    ]}, {"date": "2026-11-13", "stops": []}]}
    fact_set = facts.FactSet({i["id"]: i for i in data["ideas"]}, "walk")
    with_stays = engine._suggest_stays(old, data, fact_set)
    assert with_stays["days"][0]["stay"]["status"] == "needed"
    old["days"][0]["stops"].append(stop("arrival", idea_id="b", start_time="16:00"))
    refreshed = engine.refresh_plan_travel(old, data)
    assert all("travel_minutes" not in s and "travel_from_stop_id" not in s for s in refreshed["days"][0]["stops"])


def test_known_unavailable_route_cannot_reappear_as_optimistic_estimate_on_read():
    data = payload(idea("a"), idea("b", longitude=-7.995))
    old = {"days": [{"date": "2026-11-12", "stops": [
        stop("first", idea_id="a", start_time="09:00"),
        stop("second", idea_id="b", start_time="11:00"),
    ]}]}
    fact_set = facts.FactSet({i["id"]: i for i in data["ideas"]}, "walk")
    fact_set.blocked_routes.add(("a", "b"))
    generated = engine._refresh_travel(old, fact_set)
    for plan in (generated, engine.refresh_plan_travel(generated, data)):
        second = plan["days"][0]["stops"][1]
        assert second["travel_blocked"] is True
        assert second["travel_source"] == "unknown"
        assert "travel_minutes" not in second


@pytest.mark.parametrize("modes", [["transit"], ["walk", "transit"]])
def test_unknown_transit_duration_is_not_fabricated(modes):
    data = payload(idea("a"), idea("b", longitude=-7.80))
    data["trip"].update(transport=modes[0], transport_modes=modes)
    old = {"days": [{"date": "2026-11-12", "stops": [
        stop("first", idea_id="a", start_time="09:00"),
        stop("second", idea_id="b", start_time="14:00"),
    ]}]}
    second = engine.refresh_plan_travel(old, data)["days"][0]["stops"][1]
    assert second["travel_mode"] == "transit"
    assert second["travel_source"] == "unknown"
    assert "travel_minutes" not in second


@pytest.mark.parametrize("use_ai", [False, True])
@pytest.mark.parametrize("obstacle", ["duplicate", "closed", "distant", "first_two_days"])
def test_seven_day_coverage_uses_viable_extras_without_inflating_quotas(monkeypatch, obstacle, use_ai):
    data = payload()
    data["trip"]["end_date"] = "2026-11-18"
    dates = engine.trip_dates(data["trip"])
    extras = [idea("extra" + str(i)) for i in range(10)]
    if obstacle == "duplicate":
        shortlist = [idea("alias" + str(i), google_place_id="same_venue") for i in range(7)]
    elif obstacle == "closed":
        shortlist = [idea("chosen")] + [idea("closed" + str(i), opening_windows={day: [] for day in dates}) for i in range(6)]
    elif obstacle == "distant":
        shortlist = [idea("chosen", score=20)] + [idea("coast" + str(i), city="Taghazout", latitude=30.54, longitude=-9.71) for i in range(6)]
    else:
        shortlist = [idea("restricted" + str(i), opening_windows={day: [[540, 1200]] if j < 2 else []
                                                                  for j, day in enumerate(dates)}) for i in range(7)]
    data["ideas"] = shortlist + extras
    monkeypatch.setattr(planner_ai, "compose", lambda _: ({"days": [
        {"date": dates[0], "idea_ids": [i["id"] for i in shortlist]},
    ]}, {"cost_usd": 0}))
    plan = engine.generate_plan(data, use_ai=use_ai)["plan"]
    assert all(any(s.get("idea_id") for s in day["stops"]) for day in plan["days"])
    ids = [s["idea_id"] for s in place_stops(plan)]
    assert set(i["id"] for i in extras).issubset(ids)
    if obstacle == "duplicate":
        assert sum(identifier.startswith("alias") for identifier in ids) == 1
    elif obstacle in {"closed", "distant"}:
        assert not any(identifier.startswith(("closed", "coast")) for identifier in ids)
    else:
        assert sum(identifier.startswith("restricted") for identifier in ids) == 7
        assert all(not any(s.get("idea_id", "").startswith("restricted") for s in day["stops"])
                   for day in plan["days"][2:])


@pytest.mark.parametrize("restricted_count", [1, 2])
@pytest.mark.parametrize("flexible_must_do", [False, True])
def test_coverage_reservation_and_scarce_dates_override_overfull_early_ai_days(monkeypatch, restricted_count, flexible_must_do):
    data = payload()
    data["trip"]["end_date"] = "2026-11-18"
    dates = engine.trip_dates(data["trip"])
    flexible = [idea("flex" + str(i), must_do=flexible_must_do) for i in range(7 - restricted_count)]
    restricted = [idea("restricted" + str(i), opening_windows={day: [[540, 1200]] if j < 2 else []
                                                               for j, day in enumerate(dates)}) for i in range(restricted_count)]
    data["ideas"] = flexible + restricted
    monkeypatch.setattr(planner_ai, "compose", lambda _: ({"days": [
        {"date": dates[0], "idea_ids": [i["id"] for i in flexible]},
    ]}, {"cost_usd": 0}))
    plan = engine.generate_plan(data)["plan"]
    assert [sum(bool(s.get("idea_id")) for s in day["stops"]) for day in plan["days"]] == [1] * 7
    assert all(any(s.get("idea_id") == i["id"] for day in plan["days"][:2] for s in day["stops"]) for i in restricted)


@pytest.mark.parametrize("use_ai", [False, True])
def test_seven_days_with_eight_activities_and_fourteen_hotels_keep_every_day_useful(monkeypatch, use_ai):
    activities = [idea("activity" + str(i), category="restaurant" if i < 4 else "cafe" if i < 6 else "sight",
                       latitude=None, longitude=None) for i in range(8)]
    hotels = [idea("hotel" + str(i), category="hotel", latitude=None, longitude=None) for i in range(14)]
    data = payload(*(activities + hotels), existing_plan=None)
    data["trip"]["end_date"] = "2026-11-18"
    monkeypatch.setattr(planner_ai, "compose", lambda _: ({"days": [
        {"date": "2026-11-12", "idea_ids": [i["id"] for i in activities[:5]]},
    ]}, {"cost_usd": 0}))
    plan = engine.generate_plan(data, use_ai=use_ai)["plan"]
    assert [sum(bool(s.get("idea_id")) for s in day["stops"]) for day in plan["days"]] == [2, 1, 1, 1, 1, 1, 1]
    assert {s["idea_id"] for s in place_stops(plan)} == {i["id"] for i in activities}
    assert all(day["stay"]["status"] == "needed" for day in plan["days"][:-1])


def test_coverage_preflight_is_bounded_and_never_spends_route_requests(monkeypatch):
    data = payload(*[idea(str(i)) for i in range(200)])
    data["trip"]["end_date"] = "2026-12-12"
    fact_set = facts.FactSet({i["id"]: i for i in data["ideas"]}, "walk", route_key="synthetic", route_limit=12)
    monkeypatch.setattr(engine, "collect_facts", lambda *a, **k: fact_set)
    calls, preflights = [], []
    monkeypatch.setattr(httpx, "post", lambda *a, **k: calls.append(1) or httpx.Response(200, json={"routes": [{"duration": "60s"}]}))
    original = engine._slot
    def counted_slot(*args, **kwargs):
        before = len(calls)
        result = original(*args, **kwargs)
        if not kwargs.get("live_routes", True):
            assert len(calls) == before
            preflights.append(1)
        return result
    monkeypatch.setattr(engine, "_slot", counted_slot)
    plan = engine.generate_plan(data, use_ai=False)["plan"]
    assert len(preflights) <= 200 * 31
    assert len(calls) <= 12
    assert len(plan["days"]) == 31


@pytest.mark.parametrize("route_exists", [False, True])
def test_unknown_but_queryable_transfer_reaches_bounded_verification_before_placement(monkeypatch, route_exists):
    data = payload(idea("a", latitude=None, longitude=None, google_place_id="ChIJ_a"),
                   idea("b", city="Rabat", latitude=None, longitude=None, google_place_id="ChIJ_b"),
                   existing_plan={"days": [{"date": "2026-11-13", "stops": [
                       stop("reserved", idea_id="b", title="Place b", start_time="10:00"),
                   ]}]})
    data["trip"]["transport"] = "drive"
    fact_set = facts.FactSet({i["id"]: i for i in data["ideas"]}, "drive", route_key="synthetic", route_limit=1)
    monkeypatch.setattr(engine, "collect_facts", lambda *a, **k: fact_set)
    calls = []
    monkeypatch.setattr(httpx, "post", lambda *a, **k: calls.append(1) or httpx.Response(200, json={
        "routes": [{"duration": "7200s"}] if route_exists else [],
    }))
    plan = engine.generate_plan(data, use_ai=False)["plan"]
    assert len(calls) == 1
    assert any(s.get("idea_id") == "a" for s in plan["days"][0]["stops"]) is route_exists
    assert plan["days"][1]["stops"][0]["id"] == "reserved"


@pytest.mark.parametrize("use_ai", [False, True])
@pytest.mark.parametrize("unusable_kind", ["far_same_city", "rejected_route"])
def test_late_anchor_or_route_rejection_cannot_spend_the_final_days_activity(monkeypatch, use_ai, unusable_kind):
    data = payload()
    data["trip"]["end_date"] = "2026-11-18"
    dates = engine.trip_dates(data["trip"])
    early = [idea("early" + str(i), opening_windows={day: [[540, 1200]] if j == i else []
                                                   for j, day in enumerate(dates)}) for i in range(5)]
    # The previous physical stop shares a city label but has no usable pin.
    early[-1].update(latitude=None, longitude=None)
    late_hours = {day: [[540, 1200]] if i >= 5 else [] for i, day in enumerate(dates)}
    first = idea("late-first", score=10, opening_windows=late_hours, google_place_id="ChIJ_first")
    last = idea("late-last", score=1, opening_windows=late_hours)
    unusable = idea("unusable", score=9, opening_windows=late_hours, latitude=31.2, longitude=-8.3)
    if unusable_kind == "rejected_route":
        unusable.update(latitude=None, longitude=None, google_place_id="ChIJ_unusable")
    data["ideas"] = early + [first, last, unusable]
    fact_set = facts.FactSet({i["id"]: i for i in data["ideas"]}, "walk", route_key="synthetic", route_limit=1)
    monkeypatch.setattr(engine, "collect_facts", lambda *a, **k: fact_set)
    calls = []
    monkeypatch.setattr(httpx, "post", lambda *a, **k: calls.append(k["json"]) or httpx.Response(200, json={"routes": []}))
    monkeypatch.setattr(planner_ai, "compose", lambda _: ({"days": [
        {"date": dates[5], "idea_ids": ["late-first", "unusable", "late-last"]},
    ]}, {"cost_usd": 0}))
    plan = engine.generate_plan(data, use_ai=use_ai)["plan"]
    assert [sum(bool(s.get("idea_id")) for s in day["stops"]) for day in plan["days"]] == [1] * 7
    assert [s["idea_id"] for s in place_stops(plan)] == [i["id"] for i in early] + ["late-first", "late-last"]
    assert "unusable" in plan["unplaced_idea_ids"]
    assert len(calls) == (1 if unusable_kind == "rejected_route" else 0)


@pytest.mark.parametrize("unknown_indices", [[0], [0, 4]])
@pytest.mark.parametrize("prefer_outlier", [False, True])
def test_unknown_first_pin_cannot_bridge_into_an_isolated_walking_base(monkeypatch, unknown_indices, prefer_outlier):
    locals_ = [idea("local" + str(i)) for i in range(7)]
    for index in unknown_indices:
        locals_[index].update(latitude=None, longitude=None)
    outlier = idea("outlier", latitude=31.45, longitude=-8.3)
    data = payload(*(locals_ + [outlier]))
    data["trip"]["end_date"] = "2026-11-18"
    dates = engine.trip_dates(data["trip"])
    proposal = {"days": [{"date": day, "idea_ids": ["local" + str(i)]} for i, day in enumerate(dates)]}
    if prefer_outlier:
        proposal["days"][1]["idea_ids"].insert(0, "outlier")
    monkeypatch.setattr(planner_ai, "compose", lambda _: (proposal, {"cost_usd": 0}))
    plan = engine.generate_plan(data)["plan"]
    assert [sum(bool(s.get("idea_id")) for s in day["stops"]) for day in plan["days"]] == [1] * 7
    assert {s["idea_id"] for s in place_stops(plan)} == {i["id"] for i in locals_}
    assert "outlier" in plan["unplaced_idea_ids"]
    assert all(data["ideas"][index]["latitude"] is None for index in unknown_indices)


def test_exclusion_reason_uses_observed_walking_limit_and_excludes_stay_options():
    data = payload(idea("local", score=20), idea("desert", latitude=31.2, longitude=-8.3),
                   *[idea("hotel" + str(i), category="hotel", latitude=None, longitude=None) for i in range(14)])
    plan = engine.generate_plan(data, use_ai=False)["plan"]
    assert plan["unplaced_reasons"]["desert"] == {"code": "transport_required", "transport_mode": "walk"}
    assert not any(key.startswith("hotel") for key in plan["unplaced_reasons"])
    assert not any("remain in Ideas" in warning for warning in plan["warnings"])
    assert engine.plan_for_storage(plan)["unplaced_reasons"] == plan["unplaced_reasons"]


def test_exclusion_reasons_reflect_location_hours_votes_and_confirmed_duplicate():
    dates = ["2026-11-12", "2026-11-13"]
    data = payload(idea("chosen", score=20, google_place_id="same"), idea("alias", google_place_id="same"),
                   idea("missing", city=None, latitude=None, longitude=None),
                   idea("processing", status="processing"), idea("closed", closed=True),
                   idea("hours", opening_windows={day: [] for day in dates}), idea("downvoted", score=-1))
    reasons = engine.generate_plan(data, use_ai=False)["plan"]["unplaced_reasons"]
    assert {key: value["code"] for key, value in reasons.items()} == {
        "alias": "duplicate", "missing": "needs_location", "processing": "processing",
        "closed": "closed", "hours": "opening_hours", "downvoted": "low_interest",
    }


def test_unknown_exclusion_does_not_invent_closure_or_transport_evidence(monkeypatch):
    data = payload(idea("local", score=20), idea("long", duration_minutes=720, latitude=None, longitude=None))
    data["trip"]["end_date"] = data["trip"]["start_date"]
    plan = engine.generate_plan(data, use_ai=False)["plan"]
    assert plan["unplaced_reasons"]["long"] == {"code": "no_fit"}
    provider = facts.FactSet({"local": data["ideas"][0], "long": {**data["ideas"][1], "closed": True}}, "walk")
    monkeypatch.setattr(engine, "collect_facts", lambda *a, **k: provider)
    assert engine.generate_plan(data, use_ai=False)["plan"]["unplaced_reasons"]["long"] == {"code": "no_fit"}


def test_reason_validation_allowlists_ids_codes_and_fields_and_prunes_obsolete_reasons():
    data = payload(idea("a"), idea("b"), idea("hotel", category="hotel"), idea("c"))
    plan = {"days": [{"date": "2026-11-12", "stops": [stop("a-stop", idea_id="a")]}],
            "warnings": ["14 ideas remain in Ideas; they were not forced into the itinerary."],
            "unplaced_reasons": {"foreign-trip": {"code": "closed"}, "hotel": {"code": "no_fit"},
                                  "a": {"code": "no_fit"}, "b": {"code": "transport_required", "transport_mode": "walk", "message": "untrusted text"},
                                  "c": {"code": "invented_reason"}}}
    clean = engine.validate_plan(plan, data)
    assert clean["unplaced_reasons"] == {"b": {"code": "transport_required", "transport_mode": "walk"}}
    assert clean["warnings"] == []
    data["trip"]["transport_modes"] = ["walk", "drive"]
    assert engine.validate_plan(clean, data)["unplaced_reasons"] == {}
    del plan["unplaced_reasons"]
    assert "unplaced_reasons" not in engine.validate_plan(plan, data)


def test_place_details_edits_clear_stale_missing_location_reason():
    data = payload(idea("known"))
    plan = {"days": [], "unplaced_reasons": {"known": {"code": "needs_location"}}}
    assert engine.validate_plan(plan, data)["unplaced_reasons"] == {}


def test_marking_a_downvoted_idea_must_do_clears_the_obsolete_vote_explanation():
    data = payload(idea("required", score=-2, must_do=True))
    plan = {"days": [], "unplaced_reasons": {"required": {"code": "low_interest"}}}
    assert engine.validate_plan(plan, data)["unplaced_reasons"] == {}


@pytest.mark.parametrize("reason", [{"code": []}, {"code": "transport_required", "transport_mode": []}, None, "untrusted"])
def test_malformed_reason_metadata_is_discarded_without_breaking_editable_plan(reason):
    data = payload(idea("a"))
    assert engine.validate_plan({"days": [], "unplaced_reasons": {"a": reason}}, data)["unplaced_reasons"] == {}
