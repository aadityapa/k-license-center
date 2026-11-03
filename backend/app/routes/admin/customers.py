"""/api/v1/admin/customers — customers (CUSTOMER_VIEW / CUSTOMER_MANAGE, governed writes)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from ... import schema as z
from ...db import Binds, Conn, Row, transaction
from ...deps import Ctx, json_body, require
from ...errors import AppError
from ...query import id_param, paged_query, parse_list, parse_sort, qs, qs_date, qs_enum, rows_to_camel, to_camel
from ...respond import ok, pending_approval

SELECT = """SELECT c.customer_id, c.customer_code, c.company_name, c.contact_person, c.email,
       c.mobile, c.whatsapp, c.address_line1, c.address_line2, c.city, c.state, c.country,
       c.gst_number, c.status, c.created_at, c.updated_at"""

SORT_WHITELIST = {
    "customerId": "c.customer_id",
    "customerCode": "c.customer_code",
    "companyName": "c.company_name",
    "status": "c.status",
    "createdAt": "c.created_at",
}

create_schema = z.object({
    "customerCode": z.string().min(2).max(30),
    "companyName": z.string().min(1).max(200),
    "contactPerson": z.string().max(150).optional(),
    "email": z.string().email().max(255).optional(),
    "mobile": z.string().max(20).optional(),
    "whatsapp": z.string().max(20).optional(),
    "addressLine1": z.string().max(255).optional(),
    "addressLine2": z.string().max(255).optional(),
    "city": z.string().max(100).optional(),
    "state": z.string().max(100).optional(),
    "country": z.string().max(100).default("India"),
    "gstNumber": z.string().max(30).optional(),
    "status": z.enum(["ACTIVE", "INACTIVE"]).default("ACTIVE"),
})

update_schema = z.object({
    "companyName": z.string().min(1).max(200).optional(),
    "contactPerson": z.string().max(150).nullable().optional(),
    "email": z.string().email().max(255).nullable().optional(),
    "mobile": z.string().max(20).nullable().optional(),
    "whatsapp": z.string().max(20).nullable().optional(),
    "addressLine1": z.string().max(255).nullable().optional(),
    "addressLine2": z.string().max(255).nullable().optional(),
    "city": z.string().max(100).nullable().optional(),
    "state": z.string().max(100).nullable().optional(),
    "country": z.string().max(100).optional(),
    "gstNumber": z.string().max(30).nullable().optional(),
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


def get_customer(conn: Conn, id: int) -> Row:
    r = conn.execute(f"{SELECT} FROM customers c WHERE c.customer_id = :p_id", {"p_id": id})
    row = r.first
    if not row:
        raise AppError(404, "NOT_FOUND", "Customer not found.")
    return row


def _submit(ctx: Ctx, intent: dict[str, Any]) -> dict[str, Any]:
    from ...services.governance import submit_or_apply

    return submit_or_apply(ctx, intent)


@router.get("")
def list_customers(ctx: Ctx = Depends(require("CUSTOMER_VIEW"))):
    q_ = ctx.query
    pp = parse_list(q_)
    order_by = parse_sort(qs(q_, "sort"), SORT_WHITELIST, "c.customer_id ASC")
    where = ["1=1"]
    binds: Binds = {}
    status = qs_enum(q_, "status", ["ACTIVE", "INACTIVE"])
    if status:
        where.append("c.status = :p_status")
        binds["p_status"] = status
    date_filters = [
        ("c.created_at >= TO_DATE(:p_created_from, 'YYYY-MM-DD')", "p_created_from", qs_date(q_, "createdFrom")),
        ("c.created_at < TO_DATE(:p_created_to, 'YYYY-MM-DD') + 1", "p_created_to", qs_date(q_, "createdTo")),
    ]
    for clause, bind_name, value in date_filters:
        if value is not None:
            where.append(clause)
            binds[bind_name] = value
    q = qs(q_, "q")
    if q:
        where.append(
            """(UPPER(c.customer_code) LIKE '%' || UPPER(:p_q) || '%'
            OR UPPER(c.company_name) LIKE '%' || UPPER(:p_q) || '%'
            OR UPPER(COALESCE(c.contact_person, ' ')) LIKE '%' || UPPER(:p_q) || '%'
            OR UPPER(COALESCE(c.email, ' ')) LIKE '%' || UPPER(:p_q) || '%')"""
        )
        binds["p_q"] = q
    with transaction() as conn:
        data = paged_query(
            conn,
            select=SELECT,
            from_where=f"FROM customers c WHERE {' AND '.join(where)}",
            binds=binds,
            order_by=order_by,
            page=pp.page,
            page_size=pp.page_size,
        )
    return ok(data)


@router.get("/{id}")
def get_one(id: str, ctx: Ctx = Depends(require("CUSTOMER_VIEW"))):
    cid = id_param(id)
    with transaction() as conn:
        row = get_customer(conn, cid)
    return ok(to_camel(row))


@router.get("/{id}/licenses")
def customer_licenses(id: str, ctx: Ctx = Depends(require("CUSTOMER_VIEW"))):
    cid = id_param(id)
    with transaction() as conn:
        get_customer(conn, cid)  # 404 when missing
        bind = {"p_customer_id": cid}
        licenses = conn.execute(
            """SELECT l.license_id, l.license_no, l.customer_id, l.product_id, l.plan_id,
                  l.status, l.start_date, l.expiry_date,
                  l.max_activations, l.max_users, l.max_branches, l.current_activations,
                  l.auto_renewal, l.created_at,
                  p.product_code, p.product_name, pp.plan_code, pp.plan_name,
                  (SELECT k.license_key FROM license_keys k
                    WHERE k.license_id = l.license_id AND k.status = 'ACTIVE') AS license_key,
                  (SELECT COUNT(*) FROM license_renewals rn
                    WHERE rn.license_id = l.license_id) AS renewal_count
             FROM licenses l
             JOIN products p       ON p.product_id = l.product_id
             JOIN product_plans pp ON pp.plan_id = l.plan_id
            WHERE l.customer_id = :p_customer_id
            ORDER BY l.created_at DESC""",
            bind,
        )
        keys = conn.execute(
            """SELECT k.key_id, k.license_id, l.license_no, k.license_key, k.status,
                  k.generated_at, k.revoked_at
             FROM license_keys k
             JOIN licenses l ON l.license_id = k.license_id
            WHERE l.customer_id = :p_customer_id
            ORDER BY k.generated_at DESC""",
            bind,
        )
        activations = conn.execute(
            """SELECT a.activation_id, a.license_id, l.license_no, a.installation_id, a.device_id,
                  a.device_name, a.os_info, a.app_version, a.status, a.activated_at,
                  a.last_heartbeat_at, a.deactivated_at, a.deactivation_reason
             FROM license_activations a
             JOIN licenses l ON l.license_id = a.license_id
            WHERE l.customer_id = :p_customer_id
            ORDER BY a.activated_at DESC""",
            bind,
        )
        renewals = conn.execute(
            """SELECT r.renewal_id, r.license_id, l.license_no, r.prev_plan_id, r.new_plan_id,
                  pp.plan_name AS new_plan_name, r.prev_expiry_date, r.new_expiry_date,
                  r.renewal_date, r.amount, r.currency, r.payment_ref, r.notes
             FROM license_renewals r
             JOIN licenses l       ON l.license_id = r.license_id
             JOIN product_plans pp ON pp.plan_id = r.new_plan_id
            WHERE l.customer_id = :p_customer_id
            ORDER BY r.renewal_date DESC""",
            bind,
        )
        history = conn.execute(
            """SELECT h.history_id, h.license_id, h.old_status, h.new_status, h.changed_at,
                  h.changed_by, h.reason
             FROM license_history h
             JOIN licenses l ON l.license_id = h.license_id
            WHERE l.customer_id = :p_customer_id
            ORDER BY h.changed_at DESC""",
            bind,
        )
        data = {
            "licenses": rows_to_camel(licenses.rows),
            "keys": rows_to_camel(keys.rows),
            "activations": rows_to_camel(activations.rows),
            "renewals": rows_to_camel(renewals.rows),
            "history": rows_to_camel(history.rows),
        }
    return ok(data)


@router.post("")
def create_customer(body: Any = Depends(json_body), ctx: Ctx = Depends(require("CUSTOMER_MANAGE"))):
    b = create_schema.parse(body)
    summary = f'Create customer "{b["companyName"]}" ({b["customerCode"]})'
    result = _submit(ctx, {
        "entityType": "CUSTOMER",
        "operation": "CUSTOMER_CREATE",
        "summary": summary,
        "payload": {**b},
    })
    if not result.get("applied"):
        return pending_approval(result.get("requestId"), summary)
    new_id = int((result.get("data") or {})["customerId"])
    with transaction() as conn:
        row = get_customer(conn, new_id)
    return ok(to_camel(row), 201)


@router.put("/{id}")
def update_customer(id: str, body: Any = Depends(json_body), ctx: Ctx = Depends(require("CUSTOMER_MANAGE"))):
    b = update_schema.parse(body)
    cid = id_param(id)
    # 404s early, and gives the checker a diff base.
    with transaction() as conn:
        before = get_customer(conn, cid)
    summary = f'Update customer "{_s(before["COMPANY_NAME"])}" ({_s(before["CUSTOMER_CODE"])})'
    result = _submit(ctx, {
        "entityType": "CUSTOMER",
        "entityId": cid,
        "operation": "CUSTOMER_UPDATE",
        "summary": summary,
        "payload": {**b},
        "before": to_camel(before),
    })
    if not result.get("applied"):
        return pending_approval(result.get("requestId"), summary)
    with transaction() as conn:
        row = get_customer(conn, cid)
    return ok(to_camel(row))


@router.delete("/{id}")
def delete_customer(id: str, ctx: Ctx = Depends(require("CUSTOMER_MANAGE"))):
    """Delete a customer. Refused up front, with the reason, when the customer has
    licences — so a maker is told now rather than after a checker approves."""
    cid = id_param(id)
    with transaction() as conn:
        before = get_customer(conn, cid)  # 404s
        r = conn.execute("SELECT COUNT(*) AS n FROM licenses WHERE customer_id = :p_id", {"p_id": cid})
        first = r.first or {}
        licences = int(first.get("N") if first.get("N") is not None else 0)
    if licences > 0:
        raise AppError(
            409,
            "CUSTOMER_HAS_LICENSES",
            f'"{_s(before["COMPANY_NAME"])}" has {licences} licence{"" if licences == 1 else "s"}, so it cannot be '
            "deleted — that would erase who those licences belong to. Set the customer to Inactive instead.",
        )
    summary = f'Delete customer "{_s(before["COMPANY_NAME"])}" ({_s(before["CUSTOMER_CODE"])})'
    result = _submit(ctx, {
        "entityType": "CUSTOMER",
        "entityId": cid,
        "operation": "CUSTOMER_DELETE",
        "summary": summary,
        "payload": {},
        "before": to_camel(before),
    })
    if not result.get("applied"):
        return pending_approval(result.get("requestId"), summary)
    return ok({"customerId": cid, "deleted": True})
