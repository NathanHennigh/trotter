import base64
from datetime import datetime, timezone
from io import BytesIO

import pytest

from app.models import MessageStatus
from app.services import parser
from app.services.flight_documents import extract_pdf_text
from app.services.flight_evidence import assess_flight_evidence, has_explicit_flight_number
from app.services.flight_message import prepare_flight_message


def message(body, subject="Your flight itinerary"):
    return {"id": "evidence", "internalDate": "1748736000000", "payload": {
        "mimeType": "text/plain", "headers": [{"name": "Subject", "value": subject},
        {"name": "From", "value": "receipts@example.com"}],
        "body": {"data": base64.urlsafe_b64encode(body.encode()).decode()}}}


@pytest.mark.parametrize("subject,body,numbers", [
    ("Your trip confirmation and receipt", "Record locator ABC123. July 18, 2022. BNA CLT. "
     "5:06 PM 7:30 PM. American Airlines 2040. Ticket # 0012345678901. "
     "Hotel offers. Credit card approval. Check in at the airport.", {"AA2040"}),
    ("Expedia flight purchase confirmation", "Your flights are booked. Traveler details Alex Avery. "
     "Airline confirmation code ABC123. Spirit Airlines 1814 7:05pm Dallas to Fort Lauderdale. "
     "Aeromexico 651 1:49pm Managua to Mexico City. Fri, Mar 3. View ticketing details. "
     "Airport check-in. Rental car offers. Pay to choose your seat.", {"NK1814", "AM651"}),
])
def test_dated_receipt_with_spelled_out_carrier_survives_footer(subject, body, numbers):
    evidence = assess_flight_evidence(subject=subject, sender="receipts@example.com", body=body)
    assert evidence.verdict == "parse"
    assert numbers <= set(evidence.flight_numbers)


@pytest.mark.parametrize("subject,body", [
    ("Flight deals: book now", "Spirit Airlines 1814. DFW to FLL, Mar 3. Save up to 50%."),
    ("Your mileage statement", "New service American Airlines 2040 BNA -> CLT on July 18. Book now."),
    ("Your hotel confirmation", "Hotel reservation ABC123, July 18. American Airlines support 1 (800) 555-0100."),
])
def test_carrier_names_do_not_turn_ads_or_hotel_receipts_into_flights(subject, body):
    assert assess_flight_evidence(subject=subject, sender="news@example.com", body=body).verdict == "skip"


def test_summary_stop_count_and_support_phone_are_not_flight_number_evidence():
    text = "1 stop. Iberia 8797 TNG-MAD. Iberia 3912 MAD-PMI. Iberia support 1 (800) 555-0100."
    assert not has_explicit_flight_number("IB1", text)
    assert has_explicit_flight_number("IB8797", text)
    assert has_explicit_flight_number("AA001", "American\nAirlines 1")


def test_numbered_html_legs_override_plain_summary_stop_count():
    assert not has_explicit_flight_number("IB1", "Iberia\n1 TNG-PMI", detailed_text="Iberia 8797 TNG-MAD. Iberia 3912 MAD-PMI.")
    assert has_explicit_flight_number("IB1", "Iberia 1 TNG-PMI", detailed_text="View itinerary")
    assert has_explicit_flight_number("NK1651", "FLIGHT TERMINAL 1651 Change Aircraft")
    assert not has_explicit_flight_number("IB1", "https://mail.example/IB1")


@pytest.mark.parametrize("number,text", [("Z2712", "AirAsia 712"), ("Y4786", "Volaris Flight 786"),
    ("UA1540", "United 1540"), ("NH801", "ANA 801"), ("NK512", "FLIGHT\nTERMINAL\n512")])
def test_precision_guard_accepts_parser_carrier_aliases_and_table_columns(number, text):
    assert has_explicit_flight_number(number, text)


@pytest.mark.parametrize("source,number,text,reason", [
    ("subject", None, "Booking ABC123. KLO to MNL May 3.", "subject_only_itinerary_requires_review"),
    ("v5", "IB1", "TNG-MAD Iberia 8797. MAD-PMI Iberia 3912. 1 stop.", "summary_flight_number_not_supported"),
])
@pytest.mark.parametrize("document", [False, True])
def test_incomplete_extraction_is_retained_for_review_not_promoted(monkeypatch, source, number, text, reason, document):
    def parse(**kwargs):
        if kwargs["plain_text"] != text:
            return parser.ParseResult()
        f = parser.ParsedFlight("KLO", "MNL", datetime(2025, 5, 3, tzinfo=timezone.utc),
            datetime(2025, 5, 3, 1, tzinfo=timezone.utc), flight_number=number, pnr="ABC123",
            source=source, ownership="self", passenger_names=["Alex Avery"])
        return parser.ParseResult(flights=[f])
    monkeypatch.setattr(parser, "parse_email", parse)
    docs = [{"filename": "ticket.pdf", "sha256": "fixture", "pages": [{"number": 1, "text": text}]}] if document else []
    result = prepare_flight_message(message("Attached" if document else text), user_name="Alex Avery", aliases=[],
        documents=docs, force_parse=True)
    f = result["parse_result"].flights[0]
    assert f.force_review
    assert f.time_provenance["extraction_review_reason"] == reason
    assert result["parse_result"].status == MessageStatus.REVIEW_REQUIRED
    if document:
        assert reason in f.document_provenance["review_reasons"]


def encrypted_pdf(user_password):
    from pypdf import PdfWriter
    from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
    writer = PdfWriter()
    page = writer.add_blank_page(width=400, height=400)
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Helvetica")})
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})})
    stream = DecodedStreamObject(); stream.set_data(b"BT /F1 12 Tf 20 350 Td (Passenger: Alex Avery) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(stream)
    writer.encrypt(user_password=user_password, owner_password="owner-permission-key")
    output = BytesIO(); writer.write(output)
    return output.getvalue()


def test_owner_permission_encrypted_pdf_opens_with_empty_user_password():
    assert extract_pdf_text(encrypted_pdf("")) == [{"number": 1, "text": "Passenger: Alex Avery"}]


def test_password_protected_pdf_is_still_rejected():
    with pytest.raises(ValueError, match="unreadable_pdf"):
        extract_pdf_text(encrypted_pdf("required-user-password"))
