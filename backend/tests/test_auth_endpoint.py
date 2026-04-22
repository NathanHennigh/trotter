# backend/tests/test_auth_endpoint.py
"""
Tests for Google OAuth authentication endpoint.
"""

import os
import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.models import Base, User, Account
from app.db import get_db
from app.crypto import generate_encryption_key, decrypt_refresh_token


# Test database setup
@pytest.fixture
def test_db():
    """Create a test database."""
    engine = create_engine("sqlite:///test.db")
    Base.metadata.create_all(engine)
    
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    
    def override_get_db():
        try:
            db = TestingSessionLocal()
            yield db
        finally:
            db.close()
    
    app.dependency_overrides[get_db] = override_get_db
    yield TestingSessionLocal()
    
    # Cleanup
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(app)


@pytest.fixture
def auth_env(monkeypatch):
    """Set up authentication environment variables."""
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "test-client-id.apps.googleusercontent.com")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test-client-secret")
    monkeypatch.setenv("SECRET_KEY", "test-jwt-secret")
    monkeypatch.setenv("ENCRYPTION_KEY", generate_encryption_key())


class TestGoogleAuthEndpoint:
    """Test Google OAuth authentication endpoint."""

    @patch('app.routers.auth.httpx.AsyncClient')
    @patch('app.routers.auth.id_token.verify_oauth2_token')
    def test_google_auth_success_new_user(self, mock_verify_token, mock_http_client, client, test_db, auth_env):
        """Test successful authentication with new user."""
        # Mock Google token exchange
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "ya29.test_access_token",
            "refresh_token": "1//test_refresh_token",
            "id_token": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.test_id_token",
            "scope": "https://www.googleapis.com/auth/gmail.readonly"
        }
        
        mock_client_instance = AsyncMock()
        mock_client_instance.post.return_value = mock_response
        mock_http_client.return_value.__aenter__.return_value = mock_client_instance
        
        # Mock ID token verification
        mock_verify_token.return_value = {
            "iss": "accounts.google.com",
            "email": "testuser@gmail.com",
            "name": "Test User",
            "sub": "google_user_id_123"
        }
        
        # Make request
        response = client.post("/auth/google", json={
            "auth_code": "test_auth_code",
            "code_verifier": "test_code_verifier"
        })
        
        # Verify response
        assert response.status_code == 200
        data = response.json()
        
        assert "access_token" in data
        assert data["email"] == "testuser@gmail.com"
        assert data["name"] == "Test User"
        assert "user_id" in data
        
        # Verify user was created in database
        user = test_db.query(User).filter(User.email == "testuser@gmail.com").first()
        assert user is not None
        assert user.name == "Test User"
        
        # Verify account was created with encrypted refresh token
        account = test_db.query(Account).filter(Account.user_id == user.id).first()
        assert account is not None
        assert account.provider == "google"
        assert account.scopes == "https://www.googleapis.com/auth/gmail.readonly"
        
        # Verify refresh token is encrypted
        decrypted_token = decrypt_refresh_token(account.refresh_token_encrypted)
        assert decrypted_token == "1//test_refresh_token"

    @patch('app.routers.auth.httpx.AsyncClient')
    @patch('app.routers.auth.id_token.verify_oauth2_token')
    def test_google_auth_success_existing_user(self, mock_verify_token, mock_http_client, client, test_db, auth_env):
        """Test successful authentication with existing user."""
        # Create existing user
        existing_user = User(email="existing@gmail.com", name="Existing User")
        test_db.add(existing_user)
        test_db.commit()
        
        # Mock responses (same as above)
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "ya29.new_access_token",
            "refresh_token": "1//new_refresh_token",
            "id_token": "new_id_token",
            "scope": "https://www.googleapis.com/auth/gmail.readonly"
        }
        
        mock_client_instance = AsyncMock()
        mock_client_instance.post.return_value = mock_response
        mock_http_client.return_value.__aenter__.return_value = mock_client_instance
        
        mock_verify_token.return_value = {
            "iss": "accounts.google.com",
            "email": "existing@gmail.com",
            "name": "Updated Name",
            "sub": "google_user_id_456"
        }
        
        # Make request
        response = client.post("/auth/google", json={
            "auth_code": "test_auth_code",
            "code_verifier": "test_code_verifier"
        })
        
        # Verify response
        assert response.status_code == 200
        data = response.json()
        assert data["email"] == "existing@gmail.com"
        assert data["name"] == "Updated Name"
        
        # Verify user was updated
        user = test_db.query(User).filter(User.email == "existing@gmail.com").first()
        assert user.name == "Updated Name"
        
        # Should still be only one user
        user_count = test_db.query(User).count()
        assert user_count == 1

    def test_google_auth_missing_config(self, client, monkeypatch):
        """Test authentication fails when Google OAuth is not configured."""
        # Clear environment variables
        monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
        monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)
        
        response = client.post("/auth/google", json={
            "auth_code": "test_code",
            "code_verifier": "test_verifier"
        })
        
        assert response.status_code == 500
        assert "Google OAuth not configured" in response.json()["detail"]

    @patch('app.routers.auth.httpx.AsyncClient')
    def test_google_auth_token_exchange_failure(self, mock_http_client, client, auth_env):
        """Test authentication fails when token exchange fails."""
        # Mock failed token exchange
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = "invalid_grant"
        
        mock_client_instance = AsyncMock()
        mock_client_instance.post.return_value = mock_response
        mock_http_client.return_value.__aenter__.return_value = mock_client_instance
        
        response = client.post("/auth/google", json={
            "auth_code": "invalid_code",
            "code_verifier": "test_verifier"
        })
        
        assert response.status_code == 400
        assert "Failed to exchange auth code" in response.json()["detail"]

    @patch('app.routers.auth.httpx.AsyncClient')
    @patch('app.routers.auth.id_token.verify_oauth2_token')
    def test_google_auth_invalid_id_token(self, mock_verify_token, mock_http_client, client, auth_env):
        """Test authentication fails with invalid ID token."""
        # Mock successful token exchange
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "ya29.test_access_token",
            "refresh_token": "1//test_refresh_token",
            "id_token": "invalid_id_token",
            "scope": "https://www.googleapis.com/auth/gmail.readonly"
        }
        
        mock_client_instance = AsyncMock()
        mock_client_instance.post.return_value = mock_response
        mock_http_client.return_value.__aenter__.return_value = mock_client_instance
        
        # Mock ID token verification failure
        mock_verify_token.side_effect = ValueError("Invalid token")
        
        response = client.post("/auth/google", json={
            "auth_code": "test_code",
            "code_verifier": "test_verifier"
        })
        
        assert response.status_code == 400
        assert "Invalid ID token" in response.json()["detail"]

    def test_google_auth_missing_request_fields(self, client, auth_env):
        """Test authentication fails with missing request fields."""
        # Missing code_verifier
        response = client.post("/auth/google", json={
            "auth_code": "test_code"
        })
        assert response.status_code == 422
        
        # Missing auth_code
        response = client.post("/auth/google", json={
            "code_verifier": "test_verifier"
        })
        assert response.status_code == 422
        
        # Empty request
        response = client.post("/auth/google", json={})
        assert response.status_code == 422


