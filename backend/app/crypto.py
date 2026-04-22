# backend/app/crypto.py
"""
Encryption utilities for sensitive data storage.
Uses AES-256-GCM for authenticated encryption of refresh tokens.
"""

import base64
import os
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.exceptions import InvalidTag


def get_encryption_key() -> bytes:
    """Get the encryption key from environment variable."""
    key_str = os.getenv("ENCRYPTION_KEY")
    if not key_str:
        raise ValueError("ENCRYPTION_KEY environment variable is required")
    
    # Check if it looks like hex (only hex characters)
    if all(c in '0123456789abcdefABCDEF' for c in key_str):
        try:
            key = bytes.fromhex(key_str)
            if len(key) == 32:
                return key
        except ValueError:
            pass
    
    # Try base64 decode
    try:
        key = base64.b64decode(key_str)
        if len(key) == 32:
            return key
    except Exception:
        pass
    
    raise ValueError("ENCRYPTION_KEY must be base64 or hex encoded 32-byte key")


def encrypt_refresh_token(token: str) -> bytes:
    """
    Encrypt a refresh token using AES-256-GCM.
    Returns encrypted data including nonce.
    """
    key = get_encryption_key()
    aesgcm = AESGCM(key)
    
    # Generate random nonce
    nonce = os.urandom(12)  # 96-bit nonce for GCM
    
    # Encrypt the token
    ciphertext = aesgcm.encrypt(nonce, token.encode('utf-8'), None)
    
    # Return nonce + ciphertext
    return nonce + ciphertext


def decrypt_refresh_token(encrypted_data: bytes) -> str:
    """
    Decrypt a refresh token using AES-256-GCM.
    Expects encrypted data with nonce prefix.
    """
    key = get_encryption_key()
    aesgcm = AESGCM(key)
    
    if len(encrypted_data) < 12:
        raise ValueError("Invalid encrypted data: too short")
    
    # Split nonce and ciphertext
    nonce = encrypted_data[:12]
    ciphertext = encrypted_data[12:]
    
    try:
        # Decrypt and return as string
        plaintext = aesgcm.decrypt(nonce, ciphertext, None)
        return plaintext.decode('utf-8')
    except InvalidTag:
        raise ValueError("Failed to decrypt refresh token: invalid or corrupted data")


def generate_encryption_key() -> str:
    """Generate a new 256-bit encryption key as base64 string."""
    key = AESGCM.generate_key(bit_length=256)
    return base64.b64encode(key).decode('ascii')
