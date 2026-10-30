"""
backend/app/routers/auth.py  (full replacement)
Authentication endpoints — Google OAuth web flow + dev bypass.
"""

import os
import time
import uuid
import secrets
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional
from urllib.parse import urlencode, urlsplit, parse_qsl, urlunsplit

import jwt
from fastapi import APIRouter, HTTPException, Depends, status
from fastapi.responses import RedirectResponse, JSONResponse, Response
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
from sqlalchemy import update, delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
import httpx

from ..db import get_db
from ..models import User, Account, AuthIdentity, AppleAuthChallenge
from ..crypto import encrypt_refresh_token
from ..auth import create_app_jwt, get_jwt_secret, get_user_from_jwt, verify_app_jwt
from ..services.gmail_connection import GMAIL_READONLY_SCOPE, connection_status, google_account, has_gmail_permission
from ..services import apple_auth, auth_identities

router   = APIRouter(prefix="/auth", tags=["auth"])
security = HTTPBearer()
optional_security = HTTPBearer(auto_error=False)

SCOPES = "openid profile email"
OAUTH_HEADERS = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}


def _get_google_config():
    client_id     = os.getenv("GOOGLE_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
    backend_url   = os.getenv("BACKEND_URL", "http://localhost:8000")
    if not client_id or not client_secret:
        raise HTTPException(500, "Google OAuth not configured (GOOGLE_CLIENT_ID/SECRET missing)")
    return client_id, client_secret, backend_url


def _is_allowed_app_redirect(app_redirect_uri: str) -> bool:
    try:
        if any(ord(char) < 32 for char in app_redirect_uri) or "\\" in app_redirect_uri:
            return False
        uri = urlsplit(app_redirect_uri)
        if uri.fragment or uri.username or uri.password or len(app_redirect_uri) > 2048:
            return False
        pairs = parse_qsl(uri.query, keep_blank_values=True)
        params = dict(pairs)
        if len(params) != len(pairs) or set(params) - {"attempt", "flow"}:
            return False
        if "flow" in params and params["flow"] not in {"gmail", "reauth"}:
            return False


        if "attempt" in params:
            uuid.UUID(params["attempt"])
        base = urlunsplit((uri.scheme, uri.netloc, uri.path, "", ""))
        native = {f"{scheme}://oauthredirect" for scheme in ("trotter", "trotterv2", "com.trotter")}
        if base in native:
            return True
        # Expo callbacks are for local development only; never allow arbitrary
        # native paths, lookalike schemes, web paths, fragments or query payloads.
        if os.getenv("DEV_MODE", "").lower() in ("true", "1", "yes") and uri.scheme == "exp":
            return bool(uri.netloc) and uri.path == "/--/oauthredirect"
        web_app_url = os.getenv("WEB_APP_URL", "").rstrip("/")
        return bool(web_app_url) and base == f"{web_app_url}/oauthredirect"
    except ValueError:
        return False


def _redirect_matches_purpose(app_redirect_uri: str, purpose: str) -> bool:
    flow = dict(parse_qsl(urlsplit(app_redirect_uri).query)).get("flow")
    return flow is None or flow == purpose


def _create_oauth_state(app_redirect_uri: str, purpose: str = "identity", user_id: int | None = None) -> str:
    now = int(time.time())
    return jwt.encode(
        {
            "uri": app_redirect_uri,
            "purpose": purpose,
            "user_id": user_id,
            "jti": str(uuid.uuid4()),
            "iat": now,
            "exp": now + 600,
            "iss": "trotter-oauth",
            "aud": "trotter-oauth-callback",
        },
        get_jwt_secret(),
        algorithm="HS256",
    )


def _decode_oauth_state(state: str) -> dict:
    state_data = jwt.decode(
        state,
        get_jwt_secret(),
        algorithms=["HS256"],
        issuer="trotter-oauth",
        audience="trotter-oauth-callback",
        options={"require": ["iat", "exp", "uri"]},
    )
    app_redirect_uri = state_data["uri"]
    if not isinstance(app_redirect_uri, str) or not _is_allowed_app_redirect(app_redirect_uri):
        raise ValueError("Disallowed redirect")
    purpose = state_data.get("purpose", "identity")
    if purpose not in {"identity", "gmail", "reauth"}:
        raise ValueError("Invalid OAuth purpose")
    if purpose in {"gmail", "reauth"} and (type(state_data.get("user_id")) is not int or state_data["user_id"] < 1):
        raise ValueError("Missing connection owner")
    if "purpose" in state_data:
        uuid.UUID(state_data["jti"])
    state_data["purpose"] = purpose
    return state_data


# ── Schema models ────────────────────────────────────────────────────────────

class GoogleAuthResponse(BaseModel):
    access_token: str
    user_id: int
    email: str
    name: Optional[str] = None


class UserInfo(BaseModel):
    user_id: int
    email: str
    name: Optional[str] = None
    gmail_connected: bool = False
    gmail_connection_status: str = "not_connected"
    auth_providers: list[str] = Field(default_factory=list)


class GmailStartRequest(BaseModel):
    app_redirect_uri: str


# ── Helpers ──────────────────────────────────────────────────────────────────

async def _exchange_code(code: str, redirect_uri: str) -> dict:
    client_id, client_secret, _ = _get_google_config()
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.post("https://oauth2.googleapis.com/token", data={
                "client_id":     client_id,
                "client_secret": client_secret,
                "code":          code,
                "grant_type":    "authorization_code",
                "redirect_uri":  redirect_uri,
            })
    except httpx.RequestError as exc:
        raise HTTPException(502, "Google token exchange request failed") from exc
    if r.status_code != 200:
        raise HTTPException(400, "Google token exchange failed")
    return r.json()


async def _verify_id_token(id_token_str: str) -> dict:
    from google.auth.transport import requests as greq
    from google.oauth2 import id_token
    client_id, _, _ = _get_google_config()
    try:
        info = id_token.verify_oauth2_token(id_token_str, greq.Request(), client_id)
        if info["iss"] not in ("accounts.google.com", "https://accounts.google.com"):
            raise ValueError("Wrong issuer")
        # Flight invitations are addressed to an email, so a signed identity
        # token alone is insufficient unless Google verified that address.
        if info.get("email_verified") is not True:
            raise ValueError("Google has not verified this email address")
        auth_identities.subject_from(info)
        return info
    except ValueError as e:
        raise HTTPException(400, f"Invalid ID token: {e}")


def _upsert_user(db: Session, user_info: dict) -> User:
    user = auth_identities.resolve_google_user(db, user_info)
    if user_info.get("name"):
        user.name = user_info["name"]
    db.commit()
    return user


def _oauth_redirect(uri: str, **params: str) -> RedirectResponse:
    parts = urlsplit(uri)
    if "token" in params and parts.scheme in {"https", "http"}:
        target = urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, urlencode(params)))
    else:
        query = urlencode([*parse_qsl(parts.query), *params.items()])
        target = urlunsplit((parts.scheme, parts.netloc, parts.path, query, ""))
    return RedirectResponse(target, headers=OAUTH_HEADERS)


