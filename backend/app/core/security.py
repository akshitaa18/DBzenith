"""Role-Based Access Control and Security Token Services for DBZenith.

Implements:
- Roles: VIEWER, ANALYST, DBA, ADMIN
- Cryptographic HMAC-SHA256 tokens with timestamp expiry
- Secret management with secure fallback generation
- Constant-time signature verification
- Password hashing using PBKDF2-HMAC-SHA256 (200,000 rounds)
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from enum import Enum
from typing import Any
from pydantic import BaseModel, Field


class Role(str, Enum):
    VIEWER = "VIEWER"
    ANALYST = "ANALYST"
    DBA = "DBA"
    ADMIN = "ADMIN"


# Role hierarchy weights
ROLE_HIERARCHY: dict[Role, int] = {
    Role.VIEWER: 10,
    Role.ANALYST: 20,
    Role.DBA: 30,
    Role.ADMIN: 40,
}


class TokenPayload(BaseModel):
    user_id: str
    username: str
    role: Role
    issued_at: float
    expires_at: float


class UserRecord(BaseModel):
    user_id: str
    username: str
    password_hash: str
    salt: str
    role: Role
    is_active: bool = True


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    """Hashes a password with PBKDF2-HMAC-SHA256 and a cryptographically random salt."""
    if salt is None:
        salt = secrets.token_hex(16)
    key = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        200_000,
    )
    return key.hex(), salt


def verify_password(password: str, salt: str, expected_hash: str) -> bool:
    """Verifies a password in constant time."""
    computed_hash, _ = hash_password(password, salt)
    return hmac.compare_digest(computed_hash, expected_hash)


class SecurityManager:
    """Manages secure token creation, verification, and secret keys."""

    def __init__(self, secret_key: str | None = None, token_ttl_seconds: int = 86400) -> None:
        self.secret_key = secret_key or os.getenv("JWT_SECRET_KEY") or os.getenv("SECRET_KEY") or secrets.token_hex(32)
        self.token_ttl_seconds = token_ttl_seconds
        self._secret_bytes = self.secret_key.encode("utf-8")

    def create_token(self, user_id: str, username: str, role: Role | str, ttl_seconds: int | None = None) -> str:
        """Issues an authenticated URL-safe token signed via HMAC-SHA256."""
        now = time.time()
        ttl = ttl_seconds if ttl_seconds is not None else self.token_ttl_seconds
        if isinstance(role, Role):
            role_enum = role
        else:
            role_val = getattr(role, "value", str(role)).upper()
            role_enum = Role(role_val)
        payload = {
            "sub": user_id,
            "usr": username,
            "rol": role_enum.value,
            "iat": now,
            "exp": now + ttl,
        }
        raw_payload = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        b64_payload = base64.urlsafe_b64encode(raw_payload).decode("utf-8").rstrip("=")
        signature = hmac.new(self._secret_bytes, b64_payload.encode("utf-8"), hashlib.sha256).digest()
        b64_sig = base64.urlsafe_b64encode(signature).decode("utf-8").rstrip("=")
        return f"{b64_payload}.{b64_sig}"

    def decode_and_verify_token(self, token: str) -> TokenPayload:
        """Verifies HMAC signature, structure, and expiry time."""
        parts = token.strip().split(".")
        if len(parts) != 2:
            raise ValueError("invalid_token_format")

        b64_payload, b64_sig = parts[0], parts[1]

        # Verify HMAC signature
        expected_sig = hmac.new(self._secret_bytes, b64_payload.encode("utf-8"), hashlib.sha256).digest()
        # Add padding back if necessary
        pad_len = (4 - len(b64_sig) % 4) % 4
        padded_sig = b64_sig + ("=" * pad_len)
        try:
            actual_sig = base64.urlsafe_b64decode(padded_sig.encode("utf-8"))
        except Exception as exc:
            raise ValueError("invalid_token_signature_encoding") from exc

        if not hmac.compare_digest(actual_sig, expected_sig):
            raise ValueError("invalid_token_signature")

        # Decode payload
        pad_payload_len = (4 - len(b64_payload) % 4) % 4
        padded_payload = b64_payload + ("=" * pad_payload_len)
        try:
            payload_dict = json.loads(base64.urlsafe_b64decode(padded_payload.encode("utf-8")).decode("utf-8"))
        except Exception as exc:
            raise ValueError("invalid_token_payload") from exc

        now = time.time()
        if payload_dict.get("exp", 0) < now:
            raise ValueError("token_expired")

        return TokenPayload(
            user_id=payload_dict["sub"],
            username=payload_dict["usr"],
            role=Role(payload_dict["rol"]),
            issued_at=payload_dict["iat"],
            expires_at=payload_dict["exp"],
        )


_SECURITY_MANAGER: SecurityManager | None = None


def get_security_manager() -> SecurityManager:
    global _SECURITY_MANAGER
    if _SECURITY_MANAGER is None:
        try:
            from app.core.config import get_settings
            s = get_settings()
            _SECURITY_MANAGER = SecurityManager(secret_key=s.secret_key, token_ttl_seconds=s.token_ttl_seconds)
        except Exception:
            _SECURITY_MANAGER = SecurityManager()
    return _SECURITY_MANAGER
