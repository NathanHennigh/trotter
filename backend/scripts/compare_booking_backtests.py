"""Compare two offline mailbox replays without connecting to any service.

The default gate requires identical material results. Additional recovered
flights are deliberately a review result, not an automatic certification.
The detailed output is private; stdout contains counts and timing only.
"""
from __future__ import annotations

import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import re
import unicodedata


REQUIRED_TABLES = {
    "users", "messages", "segments", "trips", "booking_observations",
    "booking_cancellations", "itinerary_history", "travel_inbox_items",
    "travel_inbox_evidence", "travel_inbox_assignments", "flight_shares",
}
IMMUTABLE_TABLES = (
    "booking_observations", "booking_cancellations", "itinerary_history", "travel_inbox_evidence",
)
IDENTITY_METADATA = ("ownership", "passenger_names")
MATERIAL_METADATA = (
    "time_provenance", "enrichment", "aircraft", "nonstop", "personal_note", "pnr_aliases",
    *IDENTITY_METADATA,
)
VOLATILE_FIELDS = {"created_at", "updated_at"}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def fingerprint(value):
    return sha256(canonical(value).encode()).hexdigest()


def rows_by_id(rows):
    result = {str(row["id"]): row for row in rows}
    if len(result) != len(rows):
        raise ValueError("Duplicate row identity in snapshot")
    return result


def row_diff(before, after):
    left, right = rows_by_id(before), rows_by_id(after)
    return {
        "removed": [left[key] for key in sorted(left.keys() - right.keys())],
        "added": [right[key] for key in sorted(right.keys() - left.keys())],
        "changed": [
            {"id": left[key]["id"], "fields": sorted(
                field for field in left[key].keys() | right[key].keys()
                if left[key].get(field) != right[key].get(field)),
             "before": left[key], "after": right[key]}
            for key in sorted(left.keys() & right.keys()) if left[key] != right[key]
        ],
    }


def is_unchanged(change):
    return not any(change.values())


def material_segments(tables):
    result = []
    for row in tables["segments"]:
        meta = row.get("meta_json") or {}
        material = {key: meta.get(key) for key in MATERIAL_METADATA}
        # Duplicate airline formatting is provenance growth, not a new person.
        # Only normalize case, punctuation, titles and explicit family/given
        # notation. Do not guess middle names, expand initials or reorder tokens.
        names = material.get("passenger_names")
        if isinstance(names, list) and all(isinstance(name, str) for name in names):
            material["passenger_names"] = sorted({canonical_name(name) for name in names})
        result.append({**{key: value for key, value in row.items() if key != "meta_json"},
                       "material_metadata": material})
    return result


def canonical_name(name):
    value = unicodedata.normalize("NFKD", name).casefold()
    value = "".join(char for char in value if not unicodedata.combining(char))
    if len(re.findall(r"[/,]", value)) == 1:
        family, given = re.split(r"[/,]", value)
        if given.strip(" .") not in {"jr", "sr", "ii", "iii", "iv"}:
            value = given + " " + family
    tokens = re.findall(r"\w+", value)
    return " ".join(token for token in tokens if token not in {"mr", "mrs", "ms", "miss", "dr", "prof"})


def stable_rows(rows):
    return [{key: value for key, value in row.items() if key not in VOLATILE_FIELDS} for row in rows]


