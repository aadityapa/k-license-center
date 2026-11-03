"""
/api/v1/public — unauthenticated licence-request endpoints.

These are the only routes in the system reachable without credentials, so
they are deliberately narrow: they can create a request, read back the shell
of one given its single-use token, and submit that form once. They never
expose customer, licence or key data for anything other than the request the
token belongs to.
"""
from __future__ import annotations

import math
import re
from datetime import date, datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Request

from .. import schema as z
from ..db import OUT, Row, transaction
from ..deps import Ctx, json_body, public_ctx
from ..errors import AppError
from ..query import fmt_date_only
from ..ratelimit import route_limit
from ..respond import dumps, iso, ok
from ..services.audit import log_audit
from ..services.license_requests import (
    active_trials_for_email,
    issue_license_for_request,
    new_request_token,
    setting,
    setting_bool,
)
from ..services.mailer import invite_email, request_received_email, send_mail

router = APIRouter()

# Mirrors services/vbs_key.py (VbsEdition, VbsMode, VBS_FEATURE_NAMES); kept as
# literals so the schemas below can be built at import time.
VBS_FEATURE_NAMES = ["Can", "Lin", "FlexRay", "Ethernet", "Rs232", "Debugger", "Xcp"]
VBS_EDITION_VALUES = [0, 1, 2, 3]
VBS_MODE_VALUES = [0, 1, 2]


# ---------------------------------------------------------------- schemas
_JS_NUM_RE = re.compile(r"[+-]?(?:\d+\.?\d*(?:[eE][+-]?\d+)?|\.\d+(?:[eE][+-]?\d+)?|Infinity)")


def _js_number(v: Any) -> float | int:
    """JavaScript Number(v)."""
    if v is None:
        return 0
    if isinstance(v, bool):
        return 1 if v else 0
    if isinstance(v, (int, float)):
        return v
    if isinstance(v, list):
        return _js_number(_js_array_string(v))
    if isinstance(v, str):
        s = v.strip(" \t\n\r\v\f   ﻿")
        if s == "":
            return 0
        if re.fullmatch(r"0[xX][0-9a-fA-F]+", s):
            return int(s, 16)
        if re.fullmatch(r"0[bB][01]+", s):
            return int(s[2:], 2)
        if re.fullmatch(r"0[oO][0-7]+", s):
            return int(s[2:], 8)
        if _JS_NUM_RE.fullmatch(s):
            if s.endswith("Infinity"):
                return -math.inf if s.startswith("-") else math.inf
            f = float(s)
            return int(f) if f.is_integer() and abs(f) < 2**53 else f
        return math.nan
    return math.nan


def _js_array_string(v: list) -> str:
    """String([..]) in JavaScript (Array.prototype.join(','))."""
    parts = []
    for x in v:
        if x is None:
            parts.append("")
        elif isinstance(x, bool):
            parts.append("true" if x else "false")
        elif isinstance(x, float) and x.is_integer():
            parts.append(str(int(x)))
        elif isinstance(x, (int, float, str)):
            parts.append(str(x))
        elif isinstance(x, list):
            parts.append(_js_array_string(x))
        else:
            parts.append("[object Object]")
    return ",".join(parts)


class _CoerceNumber(z.Number):
    """z.coerce.number(): Number(input) before the number checks (undefined stays absent)."""

    def run(self, v: Any, path: list, issues: list) -> Any:
        if v is not z.MISSING:
            v = _js_number(v)
        return super().run(v, path, issues)


def _coerce_number() -> _CoerceNumber:
    return _CoerceNumber()


start_schema = z.object({
    "email": z.string().email().max(255),
    "productCode": z.string().min(1).max(30),
})

# The product posts the contents of its .lic file plus who is asking.
lic_request_schema = z.object({
    "licFile": z.string().min(2).max(20000),
    "email": z.string().email().max(255),
    "companyName": z.string().max(200).optional(),
    "contactPerson": z.string().max(150).optional(),
    "contactPhone": z.string().max(30).optional(),
    "hostName": z.string().max(150).optional(),
    "appVersion": z.string().max(30).optional(),
})


