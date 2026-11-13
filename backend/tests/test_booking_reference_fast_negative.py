"""Necessary-label shortcuts preserve reference fields and caller behavior."""
from dataclasses import asdict

import pytest

from app.services import booking_references as refs
from app.services.parser import _extract_pnr, _extract_pnr_aliases


class NoDetailedScan:
    def __getattr__(self, name):
        raise AssertionError(f"Unexpected detailed reference scan: {name}")


@pytest.mark.parametrize("text", [
    "", "Weather and news", "\n\t  ", "A flight from AAA to BBB",
    "<p>Save on your next trip!</p>", "Unrelated newsletter text\n" * 500,
])
def test_no_label_avoids_detailed_reference_work(monkeypatch, text):
    monkeypatch.setattr(refs, "_LABEL", NoDetailedScan())
    monkeypatch.setattr(refs, "_URL", NoDetailedScan())
    monkeypatch.setattr(refs, "re", NoDetailedScan())
    assert refs.extract_reference_fields(text) == []
    assert refs.extract_primary_reference(text) is None


@pytest.mark.parametrize("newline", ["\n", "\r\n", "\u2028"])
def test_unlabelled_lines_avoid_column_work_without_moving_offsets(monkeypatch, newline):
    real_re = refs.re
    normalized = []

    class RecordingRe:
        def __getattr__(self, name):
            return getattr(real_re, name)

        def sub(self, pattern, replacement, value, *args, **kwargs):
            normalized.append(value)
            return real_re.sub(pattern, replacement, value, *args, **kwargs)

    monkeypatch.setattr(refs, "re", RecordingRe())
    unrelated = [f"Unrelated newsletter row {index}" for index in range(100)]
    prefix = newline.join(unrelated) + newline
    field_line = "Airline confirmation: OWN123"
    text = prefix + field_line + newline + "Final unrelated line"
    fields = refs.extract_reference_fields(text)
    assert [asdict(field) for field in fields] == [{
        "code": "OWN123", "label": "airline confirmation", "start": len(prefix),
        # Existing offsets remove CR/LF, retaining other splitlines separators.
        "end": len(prefix) + len(field_line) + (1 if newline == "\u2028" else 0),
        "line": 100, "airline": None, "priority": 0,
    }]
    assert not set(unrelated + ["Final unrelated line"]) & set(normalized)


@pytest.mark.parametrize("label", [
    "Confirmation code", "CONFIRMATION CODE", "Confİrmation code",
    "Confırmation code", "BooKing reference", "Reſervation number",
    "Record locator", "pNr",
])
def test_unicode_case_matching_keeps_printed_reference(label):
    text = f"{label}: A1B2C3"
    fields = refs.extract_reference_fields(text)
    assert len(fields) == 1 and fields[0].code == "A1B2C3"
    assert fields[0].start == 0 and fields[0].end == len(text)
    assert refs.extract_primary_reference(text) == _extract_pnr(text) == "A1B2C3"


@pytest.mark.parametrize("newline", ["\n", "\r\n", "\v", "\u2028"])
def test_wrapped_field_retains_carrier_and_value_lookahead(newline):
    lines = ["Unrelated heading", "Airline", "confirmation", "",
             "<https://example.test/booking?pnr=BAD123>", "OWN123", "Passengers"]
    text = newline.join(lines)
    fields = refs.extract_reference_fields(text)
    if newline in {"\v", "\u2028"}:
        # These separators remain on the raw heading in the existing grammar.
        # This optimization must not broaden bare-heading recognition.
        assert fields == []
        assert _extract_pnr_aliases(text, primary="OTHER1") == []
        return
    assert len(fields) == 1
    field = fields[0]
    assert field.code == "OWN123" and field.label == "airline confirmation"
    assert field.priority == 0 and field.line == 2
    assert field.start == text.index("confirmation")
    assert field.end == text.index("OWN123") + 6
    assert _extract_pnr_aliases(text, primary="OTHER1") == ["OWN123"]


@pytest.mark.parametrize("label", [
    "Record locator", "Confirmation code", "Booking reference", "Reservation number",
    "PNR", "Airline confirmation", "Your confirmation number", "Booking ID",
])
def test_each_emitting_label_family_retains_value_and_priority(label):
    text = f"{label}: FIRST1\nAirline confirmation: SECOND2"
    fields = refs.extract_reference_fields(text)
    assert [field.code for field in fields] == ["FIRST1", "SECOND2"]
    expected = "FIRST1" if label == "Airline confirmation" else "SECOND2"
    assert refs.extract_primary_reference(text) == _extract_pnr(text) == expected
    assert set(_extract_pnr_aliases(text, primary=expected)) == ({"FIRST1", "SECOND2"} - {expected})


@pytest.mark.parametrize("url", [
    "https://example.test/booking/ABC123", "https://example.test/?pnr=ABC123",
    "https://example.test/confirmation/ABC123", "<https://example.test/reservation/ABC123>",
])
def test_hint_inside_url_never_creates_reference(url):
    assert refs.extract_reference_fields(url) == []
    assert refs.extract_primary_reference(url) is None


class AlternateLines(str):
    def splitlines(self, keepends=False):
        return ["Airline confirmation: OWN123"]


class StringLike:
    def splitlines(self, keepends=False):
        return ["Airline confirmation: OWN123"]


@pytest.mark.parametrize("value", [AlternateLines("unrelated"), StringLike()])
def test_nonexact_strings_keep_existing_splitlines_contract(value):
    fields = refs.extract_reference_fields(value)
    assert len(fields) == 1 and fields[0].code == "OWN123"
    assert fields[0].priority == 0


@pytest.mark.parametrize("value, error", [(None, AttributeError), (7, AttributeError), (b"text", TypeError)])
def test_invalid_input_errors_are_not_silently_converted_to_empty(value, error):
    with pytest.raises(error):
        refs.extract_reference_fields(value)
