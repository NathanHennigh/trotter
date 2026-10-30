"""Tests for the browser-based Google OAuth flow and authenticated profile."""

import time
import asyncio
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlparse

import pytest
import jwt
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.crypto import decrypt_refresh_token, generate_encryption_key
from app.db import get_db
from app.main import app
from app.models import Account, Base, User


@pytest.fixture
def test_db(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'auth-test.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override_get_db():
        db = testing_session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    db = testing_session()
    yield db
    db.close()
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def auth_env(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "test-client-id.apps.googleusercontent.com")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test-client-secret")
    monkeypatch.setenv("BACKEND_URL", "http://localhost:8000")
    monkeypatch.setenv("JWT_SECRET", "test-jwt-secret")
    monkeypatch.setenv("ENCRYPTION_KEY", generate_encryption_key())


def _oauth_state(app_redirect_uri: str = "trotterv2://oauthredirect") -> str:
    now = int(time.time())
    payload = {
        "uri": app_redirect_uri,
        "iat": now,
        "exp": now + 600,
        "iss": "trotter-oauth",
        "aud": "trotter-oauth-callback",
    }
    return jwt.encode(payload, "test-jwt-secret", algorithm="HS256")


class TestGoogleAuthEndpoint:
    def test_google_start_redirects_to_google(self, client, auth_env):
        response = client.get(
            "/auth/google/start",
            params={"app_redirect_uri": "trotterv2://oauthredirect"},
            follow_redirects=False,
        )

        assert response.status_code == 307
        location = response.headers["location"]
        parsed = urlparse(location)
        params = parse_qs(parsed.query)
        assert parsed.netloc == "accounts.google.com"
        assert params["client_id"] == ["test-client-id.apps.googleusercontent.com"]
        assert params["redirect_uri"] == ["http://localhost:8000/auth/google/callback"]
        assert set(params["scope"][0].split()) == {"openid", "profile", "email"}
        assert "include_granted_scopes" not in params
        assert "access_type" not in params
        assert "prompt" not in params
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["referrer-policy"] == "no-referrer"

    def test_google_start_rejects_disallowed_redirect(self, client, auth_env):
        response = client.get(
            "/auth/google/start",
            params={"app_redirect_uri": "https://example.com/steal-token"},
        )
        assert response.status_code == 400
        assert response.json()["detail"] == "Disallowed redirect URI scheme"

    def test_google_start_allows_configured_web_app_redirect(self, client, auth_env, monkeypatch):
        monkeypatch.setenv("WEB_APP_URL", "https://app.trotter.example")
        response = client.get(
            "/auth/google/start",
            params={"app_redirect_uri": "https://app.trotter.example/oauthredirect"},
            follow_redirects=False,
        )

        assert response.status_code == 307

    def test_google_start_rejects_other_path_on_web_app_origin(self, client, auth_env, monkeypatch):
        monkeypatch.setenv("WEB_APP_URL", "https://app.trotter.example")
        response = client.get(
            "/auth/google/start",
            params={"app_redirect_uri": "https://app.trotter.example/steal-token"},
        )

        assert response.status_code == 400

    def test_google_start_requires_configuration(self, client, monkeypatch):
        monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
        monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)

        response = client.get(
            "/auth/google/start",
            params={"app_redirect_uri": "trotterv2://oauthredirect"},
        )
        assert response.status_code == 500
        assert "Google OAuth not configured" in response.json()["detail"]

    @patch("app.routers.auth._verify_id_token", new_callable=AsyncMock)
    @patch("app.routers.auth._exchange_code", new_callable=AsyncMock)
    def test_google_callback_creates_user_and_redirects(
        self,
        mock_exchange,
        mock_verify,
        client,
        test_db,
        auth_env,
    ):
        mock_exchange.return_value = {
            "refresh_token": "1//test_refresh_token",
            "id_token": "test-id-token",
            "scope": "https://www.googleapis.com/auth/gmail.readonly",
        }
        mock_verify.return_value = {
            "iss": "accounts.google.com",
            "sub": "verified-google-subject",
            "email": "testuser@gmail.com",
            "name": "Test User",
        }

        response = client.get(
            "/auth/google/callback",
            params={"code": "test-code", "state": _oauth_state()},
            follow_redirects=False,
        )

        assert response.status_code == 307
        redirect = urlparse(response.headers["location"])
        assert f"{redirect.scheme}://{redirect.netloc}{redirect.path}" == "trotterv2://oauthredirect"
        assert parse_qs(redirect.query)["token"][0]

        user = test_db.query(User).filter(User.email == "testuser@gmail.com").one()
        assert user.name == "Test User"
        assert test_db.query(Account).filter(Account.user_id == user.id).count() == 0

    @patch("app.routers.auth._verify_id_token", new_callable=AsyncMock)
    @patch("app.routers.auth._exchange_code", new_callable=AsyncMock)
    def test_google_callback_updates_existing_user(
        self,
        mock_exchange,
        mock_verify,
        client,
        test_db,
        auth_env,
    ):
        user = User(email="existing@gmail.com", name="Existing User")
        test_db.add(user)
        test_db.commit()

        mock_exchange.return_value = {
            "refresh_token": "1//replacement",
            "id_token": "test-id-token",
            "scope": "gmail.readonly",
        }
        mock_verify.return_value = {
            "iss": "accounts.google.com",
            "sub": "verified-google-subject",
            "email": "existing@gmail.com",
            "name": "Updated Name",
        }

        response = client.get(
            "/auth/google/callback",
            params={"code": "test-code", "state": _oauth_state()},
            follow_redirects=False,
        )

        assert response.status_code == 307
        test_db.refresh(user)
        assert user.name == "Updated Name"
        assert test_db.query(User).count() == 1

    @patch("app.routers.auth._verify_id_token", new_callable=AsyncMock)
    @patch("app.routers.auth._exchange_code", new_callable=AsyncMock)
    def test_google_callback_uses_fragment_for_web_token(
        self,
        mock_exchange,
        mock_verify,
        client,
        test_db,
        auth_env,
        monkeypatch,
    ):
        monkeypatch.setenv("WEB_APP_URL", "https://app.trotter.example")
        mock_exchange.return_value = {
            "refresh_token": "1//web_refresh_token",
            "id_token": "test-id-token",
            "scope": "https://www.googleapis.com/auth/gmail.readonly",
        }
        mock_verify.return_value = {
            "iss": "accounts.google.com",
            "sub": "verified-google-subject",
            "email": "webuser@gmail.com",
            "name": "Web User",
        }

        response = client.get(
            "/auth/google/callback",
            params={
                "code": "test-code",
                "state": _oauth_state("https://app.trotter.example/oauthredirect"),
            },
            follow_redirects=False,
        )

        assert response.status_code == 307
        redirect = urlparse(response.headers["location"])
        assert redirect.query == ""
        assert parse_qs(redirect.fragment)["token"][0]

    @patch("app.routers.auth._exchange_code", new_callable=AsyncMock)
    def test_google_callback_surfaces_exchange_failure(
        self,
        mock_exchange,
        client,
        test_db,
        auth_env,
    ):
        mock_exchange.side_effect = HTTPException(400, "Google token exchange failed")
        response = client.get(
            "/auth/google/callback",
            params={"code": "bad-code", "state": _oauth_state()},
            follow_redirects=False,
        )
        assert response.status_code == 307
        assert parse_qs(urlparse(response.headers["location"]).query)["error"] == ["oauth_failed"]

    def test_google_callback_rejects_invalid_state(self, client, test_db, auth_env):
        response = client.get(
            "/auth/google/callback",
            params={"code": "test-code", "state": "not-valid-state"},
        )
        assert response.status_code == 400
        assert response.json()["detail"] == "Invalid or expired OAuth state"

    def test_google_callback_rejects_forged_redirect(self, client, test_db, auth_env):
        state = _oauth_state("https://example.com/steal-token")
        response = client.get(
            "/auth/google/callback",
            params={"code": "test-code", "state": state},
        )

        assert response.status_code == 400
        assert response.json()["detail"] == "Invalid or expired OAuth state"


