"""
The main admin account.

Exactly one account — the seeded `admin` — is protected so the system can
never be left without someone able to manage it: it cannot be locked or
deactivated, it always keeps the ADMIN role (and ADMIN keeps every
permission), and its name, email and password can be changed only by the
admin themself. database/postgres/004_protect_admin.sql enforces the same
rules inside PostgreSQL.
"""
from __future__ import annotations

from typing import Any

from ..errors import AppError

PROTECTED_ADMIN_USERNAME = "admin"
ADMIN_ROLE_CODE = "ADMIN"


def is_protected_username(username: Any) -> bool:
    return str(username if username is not None else "").lower() == PROTECTED_ADMIN_USERNAME


def protected_error(message: str, status: int = 409) -> AppError:
    return AppError(status, "PROTECTED_ACCOUNT", message)
