"""The replay gate must inspect captured rows, not trust a success banner."""
from copy import deepcopy
import importlib.util
from pathlib import Path

import pytest


SPEC = importlib.util.spec_from_file_location("compare_booking_backtests", Path(__file__).parents[1] / "scripts" / "compare_booking_backtests.py")
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


def tables():
    result = {key: [] for key in audit.REQUIRED_TABLES}
    result.update(
        users=[{"id": 1, "name": "Alex Avery", "travel_name_aliases": [], "email": "alex@example.test"}],
        messages=[{"id": 1, "user_id": 1, "provider_msg_id": "message-one", "status": "accepted", "ignored": False}],
        trips=[{"id": 1, "user_id": 1, "title": "Washington", "visibility": "private"}],
        segments=[{"id": 1, "trip_id": 1, "dep_airport": "IAH", "arr_airport": "DCA",
                   "dep_time": "2025-02-21T12:00:00Z", "arr_time": "2025-02-21T15:00:00Z",
                   "flight_number": "UA123", "pnr": "TEST01", "airline": "UA",
                   "meta_json": {"ownership": "self", "passenger_names": ["Alex Avery"]}}],
        booking_observations=[{"id": 1, "user_id": 1, "evidence_key": "original-one",
                               "ownership": "self", "facts": {"passenger_names": ["Alex Avery"]}}],
    )
    return result


def bundle(strict=False):
    state = tables()
    files = {"app/services/parser.py": "parser28"}
    if strict:
        files["app/services/booking_enrichment.py"] = "candidate"
    source = {"files": files, "sha256": "strict" if strict else "baseline"}
    report = {
        "offline_only": True, "normal_gate": True, "force_parse": False, "network_attempts": [],
        "restore_verified": True, "candidate_source_unchanged": True,
        "candidate_source_start": source, "candidate_source_end": deepcopy(source),
        "source_count": 1, "snapshot_message_count": 1, "unavailable_sources": [],
        "all_sources_accounted_for": True, "snapshot_sha256": "same-snapshot",
        "sources_sha256": "same-sources", "attachment_manifest_sha256": None,
        "runs": [{"fetches": 1, "results": [{"state": "completed", "scanned_count": 1}], "seconds": 1.0}] * 2,
        "strict_enrichment": {"requested": strict, "effective": strict, "module_present": strict,
                              "evaluations": 1 if strict else 0, "allowed": 1 if strict else 0,
                              "reasons": {"verified_original_same_booking_dated_leg": 1} if strict else {}},
    }
    return {"report": report, "before": state, "first": deepcopy(state), "second": deepcopy(state)}


def failed(result, name):
    return name in result["summary"]["failed_checks"]


def test_identical_material_results_pass_with_measured_timing():
    baseline, candidate = bundle(), bundle(True)
    candidate["report"]["runs"] = deepcopy(candidate["report"]["runs"])
    candidate["report"]["runs"][0]["seconds"] = 1.05
    result = audit.compare(baseline, candidate)
    assert result["passed"]
    assert result["summary"]["timing"]["pass_1"]["change_percent"] == 5


@pytest.mark.parametrize("field", ["snapshot_sha256", "sources_sha256", "attachment_manifest_sha256"])
def test_different_inputs_cannot_certify_no_regression(field):
    candidate = bundle(True)
    candidate["report"][field] = "different"
    assert failed(audit.compare(bundle(), candidate), f"same_{field}")


def test_addition_requires_review_even_when_it_claims_personal_ownership():
    candidate = bundle(True)
    for phase in ("first", "second"):
        extra = deepcopy(candidate[phase]["segments"][0])
        extra.update(id=2, flight_number="UA124")
        candidate[phase]["segments"].append(extra)
    result = audit.compare(bundle(), candidate)
    assert failed(result, "baseline_candidate_flights_unchanged")
    assert result["summary"]["differences"]["flights"]["added"] == 1


def test_stable_count_does_not_hide_flight_id_replacement():
    candidate = bundle(True)
    for phase in ("first", "second"):
        candidate[phase]["segments"][0]["id"] = 7
    result = audit.compare(bundle(), candidate)
    assert not result["passed"]
    assert result["summary"]["differences"]["flights"]["removed"] == 1


@pytest.mark.parametrize("mutation", ["passenger", "ownership", "privacy", "title", "status"])
def test_non_count_regressions_are_not_hidden(mutation):
    candidate = bundle(True)
    for phase in ("first", "second"):
        state = candidate[phase]
        if mutation == "passenger":
            state["segments"][0]["meta_json"]["passenger_names"] = ["Morgan Avery"]
        elif mutation == "ownership":
            state["segments"][0]["meta_json"]["ownership"] = "other"
        elif mutation == "privacy":
            state["trips"][0]["visibility"] = "public"
        elif mutation == "title":
            state["trips"][0]["title"] = "Incorrect destination"
        else:
            state["messages"][0]["status"] = "review_required"
    assert not audit.compare(bundle(), candidate)["passed"]


