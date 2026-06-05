# backend/tests/test_auth.py
"""
Tests for JWT authentication utilities.
"""

import os
import pytest
from datetime import datetime, timedelta
import jwt
from jwt.exceptions import InvalidTokenError

from app.auth import create_app_jwt, verify_app_jwt, get_user_from_jwt, get_jwt_secret


class TestJWTAuth:
    """Test JWT creation and verification."""

    def test_create_and_verify_jwt(self, monkeypatch):
        """Test JWT creation and verification roundtrip."""
        monkeypatch.setenv("JWT_SECRET", "test-secret-key")
        
        user_id = 123
        email = "test@example.com"
        
        # Create JWT
        token = create_app_jwt(user_id, email)
        assert isinstance(token, str)
        assert len(token) > 0
        
        # Verify JWT
        payload = verify_app_jwt(token)
        assert payload["sub"] == str(user_id)
        assert payload["email"] == email
        assert payload["iss"] == "travelstrava-backend"
        assert payload["aud"] == "travelstrava-mobile"
        assert "iat" in payload
        assert "exp" in payload

    def test_jwt_expiry(self, monkeypatch):
        """Test JWT expiry configuration."""
        monkeypatch.setenv("JWT_SECRET", "test-secret-key")
        
        # Create JWT with short expiry
        token = create_app_jwt(123, "test@example.com", expires_hours=1)
        payload = verify_app_jwt(token)
        
        # Check expiry is roughly 1 hour from now
        exp_time = datetime.utcfromtimestamp(payload["exp"])
        expected_exp = datetime.utcnow() + timedelta(hours=1)
        
        # Allow 5 second tolerance
        assert abs((exp_time - expected_exp).total_seconds()) < 5

    def test_verify_invalid_jwt_raises_error(self, monkeypatch):
        """Test that invalid JWT raises error."""
        monkeypatch.setenv("JWT_SECRET", "test-secret-key")
        
        with pytest.raises(InvalidTokenError):
            verify_app_jwt("invalid.jwt.token")
        
        with pytest.raises(InvalidTokenError):
            verify_app_jwt("")

    def test_verify_jwt_wrong_secret(self, monkeypatch):
        """Test that JWT with wrong secret fails verification."""
        monkeypatch.setenv("JWT_SECRET", "secret1")
        token = create_app_jwt(123, "test@example.com")
        
        # Change secret
        monkeypatch.setenv("JWT_SECRET", "secret2")
        
        with pytest.raises(InvalidTokenError):
            verify_app_jwt(token)

    def test_verify_jwt_wrong_audience(self, monkeypatch):
        """Test that JWT with wrong audience fails verification."""
        monkeypatch.setenv("JWT_SECRET", "test-secret-key")
        
        # Create JWT with different audience
        payload = {
            "sub": "123",
            "email": "test@example.com",
            "aud": "wrong-audience",
            "iss": "travelstrava-backend",
            "exp": datetime.utcnow() + timedelta(hours=1)
        }
        
        token = jwt.encode(payload, "test-secret-key", algorithm="HS256")
        
        with pytest.raises(InvalidTokenError):
            verify_app_jwt(token)

    def test_get_user_from_jwt_success(self, monkeypatch):
        """Test extracting user info from valid JWT."""
        monkeypatch.setenv("JWT_SECRET", "test-secret-key")
        
        user_id = 456
        email = "user@example.com"
        token = create_app_jwt(user_id, email)
        
        user_info = get_user_from_jwt(token)
        assert user_info is not None
        assert user_info["user_id"] == user_id
        assert user_info["email"] == email

    def test_get_user_from_jwt_invalid_token(self, monkeypatch):
        """Test that invalid JWT returns None."""
        monkeypatch.setenv("JWT_SECRET", "test-secret-key")
        
        assert get_user_from_jwt("invalid.jwt.token") is None
        assert get_user_from_jwt("") is None

    def test_get_user_from_jwt_malformed_payload(self, monkeypatch):
        """Test that JWT with missing fields returns None."""
        monkeypatch.setenv("JWT_SECRET", "test-secret-key")
        
        # Create JWT missing required fields
        payload = {
            "aud": "travelstrava-mobile",
            "iss": "travelstrava-backend",
            "exp": datetime.utcnow() + timedelta(hours=1)
            # Missing "sub" and "email"
        }
        
        token = jwt.encode(payload, "test-secret-key", algorithm="HS256")
        assert get_user_from_jwt(token) is None

    def test_get_jwt_secret_missing_raises_error(self, monkeypatch):
        """Test that missing JWT_SECRET raises error."""
        monkeypatch.delenv("JWT_SECRET", raising=False)
        
        with pytest.raises(ValueError, match="JWT_SECRET environment variable is required"):
            get_jwt_secret()

    def test_jwt_default_expiry(self, monkeypatch):
        """Test that the default mobile development session lasts 30 days."""
        monkeypatch.setenv("JWT_SECRET", "test-secret-key")
        
        token = create_app_jwt(123, "test@example.com")
        payload = verify_app_jwt(token)
        
        exp_time = datetime.utcfromtimestamp(payload["exp"])
        iat_time = datetime.utcfromtimestamp(payload["iat"])
        
        # Should be approximately 30 days.
        duration = exp_time - iat_time
        assert abs(duration.total_seconds() - 30 * 24 * 3600) < 60