def _clipped(mx: int) -> z.Schema:
    """A nullable string clipped to a column width instead of rejected for exceeding it."""
    return z.string().nullish().transform(lambda v: v if v is None else (v[:mx] if len(v) > mx else v))


# What the Vehicle SIM app sends when the customer clicks "Request licence".
# nullish throughout: the app serialises a value it could not read as JSON
# null, which is a legitimate "not available", not a malformed request.
vbs_request_schema = z.object({
    "machineId": z.string().regex(r"^[0-9A-Fa-f]{8,64}\Z", "Machine ID should be hexadecimal."),
    "email": z.string().email().max(255),
    "companyName": z.string().min(2).max(200),
    "contactPerson": z.string().max(150).nullish(),
    "contactPhone": z.string().max(30).nullish(),
    "hostName": z.string().max(150).nullish(),
    "appVersion": z.string().max(30).nullish(),
    "productCode": z.string().max(30).nullish(),
    # Trimmed to the column width rather than rejected: these are descriptive.
    "macAddress": _clipped(64),
    "cpuId": _clipped(64),
    "biosSerial": _clipped(64),
    "motherboardId": _clipped(64),
    "osName": _clipped(100),
    "osVersion": _clipped(60),
    # What the customer asked for — a suggestion to the reviewer, not a grant.
    "edition": z.enum(VBS_EDITION_VALUES).nullish(),
    "mode": z.enum(VBS_MODE_VALUES).nullish(),
    "features": z.array(z.enum(VBS_FEATURE_NAMES)).max(7).nullish(),
})

submit_schema = z.object({
    "companyName": z.string().min(2).max(200),
    "domainName": z.string().max(255).optional(),
    "contactPerson": z.string().min(2).max(150),
    "contactPhone": z.string().min(5).max(30),
    "planCode": z.string().min(1).max(30),
    "osName": z.string().max(100).optional(),
    "osVersion": z.string().max(60).optional(),
    "hostName": z.string().max(150).optional(),
    "appVersion": z.string().max(30).optional(),
    "intendedInstalls": _coerce_number().int().min(1).max(9999).optional(),
    "intendedUsers": _coerce_number().int().min(1).max(99999).optional(),
    "intendedBranches": _coerce_number().int().min(1).max(9999).optional(),
    "notes": z.string().max(1000).optional(),
})


# ---------------------------------------------------------------- helpers
def _num(raw: str) -> float | int:
    """Number(setting value)."""
    return _js_number(raw)


def _s(v: Any) -> str:
    """String(v) for a non-null row value."""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def _date_only(v: Any) -> str | None:
    return fmt_date_only(v) if isinstance(v, (date, datetime)) else None


def load_by_token(token: str) -> Row:
    """Looks up a request by token and rejects expired or already-used links."""
    with transaction() as conn:
        r = conn.execute(
            """SELECT lr.*, p.product_name, p.product_code
         FROM license_requests lr
         LEFT JOIN products p ON p.product_id = lr.product_id
        WHERE lr.request_token = :p_token""",
            {"p_token": token},
        )
        row = r.first
        # Same error for "no such token" and "wrong token" so the endpoint cannot
        # be used to probe which tokens exist.
        if not row:
            raise AppError(404, "NOT_FOUND", "This link is not valid.")
        if row["STATUS"] != "INVITED":
            raise AppError(409, "CONFLICT", "This link has already been used.")
        exp = row.get("TOKEN_EXPIRES_AT")
        if isinstance(exp, datetime) and exp < datetime.now(timezone.utc):
            raise AppError(410, "GONE", "This link has expired. Please request a new one.")
        return row


# Tight limits: this is the internet-facing surface.
_RL_MESSAGE = "Too many requests. Try again later."
start_limit = route_limit(60 * 60 * 1000, 5, _RL_MESSAGE)
form_limit = route_limit(15 * 60 * 1000, 30, _RL_MESSAGE)


