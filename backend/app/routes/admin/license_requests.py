"""
/api/v1/admin/license-requests — admin side of the self-service licence-request flow.

GOVERNANCE NOTE — deliberately NOT routed through submit_or_apply.
Approving or rejecting a licence request IS the human review step: the whole
point of UNDER_REVIEW is that a person reads the submitted details and
decides. Invite and resend are equally low-risk — they only email a form link
to an address the recipient must already control. The permission guards still
apply in full (REQUEST_LICENSE_VIEW to read, REQUEST_LICENSE_MANAGE to act),
and every action is audited. Who holds REQUEST_LICENSE_MANAGE (CHECKER and
ADMIN, never MAKER) is what makes this four-eyes.
"""
from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Depends

from ... import schema as z
from ...db import OUT, Binds, Conn, Row, transaction
from ...deps import Ctx, json_body, require
from ...errors import AppError
from ...query import id_param, paged_query, parse_list, parse_sort, qs, qs_date, qs_enum, qs_number, to_camel
from ...respond import ok
from ...services.audit import log_audit
from ...services.license_amount import amount_field
from ...services.license_requests import issue_license_for_request, new_request_token, setting
from ...services.mailer import invite_email, request_rejected_email, send_mail

router = APIRouter()

# Mirrors services/vbs_key.py (VbsMode, VbsEdition, VBS_FEATURE_NAMES).
VBS_FEATURE_NAMES = ["Can", "Lin", "FlexRay", "Ethernet", "Rs232", "Debugger", "Xcp"]
VBS_MODE_VALUES = [0, 1, 2]
VBS_EDITION_VALUES = [0, 1, 2, 3]

STATUSES = ["INVITED", "SUBMITTED", "UNDER_REVIEW", "AUTO_ISSUED", "APPROVED", "REJECTED", "EXPIRED"]

SELECT = """SELECT lr.request_id, lr.email, lr.status, lr.source,
       lr.product_id, lr.plan_id, lr.company_name, lr.domain_name,
       lr.contact_person, lr.contact_phone, lr.customer_id, lr.license_id,
       lr.invited_by, lr.reviewed_by, lr.reviewed_at, lr.review_comment,
       lr.created_at, lr.submitted_at, lr.issued_at, lr.token_expires_at,
       lr.host_name, lr.os_name, lr.os_version, lr.app_version,
       lr.mac_address, lr.cpu_id, lr.hw_fingerprint,
       p.product_code, p.product_name, pp.plan_code, pp.plan_name,
       c.company_name AS customer_name, l.license_no"""

FROM = """FROM license_requests lr
  LEFT JOIN products p       ON p.product_id = lr.product_id
  LEFT JOIN product_plans pp ON pp.plan_id = lr.plan_id
  LEFT JOIN customers c      ON c.customer_id = lr.customer_id
  LEFT JOIN licenses l       ON l.license_id = lr.license_id"""

SORT_WHITELIST = {
    "requestId": "lr.request_id",
    "email": "lr.email",
    "status": "lr.status",
    "source": "lr.source",
    "companyName": "lr.company_name",
    "createdAt": "lr.created_at",
    "submittedAt": "lr.submitted_at",
}

invite_schema = z.object({
    "email": z.string().email().max(255),
    "productCode": z.string().min(1).max(30),
    "planCode": z.string().min(1).max(30).optional(),
})

reject_schema = z.object({
    "comment": z.string().min(3).max(1000),
})

approve_schema = z.object({
    "comment": z.string().max(1000).optional(),
    # The plan to grant — always chosen by the reviewer.
    "planCode": z.string(required_error="Choose the plan to grant.").min(1).max(30),
    # What the customer pays for this licence. Compulsory; 0 for a free licence.
    "amount": amount_field,
    # Vehicle SIM only: the reviewer's grant; each field overrides the app's suggestion.
    "vbs": z.object({
        "mode": z.enum(VBS_MODE_VALUES).optional(),
        "edition": z.enum(VBS_EDITION_VALUES).optional(),
        "features": z.array(z.enum(VBS_FEATURE_NAMES)).optional(),
        "keyVersion": z.enum(["V2", "V3"]).optional(),
    }).optional(),
})


