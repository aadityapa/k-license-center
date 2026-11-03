"""Application errors with stable, machine-readable codes."""
from __future__ import annotations

import re

CODE_STATUS: dict[str, int] = {
    "VALIDATION_ERROR": 400,
    "UNAUTHORIZED": 401,
    "FORBIDDEN": 403,
    "NOT_FOUND": 404,
    "CONFLICT": 409,
    "RATE_LIMITED": 429,
    "INTERNAL_ERROR": 500,
    "INVALID_LICENSE": 404,
    "INVALID_PRODUCT": 400,
    "LICENSE_NOT_ACTIVE": 409,
    "LICENSE_EXPIRED": 409,
    "LICENSE_SUSPENDED": 409,
    "LICENSE_REVOKED": 409,
    "ACTIVATION_LIMIT_REACHED": 409,
    "INVALID_ACTIVATION": 409,
    "DUPLICATE_ACTIVATION": 409,
    "UNAUTHORIZED_CLIENT": 401,
    "INVALID_STATE_TRANSITION": 409,
    "KEY_REVOKED": 409,
    "PROTECTED_ACCOUNT": 409,
}

CODE_MESSAGES: dict[str, str] = {
    "INVALID_LICENSE": "License not found or its key is not active.",
    "INVALID_PRODUCT": "License does not belong to this product.",
    "LICENSE_NOT_ACTIVE": "The license is not active.",
    "LICENSE_EXPIRED": "The license has expired.",
    "LICENSE_SUSPENDED": "The license is suspended.",
    "LICENSE_REVOKED": "The license has been revoked.",
    "ACTIVATION_LIMIT_REACHED": "The activation limit has been reached.",
    "INVALID_ACTIVATION": "Activation not found or not active.",
    "DUPLICATE_ACTIVATION": "This installation is already activated.",
    "INVALID_STATE_TRANSITION": "The requested state transition is not allowed.",
    "KEY_REVOKED": "The license key has been revoked.",
    "PROTECTED_ACCOUNT": "The main admin account cannot be locked, deactivated, deleted or lose the ADMIN role.",
}


class AppError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def _internal() -> AppError:
    return AppError(500, "INTERNAL_ERROR", "An internal error occurred.")


def db_error_code(err: BaseException) -> tuple[str, str]:
    """(SQLSTATE, primary message) of a database error, else ('', '')."""
    sqlstate = getattr(err, "sqlstate", None) or ""
    diag = getattr(err, "diag", None)
    msg = ""
    if diag is not None:
        msg = getattr(diag, "message_primary", None) or ""
    if not msg:
        msg = str(err).split("\n")[0]
    return str(sqlstate), msg


def to_app_error(err: BaseException) -> AppError:
    """Maps any exception to an AppError. Database error text never reaches the client."""
    if isinstance(err, AppError):
        return err

    sqlstate, msg = db_error_code(err)

    # RAISE EXCEPTION 'CODE' from the PL/pgSQL functions (SQLSTATE P0001).
    if sqlstate == "P0001" and re.fullmatch(r"[A-Z_]+", msg or ""):
        if msg == "INVALID_PLAN":
            return AppError(400, "VALIDATION_ERROR", "Invalid or inactive plan.")
        status = CODE_STATUS.get(msg)
        if status is not None:
            return AppError(status, msg, CODE_MESSAGES.get(msg, "The request could not be completed."))
        return _internal()

    if sqlstate == "23505":
        return AppError(409, "CONFLICT", "A record with the same unique value already exists.")
    if sqlstate == "23503":
        if re.search(r"still referenced|update or delete on table", msg, re.I):
            return AppError(409, "CONFLICT", "The record is referenced by other data and cannot be changed.")
        return AppError(400, "VALIDATION_ERROR", "A referenced record does not exist.")
    if sqlstate in ("23502", "23514", "22001", "22P02", "22003"):
        return AppError(400, "VALIDATION_ERROR", "The supplied data violates a database constraint.")
    return _internal()