class TestAuthMeEndpoint:
    def test_auth_me_success(self, client, test_db, auth_env):
        user = User(email="test@example.com", name="Test User")
        test_db.add(user)
        test_db.commit()

        from app.auth import create_app_jwt

        token = create_app_jwt(user.id, user.email)
        response = client.get(
            "/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        assert response.json() == {
            "user_id": user.id,
            "email": user.email,
            "name": user.name,
            "gmail_connected": False,
            "gmail_connection_status": "not_connected",
            "auth_providers": ["google"],
        }

    def test_auth_me_missing_token(self, client, auth_env):
        response = client.get("/auth/me")
        assert response.status_code == 403

    def test_auth_me_invalid_token(self, client, auth_env):
        response = client.get(
            "/auth/me",
            headers={"Authorization": "Bearer invalid.jwt.token"},
        )
        assert response.status_code == 401

    def test_auth_me_user_not_found(self, client, test_db, auth_env):
        from app.auth import create_app_jwt

        token = create_app_jwt(99999, "nonexistent@example.com")
        response = client.get(
            "/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 401
        assert response.json()["detail"] == "User not found"


@pytest.mark.parametrize("verified", [False, None, "true", "false", 1])
def test_google_identity_requires_verified_email(verified, auth_env):
    from app.routers.auth import _verify_id_token
    claims = {"iss": "https://accounts.google.com", "sub": "verified-google-subject", "email": "invitee@example.com"}
    if verified is not None:
        claims["email_verified"] = verified
    with patch("google.oauth2.id_token.verify_oauth2_token", return_value=claims):
        with pytest.raises(HTTPException) as failure:
            asyncio.run(_verify_id_token("signed-token"))
    assert failure.value.status_code == 400
    assert "verified" in failure.value.detail


def test_google_identity_accepts_verified_email(auth_env):
    from app.routers.auth import _verify_id_token
    claims = {"iss": "https://accounts.google.com", "sub": "verified-google-subject", "email": "invitee@example.com", "email_verified": True}
    with patch("google.oauth2.id_token.verify_oauth2_token", return_value=claims):
        assert asyncio.run(_verify_id_token("signed-token")) == claims


@pytest.fixture
def oauth_provider(monkeypatch):
    exchange = AsyncMock(return_value={"id_token": "verified-by-mock", "scope": "openid email profile"})
    verify = AsyncMock(return_value={"sub": "verified-google-subject", "email": "optional@gmail.com", "name": "Optional", "email_verified": True})
    monkeypatch.setattr("app.routers.auth._exchange_code", exchange)
    monkeypatch.setattr("app.routers.auth._verify_id_token", verify)
    return exchange, verify


def _headers(user):
    from app.auth import create_app_jwt
    return {"Authorization": f"Bearer {create_app_jwt(user.id, user.email)}"}


def _gmail_user(db, connected=False, stored_status=None):
    from app.crypto import encrypt_refresh_token
    user = User(email="optional@gmail.com", name="Optional")
    db.add(user)
    db.flush()
    if connected:
        db.add(Account(user_id=user.id, provider="google", refresh_token_encrypted=encrypt_refresh_token("original-refresh"),
                       scopes="openid https://www.googleapis.com/auth/gmail.readonly", gmail_connection_status=stored_status))
    db.commit()
    return user


def _gmail_state(client, user, uri="trotterv2://oauthredirect?flow=gmail&attempt=12345678-1234-1234-1234-123456789abc"):
    response = client.post("/auth/google/gmail/start", headers=_headers(user), json={"app_redirect_uri": uri})
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
    params = parse_qs(urlparse(response.json()["url"]).query)
    from app.routers import auth
    # Emulate Google's signed token returning the nonce from this auth request.
    if isinstance(auth._verify_id_token, AsyncMock):
        auth._verify_id_token.return_value["nonce"] = params["nonce"][0]
    return params


def _callback(client, state, **params):
    return client.get("/auth/google/callback", params={"state": state, **params}, follow_redirects=False)


@pytest.mark.parametrize("connected,stored_status", [(False, None), (True, None), (True, "needs_reconnect")])
def test_identity_without_refresh_or_gmail_leaves_connections_untouched(client, test_db, auth_env, oauth_provider, connected, stored_status):
    user = _gmail_user(test_db, connected, stored_status)
    account = test_db.query(Account).first()
    original = (account.refresh_token_encrypted, account.scopes, account.gmail_connection_status) if account else None
    response = _callback(client, _oauth_state(), code="identity-only-code")
    assert response.status_code == 307
    assert parse_qs(urlparse(response.headers["location"]).query)["token"]
    test_db.expire_all()
    account = test_db.query(Account).first()
    assert ((account.refresh_token_encrypted, account.scopes, account.gmail_connection_status) if account else None) == original
    status = client.get("/auth/me", headers=_headers(user)).json()
    assert status["gmail_connected"] is (connected and stored_status != "needs_reconnect")
    assert status["gmail_connection_status"] == ("not_connected" if not connected else stored_status or "connected")


def test_identity_ignores_unsolicited_gmail_refresh_grant(client, test_db, auth_env, oauth_provider):
    exchange, _ = oauth_provider
    user = _gmail_user(test_db, connected=True)
    original = test_db.query(Account).one().refresh_token_encrypted
    exchange.return_value.update(refresh_token="must-not-overwrite", scope="https://www.googleapis.com/auth/gmail.readonly")
    assert _callback(client, _oauth_state(), code="code").status_code == 307
    test_db.expire_all()
    assert test_db.query(Account).one().refresh_token_encrypted == original


def test_gmail_connect_requires_authenticated_start_and_binds_state(client, test_db, auth_env):
    assert client.post("/auth/google/gmail/start", json={"app_redirect_uri": "trotterv2://oauthredirect"}).status_code in (401, 403)
    user = _gmail_user(test_db)
    params = _gmail_state(client, user)
    assert set(params["scope"][0].split()) == {"openid", "email", "profile", "https://www.googleapis.com/auth/gmail.readonly"}
    assert params["access_type"] == ["offline"]
    assert params["prompt"] == ["consent"]
    assert params["include_granted_scopes"] == ["true"]
    assert params["login_hint"] == [user.email]
    claims = jwt.decode(params["state"][0], "test-jwt-secret", algorithms=["HS256"], audience="trotter-oauth-callback")
    assert claims["purpose"] == "gmail" and claims["user_id"] == user.id
    assert claims["exp"] - claims["iat"] == 600
    assert claims["jti"]
    assert params["nonce"] == [claims["jti"]]
    assert params["state"] != _gmail_state(client, user)["state"]


@pytest.mark.parametrize("web", [False, True])
def test_explicit_gmail_connect_same_account_preserves_app_identity(client, test_db, auth_env, oauth_provider, monkeypatch, web):
    exchange, _ = oauth_provider
    user = _gmail_user(test_db)
    exchange.return_value.update(refresh_token="new-refresh", scope="openid https://www.googleapis.com/auth/gmail.readonly")
    monkeypatch.setenv("WEB_APP_URL", "https://trotter.example")
    uri = ("https://trotter.example/oauthredirect" if web else "trotterv2://oauthredirect") + "?flow=gmail&attempt=12345678-1234-1234-1234-123456789abc"
    params = _gmail_state(client, user, uri)
    response = _callback(client, params["state"][0], code="gmail-code")
    returned = parse_qs(urlparse(response.headers["location"]).query)
    assert returned == {"flow": ["gmail"], "attempt": ["12345678-1234-1234-1234-123456789abc"], "gmail": ["connected"]}
    assert not urlparse(response.headers["location"]).fragment
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert test_db.query(User).count() == 1
    assert decrypt_refresh_token(test_db.query(Account).one().refresh_token_encrypted) == "new-refresh"
    assert client.get("/auth/me", headers=_headers(user)).json()["gmail_connected"] is True


@pytest.mark.parametrize("connected", [False, True])
def test_gmail_wrong_account_does_not_switch_or_store_credentials(client, test_db, auth_env, oauth_provider, connected):
    exchange, verify = oauth_provider
    user = _gmail_user(test_db, connected=connected)
    before = test_db.query(Account).first()
    original = before.refresh_token_encrypted if before else None
    exchange.return_value.update(refresh_token="wrong-refresh", scope="https://www.googleapis.com/auth/gmail.readonly")
    verify.return_value["email"] = "someone-else@gmail.com"
    response = _callback(client, _gmail_state(client, user)["state"][0], code="wrong-account-code")
    assert parse_qs(urlparse(response.headers["location"]).query)["error"] == ["gmail_wrong_account"]
    assert test_db.query(User).count() == 1
    test_db.expire_all()
    account = test_db.query(Account).first()
    assert (account.refresh_token_encrypted if account else None) == original
    assert client.get("/auth/me", headers=_headers(user)).json()["user_id"] == user.id


@pytest.mark.parametrize("scope", [None, "", "openid email profile", "https://www.googleapis.com/auth/gmail.metadata"])
def test_missing_gmail_scope_never_overwrites_existing_connection(client, test_db, auth_env, oauth_provider, scope):
    exchange, _ = oauth_provider
    user = _gmail_user(test_db, connected=True)
    account = test_db.query(Account).one()
    original = (account.refresh_token_encrypted, account.scopes, account.gmail_connection_status)
    exchange.return_value.update(refresh_token="not-readable", scope=scope)
    response = _callback(client, _gmail_state(client, user)["state"][0], code="partial-consent-code")
    assert parse_qs(urlparse(response.headers["location"]).query)["error"] == ["gmail_permission_required"]
    test_db.refresh(account)
    assert (account.refresh_token_encrypted, account.scopes, account.gmail_connection_status) == original


@pytest.mark.parametrize("existing_status,expected", [(None, "connected"), ("needs_reconnect", "gmail_refresh_required")])
def test_missing_new_refresh_preserves_existing_valid_token_only(client, test_db, auth_env, oauth_provider, existing_status, expected):
    exchange, _ = oauth_provider
    user = _gmail_user(test_db, connected=True, stored_status=existing_status)
    account = test_db.query(Account).one()
    original = (account.refresh_token_encrypted, account.scopes)
    exchange.return_value["scope"] = "https://www.googleapis.com/auth/gmail.readonly"
    response = _callback(client, _gmail_state(client, user)["state"][0], code="repeat-consent-code")
    returned = parse_qs(urlparse(response.headers["location"]).query)
    assert returned.get("gmail", returned.get("error")) == [expected]
    test_db.refresh(account)
    assert (account.refresh_token_encrypted, account.scopes) == original


def test_first_connect_without_refresh_is_recoverable(client, test_db, auth_env, oauth_provider):
    exchange, _ = oauth_provider
    user = _gmail_user(test_db)
    exchange.return_value["scope"] = "https://www.googleapis.com/auth/gmail.readonly"
    response = _callback(client, _gmail_state(client, user)["state"][0], code="no-refresh-code")
    assert parse_qs(urlparse(response.headers["location"]).query)["error"] == ["gmail_refresh_required"]
    assert test_db.query(Account).count() == 0


@pytest.mark.parametrize("failure", ["access_denied", "provider_unavailable"])
def test_denied_connection_redirects_without_exchange_or_losing_session(client, test_db, auth_env, oauth_provider, failure):
    exchange, _ = oauth_provider
    user = _gmail_user(test_db, connected=True)
    response = _callback(client, _gmail_state(client, user)["state"][0], error=failure)
    expected = "access_denied" if failure == "access_denied" else "gmail_connect_failed"
    assert parse_qs(urlparse(response.headers["location"]).query)["error"] == [expected]
    exchange.assert_not_called()
    assert client.get("/auth/me", headers=_headers(user)).json()["gmail_connected"] is True


@pytest.mark.parametrize("uri", ["trotterv2://evil", "com.trotter.evil://oauthredirect", "trotterv2://oauthredirect/extra",
    "trotterv2://oauthredirect#token=steal", "trotterv2://oauthredirect?token=steal", "trotterv2://oauthredirect?flow=identity",
    "trotterv2://oauthredirect?attempt=bad", "trotterv2://oauthredirect?flow=gmail&flow=gmail",
    "https://app.trotter.example/oauthredirect.evil", "https://app.trotter.example@evil.example/oauthredirect"])
def test_redirects_are_exact_and_have_only_safe_attempt_parameters(client, auth_env, monkeypatch, uri):
    monkeypatch.setenv("WEB_APP_URL", "https://app.trotter.example")
    assert client.get("/auth/google/start", params={"app_redirect_uri": uri}, follow_redirects=False).status_code == 400


def test_expired_or_tampered_connect_state_never_exchanges_credentials(client, test_db, auth_env, oauth_provider):
    exchange, _ = oauth_provider
    user = _gmail_user(test_db)
    state = _gmail_state(client, user)["state"][0]
    claims = jwt.decode(state, "test-jwt-secret", algorithms=["HS256"], audience="trotter-oauth-callback")
    claims["exp"] = int(time.time()) - 1
    expired = jwt.encode(claims, "test-jwt-secret", algorithm="HS256")
    for invalid in (expired, state[:-8] + "tampered"):
        assert _callback(client, invalid, code="code").status_code == 400
    exchange.assert_not_called()


@pytest.mark.parametrize("purpose", ["identity", "gmail"])
@pytest.mark.parametrize("nonce", [None, "another-authorization-attempt"])
def test_callback_rejects_valid_identity_token_from_another_attempt(client, test_db, auth_env, oauth_provider, purpose, nonce):
    exchange, verify = oauth_provider
    user = _gmail_user(test_db)
    if purpose == "gmail":
        params = _gmail_state(client, user)
    else:
        response = client.get("/auth/google/start", params={"app_redirect_uri": "trotterv2://oauthredirect"}, follow_redirects=False)
        params = parse_qs(urlparse(response.headers["location"]).query)
    exchange.return_value.update(refresh_token="unused-refresh", scope="https://www.googleapis.com/auth/gmail.readonly")
    verify.return_value["nonce"] = nonce
    response = _callback(client, params["state"][0], code="fresh-code-from-wrong-attempt")
    assert parse_qs(urlparse(response.headers["location"]).query)["error"] == ["gmail_connect_failed" if purpose == "gmail" else "oauth_failed"]
    assert test_db.query(Account).count() == 0


def test_new_identity_attempt_verifies_nonce_without_gmail_or_refresh(client, test_db, auth_env, oauth_provider):
    _, verify = oauth_provider
    response = client.get("/auth/google/start", params={"app_redirect_uri": "trotterv2://oauthredirect"}, follow_redirects=False)
    params = parse_qs(urlparse(response.headers["location"]).query)
    verify.return_value["nonce"] = params["nonce"][0]
    response = _callback(client, params["state"][0], code="identity-code")
    assert "token" in parse_qs(urlparse(response.headers["location"]).query)
    assert test_db.query(User).count() == 1
    assert test_db.query(Account).count() == 0


@pytest.mark.parametrize("connected,status", [(False, None), (True, "needs_reconnect")])
def test_unconnected_users_can_use_private_app_but_cannot_scan(client, test_db, auth_env, connected, status):
    user = _gmail_user(test_db, connected, status)
    headers = _headers(user)
    for path in ("/dreams", "/planner/trips", "/trips"):
        assert client.get(path, headers=headers).status_code == 200
    from app.models import SyncJob
    with patch("app.routers.ingest.run_gmail_import") as task:
        response = client.post("/ingest/gmail/import", headers=headers)
        assert response.status_code == 409
        assert response.json()["detail"]["action"] == "connect_gmail"
        assert response.json()["detail"]["code"] == "gmail_connection_required"
        assert test_db.query(SyncJob).count() == 0
        task.delay.assert_not_called()
    assert client.get("/ingest/test-queries", headers=headers).status_code == 409
