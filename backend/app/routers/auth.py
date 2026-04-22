# backend/app/routers/auth.py
"""
Authentication endpoints for Google OAuth integration.
"""

import os
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from sqlalchemy.orm import Session
from google.auth.transport import requests
from google.oauth2 import id_token
import httpx

from ..db import get_db
from ..models import User, Account
from ..crypto import encrypt_refresh_token, decrypt_refresh_token
from ..auth import create_app_jwt, get_user_from_jwt

router = APIRouter(prefix="/auth", tags=["auth"])
security = HTTPBearer()


class GoogleAuthRequest(BaseModel):
    auth_code: str
    code_verifier: str  # PKCE code verifier


class GoogleAuthResponse(BaseModel):
    access_token: str  # Our app JWT
    user_id: int
    email: str
    name: Optional[str]


class UserInfo(BaseModel):
    user_id: int
    email: str


def get_google_oauth_config():
    """Get Google OAuth configuration from environment."""
    client_id = os.getenv("GOOGLE_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
    
    if not client_id or not client_secret:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Google OAuth not configured"
        )
    
    return client_id, client_secret


async def exchange_auth_code_for_tokens(auth_code: str, code_verifier: str) -> dict:
    """Exchange authorization code for access and refresh tokens."""
    client_id, client_secret = get_google_oauth_config()
    
    token_url = "https://oauth2.googleapis.com/token"
    data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "code": auth_code,
        "grant_type": "authorization_code",
        "code_verifier": code_verifier,  # PKCE
        "access_type": "offline",  # Request refresh token
    }
    
    async with httpx.AsyncClient() as client:
        response = await client.post(token_url, data=data)
        
        if response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Failed to exchange auth code: {response.text}"
            )
        
        return response.json()


def verify_google_id_token(id_token_str: str) -> dict:
    """Verify Google ID token and extract user info."""
    client_id, _ = get_google_oauth_config()
    
    try:
        # Verify the token
        idinfo = id_token.verify_oauth2_token(
            id_token_str, requests.Request(), client_id
        )
        
        # Verify the issuer
        if idinfo['iss'] not in ['accounts.google.com', 'https://accounts.google.com']:
            raise ValueError('Wrong issuer.')
        
        return idinfo
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid ID token: {str(e)}"
        )


def upsert_user_and_account(
    db: Session, 
    user_info: dict, 
    refresh_token: str, 
    scopes: str
) -> User:
    """Create or update user and account records."""
    email = user_info.get("email")
    name = user_info.get("name")
    
    if not email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email not provided in ID token"
        )
    
    # Find or create user
    user = db.query(User).filter(User.email == email).first()
    if not user:
        user = User(email=email, name=name)
        db.add(user)
        db.flush()  # Get the user ID
    else:
        # Update name if provided
        if name:
            user.name = name
    
    # Encrypt refresh token
    encrypted_token = encrypt_refresh_token(refresh_token)
    
    # Find or create account
    account = db.query(Account).filter(
        Account.user_id == user.id,
        Account.provider == "google"
    ).first()
    
    if not account:
        account = Account(
            user_id=user.id,
            provider="google",
            refresh_token_encrypted=encrypted_token,
            scopes=scopes
        )
        db.add(account)
    else:
        # Update existing account
        account.refresh_token_encrypted = encrypted_token
        account.scopes = scopes
    
    db.commit()
    return user


@router.post("/google", response_model=GoogleAuthResponse)
async def google_auth(request: GoogleAuthRequest, db: Session = Depends(get_db)):
    """
    Exchange Google authorization code for app JWT.
    
    Mobile app flow:
    1. App initiates Google Sign-In with PKCE and offline access
    2. App receives authorization code
    3. App sends code + code_verifier to this endpoint
    4. Backend exchanges code for tokens, encrypts refresh token, returns app JWT
    """
    try:
        # Exchange auth code for tokens
        token_response = await exchange_auth_code_for_tokens(
            request.auth_code, 
            request.code_verifier
        )
        
        # Extract tokens
        access_token = token_response.get("access_token")
        refresh_token = token_response.get("refresh_token")
        id_token_str = token_response.get("id_token")
        scope = token_response.get("scope", "")
        
        if not all([access_token, refresh_token, id_token_str]):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Incomplete token response from Google"
            )
        
        # Verify ID token and extract user info
        user_info = verify_google_id_token(id_token_str)
        
        # Store user and account
        user = upsert_user_and_account(db, user_info, refresh_token, scope)
        
        # Create app JWT
        app_jwt = create_app_jwt(user.id, user.email)
        
        return GoogleAuthResponse(
            access_token=app_jwt,
            user_id=user.id,
            email=user.email,
            name=user.name
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Authentication failed: {str(e)}"
        )


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
) -> User:
    """Dependency to get current user from JWT token."""
    token = credentials.credentials
    user_info = get_user_from_jwt(token)
    
    if not user_info:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token"
        )
    
    user = db.query(User).filter(User.id == user_info["user_id"]).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found"
        )
    
    return user


@router.get("/me", response_model=UserInfo)
async def get_user_info(current_user: User = Depends(get_current_user)):
    """Get current user information."""
    return UserInfo(
        user_id=current_user.id,
        email=current_user.email
    )