def _s(v: Any) -> str:
    """String(v)."""
    if v is None:
        return "null"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def _num(raw: str) -> Any:
    """Number(setting value) — the settings here are plain integers."""
    try:
        return int(raw.strip())
    except ValueError:
        try:
            f = float(raw)
            return int(f) if f.is_integer() else f
        except ValueError:
            return float("nan")


def load_request(conn: Conn, id: int) -> Row:
    """Full detail row: every submitted field plus the display names and the licence."""
    r = conn.execute(
        """SELECT lr.*, p.product_code, p.product_name, p.key_format, pp.plan_code, pp.plan_name,
            c.customer_code, c.company_name AS customer_name,
            l.license_no, l.status AS license_status, l.expiry_date,
            (SELECT k.status FROM license_keys k
              WHERE k.license_id = lr.license_id AND k.status = 'ACTIVE') AS key_status,
            iu.username AS invited_by_name, ru.username AS reviewed_by_name
       FROM license_requests lr
       LEFT JOIN products p       ON p.product_id = lr.product_id
       LEFT JOIN product_plans pp ON pp.plan_id = lr.plan_id
       LEFT JOIN customers c      ON c.customer_id = lr.customer_id
       LEFT JOIN licenses l       ON l.license_id = lr.license_id
       LEFT JOIN users iu         ON iu.user_id = lr.invited_by
       LEFT JOIN users ru         ON ru.user_id = lr.reviewed_by
      WHERE lr.request_id = :p_id""",
        {"p_id": id},
    )
    row = r.first
    if not row:
        raise AppError(404, "NOT_FOUND", "Licence request not found.")
    return row


def _caller_name(conn: Conn, user_id: int, fallback: str) -> str:
    """The reviewer's display name, used in the invite email's "who invited you"."""
    r = conn.execute(
        "SELECT user_id, username, full_name FROM users WHERE user_id = :p_user_id",
        {"p_user_id": user_id},
    )
    row = r.first
    if not row:
        return fallback
    full = "" if row["FULL_NAME"] is None else _s(row["FULL_NAME"]).strip()
    return full if full != "" else _s(row["USERNAME"] if row["USERNAME"] is not None else fallback)


def _queue_invite(conn: Conn, *, email: str, product_name: str, token: str, ttl_hours: Any, invited_by: str) -> None:
    """Queues the invite email for a request row."""
    base = setting(conn, "PORTAL_BASE_URL", "http://localhost:5173")
    send_mail(conn, invite_email({
        "to": email,
        "productName": product_name,
        "link": f"{re.sub(r'/$', '', base)}/request/{token}",
        "expiresHours": ttl_hours,
        "invitedBy": invited_by,
    }))


