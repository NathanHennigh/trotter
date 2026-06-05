"""Baseline reporting helpers for Gmail flight import recovery work."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

_FLIGHTISH_AUDIT_BUCKETS = {
    "parsed_ok",
    "duplicate_or_reminder",
    "change_or_cancellation",
}
_PNR_SUBJECT_PATTERNS = (
    re.compile(
        r"\bconfirmation(?:\s+(?:receipt|code|number))?\s*[:#-]?\s*([A-Z0-9]{5,8})\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bbooking(?:\s+(?:reference|code|number|no))?\s*[:#-]?\s*([A-Z0-9]{5,8})\b",
        re.IGNORECASE,
    ),
    re.compile(r"\breceipt\s*[-:]\s*([A-Z0-9]{5,8})\b", re.IGNORECASE),
)
_INVALID_ARTIFACT_PNRS = {
    "AGENT",
    "BEFORE",
    "BOARDING",
    "BOOKING",
    "CODES",
    "CONGRATS",
    "DENVER",
    "DETAILS",
    "DISPLAY",
    "EMAIL",
    "FINAL",
    "LETTER",
    "MANAGED",
    "MANAGUA",
    "NATHAN",
    "NUMBER",
    "NUMBERS",
    "POLICY",
    "PORTAL",
    "PRINT",
    "PROVIDED",
    "ROOMTYPE",
    "SECTION",
    "SOURCE",
    "STARTS",
    "STATUS",
    "THROUGH",
    "WITHIN",
    "WITHOUT",
}


@dataclass(frozen=True)
class SavedSegmentBaseline:
    segment_id: int
    trip_id: int
    dep_airport: str
    arr_airport: str
    airline: str | None
    flight_number: str | None
    pnr: str | None


def parse_segment_copy(text: str) -> list[SavedSegmentBaseline]:
    """Read segment rows from ``pg_restore --data-only --table=segments`` text."""
    rows: list[SavedSegmentBaseline] = []
    in_copy = False
    for line in text.splitlines():
        if line.startswith("COPY public.segments "):
            in_copy = True
            continue
        if not in_copy:
            continue
        if line == r"\.":
            break
        parts = line.split("\t")
        if len(parts) < 10:
            continue
        rows.append(
            SavedSegmentBaseline(
                segment_id=int(parts[0]),
                trip_id=int(parts[1]),
                dep_airport=parts[3],
                arr_airport=parts[4],
                airline=_none_if_pg_null(parts[7]),
                flight_number=_none_if_pg_null(parts[8]),
                pnr=_none_if_pg_null(parts[9]),
            )
        )
    return rows


def extract_segments_from_dump(dump_path: Path) -> tuple[list[SavedSegmentBaseline], str | None]:
    """Extract saved segment rows from a custom Postgres dump when tooling exists."""
    dump_path = dump_path.resolve()
    if not dump_path.exists():
        return [], f"dump not found: {dump_path}"

    commands: list[list[str]] = []
    pg_restore = shutil.which("pg_restore")
    if pg_restore:
        commands.append(
            [
                pg_restore,
                "--data-only",
                "--table=segments",
                "--file=-",
                str(dump_path),
            ]
        )

    docker = shutil.which("docker")
    if docker:
        commands.append(
            [
                docker,
                "run",
                "--rm",
                "-v",
                f"{dump_path.parent}:/backup",
                "postgres:16",
                "pg_restore",
                "--data-only",
                "--table=segments",
                "--file=-",
                f"/backup/{dump_path.name}",
            ]
        )

    errors: list[str] = []
    for command in commands:
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.returncode == 0:
            return parse_segment_copy(result.stdout), None
        errors.append(f"{Path(command[0]).name}: {result.stderr.strip()[:240]}")
    if not commands:
        return [], "neither pg_restore nor docker is available"
    return [], "; ".join(error for error in errors if error) or "segment extraction failed"


def summarize_saved_segments(rows: list[SavedSegmentBaseline]) -> dict[str, Any]:
    routes = Counter(f"{row.dep_airport}->{row.arr_airport}" for row in rows)
    airlines = Counter(row.airline or "unknown" for row in rows)
    pnrs = sorted({row.pnr for row in rows if row.pnr})
    return {
        "segments": len(rows),
        "trips": len({row.trip_id for row in rows}),
        "pnrs": len(pnrs),
        "pnr_values": pnrs,
        "top_routes": dict(routes.most_common(10)),
        "top_airlines": dict(airlines.most_common(10)),
        "sample_segments": [asdict(row) for row in rows[:10]],
    }


def summarize_audit_results(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    scanned = payload.get("scanned") or {}
    rows = [row for row in scanned.values() if isinstance(row, dict)]
    buckets = Counter(row.get("audit_bucket") or "unknown" for row in rows)
    senders = Counter(row.get("sender_domain") or "unknown" for row in rows)
    return {
        "path": str(path),
        "scan_ids": len(payload.get("scan_ids") or []),
        "v4_ids": len(payload.get("v4_ids") or []),
        "scanned": len(rows),
        "parsed_emails": sum(1 for row in rows if int(row.get("parser_flight_count") or 0) > 0),
        "parsed_segments": sum(int(row.get("parser_flight_count") or 0) for row in rows),
        "audit_buckets": dict(buckets.most_common()),
        "top_senders": dict(senders.most_common(10)),
    }


def summarize_artifact_pnrs(*, audit_paths: list[Path], markdown_paths: list[Path]) -> dict[str, Any]:
    """Compare explicit and subject-derived PNRs across audit artifacts."""
    rows_by_id: dict[str, dict[str, Any]] = {}
    for path in audit_paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        scanned = payload.get("scanned") or {}
        for message_id, row in scanned.items():
            if isinstance(row, dict):
                rows_by_id.setdefault(message_id, row)

    candidate_pnrs: set[str] = set()
    flight_bucket_candidate_pnrs: set[str] = set()
    parser_pnrs: set[str] = set()
    subject_pnrs: set[str] = set()
    for row in rows_by_id.values():
        candidate = _normal_artifact_pnr(row.get("candidate_pnr"))
        if candidate:
            candidate_pnrs.add(candidate)
            if row.get("audit_bucket") in _FLIGHTISH_AUDIT_BUCKETS:
                flight_bucket_candidate_pnrs.add(candidate)
        for flight in row.get("parser_flights") or []:
            parser_pnr = _normal_artifact_pnr((flight or {}).get("pnr"))
            if parser_pnr:
                parser_pnrs.add(parser_pnr)
        subject_pnrs.update(extract_subject_pnrs(row.get("subject") or ""))

    markdown_subject_pnrs: set[str] = set()
    for path in markdown_paths:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.lstrip().startswith("- ["):
                markdown_subject_pnrs.update(extract_subject_pnrs(line))

    explicit_pnrs = candidate_pnrs | parser_pnrs
    artifact_union = explicit_pnrs | subject_pnrs | markdown_subject_pnrs
    return {
        "audit_paths": [str(path) for path in audit_paths],
        "markdown_paths": [str(path) for path in markdown_paths],
        "audit_rows": len(rows_by_id),
        "candidate_pnrs": sorted(candidate_pnrs),
        "flight_bucket_candidate_pnrs": sorted(flight_bucket_candidate_pnrs),
        "parser_pnrs": sorted(parser_pnrs),
        "json_subject_pnrs": sorted(subject_pnrs),
        "markdown_subject_pnrs": sorted(markdown_subject_pnrs),
        "explicit_pnrs": sorted(explicit_pnrs),
        "artifact_union_pnrs": sorted(artifact_union),
    }


def extract_subject_pnrs(text: str) -> set[str]:
    pnrs: set[str] = set()
    for pattern in _PNR_SUBJECT_PATTERNS:
        for match in pattern.finditer(text or ""):
            pnr = _normal_artifact_pnr(match.group(1))
            if pnr:
                pnrs.add(pnr)
    return pnrs


def summarize_feedback(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    items = payload.get("items") or {}
    labels = Counter()
    for item in items.values():
        label = item.get("category") or item.get("suggested_category") or "unlabeled"
        labels[label] += 1
    return {
        "path": str(path),
        "items": len(items),
        "labels": dict(labels.most_common()),
    }


def summarize_jsonl(path: Path) -> dict[str, Any]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    failure_types = Counter(row.get("failure_type") or "unknown" for row in rows)
    senders = Counter(row.get("sender_domain") or "unknown" for row in rows)
    return {
        "path": str(path),
        "rows": len(rows),
        "message_ids": len({row.get("message_id") for row in rows if row.get("message_id")}),
        "failure_types": dict(failure_types.most_common()),
        "top_senders": dict(senders.most_common(10)),
    }


def summarize_fixture_dir(path: Path) -> dict[str, Any]:
    fixtures = [item for item in path.glob("*.json") if not item.name.startswith("_")]
    senders = Counter(item.name.split("__", 1)[0] for item in fixtures)
    return {
        "path": str(path),
        "fixtures": len(fixtures),
        "top_fixture_senders": dict(senders.most_common(10)),
    }


def render_markdown_report(report: dict[str, Any]) -> str:
    saved = report["saved_segments"]
    audit = report["audit_results"]
    artifact_pnrs = report.get("artifact_pnrs") or {}
    feedback = report["feedback"]
    failures = report["parser_failures"]
    failed_sync = report["failed_sync"]
    discovery = report["current_discovery"]
    lines = [
        "# Flight Import Baseline Report",
        "",
        "## Saved Snapshot",
        "",
        f"- Saved segments: {saved.get('segments', 0)}",
        f"- Saved trips: {saved.get('trips', 0)}",
        f"- Saved PNRs: {saved.get('pnrs', 0)}",
    ]
    if saved.get("error"):
        lines.append(f"- Snapshot extraction: {saved['error']}")
    lines.extend(
        [
            "",
            "## Audit Evidence",
            "",
            f"- Audit scanned: {audit['scanned']}",
            f"- Audit parsed emails: {audit['parsed_emails']}",
            f"- Audit parsed segments: {audit['parsed_segments']}",
            f"- Audit artifact rows with PNR comparison: {artifact_pnrs.get('audit_rows', 0)}",
            f"- JSON candidate PNRs: {len(artifact_pnrs.get('candidate_pnrs', []))}",
            f"- Flight-bucket candidate PNRs: {len(artifact_pnrs.get('flight_bucket_candidate_pnrs', []))}",
            f"- Parser PNRs in audit JSON: {len(artifact_pnrs.get('parser_pnrs', []))}",
            f"- JSON subject-derived PNRs: {len(artifact_pnrs.get('json_subject_pnrs', []))}",
            f"- Markdown subject-derived PNRs: {len(artifact_pnrs.get('markdown_subject_pnrs', []))}",
            f"- Artifact explicit PNR union: {len(artifact_pnrs.get('explicit_pnrs', []))}",
            f"- Artifact all-source PNR union: {len(artifact_pnrs.get('artifact_union_pnrs', []))}",
            f"- Human feedback items: {feedback['items']}",
            f"- Feedback labels: {json.dumps(feedback['labels'], sort_keys=True)}",
            f"- Parser-failure rows: {failures['rows']} across {failures['message_ids']} message ids",
            f"- Frozen regression fixtures: {report['fixtures']['fixtures']}",
            "",
            "## Discovery Reference",
            "",
            "- GitHub HEAD reference tiers: incremental_precise, initial_broad_recent, exhaustive_backfill",
            f"- Current plan tiers: {', '.join(discovery['tiers'])}",
            f"- Current plan query count: {discovery['queries']}",
            "",
            "## Failed Sync Regression",
            "",
            f"- Scanned: {failed_sync['scanned']}",
            f"- Parsed emails: {failed_sync['parsed_emails']}",
            f"- Saved segments: {failed_sync['saved_segments']}",
        ]
    )
    for tier, stats in failed_sync["tiers"].items():
        lines.append(f"- `{tier}`: {json.dumps(stats, sort_keys=True)}")
    return "\n".join(lines) + "\n"


def _none_if_pg_null(value: str) -> str | None:
    return None if value == r"\N" else value


def _normal_artifact_pnr(value: Any) -> str | None:
    normalized = "".join(str(value or "").upper().split())
    if not (5 <= len(normalized) <= 8):
        return None
    if not normalized.isalnum():
        return None
    if normalized in _INVALID_ARTIFACT_PNRS:
        return None
    return normalized