def test_immutable_row_changes_fail_even_when_both_replays_make_the_same_change():
    baseline, candidate = bundle(), bundle(True)
    for run in (baseline, candidate):
        for phase in ("first", "second"):
            run[phase]["booking_observations"][0]["facts"] = {"changed": True}
    result = audit.compare(baseline, candidate)
    assert failed(result, "candidate:original_booking_observations_preserved")


def test_original_known_cancellation_removal_is_distinct_from_new_candidate_loss():
    baseline, candidate = bundle(), bundle(True)
    for run in (baseline, candidate):
        for phase in ("first", "second"):
            run[phase]["segments"] = []
            run[phase]["trips"] = []
    result = audit.compare(baseline, candidate)
    assert result["passed"]
    assert len(result["original_to_replayed_flights"]["baseline"]["removed"]) == 1
    assert result["summary"]["differences"]["flights"]["removed"] == 0


def test_actual_second_pass_change_overrides_claimed_idempotence():
    candidate = bundle(True)
    candidate["report"]["material_projection_idempotent"] = True
    candidate["second"]["segments"][0]["arr_time"] = "2025-02-21T16:00:00Z"
    result = audit.compare(bundle(), candidate)
    assert failed(result, "candidate:material_second_pass_idempotent")


def test_source_provenance_growth_is_visible_without_changing_material_gate():
    candidate = bundle(True)
    for phase in ("first", "second"):
        candidate[phase]["segments"][0]["meta_json"]["source_message_ids"] = ["message-one"]
    result = audit.compare(bundle(), candidate)
    assert result["passed"]
    assert result["summary"]["differences"]["full_segment_provenance"]["changed"] == 1


def test_duplicate_family_given_name_formatting_is_not_a_new_person():
    candidate = bundle(True)
    candidate["second"]["segments"][0]["meta_json"]["passenger_names"].append("AVERY/ALEX")
    result = audit.compare(bundle(), candidate)
    assert result["passed"]
    assert result["summary"]["differences"]["full_segment_provenance"]["changed"] == 1


def test_added_middle_name_is_not_guessed_equivalent_by_comparator():
    candidate = bundle(True)
    candidate["second"]["segments"][0]["meta_json"]["passenger_names"].append("Alex Morgan Avery")
    assert failed(audit.compare(bundle(), candidate), "candidate:material_second_pass_idempotent")


def test_second_pass_can_skip_fetching_messages_already_processed():
    candidate = bundle(True)
    candidate["report"]["runs"] = deepcopy(candidate["report"]["runs"])
    candidate["report"]["runs"][1]["fetches"] = 0
    assert audit.compare(bundle(), candidate)["passed"]


def test_partial_pass_cannot_be_certified_by_completed_jobs_only():
    candidate = bundle(True)
    candidate["report"]["runs"] = deepcopy(candidate["report"]["runs"])
    candidate["report"]["runs"][1]["results"][0]["scanned_count"] = 0
    assert failed(audit.compare(bundle(), candidate), "candidate:two_complete_passes")


@pytest.mark.parametrize("status", [404, 500])
def test_only_documented_404_sources_count_as_accounted_for(status):
    baseline, candidate = bundle(), bundle(True)
    for run in (baseline, candidate):
        run["report"]["snapshot_message_count"] = 2
        run["report"]["unavailable_sources"] = [{"provider_msg_id": "missing",
            "classification": "deleted_or_unavailable_404", "capture_error": {"status": status}}]
    result = audit.compare(baseline, candidate)
    assert result["passed"] is (status == 404)


def test_candidate_cannot_be_silently_run_with_feature_disabled():
    candidate = bundle(True)
    candidate["report"]["strict_enrichment"]["effective"] = False
    assert failed(audit.compare(bundle(), candidate), "candidate_mode_recorded")


def test_old_baseline_without_mode_is_valid_only_when_feature_is_absent():
    baseline = bundle()
    del baseline["report"]["strict_enrichment"]
    assert audit.compare(baseline, bundle(True))["passed"]
    baseline["report"]["candidate_source_start"]["files"]["app/services/booking_enrichment.py"] = "unexpected"
    assert failed(audit.compare(baseline, bundle(True)), "baseline_mode_off")


def test_strict_mode_flag_alone_does_not_prove_candidate_was_exercised():
    candidate = bundle(True)
    candidate["report"]["strict_enrichment"].update(evaluations=0, allowed=0, reasons={})
    assert failed(audit.compare(bundle(), candidate), "candidate_policy_exercised")


def test_missing_evidence_table_cannot_be_a_green_comparison():
    candidate = bundle(True)
    del candidate["second"]["booking_observations"]
    assert not audit.compare(bundle(), candidate)["passed"]


def test_duplicate_snapshot_ids_are_rejected():
    candidate = bundle(True)
    candidate["second"]["segments"].append(deepcopy(candidate["second"]["segments"][0]))
    with pytest.raises(ValueError, match="Duplicate row identity"):
        audit.compare(bundle(), candidate)


