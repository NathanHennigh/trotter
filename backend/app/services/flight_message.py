"""One deterministic preparation path for fresh mail, history and repair."""
from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from .flight_evidence import assess_flight_evidence
from .gmail import extract_attachments, extract_headers, extract_message_body


def message_internal_time(message: dict):
    try:
        milliseconds = int(message.get("internalDate", ""))
        return datetime.fromtimestamp(milliseconds / 1000, tz=timezone.utc) if milliseconds > 0 else None
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def prepare_flight_message(full_msg: dict, *, user_name: str, aliases: list[str],
                           documents: tuple | list = (), force_parse: bool = False) -> dict:
    from .parser import ParseResult, _extract_pnr, parse_email
    from ..models import MessageStatus
    headers = extract_headers(full_msg)
    plain_text, html = extract_message_body(full_msg)
    subject, sender = headers.get("subject", ""), headers.get("from", "")
    body = plain_text if plain_text.strip() else html
    evidence = assess_flight_evidence(subject=subject, sender=sender, body=body)
    internal_ts = message_internal_time(full_msg)
    received_at = headers.get("date") or internal_ts
    if isinstance(received_at, str):
        try:
            parsedate_to_datetime(received_at)
        except (ValueError, TypeError, OverflowError):
            received_at = internal_ts
    result = None
    if force_parse or evidence.verdict != "skip":
        result = parse_email(html=html, plain_text=plain_text, attachments=extract_attachments(full_msg),
                             user_name=user_name, aliases=aliases, received_at=received_at,
                             subject=subject, from_email=sender)
    provenance = []
    for document in documents:
        # Keep document ownership independent from body greetings and other PDFs.
        text = "\n\n".join(page["text"] for page in document["pages"])
        parsed = parse_email(html="", plain_text=text, attachments=[], user_name=user_name,
                             aliases=aliases, received_at=received_at, subject=subject, from_email=sender)
        from .booking_import import _cancellation_intent
        cancellation_document = _cancellation_intent("", text)
        provenance.append({key: document.get(key) for key in ("filename", "attachment_id", "part", "sha256")}
                          | {"pages": [page["number"] for page in document["pages"]], "flight_count": len(parsed.flights)})
        if cancellation_document:
            provenance[-1]["review_reason"] = "cancellation_document_requires_review"
            for flight in parsed.flights:
                flight.force_review = True
        if parsed.flights:
            if result is None:
                result = ParseResult(source="pdf")
            # Same facts with stronger passenger evidence can coexist in the
            # immutable ledger. Only exact duplicate evidence is omitted here.
            def key(f):
                return (f.dep_airport, f.arr_airport, f.dep_time, f.arr_time, f.flight_number,
                        f.pnr, tuple(f.passenger_names), f.ownership)
            known = {key(flight) for flight in result.flights}
            for flight in parsed.flights:
                flight.document_provenance = provenance[-1]
                if key(flight) not in known:
                    result.flights.append(flight)
                    known.add(key(flight))
            result.source = "pdf" if result.source == "unknown" else result.source + "+pdf"
    if result is not None:
        result.status = (MessageStatus.ACCEPTED if result.flights and all(f.ownership == "self" and not getattr(f, "force_review", False) for f in result.flights)
                         else MessageStatus.REVIEW_REQUIRED)
    return {"full_msg": full_msg, "msg_id": full_msg["id"], "headers": headers,
            "subject": subject, "from_email": sender, "plain_text": plain_text, "html": html,
            "body_for_filter": body, "evidence": evidence, "parse_result": result,
            "received_at": received_at, "internal_ts": internal_ts,
            "pnr": _extract_pnr(f"{subject}\n{body}".upper()), "document_provenance": provenance,
            "flight_like_candidate": evidence.verdict != "skip" or bool(documents),
            "evidence_skipped": result is None, "prefilter_skipped": False}
