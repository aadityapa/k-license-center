"""/api/v1/admin/api-clients — product API clients (APICLIENT_MANAGE, governed writes)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from ... import schema as z
from ...db import Binds, transaction
from ...deps import Ctx, json_body, require
from ...errors import AppError
from ...query import id_param, paged_query, parse_list, parse_sort, qs, qs_enum, qs_number
from ...respond import ok, pending_approval

# secret_hash and signing_key are never selected for list/detail responses
SELECT = """SELECT c.client_id, c.product_id, p.product_code, p.product_name, c.client_key,
       c.name, c.status, c.last_used_at, c.created_at, c.revoked_at"""

FROM = "FROM api_clients c JOIN products p ON p.product_id = c.product_id"

SORT_WHITELIST = {
    "clientId": "c.client_id",
    "name": "c.name",
    "status": "c.status",
    "createdAt": "c.created_at",
    "lastUsedAt": "c.last_used_at",
}

create_schema = z.object({
    "productId": z.number().int().positive(),
    "name": z.string().min(1).max(100),
})

revoke_schema = z.object({"reason": z.string().min(3).max(500).optional()})

_perm = require("APICLIENT_MANAGE")

router = APIRouter()


def _s(v: Any) -> str:
    """JavaScript String(v)."""
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def _submit(ctx: Ctx, intent: dict[str, Any]) -> dict[str, Any]:
    from ...services.governance import submit_or_apply

    return submit_or_apply(ctx, intent)


@router.get("")
def list_clients(ctx: Ctx = Depends(_perm)):
    q_ = ctx.query
    pp = parse_list(q_)
    order_by = parse_sort(qs(q_, "sort"), SORT_WHITELIST, "c.client_id ASC")
    where = ["1=1"]
    binds: Binds = {}
    product_id = qs_number(q_, "productId")
    if product_id is not None:
        where.append("c.product_id = :p_product_id")
        binds["p_product_id"] = product_id
    status = qs_enum(q_, "status", ["ACTIVE", "REVOKED"])
    if status:
        where.append("c.status = :p_status")
        binds["p_status"] = status
    q = qs(q_, "q")
    if q:
        where.append("UPPER(c.name) LIKE '%' || UPPER(:p_q) || '%'")
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


@router.post("")
def create_client(body: Any = Depends(json_body), ctx: Ctx = Depends(_perm)):
    b = create_schema.parse(body)
    # Credentials are minted inside apply_change, so nothing secret is ever
    # parked in a pending change_requests row.
    result = _submit(ctx, {
        "entityType": "API_CLIENT",
        "operation": "API_CLIENT_CREATE",
        "summary": f'Create API client "{b["name"]}"',
        "payload": {"productId": b["productId"], "name": b["name"]},
    })
    if not result.get("applied"):
        return pending_approval(result.get("requestId"), f'Create API client "{b["name"]}"')
    return ok(result.get("data"), 201)


@router.post("/{id}/revoke")
def revoke_client(id: str, body: Any = Depends(json_body), ctx: Ctx = Depends(_perm)):
    b = revoke_schema.parse(body)
    cid = id_param(id)
    reason = b.get("reason")

    # Read first so the summary names the client and a missing/already-revoked
    # one fails now rather than at approval time.
    with transaction() as conn:
        existing = conn.execute("SELECT client_id, name, status FROM api_clients WHERE client_id = :p_id", {"p_id": cid})
    row = existing.first
    if not row:
        raise AppError(404, "NOT_FOUND", "API client not found.")
    if row["STATUS"] != "ACTIVE":
        raise AppError(409, "CONFLICT", "API client is already revoked.")

    summary = f'Revoke API client "{_s(row["NAME"])}"' + (f" (reason: {reason})" if reason else "")
    result = _submit(ctx, {
        "entityType": "API_CLIENT",
        "entityId": cid,
        "operation": "API_CLIENT_REVOKE",
        "summary": summary,
        "payload": {"reason": reason},
        "before": {"status": "ACTIVE", "name": row["NAME"]},
    })
    if not result.get("applied"):
        return pending_approval(result.get("requestId"), summary)
    return ok(result.get("data"))


# ---- Delete (maker-checker: admin applies at once, a maker's delete waits in Approvals)
@router.delete("/{id}")
def delete_client(id: str, ctx: Ctx = Depends(_perm)):
    from ...query import to_camel
    from ...services.deletes import governed_delete

    cid = id_param(id)
    with transaction() as conn:
        row = conn.execute(
            """SELECT c.client_id, c.name, c.client_key, c.status, p.product_name
                 FROM api_clients c JOIN products p ON p.product_id = c.product_id WHERE c.client_id = :p_id""",
            {"p_id": cid},
        ).first
    if not row:
        raise AppError(404, "NOT_FOUND", "API client not found.")
    summary = f"Delete API client {row['NAME']} ({row['PRODUCT_NAME']})"
    return governed_delete(ctx, "API_CLIENT", cid, "API_CLIENT_DELETE", summary, to_camel(row))
