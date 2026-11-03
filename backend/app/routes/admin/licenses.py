"""/api/v1/admin/licenses — licences: list, detail, create and the governed lifecycle actions."""
from __future__ import annotations

import functools
import re
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from fastapi import APIRouter, Depends

from ... import schema as z
from ...db import Binds, Conn, Row, transaction
from ...deps import Ctx, json_body, require
from ...errors import AppError
from ...respond import iso
from ...query import id_param, paged_query, parse_list, parse_sort, qs, qs_date, qs_enum, qs_number, rows_to_camel, to_camel
from ...respond import ok, pending_approval
from ...services.governance import submit_or_apply
from ...services.license_amount import amount_field

LICENSE_STATUSES = ["DRAFT", "ACTIVE", "SUSPENDED", "EXPIRED", "REVOKED", "CANCELLED"]

# p.key_format travels with every licence so the UI knows how this one is
# delivered — a typed key, a .lic file, or a Vehicle SIM key string.
SELECT = """SELECT l.license_id, l.license_no, l.serial_no, l.license_uid, l.amount, l.currency, l.customer_id, c.customer_code, c.company_name AS customer_name,
       l.product_id, p.product_code, p.product_name, p.key_format, l.plan_id, pp.plan_code, pp.plan_name,
       l.status, l.start_date, l.expiry_date, l.max_activations, l.max_users, l.max_branches,
       l.current_activations, l.auto_renewal, l.notes, l.created_at, l.updated_at"""

FROM = """FROM licenses l
  JOIN customers c      ON c.customer_id = l.customer_id
  JOIN products p       ON p.product_id = l.product_id
  JOIN product_plans pp ON pp.plan_id = l.plan_id"""

SORT_WHITELIST = {
    "licenseId": "l.license_id",
    "licenseNo": "l.license_no",
    "status": "l.status",
    "startDate": "l.start_date",
    "expiryDate": "l.expiry_date",
    "companyName": "c.company_name",
    "customerName": "c.company_name",
    "createdAt": "l.created_at",
}

create_schema = z.object({
    "customerId": z.number().int().positive(),
    "productId": z.number().int().positive(),
    "planId": z.number().int().positive(),
    "amount": amount_field,
    "autoRenewal": z.boolean().default(False),
    "notes": z.string().max(2000).optional(),
})


@functools.lru_cache(maxsize=1)
def _issue_vbs_schema() -> z.Schema:
    """Vehicle SIM key issuance (built on first use: vbs_key is imported lazily).
    Node-locked keys are perpetual and must name the machine they bind to;
    expiry always comes from the licence record."""
    from ...services.vbs_key import VBS_FEATURE_NAMES, VbsEdition, VbsMode

    return z.object({
        "mode": z.enum([int(m.value) for m in VbsMode]),
        "edition": z.enum([int(e.value) for e in VbsEdition]),
        "features": z.array(z.enum(list(VBS_FEATURE_NAMES))).default([]),
        # The 16-hex Machine ID from the customer's Licence window.
        "machineId": z.string().max(64).optional(),
        # Overrides the customer's company name shown in the app as "Licensed to".
        "licensedTo": z.string().max(200).optional(),
        # V3 is the default and is unforgeable; V2 only for pre-V3 builds.
        "keyVersion": z.enum(["V2", "V3"]).default("V3"),
    }).refine(
        lambda v: bool((v.get("machineId") or "").strip()),
        "A Machine ID is required: every Vehicle SIM key is bound to one computer.",
        ["machineId"],
    )


# An uploaded .lic request file, as text. Same ceiling as the public endpoint.
issue_lic_schema = z.object({"licFile": z.string().min(2).max(20000)})

renew_schema = z.object({
    "planId": z.number().int().positive().optional(),
    "amount": z.number().nonnegative().optional(),
    "paymentRef": z.string().max(100).optional(),
    "notes": z.string().max(1000).optional(),
})

reason_required_schema = z.object({"reason": z.string().min(3).max(1000)})
reason_optional_schema = z.object({"reason": z.string().min(3).max(1000).optional()})


def get_license(conn: Conn, id: int) -> Row:
    r = conn.execute(
        f"""{SELECT}, l.vbs_machine_id,
       (SELECT k.license_key FROM license_keys k
         WHERE k.license_id = l.license_id AND k.status = 'ACTIVE') AS license_key
     {FROM} WHERE l.license_id = :p_id""",
        {"p_id": id},
    )
    row = r.first
    if not row:
        raise AppError(404, "NOT_FOUND", "License not found.")
    return row


