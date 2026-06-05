"""Render the recovery baseline for Gmail flight import changes."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.flight_query_v4 import build_discovery_plan
from app.services.import_baseline import (
    extract_segments_from_dump,
    render_markdown_report,
    summarize_audit_results,
    summarize_artifact_pnrs,
    summarize_feedback,
    summarize_fixture_dir,
    summarize_jsonl,
    summarize_saved_segments,
)
from app.services.parser import PARSER_VERSION


BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_DIR = BACKEND_DIR.parent


def build_report(dump_path: Path) -> dict:
    saved_rows, dump_error = extract_segments_from_dump(dump_path)
    saved = summarize_saved_segments(saved_rows)
    if dump_error:
        saved["error"] = dump_error

    state = SimpleNamespace(
        last_incremental_scan_at=None,
        backfill_cursor_before=None,
        backfill_complete=False,
        parser_version=PARSER_VERSION,
        updated_at=None,
    )
    discovery_plan = build_discovery_plan(
        state,
        now=datetime.now(timezone.utc),
        max_backfill_windows=1,
    )
    tiers = []
    for item in discovery_plan:
        if item.tier not in tiers:
            tiers.append(item.tier)

    return {
        "saved_segments": saved,
        "audit_results": summarize_audit_results(BACKEND_DIR / "scripts" / "flight_ai_audit_results.json"),
        "artifact_pnrs": summarize_artifact_pnrs(
            audit_paths=[
                BACKEND_DIR / "scripts" / "flight_ai_audit_results.json",
                BACKEND_DIR / "scripts" / "flight_ai_audit_results.travel.json",
                BACKEND_DIR / "scripts" / "flight_ai_audit_results.strong-nontravel.json",
            ],
            markdown_paths=[
                BACKEND_DIR / "scripts" / "flight_ai_audit_review_queue.md",
                BACKEND_DIR / "scripts" / "flight_ai_audit_review_queue.travel.md",
                BACKEND_DIR / "scripts" / "flight_ai_audit_review_queue.strong-nontravel.md",
            ],
        ),
        "feedback": summarize_feedback(BACKEND_DIR / "scripts" / "flight_ai_audit_feedback.json"),
        "parser_failures": summarize_jsonl(BACKEND_DIR / "scripts" / "flight_parser_failures.jsonl"),
        "fixtures": summarize_fixture_dir(BACKEND_DIR / "tests" / "fixtures" / "regressions"),
        "failed_sync": json.loads(
            (BACKEND_DIR / "scripts" / "flight_import_failed_sync_20260522.json").read_text(encoding="utf-8")
        ),
        "current_discovery": {
            "tiers": tiers,
            "queries": len(discovery_plan),
            "query_counts": {tier: sum(item.tier == tier for item in discovery_plan) for tier in tiers},
        },
        "paths": {
            "dump": str(dump_path),
            "repo": str(REPO_DIR),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dump-path",
        type=Path,
        default=BACKEND_DIR / "trotter-before-clean-import-20260521-131210.dump",
    )
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()

    report = build_report(args.dump_path)
    if args.as_json:
        print(json.dumps(report, indent=2, sort_keys=True))
        return
    print(render_markdown_report(report), end="")


if __name__ == "__main__":
    main()
