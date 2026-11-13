"""Synthetic contracts for references shared by route and ownership parsing."""
import pytest

from app.services.booking_references import extract_primary_reference, extract_reference_fields
from app.services.parser import _extract_pnr, _extract_pnr_aliases


@pytest.mark.parametrize('connector', ['for your', 'foryour', 'FORyour'])
@pytest.mark.parametrize('label', ['Your reservation code', 'Confirmation code', 'Booking reference'])
def test_prose_continuation_before_flight_is_not_a_locator(label, connector):
    text=f'{label} {connector} flight Q7R8S9\nYour reservation code: Q7R8S9'
    assert {field.code for field in extract_reference_fields(text)} == {'Q7R8S9'}
    assert _extract_pnr(text.upper()) == 'Q7R8S9'
    assert _extract_pnr_aliases(text.upper(), primary='Q7R8S9') == []


@pytest.mark.parametrize('separator', [': ', '# ', '\n'])
def test_delimited_all_letter_locator_is_not_blacklisted(separator):
    text='Your reservation code'+separator+'FORYOUR\nFlight 1 UA123'
    assert extract_primary_reference(text) == 'FORYOUR'


@pytest.mark.parametrize("text", [
    "Your confirmation number is A7B8C9",
    "Your confirmation number is:\nA7B8C9",
    "Confirmation code:\nhttps://tracking.example.test/?booking=BAD123\nA7B8C9",
    "Confirmation code:\n\n<https://tracking.example.test/code>\n\nA7B8C9",
    "Confirmation\nA7B8C9 (United)\nDeparture",
    "Booking ID\nA7B8C9",
])
def test_parser_and_identity_use_complete_labeled_reference(text):
    fields = extract_reference_fields(text)
    assert {field.code for field in fields} == {"A7B8C9"}
    assert extract_primary_reference(text) == _extract_pnr(text.upper()) == "A7B8C9"
    assert _extract_pnr_aliases(text.upper(), primary="OTHER1") == ["A7B8C9"]
    assert text[fields[0].start:fields[0].end].strip().endswith(("A7B8C9", "(United)"))


@pytest.mark.parametrize("value", [
    "ABC123/DEF456", "ABC123_MORE", "ABC123-EXTRALONG", "ABC123456789",
    "https://tracking.example.test/ABC123", "PLEASE review your itinerary",
    "your booking details", "Carry-on bag not allowed",
])
def test_invalid_field_never_becomes_partial_reference(value):
    text = "Confirmation code: " + value
    assert extract_reference_fields(text) == []
    assert _extract_pnr(text.upper()) is None
    assert _extract_pnr_aliases(text.upper(), primary="OTHER1") == []


def test_url_does_not_bridge_missing_reference_into_next_field():
    text = "Confirmation code:\nhttps://tracking.example.test/\nPassenger: Alex Avery\nABC123"
    assert extract_reference_fields(text) == []


def test_primary_and_aliases_do_not_take_compound_agency_prefix():
    text = "Booking number: 12345-LONGAGENCY\nAirline confirmation: ABC123\nBooking reference: DEF456"
    assert _extract_pnr(text.upper()) == "ABC123"
    assert _extract_pnr_aliases(text.upper(), primary="ABC123") == ["DEF456"]


def test_new_field_is_not_consumed_as_missing_carrier_reference():
    text = "Airline Reservation Code\nRoyal Air Maroc: \nBooking reference: OWN123"
    assert [field.code for field in extract_reference_fields(text)] == ["OWN123"]


@pytest.mark.parametrize("text", [
    "Airline\nconfirmation\n\nQWERTY\n\nPassengers\n\n1",
    "Airline confirmation QWERTY Passengers 1 Flight details",
    "Airline\n\nconfirmation\nQWERTY\nPassengers\n1",
])
def test_typed_airline_confirmation_survives_wrapped_or_flattened_cells(text):
    assert extract_primary_reference(text) == _extract_pnr(text.upper()) == "QWERTY"
    assert _extract_pnr_aliases(text.upper(), primary="OTHER1") == ["QWERTY"]
    assert extract_reference_fields(text)[0].label == "airline confirmation"


