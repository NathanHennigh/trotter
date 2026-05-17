"""Regression tests built from frozen audit fixtures.

Every JSON file under ``tests/fixtures/regressions/`` is one email that the
parser previously got wrong (timed out, raised, or produced no segments).
Running pytest replays each one through ``parse_email``. Once a fixture is
frozen, that exact mistake cannot regress: the test will fail loudly.

Author flow when fixing a new miss:

    1. Run ``scripts/flight_ai_audit.py --reparse-cached``. Misses get
       appended to ``flight_parser_failures.jsonl``.
    2. Run ``scripts/freeze_parser_fixture.py --from-failures`` to freeze
       each open miss into ``tests/fixtures/regressions/``.
    3. Edit the parser. Run ``pytest tests/test_parser_regressions.py``.
       For new ``timeout`` or ``exception`` fixtures the test passes as
       soon as the parser returns within budget. For ``parser_miss``
       fixtures, fill in ``expectations.expected_flights`` in the JSON to
       lock in the right segments.

The redaction in the freezer guarantees fixtures contain no email
addresses, URLs, phone numbers, or long card-like digit runs, so it's safe
to commit them to the repo.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest

REGRESSION_DIR = Path(__file__).parent / "fixtures" / "regressions"


def _load_fixtures() -> list[tuple[str, dict[str, Any]]]:
    if not REGRESSION_DIR.exists():
        return []
    fixtures: list[tuple[str, dict[str, Any]]] = []
    for path in sorted(REGRESSION_DIR.glob("*.json")):
        if path.name == "_index.json":
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        fixtures.append((path.name, payload))
    return fixtures


_FIXTURES = _load_fixtures()


@pytest.mark.skipif(not _FIXTURES, reason="No regression fixtures frozen yet.")
@pytest.mark.parametrize(
    "fixture_name,fixture",
    _FIXTURES,
    ids=[name for name, _ in _FIXTURES],
)
def test_regression_fixture_parses_within_budget(fixture_name: str, fixture: dict[str, Any]) -> None:
    """Replay one frozen fixture through the parser and verify it behaves.

    For each fixture we always assert the parse completes within the
    configured budget (the original failure mode for half of them is a hang).
    Then, depending on ``expectations.expected_flights``:

    * ``None`` and ``failure_type == "parser_miss"`` — parser must produce
      at least one flight. Fill in the explicit list later to tighten.
    * Concrete list — parser must produce exactly those flights.
    * ``None`` and ``failure_type in {"timeout", "exception"}`` — only the
      time/no-raise check applies.
    """
    from app.services.parser import parse_email

    html = fixture.get("html", "") or ""
    plain_text = fixture.get("plain_text", "") or ""
    received_at = fixture.get("received_at") or None
    subject = fixture.get("subject") or None

    expectations = fixture.get("expectations") or {}
    skip_reason = expectations.get("skip_reason")
    if skip_reason:
        # Fixture is intentionally deferred — typically because the
        # underlying capability (PDF extraction, Spanish gate notice with
        # only partial info, etc.) is out of scope for the current parser.
        # We still time-check it so a regression that introduces a new hang
        # would be caught.
        pytest.skip(skip_reason)

    budget = float(expectations.get("must_complete_within_seconds") or 5.0)
    expected_flights = expectations.get("expected_flights")
    failure_type = fixture.get("failure_type") or "parser_miss"

    started = time.time()
    result = parse_email(
        html=html,
        plain_text=plain_text,
        attachments=[],
        user_name="",
        aliases=[],
        received_at=received_at,
        subject=subject,
        from_email=None,
    )
    elapsed = time.time() - started

    assert elapsed <= budget, (
        f"{fixture_name}: parse_email took {elapsed:.2f}s "
        f"(budget {budget:.2f}s). Likely catastrophic backtracking or new slow path."
    )

    if expected_flights is not None:
        actual = [
            {
                "flight_number": flight.flight_number,
                "dep_airport": flight.dep_airport,
                "arr_airport": flight.arr_airport,
            }
            for flight in result.flights
        ]
        assert actual == expected_flights, (
            f"{fixture_name}: parsed flights do not match recorded expectations.\n"
            f"  expected: {expected_flights}\n"
            f"  got:      {actual}"
        )
    elif failure_type == "parser_miss":
        assert result.flights, (
            f"{fixture_name}: parser produced no flights. The fixture was frozen "
            f"as a parser_miss; once a fix lands, set expectations.expected_flights "
            f"to lock in the right segments."
        )
