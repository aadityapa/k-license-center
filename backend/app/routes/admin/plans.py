"""/api/v1/admin/plans — product plans (read: PRODUCT_VIEW; write: PLAN_MANAGE, governed)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from ... import schema as z
from ...db import Binds, Conn, Row, transaction
from ...deps import Ctx, json_body, require
from ...errors import AppError
from ...query import id_param, paged_query, parse_list, parse_sort, qs, qs_enum, qs_number, to_camel
from ...respond import ok, pending_approval

SELECT = """SELECT pp.plan_id, pp.product_id, p.product_code, p.product_name, pp.plan_code, pp.plan_name,
       pp.duration_days, pp.is_lifetime, pp.price, pp.currency, pp.max_activations,
       pp.max_users, pp.max_branches, pp.status, pp.created_at, pp.updated_at"""

FROM = "FROM product_plans pp JOIN products p ON p.product_id = pp.product_id"

SORT_WHITELIST = {
    "planId": "pp.plan_id",
    "planCode": "pp.plan_code",
    "planName": "pp.plan_name",
    "productId": "pp.product_id",
    "productName": "p.product_name",
    # Lifetime plans have NULL duration; sort them last rather than letting the database
    # scatter them by its NULLS default.
    "durationDays": "COALESCE(pp.duration_days, 999999)",
    "price": "pp.price",
    "status": "pp.status",
    "createdAt": "pp.created_at",
    "updatedAt": "pp.updated_at",
}


def _lifetime_rule(b: dict[str, Any]) -> bool:
    if b.get("isLifetime"):
        return b.get("durationDays") is None
    d = b.get("durationDays")
    return (d if d is not None else 0) > 0


LIFETIME_MESSAGE = "Lifetime plans must omit durationDays; non-lifetime plans require durationDays > 0"

create_fields = z.object({
    "productId": z.number().int().positive(),
    "planCode": z.string().min(2).max(30).regex(r"^[A-Z0-9_]+$", "Uppercase letters, digits and _ only"),
    "planName": z.string().min(1).max(100),
    "durationDays": z.number().int().positive().max(99999).nullable().optional(),
    "isLifetime": z.boolean().default(False),
    "price": z.number().nonnegative().nullable().optional(),
    "currency": z.string().length(3).default("INR"),
    "maxActivations": z.number().int().positive().max(99999).default(1),
    "maxUsers": z.number().int().positive().max(99999).nullable().optional(),
    "maxBranches": z.number().int().positive().max(99999).nullable().optional(),
    "status": z.enum(["ACTIVE", "INACTIVE"]).default("ACTIVE"),
})

# The same fields with only their type rules. zod still runs an object's
# .refine() when its fields failed only value checks (min/max/regex/int/...),
# and adds the refine's message after theirs; it skips the refine when a field
# has the wrong type, is missing, or is not one of the enum values. This loose
# schema tells those two cases apart.
_create_types = z.object({
    "productId": z.number(),
    "planCode": z.string(),
    "planName": z.string(),
    "durationDays": z.number().nullable().optional(),
    "isLifetime": z.boolean().default(False),
    "price": z.number().nullable().optional(),
    "currency": z.string().default("INR"),
    "maxActivations": z.number().default(1),
    "maxUsers": z.number().nullable().optional(),
    "maxBranches": z.number().nullable().optional(),
    "status": z.enum(["ACTIVE", "INACTIVE"]).default("ACTIVE"),
})


def parse_create(body: Any) -> dict[str, Any]:
    """createSchema.parse: the fields, then the lifetime rule (z.object(...).refine(lifetimeRule))."""
    try:
        data = create_fields.parse(body)
    except AppError as e:
        types_ok, loose = _create_types.safe_parse(body)
        if types_ok and not _lifetime_rule(loose):
            raise AppError(400, "VALIDATION_ERROR", f"{e.message}; body: {LIFETIME_MESSAGE}") from None
        raise
    if not _lifetime_rule(data):
        raise AppError(400, "VALIDATION_ERROR", f"body: {LIFETIME_MESSAGE}")
    return data

update_schema = z.object({
    "planName": z.string().min(1).max(100).optional(),
    "price": z.number().nonnegative().nullable().optional(),
    "currency": z.string().length(3).optional(),
    "maxActivations": z.number().int().positive().max(99999).optional(),
    "maxUsers": z.number().int().positive().max(99999).nullable().optional(),
    "maxBranches": z.number().int().positive().max(99999).nullable().optional(),
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


def product_label(conn: Conn, product_id: int) -> str:
    """Product name for a readable approval summary; falls back to the id."""
    r = conn.execute("SELECT product_code, product_name FROM products WHERE product_id = :p_id", {"p_id": product_id})
    row = r.first
    if not row:
        raise AppError(404, "NOT_FOUND", "Product not found.")
    return f"{_s(row['PRODUCT_NAME'])} ({_s(row['PRODUCT_CODE'])})"


def get_plan(conn: Conn, id: int) -> Row:
    r = conn.execute(f"{SELECT} {FROM} WHERE pp.plan_id = :p_id", {"p_id": id})
    row = r.first
    if not row:
        raise AppError(404, "NOT_FOUND", "Plan not found.")
    return row


def _submit(ctx: Ctx, intent: dict[str, Any]) -> dict[str, Any]:
    from ...services.governance import submit_or_apply

    return submit_or_apply(ctx, intent)


# Reading plans is part of reading the product catalogue, so it needs only
# PRODUCT_VIEW. It used to sit behind PLAN_MANAGE, which meant a checker —
# who approves licence requests and must pick the plan to grant — could not
# load the plan list to approve with. Writes still need PLAN_MANAGE.
@router.get("")
def list_plans(ctx: Ctx = Depends(require("PRODUCT_VIEW"))):
    q_ = ctx.query
    pp = parse_list(q_)
    order_by = parse_sort(qs(q_, "sort"), SORT_WHITELIST, "pp.plan_id ASC")
    where = ["1=1"]
    binds: Binds = {}
    product_id = qs_number(q_, "productId")
    if product_id is not None:
        where.append("pp.product_id = :p_product_id")
        binds["p_product_id"] = product_id
    status = qs_enum(q_, "status", ["ACTIVE", "INACTIVE"])
    if status:
        where.append("pp.status = :p_status")
        binds["p_status"] = status
    q = qs(q_, "q")
    if q:
        where.append(
            "(UPPER(pp.plan_code) LIKE '%' || UPPER(:p_q) || '%' OR UPPER(pp.plan_name) LIKE '%' || UPPER(:p_q) || '%')"
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


@router.get("/{id}")
def get_one(id: str, ctx: Ctx = Depends(require("PRODUCT_VIEW"))):
    pid = id_param(id)
    with transaction() as conn:
        row = get_plan(conn, pid)
    return ok(to_camel(row))


@router.post("")
def create_plan(body: Any = Depends(json_body), ctx: Ctx = Depends(require("PLAN_MANAGE"))):
    b = parse_create(body)
    with transaction() as conn:
        product = product_label(conn, b["productId"])
    summary = f'Create plan "{b["planName"]}" ({b["planCode"]}) on product {product}'
    result = _submit(ctx, {
        "entityType": "PLAN",
        "operation": "PLAN_CREATE",
        "summary": summary,
        "payload": {
            **b,
            # Lifetime plans carry no duration; normalise here so the stored
            # payload is exactly what gets written.
            "durationDays": None if b["isLifetime"] else b.get("durationDays"),
        },
    })
    if not result.get("applied"):
        return pending_approval(result.get("requestId"), summary)
    new_id = int((result.get("data") or {})["planId"])
    with transaction() as conn:
        row = get_plan(conn, new_id)
    return ok(to_camel(row), 201)


@router.put("/{id}")
def update_plan(id: str, body: Any = Depends(json_body), ctx: Ctx = Depends(require("PLAN_MANAGE"))):
    b = update_schema.parse(body)
    pid = id_param(id)
    with transaction() as conn:
        before = get_plan(conn, pid)
    summary = (
        f'Update plan "{_s(before["PLAN_NAME"])}" ({_s(before["PLAN_CODE"])}) '
        f'on product {_s(before["PRODUCT_NAME"])} ({_s(before["PRODUCT_CODE"])})'
    )
    result = _submit(ctx, {
        "entityType": "PLAN",
        "entityId": pid,
        "operation": "PLAN_UPDATE",
        "summary": summary,
        "payload": {**b},
        "before": to_camel(before),
    })
    if not result.get("applied"):
        return pending_approval(result.get("requestId"), summary)
    with transaction() as conn:
        row = get_plan(conn, pid)
    return ok(to_camel(row))


@router.delete("/{id}")
def delete_plan(id: str, ctx: Ctx = Depends(require("PLAN_MANAGE"))):
    """Delete a plan no licence has ever used. A used plan is archived instead."""
    pid = id_param(id)
    with transaction() as conn:
        before = get_plan(conn, pid)  # 404s
        r = conn.execute(
            """SELECT (SELECT COUNT(*) FROM licenses WHERE plan_id = :p_id)
                + (SELECT COUNT(*) FROM license_renewals WHERE new_plan_id = :p_id OR prev_plan_id = :p_id) AS plan_uses""",
            {"p_id": pid},
        )
        first = r.first or {}
        uses = int(first.get("PLAN_USES") if first.get("PLAN_USES") is not None else 0)
    if uses > 0:
        raise AppError(
            409,
            "PLAN_IN_USE",
            f'"{_s(before["PLAN_NAME"])}" is used by licences, so it cannot be deleted — that would erase what '
            "those customers bought. Archive it instead.",
        )
    summary = f'Delete plan "{_s(before["PLAN_NAME"])}" ({_s(before["PLAN_CODE"])}) of {_s(before["PRODUCT_NAME"])}'
    result = _submit(ctx, {
        "entityType": "PLAN",
        "entityId": pid,
        "operation": "PLAN_DELETE",
        "summary": summary,
        "payload": {},
        "before": to_camel(before),
    })
    if not result.get("applied"):
        return pending_approval(result.get("requestId"), summary)
    return ok({"planId": pid, "deleted": True})
