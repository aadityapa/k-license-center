"""/api/v1/admin/activations — installations, fleet health, .lic download, governed deactivation (ACTIVATION_MANAGE)."""
from __future__ import annotations

import math
import re
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response

from ... import schema as z
from ...db import Binds, transaction
from ...deps import Ctx, json_body, require
from ...errors import AppError
from ...query import id_param, paged_query, parse_list, parse_sort, qs, qs_enum, qs_number, to_camel
from ...respond import ok, pending_approval
from ...services.governance import submit_or_apply

SELECT = """SELECT a.activation_id, a.license_id, l.license_no, c.company_name AS customer_name,
       p.product_code, p.product_name, a.installation_id, a.device_id, a.device_name,
       a.os_info, a.app_version, a.ip_address, a.status, a.activated_at,
       a.last_heartbeat_at, a.deactivated_at, a.deactivation_reason, a.lic_file_issued_at"""

FROM = """FROM license_activations a
  JOIN licenses l  ON l.license_id = a.license_id
  JOIN customers c ON c.customer_id = l.customer_id
  JOIN products p  ON p.product_id = l.product_id"""

SORT_WHITELIST = {
    "activationId": "a.activation_id",
    "licenseId": "a.license_id",
    "status": "a.status",
    "activatedAt": "a.activated_at",
    "lastHeartbeatAt": "a.last_heartbeat_at",
}

deactivate_schema = z.object({"reason": z.string().min(3).max(500)})

# router.use(requirePermission('ACTIVATION_MANAGE')) — runs before every route of this router.
_manage = require("ACTIVATION_MANAGE")

router = APIRouter()


def _number(v: Any) -> Any:
    """Number(v) for a row value (None -> 0, unparsable -> NaN)."""
    if v is None:
        return 0
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return v
    s = str(v).strip()
    if s == "":
        return 0
    try:
        f = float(s)
    except ValueError:
        return float("nan")
    return int(f) if f.is_integer() else f


@router.get("")
def list_activations(ctx: Ctx = Depends(_manage)):
    q_ = ctx.query
    pp = parse_list(q_)
    order_by = parse_sort(qs(q_, "sort"), SORT_WHITELIST, "a.activation_id DESC")
    where: list[str] = ["1=1"]
    binds: Binds = {}
    license_id = qs_number(q_, "licenseId")
    if license_id is not None:
        where.append("a.license_id = :p_license_id")
        binds["p_license_id"] = license_id
    customer_id = qs_number(q_, "customerId")
    if customer_id is not None:
        where.append("l.customer_id = :p_customer_id")
        binds["p_customer_id"] = customer_id
    product_id = qs_number(q_, "productId")
    if product_id is not None:
        where.append("l.product_id = :p_product_id")
        binds["p_product_id"] = product_id
    status = qs_enum(q_, "status", ["ACTIVE", "DEACTIVATED"])
    if status:
        where.append("a.status = :p_status")
        binds["p_status"] = status
    q = qs(q_, "q")
    if q:
        where.append(
            """(UPPER(a.installation_id) LIKE '%' || UPPER(:p_q) || '%'
            OR UPPER(COALESCE(a.device_id, ' ')) LIKE '%' || UPPER(:p_q) || '%'
            OR UPPER(COALESCE(a.device_name, ' ')) LIKE '%' || UPPER(:p_q) || '%')"""
        )
        binds["p_q"] = q
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
        # Fleet health across ALL activations (not just this page): an active
        # installation is "healthy" when it has checked in within twice the
        # configured heartbeat interval, which tolerates one missed beat.
        hb = conn.execute("SELECT setting_value FROM settings WHERE setting_key = 'HEARTBEAT_INTERVAL_HOURS'").first
        hb_value = hb.get("SETTING_VALUE") if hb else None
        hours = _number(hb_value if hb_value is not None else 24) * 2
        summary_res = conn.execute(
            """SELECT
             COUNT(*)                                                        AS total,
             SUM(CASE WHEN status = 'ACTIVE' THEN 1 ELSE 0 END)              AS active,
             SUM(CASE WHEN status = 'ACTIVE'
                       AND last_heartbeat_at IS NOT NULL
                       AND last_heartbeat_at >= now() - make_interval(hours => :p_hours)
                      THEN 1 ELSE 0 END)                                     AS healthy
           FROM license_activations""",
            {"p_hours": hours},
        )
        s = summary_res.first or {}
        active = _number(s.get("ACTIVE"))
        healthy = _number(s.get("HEALTHY"))
        data = {
            **paged,
            "summary": {
                "total": _number(s.get("TOTAL")),
                "active": active,
                "healthy": healthy,
                "stale": max(active - healthy, 0),
                "healthPercent": math.floor((healthy / active) * 100 + 0.5) if active > 0 else 100,
            },
        }
    return ok(data)


