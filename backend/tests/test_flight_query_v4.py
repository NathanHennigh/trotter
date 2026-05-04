from datetime import datetime, timezone
from types import SimpleNamespace

from app.services.flight_query_v4 import (
    build_discovery_plan,
    mark_discovery_plan_success,
)
from app.services.parser import PARSER_VERSION


def test_first_run_uses_all_history_precise_and_backfill():
    state = SimpleNamespace(
        last_incremental_scan_at=None,
        backfill_cursor_before=None,
        backfill_complete=False,
        parser_version=PARSER_VERSION,
        updated_at=None,
    )

    plan = build_discovery_plan(
        state,
        now=datetime(2026, 4, 24, tzinfo=timezone.utc),
        max_backfill_windows=1,
    )

    tiers = [item.tier for item in plan]
    assert "incremental_precise" in tiers
    assert "initial_broad_recent" in tiers
    assert tiers[-1] == "exhaustive_backfill"
    assert all(item.prefilter for item in plan if item.tier != "exhaustive_backfill")
    assert not plan[-1].prefilter
    assert any("after:2003/12/31" in item.query for item in plan if item.tier == "incremental_precise")


def test_later_run_queries_new_mail_and_continues_backfill_with_overlap():
    state = SimpleNamespace(
        last_incremental_scan_at=datetime(2026, 4, 20, 15, tzinfo=timezone.utc),
        backfill_cursor_before=datetime(2025, 1, 1, tzinfo=timezone.utc),
        backfill_complete=False,
        parser_version=PARSER_VERSION,
        updated_at=None,
    )

    plan = build_discovery_plan(
        state,
        now=datetime(2026, 4, 24, tzinfo=timezone.utc),
        max_backfill_windows=1,
    )

    assert any("after:2026/4/17" in item.query for item in plan if item.tier == "incremental_precise")
    assert not [item for item in plan if item.tier == "initial_broad_recent"]
    assert [item for item in plan if item.tier == "exhaustive_backfill"]


def test_parser_upgrade_adds_one_time_recent_repair_scan():
    state = SimpleNamespace(
        last_incremental_scan_at=datetime(2026, 4, 20, 15, tzinfo=timezone.utc),
        backfill_cursor_before=datetime(2025, 1, 1, tzinfo=timezone.utc),
        backfill_complete=True,
        parser_version=PARSER_VERSION - 1,
        updated_at=None,
    )

    now = datetime(2026, 4, 24, tzinfo=timezone.utc)
    plan = build_discovery_plan(state, now=now, max_backfill_windows=1)

    repair = [item for item in plan if item.tier == "parser_upgrade_recent_repair"]
    assert repair
    assert any("after:2024/10/22" in item.query for item in repair)

    mark_discovery_plan_success(state, plan, scan_started_at=now)
    assert state.parser_version == PARSER_VERSION


def test_later_run_includes_learned_sender_domains():
    state = SimpleNamespace(
        last_incremental_scan_at=datetime(2026, 4, 20, 15, tzinfo=timezone.utc),
        backfill_cursor_before=None,
        backfill_complete=True,
        parser_version=PARSER_VERSION,
        updated_at=None,
    )

    plan = build_discovery_plan(
        state,
        now=datetime(2026, 4, 24, tzinfo=timezone.utc),
        learned_sender_domains=["new-agency.example", "airline.example"],
        max_backfill_windows=1,
    )

    learned = [item for item in plan if item.tier == "incremental_learned_senders"]
    assert len(learned) == 1
    assert "after:2026/4/17" in learned[0].query
    assert "from:airline.example" in learned[0].query
    assert "from:new-agency.example" in learned[0].query


def test_success_updates_incremental_and_advances_backfill_cursor():
    state = SimpleNamespace(
        last_incremental_scan_at=None,
        backfill_cursor_before=None,
        backfill_complete=False,
        parser_version=PARSER_VERSION,
        updated_at=None,
    )
    now = datetime(2026, 4, 24, tzinfo=timezone.utc)
    plan = build_discovery_plan(state, now=now, max_backfill_windows=1)

    mark_discovery_plan_success(state, plan, scan_started_at=now)

    assert state.last_incremental_scan_at == now
    assert state.backfill_cursor_before == datetime(2026, 3, 24, tzinfo=timezone.utc)
    assert state.backfill_complete is False
