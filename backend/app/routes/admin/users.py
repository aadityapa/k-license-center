"""/api/v1/admin/users — admin user accounts (USER_MANAGE)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from ... import schema as z
from ...db import OUT, Binds, Conn, Row, transaction
from ...deps import Ctx, json_body, require
from ...errors import AppError
from ...query import id_param, paged_query, parse_list, parse_sort, qs, qs_enum, to_camel
from ...respond import ok
from ...config import config
from ...security import hash_password
from ...services.audit import log_audit
from ...services.prod_guard import DEFAULT_PASSWORDS
from ...services.protected_account import ADMIN_ROLE_CODE, is_protected_username, protected_error
from ...services.session_revocation import revoke_sessions

BCRYPT_COST = 12

SELECT = """SELECT u.user_id, u.username, u.email, u.full_name, u.status, u.failed_attempts,
       u.last_login_at, u.created_at, u.updated_at,
       (SELECT string_agg(r.role_id || ':' || r.role_code, ',' ORDER BY r.role_code)
          FROM user_roles ur JOIN roles r ON r.role_id = ur.role_id
         WHERE ur.user_id = u.user_id) AS role_data"""

SORT_WHITELIST = {
    "userId": "u.user_id",
    "username": "u.username",
    "email": "u.email",
    "fullName": "u.full_name",
    "status": "u.status",
    "createdAt": "u.created_at",
    "lastLoginAt": "u.last_login_at",
}

create_schema = z.object({
    "username": z.string().min(3).max(50).regex(r"^[a-zA-Z0-9._-]+$", "Invalid username characters"),
    "email": z.string().email().max(255),
    "fullName": z.string().min(1).max(150),
    "password": z.string().min(8).max(200),
    "status": z.enum(["ACTIVE", "LOCKED", "INACTIVE"]).default("ACTIVE"),
    "roleIds": z.array(z.number().int().positive()).default([]),
})

update_schema = z.object({
    "email": z.string().email().max(255).optional(),
    "fullName": z.string().min(1).max(150).optional(),
    "status": z.enum(["ACTIVE", "LOCKED", "INACTIVE"]).optional(),
    "password": z.string().min(8).max(200).optional(),
}).refine(lambda b: len(b) > 0, "No fields to update")

roles_schema = z.object({"roleIds": z.array(z.number().int().positive())})

_perm = require("USER_MANAGE")

router = APIRouter()


def _refuse_default_password(pw: str) -> None:
    """In production a published default password (Pass@100%, ChangeMe@123) is refused:
    the API would refuse to start with such an account (services/prod_guard.py)."""
    if config.env == "production" and pw in DEFAULT_PASSWORDS:
        raise AppError(
            400,
            "VALIDATION_ERROR",
            "This is a published default password and is not allowed on the live server. Choose another password.",
        )


def _js_number(s: str) -> Any:
    """Number(s) for the role-id half of 'id:code' (always digits in practice)."""
    try:
        f = float(s.strip()) if s.strip() != "" else 0.0
    except ValueError:
        return None  # NaN -> null in JSON
    return int(f) if f.is_integer() else f


def _parse_roles(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, str) or raw == "":
        return []
    roles = []
    for pair in raw.split(","):
        idx = pair.find(":")
        # JS: pair.slice(0, -1) when idx === -1
        role_id = pair[:idx] if idx != -1 else pair[:-1]
        roles.append({"roleId": _js_number(role_id), "roleCode": pair[idx + 1:]})
    return roles


def map_user(row: Row) -> Row:
    c = to_camel(row)
    roles = _parse_roles(c.get("roleData"))
    c.pop("roleData", None)
    c["roles"] = roles
    c["roleIds"] = [r["roleId"] for r in roles]
    return c


def get_user(conn: Conn, id: int) -> Row:
    r = conn.execute(f"{SELECT} FROM users u WHERE u.user_id = :p_id", {"p_id": id})
    row = r.first
    if not row or row["STATUS"] == "DELETED":
        raise AppError(404, "NOT_FOUND", "User not found.")
    return row


def replace_roles(conn: Conn, user_id: int, role_ids: list[int], granted_by: int) -> None:
    conn.execute("DELETE FROM user_roles WHERE user_id = :p_user_id", {"p_user_id": user_id})
    for role_id in role_ids:
        conn.execute(
            """INSERT INTO user_roles (user_id, role_id, granted_by)
       VALUES (:p_user_id, :p_role_id, :p_granted_by)""",
            {"p_user_id": user_id, "p_role_id": role_id, "p_granted_by": granted_by},
        )


@router.get("")
def list_users(ctx: Ctx = Depends(_perm)):
    q_ = ctx.query
    pp = parse_list(q_)
    order_by = parse_sort(qs(q_, "sort"), SORT_WHITELIST, "u.user_id ASC")
    # Deleted users are kept for the audit trail but never listed.
    where = ["u.status <> 'DELETED'"]
    binds: Binds = {}
    status = qs_enum(q_, "status", ["ACTIVE", "LOCKED", "INACTIVE"])
    if status:
        where.append("u.status = :p_status")
        binds["p_status"] = status
    q = qs(q_, "q")
    if q:
        where.append(
            """(UPPER(u.username) LIKE '%' || UPPER(:p_q) || '%'
            OR UPPER(u.email) LIKE '%' || UPPER(:p_q) || '%'
            OR UPPER(u.full_name) LIKE '%' || UPPER(:p_q) || '%')"""
        )
        binds["p_q"] = q
    with transaction() as conn:
        data = paged_query(
            conn,
            select=SELECT,
            from_where=f"FROM users u WHERE {' AND '.join(where)}",
            binds=binds,
            order_by=order_by,
            page=pp.page,
            page_size=pp.page_size,
        )
    items = []
    for item in data["items"]:
        roles = _parse_roles(item.get("roleData"))
        item.pop("roleData", None)
        item["roles"] = roles
        item["roleIds"] = [r["roleId"] for r in roles]
        items.append(item)
    data["items"] = items
    return ok(data)


@router.post("")
def create_user(body: Any = Depends(json_body), ctx: Ctx = Depends(_perm)):
    b = create_schema.parse(body)
    user = ctx.user
    assert user is not None
    _refuse_default_password(b["password"])
    password_hash = hash_password(b["password"], BCRYPT_COST)
    with transaction() as conn:
        r = conn.execute(
            """INSERT INTO users (username, email, full_name, password_hash, status)
           VALUES (:p_username, :p_email, :p_full_name, :p_hash, :p_status)
           RETURNING user_id AS o_id""",
            {
                "p_username": b["username"],
                "p_email": b["email"],
                "p_full_name": b["fullName"],
                "p_hash": password_hash,
                "p_status": b["status"],
                "o_id": OUT,
            },
        )
        new_id = int(r.out_binds["o_id"])
        if len(b["roleIds"]) > 0:
            replace_roles(conn, new_id, b["roleIds"], user.user_id)
        log_audit(
            conn,
            user_id=user.user_id,
            actor=user.username,
            action="USER_CREATED",
            entity_type="USER",
            entity_id=new_id,
            request_id=ctx.request_id,
            ip=ctx.ip,
            after={"username": b["username"], "email": b["email"], "fullName": b["fullName"], "roleIds": b["roleIds"]},
        )
        row = get_user(conn, new_id)
    return ok(map_user(row), 201)


@router.put("/{id}")
def update_user(id: str, body: Any = Depends(json_body), ctx: Ctx = Depends(_perm)):
    b = update_schema.parse(body)
    if "password" in b:
        _refuse_default_password(b["password"])
    uid = id_param(id)
    user = ctx.user
    assert user is not None
    revoke_after_commit: list[int] = []
    with transaction() as conn:
        before = get_user(conn, uid)
        if is_protected_username(before["USERNAME"]):
            if "status" in b and b["status"] != "ACTIVE":
                raise protected_error("The main admin account cannot be locked or deactivated.")
            changes_details = (
                ("email" in b and b["email"] != before["EMAIL"])
                or ("fullName" in b and b["fullName"] != before["FULL_NAME"])
                or "password" in b
            )
            if changes_details and user.user_id != uid:
                raise protected_error(
                    "Only the admin can change the main admin account's name, email or password (sign in as admin).",
                    403,
                )
        sets: list[str] = []
        binds: Binds = {"p_id": uid}
        if "email" in b:
            sets.append("email = :s_email")
            binds["s_email"] = b["email"]
        if "fullName" in b:
            sets.append("full_name = :s_full_name")
            binds["s_full_name"] = b["fullName"]
        if "status" in b:
            sets.append("status = :s_status")
            binds["s_status"] = b["status"]
            if b["status"] == "ACTIVE":
                sets.append("failed_attempts = 0")  # unlock resets the counter
        if "password" in b:
            sets.append("password_hash = :s_hash")
            binds["s_hash"] = hash_password(b["password"], BCRYPT_COST)
        sets.append("updated_at = now()")
        conn.execute(f"UPDATE users SET {', '.join(sets)} WHERE user_id = :p_id", binds)
        after = get_user(conn, uid)
        # Changing your OWN password keeps you signed in; anyone else is
        # signed out so the old password stops working everywhere at once.
        if uid != user.user_id and (("status" in b and b["status"] != "ACTIVE") or "password" in b):
            revoke_after_commit.append(uid)
        log_audit(
            conn,
            user_id=user.user_id,
            actor=user.username,
            action="USER_UPDATED",
            entity_type="USER",
            entity_id=uid,
            request_id=ctx.request_id,
            ip=ctx.ip,
            before=map_user(before),
            after=map_user(after),
        )
        row = after
    # A locked/deactivated user, or one whose password was reset, signs in again.
    for x in revoke_after_commit:
        revoke_sessions(x)
    return ok(map_user(row))


@router.put("/{id}/roles")
def update_roles(id: str, body: Any = Depends(json_body), ctx: Ctx = Depends(_perm)):
    b = roles_schema.parse(body)
    uid = id_param(id)
    role_ids: list[int] = b["roleIds"]
    user = ctx.user
    assert user is not None
    with transaction() as conn:
        before = get_user(conn, uid)
        if is_protected_username(before["USERNAME"]):
            admin_role = next((r for r in map_user(before)["roles"] if r["roleCode"] == ADMIN_ROLE_CODE), None)
            if admin_role and admin_role["roleId"] not in role_ids:
                raise protected_error("The main admin account must keep the ADMIN role.")
        replace_roles(conn, uid, role_ids, user.user_id)
        after = get_user(conn, uid)
        log_audit(
            conn,
            user_id=user.user_id,
            actor=user.username,
            action="USER_ROLES_UPDATED",
            entity_type="USER",
            entity_id=uid,
            request_id=ctx.request_id,
            ip=ctx.ip,
            before={"roles": map_user(before)["roles"]},
            after={"roles": map_user(after)["roles"]},
        )
        row = after
    # Permissions travel in the token: make the user sign in again to pick
    # up the new set (unless they changed their own roles).
    if uid != user.user_id:
        revoke_sessions(uid)
    return ok(map_user(row))


@router.delete("/{id}")
def delete_user(id: str, ctx: Ctx = Depends(_perm)):
    """Delete a user. The row stays (status DELETED) so the audit log, licence
    history and approvals keep naming who did what; see 005_user_delete.sql."""
    uid = id_param(id)
    user = ctx.user
    assert user is not None
    if uid == user.user_id:
        raise AppError(409, "CONFLICT", "You cannot delete your own account.")
    with transaction() as conn:
        before = get_user(conn, uid)
        if is_protected_username(before["USERNAME"]):
            raise protected_error("The main admin account cannot be deleted.")
        conn.execute(
            """UPDATE users
              SET status = 'DELETED',
                  username = LEFT('deleted-' || user_id || '-' || username, 50),
                  email = LEFT('deleted-' || user_id || '-' || email, 255),
                  password_hash = '!deleted',
                  failed_attempts = 0,
                  deleted_at = now(), deleted_by = :p_by, updated_at = now()
            WHERE user_id = :p_id""",
            {"p_id": uid, "p_by": user.user_id},
        )
        conn.execute("DELETE FROM user_roles WHERE user_id = :p_user_id", {"p_user_id": uid})
        # Their open requests can no longer be followed up by them.
        conn.execute(
            """UPDATE change_requests
              SET status = 'CANCELLED', reviewed_at = now(),
                  review_comment = 'Requester account deleted'
            WHERE requested_by = :p_requester AND status = 'PENDING'""",
            {"p_requester": uid},
        )
        log_audit(
            conn,
            user_id=user.user_id,
            actor=user.username,
            action="USER_DELETED",
            entity_type="USER",
            entity_id=uid,
            request_id=ctx.request_id,
            ip=ctx.ip,
            before=map_user(before),
        )
    revoke_sessions(uid)
    return ok({"userId": uid, "deleted": True})