def _js(v: Any) -> str:
    """String(v) for row values / numbers."""
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def format_inr(n: float) -> str:
    """`₹${n.toLocaleString('en-IN', { maximumFractionDigits: 2 })}`."""
    d = Decimal(repr(n) if isinstance(n, float) else str(n)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    neg = d < 0
    s = format(abs(d), "f")
    whole, _, frac = s.partition(".")
    frac = frac.rstrip("0")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join(groups + [tail])
    out = whole + ("." + frac if frac else "")
    return "₹" + ("-" if neg else "") + out


router = APIRouter()


@router.get("")
def list_licenses(ctx: Ctx = Depends(require("LICENSE_VIEW"))):
    q_ = ctx.query
    pp = parse_list(q_)
    order_by = parse_sort(qs(q_, "sort"), SORT_WHITELIST, "l.license_id DESC")
    where: list[str] = ["1=1"]
    binds: Binds = {}

    filters = [
        ("l.customer_id = :p_customer_id", qs_number(q_, "customerId")),
        ("l.product_id = :p_product_id", qs_number(q_, "productId")),
        ("l.plan_id = :p_plan_id", qs_number(q_, "planId")),
    ]
    for clause, value in filters:
        if value is not None:
            bind_name = re.search(r":(\w+)", clause).group(1)  # type: ignore[union-attr]
            where.append(clause)
            binds[bind_name] = value
    status = qs_enum(q_, "status", LICENSE_STATUSES)
    if status:
        where.append("l.status = :p_status")
        binds["p_status"] = status
    date_filters = [
        ("l.expiry_date >= TO_DATE(:p_expiry_from, 'YYYY-MM-DD')", "p_expiry_from", qs_date(q_, "expiryFrom")),
        ("l.expiry_date <= TO_DATE(:p_expiry_to, 'YYYY-MM-DD')", "p_expiry_to", qs_date(q_, "expiryTo")),
        ("l.created_at >= TO_DATE(:p_created_from, 'YYYY-MM-DD')", "p_created_from", qs_date(q_, "createdFrom")),
        ("l.created_at < TO_DATE(:p_created_to, 'YYYY-MM-DD') + 1", "p_created_to", qs_date(q_, "createdTo")),
    ]
    for clause, bind_name, value in date_filters:
        if value is not None:
            where.append(clause)
            binds[bind_name] = value
    q = qs(q_, "q")
    if q:
        where.append(
            """(UPPER(l.license_no) LIKE '%' || UPPER(:p_q) || '%'
            OR UPPER(l.serial_no) LIKE '%' || UPPER(:p_q) || '%'
            OR LOWER(l.license_uid) = LOWER(:p_q)
            OR UPPER(c.company_name) LIKE '%' || UPPER(:p_q) || '%'
            OR EXISTS (SELECT 1 FROM license_keys k
                        WHERE k.license_id = l.license_id
                          AND UPPER(k.license_key) LIKE '%' || UPPER(:p_q) || '%'))"""
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
def get_one(id: str, ctx: Ctx = Depends(require("LICENSE_VIEW"))):
    lid = id_param(id)
    with transaction() as conn:
        license = get_license(conn, lid)
        activations = conn.execute(
            """SELECT activation_id, installation_id, device_id, device_name, os_info, app_version,
                    ip_address, status, activated_at, last_heartbeat_at, deactivated_at, deactivation_reason,
                    lic_file_issued_at
               FROM license_activations WHERE license_id = :p_id ORDER BY activated_at DESC""",
            {"p_id": lid},
        )
        renewals = conn.execute(
            """SELECT r.renewal_id, r.prev_plan_id, r.new_plan_id, pp.plan_name AS new_plan_name,
                    r.prev_expiry_date, r.new_expiry_date, r.renewal_date, r.amount, r.currency,
                    r.payment_ref, r.performed_by, r.notes
               FROM license_renewals r
               JOIN product_plans pp ON pp.plan_id = r.new_plan_id
              WHERE r.license_id = :p_id ORDER BY r.renewal_date DESC""",
            {"p_id": lid},
        )
        keys = conn.execute(
            """SELECT key_id, license_key, status, generated_at, revoked_at
               FROM license_keys WHERE license_id = :p_id ORDER BY generated_at DESC""",
            {"p_id": lid},
        )
        history = conn.execute(
            """SELECT history_id, old_status, new_status, changed_at, changed_by, reason
               FROM license_history WHERE license_id = :p_id ORDER BY changed_at DESC""",
            {"p_id": lid},
        )
        computers = _computers(conn, lid, license, activations.rows)
        data = {
            **to_camel(license),
            "computers": computers,
            "activations": rows_to_camel(activations.rows),
            "renewals": rows_to_camel(renewals.rows),
            "keys": rows_to_camel(keys.rows),
            "history": rows_to_camel(history.rows),
        }
    return ok(data)


def _computers(conn: Conn, lid: int, license: Row, activations: list[Row]) -> list[dict[str, Any]]:
    """
    The computers this licence is (or was asked to be) bound to, with the hardware the app
    reported in its licence request: Machine ID, MAC, CPU ID, BIOS serial, motherboard,
    host and OS. Machine IDs come from the issued key (vbs_machine_id), the activations and
    the requests linked to the licence; hardware from the newest request of that machine.
    """
    ids: list[str] = []

    def add(v: Any) -> None:
        t = str(v or "").strip().upper()
        if t and t not in ids:
            ids.append(t)

    add(license.get("VBS_MACHINE_ID"))
    for a in activations:
        add(a.get("INSTALLATION_ID"))
    linked = conn.execute(
        "SELECT hw_fingerprint FROM license_requests WHERE license_id = :p_id AND hw_fingerprint IS NOT NULL",
        {"p_id": lid},
    )
    for r in linked.rows:
        add(r.get("HW_FINGERPRINT"))
    if not ids:
        return []
    reqs = conn.execute(
        """SELECT request_id, hw_fingerprint, mac_address, cpu_id, bios_serial, motherboard_id,
                  host_name, os_name, os_version, app_version, email, created_at
             FROM license_requests
            WHERE UPPER(hw_fingerprint) = ANY(CAST(:p_ids AS text[]))
            ORDER BY (license_id = :p_id) DESC NULLS LAST, created_at DESC""",
        {"p_ids": "{" + ",".join(re.sub(r'[{}",\\\s]', "", i) for i in ids) + "}", "p_id": lid},
    )
    newest: dict[str, Row] = {}
    for r in reqs.rows:
        newest.setdefault(str(r.get("HW_FINGERPRINT") or "").upper(), r)
    bound = str(license.get("VBS_MACHINE_ID") or "").strip().upper()
    out = []
    for mid in ids:
        r = newest.get(mid) or {}
        out.append({
            "machineId": mid,
            "boundToKey": mid == bound,
            "macAddress": r.get("MAC_ADDRESS"),
            "cpuId": r.get("CPU_ID"),
            "biosSerial": r.get("BIOS_SERIAL"),
            "motherboardId": r.get("MOTHERBOARD_ID"),
            "hostName": r.get("HOST_NAME"),
            "osName": " ".join(x for x in (r.get("OS_NAME"), r.get("OS_VERSION")) if x) or None,
            "appVersion": r.get("APP_VERSION"),
            "requestId": r.get("REQUEST_ID"),
            "requestedAt": iso(r["CREATED_AT"]) if r.get("CREATED_AT") else None,
        })
    return out


def _load(id: int) -> Row:
    with transaction() as conn:
        return get_license(conn, id)


@router.post("")
def create(ctx: Ctx = Depends(require("LICENSE_CREATE")), body: Any = Depends(json_body)):
    b = create_schema.parse(body)
    with transaction() as conn:
        r = conn.execute(
            """SELECT c.company_name, p.product_name, p.product_code, pp.plan_name, pp.plan_code
             FROM customers c, products p, product_plans pp
            WHERE c.customer_id = :p_customer_id
              AND p.product_id   = :p_product_id
              AND pp.plan_id     = :p_plan_id""",
            {"p_customer_id": b["customerId"], "p_product_id": b["productId"], "p_plan_id": b["planId"]},
        )
        target = r.first
        if not target:
            raise AppError(404, "NOT_FOUND", "Customer, product or plan not found.")
    summary = (
        f'Create licence for "{_js(target["COMPANY_NAME"])}" '
        f"on {_js(target['PRODUCT_NAME'])} / plan {_js(target['PLAN_NAME'])} for {format_inr(b['amount'])}"
    )
    result = submit_or_apply(ctx, {
        "entityType": "LICENSE",
        "operation": "LICENSE_CREATE",
        "summary": summary,
        "payload": {**b},
    })
    if not result["applied"]:
        return pending_approval(result.get("requestId"), summary)
    new_id = int(result["data"]["licenseId"])
    row = _load(new_id)
    return ok(to_camel(row), 201)


# DRAFT -> ACTIVE + first key generation
@router.post("/{id}/activate")
def activate(id: str, ctx: Ctx = Depends(require("LICENSE_MANAGE"))):
    lid = id_param(id)
    before = _load(lid)
    summary = f'Activate licence {_js(before["LICENSE_NO"])} for "{_js(before["CUSTOMER_NAME"])}"'
    result = submit_or_apply(ctx, {
        "entityType": "LICENSE",
        "entityId": lid,
        "operation": "LICENSE_ACTIVATE",
        "summary": summary,
        "payload": {},
        "before": to_camel(before),
    })
    if not result["applied"]:
        return pending_approval(result.get("requestId"), summary)
    license_key = _js(result["data"]["licenseKey"])
    license = _load(lid)
    return ok({"licenseKey": license_key, **to_camel(license)})


@router.post("/{id}/renew")
def renew(id: str, ctx: Ctx = Depends(require("LICENSE_MANAGE")), body: Any = Depends(json_body)):
    b = renew_schema.parse(body)
    lid = id_param(id)
    with transaction() as conn:
        license = get_license(conn, lid)
        # The renewal may move the licence onto a different plan; name whichever
        # plan it will end up on.
        if "planId" not in b or b["planId"] == license["PLAN_ID"]:
            before, plan_name = license, _js(license["PLAN_NAME"])
        else:
            r = conn.execute("SELECT plan_name FROM product_plans WHERE plan_id = :p_id", {"p_id": b["planId"]})
            prow = r.first
            if not prow:
                raise AppError(404, "NOT_FOUND", "Plan not found.")
            before, plan_name = license, _js(prow["PLAN_NAME"])
    summary = f"Renew licence {_js(before['LICENSE_NO'])} on plan {plan_name}"
    result = submit_or_apply(ctx, {
        "entityType": "LICENSE",
        "entityId": lid,
        "operation": "LICENSE_RENEW",
        "summary": summary,
        "payload": {**b},
        "before": to_camel(before),
    })
    if not result["applied"]:
        return pending_approval(result.get("requestId"), summary)
    new_expiry = result["data"]["newExpiryDate"]
    license = _load(lid)
    return ok({"newExpiryDate": new_expiry, **to_camel(license)})


def _lifecycle(ctx: Ctx, id: str, body: Any, schema: z.Schema, operation: str, verb: str,
               default_reason: str | None = None):
    """suspend / reactivate / revoke differ only in the operation name, the verb
    used in the summary and whether a reason is mandatory."""
    data = schema.parse(body)
    lid = id_param(id)
    reason = data.get("reason")
    if reason is None:
        reason = default_reason
    before = _load(lid)
    summary = f'{verb} licence {_js(before["LICENSE_NO"])} for "{_js(before["CUSTOMER_NAME"])}"' + (
        f" (reason: {reason})" if reason else ""
    )
    result = submit_or_apply(ctx, {
        "entityType": "LICENSE",
        "entityId": lid,
        "operation": operation,
        "summary": summary,
        "payload": {"reason": reason},
        "before": to_camel(before),
    })
    if not result["applied"]:
        return pending_approval(result.get("requestId"), summary)
    row = _load(lid)
    return ok(to_camel(row))


@router.post("/{id}/suspend")
def suspend(id: str, ctx: Ctx = Depends(require("LICENSE_MANAGE")), body: Any = Depends(json_body)):
    return _lifecycle(ctx, id, body, reason_required_schema, "LICENSE_SUSPEND", "Suspend")


@router.post("/{id}/reactivate")
def reactivate(id: str, ctx: Ctx = Depends(require("LICENSE_MANAGE")), body: Any = Depends(json_body)):
    return _lifecycle(ctx, id, body, reason_optional_schema, "LICENSE_REACTIVATE", "Reactivate", "Reactivated")


@router.post("/{id}/revoke")
def revoke(id: str, ctx: Ctx = Depends(require("LICENSE_REVOKE")), body: Any = Depends(json_body)):
    return _lifecycle(ctx, id, body, reason_required_schema, "LICENSE_REVOKE", "Revoke")


@router.post("/{id}/regenerate-key")
def regenerate_key(id: str, ctx: Ctx = Depends(require("LICENSE_MANAGE")), body: Any = Depends(json_body)):
    data = reason_required_schema.parse(body)
    lid = id_param(id)
    reason = data["reason"]
    before = _load(lid)  # 404 when missing
    summary = f"Regenerate key for licence {_js(before['LICENSE_NO'])} (reason: {reason})"
    result = submit_or_apply(ctx, {
        "entityType": "LICENSE",
        "entityId": lid,
        "operation": "LICENSE_REGENERATE_KEY",
        "summary": summary,
        "payload": {"reason": reason},
        "before": to_camel(before),
    })
    if not result["applied"]:
        return pending_approval(result.get("requestId"), summary)
    return ok({"licenseId": lid, "licenseKey": _js(result["data"]["licenseKey"])})


@router.post("/{id}/issue-vbs-key")
def issue_vbs_key(id: str, ctx: Ctx = Depends(require("LICENSE_MANAGE")), body: Any = Depends(json_body)):
    """Issue a Vehicle SIM key. The key carries the entitlement itself (mode,
    edition, protocols, bound machine); customer, expiry and seats still come
    from the licence record, so the key cannot grant more than was sold."""
    from ...services.vbs_key import VbsEdition, VbsMode

    b = _issue_vbs_schema().parse(body)
    lid = id_param(id)
    before = _load(lid)  # 404 when missing

    try:
        mode_name = VbsMode(b["mode"]).name
    except ValueError:
        mode_name = _js(b["mode"])
    try:
        edition_name = VbsEdition(b["edition"]).name
    except ValueError:
        edition_name = _js(b["edition"])
    summary = (
        f"Issue Vehicle SIM {b['keyVersion']} key for licence {_js(before['LICENSE_NO'])} "
        f"({edition_name}, {mode_name}, features: {', '.join(b['features']) or 'none'})"
    )

    payload: dict[str, Any] = {
        "mode": b["mode"],
        "edition": b["edition"],
        "features": b["features"],
        "machineId": b.get("machineId", ""),
        "keyVersion": b["keyVersion"],
    }
    if b.get("licensedTo"):
        payload["licensedTo"] = b["licensedTo"]
    result = submit_or_apply(ctx, {
        "entityType": "LICENSE",
        "entityId": lid,
        "operation": "LICENSE_ISSUE_VBS",
        "summary": summary,
        "payload": payload,
        "before": to_camel(before),
    })
    if not result["applied"]:
        return pending_approval(result.get("requestId"), summary)
    return ok({"licenseId": lid, **(result["data"] or {})})


@router.post("/{id}/issue-lic-file")
def issue_lic_file(id: str, ctx: Ctx = Depends(require("LICENSE_MANAGE")), body: Any = Depends(json_body)):
    """Issue a signed .lic file from an uploaded request (maker-checker: it takes a seat)."""
    from ...services.karnex_lic_file import fingerprint, hardware_from
    from ...services.lic_file_issue import parse_uploaded_request

    data = issue_lic_schema.parse(body)
    lid = id_param(id)
    lic_file = data["licFile"]
    # Reject a malformed file now, before it reaches a checker's queue.
    parsed = parse_uploaded_request(lic_file)
    fp = fingerprint(hardware_from(parsed))
    before = _load(lid)
    summary = (
        f"Issue .lic activation file for licence {_js(before['LICENSE_NO'])} "
        f"(machine {fp[:12]}…, MAC {parsed.get('MacAddress') or '—'})"
    )
    result = submit_or_apply(ctx, {
        "entityType": "LICENSE",
        "entityId": lid,
        "operation": "LICENSE_ISSUE_LIC",
        "summary": summary,
        "payload": {"licFile": lic_file},
        "before": to_camel(before),
    })
    if not result["applied"]:
        return pending_approval(result.get("requestId"), summary)
    return ok({"licenseId": lid, **(result["data"] or {})})


# ---- Delete (maker-checker: admin applies at once, a maker's delete waits in Approvals)
@router.delete("/{id}")
def delete_license(id: str, ctx: Ctx = Depends(require("LICENSE_MANAGE"))):
    """Delete a licence with its keys, activations, renewals and history.
    Running installations of a live licence are stopped at once."""
    from ...query import id_param as _id, to_camel as _camel
    from ...services.deletes import governed_delete

    lid = _id(id)
    with transaction() as conn:
        row = conn.execute(
            """SELECT l.license_id, l.license_no, l.status, c.company_name, p.product_name
                 FROM licenses l JOIN customers c ON c.customer_id = l.customer_id
                 JOIN products p ON p.product_id = l.product_id WHERE l.license_id = :p_id""",
            {"p_id": lid},
        ).first
    if not row:
        raise AppError(404, "NOT_FOUND", "License not found.")
    summary = f"Delete licence {row['LICENSE_NO']} ({row['PRODUCT_NAME']}, {row['COMPANY_NAME']})"
    return governed_delete(ctx, "LICENSE", lid, "LICENSE_DELETE", summary, _camel(row))
