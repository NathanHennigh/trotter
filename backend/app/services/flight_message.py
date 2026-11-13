"""One deterministic preparation path for fresh mail, history and repair."""
from __future__ import annotations

from datetime import datetime, timezone
from dataclasses import replace
from email.utils import parsedate_to_datetime
import json
import re

from .flight_evidence import assess_flight_evidence, has_explicit_flight_number
from .gmail import extract_attachments, extract_headers, extract_message_body
from .html_visibility import permitted_jsonld_scripts, visible_html_soup


def _has_complete_structured_itinerary(html: str) -> bool:
    """Typed schedules admit parsing; they do not establish passenger authority."""
    if len(html) > 200_000:
        return False
    bounded = html[:200_000]
    if "application/ld+json" not in bounded or "FlightReservation" not in bounded:
        return False
    from .flight_evidence import _valid_iata

    def complete(item, depth=0):
        if depth > 8 or not isinstance(item, dict):
            return False
        if item.get("@type") in ("ReservationPackage", "TravelAction"):
            children = item.get("subReservation")
            return isinstance(children, list) and any(complete(child, depth + 1) for child in children[:64])
        flight = item.get("reservationFor")
        if item.get("@type") != "FlightReservation" or not isinstance(flight, dict) or flight.get("@type") != "Flight":
            return False
        airports = [flight.get(key) for key in ("departureAirport", "arrivalAirport")]
        if not all(isinstance(airport, dict) for airport in airports):
            return False
        codes = [str(airport.get("iataCode") or "").upper() for airport in airports]
        if codes[0] == codes[1] or not all(_valid_iata(code) for code in codes):
            return False
        if not re.fullmatch(r"(?:[A-Z0-9]{2})?\d{1,4}[A-Z]?", str(flight.get("flightNumber") or "").upper()):
            return False
        # A date alone is not a midnight schedule. Both clocks must be printed
        # in this reservation, independent of message dates or MIME alternatives.
        for key in ("departureTime", "arrivalTime"):
            value = flight.get(key)
            if not isinstance(value, str) or not re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", value):
                return False
            try:
                datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                return False
        return True

    def inspect(item, depth=0):
        if depth > 8 or not isinstance(item, dict):
            return 0, False
        if item.get("@type") == "FlightReservation":
            return 1, complete(item)
        if item.get("@type") in ("ReservationPackage", "TravelAction"):
            children = item.get("subReservation", [])
            if not isinstance(children, list) or len(children) > 64:
                return 0, False
            results = [inspect(child, depth + 1) for child in children]
            return sum(count for count, _ in results), all(valid for _, valid in results)
        return 0, True

    scripts = permitted_jsonld_scripts(bounded)
    if len(scripts) > 64:
        return False
    reservations = 0
    for script in scripts:
        try:
            data = json.loads(script.string or "")
        except (ValueError, TypeError, RecursionError):
            continue
        items = data if isinstance(data, list) else [data]
        if len(items) > 64:
            return False
        for item in items:
            count, valid = inspect(item)
            if not valid:
                return False
            reservations += count
    if not reservations:
        return False
    # The legacy extractor consumes every JSON-LD item once admitted. A valid
    # first reservation cannot license malformed siblings or date-only clocks.
    from .parser import extract_jsonld_flights
    try:
        return bool(extract_jsonld_flights(html))
    except (AttributeError, TypeError, ValueError, RecursionError):
        return False


def _html_evidence(subject: str, sender: str, html: str):
    evidence = assess_flight_evidence(subject=subject, sender=sender, body=html)
    structural_signal = None
    if "operational_itinerary" not in evidence.signals:
        if _has_complete_structured_itinerary(html):
            structural_signal = "structured_flight_reservation"
        elif _has_clocked_html_summary(html):
            structural_signal = "clocked_flight_summary"
    if structural_signal:
        evidence = replace(evidence, verdict="parse", score=max(8, evidence.score),
                           signals=evidence.signals + (structural_signal, "operational_itinerary"))
    return evidence