# ---------------------------------------------------------------- routes
@router.get("/catalogue", dependencies=[Depends(form_limit)])
def catalogue():
    """Products a requester may pick from, with their public-facing plans."""
    with transaction() as conn:
        if not setting_bool(conn, "PUBLIC_REQUESTS_ENABLED", True):
            raise AppError(403, "FORBIDDEN", "Public licence requests are currently closed.")
        r = conn.execute(
            """SELECT p.product_id, p.product_code, p.product_name,
                  pp.plan_id, pp.plan_code, pp.plan_name, pp.duration_days, pp.is_lifetime
             FROM products p
             JOIN product_plans pp ON pp.product_id = p.product_id AND pp.status = 'ACTIVE'
            WHERE p.status = 'ACTIVE'
            ORDER BY p.product_name, pp.plan_id"""
        )
        by_product: dict[int, dict[str, Any]] = {}
        for row in r.rows:
            pid = int(row["PRODUCT_ID"])
            if pid not in by_product:
                by_product[pid] = {
                    "productId": pid,
                    "productCode": _s(row["PRODUCT_CODE"]),
                    "productName": _s(row["PRODUCT_NAME"]),
                    "plans": [],
                }
            by_product[pid]["plans"].append({
                "planCode": _s(row["PLAN_CODE"]),
                "planName": _s(row["PLAN_NAME"]),
                "durationDays": None if row["DURATION_DAYS"] is None else row["DURATION_DAYS"],
                "isLifetime": row["IS_LIFETIME"] == "Y",
            })
        data = {"products": list(by_product.values())}
    return ok(data)


@router.post("/license-requests", dependencies=[Depends(start_limit)])
def start_request(ctx: Ctx = Depends(public_ctx), body: Any = Depends(json_body)):
    """Step 1 — someone asks for a licence; we email them a personal form link."""
    b = start_schema.parse(body)
    with transaction() as conn:
        if not setting_bool(conn, "PUBLIC_REQUESTS_ENABLED", True):
            raise AppError(403, "FORBIDDEN", "Public licence requests are currently closed.")
        prod = conn.execute(
            "SELECT product_id, product_name FROM products WHERE product_code = :p_code AND status = 'ACTIVE'",
            {"p_code": b["productCode"].upper()},
        )
        product = prod.first
        if not product:
            raise AppError(400, "VALIDATION_ERROR", "Unknown product.")

        ttl = _num(setting(conn, "REQUEST_TOKEN_TTL_HOURS", "72"))
        token = new_request_token()
        r = conn.execute(
            """INSERT INTO license_requests
             (request_token, token_expires_at, email, status, source, product_id, ip_address)
           VALUES
             (:p_token, now() + make_interval(hours => :p_ttl), :p_email, 'INVITED', 'PUBLIC',
              :p_product_id, :p_ip)
           RETURNING request_id AS o_id""",
            {
                "p_token": token,
                "p_ttl": ttl,
                "p_email": b["email"],
                "p_product_id": int(product["PRODUCT_ID"]),
                "p_ip": ctx.ip,
                "o_id": OUT,
            },
        )
        request_id = int(r.out_binds["o_id"])

        base = setting(conn, "PORTAL_BASE_URL", "http://localhost:5173")
        send_mail(conn, invite_email({
            "to": b["email"],
            "productName": _s(product["PRODUCT_NAME"]),
            "link": f"{re.sub(r'/$', '', base)}/request/{token}",
            "expiresHours": ttl,
        }))

        log_audit(
            conn,
            user_id=None,
            actor="PUBLIC",
            action="LICENSE_REQUEST_STARTED",
            entity_type="LICENSE_REQUEST",
            entity_id=request_id,
            request_id=ctx.request_id,
            ip=ctx.ip,
            after={"email": b["email"], "productCode": b["productCode"]},
        )

    # Deliberately identical response whether or not the address was already
    # used, so this cannot be used to discover who has an account.
    return ok({
        "submitted": True,
        "message": "If that address is valid, a link to complete your request is on its way.",
        "requestId": request_id,
    }, 202)


