# backend/tests/test_crypto.py
"""
Tests for encryption utilities.
"""

import os
import base64
import pytest
from app.crypto import encrypt_refresh_token, decrypt_refresh_token, generate_encryption_key, get_encryption_key


class TestEncryption:
    """Test encryption and decryption of refresh tokens."""

    def test_encrypt_decrypt_roundtrip(self, monkeypatch):
        """Test that encryption and decryption work correctly."""
        # Set a test encryption key
        test_key = generate_encryption_key()
        monkeypatch.setenv("ENCRYPTION_KEY", test_key)
        
        # Test data
        original_token = "ya29.a0AfH6SMBxyz123_test_refresh_token"
        
        # Encrypt
        encrypted_data = encrypt_refresh_token(original_token)
        assert isinstance(encrypted_data, bytes)
        assert len(encrypted_data) > len(original_token)  # Includes nonce + ciphertext
        
        # Decrypt
        decrypted_token = decrypt_refresh_token(encrypted_data)
        assert decrypted_token == original_token

    def test_encryption_produces_different_ciphertext(self, monkeypatch):
        """Test that encrypting the same token twice produces different results (due to random nonce)."""
        test_key = generate_encryption_key()
        monkeypatch.setenv("ENCRYPTION_KEY", test_key)
        
        token = "test_token"
        
        encrypted1 = encrypt_refresh_token(token)
        encrypted2 = encrypt_refresh_token(token)
        
        # Different ciphertext due to random nonce
        assert encrypted1 != encrypted2
        
        # But both decrypt to the same value
        assert decrypt_refresh_token(encrypted1) == token
        assert decrypt_refresh_token(encrypted2) == token

    def test_decrypt_invalid_data_raises_error(self, monkeypatch):
        """Test that decrypting invalid data raises an error."""
        test_key = generate_encryption_key()
        monkeypatch.setenv("ENCRYPTION_KEY", test_key)
        
        # Too short
        with pytest.raises(ValueError, match="too short"):
            decrypt_refresh_token(b"short")
        
        # Invalid ciphertext
        invalid_data = b"x" * 50  # 12 bytes "nonce" + 38 bytes invalid ciphertext
        with pytest.raises(ValueError, match="Failed to decrypt"):
            decrypt_refresh_token(invalid_data)

    def test_get_encryption_key_base64(self, monkeypatch):
        """Test getting encryption key from base64 encoded env var."""
        key = generate_encryption_key()
        monkeypatch.setenv("ENCRYPTION_KEY", key)
        
        result = get_encryption_key()
        assert isinstance(result, bytes)
        assert len(result) == 32  # 256 bits

    def test_get_encryption_key_hex(self, monkeypatch):
        """Test getting encryption key from hex encoded env var."""
        # Clear any existing env var first
        monkeypatch.delenv("ENCRYPTION_KEY", raising=False)
        
        key_bytes = os.urandom(32)
        key_hex = key_bytes.hex()
        monkeypatch.setenv("ENCRYPTION_KEY", key_hex)
        
        result = get_encryption_key()
        assert result == key_bytes

    def test_get_encryption_key_missing_raises_error(self, monkeypatch):
        """Test that missing encryption key raises an error."""
        monkeypatch.delenv("ENCRYPTION_KEY", raising=False)
        
        with pytest.raises(ValueError, match="ENCRYPTION_KEY environment variable is required"):
            get_encryption_key()

    def test_get_encryption_key_invalid_raises_error(self, monkeypatch):
        """Test that invalid encryption key raises an error."""
        monkeypatch.setenv("ENCRYPTION_KEY", "not_valid_base64_or_hex")
        
        with pytest.raises(ValueError, match="must be base64 or hex encoded"):
            get_encryption_key()

    def test_generate_encryption_key(self):
        """Test that generate_encryption_key produces valid keys."""
        key1 = generate_encryption_key()
        key2 = generate_encryption_key()
        
        # Different keys each time
        assert key1 != key2
        
        # Valid base64
        decoded1 = base64.b64decode(key1)
        decoded2 = base64.b64decode(key2)
        
        # 32 bytes each
        assert len(decoded1) == 32
        assert len(decoded2) == 32