def _connect_gmail(db: Session, user_id: int, user_info: dict, token_resp: dict) -> str | None:
    # The initiating app account owns this connection, even when another Google
    # account is selected in the consent dialog. Never switch/sign in here.
    user = db.query(User).filter(User.id == user_id).with_for_update().first()
    if not user:
        return "gmail_wrong_account"
    scopes = token_resp.get("scope", "")
    if not isinstance(scopes, str) or not has_gmail_permission(scopes):
        return "gmail_permission_required"
    account = google_account(db, user_id)
    refresh = token_resp.get("refresh_token")
    if not refresh and connection_status(account) != "connected":
        return "gmail_refresh_required"
    try:
        auth_identities.link_google_for_gmail(db, user, user_info)
    except HTTPException:
        return "gmail_wrong_account"
    if account is None:
        account = Account(user_id=user_id, provider="google", scopes=scopes,
                          refresh_token_encrypted=encrypt_refresh_token(refresh))
        db.add(account)
    elif refresh:
        account.refresh_token_encrypted = encrypt_refresh_token(refresh)
        account.scopes = scopes
    # Without a new refresh token retain the complete original credential/scope
    # pair. A denied/incomplete flow never overwrites a working connection.
    account.gmail_connection_status = "connected"
    db.commit()
    return None