@router.get("/license-requests/{token}", dependencies=[Depends(form_limit)])
def get_request_form(token: str):
    """Step 2 — the form behind the emailed link."""
    row = load_by_token(token)
    with transaction() as conn:
        plans = conn.execute(
            """SELECT plan_code, plan_name, duration_days, is_lifetime, price, currency,
                  max_activations, max_users, max_branches
             FROM product_plans WHERE product_id = :p_id AND status = 'ACTIVE' ORDER BY plan_id""",
            {"p_id": row["PRODUCT_ID"]},
        )
    exp = row.get("TOKEN_EXPIRES_AT")
    return ok({
        "email": _s(row["EMAIL"]),
        "productCode": _s(row["PRODUCT_CODE"] if row.get("PRODUCT_CODE") is not None else ""),
        "productName": _s(row["PRODUCT_NAME"] if row.get("PRODUCT_NAME") is not None else ""),
        "expiresAt": iso(exp) if isinstance(exp, datetime) else None,
        "plans": [
            {
                "planCode": _s(p["PLAN_CODE"]),
                "planName": _s(p["PLAN_NAME"]),
                "durationDays": None if p["DURATION_DAYS"] is None else p["DURATION_DAYS"],
                "isLifetime": p["IS_LIFETIME"] == "Y",
                "maxActivations": p["MAX_ACTIVATIONS"] if p["MAX_ACTIVATIONS"] is not None else 1,
                "maxUsers": None if p["MAX_USERS"] is None else p["MAX_USERS"],
                "maxBranches": None if p["MAX_BRANCHES"] is None else p["MAX_BRANCHES"],
            }
            for p in plans.rows
        ],
    })


@router.post("/license-requests/{token}", dependencies=[Depends(form_limit)])
def submit_request(token: str, ctx: Ctx = Depends(public_ctx), body: Any = Depends(json_body)):
    """Step 3 — details submitted. Trials issue immediately; paid plans queue."""
    b = submit_schema.parse(body)
    existing = load_by_token(token)

    with transaction() as conn:
        plan_res = conn.execute(
            """SELECT plan_id, plan_code, plan_name FROM product_plans
            WHERE product_id = :p_product_id AND plan_code = :p_plan_code AND status = 'ACTIVE'""",
            {"p_product_id": existing["PRODUCT_ID"], "p_plan_code": b["planCode"].upper()},
        )
        plan = plan_res.first
        if not plan:
            raise AppError(400, "VALIDATION_ERROR", "That plan is not available for this product.")

        is_trial = _s(plan["PLAN_CODE"]).upper() == "TRIAL"
        auto_issue = is_trial and setting_bool(conn, "TRIAL_AUTO_ISSUE", True)

        # Trial farming guard — only applies to the automatic path.
        if auto_issue:
            cap = _num(setting(conn, "TRIAL_MAX_PER_EMAIL", "1"))
            if active_trials_for_email(conn, _s(existing["EMAIL"])) >= cap:
                raise AppError(
                    409,
                    "CONFLICT",
                    "This address already has an active trial. Please contact us for an extension or a paid plan.",
                )

        conn.execute(
            """UPDATE license_requests
              SET status = :p_status, plan_id = :p_plan_id, company_name = :p_company,
                  domain_name = :p_domain, contact_person = :p_contact, contact_phone = :p_phone,
                  os_name = :p_os, os_version = :p_os_version, host_name = :p_host,
                  app_version = :p_app_version, intended_installs = :p_installs,
                  intended_users = :p_users, intended_branches = :p_branches,
                  notes = :p_notes, submitted_at = now()
            WHERE request_id = :p_id""",
            {
                "p_status": "AUTO_ISSUED" if auto_issue else "UNDER_REVIEW",
                "p_plan_id": int(plan["PLAN_ID"]),
                "p_company": b["companyName"],
                "p_domain": b.get("domainName"),
                "p_contact": b["contactPerson"],
                "p_phone": b["contactPhone"],
                "p_os": b.get("osName"),
                "p_os_version": b.get("osVersion"),
                "p_host": b.get("hostName"),
                "p_app_version": b.get("appVersion"),
                "p_installs": b.get("intendedInstalls"),
                "p_users": b.get("intendedUsers"),
                "p_branches": b.get("intendedBranches"),
                "p_notes": b.get("notes"),
                "p_id": int(existing["REQUEST_ID"]),
            },
        )

        if not auto_issue:
            send_mail(conn, request_received_email({
                "to": _s(existing["EMAIL"]),
                "productName": _s(existing["PRODUCT_NAME"] if existing.get("PRODUCT_NAME") is not None else ""),
                "planName": _s(plan["PLAN_NAME"]),
            }))
            log_audit(
                conn,
                user_id=None, actor="PUBLIC", action="LICENSE_REQUEST_SUBMITTED",
                entity_type="LICENSE_REQUEST", entity_id=int(existing["REQUEST_ID"]),
                request_id=ctx.request_id, ip=ctx.ip,
                after={"company": b["companyName"], "plan": plan["PLAN_CODE"], "autoIssued": False},
            )
            data: dict[str, Any] = {"issued": False, "planName": _s(plan["PLAN_NAME"])}
        else:
            # Re-read so the issuer sees the details just written.
            fresh = conn.execute(
                """SELECT lr.*, p.product_name FROM license_requests lr
             LEFT JOIN products p ON p.product_id = lr.product_id
            WHERE lr.request_id = :p_id""",
                {"p_id": int(existing["REQUEST_ID"])},
            )
            outcome = issue_license_for_request(conn, fresh.rows[0], None, ctx.request_id)
            data = {"issued": True, "planName": _s(plan["PLAN_NAME"]), "outcome": outcome}

    if not data["issued"]:
        return ok({
            "issued": False,
            "message": (
                f"Thank you. Your request for the {data['planName']} plan has been received and is "
                "with our team for review. We will email you once it is approved."
            ),
        })
    # The key itself goes only to the verified mailbox, never in this response.
    return ok({
        "issued": True,
        "message": f"Your {data['planName']} licence has been issued. The licence key has been emailed to you.",
        "licenseNo": data["outcome"]["licenseNo"],
        "expiryDate": data["outcome"]["expiryDate"],
    })


