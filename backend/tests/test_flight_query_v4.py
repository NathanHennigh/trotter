from datetime import datetime, timezone
from types import SimpleNamespace

from app.services import flight_query_v4
from app.services.flight_query_v4 import (
    build_fast_known_sender_queries,
    build_fast_strong_keyword_queries,
    build_discovery_plan,
    load_fast_known_sender_domains,
    mark_discovery_plan_success,
)
from app.services.flight_query_v3 import build_gmail_queries as build_precise_queries
from app.services.parser import PARSER_VERSION


def test_first_run_defaults_to_fast_user_visible_tiers():
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
    assert tiers[0] == "fast_known_senders"
    assert tiers.index("fast_known_senders") < tiers.index("fast_strong_keywords")
    assert "fast_known_senders" in tiers
    assert "fast_strong_keywords" in tiers
    assert "incremental_precise" not in tiers
    assert "initial_broad_recent" not in tiers
    assert "exhaustive_backfill" not in tiers
    assert not any("category:travel" in item.query for item in plan if item.tier.startswith("fast_"))
    assert all("-category:promotions" in item.query for item in plan if item.tier.startswith("fast_"))


def test_recall_discovery_tiers_are_available_when_enabled(monkeypatch):
    monkeypatch.setattr(flight_query_v4, "ENABLE_RECALL_DISCOVERY_TIERS", True)
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
    assert tiers.index("fast_strong_keywords") < tiers.index("incremental_precise")
    assert "initial_broad_recent" in tiers
    assert any("after:2003/12/31" in item.query for item in plan if item.tier == "incremental_precise")
    assert any("after:2024/10/22" in item.query for item in plan if item.tier == "initial_broad_recent")


def test_incremental_precise_demotes_noisy_low_value_keywords():
    combined = " ".join(build_precise_queries(since="2026/1/1"))

    assert '"boarding pass"' in combined
    assert '"your trip"' in combined
    assert '"itinerary"' in combined
    assert '"order confirmation"' not in combined
    assert '"purchase confirmation"' not in combined
    assert '"trip itinerary"' not in combined


def test_later_run_queries_new_mail_without_automatic_backfill():
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

    assert any("after:2026/4/17" in item.query for item in plan if item.tier == "fast_known_senders")
    assert not [item for item in plan if item.tier == "incremental_precise"]
    assert not [item for item in plan if item.tier == "initial_broad_recent"]
    assert not [item for item in plan if item.tier == "exhaustive_backfill"]
    assert not any(item.query.strip() == "" for item in plan)


def test_parser_upgrade_does_not_add_broad_gmail_repair_scan():
    state = SimpleNamespace(
        last_incremental_scan_at=datetime(2026, 4, 20, 15, tzinfo=timezone.utc),
        backfill_cursor_before=datetime(2025, 1, 1, tzinfo=timezone.utc),
        backfill_complete=True,
        parser_version=PARSER_VERSION - 1,
        updated_at=None,
    )

    now = datetime(2026, 4, 24, tzinfo=timezone.utc)
    plan = build_discovery_plan(state, now=now, max_backfill_windows=1)

    assert not [item for item in plan if item.tier == "parser_upgrade_recent_repair"]

    mark_discovery_plan_success(state, plan, scan_started_at=now)
    assert state.parser_version == PARSER_VERSION - 1


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

    fast = [item for item in plan if item.tier == "fast_known_senders"]
    assert fast
    combined = " ".join(item.query for item in fast)
    assert "after:2026/4/17" in combined
    assert "from:airline.example" in combined
    assert "from:new-agency.example" in combined


def test_success_updates_incremental_and_marks_automatic_backfill_complete():
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
    assert state.backfill_cursor_before == now
    assert state.backfill_complete is True


def test_explicit_backfill_flag_can_build_recovery_window(monkeypatch):
    monkeypatch.setattr(flight_query_v4, "ENABLE_AUTOMATIC_BACKFILL", True)
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

    backfill = [item for item in plan if item.tier == "exhaustive_backfill"]
    assert len(backfill) == 1
    assert backfill[0].prefilter is False
    assert backfill[0].window_end == datetime(2026, 4, 24, tzinfo=timezone.utc)


