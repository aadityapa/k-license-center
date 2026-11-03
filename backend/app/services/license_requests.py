"""
Licence request lifecycle.

INVITED -> SUBMITTED -> AUTO_ISSUED | UNDER_REVIEW -> APPROVED | REJECTED

The token in the emailed link is what proves the requester controls the
mailbox, so no key is ever issued to an unverified address — that is the
guardrail that makes automatic trial issuing acceptable.

IssueOutcome (dict): licenseId, licenseNo, licenseKey, customerId, expiryDate, licFile.
VbsApprovalChoices (dict, all optional): mode, edition, features, keyVersion.
"""
from __future__ import annotations

import base64
import re
import secrets
from datetime import date, datetime
from typing import Any

from ..db import OUT, Conn, Row
from ..errors import AppError
from ..query import fmt_date_only
from .audit import log_audit
from .license_amount import set_license_amount
from .mailer import license_issued_email, send_mail


def _fingerprint_of(file: dict[str, Any]) -> str:
    """Fingerprint straight from a parsed .lic, for readability at the call site."""
    from .karnex_lic_file import fingerprint, hardware_from

    return fingerprint(hardware_from(file))


def new_request_token() -> str:
    """24 random bytes as base64url without padding (32 characters)."""
    return base64.urlsafe_b64encode(secrets.token_bytes(24)).decode("ascii").rstrip("=")


def setting(conn: Conn, key: str, fallback: str) -> str:
    """Reads a settings value with a fallback, so a missing row never 500s."""
    r = conn.execute("SELECT setting_value FROM settings WHERE setting_key = :p_key", {"p_key": key})
    row = r.first
    v = row.get("SETTING_VALUE") if row else None
    return fallback if v is None else _js_string(v)


def setting_bool(conn: Conn, key: str, fallback: bool) -> bool:
    raw = setting(conn, key, "true" if fallback else "false").strip().lower()
    return raw in ("true", "1", "yes")