@pytest.mark.parametrize("text", [
    "Airline confirmation email",
    "Airline confirmation EMAIL Passengers 1",
    "Airline confirmation https://example.test/QWERTY",
    "Airline confirmation PLEASE check your email",
    "Airline confirmation QWERTY passengers are welcome",
    "Airline\nUnrelated details\nconfirmation\nQWERTY",
    "Airline\n\n\n\nconfirmation\nQWERTY",
])
def test_airline_heading_cannot_turn_notification_prose_into_a_reference(text):
    assert extract_reference_fields(text) == []


def test_flattened_itinerary_column_headings_cannot_supply_booking_alias():
    text = ("Record Locator:\nQWERTY\nYour Itinerary\n"
            "Carrier | Flight Number | Departing | Arriving | Booking Code Meals | Meals\n"
            "City | Date & Time | City | Time\n"
            "EXAMPLE AIRLINES | 123 | SEA Seattle | May 20, 2027 05:50 AM | SFO San Francisco")
    assert [field.code for field in extract_reference_fields(text)] == ["QWERTY"]
    assert _extract_pnr_aliases(text.upper(), primary="QWERTY") == []
    # Classification depends on the complete column-header row, not a ban on
    # an otherwise valid all-letter value in an actual labeled field.
    assert extract_primary_reference("Booking Code: MEALS") == "MEALS"


@pytest.mark.parametrize("separator", ["\n", "\n\n"])
def test_plural_confirmation_heading_reads_only_adjacent_carrier_cells(separator):
    text = ("Here are your Travel Desk and airline confirmation codes\n"
            "Pack your bags for your trip!\nYour confirmation codes" + separator
            + "American Airlines" + separator + "QWERTY\n"
            "Travel Desk\nH-N-12AB34")
    fields = extract_reference_fields(text)
    assert [(field.code, field.airline) for field in fields] == [("QWERTY", "American Airlines")]
    assert extract_primary_reference(text) == _extract_pnr(text.upper()) == "QWERTY"
    assert _extract_pnr_aliases(text.upper(), primary="QWERTY") == []


@pytest.mark.parametrize("text", [
    "Here are your airline confirmation codes",
    "Your confirmation codes\nPassenger: Alex Avery\nAmerican Airlines\nQWERTY",
    "Your confirmation codes\nAmerican Airlines\nManage your trip\nQWERTY",
    "Your confirmation codes\nAmerican Airlines\nQWERTY/ABC123",
])
def test_plural_reference_heading_cannot_supply_or_search_for_a_value(text):
    assert extract_reference_fields(text) == []


@pytest.mark.parametrize("label", ["Confirmation", "Confirmation code", "Airline confirmation"])
def test_explicit_all_letter_locator_named_codes_remains_valid(label):
    assert extract_primary_reference(label + ": CODES") == "CODES"


@pytest.mark.parametrize("text", [
    "To view your airline confirmation numbers, click here.",
    "To view your airline confirmation numbers,\nclick\nhere\n.",
    "Your confirmation numbers\nhttps://booking.example.test/ABC123\nPassenger: Alex Avery",
])
def test_plural_confirmation_numbers_is_heading_or_link_prose_not_locator(text):
    assert extract_reference_fields(text) == []
    assert _extract_pnr_aliases(text.upper(), primary="OTHER1") == []


def test_plural_numbers_table_still_reads_exact_carrier_reference():
    assert extract_primary_reference("Your confirmation numbers\nUnited Airlines\nQWERTY") == "QWERTY"
    assert extract_primary_reference("Confirmation code: NUMBERS") == "NUMBERS"
@pytest.mark.parametrize("heading", ["Airline Confirmation Numbers", "Confirmation Codes"])
def test_plural_reference_heading_has_adjacent_inline_carrier_cell(heading):
    fields = extract_reference_fields(heading + "\nAmerican Airlines: TEST12\nPassengers: Alex Avery")
    assert [(f.code, f.airline) for f in fields] == [("TEST12", "American Airlines")]
    assert not extract_reference_fields(heading + "\nTo view American Airlines: TEST12\n")
