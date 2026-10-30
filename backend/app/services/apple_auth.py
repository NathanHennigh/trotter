"""Native Apple authentication, with server-bound nonces and revocable grants.

Only Apple's fixed issuer/JWKS/token endpoints are contacted. A native ID token
alone is insufficient: its single-use code must yield a matching verified token.
"""
from __future__ import annotations

import hashlib
import hmac
import os
from pathlib import Path
import time

from fastapi import HTTPException
import httpx
import jwt
from starlette.concurrency import run_in_threadpool

ISSUER = "https://appleid.apple.com"
_keys = jwt.PyJWKClient(f"{ISSUER}/auth/keys", lifespan=3600, timeout=10)


def apple_config() -> tuple[str, str, str, str]:
    client_id = os.getenv("APPLE_CLIENT_ID", "").strip()
    team_id = os.getenv("APPLE_TEAM_ID", "").strip()
    key_id = os.getenv("APPLE_KEY_ID", "").strip()
    private_key = os.getenv("APPLE_PRIVATE_KEY", "").replace("\\n", "\n").strip()
    key_path = os.getenv("APPLE_PRIVATE_KEY_FILE", "").strip()
    if not private_key and key_path:
        try:
            private_key = Path(key_path).read_text(encoding="utf-8")
        except OSError as exc:
            raise HTTPException(503, "apple_signin_unavailable") from exc
    if not all((client_id, team_id, key_id, private_key)):
        raise HTTPException(503, "apple_signin_unavailable")
    return client_id, team_id, key_id, private_key


def client_secret() -> tuple[str, str]:
    client_id, team_id, key_id, private_key = apple_config()
    now = int(time.time())
    try:
        secret = jwt.encode({"iss": team_id, "iat": now, "exp": now + 300,
                             "aud": ISSUER, "sub": client_id}, private_key,
                            algorithm="ES256", headers={"kid": key_id})
    except (ValueError, jwt.PyJWTError) as exc:
        raise HTTPException(503, "apple_signin_unavailable") from exc
    return client_id, secret


def nonce_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _verify(token: str, expected_nonce_hash: str) -> dict:
    client_id = apple_config()[0]
    try:
        header = jwt.get_unverified_header(token)
        if header.get("alg") != "RS256" or not isinstance(header.get("kid"), str):
            raise jwt.InvalidTokenError("Unsupported Apple key")
        signing_key = _keys.get_signing_key_from_jwt(token)
        info = jwt.decode(token, signing_key.key, algorithms=["RS256"], issuer=ISSUER,
                          audience=client_id, options={"require": ["sub", "iat", "exp", "iss", "aud", "nonce"]})
        nonce = info.get("nonce")
        subject = info.get("sub")
        if not isinstance(subject, str) or not subject or len(subject) > 255:
            raise jwt.InvalidTokenError("Missing Apple subject")
        if not isinstance(nonce, str) or not hmac.compare_digest(nonce_hash(nonce), expected_nonce_hash):
            raise jwt.InvalidTokenError("Wrong Apple nonce")
        if info.get("email") and not (info.get("email_verified") is True or info.get("email_verified") == "true"):
            raise jwt.InvalidTokenError("Unverified Apple email")
        return info
    except jwt.PyJWKClientConnectionError as exc:
        raise HTTPException(503, "apple_signin_unavailable") from exc
    except (jwt.PyJWTError, ValueError, TypeError) as exc:
        raise HTTPException(400, "invalid_apple_credential") from exc


async def verify_identity_token(token: str, expected_nonce_hash: str) -> dict:
    return await run_in_threadpool(_verify, token, expected_nonce_hash)


async def exchange_authorization_code(code: str) -> dict:
    client_id, secret = client_secret()
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(f"{ISSUER}/auth/token", data={
                "client_id": client_id, "client_secret": secret,
                "grant_type": "authorization_code", "code": code,
            })
        if response.status_code >= 500 or response.status_code == 429:
            raise HTTPException(503, "apple_signin_unavailable")
        if response.status_code != 200:
            raise HTTPException(400, "invalid_apple_credential")
        result = response.json()
        if not isinstance(result.get("id_token"), str) or not isinstance(result.get("refresh_token"), str) or not result["refresh_token"]:
            raise HTTPException(503, "apple_signin_unavailable")
        return result
    except (httpx.RequestError, ValueError) as exc:
        raise HTTPException(503, "apple_signin_unavailable") from exc


async def revoke_refresh_token(refresh_token: str) -> None:
    client_id, secret = client_secret()
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(f"{ISSUER}/auth/revoke", data={
                "client_id": client_id, "client_secret": secret,
                "token": refresh_token, "token_type_hint": "refresh_token",
            })
        # Apple responds 200 when the token was already revoked, making retry safe.
        if response.status_code != 200:
            raise HTTPException(503, "account_deletion_retry")
    except httpx.RequestError as exc:
        raise HTTPException(503, "account_deletion_retry") from exc