@router.post("/lic-request", dependencies=[Depends(start_limit)])
def lic_request(ctx: Ctx = Depends(public_ctx), body: Any = Depends(json_body)):
    """
    The product submits its own .lic request file.

    Nothing is issued here: a hardware-bound licence is always a human decision,
    because the file alone proves possession of a machine, not entitlement.
    """
    from ..services.karnex_lic_file import fingerprint, hardware_from, parse_karnex_lic

    b = lic_request_schema.parse(body)
    parsed = parse_karnex_lic(b["licFile"])
    hw = hardware_from(parsed)
    fp = fingerprint(hw)

    with transaction() as conn:
        # Match the product by code or display name, case-insensitively:
        # the file says "Kflash" where the catalogue says "KFLASH"/"KFlash".
        prod = conn.execute(
            """SELECT product_id, product_code, product_name FROM products
            WHERE status = 'ACTIVE'
              AND (UPPER(product_code) = UPPER(:p_name) OR UPPER(product_name) = UPPER(:p_name))""",
            {"p_name": parsed["Product"]},
        )
        product = prod.first
        if not product:
            raise AppError(
                400,
                "VALIDATION_ERROR",
                f'The .lic file is for "{parsed["Product"]}", which is not a product on this system.',
            )

        # Same machine asking again while a request is already open: return the
        # existing one instead of stacking duplicates in the reviewer's queue.
        open_ = conn.execute(
            """SELECT request_id, status FROM license_requests
            WHERE hw_fingerprint = :p_fp AND status IN ('INVITED','SUBMITTED','UNDER_REVIEW')""",
            {"p_fp": fp},
        )
        already = open_.first
        if already:
            data = {"requestId": int(already["REQUEST_ID"]), "duplicate": True}
        else:
            ttl = _num(setting(conn, "REQUEST_TOKEN_TTL_HOURS", "72"))
            r = conn.execute(
                """INSERT INTO license_requests
             (request_token, token_expires_at, email, status, source, product_id,
              company_name, contact_person, contact_phone, host_name, app_version,
              mac_address, cpu_id, bios_serial, motherboard_id, hw_fingerprint,
              lic_request_json, ip_address, submitted_at)
           VALUES
             (:p_token, now() + make_interval(hours => :p_ttl), :p_email, 'UNDER_REVIEW', 'PUBLIC',
              :p_product_id, :p_company, :p_contact, :p_phone, :p_host, :p_app_version,
              :p_mac, :p_cpu, :p_bios, :p_mb, :p_fp, :p_json, :p_ip, now())
           RETURNING request_id AS o_id""",
                {
                    "p_token": new_request_token(),
                    "p_ttl": ttl,
                    "p_email": b["email"],
                    "p_product_id": int(product["PRODUCT_ID"]),
                    "p_company": b.get("companyName"),
                    "p_contact": b.get("contactPerson"),
                    "p_phone": b.get("contactPhone"),
                    "p_host": b.get("hostName"),
                    "p_app_version": b.get("appVersion"),
                    "p_mac": hw.get("macAddress") or None,
                    "p_cpu": hw.get("cpuId") or None,
                    "p_bios": hw.get("bios") or None,
                    "p_mb": hw.get("motherBoardId") or None,
                    "p_fp": fp,
                    "p_json": dumps(parsed),
                    "p_ip": ctx.ip,
                    "o_id": OUT,
                },
            )
            request_id = int(r.out_binds["o_id"])

            # Raises the bell in the portal; the reviewer sees it without refreshing.
            conn.execute(
                """INSERT INTO notification_events (event_type, entity_type, entity_id, payload)
           VALUES ('LICENSE_REQUEST_RECEIVED', 'LICENSE_REQUEST', :p_id, :p_payload)""",
                {
                    "p_id": request_id,
                    "p_payload": dumps({
                        "product": _s(product["PRODUCT_NAME"]),
                        "email": b["email"],
                        "hostName": b.get("hostName"),
                        "fingerprint": fp,
                    }),
                },
            )

            send_mail(conn, request_received_email({
                "to": b["email"],
                "productName": _s(product["PRODUCT_NAME"]),
                "planName": "the plan you requested",
            }))

            log_audit(
                conn,
                user_id=None,
                actor="PRODUCT",
                action="LIC_REQUEST_RECEIVED",
                entity_type="LICENSE_REQUEST",
                entity_id=request_id,
                request_id=ctx.request_id,
                ip=ctx.ip,
                after={"product": product["PRODUCT_CODE"], "fingerprint": fp, "email": b["email"]},
            )
            data = {"requestId": request_id, "duplicate": False}

    return ok({
        "received": True,
        "requestId": data["requestId"],
        "fingerprint": fp,
        "message": (
            "A request for this machine is already awaiting review."
            if data["duplicate"]
            else "Your licence request has been received and is awaiting approval."
        ),
    }, 202)