class TestAuthMeEndpoint:
    """Test the /auth/me endpoint for getting current user info."""

    def test_auth_me_success(self, client, test_db, auth_env):
        """Test successful user info retrieval."""
        # Create user
        user = User(email="test@example.com", name="Test User")
        test_db.add(user)
        test_db.commit()
        
        # Create JWT token
        from app.auth import create_app_jwt
        token = create_app_jwt(user.id, user.email)
        
        # Make authenticated request
        response = client.get("/auth/me", headers={
            "Authorization": f"Bearer {token}"
        })
        
        assert response.status_code == 200
        data = response.json()
        assert data["user_id"] == user.id
        assert data["email"] == user.email

    def test_auth_me_missing_token(self, client, auth_env):
        """Test user info fails without token."""
        response = client.get("/auth/me")
        assert response.status_code == 403  # FastAPI HTTPBearer returns 403 for missing token

    def test_auth_me_invalid_token(self, client, auth_env):
        """Test user info fails with invalid token."""
        response = client.get("/auth/me", headers={
            "Authorization": "Bearer invalid.jwt.token"
        })
        assert response.status_code == 401
        assert "Invalid or expired token" in response.json()["detail"]

    def test_auth_me_user_not_found(self, client, test_db, auth_env):
        """Test user info fails when user doesn't exist in database."""
        # Create JWT for non-existent user
        from app.auth import create_app_jwt
        token = create_app_jwt(99999, "nonexistent@example.com")
        
        response = client.get("/auth/me", headers={
            "Authorization": f"Bearer {token}"
        })
        
        assert response.status_code == 401
        assert "User not found" in response.json()["detail"]
