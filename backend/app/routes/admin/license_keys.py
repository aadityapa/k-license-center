"""/api/v1/admin/license-keys — every key ever minted (LICENSE_VIEW on the whole router)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request

from ...db import Binds, transaction
from ...deps import Ctx, check_perm, require
from ...errors import AppError
from ...query import id_param, paged_query, parse_list, parse_sort, qs, qs_enum, qs_number, to_camel
from ...respond import ok, pending_approval
from ...services.governance import submit_or_apply

SELECT = """SELECT k.key_id, k.license_id, l.license_no, c.company_name AS customer_name,
       p.product_code, p.product_name,
       k.license_key, k.status, k.generated_at, k.generated_by, u.username AS generated_by_username,
       k.revoked_at"""

FROM = """FROM license_keys k
  JOIN licenses l   ON l.license_id = k.license_id
  JOIN customers c  ON c.customer_id = l.customer_id
  JOIN products p   ON p.product_id = l.product_id
  LEFT JOIN users u ON u.user_id = k.generated_by"""

SORT_WHITELIST = {
    "keyId": "k.key_id",
    "licenseId": "k.license_id",
    "status": "k.status",
    "generatedAt": "k.generated_at",
}

# router.use(requirePermission('LICENSE_VIEW')) — runs before every route of this router.
_view = require("LICENSE_VIEW")

router = APIRouter()


@router.get("")
def list_keys(ctx: Ctx = Depends(_view)):
    q_ = ctx.query
    pp = parse_list(q_)
    order_by = parse_sort(qs(q_, "sort"), SORT_WHITELIST, "k.key_id DESC")
    where: list[str] = ["1=1"]
    binds: Binds = {}
    license_id = qs_number(q_, "licenseId")
    if license_id is not None:
        where.append("k.license_id = :p_license_id")
        binds["p_license_id"] = license_id
    status = qs_enum(q_, "status", ["ACTIVE", "REVOKED"])
    if status:
        where.append("k.status = :p_status")
        binds["p_status"] = status
    q = qs(q_, "q")
    if q:
        where.append(
            """(UPPER(k.license_key) LIKE '%' || UPPER(:p_q) || '%'
            OR UPPER(l.license_no) LIKE '%' || UPPER(:p_q) || '%')"""
        )
        binds["p_q"] = q
    with transaction() as conn:
        data = paged_query(
            conn,
            select=SELECT,
            from_where=f"{FROM} WHERE {' AND '.join(where)}",
            binds=binds,
            order_by=order_by,
            page=pp.page,
            page_size=pp.page_size,
        )
    return ok(data)


@router.delete("/{id}")
def delete_key(id: str, ctx: Ctx = Depends(_view)):
    """Delete a key record. Only REVOKED keys: the live key is what the customer's
    app is running on, so it has to be revoked (or replaced) first."""
    check_perm(ctx, "LICENSE_MANAGE")
    kid = id_param(id)
    with transaction() as conn:
        before = conn.execute(f"{SELECT} {FROM} WHERE k.key_id = :p_key_id", {"p_key_id": kid}).first
    if not before:
        raise AppError(404, "NOT_FOUND", "Key not found.")
    if str(before["STATUS"]) == "ACTIVE":
        raise AppError(
            409,
            "KEY_ACTIVE",
            "This is the live key a customer is using. Revoke it or issue a new key first; only revoked keys can be deleted.",
        )
    summary = f"Delete revoked key of licence {before['LICENSE_NO']} ({before['CUSTOMER_NAME']})"
    snapshot: dict[str, Any] = to_camel(before)
    # Never copy the full key into the approval record.
    if isinstance(snapshot.get("licenseKey"), str):
        snapshot["licenseKey"] = f"{snapshot['licenseKey'][:9]}…"
    result = submit_or_apply(ctx, {
        "entityType": "LICENSE_KEY",
        "entityId": kid,
        "operation": "LICENSE_KEY_DELETE",
        "summary": summary,
        "payload": {},
        "before": snapshot,
    })
    if not result["applied"]:
        return pending_approval(result.get("requestId"), summary)
    return ok({"keyId": kid, "deleted": True})


# Express ran the router-level permission check before deciding "no such route".
_ALL = ["GET", "POST", "PUT", "PATCH", "DELETE"]


@router.api_route("", methods=_ALL, include_in_schema=False)
@router.api_route("/{rest:path}", methods=_ALL, include_in_schema=False)
def _unmatched(request: Request, ctx: Ctx = Depends(_view)):
    raise AppError(404, "NOT_FOUND", "Resource not found.")
