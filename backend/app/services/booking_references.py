"""Strict booking-reference fields shared by route and traveler extraction.

A reference is a complete labeled field, never a token prefix from a URL,
compound agency identifier, or ordinary booking prose. Positions refer to the
original text so callers can keep traveler evidence inside its booking section.
"""
from __future__ import annotations

from dataclasses import dataclass
import re


_REFERENCE_LABEL_HINT = re.compile(r"record|confirmation|booking|reservation|pnr", re.I)


_LABEL = re.compile(
    r"\b(?P<label>record[ \t]+locator|(?:airline[ \t]+)?confirmation[ \t]+(?:codes?|numbers?)|"
    r"(?:airline[ \t]+)?(?:booking|reservation)[ \t]+(?:reference|code|number|id)|"
    r"airline[ \t]+confirmation|pnr|(?:booking|confirmation)(?=[ \t]*[:#-]|[ \t]+[A-Z0-9]{5,8}\b|[ \t]*$))\b",
    re.I,
)
_CARRIERS = re.compile(
    r"(?:UAL|United(?: Airlines)?|American(?: Airlines)?|Southwest(?: Airlines)?|"
    r"Delta(?: Air Lines| Airlines)?|Alaska(?: Airlines)?|Spirit(?: Airlines)?|"
    r"Frontier(?: Airlines)?|JetBlue|Allegiant(?: Air)?|Sun Country(?: Airlines)?|"
    r"Royal Air Maroc|British Airways|Air Canada|Air France|Lufthansa|Finnair|"
    r"ANA|All Nippon Airways|EVA Air|Iberia|AirAsia|Volaris|Aeromexico)", re.I,
)
_URL = re.compile(r"(?:<https?://[^>]+>|https?://[^\s<>]+)", re.I)
_VALUE = re.compile(r"(?P<code>[A-Z0-9]{5,8})(?![A-Z0-9_/-])", re.I)
_NEXT_FIELD = re.compile(
    r"(?:(?:your\s+)?(?:complete\s+)?itinerary\b|flight\s+(?:\d|to\b|details\b|information\b|[A-Z0-9]{2}\d)|"
    r"(?:original|new)\s+schedule\b|(?:outbound|return)\s+to\b|capital\s+one\s+travel\b|"
    r"date\s+departs\b|passengers?\s+\d{1,2}\b|(?:mon|tue|wed|thu|fri|sat|sun)(?:day|sday|nesday|rsday|urday)?[, .]+\d|"
    r"(?:mon|tue|wed|thu|fri|sat|sun)(?:day|sday|nesday|rsday|urday)?[, .]+[A-Z]{3,9}\s+\d|"
    r"[A-Z]{3}\s+[A-Z]{3}\s+flight\b|[A-Z][A-Z ,./'-]{1,65}\([A-Z]{3}\))", re.I,
)


def _next_field(value: str) -> bool:
    if _LABEL.match(value) or _NEXT_FIELD.match(value):
        return True
    carrier = _CARRIERS.match(value)
    return bool(carrier and re.match(r"\s+(?:airways\b|flight\b|\d|record locator\b)", value[carrier.end():], re.I))


@dataclass(frozen=True)
class BookingReference:
    code: str
    label: str
    start: int
    end: int
    line: int
    airline: str | None = None
    priority: int = 2


