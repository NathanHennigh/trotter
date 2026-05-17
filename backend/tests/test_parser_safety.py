"""Lint-style safety checks for parser regex patterns.

Catastrophic backtracking is the dominant performance failure mode of the
parser. The classic shape is multiple unbounded ``.*?`` (or ``.+?``) inside a
single ``re.compile`` block that also has ``re.DOTALL``. To prevent regressions,
this test parses parser.py and asserts every DOTALL pattern uses bounded
quantifiers like ``.{0,N}?`` instead of raw ``.*?``.
"""

from __future__ import annotations

import re
from pathlib import Path

PARSER_PATH = Path(__file__).resolve().parents[1] / "app" / "services" / "parser.py"


def _iter_dotall_compile_bodies():
    """Yield (line_number, var_name, body_text) for every DOTALL re.compile in parser.py."""
    text = PARSER_PATH.read_text(encoding="utf-8")
    cursor = 0
    while True:
        idx = text.find("re.compile(", cursor)
        if idx < 0:
            return
        line_start = text.rfind("\n", 0, idx) + 1
        prefix = text[line_start:idx]
        var_name = prefix.split("=")[0].strip() if "=" in prefix else "<anonymous>"

        body_start_match = re.search(r"(?:r|rf)\"{3}", text[idx:idx + 200])
        if not body_start_match:
            cursor = idx + 1
            continue
        body_start = idx + body_start_match.end()
        body_end = text.find('"""', body_start)
        if body_end < 0:
            cursor = idx + 1
            continue
        body = text[body_start:body_end]
        flags_segment = text[body_end + 3:body_end + 200]
        if "DOTALL" in flags_segment:
            line_number = text[:idx].count("\n") + 1
            yield line_number, var_name, body
        cursor = body_end + 3


def test_no_unbounded_lazy_quantifiers_in_dotall_regexes():
    """Every ``.*?`` and ``.+?`` inside a DOTALL pattern must be replaced with
    a bounded ``.{0,N}?`` or ``.{1,N}?`` form. Unbounded lazy quantifiers across
    DOTALL multi-line text cause catastrophic backtracking on real email bodies.
    """
    offenders: list[tuple[int, str, int, int]] = []
    for line, name, body in _iter_dotall_compile_bodies():
        # Strip bounded forms like .{0,200}? before counting raw .*? / .+?
        bounded_stripped = re.sub(r"\.\{[^}]+\}\??", "", body)
        raw_star = bounded_stripped.count(".*?")
        raw_plus = bounded_stripped.count(".+?")
        if raw_star or raw_plus:
            offenders.append((line, name, raw_star, raw_plus))

    if offenders:
        details = "\n".join(
            f"  parser.py:{line}  {name}  unbounded .*?={s}  .+?={p}"
            for line, name, s, p in offenders
        )
        raise AssertionError(
            "Found unbounded lazy quantifiers in DOTALL regexes. Replace each "
            "raw .*? or .+? with a bounded form like .{0,N}? or .{1,N}?:\n"
            + details
        )
