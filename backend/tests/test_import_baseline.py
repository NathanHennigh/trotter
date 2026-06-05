from pathlib import Path

from app.services.import_baseline import (
    extract_subject_pnrs,
    parse_segment_copy,
    render_markdown_report,
    summarize_artifact_pnrs,
    summarize_feedback,
    summarize_saved_segments,
)


def test_parse_segment_copy_extracts_saved_segment_rows():
    rows = parse_segment_copy(
        "\n".join(
            [
                "COPY public.segments (id, trip_id, mode, dep_airport, arr_airport, dep_time, arr_time, airline, flight_number, pnr) FROM stdin;",
                "7\t3\tflight\tDFW\tNRT\t2025-01-01\t2025-01-02\tJL\tJL11\tABC123",
                "8\t3\tflight\tNRT\tSIN\t2025-01-02\t2025-01-02\tNH\tNH801\t\\N",
                r"\.",
            ]
        )
    )

    assert [row.segment_id for row in rows] == [7, 8]
    assert rows[0].dep_airport == "DFW"
    assert rows[1].pnr is None
    assert summarize_saved_segments(rows)["trips"] == 1
    assert summarize_saved_segments(rows)["pnr_values"] == ["ABC123"]


def test_feedback_summary_prefers_reviewed_category(tmp_path: Path):
    path = tmp_path / "feedback.json"
    path.write_text(
        '{"items":{"a":{"category":"yes_flight","suggested_category":"hotel"},"b":{"suggested_category":"reminder"}}}',
        encoding="utf-8",
    )

    summary = summarize_feedback(path)

    assert summary["items"] == 2
    assert summary["labels"] == {"yes_flight": 1, "reminder": 1}


def test_baseline_report_mentions_failed_sync_funnel():
    text = render_markdown_report(
        {
            "saved_segments": {"segments": 60, "trips": 12, "pnrs": 10},
            "audit_results": {"scanned": 232, "parsed_emails": 43, "parsed_segments": 60},
            "artifact_pnrs": {
                "audit_rows": 400,
                "candidate_pnrs": ["ABC123"],
                "flight_bucket_candidate_pnrs": ["ABC123"],
                "parser_pnrs": ["ABC123", "DEF456"],
                "json_subject_pnrs": ["DEF456"],
                "markdown_subject_pnrs": ["GHI789"],
                "explicit_pnrs": ["ABC123", "DEF456"],
                "artifact_union_pnrs": ["ABC123", "DEF456", "GHI789"],
            },
            "feedback": {"items": 267, "labels": {"yes_flight": 108}},
            "parser_failures": {"rows": 110, "message_ids": 100},
            "fixtures": {"fixtures": 29},
            "current_discovery": {"tiers": ["incremental_precise", "exhaustive_backfill"], "queries": 3},
            "failed_sync": {
                "scanned": 446,
                "parsed_emails": 7,
                "saved_segments": 6,
                "tiers": {"fast_known_senders": {"meta_skip": 227}},
            },
        }
    )

    assert "Saved segments: 60" in text
    assert "Artifact all-source PNR union: 3" in text
    assert "GitHub HEAD reference tiers" in text
    assert '"meta_skip": 227' in text


def test_artifact_pnrs_compare_explicit_and_subject_sources(tmp_path: Path):
    audit_path = tmp_path / "audit.json"
    markdown_path = tmp_path / "queue.md"
    audit_path.write_text(
        """
        {
          "scanned": {
            "a": {
              "audit_bucket": "parsed_ok",
              "candidate_pnr": "ABC123",
              "subject": "Boarding pass for confirmation DEF456",
              "parser_flights": [{"pnr": "GHI789"}]
            },
            "b": {
              "audit_bucket": "other_travel",
              "candidate_pnr": "WITHIN",
              "subject": "Marketing booking DETAILS",
              "parser_flights": []
            }
          }
        }
        """,
        encoding="utf-8",
    )
    markdown_path.write_text("- [Booking JKL012: Get your boarding pass](https://example.test)\n", encoding="utf-8")

    summary = summarize_artifact_pnrs(audit_paths=[audit_path], markdown_paths=[markdown_path])

    assert summary["candidate_pnrs"] == ["ABC123"]
    assert summary["flight_bucket_candidate_pnrs"] == ["ABC123"]
    assert summary["parser_pnrs"] == ["GHI789"]
    assert summary["json_subject_pnrs"] == ["DEF456"]
    assert summary["markdown_subject_pnrs"] == ["JKL012"]
    assert extract_subject_pnrs("Your purchase receipt - MNO345") == {"MNO345"}
