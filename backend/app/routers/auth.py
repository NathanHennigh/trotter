"""
backend/app/routers/auth.py  (full replacement)
Authentication endpoints — Google OAuth web flow + dev bypass.
"""

import os
import time
import secrets
from datetime import datetime
from typing import Optional
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Depends, status
from fastapi.responses import RedirectResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from sqlalchemy.orm import Session
import httpx

from ..db import get_db
from ..models import User, Account
from ..crypto import encrypt_refresh_token, decrypt_refresh_token
from ..auth import create_app_jwt, get_user_from_jwt

router   = APIRouter(prefix="/auth", tags=["auth"])
security = HTTPBearer()

import base64
import json

SCOPES = " ".join([
    "openid", "profile", "email",
    "https://www.googleapis.com/auth/gmail.readonly",
])


def _get_google_config():
    client_id     = os.getenv("GOOGLE_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
    backend_url   = os.getenv("BACKEND_URL", "http://localhost:8000")
    if not client_id or not client_secret:
        raise HTTPException(500, "Google OAuth not configured (GOOGLE_CLIENT_ID/SECRET missing)")
    return client_id, client_secret, backend_url


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


# ── Helpers ──────────────────────────────────────────────────────────────────

async def _exchange_code(code: str, redirect_uri: str) -> dict:
    client_id, client_secret, _ = _get_google_config()
    async with httpx.AsyncClient() as client:
        r = await client.post("https://oauth2.googleapis.com/token", data={
            "client_id":     client_id,
            "client_secret": client_secret,
            "code":          code,
            "grant_type":    "authorization_code",
            "redirect_uri":  redirect_uri,
        })
    if r.status_code != 200:
        raise HTTPException(400, f"Google token exchange failed: {r.text}")
    return r.json()


async def _verify_id_token(id_token_str: str) -> dict:
    from google.auth.transport import requests as greq
    from google.oauth2 import id_token
    client_id, _, _ = _get_google_config()
    try:
        info = id_token.verify_oauth2_token(id_token_str, greq.Request(), client_id)
        if info["iss"] not in ("accounts.google.com", "https://accounts.google.com"):
            raise ValueError("Wrong issuer")
        return info
    except ValueError as e:
        raise HTTPException(400, f"Invalid ID token: {e}")


def _upsert_user(db: Session, user_info: dict, refresh_token: str, scopes: str) -> User:
    email = user_info.get("email")
    if not email:
        raise HTTPException(400, "No email in ID token")
    user = db.query(User).filter(User.email == email).first()
    if not user:
        user = User(email=email, name=user_info.get("name"))
        db.add(user)
        db.flush()
    else:
        if user_info.get("name"):
            user.name = user_info["name"]
    encrypted = encrypt_refresh_token(refresh_token)
    account = db.query(Account).filter(
        Account.user_id == user.id, Account.provider == "google"
    ).first()
    if not account:
        account = Account(
            user_id=user.id, provider="google",
            refresh_token_encrypted=encrypted, scopes=scopes
        )
        db.add(account)
    else:
        account.refresh_token_encrypted = encrypted
        account.scopes = scopes
    db.commit()
    return user


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
    allowed = ("trotter://", "exp://", "com.trotter")
    if not any(app_redirect_uri.startswith(s) for s in allowed):
        raise HTTPException(400, "Disallowed redirect URI scheme")

    state_payload = {
        "uri": app_redirect_uri,
        "exp": time.time() + 600
    }
    state_bytes = json.dumps(state_payload).encode()
    state = base64.urlsafe_b64encode(state_bytes).decode().rstrip("=")

    callback_uri = f"{backend_url}/auth/google/callback"
    params = {
        "client_id":     client_id,
        "response_type": "code",
        "scope":         SCOPES,
        "redirect_uri":  callback_uri,
        "state":         state,
        "access_type":   "offline",
        "prompt":        "consent",
    }
    return RedirectResponse(
        url="https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)
    )


@router.get("/google/callback")
async def google_callback(code: str, state: str, db: Session = Depends(get_db)):
    """
    Step 2: Google redirects here after user consents.
    Exchange code → tokens → create app JWT → redirect back to app.
    """
    try:
        padding = "=" * (4 - len(state) % 4)
        state_bytes = base64.urlsafe_b64decode(state + padding)
        state_data = json.loads(state_bytes)
        if time.time() > state_data["exp"]:
            raise ValueError("Expired")
        app_redirect_uri = state_data["uri"]
    except Exception:
        raise HTTPException(400, "Invalid or expired OAuth state")
        
    _, _, backend_url = _get_google_config()
    callback_uri = f"{backend_url}/auth/google/callback"

    try:
        token_resp  = await _exchange_code(code, callback_uri)
        user_info   = await _verify_id_token(token_resp["id_token"])
        refresh_tok = token_resp.get("refresh_token")
        if not refresh_tok:
            raise HTTPException(400, "No refresh token returned — revoke app access in Google Account and retry")
        user = _upsert_user(db, user_info, refresh_tok, token_resp.get("scope", ""))
        jwt  = create_app_jwt(user.id, user.email)
        # Redirect back to app with token in query string
        sep = "&" if "?" in app_redirect_uri else "?"
        return RedirectResponse(url=f"{app_redirect_uri}{sep}token={jwt}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"OAuth callback failed: {e}")


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

@router.get("/me", response_model=UserInfo)
async def get_user_info(current_user: User = Depends(get_current_user)):
    return UserInfo(user_id=current_user.id, email=current_user.email, name=current_user.name)
