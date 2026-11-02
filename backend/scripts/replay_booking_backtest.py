"""Replay captured Gmail through the real importer in a disposable local database.

No mailbox/database HTTP is allowed. Captured IDs are fed as already committed
history checkpoints, so this exercises normal gating, parsing, reconciliation,
trip building and local enrichment, not Gmail search/discovery itself. No repair
manifest, force_parse override, row downgrade, or preservation guard is applied.
"""
from __future__ import annotations

import argparse
import base64
from collections import Counter
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from enum import Enum
from hashlib import sha256
import json
import os
from pathlib import Path
import socket
import sys
import time


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def file_digest(path):
    checksum = sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            checksum.update(chunk)
    return checksum.hexdigest()


def backend_source_manifest(backend):
    """Capture executable app sources and dependency declarations for this run."""
    backend = Path(backend).resolve()
    paths = list((backend / "app").rglob("*.py"))
    paths.extend(path for name in ("pyproject.toml", "poetry.lock", "uv.lock") if (path := backend / name).is_file())
    files = {path.relative_to(backend).as_posix(): file_digest(path) for path in sorted(paths)}
    encoded = json.dumps(files, sort_keys=True, separators=(",", ":")).encode()
    return {"root": str(backend), "file_count": len(files), "sha256": sha256(encoded).hexdigest(), "files": files}


def encode(value):
    if isinstance(value, (datetime, date)):
        if isinstance(value, datetime):
            value = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, bytes):
        return {"bytes_sha256": sha256(value).hexdigest()}
    raise TypeError(type(value).__name__)


def canonical(value):
    return json.loads(json.dumps(value, default=encode, sort_keys=True))


