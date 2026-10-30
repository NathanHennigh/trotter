"""Gmail consent is separate from app identity; retain credentials on disconnect."""
from __future__ import annotations

import json

from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..models import Account

GMAIL_READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
READABLE_GMAIL_SCOPES = frozenset({
    GMAIL_READONLY_SCOPE,
    "https://www.googleapis.com/auth/gmail.modify",
    "https://mail.google.com/",
})


def has_gmail_permission(scopes: str | None) -> bool:
    return bool(READABLE_GMAIL_SCOPES.intersection((scopes or "").split()))


def google_account(db: Session, user_id: int) -> Account | None:
    return db.query(Account).filter(Account.user_id == user_id, Account.provider == "google").order_by(Account.id).first()


def connection_status(account: Account | None) -> str:
    if account is None:
        return "not_connected"
    if account.gmail_connection_status == "needs_reconnect":
        return "needs_reconnect"
    # NULL is the legacy representation. Never infer permission from app sign-in.
    if account.refresh_token_encrypted and has_gmail_permission(account.scopes):
        return "connected"
    return "needs_reconnect"


def connection_required_error(account: Account | None) -> HTTPException:
    verb = "Reconnect" if connection_status(account) == "needs_reconnect" else "Connect"
    return HTTPException(409, {
        "code": "gmail_connection_required",
        "message": f"{verb} Gmail to import your flights.",
        "action": "connect_gmail",
    })


def require_gmail_connection(db: Session, user_id: int) -> Account:
    account = google_account(db, user_id)
    if connection_status(account) != "connected":
        raise connection_required_error(account)
    return account


def is_gmail_authorization_error(exc: BaseException) -> bool:
    """Distinguish revoked grants/missing scopes from quota and network failures."""
    from google.auth.exceptions import RefreshError
    from googleapiclient.errors import HttpError

    seen = set()
    current = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, RefreshError):
            text = str(current).lower()
            if any(value in text for value in ("invalid_grant", "expired or revoked", "invalid_scope", "reauth")):
                return True
        if isinstance(current, HttpError):
            if current.resp.status == 401:
                return True
            if current.resp.status == 403:
                try:
                    error = json.loads(current.content).get("error", {})
                    reasons = {entry.get("reason") for entry in error.get("errors", []) + error.get("details", [])}
                    if reasons.intersection({"insufficientPermissions", "ACCESS_TOKEN_SCOPE_INSUFFICIENT", "authError"}):
                        return True
                except (ValueError, TypeError, AttributeError):
                    pass
        current = current.__cause__ or current.__context__
    return False


def mark_gmail_reconnect(db: Session, user_id: int, failed_token: bytes | None, exc: BaseException) -> bool:
    if failed_token is None or not is_gmail_authorization_error(exc):
        return False
    # An older in-flight job must not disconnect a newly replaced credential.
    return bool(db.query(Account).filter(
        Account.user_id == user_id, Account.provider == "google",
        Account.refresh_token_encrypted == failed_token,
    ).update({Account.gmail_connection_status: "needs_reconnect"}, synchronize_session=False))
