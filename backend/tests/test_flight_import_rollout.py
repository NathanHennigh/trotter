"""Explicit cohorts constrain every staged authority without erasing records."""
from types import SimpleNamespace

import pytest

from app.services.flight_import_rollout import ALLOWLIST_ENV, FEATURE_FLAGS, enabled
from app.services import booking_enrichment as strict, carrier_travel_recovery as carrier
from app.services import booking_leg_lineage as lineage


@pytest.fixture(autouse=True)
def clean_rollout_environment(monkeypatch):
    for key in [ALLOWLIST_ENV, *FEATURE_FLAGS]:
        monkeypatch.delenv(key, raising=False)


@pytest.mark.parametrize("flag", sorted(FEATURE_FLAGS))
def test_master_switch_without_explicit_cohort_is_off(monkeypatch, flag):
    assert not enabled(flag, 12)
    monkeypatch.setenv(flag, "true")
    assert not enabled(flag, 12)
    monkeypatch.setenv(ALLOWLIST_ENV, "12,34")
    assert enabled(flag, 12) and enabled(flag, 34)
    assert not enabled(flag, 13)
    monkeypatch.setenv(flag, "false")
    assert not enabled(flag, 12)


@pytest.mark.parametrize("value", ["", " ", "0", "-1", "01", "+1", "1.0", "1,", ",1", "1,,2",
    "1;2", "1 two", "1,invalid", "1,*", "*,1", "**", "all", "ALL", "1,9223372036854775808"])
def test_malformed_cohort_fails_closed_for_every_account(monkeypatch, value):
    monkeypatch.setenv(ALLOWLIST_ENV, value)
    for flag in FEATURE_FLAGS:
        monkeypatch.setenv(flag, "true")
        assert not enabled(flag, 1) and not enabled(flag, 2)


@pytest.mark.parametrize("value", [None, 0, -1, True, False, "1", 1.0, 2**63])
def test_missing_or_invalid_caller_identity_is_never_opted_in(monkeypatch, value):
    monkeypatch.setenv(ALLOWLIST_ENV, "*")
    for flag in FEATURE_FLAGS:
        monkeypatch.setenv(flag, "true")
        assert not enabled(flag, value)


@pytest.mark.parametrize("switch", ["yes", "on", "enabled", "2", "", "TRUE,false"])
def test_invalid_master_switch_stays_off_with_valid_cohort(monkeypatch, switch):
    monkeypatch.setenv(ALLOWLIST_ENV, "*")
    for flag in FEATURE_FLAGS:
        monkeypatch.setenv(flag, switch)
        assert not enabled(flag, 1)


def test_each_master_switch_remains_independent_and_star_is_explicit(monkeypatch):
    monkeypatch.setenv(ALLOWLIST_ENV, "  *  ")
    only = "BOOKING_LEG_RECONCILIATION_ENABLED"
    monkeypatch.setenv(only, " TRUE ")
    for flag in FEATURE_FLAGS:
        assert enabled(flag, 923) == (flag == only)
    assert not enabled("UNKNOWN_FEATURE_ENABLED", 923)


def test_cohort_add_remove_and_readd_take_effect_without_cached_authority(monkeypatch):
    flag = "BOOKING_STRICT_ENRICHMENT_ENABLED"
    monkeypatch.setenv(flag, "1")
    monkeypatch.setenv(ALLOWLIST_ENV, "12, 34,12")
    assert enabled(flag, 12) and enabled(flag, 34)
    monkeypatch.setenv(ALLOWLIST_ENV, "34")
    assert not enabled(flag, 12) and enabled(flag, 34)
    monkeypatch.setenv(ALLOWLIST_ENV, "12,34")
    assert enabled(flag, 12)
    monkeypatch.delenv(ALLOWLIST_ENV)
    assert not enabled(flag, 12)


class NoDatabaseAccess:
    def __getattr__(self, name):
        raise AssertionError("Unlisted recovery must not access database: " + name)


@pytest.mark.parametrize("allowlist", [None, "", "bad", "34"])
def test_unlisted_accounts_cannot_enter_recovery_service_paths(monkeypatch, allowlist):
    for flag in FEATURE_FLAGS:
        monkeypatch.setenv(flag, "true")
    if allowlist is not None:
        monkeypatch.setenv(ALLOWLIST_ENV, allowlist)
    db = NoDatabaseAccess()
    assert strict.evaluate(db, 12, object()).reason == "feature_not_enabled_for_account"
    assert carrier.evaluate(db, 12, object()).reason == "feature_not_enabled_for_account"
    assert carrier.record_payload(db, 12, {}) == []
    assert carrier.reconcile(db, 12, [object()]).inserted == 0
    assert carrier.existing_projection_trip(db, 12, [object()]) is None
    value = SimpleNamespace(source_leg={"version": 1, "key": "a" * 64}, time_provenance={})
    assert lineage.find(db, 12, value).status == "none"