def test_noisy_domains_are_not_in_fast_known_senders():
    combined = " ".join(build_fast_known_sender_queries(since="2026/1/1"))

    assert "from:aa.com" in combined
    assert "from:e.delta.com" in combined
    assert "from:emirates.email" in combined
    assert "from:ifly.southwest.com" in combined
    assert "from:iluv.southwest.com" in combined
    assert "from:marriott.com" not in combined
    assert "from:email-marriott.com" not in combined
    assert "from:uber.com" not in combined
    assert "from:wellsfargo.com" not in combined
    assert "from:capitalone.com" not in combined
    assert "from:citicards.com" not in combined
    assert "from:airbnb.com" not in combined
    assert "from:membership.prioritypass.com" not in combined
    assert "-category:promotions" in combined


def test_fast_known_senders_include_exact_subdomains_and_roots(tmp_path):
    csv_path = tmp_path / "domains.csv"
    csv_path.write_text("domain\nt.delta.com\nemail.example.co.uk\n", encoding="utf-8")

    domains = load_fast_known_sender_domains(csv_path)
    assert "t.delta.com" in domains
    assert "email.example.co.uk" in domains

    plan = build_discovery_plan(
        SimpleNamespace(
            last_incremental_scan_at=None,
            backfill_cursor_before=None,
            backfill_complete=True,
            parser_version=PARSER_VERSION,
            updated_at=None,
        ),
        now=datetime(2026, 4, 24, tzinfo=timezone.utc),
        learned_sender_domains=["alerts.foo-air.example", "email.example.co.uk"],
    )
    combined = " ".join(item.query for item in plan if item.tier == "fast_known_senders")

    assert "from:t.delta.com" in combined
    assert "from:delta.com" in combined
    assert "from:alerts.foo-air.example" in combined
    assert "from:foo-air.example" in combined
    assert "from:email.example.co.uk" in combined
    assert "from:example.co.uk" in combined


def test_root_from_terms_act_as_wildcard_subdomain_queries():
    plan = build_discovery_plan(
        SimpleNamespace(
            last_incremental_scan_at=None,
            backfill_cursor_before=None,
            backfill_complete=True,
            parser_version=PARSER_VERSION,
            updated_at=None,
        ),
        now=datetime(2026, 4, 24, tzinfo=timezone.utc),
        learned_sender_domains=["receipts.t.delta.com"],
    )
    combined = " ".join(item.query for item in plan if item.tier == "fast_known_senders")

    assert "from:receipts.t.delta.com" in combined
    assert "from:delta.com" in combined
    assert "from:*.delta.com" not in combined


def test_country_suffix_domains_do_not_expand_to_public_suffixes():
    plan = build_discovery_plan(
        SimpleNamespace(
            last_incremental_scan_at=None,
            backfill_cursor_before=None,
            backfill_complete=True,
            parser_version=PARSER_VERSION,
            updated_at=None,
        ),
        now=datetime(2026, 4, 24, tzinfo=timezone.utc),
        learned_sender_domains=["booking.airasia.co.id", "alerts.tiara.co.kr"],
    )
    combined = " ".join(item.query for item in plan if item.tier == "fast_known_senders")

    assert "from:airasia.co.id" in combined
    assert "from:tiara.co.kr" in combined
    assert "from:co.id" not in combined
    assert "from:co.kr" not in combined


def test_load_fast_known_sender_domains_from_csv(tmp_path):
    csv_path = tmp_path / "domains.csv"
    csv_path.write_text("domain\nnew-airline.example\nEmail.ExampleAir.com\n", encoding="utf-8")

    domains = load_fast_known_sender_domains(csv_path)

    assert "aa.com" in domains
    assert "new-airline.example" in domains
    assert "email.exampleair.com" in domains


def test_fast_strong_keywords_cover_forwarded_confirmation_and_online_checkin_shapes():
    combined = " ".join(build_fast_strong_keyword_queries(since="2026/1/1"))

    assert '"confirmation #"' in combined
    assert '"confirmation code"' in combined
    assert '"check in online for your flight"' in combined
    assert '"check-in online for your flight"' in combined