@router.get("/lic-status/{fingerprint}", dependencies=[Depends(form_limit)])
def lic_status(fingerprint: str):
    """
    The product collects its activated licence. Until a reviewer approves, this
    answers approved:false; once approved it returns the completed, signed file.
    """
    fp = fingerprint
    with transaction() as conn:
        r = conn.execute(
            """SELECT lr.request_id, lr.status, lr.license_id, a.lic_file, l.license_no, l.expiry_date
             FROM license_requests lr
             LEFT JOIN licenses l ON l.license_id = lr.license_id
             LEFT JOIN license_activations a
                    ON a.license_id = lr.license_id
                   AND a.installation_id = lr.hw_fingerprint
                   AND a.status = 'ACTIVE'
            WHERE lr.hw_fingerprint = :p_fp
            ORDER BY lr.request_id DESC
            FETCH FIRST 1 ROWS ONLY""",
            {"p_fp": fp},
        )
        data = r.first

    if not data:
        raise AppError(404, "NOT_FOUND", "No licence request found for this machine.")

    status = _s(data["STATUS"])
    if status == "REJECTED":
        return ok({"approved": False, "status": status, "message": "This licence request was declined."})
    if not data.get("LIC_FILE"):
        return ok({"approved": False, "status": status, "message": "Your licence request is awaiting approval."})
    return ok({
        "approved": True,
        "status": status,
        "licenseNo": _s(data["LICENSE_NO"] if data.get("LICENSE_NO") is not None else ""),
        "expiryDate": _date_only(data.get("EXPIRY_DATE")),
        "licFile": _s(data["LIC_FILE"]),
    })


