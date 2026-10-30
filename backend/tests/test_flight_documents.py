import base64
from datetime import datetime, timezone
from io import BytesIO

import pytest

from app.services import flight_documents as documents, parser
from app.services.flight_evidence import assess_flight_evidence
from app.services.flight_message import message_internal_time, prepare_flight_message


def message(body="See your attached e-ticket."):
    return {"id": "source", "internalDate": "1748736000000", "payload": {"mimeType": "multipart/mixed",
        "headers": [{"name": "Subject", "value": "Your flight itinerary"}, {"name": "From", "value": "air@example.com"}],
        "parts": [{"mimeType": "text/plain", "body": {"data": base64.urlsafe_b64encode(body.encode()).decode()}},
                  {"mimeType": "application/pdf", "filename": "e-ticket.pdf", "body": {"attachmentId": "ticket", "size": 100}}]}}


def test_complete_named_body_does_not_download_ticket():
    body = "Passenger: Alex Avery. Record locator ABC123. Flight AA100 DFW -> JFK on June 1, 2025 at 9:30 AM."
    evidence = assess_flight_evidence(subject="Your flight itinerary", sender="air@example.com", body=body)
    assert not documents.needs_ticket_documents(message(body), subject="Your flight itinerary", body=body, evidence=evidence)
    sparse = "See your attached e-ticket."
    evidence = assess_flight_evidence(subject="Your flight itinerary", sender="air@example.com", body=sparse)
    assert documents.needs_ticket_documents(message(), subject="Your flight itinerary", body=sparse, evidence=evidence)


def test_large_or_unrelated_attachments_are_not_fetched():
    msg = message()
    msg["payload"]["parts"][1]["body"]["size"] = documents.MAX_DOCUMENT_BYTES + 1
    assert documents.load_ticket_documents(object(), msg) == ([], ["oversized_pdf"])
    no_ticket = message("Your tax statement is attached.")
    no_ticket["payload"]["parts"][1]["filename"] = "statement.pdf"
    evidence = assess_flight_evidence(subject="Tax statement", sender="bank@example.com", body="Your tax statement is attached.")
    assert not documents.needs_ticket_documents(no_ticket, subject="Tax statement", body="Your tax statement is attached.", evidence=evidence)


def test_pdf_text_extraction_is_local_and_preserves_page_numbers():
    from pypdf import PdfWriter
    from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
    writer = PdfWriter()
    page = writer.add_blank_page(width=400, height=400)
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Helvetica")})
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})})
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 12 Tf 20 350 Td (Passenger: Alex Avery) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(stream)
    data = BytesIO()
    writer.write(data)
    pages = documents.extract_pdf_text(data.getvalue())
    assert pages == [{"number": 1, "text": "Passenger: Alex Avery"}]
    with pytest.raises(ValueError, match="invalid_or_oversized"):
        documents.extract_pdf_text(b"not a PDF")


def test_pdf_name_is_not_borrowed_from_body_or_another_document(monkeypatch):
    calls = []
    def parse(**kwargs):
        calls.append(kwargs["plain_text"])
        if "Passenger: Other Person" in kwargs["plain_text"]:
            name, ownership = "Other Person", "other"
        elif "Passenger: Alex Avery" in kwargs["plain_text"]:
            name, ownership = "Alex Avery", "self"
        else:
            return parser.ParseResult()
        flight = parser.ParsedFlight("DFW", "JFK", datetime(2025, 6, 1, tzinfo=timezone.utc), datetime(2025, 6, 1, 3, tzinfo=timezone.utc),
                                     flight_number="AA100", pnr="ABC123", passenger_name=name, passenger_names=[name], ownership=ownership)
        return parser.ParseResult(flights=[flight], source="fixture")
    monkeypatch.setattr(parser, "parse_email", parse)
    docs = [{"filename": name + ".pdf", "sha256": name, "pages": [{"number": 1, "text": "Passenger: " + name}]} for name in ("Alex Avery", "Other Person")]
    payload = prepare_flight_message(message("Dear Alex Avery, your flight itinerary is attached."), user_name="Alex Avery", aliases=[], documents=docs)
    assert {flight.ownership for flight in payload["parse_result"].flights} == {"self", "other"}
    assert all(not ("Other Person" in text and "Alex Avery" in text) for text in calls)
    assert len(payload["document_provenance"]) == 2


@pytest.mark.parametrize("value", [None, "", "invalid", "0", -1])
def test_invalid_internal_date_never_becomes_epoch(value):
    assert message_internal_time({"internalDate": value}) is None


def test_complete_parsed_city_itinerary_does_not_need_pdf_even_without_iata_text():
    from types import SimpleNamespace
    body = "Completed check-in. Houston to Taipei. Your e-ticket is attached."
    evidence = assess_flight_evidence(subject="Check-in completed", sender="air@example.com", body=body)
    flight = SimpleNamespace(dep_airport="IAH", arr_airport="TPE", dep_time=datetime.now(timezone.utc),
        arr_time=datetime.now(timezone.utc), flight_number="BR051", pnr="ABC123", ownership="self",
        passenger_evidence=[{"name": "Alex Avery", "role": "traveler"}])
    assert not documents.needs_ticket_documents(message(body), subject="Check-in completed", body=body,
        evidence=evidence, parsed_result=SimpleNamespace(flights=[flight]), body_parse_checked=True)
    assert documents.needs_ticket_documents(message(body), subject="Check-in completed", body=body,
        evidence=evidence, parsed_result=SimpleNamespace(flights=[]), body_parse_checked=True)


def test_preparation_keeps_time_ambiguity_review_status(monkeypatch):
    from types import SimpleNamespace
    from app.models import MessageStatus
    monkeypatch.setattr(parser, "parse_email", lambda **kwargs: parser.ParseResult(
        flights=[SimpleNamespace(ownership="self", force_review=True)], status=MessageStatus.REVIEW_REQUIRED))
    prepared = prepare_flight_message(message(), user_name="Alex Avery", aliases=[], force_parse=True)
    assert prepared["parse_result"].status == MessageStatus.REVIEW_REQUIRED


def test_canceled_pdf_cannot_introduce_active_flight_from_sparse_email(monkeypatch):
    from app.models import MessageStatus
    def parse(**kwargs):
        if "was canceled" not in kwargs["plain_text"]:
            return parser.ParseResult()
        flight = parser.ParsedFlight("DFW", "JFK", datetime(2025, 6, 1, tzinfo=timezone.utc), datetime(2025, 6, 1, 3, tzinfo=timezone.utc),
            flight_number="AA100", pnr="ABC123", passenger_name="Alex Avery", passenger_names=["Alex Avery"], ownership="self")
        return parser.ParseResult(flights=[flight])
    monkeypatch.setattr(parser, "parse_email", parse)
    doc = {"filename": "ticket.pdf", "sha256": "fixture", "pages": [{"number": 1, "text": "Your reservation ABC123 was canceled. Flight AA100 DFW to JFK."}]}
    result = prepare_flight_message(message(), user_name="Alex Avery", aliases=[], documents=[doc])
    assert result["parse_result"].flights[0].force_review
    assert result["parse_result"].status == MessageStatus.REVIEW_REQUIRED
    assert result["document_provenance"][0]["review_reason"] == "cancellation_document_requires_review"