def _js_string(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def _customer_code_from(company: str, suffix: int) -> str:
    """Derives a stable customer code from the company name, e.g. "Acme Pvt Ltd" -> CUST-ACME."""
    base = re.sub(r"[^A-Z0-9]+", "", company.upper())[:8] or "CUST"
    return f"CUST-{base}" if suffix == 0 else f"CUST-{base}{suffix}"


def _find_or_create_customer(conn: Conn, req: Row) -> int:
    """
    Finds an existing customer by the request's email, or creates one from the
    submitted company details. Matching on email avoids creating a duplicate
    customer every time the same person requests another trial.
    """
    existing = conn.execute(
        "SELECT customer_id FROM customers WHERE UPPER(email) = UPPER(:p_email)",
        {"p_email": req.get("EMAIL")},
    )
    found = existing.first
    if found:
        return int(found["CUSTOMER_ID"])

    company_raw = req.get("COMPANY_NAME")
    company = _js_string(company_raw if company_raw is not None else req.get("EMAIL"))
    # Codes are unique; try a few suffixes before giving up rather than failing
    # the whole request on a name collision.
    for i in range(20):
        code = _customer_code_from(company, i)
        clash = conn.execute(
            "SELECT customer_id FROM customers WHERE customer_code = :p_code",
            {"p_code": code},
        )
        if clash.first:
            continue
        r = conn.execute(
            """INSERT INTO customers (customer_code, company_name, contact_person, email, mobile, status, created_by, updated_by)
       VALUES (:p_code, :p_company, :p_contact, :p_email, :p_phone, 'ACTIVE', NULL, NULL)
       RETURNING customer_id AS o_id""",
            {
                "p_code": code,
                "p_company": company,
                "p_contact": req.get("CONTACT_PERSON"),
                "p_email": req.get("EMAIL"),
                "p_phone": req.get("CONTACT_PHONE"),
                "o_id": OUT,
            },
        )
        return int(r.out_binds["o_id"])
    raise AppError(409, "CONFLICT", "Could not allocate a unique customer code.")


def _date_only(v: Any) -> str | None:
    if isinstance(v, (date, datetime)):
        return fmt_date_only(v)
    return None


def _nn(*vals: Any) -> Any:
    """a ?? b ?? c"""
    for v in vals:
        if v is not None:
            return v
    return None


def issue_license_for_request(
    conn: Conn,
    req: Row,
    acting_user_id: int | None,
    correlation_id: str | None = None,
    vbs: dict[str, Any] | None = None,
    amount: float | None = None,
) -> dict[str, Any]:
    """
    Creates the customer (if needed), the licence, activates it to mint a key,
    and emails the key to the requester. Used by both the automatic trial path
    and the manual approval path, so the two can never diverge.
    """
    from .trial_guard import assert_trial_allowed
    from .vbs_issue import parse_vbs_request_json

    # One trial per computer: refuse before anything is created.
    asked_vbs = parse_vbs_request_json(req.get("LIC_REQUEST_JSON"))
    assert_trial_allowed(conn, {
        "productId": int(req["PRODUCT_ID"]),
        "planId": int(req["PLAN_ID"]),
        "machineIds": [req.get("HW_FINGERPRINT"), asked_vbs.get("machineId") if asked_vbs else None],
    })

    customer_id = _find_or_create_customer(conn, req)

    created = conn.execute(
        """SELECT pkg_license.create_license(
       p_customer_id => :p_customer_id, p_product_id => :p_product_id, p_plan_id => :p_plan_id,
       p_auto_renew => 'N', p_notes => :p_notes, p_user_id => :p_user_id,
       p_request_id => :p_request_id) AS o_license_id""",
        {
            "p_customer_id": customer_id,
            "p_product_id": int(req["PRODUCT_ID"]),
            "p_plan_id": int(req["PLAN_ID"]),
            "p_notes": f"Self-service request #{_js_string(req.get('REQUEST_ID'))} from {_js_string(req.get('EMAIL'))}",
            "p_user_id": acting_user_id,
            "p_request_id": correlation_id,
            "o_license_id": OUT,
        },
    )
    license_id = int(created.out_binds["o_license_id"])
    # Approval by a reviewer always carries the amount; an automatic trial is free.
    set_license_amount(conn, license_id, amount if amount is not None else 0)

    activated = conn.execute(
        """SELECT pkg_license.activate_license(
       p_license_id => :p_license_id, p_user_id => :p_user_id, p_request_id => :p_request_id) AS o_key""",
        {
            "p_license_id": license_id,
            "p_user_id": acting_user_id,
            "p_request_id": correlation_id,
            "o_key": OUT,
        },
    )
    key_val = activated.out_binds.get("o_key")
    license_key = "" if key_val is None else str(key_val)

    detail = conn.execute(
        """SELECT l.license_no, l.expiry_date, l.max_activations, p.product_name, pp.plan_name
       FROM licenses l
       JOIN products p ON p.product_id = l.product_id
       JOIN product_plans pp ON pp.plan_id = l.plan_id
      WHERE l.license_id = :p_id""",
        {"p_id": license_id},
    )
    d: Row = detail.first or {}
    expiry = _date_only(d.get("EXPIRY_DATE"))

    conn.execute(
        """UPDATE license_requests
        SET customer_id = :p_customer_id, license_id = :p_license_id, issued_at = now()
      WHERE request_id = :p_request_id""",
        {"p_customer_id": customer_id, "p_license_id": license_id, "p_request_id": int(req["REQUEST_ID"])},
    )

    # A request raised by the Vehicle SIM app itself. The typed key that
    # activate_license minted is not something that app can read, so replace it
    # with a Vehicle SIM key bound to the machine that asked, register that
    # machine as an activation, and let the app collect the key on its next poll.
    # The reviewer's choices (passed in via `vbs`) win over what the app suggested.
    vbs_req = parse_vbs_request_json(req.get("LIC_REQUEST_JSON"))
    vbs_key: str | None = None
    if vbs_req:
        from .vbs_issue import issue_vbs_key_for_license
        from .vbs_key import VbsEdition, VbsMode

        v = vbs or {}
        issued = issue_vbs_key_for_license(
            conn,
            license_id,
            {
                "mode": _nn(v.get("mode"), vbs_req.get("mode"), VbsMode.Subscription),
                "edition": _nn(v.get("edition"), vbs_req.get("edition"), VbsEdition.Pro),
                "features": _nn(v.get("features"), vbs_req.get("features"), ["Can", "Lin"]),
                "machineId": vbs_req["machineId"],
                "keyVersion": _nn(v.get("keyVersion"), "V3"),
            },
            acting_user_id,
        )
        vbs_key = issued["licenseKey"]

        conn.execute(
            """INSERT INTO license_activations
         (license_id, installation_id, machine_fingerprint, device_name, os_info,
          app_version, status, activated_at)
       VALUES
         (:p_license_id, :p_installation_id, :p_fp, :p_device, :p_os,
          :p_app_version, 'ACTIVE', now())""",
            {
                "p_license_id": license_id,
                "p_installation_id": vbs_req["machineId"],
                "p_fp": vbs_req["machineId"],
                "p_device": _nn(req.get("HOST_NAME"), vbs_req.get("hostName")),
                "p_os": req.get("OS_NAME"),
                "p_app_version": req.get("APP_VERSION"),
            },
        )
        conn.execute(
            "UPDATE licenses SET current_activations = current_activations + 1 WHERE license_id = :p_id",
            {"p_id": license_id},
        )

    def s(v: Any, fallback: str) -> str:
        return fallback if v is None else _js_string(v)

    send_mail(conn, license_issued_email({
        "to": _js_string(req.get("EMAIL")),
        "productName": s(d.get("PRODUCT_NAME"), "your product"),
        "planName": s(d.get("PLAN_NAME"), ""),
        "licenseKey": vbs_key if vbs_key is not None else license_key,
        "licenseNo": s(d.get("LICENSE_NO"), ""),
        "expiryDate": expiry,
        "maxActivations": _nn(d.get("MAX_ACTIVATIONS"), 1),
    }))

    # If the request arrived as a .lic file, complete and sign that same file and
    # push it to the waiting machine, so approving in the portal activates the
    # product without the customer touching anything.
    lic_file: str | None = None
    if req.get("LIC_REQUEST_JSON") and not vbs_req:
        from .karnex_lic_file import issue_karnex_lic, parse_karnex_lic
        from .live_channel import publish as push_live

        parsed = parse_karnex_lic(_js_string(req["LIC_REQUEST_JSON"]))
        customer_name = conn.execute(
            "SELECT company_name FROM customers WHERE customer_id = :p_id",
            {"p_id": customer_id},
        )
        cn_row = customer_name.first or {}
        lic_file = issue_karnex_lic(parsed, {
            "customer": s(_nn(cn_row.get("COMPANY_NAME"), req.get("COMPANY_NAME")), ""),
            "serialKey": license_key,
            "licenceNo": s(d.get("LICENSE_NO"), ""),
            "plan": s(d.get("PLAN_NAME"), ""),
            "expiry": expiry,
            "maxActivations": _nn(d.get("MAX_ACTIVATIONS"), 1),
        })

        # Record it against an activation so the machine is a known installation
        # and the file can be re-downloaded without re-signing.
        hw_fp = req.get("HW_FINGERPRINT")
        installation_id = _js_string(hw_fp if hw_fp is not None else _fingerprint_of(parsed))
        conn.execute(
            """INSERT INTO license_activations
         (license_id, installation_id, machine_fingerprint, device_name, os_info,
          app_version, status, activated_at, lic_file_issued_at, lic_file)
       VALUES
         (:p_license_id, :p_installation_id, :p_fp, :p_device, :p_os,
          :p_app_version, 'ACTIVE', now(), now(), :p_lic)""",
            {
                "p_license_id": license_id,
                "p_installation_id": installation_id,
                "p_fp": installation_id,
                "p_device": _nn(req.get("HOST_NAME"), parsed.get("MotherBoardId")),
                "p_os": req.get("OS_NAME"),
                "p_app_version": req.get("APP_VERSION"),
                "p_lic": lic_file,
            },
        )
        conn.execute(
            "UPDATE licenses SET current_activations = current_activations + 1 WHERE license_id = :p_id",
            {"p_id": license_id},
        )

        # Sub-second delivery to a product sitting on the live channel.
        push_live(license_id, {"type": "license.updated", "status": "ACTIVE", "expiry": expiry})

    log_audit(
        conn,
        user_id=acting_user_id,
        actor="SELF_SERVICE" if acting_user_id is None else None,
        action="LICENSE_ISSUED_FROM_REQUEST",
        entity_type="LICENSE_REQUEST",
        entity_id=int(req["REQUEST_ID"]),
        request_id=correlation_id,
        after={
            "licenseId": license_id,
            "customerId": customer_id,
            "email": req.get("EMAIL"),
            "licFileIssued": lic_file is not None,
            "vbsKeyIssued": vbs_key is not None,
        },
    )

    return {
        "licenseId": license_id,
        "licenseNo": s(d.get("LICENSE_NO"), ""),
        # For a Vehicle SIM request the key the customer actually uses is the
        # Vehicle SIM one; the typed key was superseded the moment it was minted.
        "licenseKey": vbs_key if vbs_key is not None else license_key,
        "customerId": customer_id,
        "expiryDate": expiry,
        "licFile": lic_file,
    }


def active_trials_for_email(conn: Conn, email: str) -> int:
    """
    Guardrail for automatic issuing: how many active licences this email already
    has on trial plans. Keeps one person from farming unlimited trials.
    """
    r = conn.execute(
        """SELECT COUNT(*) AS n
       FROM licenses l
       JOIN customers c ON c.customer_id = l.customer_id
       JOIN product_plans pp ON pp.plan_id = l.plan_id
      WHERE UPPER(c.email) = UPPER(:p_email)
        AND l.status = 'ACTIVE'
        AND pp.plan_code = 'TRIAL'""",
        {"p_email": email},
    )
    row = r.first or {}
    return int(row.get("N") or 0)