@router.get("")
def list_requests(ctx: Ctx = Depends(require("REQUEST_LICENSE_VIEW"))):
    q = ctx.query
    pp = parse_list(q)
    order_by = parse_sort(qs(q, "sort"), SORT_WHITELIST, "lr.request_id DESC")
    where = ["1=1"]
    binds: Binds = {}

    status = qs_enum(q, "status", STATUSES)
    if status:
        where.append("lr.status = :p_status")
        binds["p_status"] = status
    source = qs_enum(q, "source", ["PUBLIC", "INVITE"])
    if source:
        where.append("lr.source = :p_source")
        binds["p_source"] = source
    product_id = qs_number(q, "productId")
    if product_id is not None:
        where.append("lr.product_id = :p_product_id")
        binds["p_product_id"] = product_id
    date_filters = [
        ("lr.created_at >= TO_DATE(:p_created_from, 'YYYY-MM-DD')", "p_created_from", qs_date(q, "createdFrom")),
        ("lr.created_at < TO_DATE(:p_created_to, 'YYYY-MM-DD') + 1", "p_created_to", qs_date(q, "createdTo")),
    ]
    for clause, bind_name, value in date_filters:
        if value is not None:
            where.append(clause)
            binds[bind_name] = value
    text = qs(q, "q")
    if text:
        where.append(
            """(UPPER(lr.email) LIKE '%' || UPPER(:p_q) || '%'
            OR UPPER(COALESCE(lr.company_name, ' ')) LIKE '%' || UPPER(:p_q) || '%')"""
        )
        binds["p_q"] = text

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
def get_request(id: str, ctx: Ctx = Depends(require("REQUEST_LICENSE_VIEW"))):
    rid = id_param(id)
    from ...services.trial_guard import find_prior_trial
    from ...services.vbs_issue import parse_vbs_request_json

    with transaction() as conn:
        row = load_request(conn, rid)
        # Has this computer already had a trial of this product? The reviewer is
        # warned before choosing a plan; approving a trial for it is refused.
        asked = parse_vbs_request_json(row.get("LIC_REQUEST_JSON"))
        prior = (
            None
            if row.get("PRODUCT_ID") is None
            else find_prior_trial(
                conn, int(row["PRODUCT_ID"]),
                [row.get("HW_FINGERPRINT"), asked.get("machineId") if asked else None],
            )
        )
    item = to_camel(row)
    item["priorTrial"] = prior
    # The token itself is never echoed to the UI: support resends the link
    # instead, so a screenshot of this screen cannot be used to impersonate.
    item.pop("requestToken", None)
    return ok(item)


@router.post("/invite")
def invite(ctx: Ctx = Depends(require("REQUEST_LICENSE_MANAGE")), body: Any = Depends(json_body)):
    """Staff-initiated invite: creates the row and emails the form link."""
    b = invite_schema.parse(body)
    user = ctx.user
    assert user is not None
    with transaction() as conn:
        prod = conn.execute(
            "SELECT product_id, product_name FROM products WHERE product_code = :p_code AND status = 'ACTIVE'",
            {"p_code": b["productCode"].upper()},
        )
        product = prod.first
        if not product:
            raise AppError(400, "VALIDATION_ERROR", "Unknown or inactive product.")

        plan_id: int | None = None
        if "planCode" in b:
            plan_res = conn.execute(
                """SELECT plan_id FROM product_plans
              WHERE product_id = :p_product_id AND plan_code = :p_plan_code AND status = 'ACTIVE'""",
                {"p_product_id": int(product["PRODUCT_ID"]), "p_plan_code": b["planCode"].upper()},
            )
            plan = plan_res.first
            if not plan:
                raise AppError(400, "VALIDATION_ERROR", "That plan is not available for this product.")
            plan_id = int(plan["PLAN_ID"])

        ttl_hours = _num(setting(conn, "REQUEST_TOKEN_TTL_HOURS", "72"))
        token = new_request_token()
        inserted = conn.execute(
            """INSERT INTO license_requests
             (request_token, token_expires_at, email, status, source, product_id, plan_id, invited_by)
           VALUES
             (:p_token, now() + make_interval(hours => :p_ttl), :p_email, 'INVITED', 'INVITE',
              :p_product_id, :p_plan_id, :p_invited_by)
           RETURNING request_id AS o_id""",
            {
                "p_token": token,
                "p_ttl": ttl_hours,
                "p_email": b["email"],
                "p_product_id": int(product["PRODUCT_ID"]),
                "p_plan_id": plan_id,
                "p_invited_by": user.user_id,
                "o_id": OUT,
            },
        )
        request_id = int(inserted.out_binds["o_id"])

        _queue_invite(
            conn,
            email=b["email"],
            product_name=_s(product["PRODUCT_NAME"]),
            token=token,
            ttl_hours=ttl_hours,
            invited_by=_caller_name(conn, user.user_id, user.username),
        )

        log_audit(
            conn,
            user_id=user.user_id,
            action="LICENSE_REQUEST_INVITED",
            entity_type="LICENSE_REQUEST",
            entity_id=request_id,
            request_id=ctx.request_id,
            ip=ctx.ip,
            after={"email": b["email"], "productCode": b["productCode"], "planCode": b.get("planCode")},
        )

    return ok({
        "requestId": request_id,
        "email": b["email"],
        "status": "INVITED",
        "expiresHours": ttl_hours,
        "message": f"An invitation has been queued for {b['email']}.",
    }, 201)


