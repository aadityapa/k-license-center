"""Passwords, tokens and small crypto helpers."""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from typing import Any

import bcrypt
import jwt

from .config import config


def _pw(p: str) -> bytes:
    # bcryptjs (the previous implementation) silently used the first 72 bytes.
    return p.encode("utf-8")[:72]


def hash_password(password: str, rounds: int = 10) -> str:
    return bcrypt.hashpw(_pw(password), bcrypt.gensalt(rounds)).decode("ascii")


def check_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(_pw(password), hashed.encode("ascii"))
    except (ValueError, TypeError):
        return False


# Compared against when the client key is unknown, to keep timing uniform.
DUMMY_HASH = hash_password("k-license-dummy-secret")


def sign_token(user_id: int, username: str, permissions: list[str]) -> str:
    now = int(time.time())
    return jwt.encode(
        {
            "sub": str(user_id),
            "username": username,
            "permissions": permissions,
            "iat": now,
            "exp": now + config.jwt_expires_seconds,
        },
        config.jwt_secret,
        algorithm="HS256",
    )


def decode_token(token: str) -> dict[str, Any]:
    """Raises jwt.PyJWTError when invalid or expired."""
    return jwt.decode(token, config.jwt_secret, algorithms=["HS256"], options={"verify_sub": False})


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def hmac_sha256_hex(key: str, payload: str) -> str:
    return hmac.new(key.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def random_hex(nbytes: int) -> str:
    """n random bytes as lowercase hex (2n chars)."""
    return secrets.token_hex(nbytes)


def random_client_secret() -> str:
    """48-character URL-safe client secret."""
    return base64.urlsafe_b64encode(secrets.token_bytes(36)).decode("ascii").rstrip("=")
