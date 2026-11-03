"""/api/v1/admin/roles and /api/v1/admin/permissions (USER_MANAGE)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from ... import schema as z
from ...db import Conn, Row, transaction
from ...deps import Ctx, json_body, require
from ...errors import AppError
from ...query import id_param, rows_to_camel, to_camel
from ...respond import ok
from ...services.audit import log_audit
from ...services.protected_account import ADMIN_ROLE_CODE, protected_error

perms_schema = z.object({"permissions": z.array(z.string().min(1).max(40))})

_perm = require("USER_MANAGE")

router = APIRouter()
permissions_router = APIRouter()


def get_role_with_perms(conn: Conn, role_id: int) -> Row:
    r = conn.execute(
        """SELECT r.role_id, r.role_code, r.role_name, r.description, r.created_at,
            (SELECT string_agg(p.perm_code, ',' ORDER BY p.perm_code)
               FROM role_permissions rp JOIN permissions p ON p.perm_id = rp.perm_id
              WHERE rp.role_id = r.role_id) AS perm_codes
       FROM roles r WHERE r.role_id = :p_id""",
        {"p_id": role_id},
    )
    row = r.first
    if not row:
        raise AppError(404, "NOT_FOUND", "Role not found.")
    return row


def map_role(row: Row) -> Row:
    c = to_camel(row)
    pc = c.get("permCodes")
    c["permissions"] = pc.split(",") if isinstance(pc, str) and pc != "" else []
    c.pop("permCodes", None)
    return c


@router.get("")
def list_roles(ctx: Ctx = Depends(_perm)):
    with transaction() as conn:
        r = conn.execute(
            """SELECT r.role_id, r.role_code, r.role_name, r.description, r.created_at,
                  (SELECT string_agg(p.perm_code, ',' ORDER BY p.perm_code)
                     FROM role_permissions rp JOIN permissions p ON p.perm_id = rp.perm_id
                    WHERE rp.role_id = r.role_id) AS perm_codes
             FROM roles r ORDER BY r.role_id"""
        )
        items = [map_role(x) for x in r.rows]
    return ok({"items": items})


@router.put("/{id}/permissions")
def update_permissions(id: str, body: Any = Depends(json_body), ctx: Ctx = Depends(_perm)):
    b = perms_schema.parse(body)
    rid = id_param(id)
    permissions: list[str] = b["permissions"]
    user = ctx.user
    assert user is not None
    with transaction() as conn:
        before = map_role(get_role_with_perms(conn, rid))
        if before["roleCode"] == ADMIN_ROLE_CODE:
            raise protected_error("The ADMIN role always has every permission and cannot be edited.")
        conn.execute("DELETE FROM role_permissions WHERE role_id = :p_role_id", {"p_role_id": rid})
        for perm_code in permissions:
            r = conn.execute(
                """INSERT INTO role_permissions (role_id, perm_id)
             SELECT :p_role_id, p.perm_id FROM permissions p WHERE p.perm_code = :p_perm_code""",
                {"p_role_id": rid, "p_perm_code": perm_code},
            )
            if (r.rows_affected or 0) == 0:
                raise AppError(400, "VALIDATION_ERROR", f"Unknown permission code: {perm_code}")
        after = map_role(get_role_with_perms(conn, rid))
        log_audit(
            conn,
            user_id=user.user_id,
            actor=user.username,
            action="ROLE_PERMISSIONS_UPDATED",
            entity_type="ROLE",
            entity_id=rid,
            request_id=ctx.request_id,
            ip=ctx.ip,
            before={"permissions": before["permissions"]},
            after={"permissions": after["permissions"]},
        )
    return ok(after)


@permissions_router.get("")
def list_permissions(ctx: Ctx = Depends(_perm)):
    with transaction() as conn:
        r = conn.execute("SELECT perm_id, perm_code, perm_name AS description FROM permissions ORDER BY perm_code")
        items = rows_to_camel(r.rows)
    return ok({"items": items})