def _field_value(value: str) -> tuple[str, str | None] | None:
    value = value.strip(" \t*|:#")
    carrier = None
    # A carrier can be the label of the next cell, but a new reference field
    # cannot be consumed as an airline or as this field's missing value.
    carrier_match = re.match(r"(.{1,60}?)\s*[:#|]\s*(.*)$", value)
    if carrier_match and _CARRIERS.fullmatch(carrier_match[1].strip()):
        carrier, value = carrier_match[1].strip(), carrier_match[2].strip()
    match = _VALUE.match(value)
    # These are transport/notification labels, not locator values. In
    # particular, "airline confirmation email" is a document description.
    if not match or match["code"].upper() in {"EMAIL", "HTTPS"}:
        return None
    tail = value[match.end():].strip(" \t*")
    if tail:
        if tail.startswith("("):
            suffix = re.match(r"\(([^)]+)\)(.*)$", tail)
            if not suffix or not _CARRIERS.fullmatch(suffix[1].strip()):
                return None
            carrier, tail = suffix[1].strip(), suffix[2].strip()
        # A field terminates at punctuation/a column or the next explicit
        # field. Free prose following a word is not a booking reference.
        if tail and not (tail.startswith(("|", ";", ".", ",")) or _next_field(tail)):
            return None
    return match["code"].upper(), carrier


