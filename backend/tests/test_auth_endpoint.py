"""Tests for the browser-based Google OAuth flow and authenticated profile."""

import base64
import json
import time
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlparse

import pytest
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
    payload = {"uri": app_redirect_uri, "exp": time.time() + 600}
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")


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
        assert "https://www.googleapis.com/auth/gmail.readonly" in params["scope"][0]

    def test_google_start_rejects_disallowed_redirect(self, client, auth_env):
        response = client.get(
            "/auth/google/start",
            params={"app_redirect_uri": "https://example.com/steal-token"},
        )
        assert response.status_code == 400
        assert response.json()["detail"] == "Disallowed redirect URI scheme"

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
        account = test_db.query(Account).filter(Account.user_id == user.id).one()
        assert user.name == "Test User"
        assert decrypt_refresh_token(account.refresh_token_encrypted) == "1//test_refresh_token"

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
        )
        assert response.status_code == 400
        assert "Google token exchange failed" in response.json()["detail"]

    def test_google_callback_rejects_invalid_state(self, client, test_db, auth_env):
        response = client.get(
            "/auth/google/callback",
            params={"code": "test-code", "state": "not-valid-state"},
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
