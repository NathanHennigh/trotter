# backend/app/auth.py
"""
JWT utilities for app authentication.
Issues and verifies short-lived JWTs for mobile app sessions.
"""

import os
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
import jwt
from jwt.exceptions import InvalidTokenError


def get_jwt_secret() -> str:
    """Get JWT secret from environment variable."""
    secret = os.getenv("JWT_SECRET")
    if not secret:
        raise ValueError("JWT_SECRET environment variable is required")
    return secret


def create_app_jwt(user_id: int, email: str, expires_hours: int = 24) -> str:
    """
    Create a JWT for app authentication.
    Default expiry: 24 hours (long-lived for convenience in Phase 0).
    """
    now = datetime.utcnow()
    payload = {
        "sub": str(user_id),  # Subject (user ID)
        "email": email,
        "iat": now,  # Issued at
        "exp": now + timedelta(hours=expires_hours),  # Expires
        "iss": "travelstrava-backend",  # Issuer
        "aud": "travelstrava-mobile",  # Audience
    }
    
    secret = get_jwt_secret()
    return jwt.encode(payload, secret, algorithm="HS256")


def verify_app_jwt(token: str) -> Dict[str, Any]:
    """
    Verify and decode a JWT.
    Returns the payload if valid, raises InvalidTokenError if not.
    """
    secret = get_jwt_secret()
    
    try:
        payload = jwt.decode(
            token, 
            secret, 
            algorithms=["HS256"],
            audience="travelstrava-mobile",
            issuer="travelstrava-backend"
        )
        return payload
    except InvalidTokenError:
        raise


def get_user_from_jwt(token: str) -> Optional[Dict[str, Any]]:
    """
    Extract user info from JWT token.
    Returns None if token is invalid or expired.
    """
    try:
        payload = verify_app_jwt(token)
        return {
            "user_id": int(payload["sub"]),
            "email": payload["email"]
        }
    except (InvalidTokenError, ValueError, KeyError):
        return None