# ── OAuth web flow (works in Expo Go — no native modules needed) ─────────────

@router.get("/google/start")
async def google_start(app_redirect_uri: str):
    """
    Step 1: Redirect the device browser to Google's consent screen.
    
    The mobile app calls:
        WebBrowser.openAuthSessionAsync(
            `{BACKEND_URL}/auth/google/start?app_redirect_uri={encodedDeepLink}`,
            deepLink
        )
    """
    client_id, _, backend_url = _get_google_config()

    # Validate the app redirect URI — only allow known schemes
    if not _is_allowed_app_redirect(app_redirect_uri) or not _redirect_matches_purpose(app_redirect_uri, "identity"):
        raise HTTPException(400, "Disallowed redirect URI scheme")

    state = _create_oauth_state(app_redirect_uri)

    callback_uri = f"{backend_url}/auth/google/callback"
    params = {
        "client_id":     client_id,
        "response_type": "code",
        "scope":         SCOPES,
        "redirect_uri":  callback_uri,
        "state":         state,
        "nonce":         _decode_oauth_state(state)["jti"],
    }
    return RedirectResponse(
        url="https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params), headers=OAUTH_HEADERS,
    )


@router.get("/google/callback")
async def google_callback(state: str, code: str | None = None, error: str | None = None, db: Session = Depends(get_db)):
    """
    Step 2: Google redirects here after user consents.
    Exchange code → tokens → create app JWT → redirect back to app.
    """
    try:
        state_data = _decode_oauth_state(state)
    except Exception:
        raise HTTPException(400, "Invalid or expired OAuth state")
        
    app_redirect_uri = state_data["uri"]
    is_gmail = state_data["purpose"] == "gmail"
    is_reauth = state_data["purpose"] == "reauth"
    if error or not code:
        return _oauth_redirect(app_redirect_uri, error="access_denied" if error == "access_denied" else ("gmail_connect_failed" if is_gmail else "oauth_failed"))
    _, _, backend_url = _get_google_config()
    callback_uri = f"{backend_url}/auth/google/callback"

    try:
        token_resp  = await _exchange_code(code, callback_uri)
        user_info   = await _verify_id_token(token_resp["id_token"])
        # A valid signed ID token must also belong to this authorization attempt.
        # Old identity states may finish during their existing 10-minute expiry.
        if state_data.get("jti") and user_info.get("nonce") != state_data["jti"]:
            raise HTTPException(400, "Google authorization attempt did not match")
        if is_reauth:
            user = auth_identities.resolve_google_user(db, user_info, expected_user_id=state_data["user_id"])
            db.commit()
            return _oauth_redirect(app_redirect_uri, token=create_app_jwt(user.id, user.email))
        if is_gmail:
            failure = _connect_gmail(db, state_data["user_id"], user_info, token_resp)
            if failure:
                db.rollback()
                return _oauth_redirect(app_redirect_uri, error=failure)
            return _oauth_redirect(app_redirect_uri, gmail="connected")
        user = _upsert_user(db, user_info)
        return _oauth_redirect(app_redirect_uri, token=create_app_jwt(user.id, user.email))
    except Exception as exc:
        db.rollback()
        if is_reauth:
            return _oauth_redirect(app_redirect_uri, error="reauth_wrong_account" if isinstance(exc, HTTPException) and exc.status_code == 409 else "oauth_failed")
        if isinstance(exc, HTTPException) and exc.detail == "account_link_required":
            return _oauth_redirect(app_redirect_uri, error="account_link_required")
        return _oauth_redirect(app_redirect_uri, error="gmail_connect_failed" if is_gmail else "oauth_failed")


