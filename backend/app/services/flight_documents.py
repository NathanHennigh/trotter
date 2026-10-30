"""Selective, bounded extraction of ticket attachments. No OCR or remote AI."""
from __future__ import annotations

import base64
from hashlib import sha256
import json
import re
import subprocess
import sys

MAX_DOCUMENT_BYTES = 4 * 1024 * 1024
MAX_DOCUMENTS = 3
MAX_PAGES = 12
MAX_TEXT_CHARS = 100_000
EXTRACTION_TIMEOUT_SECONDS = 12
_TICKET = re.compile(r"e[- ]?ticket|boarding[ _-]?pass|passenger[ _-]?receipt|flight[ _-]?(?:itinerary|confirmation)|itinerary", re.I)


def attachment_manifest(message: dict) -> list[dict]:
    result = []

    def walk(part, path):
        if not isinstance(part, dict):
            return
        filename = str(part.get("filename") or "")
        mime = str(part.get("mimeType") or "").lower()
        if filename.lower().endswith(".pdf") or mime == "application/pdf":
            body = part.get("body") or {}
            result.append({"filename": filename, "attachment_id": body.get("attachmentId"),
                           "size": body.get("size", 0), "data": body.get("data"), "part": path})
        for index, child in enumerate(part.get("parts") or []):
            walk(child, f"{path}.{index}")
    walk(message.get("payload") or {}, "0")
    return result


def needs_ticket_documents(message: dict, *, subject: str, body: str, evidence,
                           parsed_result=None, body_parse_checked=False) -> bool:
    manifests = attachment_manifest(message)
    if not manifests or not (_TICKET.search(subject + "\n" + body[:20_000])
                             or any(_TICKET.search(item["filename"]) for item in manifests)):
        return False
    if body_parse_checked:
        flights = getattr(parsed_result, "flights", None) or []
        complete = bool(flights) and all(
            flight.dep_airport and flight.arr_airport and flight.dep_time and flight.arr_time
            and flight.flight_number and flight.pnr and flight.ownership in {"self", "other"}
            and flight.passenger_evidence and not getattr(flight, "force_review", False)
            for flight in flights
        )
        return not complete
    signals = set(evidence.signals)
    complete = {"route_airport_pair", "date_or_time", "flight_number", "booking_identifier"} <= signals
    named = bool(re.search(r"\b(?:passenger|travell?er|name)\s*[:\n]", body, re.I))
    return not (complete and named)


def extract_pdf_text(data: bytes) -> list[dict]:
    """A disposable process bounds hostile PDF CPU/memory, including decompression."""
    if not data.startswith(b"%PDF-") or len(data) > MAX_DOCUMENT_BYTES:
        raise ValueError("invalid_or_oversized_pdf")
    completed = subprocess.run(
        [sys.executable, "-m", "app.services.flight_documents"], input=data,
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        timeout=EXTRACTION_TIMEOUT_SECONDS, check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if completed.returncode or len(completed.stdout) > MAX_TEXT_CHARS * 8:
        raise ValueError("unreadable_pdf")
    result = json.loads(completed.stdout)
    if not isinstance(result, list) or len(result) > MAX_PAGES:
        raise ValueError("invalid_pdf_result")
    return result


def load_ticket_documents(service, message: dict) -> tuple[list[dict], list[str]]:
    from .gmail import _with_backoff
    from .gmail_connection import is_gmail_authorization_error
    documents, errors = [], []
    manifests = attachment_manifest(message)
    if len(manifests) > MAX_DOCUMENTS:
        return [], ["too_many_ticket_documents"]
    for item in manifests:
        stage = "extract"
        try:
            if int(item["size"] or 0) > MAX_DOCUMENT_BYTES:
                errors.append("oversized_pdf")
                continue
            encoded = item["data"]
            if not encoded and item["attachment_id"]:
                stage = "fetch"
                response = _with_backoff(lambda: service.users().messages().attachments().get(
                    userId="me", messageId=message["id"], id=item["attachment_id"],
                ).execute())
                encoded = response.get("data")
                stage = "extract"
            if not encoded:
                errors.append("missing_pdf_bytes")
                continue
            if len(encoded) > ((MAX_DOCUMENT_BYTES + 2) // 3) * 4 + 4:
                errors.append("oversized_pdf")
                continue
            data = base64.urlsafe_b64decode(encoded + "==")
            pages = extract_pdf_text(data)
            if not any(page["text"].strip() for page in pages):
                errors.append("pdf_has_no_text")
                continue
            documents.append({"filename": item["filename"], "attachment_id": item["attachment_id"],
                              "part": item["part"], "sha256": sha256(data).hexdigest(), "pages": pages})
        except Exception as exc:
            if is_gmail_authorization_error(exc):
                raise
            # Stable codes only: Gmail exceptions can contain sensitive request data.
            errors.append("pdf_fetch_failed" if stage == "fetch" else
                          "pdf_timeout" if isinstance(exc, subprocess.TimeoutExpired) else "pdf_extraction_failed")
    return documents, errors


def _extract_child() -> None:
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (384 * 1024 * 1024, 384 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_CPU, (10, 10))
    except ImportError:
        pass  # Windows is still bounded by input, page count and parent timeout.
    from io import BytesIO
    from pypdf import PdfReader
    reader = PdfReader(BytesIO(sys.stdin.buffer.read(MAX_DOCUMENT_BYTES + 1)), strict=True)
    if reader.is_encrypted or len(reader.pages) > MAX_PAGES:
        raise ValueError("unsupported_pdf")
    pages, chars = [], 0
    for number, page in enumerate(reader.pages, 1):
        content = page.get_contents()
        if content is not None and len(content.get_data()) > 2 * 1024 * 1024:
            raise ValueError("oversized_pdf_stream")
        text = page.extract_text() or ""
        chars += len(text)
        if chars > MAX_TEXT_CHARS:
            raise ValueError("oversized_pdf_text")
        pages.append({"number": number, "text": text})
    sys.stdout.write(json.dumps(pages))


if __name__ == "__main__":
    _extract_child()