@router.post("/{id}/approve")
def approve(id: str, ctx: Ctx = Depends(require("REQUEST_LICENSE_MANAGE")), body: Any = Depends(json_body)):
    """Human approval of a paid-plan request — issues the licence and the key."""
    rid = id_param(id)
    b = approve_schema.parse(body)
    user = ctx.user
    assert user is not None
    with transaction() as conn:
        row = load_request(conn, rid)
        if row["STATUS"] != "UNDER_REVIEW":
            raise AppError(
                409,
                "CONFLICT",
                f"Only a request under review can be approved; this one is {_s(row['STATUS'])}.",
            )
        # Resolve the plan: the reviewer's choice wins, otherwise whatever the
        # requester asked for. A request with neither cannot be issued.
        if b.get("planCode"):
            plan_res = conn.execute(
                """SELECT plan_id FROM product_plans
              WHERE product_id = :p_product_id AND UPPER(plan_code) = UPPER(:p_plan_code)
                AND status = 'ACTIVE'""",
                {"p_product_id": row["PRODUCT_ID"], "p_plan_code": b["planCode"]},
            )
            plan = plan_res.first
            if not plan:
                raise AppError(
                    400,
                    "VALIDATION_ERROR",
                    f'Plan "{b["planCode"]}" is not available for this product.',
                )
            row["PLAN_ID"] = int(plan["PLAN_ID"])
            conn.execute(
                "UPDATE license_requests SET plan_id = :p_plan_id WHERE request_id = :p_id",
                {"p_plan_id": row["PLAN_ID"], "p_id": rid},
            )
        if row.get("PLAN_ID") is None:
            raise AppError(400, "VALIDATION_ERROR", "This request has no plan. Choose one when approving.")

        outcome = issue_license_for_request(conn, row, user.user_id, ctx.request_id, b.get("vbs"), b.get("amount"))
        conn.execute(
            """UPDATE license_requests
              SET status = 'APPROVED', reviewed_by = :p_user, reviewed_at = now(),
                  review_comment = :p_comment
            WHERE request_id = :p_id""",
            {"p_user": user.user_id, "p_comment": b.get("comment"), "p_id": rid},
        )
        log_audit(
            conn,
            user_id=user.user_id,
            action="LICENSE_REQUEST_APPROVED",
            entity_type="LICENSE_REQUEST",
            entity_id=rid,
            request_id=ctx.request_id,
            ip=ctx.ip,
            after={"licenseId": outcome["licenseId"], "licenseNo": outcome["licenseNo"]},
        )

    # The key itself is emailed to the verified mailbox; the reviewer sees
    # the licence identity so they can confirm what was issued.
    return ok({
        "requestId": rid,
        "status": "APPROVED",
        "licenseId": outcome["licenseId"],
        "licenseNo": outcome["licenseNo"],
        "customerId": outcome["customerId"],
        "expiryDate": outcome["expiryDate"],
        "message": f"Licence {outcome['licenseNo']} issued; the key has been emailed to the requester.",
    })