def digest(value):
    return sha256(json.dumps(canonical(value), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def decode(value):
    return datetime.fromisoformat(value["__datetime__"]) if isinstance(value, dict) and set(value) == {"__datetime__"} else value


def summarize_leg(row):
    # Detailed metadata is retained in the before/after snapshots beside the report.
    return {key: row.get(key) for key in (
        "id", "trip_id", "dep_airport", "arr_airport", "dep_time", "arr_time", "flight_number", "pnr")}


def leg_key(row):
    meta = row.get("meta_json") or {}
    day = (meta.get("time_provenance") or {}).get("departure_local_date") or str(row["dep_time"])[:10]
    return (day, row["dep_airport"], row["arr_airport"], row.get("flight_number") or "")


def diff(before, after):
    result = {}
    for table in before:
        old = {str(row["id"]): row for row in before[table]}
        new = {str(row["id"]): row for row in after.get(table, [])}
        common = old.keys() & new.keys()
        changed = [key for key in common if old[key] != new[key]]
        fields = Counter(field for key in changed for field in old[key] if old[key][field] != new[key].get(field))
        result[table] = {"before": len(old), "after": len(new),
                         "removed_ids": sorted(old.keys() - new.keys()),
                         "added_ids": sorted(new.keys() - old.keys()),
                         "changed_ids": sorted(changed), "changed_fields": dict(fields)}
    old = {row["id"]: row for row in before["segments"]}
    new = {row["id"]: row for row in after["segments"]}
    material_fields = ("trip_id", "dep_airport", "arr_airport", "dep_time", "arr_time", "flight_number", "pnr")
    old_keys, new_keys = Counter(map(leg_key, old.values())), Counter(map(leg_key, new.values()))
    return {"tables": result,
            "removed_flights": [summarize_leg(old[key]) for key in sorted(old.keys() - new.keys())],
            "added_flights": [summarize_leg(new[key]) for key in sorted(new.keys() - old.keys())],
            "changed_flights": [{"before": summarize_leg(old[key]), "after": summarize_leg(new[key]),
                                  "fields": [field for field in material_fields if old[key][field] != new[key][field]]}
                                 for key in sorted(old.keys() & new.keys())
                                 if any(old[key][field] != new[key][field] for field in material_fields)],
            "removed_leg_keys": list((old_keys - new_keys).elements()),
            "added_leg_keys": list((new_keys - old_keys).elements()),
            "duplicate_leg_keys": [{"leg_key": key, "count": count} for key, count in new_keys.items() if count > 1]}


def boundaries(tables):
    segments = tables["segments"]
    def during(start, end):
        return [summarize_leg(row) for row in segments if start <= leg_key(row)[0] < end]
    decisions = [row for row in tables["booking_observations"] if (row.get("facts") or {}).get("user_decision")]
    return {"orlando": during("2025-02-18", "2025-02-24"),
            "bilt": during("2026-09-09", "2026-09-12"),
            "user_decisions": [{"id": row["id"], "evidence_key": row["evidence_key"], "ownership": row["ownership"],
                                "route": [row["dep_airport"], row["arr_airport"]], "flight_number": row["flight_number"],
                                "date": row["travel_date"], "decision": row["facts"]["user_decision"]}
                               for row in decisions],
            "trip_membership": {str(row["id"]): sorted(s["id"] for s in segments if s["trip_id"] == row["id"])
                                for row in tables["trips"]}}


MATERIAL_META_FIELDS = ("time_provenance", "enrichment", "aircraft", "nonstop", "personal_note", "pnr_aliases")


def material_projection(tables):
    """Keep itinerary content and rendering facts separate from source-link growth."""
    segments = []
    for row in tables["segments"]:
        meta = row.get("meta_json") or {}
        segments.append({**{key: value for key, value in row.items() if key != "meta_json"},
                         "display_metadata": {key: meta.get(key) for key in MATERIAL_META_FIELDS}})
    return {"segments": segments, "trips": tables["trips"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    root = Path(__file__).resolve().parent
    parser.add_argument("--backend", type=Path, default=root.parent)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--sources", type=Path, required=True)
    parser.add_argument("--output-prefix", type=Path, required=True)
    parser.add_argument("--strict-enrichment", choices=("on", "off"), default="off",
                        help="Explicit candidate policy; never inherit this setting from the shell")
    parser.add_argument("--carrier-corroboration", choices=("on", "off"), default="off",
                        help="Explicit typed carrier recovery; default off and never inherited")
    parser.add_argument("--max-messages", type=int, default=None, help="Explicit partial smoke test only")
    parser.add_argument("--attachment-files", type=Path, default=None,
                        help="Captured original PDF files to re-extract offline, scoped by message and attachment ID")
    args = parser.parse_args()
    candidate_source_start = backend_source_manifest(args.backend)
    prefix = args.output_prefix.resolve()
    prefix.parent.mkdir(parents=True, exist_ok=True)
    db_path = Path(str(prefix) + ".sqlite")
    if db_path.exists():
        raise SystemExit(f"Refusing to overwrite prior replay database: {db_path}")
    captured = load(args.snapshot)
    user_id = captured["user_id"]
    sources_document = load(args.sources)
    entries = sources_document["messages"]
    if args.max_messages is not None:
        entries = entries[:args.max_messages]
    db_ids = {row["id"]: row["provider_msg_id"] for row in captured["tables"]["messages"]}
    sources = {}
    for entry in entries:
        message = entry["gmail"]
        if db_ids.get(entry["db_id"]) != message["id"]:
            raise ValueError(f"Source is not the captured account's original message: {entry['db_id']}")
        if message["id"] in sources:
            raise ValueError("Duplicate captured source message")
        sources[message["id"]] = entry
    expected_sources = {row["provider_msg_id"]: row["id"] for row in captured["tables"]["messages"]}
    capture_errors = sources_document.get("errors") or {}
    unavailable = [{"db_id": expected_sources[mid], "provider_msg_id": mid, "capture_error": capture_errors.get(mid),
                    "classification": "deleted_or_unavailable_404" if capture_errors.get(mid, {}).get("status") == 404
                    else "capture_error_retry_needed" if mid in capture_errors else "not_captured"}
                   for mid in sorted(set(expected_sources) - set(sources))]

    # Set these before importing the app; no environment file or live DB is read.
    os.environ.update(DATABASE_URL=f"sqlite:///{db_path.as_posix()}", CELERY_BROKER_URL="memory://",
                      CELERY_RESULT_BACKEND="cache+memory://", CELERY_TASK_ALWAYS_EAGER="true",
                      TROTTER_ENABLE_AUTOMATIC_BACKFILL="true", TROTTER_GMAIL_HISTORY_USER_IDS=str(user_id),
                      TROTTER_REPARSE_MESSAGE_IDS="", TROTTER_PARSE_WORKERS="1")
    os.environ["BOOKING_STRICT_ENRICHMENT_ENABLED"] = "1" if args.strict_enrichment == "on" else "0"
    os.environ["CARRIER_TRAVEL_CORROBORATION_ENABLED"] = "1" if args.carrier_corroboration == "on" else "0"
    sys.path.insert(0, str(args.backend.resolve()))
    os.environ["PYTHONPATH"] = str(args.backend.resolve())
    network_attempts = []
    def deny_network(*args, **kwargs):
        network_attempts.append("blocked_network_call")
        raise RuntimeError("Network is forbidden in offline shadow replay")
    socket.socket.connect = deny_network
    socket.socket.connect_ex = deny_network
    socket.create_connection = deny_network
    socket.getaddrinfo = deny_network

    from sqlalchemy import create_engine, event, select
    from sqlalchemy.orm import sessionmaker
    from app import db as app_db
    from app.models import Account, Base, GmailHistoryState, SyncJob
    from app.services import enrichment, flight_documents, flight_message, gmail, gmail_history
    from app.services.parser import PARSER_VERSION
    from app.tasks import import_tasks

    strict_requested = args.strict_enrichment == "on"
    strict_module_present = (args.backend / "app/services/booking_enrichment.py").is_file()
    if strict_requested and not strict_module_present:
        raise RuntimeError("Strict replay requested but frozen backend has no strict enrichment implementation")
    strict_counts = Counter()
    strict_allowed = 0
    strict_seconds = 0.0
    strict_effective = False
    if strict_module_present:
        from app.services import booking_enrichment
        strict_effective = booking_enrichment.enabled()
        if strict_effective != strict_requested:
            raise RuntimeError("Effective strict enrichment policy differs from requested replay policy")
        real_evaluate = booking_enrichment.evaluate
        def evaluate(*values, **options):
            nonlocal strict_allowed, strict_seconds
            started = time.perf_counter()
            result = real_evaluate(*values, **options)
            strict_seconds += time.perf_counter() - started
            strict_counts[result.reason] += 1
            strict_allowed += int(result.allowed)
            return result
        booking_enrichment.evaluate = evaluate

    carrier_requested = args.carrier_corroboration == "on"
    carrier_module_present = (args.backend / "app/services/carrier_travel_recovery.py").is_file()
    carrier_counts, carrier_allowed, carrier_seconds = Counter(), 0, 0.0
    carrier_effective = False
    if carrier_requested and not carrier_module_present:
        raise RuntimeError("Carrier recovery requested but frozen backend has no implementation")
    if carrier_module_present:
        from app.services import carrier_travel_recovery
        carrier_effective = carrier_travel_recovery.enabled()
        if carrier_effective != carrier_requested:
            raise RuntimeError("Effective carrier policy differs from requested replay policy")
        real_carrier_evaluate = carrier_travel_recovery.evaluate
        def evaluate_carrier(*values, **options):
            nonlocal carrier_allowed, carrier_seconds
            started = time.perf_counter()
            result = real_carrier_evaluate(*values, **options)
            carrier_seconds += time.perf_counter() - started
            carrier_counts[result.reason] += 1
            carrier_allowed += int(result.allowed)
            return result
        carrier_travel_recovery.evaluate = evaluate_carrier

    attachment_files, attachment_evidence = {}, []
    if args.attachment_files:
        for item in load(args.attachment_files):
            mid = item["provider_msg_id"]
            if mid not in sources or sources[mid]["db_id"] != item["db_id"]:
                raise ValueError("Attachment override does not belong to a captured source")
            manifests = flight_documents.attachment_manifest(sources[mid]["gmail"])
            matches = [part for part in manifests if part["attachment_id"] == item["attachment_id"]
                       and part["filename"] == item["filename"]]
            if len(matches) != 1:
                raise ValueError("Attachment identity does not uniquely match original Gmail metadata")
            path = Path(item["path"]).resolve()
            if path.stat().st_size > flight_documents.MAX_DOCUMENT_BYTES:
                raise ValueError("Attachment override exceeds normal extractor limit")
            data = path.read_bytes()
            if not data.startswith(b"%PDF-"):
                raise ValueError("Attachment override is not an original PDF")
            if item.get("sha256") and item["sha256"] != sha256(data).hexdigest():
                raise ValueError("Attachment bytes do not match captured checksum")
            attachment_files.setdefault(mid, {})[item["attachment_id"]] = base64.urlsafe_b64encode(data).decode()
            attachment_evidence.append({**{key: item[key] for key in
                ("db_id", "provider_msg_id", "attachment_id", "filename")},
                "path": str(path), "sha256": sha256(data).hexdigest(), "bytes": len(data)})
        for mid, overrides in attachment_files.items():
            expected = {part["attachment_id"] for part in flight_documents.attachment_manifest(sources[mid]["gmail"])}
            if set(overrides) != expected:
                raise ValueError("Offline byte extraction requires every PDF attachment in that exact message")

    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        for table in Base.metadata.sorted_tables:
            rows = captured["tables"].get(table.name, [])
            if rows:
                connection.execute(table.insert(), [{key: decode(value) for key, value in row.items()} for row in rows])
    factory = sessionmaker(bind=engine, autoflush=False)
    app_db.SessionLocal = import_tasks.SessionLocal = factory
    with factory() as db:
        db.add(Account(user_id=user_id, provider="google", refresh_token_encrypted=b"offline-only-not-a-real-token",
                       scopes="https://www.googleapis.com/auth/gmail.readonly"))
        db.commit()

    table_names = list(captured["tables"])
    def snapshot():
        with engine.connect() as connection:
            return {name: canonical([dict(row) for row in connection.execute(
                select(Base.metadata.tables[name]).order_by(*Base.metadata.tables[name].primary_key.columns)).mappings()])
                    for name in table_names}
    before = snapshot()
    def carrier_snapshot():
        if "carrier_travel_evidence" not in Base.metadata.tables:
            return []
        table = Base.metadata.tables["carrier_travel_evidence"]
        with engine.connect() as connection:
            return canonical([dict(row) for row in connection.execute(select(table).order_by(table.c.id)).mappings()])
    carrier_snapshots = {"before": carrier_snapshot()}
    for name, rows in captured["tables"].items():
        restored = {row["id"]: row for row in before[name]}
        assert all(canonical({key: decode(value) for key, value in row.items()}) ==
                   {key: restored[row["id"]][key] for key in row} for row in rows), f"Restore changed {name}"
    Path(str(prefix) + "-before.json").write_text(json.dumps(before, indent=2), encoding="utf8")

    requested = []; prepared = []; attachment_requests = []; enrichment_calls = []
    gmail.build_gmail_service = lambda _token: object()
    def fetch(_service, ids):
        requested.extend(ids)
        found = {mid: deepcopy(sources[mid]["gmail"]) for mid in ids if mid in sources}
        missing = {mid: RuntimeError("Message absent from cache") for mid in ids if mid not in sources}
        return found, missing
    gmail.batch_get_messages = fetch
    gmail.batch_get_message_metadata = fetch
    gmail.get_message = lambda service, mid: fetch(service, [mid])[0][mid]
    gmail.list_messages = lambda *a, **kw: (_ for _ in ()).throw(AssertionError("History checkpoints must stay within captured source IDs"))
    real_load_documents = flight_documents.load_ticket_documents
    def documents(_service, message):
        attachment_requests.append(message["id"])
        if message["id"] in attachment_files:
            original = deepcopy(message)
            def inject(part):
                body = part.get("body") or {}
                if body.get("attachmentId") in attachment_files[message["id"]]:
                    body["data"] = attachment_files[message["id"]][body["attachmentId"]]
                for child in part.get("parts") or []:
                    inject(child)
            inject(original["payload"])
            return real_load_documents(object(), original)
        entry = sources[message["id"]]
        if "documents" not in entry:
            return [], ["cache_attachment_unavailable"]
        return deepcopy(entry.get("documents") or []), list(entry.get("document_errors") or [])
    flight_documents.load_ticket_documents = documents
    real_prepare = flight_message.prepare_flight_message
    def prepare(message, **kwargs):
        assert kwargs.get("force_parse") is False, "Shadow replay must use normal evidence gate"
        result = real_prepare(message, **kwargs)
        prepared.append({"provider_msg_id": message["id"], "verdict": result["evidence"].verdict,
                         "flights": len(result["parse_result"].flights) if result["parse_result"] else 0,
                         "documents": len(kwargs.get("documents") or [])})
        return result
    flight_message.prepare_flight_message = prepare
    real_enrich = enrichment.enrich_user_segments
    def enrich(db, uid, **kwargs):
        assert kwargs.get("include_weather") is False and kwargs.get("include_provider_lookup") is False
        enrichment_calls.append(len(kwargs.get("segment_ids") or []))
        return real_enrich(db, uid, **kwargs)
    enrichment.enrich_user_segments = enrich

    ids = sorted(sources, key=lambda mid: (int(sources[mid]["gmail"].get("internalDate") or 0), mid), reverse=True)
    runs = []
    with Path(str(prefix) + "-worker.log").open("w", encoding="utf8") as log:
        for pass_number in (1, 2):
            begin = time.monotonic(); results = []; start_fetch = len(requested); start_prepared = len(prepared)
            for offset in range(0, len(ids), gmail_history.PAGE_SIZE):
                chunk = ids[offset:offset + gmail_history.PAGE_SIZE]
                with factory() as db:
                    row = db.query(GmailHistoryState).filter_by(user_id=user_id).first()
                    if row is None:
                        row = GmailHistoryState(user_id=user_id)
                        db.add(row)
                    now = datetime.now(timezone.utc)
                    row.state, row.pending_message_ids = "queued", chunk
                    row.cursor_before = row.window_end = now
                    row.window_start = now - timedelta(days=31)
                    row.page_token = row.next_page_token = None
                    row.lease_until = row.next_attempt_at = None
                    db.commit(); state_id = row.id
                for attempt in range(len(chunk) + 2):
                    job_id = f"shadow-{pass_number}-{offset}-{attempt}"
                    with factory() as db:
                        row = db.get(GmailHistoryState, state_id)
                        row.state = "queued"
                        db.add(SyncJob(id=job_id, user_id=user_id, state="pending"))
                        db.commit()
                    with redirect_stdout(log), redirect_stderr(log):
                        result = import_tasks.run_gmail_import.run(job_id=job_id, user_id=user_id, mode="history",
                                                                  history_state_id=state_id, limit=50)
                    results.append(result)
                    if not result or result.get("state") != "completed" or result.get("failed_message_ids"):
                        Path(str(prefix) + "-failure.json").write_text(json.dumps({
                            "job_id": job_id, "result": result, "pass": pass_number,
                            "offset": offset, "network_attempts": network_attempts,
                            "diff": diff(before, snapshot()),
                        }, default=encode, indent=2), encoding="utf8")
                        raise RuntimeError(f"Shadow worker failed at {job_id}; inspect local worker log")
                    with factory() as db:
                        remaining = list(db.get(GmailHistoryState, state_id).pending_message_ids or [])
                    if not remaining:
                        break
                else:
                    raise RuntimeError("History checkpoint made no bounded progress")
                print(json.dumps({"pass": pass_number, "checked": min(offset + 50, len(ids)), "total": len(ids),
                                  "seconds": round(time.monotonic() - begin, 1)}), flush=True)
            runs.append({"results": results, "seconds": round(time.monotonic() - begin, 3),
                         "fetches": len(requested) - start_fetch, "preparations": prepared[start_prepared:]})
            current = snapshot()
            carrier_snapshots[f"pass_{pass_number}"] = carrier_snapshot()
            Path(str(prefix) + f"-pass-{pass_number}.json").write_text(json.dumps(current, indent=2), encoding="utf8")
            if pass_number == 1:
                first = current
            else:
                second = current
    immutable_tables = ("booking_observations", "booking_cancellations", "itinerary_history", "travel_inbox_evidence")
    preservation = {}
    for name in immutable_tables:
        after_map = {row["id"]: row for row in second[name]}
        preservation[name] = all(after_map.get(row["id"]) == row for row in before[name])
    report = {"offline_only": True, "normal_gate": True, "force_parse": False, "parser_version": PARSER_VERSION,
              "strict_enrichment": {"requested": strict_requested, "module_present": strict_module_present,
                  "environment_enabled": os.environ["BOOKING_STRICT_ENRICHMENT_ENABLED"] == "1",
                  "effective": strict_effective, "evaluations": sum(strict_counts.values()),
                  "allowed": strict_allowed, "reasons": dict(strict_counts),
                  "evaluation_seconds": round(strict_seconds, 6)},
              "carrier_corroboration": {"requested": carrier_requested, "module_present": carrier_module_present,
                  "effective": carrier_effective, "evaluations": sum(carrier_counts.values()),
                  "allowed": carrier_allowed, "reasons": dict(carrier_counts),
                  "evaluation_seconds": round(carrier_seconds, 6),
                  "evidence_rows": {key: len(value) for key, value in carrier_snapshots.items()},
                  "evidence_idempotent": carrier_snapshots["pass_1"] == carrier_snapshots["pass_2"],
                  "original_rows_preserved": all(row in carrier_snapshots["pass_2"] for row in carrier_snapshots["before"])},
              "candidate_source_start": candidate_source_start,
              "original_attachment_reextraction": attachment_evidence,
              "attachment_manifest_sha256": file_digest(args.attachment_files) if args.attachment_files else None,
              "database": str(db_path), "snapshot": str(args.snapshot.resolve()), "sources": str(args.sources.resolve()),
              "snapshot_sha256": file_digest(args.snapshot), "sources_sha256": file_digest(args.sources),
              "source_count": len(sources), "snapshot_message_count": len(before["messages"]),
              "coverage_complete": len(sources) == len(before["messages"]) and args.max_messages is None,
              "unavailable_sources": unavailable,
              "all_sources_accounted_for": all(row["capture_error"] is not None for row in unavailable),
              "source_quality": dict(Counter(entry.get("source_quality", "captured_gmail") for entry in entries)),
              "source_errors": sources_document.get("errors", {}), "network_attempts": network_attempts,
              "restore_verified": True, "before": boundaries(before), "after": boundaries(first),
              "first_pass": diff(before, first), "second_pass": diff(first, second),
              "projection_idempotent": all(first[name] == second[name] for name in ("segments", "trips")),
              "material_projection_idempotent": material_projection(first) == material_projection(second),
              "material_projection_definition": {"segment_fields": "all stored columns except meta_json",
                  "segment_metadata_fields": MATERIAL_META_FIELDS, "trip_fields": "all stored columns"},
              "evidence_idempotent": all(first[name] == second[name] for name in ("booking_observations", "booking_cancellations", "travel_inbox_items", "travel_inbox_evidence")),
              "original_immutable_rows_preserved": preservation,
              "manual_decisions_preserved": boundaries(before)["user_decisions"] == boundaries(second)["user_decisions"],
              "attachment_requests": attachment_requests, "local_enrichment_calls": len(enrichment_calls), "runs": runs}
    candidate_source_end = backend_source_manifest(args.backend)
    report["candidate_source_end"] = candidate_source_end
    report["candidate_source_unchanged"] = candidate_source_start == candidate_source_end
    Path(str(prefix) + "-carrier-evidence.json").write_text(json.dumps(carrier_snapshots, indent=2), encoding="utf8")
    Path(str(prefix) + "-report.json").write_text(json.dumps(report, indent=2), encoding="utf8")
    if not report["candidate_source_unchanged"]:
        engine.dispose()
        raise RuntimeError("Candidate app sources changed during replay; report is not a coherent frozen-code result")
    print(json.dumps({"report": str(prefix) + "-report.json", "source_count": len(sources),
                      "coverage_complete": report["coverage_complete"], "projection_idempotent": report["projection_idempotent"],
                      "material_projection_idempotent": report["material_projection_idempotent"],
                      "evidence_idempotent": report["evidence_idempotent"], "manual_decisions_preserved": report["manual_decisions_preserved"],
                      "removed_flights": len(report["first_pass"]["removed_flights"]),
                      "added_flights": len(report["first_pass"]["added_flights"]),
                      "changed_flights": len(report["first_pass"]["changed_flights"]), "network_attempts": len(network_attempts)}, indent=2))
    engine.dispose()


if __name__ == "__main__":
    main()