def extract_reference_fields(text: str) -> list[BookingReference]:
    """Read labeled values, skipping only blank lines and URL-only wrappers.

    A bare ``Confirmation`` heading needs a mixed/digit code or an explicit
    carrier suffix. More specific fields accept all-letter and numeric codes.
    """
    if type(text) is str and not _REFERENCE_LABEL_HINT.search(text):
        return []
    lines = text.splitlines(keepends=True)
    offsets, offset = [], 0
    for line in lines:
        offsets.append(offset)
        offset += len(line)
    fields: list[BookingReference] = []
    for line_index, raw_line in enumerate(lines):
        line = raw_line.rstrip("\r\n")
        if type(text) is str and not _REFERENCE_LABEL_HINT.search(line):
            continue
        # Flattened airline tables can merge adjacent headings into
        # "Booking Code Meals". A row made entirely of itinerary column
        # headings contains no locator value, even though MEALS is 5 letters.
        columns = {re.sub(r"\s+", " ", cell).strip().lower() for cell in line.split("|")}
        if ({"carrier", "flight number", "departing", "arriving"} <= columns
                and columns <= {"carrier", "flight number", "departing", "arriving",
                                "booking code", "booking code meals", "meals"}):
            continue
        # Never discover field names inside a URL's path/query parameters.
        masked = _URL.sub(lambda m: " " * len(m[0]), line)
        for match in _LABEL.finditer(masked):
            label = re.sub(r"\s+", " ", match["label"]).lower()
            # Plural codes/numbers describes a heading, not a locator whose
            # value is the word CODES or NUMBERS. Carrier-scoped cells are read
            # separately below; explicitly labeled all-letter values remain valid.
            if label in {"confirmation codes", "airline confirmation codes",
                         "confirmation numbers", "airline confirmation numbers"}:
                continue
            # MIME text can wrap this one explicit two-word heading. Only an
            # adjacent standalone Airline heading qualifies; do not carry an
            # earlier carrier/heading through unrelated fields or prose.
            if label == "confirmation" and not line[:match.start()].strip():
                for previous in range(line_index - 1, max(-1, line_index - 4), -1):
                    heading = lines[previous].strip()
                    if not heading:
                        continue
                    if heading.casefold() == "airline":
                        label = "airline confirmation"
                    break
            remainder = line[match.end():]
            # A destination-bearing flight-purchase title names a document,
            # not a locator field. Require its complete city/airport shape;
            # all-letter references (including city names) remain valid fields.
            if (label == "confirmation"
                    and re.search(r"\bflight[ \t]+(?:purchase[ \t]+)?$", line[:match.start()], re.I)
                    and re.match(r"^[ \t]*[-–—][ \t]*(?:[^\W\d_]|[ .'’-]){3,80},[^|;\n]*"
                                 r"\([A-Z]{3}[ \t]*[-–—][^)]{2,80}\)[ \t]*[-–—][^|;\n]+"
                                 r"[ \t]*[-–—][ \t]*\(itinerary[ \t]*#[ \t]*\d{8,}\)[ \t]*$", remainder, re.I)):
                continue
            # A preheader can fuse "for your" into FORYOUR. Its following
            # flight/code text is prose continuing this label, not a value
            # followed by another flight field. Delimited all-letter locators
            # remain valid, including the same literal letters.
            if re.match(r"\s+for\s*your\s+flight\b", remainder, re.I):
                continue
            separator = re.match(r"\s*(?:is\b\s*)?[:#*|\-\s]*", remainder, re.I)
            value = remainder[separator.end():].strip()
            value_line = line_index
            # The linked code in plain-text MIME frequently becomes
            # 'Confirmation code:\nhttps://tracking/...\nABC123'.
            if not value or not _URL.sub("", value).strip(" <>[]()\t*"):
                value = ""
                for following in range(line_index + 1, min(len(lines), line_index + 12)):
                    candidate = lines[following].strip(" \t\r\n*")
                    if not candidate or not _URL.sub("", candidate).strip(" <>[]()\t*"):
                        continue
                    value, value_line = candidate, following
                    break
            parsed = _field_value(value)
            if not parsed:
                continue
            code, carrier = parsed
            bare = label in {"booking", "confirmation"}
            explicit_separator = bool(re.match(r"\s*[:#-]", remainder))
            if bare and not explicit_separator and code.isalpha() and not carrier:
                continue
            prefix = line[:match.start()].strip(" *|:#")
            prefix_carrier = next((m[0] for m in _CARRIERS.finditer(prefix)
                                   if not prefix[m.end():].strip()), None)
            carrier = carrier or prefix_carrier
            priority = 0 if (label == "airline confirmation" or
                             (prefix_carrier and ("confirmation" in label or label == "record locator"))) else 2
            fields.append(BookingReference(code, label, offsets[line_index] + match.start(),
                offsets[value_line] + len(lines[value_line].rstrip("\r\n")), line_index,
                carrier, priority))
        # Compact agency confirmation tables can lose their line breaks in
        # HTML extraction. The carrier is still an explicit field heading.
        for table in re.finditer(r"\bconfirmation\s+(?:codes?|numbers)\s+", masked, re.I):
            tail = line[table.end():]
            carrier = _CARRIERS.match(tail)
            if not carrier or not re.match(r"[\s:#]", tail[carrier.end():]):
                continue
            parsed = _field_value(tail[carrier.end():])
            if parsed:
                fields.append(BookingReference(parsed[0], "confirmation code", offsets[line_index] + table.start(),
                    offsets[line_index] + len(line), line_index, carrier[0], 0))
        # Preserve the same carrier scope when the heading, carrier and
        # reference occupy separate visible cells. Never scan past a nonblank
        # intervening heading or prose to find a plausible code elsewhere.
        table = re.search(r"\bconfirmation\s+(?:codes?|numbers)\s*:?\s*$", masked, re.I)
        if table:
            cells = [(index, lines[index].strip())
                     for index in range(line_index + 1, min(len(lines), line_index + 7))
                     if lines[index].strip()]
            # A visible carrier cell can keep its own value on the same line:
            # "Airline Confirmation Numbers\nAmerican Airlines: ABC123".
            inline = _field_value(cells[0][1]) if cells else None
            if inline and inline[1]:
                value_line = cells[0][0]
                fields.append(BookingReference(inline[0], "confirmation code",
                    offsets[line_index] + table.start(),
                    offsets[value_line] + len(lines[value_line].rstrip("\r\n")),
                    line_index, inline[1], 0))
            elif len(cells) >= 2 and _CARRIERS.fullmatch(cells[0][1]):
                value_line, value = cells[1]
                parsed = _field_value(value)
                if parsed:
                    fields.append(BookingReference(parsed[0], "confirmation code",
                        offsets[line_index] + table.start(),
                        offsets[value_line] + len(lines[value_line].rstrip("\r\n")),
                        line_index, cells[0][1], 0))
    return fields


def extract_primary_reference(text: str) -> str | None:
    fields = extract_reference_fields(text)
    return min(fields, key=lambda field: (field.priority, field.start)).code if fields else None
