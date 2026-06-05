from __future__ import annotations

from argparse import Namespace

from scripts.evaluate_shape_corpus import (
    ExpectedSegment,
    ParsedSegment,
    catalog_summary_route_covered,
    check_thresholds,
    classify_missing_segment,
    visible_expected_signals,
)


def _segment(**overrides) -> ExpectedSegment:
    values = {
        "pnr": "ABC123",
        "airline": "WN",
        "flight_number": "WN1783",
        "dep_airport": "STL",
        "arr_airport": "EWR",
        "dep_time": "2019-01-01 08:30:00",
        "arr_time": "2019-01-01 11:45:00",
        "trip_id": 1,
        "trip_title": "Test Trip",
        "source_message_id": "message-1",
    }
    values.update(overrides)
    return ExpectedSegment(**values)


def test_visible_expected_signals_detects_flight_route_and_pnr() -> None:
    text = "Confirmation ABC123 Flight WN 1783 STL to EWR Tuesday, 01/01/2019"

    signals = visible_expected_signals(_segment(), text.upper())

    assert "flight_number" in signals
    assert "route" in signals
    assert "pnr" in signals


def test_classify_missing_marks_visible_parser_miss() -> None:
    segment = _segment()

    result = classify_missing_segment(
        segment,
        record={"pnrs": ["ABC123"]},
        evidence_text="Flight WN1783 Tuesday, 01/01/2019 departs STL 8:30 AM and arrives EWR ABC123",
    )

    assert result["reason"] == "visible_parser_miss"


def test_classify_missing_does_not_treat_undirected_airports_as_visible() -> None:
    segment = _segment(
        airline="AA",
        flight_number="AA1390",
        dep_airport="IAD",
        arr_airport="DFW",
        dep_time="2024-06-27 17:13:00",
        arr_time="2024-06-27 19:43:00",
        pnr="OVMOJR",
    )

    result = classify_missing_segment(
        segment,
        record={"pnrs": ["OVMOJR"]},
        evidence_text="Confirmation OVMOJR Monday, June 24, 2024 DFW 12:19 PM AA 1390 IAD 4:23 PM",
    )

    assert result["reason"] == "pnr_sibling_or_catalog_scope"
    assert "flight_number" in result["visible_signals"]
    assert "route" not in result["visible_signals"]


def test_classify_missing_marks_pnr_sibling_when_not_visible() -> None:
    segment = _segment()

    result = classify_missing_segment(
        segment,
        record={"pnrs": ["ABC123"]},
        evidence_text="This email only contains a different leg for ABC123.",
    )

    assert result["reason"] == "pnr_sibling_or_catalog_scope"


def test_catalog_summary_route_is_not_actionable_when_connection_legs_exist() -> None:
    segment = _segment(flight_number=None, dep_airport="DAL", arr_airport="LGA")
    parsed = [
        ParsedSegment("ABC123", "WN", "WN1220", "DAL", "MSY", "2019-01-01T08:15:00+00:00", None, "shape"),
        ParsedSegment("ABC123", "WN", "WN393", "MSY", "LGA", "2019-01-01T11:10:00+00:00", None, "shape"),
    ]

    result = classify_missing_segment(
        segment,
        record={"message_id": "message-1", "pnrs": ["ABC123"]},
        evidence_text="DAL to LGA ABC123 Tuesday, 01/01/2019",
        parsed=parsed,
    )

    assert catalog_summary_route_covered(segment, parsed)
    assert result["reason"] == "catalog_summary_route"


def test_checkin_sibling_missing_is_not_actionable_parser_miss() -> None:
    segment = _segment(source_message_id="confirmation-message")

    result = classify_missing_segment(
        segment,
        record={"message_id": "checkin-message", "pnrs": ["ABC123"], "shape": "checkin_or_reminder"},
        evidence_text="Check in for your flight ABC123",
        parsed=[],
    )

    assert result["reason"] == "checkin_single_leg_expected"


def test_check_thresholds_reports_all_failures() -> None:
    summary = {
        "error_count": 1,
        "seconds": 130.0,
        "slowest": [{"seconds": 12.0}],
        "match_rate": 0.9,
        "missing_segments": 20,
        "extra_segments": 101,
    }
    args = Namespace(
        max_errors=0,
        max_seconds=120.0,
        max_message_seconds=10.0,
        min_match_rate=0.95,
        max_missing=16,
        max_extras=100,
    )

    failures = check_thresholds(summary, args)

    assert len(failures) == 6