def _has_clocked_html_summary(html: str) -> bool:
    """A summary card can print timed airport cells without route punctuation."""
    bounded = html[:200_000]
    if not re.search(r"flight\s+summary", bounded, re.I):
        return False
    from .flight_evidence import _DATE_TIME, _flight_numbers, _valid_iata
    soup = visible_html_soup(bounded)
    text = re.sub(r"https?://\S+", " ", " ".join(soup.get_text(" ", strip=True).split()))
    headings = list(re.finditer(r"\bflight summary\b", text, re.I))
    endpoint = re.compile(r"\b((?:[01]?\d|2[0-3]):[0-5]\d(?:\s*[AP]M)?)\s+([A-Z]{3})\s+(?:GMT|UTC)\s*[+-]\d{1,2}(?::?\d{2})?\b", re.I)
    for index, heading in enumerate(headings):
        end = min(heading.end() + 1600, headings[index + 1].start() if index + 1 < len(headings) else len(text))
        block = text[heading.end():end]
        if not _DATE_TIME.search(block) or not _flight_numbers(block.upper()):
            continue
        codes = set()
        for clock, code in endpoint.findall(block):
            try:
                value = re.sub(r"\s", "", clock).upper()
                datetime.strptime(value, "%I:%M%p" if value.endswith(("AM", "PM")) else "%H:%M")
            except ValueError:
                continue
            if _valid_iata(code.upper()):
                codes.add(code.upper())
        if len(codes) >= 2:
            return True
    return False


def message_internal_time(message: dict):
    try:
        milliseconds = int(message.get("internalDate", ""))
        return datetime.fromtimestamp(milliseconds / 1000, tz=timezone.utc) if milliseconds > 0 else None
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _hold_incomplete_extractions(result, text: str, *, detailed_text: str = "") -> list[str]:
    """Retain uncertain facts without creating timed flights from placeholders."""
    reasons = []
    for flight in result.flights:
        source = getattr(flight, "source", None)
        reason = ("subject_only_itinerary_requires_review" if source == "subject" else
                  "summary_flight_number_not_supported" if source == "v5"
                  and getattr(flight, "flight_number", None)
                  and not has_explicit_flight_number(flight.flight_number, text, detailed_text=detailed_text) else None)
        if reason:
            flight.force_review = True
            # This survives the immutable ledger and explains why normalized
            # clocks alone do not establish a complete itinerary.
            flight.time_provenance = {**(getattr(flight, "time_provenance", None) or {}),
                                      "extraction_review_reason": reason}
            reasons.append(reason)
    return list(dict.fromkeys(reasons))


def prepare_flight_message(full_msg: dict, *, user_name: str, aliases: list[str],
                           documents: tuple | list = (), force_parse: bool = False) -> dict:
    from .parser import ParseResult, _extract_pnr, parse_email
    from ..models import MessageStatus
    headers = extract_headers(full_msg)
    plain_text, html = extract_message_body(full_msg)
    subject, sender = headers.get("subject", ""), headers.get("from", "")
    has_plain = bool(plain_text.strip())
    has_html = bool(html.strip())
    same_body = plain_text == html
    body = plain_text if has_plain else html
    evidence = (_html_evidence(subject, sender, html) if has_html and (not has_plain or same_body)
                else assess_flight_evidence(subject=subject, sender=sender, body=body))
    if has_plain and has_html and not same_body:
        # MIME alternatives can differ materially: a short plain-text marketing
        # fallback must not hide the HTML itinerary. Score each independently;
        # scattered fields in two weak alternatives cannot combine into proof.
        html_evidence = _html_evidence(subject, sender, html)
        def strength(value):
            return ({"skip": 0, "review": 1, "parse": 2}[value.verdict],
                    "labeled_operational_block" in value.signals, value.score)
        # A higher score alone may only mean the HTML omitted promotional text
        # or contains incidental words such as "way to get" or "check in".
        # Replacing present plain text requires an actual itinerary in the HTML.
        if "operational_itinerary" in html_evidence.signals and strength(html_evidence) > strength(evidence):
            body, evidence = html, html_evidence
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
        if any(getattr(flight, "source", None) in {"subject", "v5"} for flight in result.flights):
            from .booking_import import visible_message_text
            _hold_incomplete_extractions(result, visible_message_text(plain_text, html),
                                        detailed_text=visible_message_text("", html) if html else "")
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
        incomplete = _hold_incomplete_extractions(parsed, text)
        if incomplete:
            provenance[-1]["review_reasons"] = incomplete
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