def add_inbox(run, identifier, *, original=False):
    phases = ("before", "first", "second") if original else ("first", "second")
    for phase in phases:
        run[phase]["travel_inbox_items"].append({"id": identifier, "user_id": 1, "record_key": "record-one",
            "flight_key": "flight-one", "passenger_key": "passenger-one", "passenger_name": "Morgan Avery",
            "reason": "other_passenger", "created_at": identifier + "-timestamp"})
        run[phase]["travel_inbox_evidence"].append({"id": 1, "item_id": identifier, "observation_id": 1})


def test_new_random_inbox_uuid_and_fk_are_compared_by_unique_record_key():
    baseline, candidate = bundle(), bundle(True)
    add_inbox(baseline, "fresh-baseline-uuid")
    add_inbox(candidate, "fresh-candidate-uuid")
    result = audit.compare(baseline, candidate)
    assert result["passed"]
    assert result["summary"]["differences"]["inbox_items"] == {"removed": 0, "added": 0, "changed": 0}
    assert result["summary"]["differences"]["inbox_evidence"] == {"removed": 0, "added": 0, "changed": 0}
    assert result["summary"]["differences"]["raw_inbox_uuid_provenance"]["removed"] == 1
    assert result["summary"]["differences"]["raw_inbox_evidence_provenance"]["changed"] == 1


def test_original_inbox_uuid_is_never_canonicalized_away():
    baseline, candidate = bundle(), bundle(True)
    add_inbox(baseline, "original-uuid", original=True)
    add_inbox(candidate, "original-uuid", original=True)
    for phase in ("first", "second"):
        candidate[phase]["travel_inbox_items"][0]["id"] = "replacement-uuid"
        candidate[phase]["travel_inbox_evidence"][0]["item_id"] = "replacement-uuid"
    with pytest.raises(ValueError, match="Original inbox ID was replaced"):
        audit.compare(baseline, candidate)


def test_original_inbox_row_changes_remain_a_failure():
    baseline, candidate = bundle(), bundle(True)
    add_inbox(baseline, "original-uuid", original=True)
    add_inbox(candidate, "original-uuid", original=True)
    for phase in ("first", "second"):
        candidate[phase]["travel_inbox_items"][0]["passenger_name"] = "Alex Avery"
    result = audit.compare(baseline, candidate)
    assert failed(result, "candidate:original_inbox_rows_preserved")


def test_new_inbox_identity_canonicalization_does_not_hide_wrong_passenger():
    baseline, candidate = bundle(), bundle(True)
    add_inbox(baseline, "fresh-baseline-uuid")
    add_inbox(candidate, "fresh-candidate-uuid")
    for phase in ("first", "second"):
        candidate[phase]["travel_inbox_items"][0]["passenger_name"] = "Alex Avery"
    assert failed(audit.compare(baseline, candidate), "baseline_candidate_inbox_items_unchanged")


def test_new_uuid_must_stay_identical_on_second_pass_within_one_run():
    baseline, candidate = bundle(), bundle(True)
    add_inbox(baseline, "fresh-baseline-uuid")
    add_inbox(candidate, "fresh-candidate-uuid")
    candidate["second"]["travel_inbox_items"][0]["id"] = "regenerated-on-second-pass"
    candidate["second"]["travel_inbox_evidence"][0]["item_id"] = "regenerated-on-second-pass"
    assert failed(audit.compare(baseline, candidate), "candidate:evidence_second_pass_idempotent")


def test_duplicate_inbox_logical_identity_is_rejected():
    candidate = bundle(True)
    add_inbox(candidate, "fresh-candidate-uuid")
    extra = deepcopy(candidate["second"]["travel_inbox_items"][0])
    extra["id"] = "second-uuid-same-record"
    candidate["second"]["travel_inbox_items"].append(extra)
    with pytest.raises(ValueError, match="Duplicate inbox logical identity"):
        audit.compare(bundle(), candidate)


@pytest.mark.parametrize("missing", ["item", "observation"])
def test_missing_inbox_evidence_reference_is_rejected(missing):
    candidate = bundle(True)
    add_inbox(candidate, "fresh-candidate-uuid")
    key = "item_id" if missing == "item" else "observation_id"
    candidate["second"]["travel_inbox_evidence"][0][key] = "missing-reference"
    with pytest.raises(ValueError, match="Dangling inbox evidence reference"):
        audit.compare(bundle(), candidate)


def test_shares_are_never_remapped_or_ignored():
    baseline, candidate = bundle(), bundle(True)
    add_inbox(baseline, "fresh-baseline-uuid")
    add_inbox(candidate, "fresh-candidate-uuid")
    for phase in ("first", "second"):
        candidate[phase]["flight_shares"].append({"id": "new-share", "item_ids": ["fresh-candidate-uuid"]})
    result = audit.compare(baseline, candidate)
    assert failed(result, "candidate:flight_shares_untouched")