@router.post("/{id}/reject")
def reject(id: str, ctx: Ctx = Depends(require("REQUEST_LICENSE_MANAGE")), body: Any = Depends(json_body)):
    rid = id_param(id)
    b = reject_schema.parse(body)
    user = ctx.user
    assert user is not None
    with transaction() as conn:
        row = load_request(conn, rid)
        if row["STATUS"] != "UNDER_REVIEW":
            raise AppError(
                409,
                "CONFLICT",
                f"Only a request under review can be rejected; this one is {_s(row['STATUS'])}.",
            )
        conn.execute(
            """UPDATE license_requests
              SET status = 'REJECTED', reviewed_by = :p_user, reviewed_at = now(),
                  review_comment = :p_comment
            WHERE request_id = :p_id""",
            {"p_user": user.user_id, "p_comment": b["comment"], "p_id": rid},
        )
        send_mail(conn, request_rejected_email({
            "to": _s(row["EMAIL"]),
            "productName": _s(row["PRODUCT_NAME"] if row.get("PRODUCT_NAME") is not None else "your product"),
            "reason": b["comment"],
        }))
        log_audit(
            conn,
            user_id=user.user_id,
            action="LICENSE_REQUEST_REJECTED",
            entity_type="LICENSE_REQUEST",
            entity_id=rid,
            request_id=ctx.request_id,
            ip=ctx.ip,
            before={"status": _s(row["STATUS"])},
            after={"status": "REJECTED", "comment": b["comment"]},
        )

    return ok({
        "requestId": rid,
        "status": "REJECTED",
        "message": "The request was rejected and the requester has been notified.",
    })


@router.post("/{id}/resend")
def resend(id: str, ctx: Ctx = Depends(require("REQUEST_LICENSE_MANAGE"))):
    """Re-sends the form link with a NEW token, invalidating the previous one."""
    rid = id_param(id)
    user = ctx.user
    assert user is not None
    with transaction() as conn:
        row = load_request(conn, rid)
        if row["STATUS"] != "INVITED":
            raise AppError(
                409,
                "CONFLICT",
                f"Only an invited request can have its link re-sent; this one is {_s(row['STATUS'])}.",
            )
        ttl_hours = _num(setting(conn, "REQUEST_TOKEN_TTL_HOURS", "72"))
        token = new_request_token()
        conn.execute(
            """UPDATE license_requests
              SET request_token = :p_token,
                  token_expires_at = now() + make_interval(hours => :p_ttl)
            WHERE request_id = :p_id""",
            {"p_token": token, "p_ttl": ttl_hours, "p_id": rid},
        )
        _queue_invite(
            conn,
            email=_s(row["EMAIL"]),
            product_name=_s(row["PRODUCT_NAME"] if row.get("PRODUCT_NAME") is not None else "your product"),
            token=token,
            ttl_hours=ttl_hours,
            invited_by=_caller_name(conn, user.user_id, user.username),
        )
        log_audit(
            conn,
            user_id=user.user_id,
            action="LICENSE_REQUEST_RESENT",
            entity_type="LICENSE_REQUEST",
            entity_id=rid,
            request_id=ctx.request_id,
            ip=ctx.ip,
            after={"email": row["EMAIL"], "expiresHours": ttl_hours},
        )
        email = _s(row["EMAIL"])

    return ok({
        "requestId": rid,
        "status": "INVITED",
        "expiresHours": ttl_hours,
        "message": f"A new link has been queued for {email}. The previous link no longer works.",
    })


# ---- Delete (maker-checker: admin applies at once, a maker's delete waits in Approvals)
@router.delete("/{id}")
def delete_request(id: str, ctx: Ctx = Depends(require("REQUEST_LICENSE_MANAGE"))):
    """Delete a request record. A licence it already produced is kept (delete that separately)."""
    from ...services.deletes import governed_delete

    rid = id_param(id)
    with transaction() as conn:
        row = load_request(conn, rid)  # 404s
    who = row.get("COMPANY_NAME") or row.get("EMAIL") or ""
    summary = f"Delete licence request #{rid} ({who})"
    before = {k: v for k, v in to_camel(row).items() if k not in ("requestToken", "licRequestJson")}
    return governed_delete(ctx, "LICENSE_REQUEST", rid, "LICENSE_REQUEST_DELETE", summary, before)