# ── Dev bypass ───────────────────────────────────────────────────────────────

@router.get("/dev-token", response_model=GoogleAuthResponse)
async def dev_token(db: Session = Depends(get_db)):
    """
    Returns a real JWT for a dev test user.
    Only available when DEV_MODE=true in the backend .env.
    Lets you test the full import/API flow without Google OAuth.
    """
    dev_mode = os.getenv("DEV_MODE", "").lower() in ("1", "true", "yes")
    if not dev_mode:
        raise HTTPException(403, "dev-token is only available when DEV_MODE=true")

    email = "dev@localhost"
    user  = db.query(User).filter(User.email == email).first()
    if not user:
        user = User(email=email, name="Dev User")
        db.add(user)
        db.commit()
        db.refresh(user)

    jwt = create_app_jwt(user.id, user.email)
    return GoogleAuthResponse(access_token=jwt, user_id=user.id, email=user.email, name=user.name)


# ── Current user dependency (used by /me and other routers) ─────────────────

def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    token     = credentials.credentials
    user_info = get_user_from_jwt(token)
    if not user_info:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")
    user = db.query(User).filter(User.id == user_info["user_id"]).first()
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found")
    return user


# ── JWT endpoints ─────────────────────────────────────────────────────────────

@router.post("/google/gmail/start")
async def gmail_start(body: GmailStartRequest, current_user: User = Depends(get_current_user),
                      credentials: HTTPAuthorizationCredentials = Depends(security), db: Session = Depends(get_db)):
    client_id, _, backend_url = _get_google_config()
    if not _is_allowed_app_redirect(body.app_redirect_uri) or not _redirect_matches_purpose(body.app_redirect_uri, "gmail"):
        raise HTTPException(400, "Disallowed redirect URI scheme")
    if (db.query(AuthIdentity).filter_by(user_id=current_user.id, provider="apple").first()
            and not db.query(AuthIdentity).filter_by(user_id=current_user.id, provider="google").first()):
        # The first Gmail connection also grants a new Google login method.
        # Treat enrolling it with the same recent-auth boundary as Apple linking.
        _recent_auth(credentials)
    state = _create_oauth_state(body.app_redirect_uri, "gmail", current_user.id)
    params = {
        "client_id": client_id, "response_type": "code",
        "scope": f"{SCOPES} {GMAIL_READONLY_SCOPE}",
        "redirect_uri": f"{backend_url}/auth/google/callback",
        "state": state, "nonce": _decode_oauth_state(state)["jti"],
        "access_type": "offline", "prompt": "consent", "include_granted_scopes": "true",
    }
    if not current_user.email.endswith("@privaterelay.appleid.com"):
        params["login_hint"] = current_user.email
    return JSONResponse({"url": "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)}, headers=OAUTH_HEADERS)

@router.get("/me", response_model=UserInfo)
async def get_user_info(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    gmail_status = connection_status(google_account(db, current_user.id))
    return UserInfo(user_id=current_user.id, email=current_user.email, name=current_user.name,
                    gmail_connected=gmail_status == "connected", gmail_connection_status=gmail_status,
                    auth_providers=auth_identities.providers(db, current_user.id))


@router.post("/google/reauth/start")
async def google_reauth_start(body: GmailStartRequest, current_user: User = Depends(get_current_user)):
    client_id, _, backend_url = _get_google_config()
    if not _is_allowed_app_redirect(body.app_redirect_uri) or not _redirect_matches_purpose(body.app_redirect_uri, "reauth"):
        raise HTTPException(400, "Disallowed redirect URI scheme")
    state = _create_oauth_state(body.app_redirect_uri, "reauth", current_user.id)
    params = {
        "client_id": client_id, "response_type": "code", "scope": SCOPES,
        "redirect_uri": f"{backend_url}/auth/google/callback", "state": state,
        "nonce": _decode_oauth_state(state)["jti"], "prompt": "select_account",
    }
    return JSONResponse({"url": "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)}, headers=OAUTH_HEADERS)


def _recent_auth(credentials: HTTPAuthorizationCredentials | None) -> dict:
    if credentials is None:
        raise HTTPException(401, "authentication_required")
    try:
        claims = verify_app_jwt(credentials.credentials)
        issued = claims.get("iat")
        if type(issued) not in (int, float) or not 0 <= time.time() - issued <= 600:
            raise HTTPException(403, "reauthentication_required")
        return claims
    except jwt.InvalidTokenError as exc:
        raise HTTPException(401, "Invalid or expired token") from exc


class AppleChallengeRequest(BaseModel):
    purpose: Literal["signin", "link", "reauth"] = "signin"


class AppleAuthRequest(BaseModel):
    challenge_id: str = Field(min_length=36, max_length=36)
    identity_token: str = Field(min_length=1, max_length=16384)
    authorization_code: str = Field(min_length=1, max_length=4096)
    name: str | None = Field(default=None, max_length=255)


def _optional_user(credentials, db: Session):
    return get_current_user(credentials, db) if credentials else None


@router.post("/apple/challenge")
async def apple_challenge(body: AppleChallengeRequest,
                          credentials: HTTPAuthorizationCredentials | None = Depends(optional_security),
                          db: Session = Depends(get_db)):
    apple_auth.apple_config()
    user = _optional_user(credentials, db)
    if body.purpose != "signin" and user is None:
        raise HTTPException(401, "authentication_required")
    if body.purpose == "link":
        _recent_auth(credentials)
        if not db.query(AuthIdentity).filter_by(user_id=user.id).first():
            # Bootstrap the legacy Google subject through reauth before adding
            # Apple, so the original Google login cannot be orphaned.
            raise HTTPException(403, "reauthentication_required")
    now = datetime.now(timezone.utc)
    nonce = secrets.token_urlsafe(32)
    challenge = AppleAuthChallenge(id=str(uuid.uuid4()), nonce_hash=apple_auth.nonce_hash(nonce),
        purpose=body.purpose, user_id=user.id if body.purpose != "signin" else None,
        expires_at=now + timedelta(minutes=5))
    # Expired challenges carry no identity data worth retaining.
    db.execute(delete(AppleAuthChallenge).where(AppleAuthChallenge.expires_at < now))
    db.add(challenge)
    db.commit()
    return JSONResponse({"challenge_id": challenge.id, "nonce": nonce, "expires_in": 300}, headers=OAUTH_HEADERS)


@router.post("/apple", response_model=GoogleAuthResponse)
async def apple_signin(body: AppleAuthRequest,
                       credentials: HTTPAuthorizationCredentials | None = Depends(optional_security),
                       db: Session = Depends(get_db)):
    user = _optional_user(credentials, db)
    challenge = db.get(AppleAuthChallenge, body.challenge_id)
    if challenge is None:
        raise HTTPException(400, "invalid_apple_challenge")
    purpose, owner_id, expected_nonce = challenge.purpose, challenge.user_id, challenge.nonce_hash
    if purpose != "signin" and (user is None or user.id != owner_id):
        raise HTTPException(403, "apple_challenge_wrong_account")
    if purpose == "link":
        _recent_auth(credentials)
        if not db.query(AuthIdentity).filter_by(user_id=user.id).first():
            raise HTTPException(403, "reauthentication_required")
    now = datetime.now(timezone.utc)
    consumed = db.execute(update(AppleAuthChallenge).where(
        AppleAuthChallenge.id == challenge.id, AppleAuthChallenge.consumed_at.is_(None),
        AppleAuthChallenge.expires_at > now).values(consumed_at=now),
        execution_options={"synchronize_session": False}).rowcount
    if consumed != 1:
        db.rollback()
        raise HTTPException(400, "invalid_apple_challenge")
    # Commit the one-time consumption before contacting Apple; failed attempts
    # need a new challenge, including after a process crash or concurrent replay.
    db.commit()
    info = await apple_auth.verify_identity_token(body.identity_token, expected_nonce)
    grant = await apple_auth.exchange_authorization_code(body.authorization_code)
    exchanged = await apple_auth.verify_identity_token(grant["id_token"], expected_nonce)
    if exchanged["sub"] != info["sub"]:
        raise HTTPException(400, "invalid_apple_credential")
    linked = auth_identities.identity(db, "apple", info["sub"])
    if purpose in {"link", "reauth"}:
        user = db.query(User).filter_by(id=owner_id).with_for_update().first()
        if user is None:
            raise HTTPException(401, "User not found")
        if linked and linked.user_id != user.id:
            raise HTTPException(409, "reauth_wrong_account" if purpose == "reauth" else "apple_account_already_linked")
        if purpose == "reauth" and not linked:
            raise HTTPException(409, "reauth_wrong_account")
        owned = db.query(AuthIdentity).filter_by(user_id=user.id, provider="apple").first()
        if owned and owned.subject != info["sub"]:
            raise HTTPException(409, "apple_account_already_linked")
        if not linked and info.get("email"):
            email_owner = auth_identities.email_owner(db, info["email"])
            if email_owner and email_owner.id != user.id:
                raise HTTPException(409, "account_link_required")
    elif linked:
        user = db.get(User, linked.user_id)
    else:
        email = info.get("email")
        if not isinstance(email, str) or not email or len(email) > 255:
            raise HTTPException(400, "apple_email_required")
        if auth_identities.email_owner(db, email):
            raise HTTPException(409, "account_link_required")
        user = User(email=email, name=(body.name or "").strip() or None)
        db.add(user)
    try:
        db.flush()
        if not linked:
            linked = AuthIdentity(user_id=user.id, provider="apple", subject=info["sub"], email=info.get("email"))
            db.add(linked)
        elif info.get("email"):
            email = info["email"]
            if not isinstance(email, str) or len(email) > 255:
                raise HTTPException(400, "invalid_provider_email")
            email_owner = auth_identities.email_owner(db, email)
            if email_owner and email_owner.id != user.id:
                raise HTTPException(409, "account_link_required")
            if linked.email and user.email.casefold() == linked.email.casefold():
                user.email = email
            linked.email = email
        linked.refresh_token_encrypted = encrypt_refresh_token(grant["refresh_token"])
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "account_link_required") from exc
    return JSONResponse({"access_token": create_app_jwt(user.id, user.email), "user_id": user.id,
                         "email": user.email, "name": user.name}, headers=OAUTH_HEADERS)


class AccountDeletionRequest(BaseModel):
    confirmation: Literal["DELETE"]


@router.get("/account/deletion-preview")
def deletion_preview(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from ..services.account_deletion import preview
    return JSONResponse(preview(db, current_user.id), headers=OAUTH_HEADERS)


@router.delete("/account", status_code=204)
async def delete_account(body: AccountDeletionRequest,
                         credentials: HTTPAuthorizationCredentials = Depends(security),
                         current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from ..services.account_deletion import clean_thumbnails, erase_database, revoke_connections
    _recent_auth(credentials)
    user = db.query(User).filter_by(id=current_user.id).with_for_update().first()
    if user is None:
        raise HTTPException(401, "User not found")
    await revoke_connections(db, user.id)
    cleanup_id = erase_database(db, user)
    db.commit()
    try:
        clean_thumbnails(db, cleanup_id)
    except Exception:
        # The account is already erased and the cleanup row is durable. Do not
        # report deletion failure because the optional immediate sweep failed.
        db.rollback()
    return Response(status_code=204, headers=OAUTH_HEADERS)