@router.post("/vbs-request", dependencies=[Depends(start_limit)])
def vbs_request(ctx: Ctx = Depends(public_ctx), body: Any = Depends(json_body)):
    """
    Vehicle SIM asks for a licence from inside the app. Nothing is issued here;
    the reviewer decides the plan, edition and protocols.
    """
    b = vbs_request_schema.parse(body)
    machine_id = b["machineId"].strip().upper()

    with transaction() as conn:
        pc = b.get("productCode")
        prod = conn.execute(
            """SELECT product_id, product_code, product_name, key_format FROM products
            WHERE status = 'ACTIVE' AND key_format = 'VBS_KEY'
              AND UPPER(product_code) = UPPER(:p_code)""",
            {"p_code": pc if pc is not None else "VEHICLESIM"},
        )
        product = prod.first
        if not product:
            raise AppError(400, "VALIDATION_ERROR",
                           "Vehicle SIM is not an active product on this system." if pc is None
                           else f"{pc} is not an active product with signed keys on this system.")

        # Same machine asking again while a request is open: hand back the
        # existing one rather than stacking duplicates in the reviewer's queue.
        open_ = conn.execute(
            """SELECT request_id, status FROM license_requests
            WHERE hw_fingerprint = :p_fp AND product_id = :p_product
              AND status IN ('INVITED','SUBMITTED','UNDER_REVIEW')""",
            # Per product: the same computer may run several Karnex apps (VehSim, KStack…).
            {"p_fp": machine_id, "p_product": product["PRODUCT_ID"]},
        )
        already = open_.first
        if already:
            data = {"requestId": int(already["REQUEST_ID"]), "duplicate": True}
        else:
            request_json: dict[str, Any] = {
                "kind": "VBS_KEY",
                "machineId": machine_id,
                "hostName": b.get("hostName"),
            }
            if b.get("edition") is not None:
                request_json["edition"] = b["edition"]
            if b.get("mode") is not None:
                request_json["mode"] = b["mode"]
            if b.get("features") is not None:  # [] is truthy in JavaScript
                request_json["features"] = b["features"]

            ttl = _num(setting(conn, "REQUEST_TOKEN_TTL_HOURS", "72"))
            r = conn.execute(
                """INSERT INTO license_requests
             (request_token, token_expires_at, email, status, source, product_id,
              company_name, contact_person, contact_phone, host_name, app_version,
              os_name, os_version,
              mac_address, cpu_id, bios_serial, motherboard_id, hw_fingerprint,
              lic_request_json, ip_address, submitted_at)
           VALUES
             (:p_token, now() + make_interval(hours => :p_ttl), :p_email, 'UNDER_REVIEW', 'PUBLIC',
              :p_product_id, :p_company, :p_contact, :p_phone, :p_host, :p_app_version,
              :p_os_name, :p_os_version,
              :p_mac, :p_cpu, :p_bios, :p_mb, :p_fp, :p_json, :p_ip, now())
           RETURNING request_id AS o_id""",
                {
                    "p_token": new_request_token(),
                    "p_ttl": ttl,
                    "p_email": b["email"],
                    "p_product_id": int(product["PRODUCT_ID"]),
                    "p_company": b.get("companyName"),
                    "p_contact": b.get("contactPerson"),
                    "p_phone": b.get("contactPhone"),
                    "p_host": b.get("hostName"),
                    "p_app_version": b.get("appVersion"),
                    "p_os_name": b.get("osName"),
                    "p_os_version": b.get("osVersion"),
                    "p_mac": b.get("macAddress"),
                    "p_cpu": b.get("cpuId"),
                    "p_bios": b.get("biosSerial"),
                    "p_mb": b.get("motherboardId"),
                    # The Machine ID is the installation identity, so it goes where the
                    # .lic flow puts its hardware fingerprint and the same joins apply.
                    "p_fp": machine_id,
                    "p_json": dumps(request_json),
                    "p_ip": ctx.ip,
                    "o_id": OUT,
                },
            )
            request_id = int(r.out_binds["o_id"])

            conn.execute(
                """INSERT INTO notification_events (event_type, entity_type, entity_id, payload)
           VALUES ('LICENSE_REQUEST_RECEIVED', 'LICENSE_REQUEST', :p_id, :p_payload)""",
                {
                    "p_id": request_id,
                    "p_payload": dumps({
                        "product": _s(product["PRODUCT_NAME"]),
                        "email": b["email"],
                        "hostName": b.get("hostName"),
                        "fingerprint": machine_id,
                    }),
                },
            )

            send_mail(conn, request_received_email({
                "to": b["email"],
                "productName": _s(product["PRODUCT_NAME"]),
                "planName": "the plan you requested",
            }))

            log_audit(
                conn,
                user_id=None,
                actor="PRODUCT",
                action="VBS_REQUEST_RECEIVED",
                entity_type="LICENSE_REQUEST",
                entity_id=request_id,
                request_id=ctx.request_id,
                ip=ctx.ip,
                after={"product": product["PRODUCT_CODE"], "machineId": machine_id, "email": b["email"]},
            )
            data = {"requestId": request_id, "duplicate": False}

    return ok({
        "received": True,
        "requestId": data["requestId"],
        "machineId": machine_id,
        "message": (
            "A request for this machine is already awaiting review."
            if data["duplicate"]
            else "Your licence request has been received and is awaiting approval."
        ),
    }, 202)


