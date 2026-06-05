"""Gmail API client: authentication, paginated fetching, and body extraction."""

from __future__ import annotations

import base64
import logging
import os
import random
import socket
import ssl
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


def _with_backoff(
    fn,
    max_attempts: int = 5,
    *,
    _network_deadline: Optional[float] = None,
    _network_attempt: int = 0,
):
    """Retry fn on Gmail throttling and transient network outages.

    Long imports should survive a flaky laptop/network. DNS drops and brief
    connection failures pause here, then the original Gmail request is retried
    from the same page/message instead of failing the whole sync job.
    """
    from googleapiclient.errors import HttpError

    network_deadline = _network_deadline
    if network_deadline is None:
        network_deadline = time.monotonic() + _network_retry_seconds()
    network_attempt = _network_attempt
    for attempt in range(max_attempts):
        try:
            return fn()
        except Exception as exc:
            if _is_retryable_network_error(exc) and time.monotonic() < network_deadline:
                network_attempt += 1
                _wait_for_google_network(exc, network_deadline, network_attempt)
                return _with_backoff(
                    fn,
                    max_attempts=max_attempts,
                    _network_deadline=network_deadline,
                    _network_attempt=network_attempt,
                )
            if isinstance(exc, HttpError):
                if exc.resp.status in (429, 500, 502, 503, 504) and attempt < max_attempts - 1:
                    delay = (2**attempt) + random.uniform(0, 1)
                    logger.warning(
                        "HTTP %s; retrying in %.1fs (attempt %d/%d)",
                        exc.resp.status, delay, attempt + 1, max_attempts,
                    )
                    time.sleep(delay)
                    continue
            raise


def _network_retry_seconds() -> int:
    try:
        return max(0, int(os.getenv("TROTTER_GMAIL_NETWORK_RETRY_SECONDS", "1800")))
    except ValueError:
        return 1800


def _is_retryable_network_error(exc: BaseException) -> bool:
    if _is_non_retryable_auth_error(exc):
        return False
    retryable_types = (
        ConnectionError,
        TimeoutError,
        socket.gaierror,
        socket.timeout,
        ssl.SSLError,
    )
    retryable_names = {
        "TransportError",
        "ServerNotFoundError",
        "ConnectionError",
        "ConnectTimeout",
        "ReadTimeout",
        "Timeout",
    }
    seen: set[int] = set()
    current: Optional[BaseException] = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if _is_non_retryable_auth_error(current):
            return False
        if isinstance(current, retryable_types):
            return True
        if type(current).__name__ in retryable_names:
            return True
        text = str(current).lower()
        if (
            "getaddrinfo failed" in text
            or "unable to find the server" in text
            or "temporary failure in name resolution" in text
            or "name or service not known" in text
            or "connection aborted" in text
            or "connection reset" in text
            or "timed out" in text
        ):
            return True
        current = current.__cause__ or current.__context__
    return False


def _is_non_retryable_auth_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    return (
        "invalid_grant" in text
        or "token has been expired or revoked" in text
        or "invalid_request" in text and "reauth" in text
    )


def _wait_for_google_network(exc: BaseException, deadline: float, attempt: int) -> None:
    max_sleep = max(1, int(os.getenv("TROTTER_GMAIL_NETWORK_RETRY_INTERVAL_SECONDS", "30")))
    delay = min(max_sleep, 2 ** min(attempt, 5)) + random.uniform(0, 1)
    remaining = max(0, deadline - time.monotonic())
    delay = min(delay, remaining)
    logger.warning(
        "Google API network error (%s). Waiting %.1fs before retry; %.0fs retry budget remains.",
        exc,
        delay,
        remaining,
    )
    print(
        f"\nNetwork issue reaching Google APIs. Pausing {delay:.0f}s, then retrying "
        f"from the same Gmail request..."
    )
    time.sleep(delay)


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


def batch_get_messages(service, msg_ids: list[str]) -> tuple[dict[str, dict], dict[str, Exception]]:
    """Fetch full message payloads in one Gmail batch request."""
    return _batch_get_messages(service, msg_ids, format_name="full")


def batch_get_message_metadata(service, msg_ids: list[str]) -> tuple[dict[str, dict], dict[str, Exception]]:
    """Fetch message snippets and From/Subject headers without full bodies."""
    return _batch_get_messages(
        service,
        msg_ids,
        format_name="metadata",
        metadata_headers=["From", "Subject", "Date"],
    )


def _batch_get_messages(
    service,
    msg_ids: list[str],
    *,
    format_name: str,
    metadata_headers: Optional[list[str]] = None,
) -> tuple[dict[str, dict], dict[str, Exception]]:
    """Fetch Gmail payloads in one batch request.

    Returns successful responses and per-message failures separately so a sync
    can keep moving when one message fetch fails.
    """
    if not msg_ids:
        return {}, {}
    if not hasattr(service, "new_batch_http_request"):
        results: dict[str, dict] = {}
        errors: dict[str, Exception] = {}
        for msg_id in msg_ids:
            try:
                if format_name == "full":
                    results[msg_id] = get_message(service, msg_id)
                else:
                    params = {"userId": "me", "id": msg_id, "format": format_name}
                    if metadata_headers:
                        params["metadataHeaders"] = metadata_headers
                    results[msg_id] = _with_backoff(lambda params=params: service.users().messages().get(**params).execute())
            except Exception as exc:  # pragma: no cover - defensive fallback
                errors[msg_id] = exc
        return results, errors

    results: dict[str, dict] = {}
    errors: dict[str, Exception] = {}

    def _callback(request_id, response, exception):
        if exception:
            errors[str(request_id)] = exception
            return
        if response:
            results[str(request_id)] = response

    def _call():
        batch = service.new_batch_http_request(callback=_callback)
        for msg_id in msg_ids:
            params = {"userId": "me", "id": msg_id, "format": format_name}
            if metadata_headers:
                params["metadataHeaders"] = metadata_headers
            request = service.users().messages().get(**params)
            batch.add(request, request_id=msg_id)
        batch.execute()
        return results

    _with_backoff(_call)

    retryable_ids = [
        msg_id
        for msg_id, exc in errors.items()
        if getattr(getattr(exc, "resp", None), "status", None) in (429, 500, 502, 503, 504)
    ]
    for msg_id in retryable_ids:
        try:
            if format_name == "full":
                results[msg_id] = get_message(service, msg_id)
            else:
                params = {"userId": "me", "id": msg_id, "format": format_name}
                if metadata_headers:
                    params["metadataHeaders"] = metadata_headers
                results[msg_id] = _with_backoff(lambda params=params: service.users().messages().get(**params).execute())
            errors.pop(msg_id, None)
        except Exception as exc:
            errors[msg_id] = exc
    return results, errors


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