def canonical_inbox(tables, original_items):
    """Reconcile fresh uuid4 values across runs, never existing account IDs.

    The database enforces unique (user_id, record_key). Only rows absent from
    the common snapshot may use this logical identity; replacing an original
    item's ID, changing its identity, or losing a foreign key is a failure.
    """
    originals = rows_by_id(original_items)
    original_keys = {(row["user_id"], row["record_key"]): str(row["id"]) for row in original_items}
    if len(original_keys) != len(original_items):
        raise ValueError("Duplicate original inbox logical identity")
    rows_by_id(tables["travel_inbox_items"])
    keys, mapping, items = set(), {}, []
    for row in tables["travel_inbox_items"]:
        if row.get("user_id") is None or not isinstance(row.get("record_key"), str) or not row["record_key"]:
            raise ValueError("Incomplete inbox logical identity")
        key = (row["user_id"], row["record_key"])
        if key in keys:
            raise ValueError("Duplicate inbox logical identity")
        keys.add(key)
        identifier = str(row["id"])
        if identifier in originals:
            old = originals[identifier]
            if key != (old["user_id"], old["record_key"]):
                raise ValueError("Original inbox identity changed")
            normalized_id = identifier
        elif key in original_keys:
            raise ValueError("Original inbox ID was replaced")
        else:
            normalized_id = "new-inbox:" + fingerprint(key)
        mapping[identifier] = normalized_id
        items.append({**{name: value for name, value in row.items() if name not in VOLATILE_FIELDS}, "id": normalized_id})
    if not originals.keys() <= mapping.keys():
        raise ValueError("Original inbox item disappeared")
    observations = {str(row["id"]) for row in tables["booking_observations"]}
    evidence = []
    for row in tables["travel_inbox_evidence"]:
        identifier = str(row["item_id"])
        if identifier not in mapping or str(row["observation_id"]) not in observations:
            raise ValueError("Dangling inbox evidence reference")
        evidence.append({**row, "item_id": mapping[identifier]})
    return items, evidence


def immutable_changes(before, after, table):
    right = rows_by_id(after[table])
    return [row["id"] for row in before[table] if right.get(str(row["id"])) != row]


def leg_counts(tables):
    counts = Counter()
    for row in tables["segments"]:
        meta = row.get("meta_json") or {}
        day = (meta.get("time_provenance") or {}).get("departure_local_date") or str(row["dep_time"])[:10]
        counts[(day, row["dep_airport"], row["arr_airport"],
                "".join(str(row.get("flight_number") or "").split()).upper())] += 1
    return counts


def manual_decisions(tables):
    return [row for row in tables["booking_observations"] if (row.get("facts") or {}).get("user_decision")]


def coverage_valid(report):
    unavailable = report.get("unavailable_sources")
    if not isinstance(unavailable, list):
        return False
    ids = [row.get("provider_msg_id") for row in unavailable]
    return (
        isinstance(report.get("source_count"), int)
        and report["source_count"] > 0
        and report.get("snapshot_message_count") == report["source_count"] + len(unavailable)
        and len(set(ids)) == len(ids)
        and report.get("all_sources_accounted_for") is True
        and all(row.get("classification") == "deleted_or_unavailable_404"
                and (row.get("capture_error") or {}).get("status") == 404 for row in unavailable)
    )


def run_checks(label, bundle):
    report, before, first, second = (bundle[key] for key in ("report", "before", "first", "second"))
    checks = []
    def check(name, passed, detail=None):
        checks.append({"name": f"{label}:{name}", "passed": bool(passed), "detail": detail})
    for phase, tables in (("before", before), ("first", first), ("second", second)):
        check(f"{phase}_tables_complete", REQUIRED_TABLES <= tables.keys())
        if not REQUIRED_TABLES <= tables.keys():
            return checks
        for rows in tables.values():
            rows_by_id(rows)
    check("offline_normal_gate", report.get("offline_only") is True
          and report.get("normal_gate") is True and report.get("force_parse") is False)
    check("no_network", report.get("network_attempts") == [])
    check("restore_verified", report.get("restore_verified") is True)
    check("source_frozen", report.get("candidate_source_unchanged") is True
          and bool(report.get("candidate_source_start"))
          and report.get("candidate_source_start") == report.get("candidate_source_end"))
    check("indexed_sources_accounted_for", coverage_valid(report), {
        "captured": report.get("source_count"), "indexed": report.get("snapshot_message_count"),
        "unavailable": len(report.get("unavailable_sources") or []),
    })
    runs = report.get("runs") or []
    check("two_complete_passes", len(runs) == 2 and all(
        run.get("results")
        and sum(item.get("scanned_count", 0) for item in run["results"]) == report.get("source_count", 0)
        and all(item and item.get("state") == "completed" and not item.get("failed_message_ids")
                for item in run["results"]) for run in runs))
    for table in IMMUTABLE_TABLES:
        changed = immutable_changes(before, second, table)
        check(f"original_{table}_preserved", not changed, changed)
    for phase in ("first", "second"):
        canonical_inbox(bundle[phase], before["travel_inbox_items"])
    original_inbox = rows_by_id(before["travel_inbox_items"])
    final_inbox = rows_by_id(second["travel_inbox_items"])
    check("original_inbox_rows_preserved", all(final_inbox.get(key) == row for key, row in original_inbox.items()))
    check("manual_decisions_preserved", manual_decisions(before) == manual_decisions(second))
    for table in ("flight_shares", "travel_inbox_assignments", "users"):
        check(f"{table}_untouched", before[table] == second[table])
    check("material_second_pass_idempotent", material_segments(first) == material_segments(second)
          and first["trips"] == second["trips"])
    check("evidence_second_pass_idempotent", all(first[table] == second[table] for table in (
        "booking_observations", "booking_cancellations", "travel_inbox_items", "travel_inbox_evidence")))
    valid_trips = {row["id"] for row in second["trips"]}
    orphans = [row["id"] for row in second["segments"] if row["trip_id"] not in valid_trips]
    check("no_orphan_flights", not orphans, orphans)
    prior = leg_counts(before)
    increased_duplicates = [{"leg": key, "count": count} for key, count in leg_counts(second).items()
                            if count > max(1, prior[key])]
    check("no_new_duplicate_legs", not increased_duplicates, increased_duplicates)
    return checks


