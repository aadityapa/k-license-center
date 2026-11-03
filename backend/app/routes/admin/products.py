"""/api/v1/admin/products — product catalogue (PRODUCT_VIEW / PRODUCT_MANAGE, governed writes)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from ... import schema as z
from ...db import Binds, Conn, Row, transaction
from ...deps import Ctx, json_body, require
from ...errors import AppError
from ...query import id_param, paged_query, parse_list, parse_sort, qs, qs_enum, to_camel
from ...respond import ok, pending_approval

# key_format and uses_lic_file tell the UI how a licence for this product is
# delivered — a typed key, a hardware-bound .lic file, or a Vehicle SIM key
# string — so the licence screens can show the right form without hard-coding
# product codes.
SELECT = """SELECT p.product_id, p.product_code, p.product_name, p.key_prefix, p.description,
       p.version, p.status, p.key_format, p.uses_lic_file, p.created_at, p.updated_at"""

SORT_WHITELIST = {
    "productId": "p.product_id",
    "productCode": "p.product_code",
    "productName": "p.product_name",
    "status": "p.status",
    "createdAt": "p.created_at",
}

create_schema = z.object({
    "productCode": z.string().min(2).max(30).regex(r"^[A-Z0-9_]+$", "Uppercase letters, digits and _ only"),
    "productName": z.string().min(1).max(100),
    "keyPrefix": z.string().min(2).max(6).regex(r"^[A-Z]+$", "Uppercase letters only"),
    "description": z.string().max(1000).optional(),
    "version": z.string().max(30).optional(),
    "status": z.enum(["ACTIVE", "INACTIVE"]).default("ACTIVE"),
})

update_schema = z.object({
    "productName": z.string().min(1).max(100).optional(),
    "description": z.string().max(1000).nullable().optional(),
    "version": z.string().max(30).nullable().optional(),
    "status": z.enum(["ACTIVE", "INACTIVE"]).optional(),
}).refine(lambda b: len(b) > 0, "No fields to update")

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


def get_product(conn: Conn, id: int) -> Row:
    r = conn.execute(f"{SELECT} FROM products p WHERE p.product_id = :p_id", {"p_id": id})
    row = r.first
    if not row:
        raise AppError(404, "NOT_FOUND", "Product not found.")
    return row


def _submit(ctx: Ctx, intent: dict[str, Any]) -> dict[str, Any]:
    from ...services.governance import submit_or_apply

    return submit_or_apply(ctx, intent)


@router.get("")
def list_products(ctx: Ctx = Depends(require("PRODUCT_VIEW"))):
    q_ = ctx.query
    pp = parse_list(q_)
    order_by = parse_sort(qs(q_, "sort"), SORT_WHITELIST, "p.product_id ASC")
    where = ["1=1"]
    binds: Binds = {}
    status = qs_enum(q_, "status", ["ACTIVE", "INACTIVE"])
    if status:
        where.append("p.status = :p_status")
        binds["p_status"] = status
    version = qs(q_, "version")
    if version:
        where.append("p.version = :p_version")
        binds["p_version"] = version
    q = qs(q_, "q")
    if q:
        where.append(
            "(UPPER(p.product_code) LIKE '%' || UPPER(:p_q) || '%' OR UPPER(p.product_name) LIKE '%' || UPPER(:p_q) || '%')"
        )
        binds["p_q"] = q
    with transaction() as conn:
        paged = paged_query(
            conn,
            select=SELECT,
            from_where=f"FROM products p WHERE {' AND '.join(where)}",
            binds=binds,
            order_by=order_by,
            page=pp.page,
            page_size=pp.page_size,
        )
        # Distinct versions across ALL products, so the filter dropdown offers every
        # real option rather than only those on the current page.
        versions_res = conn.execute("SELECT DISTINCT version FROM products WHERE version IS NOT NULL ORDER BY version")
        data = {**paged, "versions": [_s(r["VERSION"]) for r in versions_res.rows]}
    return ok(data)


@router.get("/{id}")
def get_one(id: str, ctx: Ctx = Depends(require("PRODUCT_VIEW"))):
    pid = id_param(id)
    with transaction() as conn:
        row = get_product(conn, pid)
    return ok(to_camel(row))


@router.post("")
def create_product(body: Any = Depends(json_body), ctx: Ctx = Depends(require("PRODUCT_MANAGE"))):
    b = create_schema.parse(body)
    summary = f'Create product "{b["productName"]}" ({b["productCode"]})'
    result = _submit(ctx, {
        "entityType": "PRODUCT",
        "operation": "PRODUCT_CREATE",
        "summary": summary,
        "payload": {**b},
    })
    if not result.get("applied"):
        return pending_approval(result.get("requestId"), summary)
    new_id = int((result.get("data") or {})["productId"])
    with transaction() as conn:
        row = get_product(conn, new_id)
    return ok(to_camel(row), 201)


@router.put("/{id}")
def update_product(id: str, body: Any = Depends(json_body), ctx: Ctx = Depends(require("PRODUCT_MANAGE"))):
    b = update_schema.parse(body)
    pid = id_param(id)
    with transaction() as conn:
        before = get_product(conn, pid)
    summary = f'Update product "{_s(before["PRODUCT_NAME"])}" ({_s(before["PRODUCT_CODE"])})'
    result = _submit(ctx, {
        "entityType": "PRODUCT",
        "entityId": pid,
        "operation": "PRODUCT_UPDATE",
        "summary": summary,
        "payload": {**b},
        "before": to_camel(before),
    })
    if not result.get("applied"):
        return pending_approval(result.get("requestId"), summary)
    with transaction() as conn:
        row = get_product(conn, pid)
    return ok(to_camel(row))


# ---- Delete (maker-checker: admin applies at once, a maker's delete waits in Approvals)
@router.delete("/{id}")
def delete_product(id: str, ctx: Ctx = Depends(require("PRODUCT_MANAGE"))):
    """Delete a product with its plans and API clients. Refused while it has licences."""
    from ...services.deletes import governed_delete

    pid = id_param(id)
    with transaction() as conn:
        before = get_product(conn, pid)  # 404s
        n = conn.execute("SELECT COUNT(*) AS n FROM licenses WHERE product_id = :p_id", {"p_id": pid}).first["N"]
    if int(n or 0) > 0:
        raise AppError(
            409, "PRODUCT_HAS_LICENSES",
            f"This product has {n} licence{'' if n == 1 else 's'}. Delete {'it' if n == 1 else 'them'} first "
            "(All Licences → Delete), then delete the product.",
        )
    summary = f"Delete product {_s(before['PRODUCT_NAME'])} ({_s(before['PRODUCT_CODE'])})"
    return governed_delete(ctx, "PRODUCT", pid, "PRODUCT_DELETE", summary, to_camel(before))
