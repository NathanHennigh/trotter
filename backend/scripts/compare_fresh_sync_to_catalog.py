"""Compare the current saved flight graph to the private catalog export.

This is a read-only post-sync report for fresh Gmail import validation.
It classifies mismatches so parser misses, PNR aliases, sparse context emails,
catalog artifacts, and through-flight overparses do not all look the same.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from app.db import SessionLocal  # noqa: E402
from app.models import Segment, Trip, User  # noqa: E402


INVALID_PNRS = {"EMAIL", "LETTER", "POLICY"}


@dataclass(frozen=True)
class SegmentView:
    dep_airport: str
    arr_airport: str
    dep_date: str
    flight_number: str | None
    pnr: str | None
    source: str | None = None
    aliases: tuple[str, ...] = ()

    @property
    def route_flight_key(self) -> tuple[str, str, str, str | None]:
        return (self.dep_airport, self.arr_airport, self.dep_date, self.flight_number)

    @property
    def route_date_key(self) -> tuple[str, str, str]:
        return (self.dep_airport, self.arr_airport, self.dep_date)

    @property
    def exact_key(self) -> tuple[str, str, str, str | None, str | None]:
        return (*self.route_flight_key, self.pnr)

    @property
    def pnr_set(self) -> set[str]:
        return {value for value in [self.pnr, *self.aliases] if value}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference-export", type=Path, required=True)
    parser.add_argument("--user-email", required=True)
    parser.add_argument("--json-out", type=Path, default=Path("scripts/.flight_shape_corpus/fresh_sync_comparison.json"))
    parser.add_argument("--md-out", type=Path, default=Path("scripts/.flight_shape_corpus/fresh_sync_comparison.md"))
    args = parser.parse_args()

    expected = load_reference(args.reference_export)
    current = load_current_segments(args.user_email)
    report = compare_segments(expected, current)
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    args.md_out.write_text(render_markdown(report), encoding="utf-8")
    print(render_markdown(report), end="")
    print(f"\nJSON:   {args.json_out.resolve()}")
    print(f"Report: {args.md_out.resolve()}")


def load_reference(path: Path) -> list[SegmentView]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = []
    for row in payload.get("segments") or []:
        if row.get("mode") != "flight":
            continue
        rows.append(
            SegmentView(
                dep_airport=row.get("dep_airport") or "",
                arr_airport=row.get("arr_airport") or "",
                dep_date=_date_key(row.get("dep_time")),
                flight_number=_normalize_flight_number(row.get("flight_number")),
                pnr=_normalize_pnr(row.get("pnr")),
                source=(row.get("meta_json") or {}).get("source"),
                aliases=tuple(_meta_aliases(row.get("meta_json") or {})),
            )
        )
    return rows


def load_current_segments(user_email: str) -> list[SegmentView]:
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == user_email).first()
        if not user:
            raise SystemExit(f"No user found for {user_email!r}")
        rows = (
            db.query(Segment)
            .join(Trip)
            .filter(Trip.user_id == user.id, Segment.mode == "flight")
            .all()
        )
        segments = []
        for row in rows:
            meta = row.meta_json or {}
            segments.append(
                SegmentView(
                    dep_airport=row.dep_airport or "",
                    arr_airport=row.arr_airport or "",
                    dep_date=_date_key(row.dep_time),
                    flight_number=_normalize_flight_number(row.flight_number),
                    pnr=_normalize_pnr(row.pnr),
                    source=meta.get("source"),
                    aliases=tuple(_meta_aliases(meta)),
                )
            )
        return segments
    finally:
        db.close()


def compare_segments(expected: list[SegmentView], current: list[SegmentView]) -> dict[str, Any]:
    current_exact = Counter(segment.exact_key for segment in current)
    expected_exact = Counter(segment.exact_key for segment in expected)
    current_route_flight = Counter(segment.route_flight_key for segment in current)
    expected_route_flight = Counter(segment.route_flight_key for segment in expected)
    current_pnrs = {pnr for segment in current for pnr in segment.pnr_set}
    expected_pnrs = {pnr for segment in expected for pnr in segment.pnr_set}

    missing = []
    for segment in expected:
        if current_exact[segment.exact_key] > 0:
            current_exact[segment.exact_key] -= 1
            continue
        classification = classify_missing(segment, current)
        missing.append({"segment": asdict(segment), "classification": classification})

    extras = []
    for segment in current:
        if expected_exact[segment.exact_key] > 0:
            expected_exact[segment.exact_key] -= 1
            continue
        extras.append({"segment": asdict(segment), "classification": classify_extra(segment, expected, current)})

    actionable_missing = [item for item in missing if item["classification"] == "true_parser_miss"]
    actionable_extras = [
        item
        for item in extras
        if item["classification"] in {"through_flight_overparse", "uncataloged_real_flight_or_false_positive"}
    ]
    route_flight_matches = sum((expected_route_flight & current_route_flight).values())
    exact_matches = len(expected) - len(missing)
    return {
        "summary": {
            "expected_segments": len(expected),
            "current_segments": len(current),
            "exact_matches": exact_matches,
            "route_date_flight_matches": route_flight_matches,
            "raw_missing": len(missing),
            "raw_extras": len(extras),
            "actionable_missing": len(actionable_missing),
            "actionable_extras": len(actionable_extras),
            "expected_pnrs": len(expected_pnrs),
            "current_pnrs_with_aliases": len(current_pnrs),
            "missing_pnrs_with_aliases": sorted(expected_pnrs - current_pnrs),
        },
        "missing_by_classification": dict(Counter(item["classification"] for item in missing)),
        "extras_by_classification": dict(Counter(item["classification"] for item in extras)),
        "missing": missing,
        "extras": extras,
    }


def classify_missing(segment: SegmentView, current: list[SegmentView]) -> str:
    if any(segment.route_flight_key == item.route_flight_key and segment.pnr_set & item.pnr_set for item in current):
        return "covered_by_pnr_alias"
    if any(segment.route_flight_key == item.route_flight_key for item in current):
        return "covered_by_same_route_flight"
    if _route_covered_by_chain(segment, current):
        return "covered_by_layover_chain_or_catalog_artifact"
    if any(segment.pnr and segment.pnr in item.pnr_set for item in current):
        return "sparse_checkin_context_or_catalog_scope"
    return "true_parser_miss"


def classify_extra(segment: SegmentView, expected: list[SegmentView], current: list[SegmentView]) -> str:
    if _route_covered_by_chain(segment, current, same_pnr_only=True):
        return "through_flight_overparse"
    if any(segment.route_flight_key == item.route_flight_key and segment.pnr_set & item.pnr_set for item in expected):
        return "pnr_alias_catalog_grouping"
    if any(segment.route_flight_key == item.route_flight_key for item in expected):
        return "pnr_alias_or_catalog_grouping"
    if any(segment.pnr and segment.pnr in item.pnr_set for item in expected):
        return "same_pnr_update_or_duplicate_evidence"
    return "uncataloged_real_flight_or_false_positive"

def _route_covered_by_chain(segment: SegmentView, segments: list[SegmentView], *, same_pnr_only: bool = False) -> bool:
    candidates = [
        item
        for item in segments
        if item is not segment
        and item.dep_date == segment.dep_date
        and item.dep_airport != item.arr_airport
        and (not same_pnr_only or bool(segment.pnr_set & item.pnr_set))
    ]
    adjacency: dict[str, set[str]] = defaultdict(set)
    for item in candidates:
        adjacency[item.dep_airport].add(item.arr_airport)
    stack = [segment.dep_airport]
    seen = set()
    while stack:
        airport = stack.pop()
        if airport == segment.arr_airport:
            return True
        if airport in seen:
            continue
        seen.add(airport)
        stack.extend(adjacency.get(airport, set()) - seen)
    return False


def render_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# Fresh Sync Catalog Comparison",
        "",
        f"- Expected segments: {summary['expected_segments']}",
        f"- Current segments: {summary['current_segments']}",
        f"- Exact route/date/flight/PNR matches: {summary['exact_matches']}",
        f"- Route/date/flight matches: {summary['route_date_flight_matches']}",
        f"- Raw unmatched catalog rows: {summary['raw_missing']}",
        f"- Raw extra saved rows: {summary['raw_extras']}",
        f"- Actionable missing segments: {summary['actionable_missing']}",
        f"- Actionable extra segments: {summary['actionable_extras']}",
        f"- Missing PNRs with aliases: {', '.join(summary['missing_pnrs_with_aliases']) or 'None'}",
        "",
        "## Missing Classifications",
    ]
    lines.extend(f"- `{key}`: {value}" for key, value in report["missing_by_classification"].items())
    lines.append("")
    lines.append("## Extra Classifications")
    lines.extend(f"- `{key}`: {value}" for key, value in report["extras_by_classification"].items())
    lines.append("")
    lines.append("## Missing Samples")
    for item in report["missing"][:30]:
        segment = item["segment"]
        lines.append(
            f"- `{item['classification']}` {segment['pnr'] or '-'} "
            f"{segment['flight_number'] or '-'} {segment['dep_airport']}->{segment['arr_airport']} {segment['dep_date']}"
        )
    lines.append("")
    lines.append("## Extra Samples")
    for item in report["extras"][:30]:
        segment = item["segment"]
        lines.append(
            f"- `{item['classification']}` {segment['pnr'] or '-'} "
            f"{segment['flight_number'] or '-'} {segment['dep_airport']}->{segment['arr_airport']} {segment['dep_date']} source={segment['source'] or '-'}"
        )
    return "\n".join(lines) + "\n"


def _meta_aliases(meta: dict[str, Any]) -> list[str]:
    aliases = []
    for value in meta.get("pnr_aliases") or []:
        normalized = _normalize_pnr(value)
        if normalized and normalized not in aliases:
            aliases.append(normalized)
    return aliases


def _date_key(value: Any) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    text = str(value or "")
    if not text:
        return ""
    return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()


def _normalize_flight_number(value: Any) -> str | None:
    if not value:
        return None
    normalized = "".join(str(value).upper().split())
    if len(normalized) >= 3 and normalized[:2].isalpha():
        return f"{normalized[:2]}{normalized[2:].lstrip('0') or '0'}"
    return normalized


def _normalize_pnr(value: Any) -> str | None:
    if not value:
        return None
    normalized = "".join(str(value).upper().split())
    if normalized in INVALID_PNRS:
        return None
    return normalized or None


if __name__ == "__main__":
    main()