def compare(baseline, candidate, *, expected_mode="strict"):
    checks = [*run_checks("baseline", baseline), *run_checks("candidate", candidate)]
    def check(name, passed, detail=None):
        checks.append({"name": name, "passed": bool(passed), "detail": detail})
    b_report, c_report = baseline["report"], candidate["report"]
    for field in ("snapshot_sha256", "sources_sha256", "attachment_manifest_sha256"):
        check(f"same_{field}", b_report.get(field) == c_report.get(field)
              and (field == "attachment_manifest_sha256" or bool(b_report.get(field))))
    check("same_starting_tables", baseline["before"] == candidate["before"])
    c_files = (c_report.get("candidate_source_start") or {}).get("files") or {}
    b_files = (b_report.get("candidate_source_start") or {}).get("files") or {}
    c_mode, b_mode = c_report.get("strict_enrichment") or {}, b_report.get("strict_enrichment")
    strict = expected_mode == "strict"
    check("candidate_mode_recorded", c_mode.get("requested") is strict and c_mode.get("effective") is strict
          and (not strict or c_mode.get("module_present") is True
               and "app/services/booking_enrichment.py" in c_files))
    if strict:
        count, reasons = c_mode.get("evaluations"), c_mode.get("reasons")
        check("candidate_policy_exercised", isinstance(count, int) and count > 0
              and isinstance(reasons, dict) and all(isinstance(value, int) and value >= 0 for value in reasons.values())
              and sum(reasons.values()) == count
              and isinstance(c_mode.get("allowed"), int) and 0 <= c_mode["allowed"] <= count)
    check("baseline_mode_off", isinstance(b_mode, dict) and b_mode.get("requested") is False
          and b_mode.get("effective") is False
          or b_mode is None and "app/services/booking_enrichment.py" not in b_files)
    if any(not REQUIRED_TABLES <= bundle[phase].keys() for bundle in (baseline, candidate)
           for phase in ("before", "first", "second")):
        return {"passed": False, "checks": checks, "differences": {}, "summary": {"passed": False}}

    left, right = baseline["second"], candidate["second"]
    left_items, left_evidence = canonical_inbox(left, baseline["before"]["travel_inbox_items"])
    right_items, right_evidence = canonical_inbox(right, candidate["before"]["travel_inbox_items"])
    differences = {}
    for name, old, new in (
        ("flights", material_segments(left), material_segments(right)),
        ("trips", left["trips"], right["trips"]),
        ("users", left["users"], right["users"]),
        ("shares", left["flight_shares"], right["flight_shares"]),
        ("assignments", left["travel_inbox_assignments"], right["travel_inbox_assignments"]),
        ("manual_decisions", manual_decisions(left), manual_decisions(right)),
        ("inbox_items", left_items, right_items),
        ("inbox_evidence", left_evidence, right_evidence),
        ("observations", stable_rows(left["booking_observations"]), stable_rows(right["booking_observations"])),
        ("cancellations", stable_rows(left["booking_cancellations"]), stable_rows(right["booking_cancellations"])),
    ):
        differences[name] = row_diff(old, new)
        check(f"baseline_candidate_{name}_unchanged", is_unchanged(differences[name]))
    message_fields = ("id", "user_id", "provider_msg_id", "status", "parse_error", "ignored")
    differences["message_statuses"] = row_diff(
        [{key: row.get(key) for key in message_fields} for row in left["messages"]],
        [{key: row.get(key) for key in message_fields} for row in right["messages"]])
    check("message_statuses_unchanged", is_unchanged(differences["message_statuses"]))
    # Extra provenance can be useful without changing the itinerary, but it is
    # surfaced privately for review rather than hidden by the material projection.
    differences["full_segment_provenance"] = row_diff(left["segments"], right["segments"])
    differences["raw_inbox_uuid_provenance"] = row_diff(left["travel_inbox_items"], right["travel_inbox_items"])
    differences["raw_inbox_evidence_provenance"] = row_diff(left["travel_inbox_evidence"], right["travel_inbox_evidence"])
    timings = {}
    for index in range(2):
        b_runs, c_runs = b_report.get("runs") or [], c_report.get("runs") or []
        b = b_runs[index].get("seconds") if len(b_runs) > index else None
        c = c_runs[index].get("seconds") if len(c_runs) > index else None
        timings[f"pass_{index + 1}"] = {"baseline_seconds": b, "candidate_seconds": c,
            "change_percent": round((c / b - 1) * 100, 2) if b and c is not None else None}
    failures = [item["name"] for item in checks if not item["passed"]]
    counts = {name: {kind: len(rows) for kind, rows in change.items()}
              for name, change in differences.items()}
    original = baseline["before"]
    inherited = {"baseline": row_diff(material_segments(original), material_segments(left)),
                 "candidate": row_diff(material_segments(original), material_segments(right))}
    summary = {"passed": not failures, "failed_checks": failures,
               "source_count": c_report.get("source_count"), "differences": counts, "timing": timings}
    return {"passed": not failures, "offline_comparison": True, "checks": checks,
            "input_fingerprints": {label: {field: bundle["report"].get(field) for field in
                ("snapshot_sha256", "sources_sha256", "attachment_manifest_sha256")}
                for label, bundle in (("baseline", baseline), ("candidate", candidate))},
            "differences": differences, "original_to_replayed_flights": inherited,
            "inbox_identity_policy": "Only newly generated inbox UUIDs are compared by unique(user_id,record_key), with evidence foreign keys remapped. Original rows/IDs, assignment/share IDs, and within-run second-pass IDs remain exact. Raw UUID differences are advisory.",
            "timing_note": "Observed offline worker timings; not a controlled benchmark or production latency guarantee.",
            "summary": summary}


