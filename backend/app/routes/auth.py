"""/api/v1/auth — sign in, current user, sign out."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from .. import schema as z
from ..config import config
from ..db import Conn, transaction
from ..deps import Ctx, admin_ctx, json_body
from ..errors import AppError
from ..ratelimit import route_limit
from ..respond import iso, ok
from ..security import check_password, sign_token
from ..services.protected_account import is_protected_username

router = APIRouter()

MAX_FAILED_ATTEMPTS = 5

login_schema = z.object({
    "username": z.string().min(1).max(50),
    "password": z.string().min(1).max(200),
})

login_limit = route_limit(config.rate_limit.login_window_ms, config.rate_limit.login_max)  # type: ignore[union-attr]


def load_permissions(conn: Conn, user_id: int) -> list[str]:
    r = conn.execute(
        """SELECT DISTINCT p.perm_code
             FROM user_roles ur
             JOIN role_permissions rp ON rp.role_id = ur.role_id
             JOIN permissions p ON p.perm_id = rp.perm_id
            WHERE ur.user_id = :p_user_id""",
        {"p_user_id": user_id},
    )
    return [str(row["PERM_CODE"]) for row in r.rows]


def load_roles(conn: Conn, user_id: int) -> list[str]:
    """Role names for display — the UI shows these under the user's name."""
    r = conn.execute(
        """SELECT r.role_name
             FROM user_roles ur JOIN roles r ON r.role_id = ur.role_id
            WHERE ur.user_id = :p_user_id
            ORDER BY r.role_name""",
        {"p_user_id": user_id},
    )
    return [str(row["ROLE_NAME"]) for row in r.rows]


@router.post("/login", dependencies=[Depends(login_limit)])
def login(body: Any = Depends(json_body)):
    data = login_schema.parse(body)
    username, password = data["username"], data["password"]

    with transaction() as conn:
        r = conn.execute(
            """SELECT user_id, username, email, full_name, password_hash, status, failed_attempts
                 FROM users WHERE username = :p_username""",
            {"p_username": username},
        )
        row = r.first
        outcome: dict[str, Any]
        if not row:
            outcome = {"kind": "invalid"}
        elif row["STATUS"] == "LOCKED":
            outcome = {"kind": "locked"}
        elif row["STATUS"] != "ACTIVE":
            outcome = {"kind": "inactive"}
        elif not check_password(password, str(row["PASSWORD_HASH"])):
            # committed even though login fails
            conn.execute(
                """UPDATE users
                      SET failed_attempts = failed_attempts + 1,
                          status = CASE WHEN failed_attempts + 1 >= :p_max THEN 'LOCKED' ELSE status END,
                          updated_at = now()
                    WHERE user_id = :p_user_id""",
                {
                    # The main admin is never auto-locked; the login rate limiter still slows guessing.
                    "p_max": 2147483647 if is_protected_username(row["USERNAME"]) else MAX_FAILED_ATTEMPTS,
                    "p_user_id": row["USER_ID"],
                },
            )
            outcome = {"kind": "invalid"}
        else:
            conn.execute(
                """UPDATE users
                      SET failed_attempts = 0, last_login_at = now(), updated_at = now()
                    WHERE user_id = :p_user_id""",
                {"p_user_id": row["USER_ID"]},
            )
            uid = int(row["USER_ID"])
            outcome = {
                "kind": "ok",
                "user": {
                    "userId": uid,
                    "username": str(row["USERNAME"]),
                    "email": str(row["EMAIL"]),
                    "fullName": str(row["FULL_NAME"]),
                    "roles": load_roles(conn, uid),
                },
                "permissions": load_permissions(conn, uid),
            }

    if outcome["kind"] == "locked":
        raise AppError(401, "UNAUTHORIZED", "Account is locked. Contact an administrator.")
    if outcome["kind"] in ("invalid", "inactive"):
        raise AppError(401, "UNAUTHORIZED", "Invalid username or password.")

    user = outcome["user"]
    token = sign_token(user["userId"], user["username"], outcome["permissions"])
    return ok({"token": token, "user": {**user, "permissions": outcome["permissions"]}})


@router.get("/me")
def me(ctx: Ctx = Depends(admin_ctx)):
    u = ctx.user
    assert u is not None
    with transaction() as conn:
        r = conn.execute(
            """SELECT user_id, username, email, full_name, status, last_login_at
                 FROM users WHERE user_id = :p_user_id""",
            {"p_user_id": u.user_id},
        )
        row = r.first
        if not row or row["STATUS"] != "ACTIVE":
            raise AppError(401, "UNAUTHORIZED", "User account is not active.")
        data = {
            "userId": int(row["USER_ID"]),
            "username": str(row["USERNAME"]),
            "email": str(row["EMAIL"]),
            "fullName": str(row["FULL_NAME"]),
            "lastLoginAt": iso(row["LAST_LOGIN_AT"]) if row["LAST_LOGIN_AT"] is not None else None,
            "roles": load_roles(conn, u.user_id),
            "permissions": u.permissions,
        }
    return ok(data)


@router.post("/logout")
def logout(_ctx: Ctx = Depends(admin_ctx)):
    # Stateless JWT: logout is a client-side token discard.
    return ok({"loggedOut": True})