@router.get("/vbs-status/{machineId}", dependencies=[Depends(form_limit)])
def vbs_status(machineId: str, request: Request):  # noqa: N803 - path parameter name as in the TS route
    """An app (Vehicle SIM, KStack…) collects its key once the request is approved, identified by
    Machine ID and product (?productCode=, default VEHICLESIM — what older Vehicle SIM builds expect)."""
    machine_id = machineId.strip().upper()
    pc = (request.query_params.get("productCode") or "VEHICLESIM").strip().upper()[:30]
    with transaction() as conn:
        r = conn.execute(
            """SELECT lr.request_id, lr.status, lr.license_id, lr.review_comment,
                  l.license_no, l.expiry_date, k.license_key
             FROM license_requests lr
             LEFT JOIN licenses l ON l.license_id = lr.license_id
             LEFT JOIN license_keys k ON k.license_id = lr.license_id AND k.status = 'ACTIVE'
            WHERE lr.hw_fingerprint = :p_fp
              AND lr.product_id = (SELECT product_id FROM products WHERE product_code = :p_pc)
            ORDER BY lr.request_id DESC
            FETCH FIRST 1 ROWS ONLY""",
            {"p_fp": machine_id, "p_pc": pc},
        )
        data = r.first

    if not data:
        raise AppError(404, "NOT_FOUND", "No licence request found for this machine.")

    status = _s(data["STATUS"])
    if status == "REJECTED":
        return ok({
            "approved": False,
            "status": status,
            "message": (
                f"This licence request was declined: {_s(data['REVIEW_COMMENT'])}"
                if data.get("REVIEW_COMMENT")
                else "This licence request was declined."
            ),
        })
    if not data.get("LICENSE_KEY"):
        return ok({"approved": False, "status": status, "message": "Your licence request is awaiting approval."})
    return ok({
        "approved": True,
        "status": status,
        "licenseNo": _s(data["LICENSE_NO"] if data.get("LICENSE_NO") is not None else ""),
        "expiryDate": _date_only(data.get("EXPIRY_DATE")),
        "licenseKey": _s(data["LICENSE_KEY"]),
    })


@router.get("/signing-keys", dependencies=[Depends(form_limit)])
def signing_keys():
    """
    The PUBLIC halves of the signing keys (safe to publish). Release tooling uses it
    to check that an app build embeds the key this server signs with
    (scripts.set_app_public_key --from-server), so a mismatch is caught before shipping.
    """
    from ..services.licence_file import public_key_base64 as licence_public_key_base64
    from ..services.vbs_key import vbs_public_key_base64

    return ok({"vbsPublicKeySpki": vbs_public_key_base64(), "licencePublicKey": licence_public_key_base64()})
