"""/api/v1/admin/renewals — renewal history with year-to-date headline figures (LICENSE_VIEW)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request

from ...db import Binds, transaction
from ...deps import Ctx, require
from ...errors import AppError
from ...query import paged_query, parse_list, parse_sort, qs, qs_date, qs_number
from ...respond import ok

SELECT = """SELECT r.renewal_id, r.license_id, l.license_no, c.company_name AS customer_name,
       p.product_code, p.product_name, r.prev_plan_id, r.new_plan_id,
       pp_prev.plan_name AS prev_plan_name, pp.plan_name AS new_plan_name,
       r.prev_expiry_date, r.new_expiry_date, r.renewal_date, r.amount, r.currency,
       r.payment_ref, r.performed_by, u.username AS performed_by_name, r.notes"""

FROM = """FROM license_renewals r
  JOIN licenses l       ON l.license_id = r.license_id
  JOIN customers c      ON c.customer_id = l.customer_id
  JOIN products p       ON p.product_id = l.product_id
  JOIN product_plans pp ON pp.plan_id = r.new_plan_id
  LEFT JOIN product_plans pp_prev ON pp_prev.plan_id = r.prev_plan_id
  LEFT JOIN users u     ON u.user_id = r.performed_by"""

SORT_WHITELIST = {
    "renewalId": "r.renewal_id",
    "licenseId": "r.license_id",
    "renewalDate": "r.renewal_date",
    "amount": "r.amount",
    "newExpiryDate": "r.new_expiry_date",
}

_view = require("LICENSE_VIEW")

router = APIRouter()


def _number(v: Any) -> Any:
    """Number(v ?? 0)."""
    if v is None:
        return 0
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return v
    try:
        f = float(str(v))
        return int(f) if f.is_integer() else f
    except ValueError:
        return float("nan")


@router.get("")
def list_renewals(ctx: Ctx = Depends(_view)):
    q_ = ctx.query
    pp = parse_list(q_)
    order_by = parse_sort(qs(q_, "sort"), SORT_WHITELIST, "r.renewal_date DESC")
    where: list[str] = ["1=1"]
    binds: Binds = {}
    license_id = qs_number(q_, "licenseId")
    if license_id is not None:
        where.append("r.license_id = :p_license_id")
        binds["p_license_id"] = license_id
    customer_id = qs_number(q_, "customerId")
    if customer_id is not None:
        where.append("l.customer_id = :p_customer_id")
        binds["p_customer_id"] = customer_id
    product_id = qs_number(q_, "productId")
    if product_id is not None:
        where.append("l.product_id = :p_product_id")
        binds["p_product_id"] = product_id
    q = qs(q_, "q")
    if q:
        where.append(
            """(UPPER(l.license_no) LIKE '%' || UPPER(:p_q) || '%'
            OR UPPER(c.company_name) LIKE '%' || UPPER(:p_q) || '%'
            OR UPPER(COALESCE(r.payment_ref, ' ')) LIKE '%' || UPPER(:p_q) || '%')"""
        )
        binds["p_q"] = q
    frm = qs_date(q_, "createdFrom")
    if frm is not None:
        where.append("r.renewal_date >= TO_DATE(:p_from, 'YYYY-MM-DD')")
        binds["p_from"] = frm
    to = qs_date(q_, "createdTo")
    if to is not None:
        where.append("r.renewal_date < TO_DATE(:p_to, 'YYYY-MM-DD') + 1")
        binds["p_to"] = to
    with transaction() as conn:
        paged = paged_query(
            conn,
            select=SELECT,
            from_where=f"{FROM} WHERE {' AND '.join(where)}",
            binds=binds,
            order_by=order_by,
            page=pp.page,
            page_size=pp.page_size,
        )
        # Year-to-date totals and the forward pipeline. Unfiltered on purpose —
        # these headline the page, so they must not shift with the table filters.
        summary_res = conn.execute(
            """SELECT
             (SELECT COUNT(*) FROM license_renewals
               WHERE renewal_date >= date_trunc('year', CURRENT_DATE))                 AS ytd_count,
             (SELECT COALESCE(SUM(amount), 0) FROM license_renewals
               WHERE renewal_date >= date_trunc('year', CURRENT_DATE))                 AS ytd_amount,
             (SELECT COUNT(*) FROM licenses
               WHERE status = 'ACTIVE' AND expiry_date IS NOT NULL
                 AND expiry_date BETWEEN CURRENT_DATE AND CURRENT_DATE + 30)
                                                                              AS pending"""
        )
        s = summary_res.first or {}
        data = {
            **paged,
            "summary": {
                "ytdCount": _number(s.get("YTD_COUNT")),
                "ytdAmount": _number(s.get("YTD_AMOUNT")),
                "pending": _number(s.get("PENDING")),
            },
        }
    return ok(data)


# ---- Delete (maker-checker: admin applies at once, a maker's delete waits in Approvals)
@router.delete("/{id}")
def delete_renewal(id: str, ctx: Ctx = Depends(require("LICENSE_MANAGE"))):
    """Delete a renewal record. The licence keeps its current plan and expiry."""
    from ...query import id_param, to_camel
    from ...services.deletes import governed_delete

    rid = id_param(id)
    with transaction() as conn:
        row = conn.execute(
            """SELECT r.renewal_id, r.amount, r.currency, r.payment_ref, r.renewal_date, l.license_no
                 FROM license_renewals r JOIN licenses l ON l.license_id = r.license_id
                WHERE r.renewal_id = :p_id""",
            {"p_id": rid},
        ).first
    if not row:
        raise AppError(404, "NOT_FOUND", "Renewal not found.")
    summary = f"Delete renewal #{rid} of licence {row['LICENSE_NO']}"
    return governed_delete(ctx, "RENEWAL", rid, "RENEWAL_DELETE", summary, to_camel(row))


# Express ran the router-level permission check before deciding "no such route".
_ALL = ["GET", "POST", "PUT", "PATCH", "DELETE"]


@router.api_route("", methods=_ALL, include_in_schema=False)
@router.api_route("/{rest:path}", methods=_ALL, include_in_schema=False)
def _unmatched(request: Request, ctx: Ctx = Depends(_view)):
    raise AppError(404, "NOT_FOUND", "Resource not found.")
