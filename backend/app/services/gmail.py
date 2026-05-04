"""Gmail API client: authentication, paginated fetching, and body extraction."""

from __future__ import annotations

import base64
import logging
import os
import random
import time
from typing import Iterator, Optional

from ..crypto import decrypt_refresh_token

logger = logging.getLogger(__name__)

GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

from .flight_query_v3 import build_gmail_queries, build_gmail_query

FLIGHT_QUERY = build_gmail_query()


def build_gmail_service(refresh_token_encrypted: bytes):
    """Build an authenticated Gmail API service from an encrypted refresh token."""
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    refresh_token = decrypt_refresh_token(refresh_token_encrypted)
    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.environ["GOOGLE_CLIENT_ID"],
        client_secret=os.environ["GOOGLE_CLIENT_SECRET"],
        scopes=GMAIL_SCOPES,
    )
    return build("gmail", "v1", credentials=creds)


def _with_backoff(fn, max_attempts: int = 5):
    """Retry fn with exponential backoff on 429/5xx HTTP errors."""
    from googleapiclient.errors import HttpError

    for attempt in range(max_attempts):
        try:
            return fn()
        except HttpError as exc:
            if exc.resp.status in (429, 500, 502, 503, 504) and attempt < max_attempts - 1:
                delay = (2**attempt) + random.uniform(0, 1)
                logger.warning(
                    "HTTP %s; retrying in %.1fs (attempt %d/%d)",
                    exc.resp.status, delay, attempt + 1, max_attempts,
                )
                time.sleep(delay)
            else:
                raise


def list_messages(
    service,
    query: Optional[str] = None,
    page_token: Optional[str] = None,
) -> tuple[list[dict], Optional[str]]:
    """Fetch one page of message stubs. Returns (messages, next_page_token)."""
    if query is None:
        from .flight_query import build_gmail_query
        query = build_gmail_query()

    def _call():
        params: dict = {"userId": "me", "maxResults": 500}
        if query:
            params["q"] = query
        if page_token:
            params["pageToken"] = page_token
        return service.users().messages().list(**params).execute()

    result = _with_backoff(_call)
    return result.get("messages", []), result.get("nextPageToken")


def get_message(service, msg_id: str) -> dict:
    """Fetch a full message payload by ID."""
    return _with_backoff(lambda: service.users().messages().get(
        userId="me", id=msg_id, format="full"
    ).execute())


def iter_all_messages(
    service,
    query: Optional[str] = None,
    start_page_token: Optional[str] = None,
) -> Iterator[tuple[dict, Optional[str]]]:
    """Yield (message_stub, current_page_token) for every matching message."""
    page_token = start_page_token
    while True:
        messages, next_token = list_messages(service, query=query, page_token=page_token)
        for msg in messages:
            yield msg, page_token
        if not next_token:
            break
        page_token = next_token


def iter_flight_candidate_messages(service) -> Iterator[tuple[dict, str]]:
    """Yield deduplicated message stubs across all production flight queries."""
    seen: set[str] = set()
    for query in build_gmail_queries():
        for msg, _page_token in iter_all_messages(service, query=query):
            msg_id = msg.get("id")
            if not msg_id or msg_id in seen:
                continue
            seen.add(msg_id)
            yield msg, query


def extract_message_body(message: dict) -> tuple[str, str]:
    """Return (plain_text, html) extracted from a Gmail message payload."""
    plain_parts: list[str] = []
    html_parts: list[str] = []

    def _walk(payload: dict) -> None:
        mime_type = payload.get("mimeType", "")
        data = payload.get("body", {}).get("data", "")
        if data:
            decoded = base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")
            if mime_type == "text/plain":
                plain_parts.append(decoded)
            elif mime_type == "text/html":
                html_parts.append(decoded)
        for part in payload.get("parts", []):
            _walk(part)

    _walk(message.get("payload", {}))
    return "\n".join(plain_parts), "\n".join(html_parts)


def extract_attachments(message: dict) -> list[tuple[str, bytes]]:
    """Return a list of (filename, bytes) for .ics attachments in the message."""
    results: list[tuple[str, bytes]] = []

    def _walk(payload: dict) -> None:
        filename = payload.get("filename", "")
        mime_type = payload.get("mimeType", "")
        is_ics = filename.lower().endswith(".ics") or mime_type in (
            "text/calendar", "application/ics", "application/x-vcalendar"
        )
        if is_ics:
            data = payload.get("body", {}).get("data", "")
            if data:
                results.append((filename, base64.urlsafe_b64decode(data + "==")))
        for part in payload.get("parts", []):
            _walk(part)

    _walk(message.get("payload", {}))
    return results


def extract_headers(message: dict) -> dict[str, str]:
    """Return a dict of lowercased header name → value for key headers."""
    headers: dict[str, str] = {}
    for h in message.get("payload", {}).get("headers", []):
        name = h["name"].lower()
        if name in ("from", "subject", "date"):
            headers[name] = h["value"]
    return headers