@router.get("/{id}/lic-file")
def lic_file(id: str, ctx: Ctx = Depends(_manage)):
    """The signed .lic file issued to this machine, as a download (re-send without re-signing)."""
    aid = id_param(id)
    with transaction() as conn:
        row = conn.execute(
            """SELECT a.lic_file, a.installation_id, l.license_no, p.product_code
             FROM license_activations a
             JOIN licenses l ON l.license_id = a.license_id
             JOIN products p ON p.product_id = l.product_id
            WHERE a.activation_id = :p_id""",
            {"p_id": aid},
        ).first
    if not row:
        raise AppError(404, "NOT_FOUND", "Activation not found.")
    if not row.get("LIC_FILE"):
        raise AppError(404, "NOT_FOUND", "No .lic file was issued for this activation.")

    name = f"{str(row['PRODUCT_CODE']).lower()}-{row['LICENSE_NO']}-{str(row['INSTALLATION_ID'])[:8]}.lic"
    # Text, because it is: the .lic is JSON. The attachment disposition makes the browser save it.
    return Response(
        content=str(row["LIC_FILE"]),
        status_code=200,
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{re.sub(r"[^A-Za-z0-9._-]", "_", name)}"'},
    )


@router.post("/{id}/deactivate")
def deactivate(id: str, ctx: Ctx = Depends(_manage), body: Any = Depends(json_body)):
    data_in = deactivate_schema.parse(body)
    aid = id_param(id)
    reason = data_in["reason"]
    with transaction() as conn:
        before = conn.execute(
            """SELECT a.activation_id, a.license_id, l.license_no, a.installation_id,
                  a.device_name, a.status
             FROM license_activations a
             JOIN licenses l ON l.license_id = a.license_id
            WHERE a.activation_id = :p_id""",
            {"p_id": aid},
        ).first
        if not before:
            raise AppError(404, "NOT_FOUND", "Activation not found.")
    device = str(before["DEVICE_NAME"]) if before.get("DEVICE_NAME") else str(before["INSTALLATION_ID"])
    summary = f"Deactivate installation {device} on licence {before['LICENSE_NO']} (reason: {reason})"
    result = submit_or_apply(ctx, {
        "entityType": "ACTIVATION",
        "entityId": aid,
        "operation": "ACTIVATION_DEACTIVATE",
        "summary": summary,
        "payload": {"reason": reason},
        "before": to_camel(before),
    })
    if not result["applied"]:
        return pending_approval(result.get("requestId"), summary)
    return ok({"activationId": aid, "status": "DEACTIVATED"})


# ---- Delete (maker-checker: admin applies at once, a maker's delete waits in Approvals)
@router.delete("/{id}")
def delete_activation(id: str, ctx: Ctx = Depends(_manage)):
    """Delete an activation record; an active one frees its seat and the app is told at once."""
    from ...services.deletes import governed_delete

    aid = id_param(id)
    with transaction() as conn:
        row = conn.execute(
            """SELECT a.activation_id, a.installation_id, a.device_name, a.status, l.license_no
                 FROM license_activations a JOIN licenses l ON l.license_id = a.license_id
                WHERE a.activation_id = :p_id""",
            {"p_id": aid},
        ).first
    if not row:
        raise AppError(404, "NOT_FOUND", "Activation not found.")
    summary = f"Delete activation {row['DEVICE_NAME'] or row['INSTALLATION_ID']} of licence {row['LICENSE_NO']}"
    return governed_delete(ctx, "ACTIVATION", aid, "ACTIVATION_DELETE", summary, to_camel(row))


# Express ran the router-level permission check before deciding "no such route".
_ALL = ["GET", "POST", "PUT", "PATCH", "DELETE"]


@router.api_route("", methods=_ALL, include_in_schema=False)
@router.api_route("/{rest:path}", methods=_ALL, include_in_schema=False)
def _unmatched(request: Request, ctx: Ctx = Depends(_manage)):
    raise AppError(404, "NOT_FOUND", "Resource not found.")
