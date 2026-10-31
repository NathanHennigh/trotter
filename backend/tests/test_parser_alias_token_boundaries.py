import pytest
from app.services.parser import _extract_pnr, _extract_pnr_aliases


@pytest.mark.parametrize("value", ["12345-ZXCVBNM1234", "ABCDEF12345", "ABCDEF/XYZ123", "ABCDEF_XYZ123"])
def test_compound_or_long_reference_never_supplies_a_partial_extra_alias(value):
    assert _extract_pnr_aliases(f"Booking confirmation: {value}".upper(), primary="OWN123") == []


@pytest.mark.parametrize("carrier", ["Royal Air Maroc", "United Airlines", "Spirit Airlines", "American Airlines"])
def test_carrier_label_is_not_the_extra_booking_reference(carrier):
    text = f"Airline Reservation Code\n{carrier}: AIR123\nAgency booking reference AGY123"
    assert _extract_pnr_aliases(text.upper(), primary="AGY123") == ["AIR123"]


def test_explicit_all_letter_or_numeric_reference_stays_valid():
    assert _extract_pnr_aliases("Booking reference: ROYAL\nConfirmation code: 12345", primary="OWN123") == ["ROYAL", "12345"]


def test_new_field_after_a_valid_reference_does_not_replace_it():
    text = "Booking reference: ROYAL\nAirline name: Royal Air Maroc\nBooking reference: OTHER1"
    assert _extract_pnr_aliases(text.upper(), primary="OWN123") == ["ROYAL", "OTHER1"]


def test_mixed_agency_receipt_retains_primary_and_actual_airline_reference():
    text = "PNR: AGY123\nBooking confirmation: 12345-ZXCVBNM1234\nAirline Reservation Code\nRoyal Air Maroc: AIR123"
    assert _extract_pnr(text.upper()) == "AGY123"
    assert _extract_pnr_aliases(text.upper(), primary="AGY123") == ["AIR123"]


@pytest.mark.parametrize("value", ["ABCDEF/XYZ123", "ABCDEF12345", "ABCDEF-XYZ123", "", "\nBooking reference: OWN123"])
def test_invalid_or_missing_carrier_reference_never_falls_back_to_carrier_name(value):
    text = f"Airline Reservation Code\nRoyal Air Maroc: {value}"
    assert _extract_pnr_aliases(text.upper(), primary="OWN123") == []


@pytest.mark.parametrize("reference", ["AIR123", "ROYAL"])
@pytest.mark.parametrize("separator", ["\n", " "])
def test_valid_carrier_reference_followed_by_another_field(reference, separator):
    text = f"Airline Reservation Code\nRoyal Air Maroc: {reference}{separator}Booking reference: OWN123"
    assert _extract_pnr_aliases(text.upper(), primary="OWN123") == [reference]
