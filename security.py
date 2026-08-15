"""Fernet-based symmetric encryption for API token storage."""

import base64
import hashlib

from cryptography.fernet import Fernet

from config import settings


def _get_fernet() -> Fernet:
    """Derive a Fernet key from the configured secret key using SHA-256."""
    key_bytes = hashlib.sha256(settings.secret_key.encode()).digest()
    b64_key = base64.urlsafe_b64encode(key_bytes)
    return Fernet(b64_key)


def encrypt_token(token: str) -> str:
    """Encrypt a plaintext API token for storage."""
    return _get_fernet().encrypt(token.encode()).decode()


def decrypt_token(encrypted: str) -> str:
    """Decrypt a stored encrypted API token."""
    return _get_fernet().decrypt(encrypted.encode()).decode()
