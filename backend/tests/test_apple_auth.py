"""iPhone authentication security and account isolation, entirely offline."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlparse

from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
import jwt
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.auth import create_app_jwt
from app.crypto import decrypt_refresh_token, encrypt_refresh_token, generate_encryption_key
from app.db import get_db
from app.main import app
from app.models import Account, AppleAuthChallenge, AuthIdentity, Base, User
from app.routers import auth
from app.services import apple_auth, auth_identities


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "offline-account-test-secret-at-least-32-bytes")
    monkeypatch.setenv("ENCRYPTION_KEY", generate_encryption_key())
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "test.apps.googleusercontent.com")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "offline-test")
    monkeypatch.setenv("APPLE_CLIENT_ID", "com.trotter.mobilev2")
    monkeypatch.setenv("APPLE_TEAM_ID", "TEAM123456")
    monkeypatch.setenv("APPLE_KEY_ID", "KEY1234567")
    monkeypatch.setenv("APPLE_PRIVATE_KEY", "offline-test-key-never-sent")


@pytest.fixture
def db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'ios-auth.db'}", connect_args={"check_same_thread": False})
    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    def request_db():
        with factory() as session:
            yield session
    app.dependency_overrides[get_db] = request_db
    with factory() as session:
        yield session
    app.dependency_overrides.clear()
    engine.dispose()


@pytest.fixture
def client(env, db):
    return TestClient(app)


def headers(user):
    return {"Authorization": f"Bearer {create_app_jwt(user.id, user.email)}"}


def user(db, email="existing@example.com", provider="google", subject="google-existing"):
    row = User(email=email, name="Existing Traveller")
    db.add(row)
    db.flush()
    if provider:
        db.add(AuthIdentity(user_id=row.id, provider=provider, subject=subject, email=email))
    db.commit()
    return row


@pytest.fixture
def provider(monkeypatch):
    info = {"sub": "apple-subject", "email": "private@privaterelay.appleid.com", "email_verified": True}
    verify = AsyncMock(return_value=info)
    exchange = AsyncMock(return_value={"id_token": "exchanged-token", "refresh_token": "apple-refresh"})
    monkeypatch.setattr(apple_auth, "verify_identity_token", verify)
    monkeypatch.setattr(apple_auth, "exchange_authorization_code", exchange)
    return info, verify, exchange


def challenge(client, purpose="signin", bearer=None):
    response = client.post("/auth/apple/challenge", json={"purpose": purpose}, headers=bearer or {})
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    return response.json()


def complete(client, data, bearer=None, **extra):
    return client.post("/auth/apple", headers=bearer or {}, json={
        "challenge_id": data["challenge_id"], "identity_token": "native-token",
        "authorization_code": "one-use-code", **extra})


def test_challenges_random_and_link_requires_authenticated_recent_account(client, db, monkeypatch):
    first, second = challenge(client), challenge(client)
    assert first["nonce"] != second["nonce"] and first["challenge_id"] != second["challenge_id"]
    assert first["expires_in"] == 300
    stored = db.get(AppleAuthChallenge, first["challenge_id"])
    assert stored.nonce_hash == apple_auth.nonce_hash(first["nonce"])
    for purpose in ("link", "reauth"):
        assert client.post("/auth/apple/challenge", json={"purpose": purpose}).status_code == 401
    row = user(db)
    old = jwt.decode(create_app_jwt(row.id, row.email), options={"verify_signature": False})
    old["iat"] = int(time.time()) - 601
    import os
    bearer = {"Authorization": "Bearer " + jwt.encode(old, os.environ["JWT_SECRET"], algorithm="HS256")}
    assert client.post("/auth/apple/challenge", json={"purpose": "link"}, headers=bearer).json()["detail"] == "reauthentication_required"
    monkeypatch.delenv("APPLE_KEY_ID")
    assert client.post("/auth/apple/challenge", json={}).status_code == 503


def test_signin_keeps_apple_refresh_encrypted_and_does_not_connect_gmail(client, db, provider):
    data = challenge(client)
    response = complete(client, data, name="New Traveller")
    assert response.status_code == 200, response.text
    result = response.json()
    saved = db.query(AuthIdentity).one()
    assert saved.provider == "apple"
    assert saved.refresh_token_encrypted != b"apple-refresh"
    assert decrypt_refresh_token(saved.refresh_token_encrypted) == "apple-refresh"
    assert db.query(Account).count() == 0
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {result['access_token']}"}).json()["auth_providers"] == ["apple"]
    provider[1].assert_any_await("native-token", apple_auth.nonce_hash(data["nonce"]))
    provider[1].assert_any_await("exchanged-token", apple_auth.nonce_hash(data["nonce"]))
    assert complete(client, data).json()["detail"] == "invalid_apple_challenge"
    assert provider[2].await_count == 1


def test_repeated_signin_without_email_uses_subject_and_retains_profile(client, db, provider):
    first = complete(client, challenge(client), name="First Name").json()
    provider[0].pop("email")
    second = complete(client, challenge(client), name="Untrusted Changed Name").json()
    assert second["user_id"] == first["user_id"]
    assert second["email"] == first["email"]
    assert second["name"] == "First Name"
    assert db.query(User).count() == 1


def test_updated_apple_email_replaces_old_verified_alias(client, db, provider):
    first = complete(client, challenge(client)).json()
    provider[0]["email"] = "new-relay@privaterelay.appleid.com"
    second = complete(client, challenge(client)).json()
    assert second["user_id"] == first["user_id"] and second["email"] == provider[0]["email"]
    db.expire_all()
    assert auth_identities.verified_emails(db, db.get(User, first["user_id"])) == {provider[0]["email"]}


def test_apple_matching_google_email_never_silently_merges(client, db, provider):
    existing = user(db, email=provider[0]["email"])
    result = complete(client, challenge(client))
    assert result.status_code == 409 and result.json()["detail"] == "account_link_required"
    assert db.query(User).count() == 1
    linked = complete(client, challenge(client, "link", headers(existing)), headers(existing))
    assert linked.status_code == 200
    assert linked.json()["user_id"] == existing.id
    assert db.query(AuthIdentity).count() == 2


def test_link_challenge_cannot_be_completed_by_other_account(client, db, provider):
    owner = user(db)
    other = user(db, "other@example.com", subject="google-other")
    data = challenge(client, "link", headers(owner))
    assert complete(client, data, headers(other)).status_code == 403
    provider[1].assert_not_called()
    assert complete(client, data, headers(owner)).status_code == 200


def test_reauth_never_creates_or_links_another_apple_identity(client, db, provider):
    existing = user(db, provider="apple", subject="correct-apple")
    response = complete(client, challenge(client, "reauth", headers(existing)), headers(existing))
    assert response.status_code == 409 and response.json()["detail"] == "reauth_wrong_account"
    assert db.query(User).count() == 1
    assert db.query(AuthIdentity).count() == 1


def test_code_and_identity_token_must_match_subject(client, db, provider):
    provider[1].side_effect = [{"sub": "native-user"}, {"sub": "code-for-different-user"}]
    assert complete(client, challenge(client)).json()["detail"] == "invalid_apple_credential"
    assert db.query(User).count() == 0


def test_consumption_is_atomic_under_concurrent_replay(client, db, provider):
    data = challenge(client)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: complete(client, data).status_code, range(2)))
    assert sorted(results) == [200, 400]
    assert provider[2].await_count == 1
    assert db.query(User).count() == 1


def test_expired_challenge_does_not_contact_apple(client, db, provider):
    data = challenge(client)
    stored = db.get(AppleAuthChallenge, data["challenge_id"])
    stored.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.commit()
    assert complete(client, data).status_code == 400
    provider[1].assert_not_called()


@pytest.fixture(scope="module")
def rsa_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.mark.parametrize("change", [
    {"aud": "another.app"}, {"iss": "https://attacker.example"}, {"nonce": "wrong"},
    {"exp": 1}, {"iat": 99999999999}, {"email_verified": False}, {"email_verified": "false"},
    {"sub": ""}, {"nonce": None}, {"email_verified": 1},
])
def test_real_apple_signature_claims_are_validated(env, monkeypatch, rsa_key, change):
    monkeypatch.setattr(apple_auth._keys, "get_signing_key_from_jwt", lambda _: SimpleNamespace(key=rsa_key.public_key()))
    info = {"sub": "apple-real-sub", "iss": apple_auth.ISSUER, "aud": "com.trotter.mobilev2",
            "iat": int(time.time()), "exp": int(time.time()) + 300, "nonce": "server-nonce",
            "email": "private@example.com", "email_verified": "true", **change}
    token = jwt.encode(info, rsa_key, algorithm="RS256", headers={"kid": "apple-key"})
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as failure:
        asyncio.run(apple_auth.verify_identity_token(token, apple_auth.nonce_hash("server-nonce")))
    assert failure.value.status_code == 400


def test_real_apple_signature_accepts_valid_token_and_rejects_forgery(env, monkeypatch, rsa_key):
    monkeypatch.setattr(apple_auth._keys, "get_signing_key_from_jwt", lambda _: SimpleNamespace(key=rsa_key.public_key()))
    info = {"sub": "apple-sub", "iss": apple_auth.ISSUER, "aud": "com.trotter.mobilev2",
            "iat": int(time.time()), "exp": int(time.time()) + 300, "nonce": "server-nonce"}
    token = jwt.encode(info, rsa_key, algorithm="RS256", headers={"kid": "apple-key"})
    assert asyncio.run(apple_auth.verify_identity_token(token, apple_auth.nonce_hash("server-nonce")))["sub"] == "apple-sub"
    forged = jwt.encode(info, "not-apple-secret", algorithm="HS256", headers={"kid": "apple-key"})
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        asyncio.run(apple_auth.verify_identity_token(forged, apple_auth.nonce_hash("server-nonce")))


def test_hidden_email_gmail_connect_links_verified_google_subject_not_new_user(client, db, monkeypatch):
    owner = user(db, "private@privaterelay.appleid.com", "apple", "apple-private")
    info = {"sub": "google-private", "email": "real@gmail.com", "email_verified": True}
    start = client.post("/auth/google/gmail/start", headers=headers(owner), json={"app_redirect_uri": "trotterv2://oauthredirect"})
    params = parse_qs(urlparse(start.json()["url"]).query)
    assert "login_hint" not in params
    info["nonce"] = params["nonce"][0]
    monkeypatch.setattr(auth, "_verify_id_token", AsyncMock(return_value=info))
    monkeypatch.setattr(auth, "_exchange_code", AsyncMock(return_value={"id_token": "mock", "refresh_token": "gmail-refresh", "scope": "https://www.googleapis.com/auth/gmail.readonly"}))
    response = client.get("/auth/google/callback", params={"state": params["state"][0], "code": "code"}, follow_redirects=False)
    assert parse_qs(urlparse(response.headers["location"]).query)["gmail"] == ["connected"]
    db.expire_all()
    assert db.query(User).count() == 1
    assert auth_identities.resolve_google_user(db, info).id == owner.id
    assert db.get(User, owner.id).email == "private@privaterelay.appleid.com"


def test_gmail_identity_already_owned_cannot_be_linked(db, env):
    existing = user(db, "claimed@gmail.com", "google", "google-claimed")
    apple = user(db, "relay@privaterelay.appleid.com", "apple", "apple")
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        auth_identities.link_google_for_gmail(db, apple, {"sub": "google-claimed", "email": existing.email})
    assert db.query(AuthIdentity).count() == 2


def test_legacy_google_account_must_bootstrap_before_apple_linking(client, db, provider, monkeypatch):
    legacy = user(db, provider=None)
    result = client.post("/auth/apple/challenge", headers=headers(legacy), json={"purpose": "link"})
    assert result.status_code == 403 and result.json()["detail"] == "reauthentication_required"
    response = client.post("/auth/google/reauth/start", headers=headers(legacy), json={"app_redirect_uri": "trotterv2://oauthredirect"})
    params = parse_qs(urlparse(response.json()["url"]).query)
    info = {"sub": "legacy-google", "email": legacy.email, "nonce": params["nonce"][0]}
    monkeypatch.setattr(auth, "_verify_id_token", AsyncMock(return_value=info))
    monkeypatch.setattr(auth, "_exchange_code", AsyncMock(return_value={"id_token": "mock"}))
    response = client.get("/auth/google/callback", params={"state": params["state"][0], "code": "code"}, follow_redirects=False)
    fresh = parse_qs(urlparse(response.headers["location"]).query)["token"][0]
    bearer = {"Authorization": "Bearer " + fresh}
    assert complete(client, challenge(client, "link", bearer), bearer).status_code == 200
    db.expire_all()
    assert auth_identities.resolve_google_user(db, info).id == legacy.id
    assert auth_identities.providers(db, legacy.id) == ["apple", "google"]


def test_new_google_enrollment_on_apple_account_requires_recent_auth(client, db):
    owner = user(db, "relay@privaterelay.appleid.com", "apple", "apple-private")
    claims = jwt.decode(create_app_jwt(owner.id, owner.email), options={"verify_signature": False})
    claims["iat"] -= 601
    import os
    bearer = {"Authorization": "Bearer " + jwt.encode(claims, os.environ["JWT_SECRET"], algorithm="HS256")}
    response = client.post("/auth/google/gmail/start", headers=bearer, json={"app_redirect_uri": "trotterv2://oauthredirect"})
    assert response.status_code == 403 and response.json()["detail"] == "reauthentication_required"
    db.add(AuthIdentity(user_id=owner.id, provider="google", subject="already-linked", email="linked@gmail.com"))
    db.commit()
    assert client.post("/auth/google/gmail/start", headers=bearer, json={"app_redirect_uri": "trotterv2://oauthredirect"}).status_code == 200


def test_google_reauth_is_bound_to_existing_subject_and_never_creates_users(client, db, monkeypatch):
    owner = user(db)
    response = client.post("/auth/google/reauth/start", headers=headers(owner), json={"app_redirect_uri": "trotterv2://oauthredirect"})
    params = parse_qs(urlparse(response.json()["url"]).query)
    monkeypatch.setattr(auth, "_verify_id_token", AsyncMock(return_value={"sub": "different-google", "email": "different@gmail.com", "nonce": params["nonce"][0]}))
    monkeypatch.setattr(auth, "_exchange_code", AsyncMock(return_value={"id_token": "mock"}))
    response = client.get("/auth/google/callback", params={"state": params["state"][0], "code": "code"}, follow_redirects=False)
    assert parse_qs(urlparse(response.headers["location"]).query)["error"] == ["reauth_wrong_account"]
    assert db.query(User).count() == 1


@pytest.mark.parametrize("web", [False, True])
def test_google_reauth_redirect_preserves_separate_callback_flow(client, db, monkeypatch, web):
    owner = user(db)
    monkeypatch.setenv("WEB_APP_URL", "https://trotter.example")
    base = "https://trotter.example/oauthredirect" if web else "trotterv2://oauthredirect"
    uri = base + "?flow=reauth&attempt=12345678-1234-1234-1234-123456789abc"
    response = client.post("/auth/google/reauth/start", headers=headers(owner), json={"app_redirect_uri": uri})
    assert response.status_code == 200, response.text
    params = parse_qs(urlparse(response.json()["url"]).query)
    monkeypatch.setattr(auth, "_verify_id_token", AsyncMock(return_value={"sub": "google-existing", "email": owner.email, "nonce": params["nonce"][0]}))
    monkeypatch.setattr(auth, "_exchange_code", AsyncMock(return_value={"id_token": "mock"}))
    callback = client.get("/auth/google/callback", params={"state": params["state"][0], "code": "code"}, follow_redirects=False)
    target = urlparse(callback.headers["location"])
    assert parse_qs(target.query)["flow"] == ["reauth"]
    assert parse_qs(target.fragment if web else target.query)["token"]
    assert client.get("/auth/google/start", params={"app_redirect_uri": uri}).status_code == 400
    assert client.post("/auth/google/gmail/start", headers=headers(owner), json={"app_redirect_uri": uri}).status_code == 400
    assert client.post("/auth/google/reauth/start", headers=headers(owner), json={"app_redirect_uri": uri.replace("flow=reauth", "flow=gmail")}).status_code == 400


def test_renamed_google_email_does_not_authorize_old_address_or_merge_other_account(db, env):
    owner = user(db, "old@workspace.example", "google", "workspace-subject")
    info = {"sub": "workspace-subject", "email": "new@workspace.example"}
    assert auth_identities.resolve_google_user(db, info).id == owner.id
    db.commit()
    assert owner.email == "new@workspace.example"
    assert auth_identities.verified_emails(db, owner) == {"new@workspace.example"}
    # A stale primary value never becomes an authorization alias after migration.
    owner.email = "old@workspace.example"
    db.commit()
    assert auth_identities.verified_emails(db, owner) == {"new@workspace.example"}
    another = user(db, "claimed@workspace.example", "google", "other-subject")
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as failure:
        auth_identities.resolve_google_user(db, {"sub": "workspace-subject", "email": another.email})
    assert failure.value.detail == "account_link_required"


def test_apple_client_secret_is_short_lived_es256_for_exact_app(env, monkeypatch):
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import serialization
    key = ec.generate_private_key(ec.SECP256R1())
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption()).decode()
    monkeypatch.setenv("APPLE_PRIVATE_KEY", pem)
    client_id, secret = apple_auth.client_secret()
    decoded = jwt.decode(secret, key.public_key(), algorithms=["ES256"], audience=apple_auth.ISSUER)
    assert client_id == decoded["sub"] == "com.trotter.mobilev2"
    assert decoded["iss"] == "TEAM123456"
    assert decoded["exp"] - decoded["iat"] == 300
    assert jwt.get_unverified_header(secret)["kid"] == "KEY1234567"


def test_apple_exchange_and_revoke_use_fixed_endpoints_and_fail_closed(env, monkeypatch):
    import httpx
    calls = []
    def respond(request):
        calls.append((str(request.url), parse_qs(request.content.decode())))
        if request.url.path == "/auth/token":
            return httpx.Response(200, json={"id_token": "signed-token", "refresh_token": "refresh"})
        return httpx.Response(200)
    original_client = httpx.AsyncClient
    monkeypatch.setattr(apple_auth, "client_secret", lambda: ("com.trotter.mobilev2", "client-secret"))
    monkeypatch.setattr(apple_auth.httpx, "AsyncClient", lambda **kwargs: original_client(transport=httpx.MockTransport(respond), **kwargs))
    assert asyncio.run(apple_auth.exchange_authorization_code("code"))["refresh_token"] == "refresh"
    asyncio.run(apple_auth.revoke_refresh_token("refresh"))
    assert calls[0][0] == "https://appleid.apple.com/auth/token"
    assert calls[0][1]["grant_type"] == ["authorization_code"]
    assert calls[0][1]["code"] == ["code"]
    assert calls[1][0] == "https://appleid.apple.com/auth/revoke"
    assert calls[1][1]["token_type_hint"] == ["refresh_token"]
    from fastapi import HTTPException
    monkeypatch.setattr(apple_auth.httpx, "AsyncClient", lambda **kwargs: original_client(
        transport=httpx.MockTransport(lambda _: httpx.Response(503)), **kwargs))
    for fn, message in ((apple_auth.exchange_authorization_code, "apple_signin_unavailable"),
                        (apple_auth.revoke_refresh_token, "account_deletion_retry")):
        with pytest.raises(HTTPException) as failure:
            asyncio.run(fn("value"))
        assert failure.value.status_code == 503 and failure.value.detail == message