def load_bundle(prefix):
    result, paths = {}, []
    for key, suffix in (("report", "-report.json"), ("before", "-before.json"),
                        ("first", "-pass-1.json"), ("second", "-pass-2.json")):
        path = Path(str(prefix) + suffix).resolve()
        result[key] = json.loads(path.read_text(encoding="utf-8-sig"))
        paths.append(path)
    return result, paths


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-prefix", type=Path, required=True)
    parser.add_argument("--candidate-prefix", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="New private report; never overwrites a file")
    parser.add_argument("--expected-mode", choices=("strict", "off"), default="strict")
    args = parser.parse_args()
    baseline, b_paths = load_bundle(args.baseline_prefix)
    candidate, c_paths = load_bundle(args.candidate_prefix)
    output = args.output.resolve()
    if output in b_paths + c_paths:
        raise SystemExit("Output cannot replace a replay input")
    report = compare(baseline, candidate, expected_mode=args.expected_mode)
    report["artifact_sha256"] = {str(path): sha256(path.read_bytes()).hexdigest() for path in b_paths + c_paths}
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf8") as target:
        json.dump(report, target, indent=2, ensure_ascii=False)
    try:
        output.chmod(0o600)
    except OSError:
        pass  # Windows access is inherited from the private artifact directory.
    print(json.dumps(report["summary"], indent=2))
    raise SystemExit(0 if report["passed"] else 2)


if __name__ == "__main__":
    main()
