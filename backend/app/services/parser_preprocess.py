"""Fast text preparation for flight-email parsing.

The legacy parser wants plain text, but many transactional emails contain
large duplicated HTML tables. This module builds compact, parser-oriented text
forms so the expensive heuristic passes can work on evidence-rich text first.
"""

from __future__ import annotations

import re
import time
import unicodedata
import html as html_lib
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from bs4 import BeautifulSoup


@dataclass
class ParserTextBundle:
    clean_text: str
    table_text: str
    evidence_text: str
    full_text: str
    forwarded_text: str = ""
    is_forwarded: bool = False
    timings: dict[str, float] = field(default_factory=dict)
    stats: dict[str, Any] = field(default_factory=dict)


_NOISE_TAGS = {"script", "style", "noscript", "svg", "head", "meta", "link"}
_HIDDEN_STYLE = re.compile(r"(?:display\s*:\s*none|visibility\s*:\s*hidden)", re.IGNORECASE)
_SPACE_RE = re.compile(r"[ \t\r\f\v]+")
_BLANK_LINES_RE = re.compile(r"\n{3,}")
_FLIGHT_NUMBER_RE = re.compile(r"\b[A-Z0-9]{2}\s?\d{1,4}[A-Z]?\b")
_AIRPORT_ROUTE_RE = re.compile(
    r"\b[A-Z]{3}\b\s*(?:->|-->|-|to|TO)\s*\b[A-Z]{3}\b|\([A-Z]{3}\).*?\([A-Z]{3}\)"
)
_ANCHOR_RE = re.compile(
    r"""
    \b(?:
        record\s+locator|confirmation(?:\s+(?:code|number))?|booking\s+(?:reference|code|number)|
        reservation\s+(?:code|number)|airline\s+confirmation|pnr|flight|itinerary|depart(?:ure|ing)?|
        arriv(?:al|e|ing)?|boarding\s+pass|check[- ]?in|ticket|e-ticket|passenger|route|
        origin|destination|schedule\s+change|cancel(?:led|lation)?
    )\b
    """,
    re.IGNORECASE | re.VERBOSE,
)
_FORWARDED_MARKER_RE = re.compile(
    r"""
    (?:
        -{2,}\s*Forwarded\s+message\s*-{2,}|
        Begin\s+forwarded\s+message:|
        Forwarded\s+message|
        Original\s+Message
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)
_FORWARDED_HEADER_RE = re.compile(
    r"^\s*(From|Sent|Date|Subject|To):\s+.+", re.IGNORECASE | re.MULTILINE
)
_STRUCTURAL_REPEAT_RE = re.compile(
    r"""
    (?:
        [A-Z]{3}|
        \d{1,4}[A-Z]?|
        Flight|
        Depart(?:s|ure|ing)?|
        Arriv(?:es|al|ing)?|
        \d{1,2}:\d{2}\s*[AP]M|
        (?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)(?:day)?,?\s+
            (?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2}
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)


def prepare_parser_text(
    *,
    html: str,
    plain_text: str,
    subject: str | None = None,
    from_email: str | None = None,
) -> ParserTextBundle:
    timings: dict[str, float] = {}
    started = time.perf_counter()
    soup = _clean_soup(html) if html else None
    timings["html_clean"] = round(time.perf_counter() - started, 6)

    started = time.perf_counter()
    html_text = _normalize_text(soup.get_text(separator="\n") if soup else "")
    if html and len(html_text) < 100 and len(html) > 1000:
        html_text = _normalize_text(_raw_html_text_fallback(html))
    plain_clean = _normalize_text(plain_text or "")
    clean_source = "\n".join(
        part for part in [plain_clean, html_text] if part
    )
    clean_text = _dedupe_lines(clean_source, max_repeats=2, max_chars=80_000)
    timings["clean_text"] = round(time.perf_counter() - started, 6)

    started = time.perf_counter()
    table_text = _extract_table_text(soup) if soup else ""
    table_text = _dedupe_lines(table_text, max_repeats=1, max_chars=45_000)
    timings["table_text"] = round(time.perf_counter() - started, 6)

    started = time.perf_counter()
    header_context = "\n".join(part for part in [from_email or "", subject or ""] if part)
    full_text = "\n".join(part for part in [header_context, clean_text, table_text] if part)
    forwarded_text = _extract_forwarded_text(subject=subject, text=full_text)
    evidence_text = _build_evidence_text(forwarded_text or full_text)
    timings["evidence_text"] = round(time.perf_counter() - started, 6)

    return ParserTextBundle(
        clean_text=clean_text,
        table_text=table_text,
        evidence_text=evidence_text,
        full_text=_dedupe_lines(full_text, max_repeats=2, max_chars=100_000),
        forwarded_text=forwarded_text,
        is_forwarded=bool(forwarded_text),
        timings=timings,
        stats={
            "clean_chars": len(clean_text),
            "table_chars": len(table_text),
            "evidence_chars": len(evidence_text),
            "full_chars": len(full_text),
        },
    )


def _clean_soup(html: str) -> BeautifulSoup:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(_NOISE_TAGS):
        tag.decompose()
    for tag in soup.find_all(True):
        if tag.attrs is None:
            continue
        style = tag.get("style")
        if style and _HIDDEN_STYLE.search(str(style)):
            tag.decompose()
            continue
        if str(tag.get("aria-hidden", "")).lower() == "true":
            tag.decompose()
            continue
        classes = " ".join(str(item).lower() for item in tag.get("class", []) or [])
        if "hidden" in classes or "preheader" in classes:
            tag.decompose()
    return soup


def _extract_table_text(soup: BeautifulSoup) -> str:
    blocks: list[str] = []
    seen_rows: set[str] = set()
    for table in soup.find_all("table"):
        for row in table.find_all("tr"):
            cells = [
                _compact_space(cell.get_text(" "))
                for cell in row.find_all(["th", "td"])
                if _compact_space(cell.get_text(" "))
            ]
            if not cells:
                continue
            row_text = " | ".join(cells)
            if row_text in seen_rows:
                continue
            seen_rows.add(row_text)
            blocks.append(row_text)
    return "\n".join(blocks)


def _raw_html_text_fallback(value: str) -> str:
    value = re.sub(r"(?is)<script\b.*?</script>", " ", value)
    value = re.sub(r"(?is)<style\b.*?(?=</head>|<body\b|</style>)", " ", value)
    value = re.sub(r"(?i)<br\s*/?>", "\n", value)
    value = re.sub(r"(?i)</(?:tr|td|th|p|div|li|h[1-6]|table)>", "\n", value)
    value = re.sub(r"<[^>]+>", " ", value)
    return html_lib.unescape(value)


def _build_evidence_text(text: str) -> str:
    lines = [_compact_space(line) for line in text.splitlines() if _compact_space(line)]
    if len(lines) <= 260 and len(text) <= 24_000:
        return "\n".join(lines)

    anchor_indexes: set[int] = set()
    for index, line in enumerate(lines):
        upper = line.upper()
        has_confirmation_code = bool(
            re.search(
                r"\b(?:record\s+locator|confirmation|booking|reservation|pnr|itinerary)\b",
                line,
                re.IGNORECASE,
            )
            and re.search(r"\b[A-Z0-9]{5,8}\b", upper)
        )
        if (
            _ANCHOR_RE.search(line)
            or _FLIGHT_NUMBER_RE.search(upper)
            or _AIRPORT_ROUTE_RE.search(upper)
            or has_confirmation_code
        ):
            start = max(0, index - 5)
            end = min(len(lines), index + 8)
            anchor_indexes.update(range(start, end))

    if not anchor_indexes:
        return "\n".join(lines[:320])

    selected = [lines[index] for index in sorted(anchor_indexes)]
    return _dedupe_lines("\n".join(selected), max_repeats=2, max_chars=18_000)


def _extract_forwarded_text(*, subject: str | None, text: str) -> str:
    subject_says_forwarded = bool(re.match(r"\s*(?:fwd?|fw|re):", subject or "", re.IGNORECASE))
    marker = _FORWARDED_MARKER_RE.search(text)
    if marker:
        return text[marker.start() :]

    if not subject_says_forwarded:
        return ""

    matches = list(_FORWARDED_HEADER_RE.finditer(text))
    if len(matches) >= 2:
        return text[matches[0].start() :]
    return ""


def _dedupe_lines(text: str, *, max_repeats: int, max_chars: int) -> str:
    output: list[str] = []
    counts: Counter[str] = Counter()
    current_len = 0
    for raw_line in text.splitlines():
        line = _compact_space(raw_line)
        if not line:
            if output and output[-1]:
                output.append("")
            continue
        key = line.lower()
        if not _STRUCTURAL_REPEAT_RE.fullmatch(line):
            counts[key] += 1
            if counts[key] > max_repeats:
                continue
        current_len += len(line) + 1
        if current_len > max_chars:
            output.append("[TRUNCATED]")
            break
        output.append(line)
    return _BLANK_LINES_RE.sub("\n\n", "\n".join(output)).strip()


def _normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value or "")
    value = value.replace("\xa0", " ")
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = "\n".join(_SPACE_RE.sub(" ", line).strip() for line in value.splitlines())
    return _BLANK_LINES_RE.sub("\n\n", value).strip()


def _compact_space(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("\xa0", " ")).strip()
