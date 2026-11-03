"""
Maker-checker governance.

Every mutating admin endpoint routes through `submit_or_apply`. What happens
depends on the caller's permissions:

  APPROVAL_BYPASS (admin) -> the change is applied immediately.
  REQUEST_SUBMIT  (maker) -> a PENDING change_requests row is written and
                             nothing else changes until a checker approves.
  neither                 -> 403.

The apply step is a single named operation (`apply_change`) shared by both
paths, so an approved request executes exactly the same code an admin would
have run. There is no second implementation to drift out of sync.

A ChangeIntent is a plain dict with the TypeScript keys:
    {"entityType", "entityId"?, "operation", "summary", "payload", "before"?}
("before" absent — or UNDEFINED — means no snapshot; None is stored as JSON null).
`submit_or_apply` returns {"applied": bool, "requestId"?: int, "data"?: Any}.
"""
from __future__ import annotations

import math
from datetime import date, datetime
from typing import Any

from ..db import OUT, Binds, Conn, transaction
from ..errors import AppError
from ..query import fmt_date_only
from ..respond import UNDEFINED, dumps
from ..security import hash_password, random_client_secret, random_hex
from .audit import log_audit
from .license_amount import set_license_amount
from .live_channel import publish as push_live
from .live_channel import publish_to_installation as push_to_installation

EntityType = str  # 'CUSTOMER' | 'PRODUCT' | 'PLAN' | 'LICENSE' | 'ACTIVATION' | 'API_CLIENT' | 'USER' | 'ROLE' | 'SETTING' | 'LICENSE_KEY'


# ---------------------------------------------------------------------------
# JavaScript value semantics used by the payload helpers
# ---------------------------------------------------------------------------
def _js_string(v: Any) -> str:
    """String(v)."""
    if v is None:
        return "null"
    if v is UNDEFINED:
        return "undefined"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float):
        if math.isnan(v):
            return "NaN"
        if math.isinf(v):
            return "Infinity" if v > 0 else "-Infinity"
        if v.is_integer() and abs(v) < 1e21:
            return str(int(v))
        return repr(v)
    if isinstance(v, list):
        return ",".join("" if x is None else _js_string(x) for x in v)
    if isinstance(v, dict):
        return "[object Object]"
    return str(v)


def _js_number(v: Any) -> int | float:
    """Number(v)."""
    if v is None:
        return 0
    if isinstance(v, bool):
        return 1 if v else 0
    if isinstance(v, (int, float)):
        return v
    if isinstance(v, str):
        s = v.strip()
        if s == "":
            return 0
        if s in ("Infinity", "+Infinity"):
            return float("inf")
        if s == "-Infinity":
            return float("-inf")
        low = s.lower()
        if "_" in s or "inf" in low or "nan" in low:
            return float("nan")
        try:
            if low.startswith("0x"):
                return int(s, 16)
            f = float(s)
        except ValueError:
            return float("nan")
        return int(f) if f.is_integer() and abs(f) < 2**53 else f
    if isinstance(v, list):
        if not v:
            return 0
        if len(v) == 1:
            return _js_number(_js_string(v[0]) if v[0] is not None else "")
        return float("nan")
    return float("nan")


def _truthy(v: Any) -> bool:
    """JavaScript truthiness ([] and {} are truthy)."""
    if v is None or v is UNDEFINED or v is False:
        return False
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return not (v == 0 or (isinstance(v, float) and math.isnan(v)))
    if isinstance(v, str):
        return v != ""
    return True


def _str(p: dict[str, Any], k: str) -> str | None:
    v = p.get(k)
    return None if v is None else _js_string(v)


def _num(p: dict[str, Any], k: str) -> int | float | None:
    v = p.get(k)
    return None if v is None else _js_number(v)


def _int_id(v: Any) -> int:
    n = _js_number(v)
    return int(n) if isinstance(n, float) and n.is_integer() else n  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------
def submit_or_apply(ctx: Any, intent: dict[str, Any]) -> dict[str, Any]:
    """Gate for every governed mutation. Returns immediately-applied data, or the
    id of the pending request that now needs a checker."""
    user = ctx.user
    if not user:
        raise AppError(401, "UNAUTHORIZED", "Authentication required.")

    if ctx.has("APPROVAL_BYPASS"):
        with transaction() as conn:
            data = apply_change(conn, intent, user.user_id, ctx.request_id)
        return {"applied": True, "data": data}

    if not ctx.has("REQUEST_SUBMIT"):
        raise AppError(
            403,
            "FORBIDDEN",
            "Your role cannot change this data. Ask a maker to submit the change for approval.",
        )

    payload = intent.get("payload") or {}
    before = intent.get("before", UNDEFINED)
    note = payload.get("_note") if isinstance(payload, dict) else None
    with transaction() as conn:
        r = conn.execute(
            """INSERT INTO change_requests
         (entity_type, entity_id, operation, summary, payload, before_state,
          status, requested_by, request_note, request_id_ref)
       VALUES
         (:p_entity_type, :p_entity_id, :p_operation, :p_summary, :p_payload, :p_before,
          'PENDING', :p_user, :p_note, :p_ref)
       RETURNING request_id AS o_id""",
            {
                "p_entity_type": intent["entityType"],
                "p_entity_id": intent.get("entityId"),
                "p_operation": intent["operation"],
                "p_summary": intent["summary"][:400],
                "p_payload": dumps(payload),
                "p_before": None if before is UNDEFINED else dumps(before),
                "p_user": user.user_id,
                "p_note": note[:1000] if isinstance(note, str) else None,
                "p_ref": ctx.request_id or None,
                "o_id": OUT,
            },
        )
        request_id = _int_id(r.out_binds.get("o_id"))
        log_audit(
            conn,
            user_id=user.user_id,
            action="CHANGE_REQUESTED",
            entity_type=intent["entityType"],
            entity_id=intent.get("entityId"),
            request_id=ctx.request_id,
            after={"operation": intent["operation"], "summary": intent["summary"], "changeRequestId": request_id},
        )

    return {"applied": False, "requestId": request_id}


def _unknown_operation(op: str):
    """A stored operation name with no handler — a coding error, not user error."""
    raise AppError(500, "INTERNAL_ERROR", f"No handler for change operation: {op}")


def _require_id(id: int | None, operation: str) -> int:
    """Licence operations always carry an entityId; never coerce a null to 0."""
    if id is None:
        raise AppError(500, "INTERNAL_ERROR", f"{operation} requires an entityId.")
    return id


def _update_sets(p: dict[str, Any], mapping: list[tuple[str, str]], binds: Binds) -> list[str]:
    sets: list[str] = []
    for key, col in mapping:
        if key in p:
            sets.append(f"{col} = :p_{col}")
            binds[f"p_{col}"] = p[key]
    return sets


def _before(intent: dict[str, Any]) -> Any:
    return intent.get("before", UNDEFINED)


def apply_change(conn: Conn, intent: dict[str, Any], acting_user_id: int, correlation_id: str | None = None) -> Any:
    """Performs the actual mutation. Called by an admin's direct write and by the
    approval step alike. Runs inside the caller's transaction."""
    p: dict[str, Any] = intent.get("payload") or {}
    id = intent.get("entityId")
    op = intent["operation"]
    cid = correlation_id if correlation_id is not None else None

    # Deletes of licences, products, activations, renewals, API clients,
    # licence requests and e-mails live in services/deletes.py.
    from .deletes import DELETE_OPS

    if op in DELETE_OPS:
        return DELETE_OPS[op](conn, _require_id(id, op), acting_user_id, cid, _before(intent))

    if op == "CLOCK_RELEASE":
        from .clock_reactivation import admin_release

        return admin_release(conn, product_code=str(p.get("productCode") or ""),
                             installation_id=str(p.get("installationId") or ""),
                             user_id=acting_user_id, correlation_id=cid, note=p.get("note"))

    # ---------------------------------------------------------------- customers
    if op == "CUSTOMER_CREATE":
        r = conn.execute(
            """INSERT INTO customers
           (customer_code, company_name, contact_person, email, mobile, whatsapp,
            address_line1, address_line2, city, state, country, gst_number, status,
            created_by, updated_by)
         VALUES
           (:p_code, :p_name, :p_contact, :p_email, :p_mobile, :p_whatsapp,
            :p_a1, :p_a2, :p_city, :p_state, :p_country, :p_gst, :p_status,
            :p_user, :p_user)
         RETURNING customer_id AS o_id""",
            {
                "p_code": _str(p, "customerCode"), "p_name": _str(p, "companyName"),
                "p_contact": _str(p, "contactPerson"), "p_email": _str(p, "email"),
                "p_mobile": _str(p, "mobile"), "p_whatsapp": _str(p, "whatsapp"),
                "p_a1": _str(p, "addressLine1"), "p_a2": _str(p, "addressLine2"),
                "p_city": _str(p, "city"), "p_state": _str(p, "state"),
                "p_country": _str(p, "country"), "p_gst": _str(p, "gstNumber"),
                "p_status": _str(p, "status") if _str(p, "status") is not None else "ACTIVE",
                "p_user": acting_user_id, "o_id": OUT,
            },
        )
        new_id = _int_id(r.out_binds.get("o_id"))
        log_audit(conn, user_id=acting_user_id, action="CUSTOMER_CREATED", entity_type="CUSTOMER",
                  entity_id=new_id, request_id=cid, after=p)
        return {"customerId": new_id}

    if op == "CUSTOMER_UPDATE":
        binds: Binds = {"p_id": id, "p_user": acting_user_id}
        sets = _update_sets(p, [
            ("companyName", "company_name"), ("contactPerson", "contact_person"),
            ("email", "email"), ("mobile", "mobile"), ("whatsapp", "whatsapp"),
            ("addressLine1", "address_line1"), ("addressLine2", "address_line2"),
            ("city", "city"), ("state", "state"), ("country", "country"),
            ("gstNumber", "gst_number"), ("status", "status"),
        ], binds)
        if not sets:
            return {"customerId": id}
        conn.execute(
            f"""UPDATE customers SET {', '.join(sets)}, updated_at = now(), updated_by = :p_user
          WHERE customer_id = :p_id""",
            binds,
        )
        log_audit(conn, user_id=acting_user_id, action="CUSTOMER_UPDATED", entity_type="CUSTOMER",
                  entity_id=id, request_id=cid, before=_before(intent), after=p)
        return {"customerId": id}

    # Deletes a customer who never received a licence. A customer WITH licences
    # cannot be deleted (it would orphan their record); checked again here, at
    # apply time, because a licence may have been issued since the request.
    if op == "CUSTOMER_DELETE":
        cust_id = _require_id(id, "CUSTOMER_DELETE")
        used = conn.execute("SELECT COUNT(*) AS n FROM licenses WHERE customer_id = :p_id", {"p_id": cust_id})
        n = _js_number((used.first or {}).get("N") if (used.first or {}).get("N") is not None else 0)
        if n > 0:
            raise AppError(
                409,
                "CUSTOMER_HAS_LICENSES",
                f"This customer has {_js_string(n)} licence{'' if n == 1 else 's'}, so it cannot be deleted — that would erase "
                "who those licences belong to. Set the customer to Inactive instead.",
            )
        # Detach records that only point at the customer, then remove it.
        conn.execute("UPDATE license_requests SET customer_id = NULL WHERE customer_id = :p_id", {"p_id": cust_id})
        conn.execute("DELETE FROM customer_contacts WHERE customer_id = :p_id", {"p_id": cust_id})
        dele = conn.execute("DELETE FROM customers WHERE customer_id = :p_id", {"p_id": cust_id})
        if (dele.rows_affected or 0) == 0:
            raise AppError(404, "NOT_FOUND", "Customer not found.")
        log_audit(conn, user_id=acting_user_id, action="CUSTOMER_DELETED", entity_type="CUSTOMER",
                  entity_id=cust_id, request_id=cid, before=_before(intent))
        return {"customerId": cust_id, "deleted": True}

    if op == "PLAN_DELETE":
        pid = _require_id(id, "PLAN_DELETE")
        used = conn.execute(
            """SELECT (SELECT COUNT(*) FROM licenses WHERE plan_id = :p_id)
              + (SELECT COUNT(*) FROM license_renewals WHERE new_plan_id = :p_id OR prev_plan_id = :p_id) AS plan_uses""",
            {"p_id": pid},
        )
        uses = (used.first or {}).get("PLAN_USES")
        n = _js_number(uses if uses is not None else 0)
        if n > 0:
            raise AppError(
                409,
                "PLAN_IN_USE",
                "Licences use this plan, so it cannot be deleted — that would erase what those customers bought. "
                "Archive it instead: it then cannot be chosen for new licences.",
            )
        # Requests that merely named the plan keep their history without it.
        conn.execute("UPDATE license_requests SET plan_id = NULL WHERE plan_id = :p_id", {"p_id": pid})
        dele = conn.execute("DELETE FROM product_plans WHERE plan_id = :p_id", {"p_id": pid})
        if (dele.rows_affected or 0) == 0:
            raise AppError(404, "NOT_FOUND", "Plan not found.")
        log_audit(conn, user_id=acting_user_id, action="PLAN_DELETED", entity_type="PLAN",
                  entity_id=pid, request_id=cid, before=_before(intent))
        return {"planId": pid, "deleted": True}

    if op == "LICENSE_KEY_DELETE":
        kid = _require_id(id, "LICENSE_KEY_DELETE")
        cur = conn.execute("SELECT status FROM license_keys WHERE key_id = :p_key_id FOR UPDATE", {"p_key_id": kid})
        row = cur.first
        if not row:
            raise AppError(404, "NOT_FOUND", "Key not found.")
        if _js_string(row["STATUS"]) == "ACTIVE":
            raise AppError(
                409,
                "KEY_ACTIVE",
                "This is the live key a customer is using. Revoke it or issue a new key first; only revoked keys can be deleted.",
            )
        conn.execute("DELETE FROM license_keys WHERE key_id = :p_key_id", {"p_key_id": kid})
        log_audit(conn, user_id=acting_user_id, action="KEY_DELETED", entity_type="LICENSE_KEY",
                  entity_id=kid, request_id=cid, before=_before(intent))
        return {"keyId": kid, "deleted": True}

    # ---------------------------------------------------------------- products
    if op == "PRODUCT_CREATE":
        r = conn.execute(
            """INSERT INTO products (product_code, product_name, key_prefix, description, version, status, created_by, updated_by)
         VALUES (:p_code, :p_name, :p_prefix, :p_desc, :p_version, :p_status, :p_user, :p_user)
         RETURNING product_id AS o_id""",
            {
                "p_code": _str(p, "productCode"), "p_name": _str(p, "productName"),
                "p_prefix": _str(p, "keyPrefix"), "p_desc": _str(p, "description"),
                "p_version": _str(p, "version"),
                "p_status": _str(p, "status") if _str(p, "status") is not None else "ACTIVE",
                "p_user": acting_user_id, "o_id": OUT,
            },
        )
        new_id = _int_id(r.out_binds.get("o_id"))
        log_audit(conn, user_id=acting_user_id, action="PRODUCT_CREATED", entity_type="PRODUCT",
                  entity_id=new_id, request_id=cid, after=p)
        return {"productId": new_id}

    if op == "PRODUCT_UPDATE":
        binds = {"p_id": id, "p_user": acting_user_id}
        sets = _update_sets(p, [
            ("productName", "product_name"), ("description", "description"),
            ("version", "version"), ("status", "status"),
        ], binds)
        if not sets:
            return {"productId": id}
        conn.execute(
            f"""UPDATE products SET {', '.join(sets)}, updated_at = now(), updated_by = :p_user
          WHERE product_id = :p_id""",
            binds,
        )
        log_audit(conn, user_id=acting_user_id, action="PRODUCT_UPDATED", entity_type="PRODUCT",
                  entity_id=id, request_id=cid, before=_before(intent), after=p)
        return {"productId": id}

    # ---------------------------------------------------------------- plans
    if op == "PLAN_CREATE":
        maxact = _num(p, "maxActivations")
        r = conn.execute(
            """INSERT INTO product_plans
           (product_id, plan_code, plan_name, duration_days, is_lifetime, price, currency,
            max_activations, max_users, max_branches, status, created_by, updated_by)
         VALUES
           (:p_product, :p_code, :p_name, :p_duration, :p_lifetime, :p_price, :p_currency,
            :p_maxact, :p_maxusers, :p_maxbranches, :p_status, :p_user, :p_user)
         RETURNING plan_id AS o_id""",
            {
                "p_product": _num(p, "productId"), "p_code": _str(p, "planCode"), "p_name": _str(p, "planName"),
                "p_duration": _num(p, "durationDays"), "p_lifetime": "Y" if _truthy(p.get("isLifetime")) else "N",
                "p_price": _num(p, "price"),
                "p_currency": _str(p, "currency") if _str(p, "currency") is not None else "INR",
                "p_maxact": maxact if maxact is not None else 1, "p_maxusers": _num(p, "maxUsers"),
                "p_maxbranches": _num(p, "maxBranches"),
                "p_status": _str(p, "status") if _str(p, "status") is not None else "ACTIVE",
                "p_user": acting_user_id, "o_id": OUT,
            },
        )
        new_id = _int_id(r.out_binds.get("o_id"))
        log_audit(conn, user_id=acting_user_id, action="PLAN_CREATED", entity_type="PLAN",
                  entity_id=new_id, request_id=cid, after=p)
        return {"planId": new_id}

    if op == "PLAN_UPDATE":
        binds = {"p_id": id, "p_user": acting_user_id}
        sets = _update_sets(p, [
            ("planName", "plan_name"), ("durationDays", "duration_days"),
            ("price", "price"), ("currency", "currency"), ("maxActivations", "max_activations"),
            ("maxUsers", "max_users"), ("maxBranches", "max_branches"), ("status", "status"),
        ], binds)
        if "isLifetime" in p:
            sets.append("is_lifetime = :p_is_lifetime")
            binds["p_is_lifetime"] = "Y" if _truthy(p["isLifetime"]) else "N"
        if not sets:
            return {"planId": id}
        conn.execute(
            f"""UPDATE product_plans SET {', '.join(sets)}, updated_at = now(), updated_by = :p_user
          WHERE plan_id = :p_id""",
            binds,
        )
        log_audit(conn, user_id=acting_user_id, action="PLAN_UPDATED", entity_type="PLAN",
                  entity_id=id, request_id=cid, before=_before(intent), after=p)
        return {"planId": id}

    # ---------------------------------------------------------------- licences
    # Bind names match the database function parameter names exactly.
    if op == "LICENSE_CREATE":
        r = conn.execute(
            """SELECT pkg_license.create_license(
           p_customer_id => :p_customer_id, p_product_id => :p_product_id, p_plan_id => :p_plan_id,
           p_auto_renew => :p_auto_renew, p_notes => :p_notes, p_user_id => :p_user_id,
           p_request_id => :p_request_id) AS o_license_id""",
            {
                "p_customer_id": _num(p, "customerId"), "p_product_id": _num(p, "productId"),
                "p_plan_id": _num(p, "planId"), "p_auto_renew": "Y" if _truthy(p.get("autoRenewal")) else "N",
                "p_notes": _str(p, "notes"), "p_user_id": acting_user_id,
                "p_request_id": cid, "o_license_id": OUT,
            },
        )
        license_id = _int_id(r.out_binds.get("o_license_id"))
        # Requests queued before the amount became compulsory carry none.
        if p.get("amount") is not None:
            set_license_amount(conn, license_id, _js_number(p["amount"]))
        return {"licenseId": license_id}

    if op == "LICENSE_ACTIVATE":
        r = conn.execute(
            """SELECT pkg_license.activate_license(
           p_license_id => :p_license_id, p_user_id => :p_user_id, p_request_id => :p_request_id) AS o_key""",
            {"p_license_id": id, "p_user_id": acting_user_id, "p_request_id": cid, "o_key": OUT},
        )
        key = r.out_binds.get("o_key")
        return {"licenseKey": _js_string(key if key is not None else "")}

    if op == "LICENSE_SUSPEND":
        conn.execute(
            "SELECT pkg_license.suspend_license(:p_license_id, :p_user_id, :p_reason, :p_request_id)",
            {"p_license_id": id, "p_user_id": acting_user_id, "p_reason": _str(p, "reason"), "p_request_id": cid},
        )
        # Push after the statement, so connected installations stop within a
        # second instead of waiting for their next heartbeat.
        reason = _str(p, "reason")
        push_live(_require_id(id, "LICENSE_SUSPEND"), {
            "type": "license.suspended", "status": "SUSPENDED",
            "reason": reason if reason is not None else UNDEFINED,
        })
        return {"licenseId": id}

    if op == "LICENSE_REACTIVATE":
        conn.execute(
            "SELECT pkg_license.reactivate_license(:p_license_id, :p_user_id, :p_reason, :p_request_id)",
            {"p_license_id": id, "p_user_id": acting_user_id, "p_reason": _str(p, "reason"), "p_request_id": cid},
        )
        push_live(_require_id(id, "LICENSE_REACTIVATE"), {"type": "license.reactivated", "status": "ACTIVE"})
        return {"licenseId": id}

    if op == "LICENSE_REVOKE":
        conn.execute(
            "SELECT pkg_license.revoke_license(:p_license_id, :p_user_id, :p_reason, :p_request_id)",
            {"p_license_id": id, "p_user_id": acting_user_id, "p_reason": _str(p, "reason"), "p_request_id": cid},
        )
        reason = _str(p, "reason")
        push_live(_require_id(id, "LICENSE_REVOKE"), {
            "type": "license.revoked", "status": "REVOKED",
            "reason": reason if reason is not None else UNDEFINED,
        })
        return {"licenseId": id}

    if op == "LICENSE_RENEW":
        r = conn.execute(
            """SELECT pkg_renewal.renew_license(
           p_license_id => :p_license_id, p_new_plan_id => :p_new_plan_id, p_amount => :p_amount,
           p_payment_ref => :p_payment_ref, p_notes => :p_notes, p_user_id => :p_user_id,
           p_request_id => :p_request_id) AS o_new_expiry""",
            {
                "p_license_id": id, "p_new_plan_id": _num(p, "planId"), "p_amount": _num(p, "amount"),
                "p_payment_ref": _str(p, "paymentRef"), "p_notes": _str(p, "notes"),
                "p_user_id": acting_user_id, "p_request_id": cid, "o_new_expiry": OUT,
            },
        )
        expiry = r.out_binds.get("o_new_expiry")
        push_live(_require_id(id, "LICENSE_RENEW"), {"type": "license.renewed", "status": "ACTIVE"})
        # Local date parts (a DATE is a calendar day, never shifted through UTC).
        return {"newExpiryDate": fmt_date_only(expiry) if isinstance(expiry, (date, datetime)) else None}

    if op == "LICENSE_REGENERATE_KEY":
        # pkg_license_key.generate_key only mints typed PREF-XXXX-XXXX-XXXX keys;
        # a product whose app expects another key shape must not get one.
        fmt = conn.execute(
            """SELECT p.key_format, p.product_code
           FROM licenses l JOIN products p ON p.product_id = l.product_id
          WHERE l.license_id = :p_license_id""",
            {"p_license_id": id},
        )
        fmt_row = fmt.first
        if fmt_row and _js_string(fmt_row["KEY_FORMAT"]) == "VBS_KEY":
            raise AppError(
                400,
                "VALIDATION_ERROR",
                f"{_js_string(fmt_row['PRODUCT_CODE'])} keys carry the entitlement and must be reissued "
                "from the Vehicle SIM Key panel, not regenerated.",
            )
        r = conn.execute(
            """SELECT pkg_license_key.generate_key(
           p_license_id => :p_license_id, p_user_id => :p_user_id, p_request_id => :p_request_id,
           p_revoke_existing => 'Y') AS o_key""",
            {"p_license_id": id, "p_user_id": acting_user_id, "p_request_id": cid, "o_key": OUT},
        )
        key = r.out_binds.get("o_key")
        return {"licenseKey": _js_string(key if key is not None else "")}

    # Mints a Vehicle SIM key for an existing licence and records the grant
    # (shared with the request-approval path).
    if op == "LICENSE_ISSUE_VBS":
        license_id = _require_id(id, "LICENSE_ISSUE_VBS")
        from .vbs_issue import issue_vbs_key_for_license

        vbs_input: dict[str, Any] = {
            "mode": _num(p, "mode"),
            "edition": _num(p, "edition"),
            "features": p["features"] if isinstance(p.get("features"), list) else [],
            "machineId": _str(p, "machineId") if _str(p, "machineId") is not None else "",
            # V2 only for installs not yet on a V3-capable build. V3 is unforgeable.
            "keyVersion": "V2" if p.get("keyVersion") == "V2" else "V3",
        }
        licensed_to = _str(p, "licensedTo")
        if licensed_to is not None:
            vbs_input["licensedTo"] = licensed_to
        return issue_vbs_key_for_license(conn, license_id, vbs_input, acting_user_id)

    # Signs an uploaded .lic request for a machine that cannot reach the portal.
    if op == "LICENSE_ISSUE_LIC":
        from .lic_file_issue import issue_lic_file_for_license

        lic = _str(p, "licFile")
        return issue_lic_file_for_license(
            conn, _require_id(id, "LICENSE_ISSUE_LIC"), lic if lic is not None else "", acting_user_id
        )

    # ---------------------------------------------------------------- activations
    if op == "ACTIVATION_DEACTIVATE":
        conn.execute(
            """SELECT pkg_authorization.admin_deactivate(
           p_activation_id => :p_activation_id, p_user_id => :p_user_id,
           p_reason => :p_reason, p_request_id => :p_request_id)""",
            {"p_activation_id": id, "p_user_id": acting_user_id, "p_reason": _str(p, "reason"), "p_request_id": cid},
        )
        # Push only to the machine that lost its slot.
        who = conn.execute(
            "SELECT license_id, installation_id FROM license_activations WHERE activation_id = :p_id",
            {"p_id": id},
        )
        row = who.first
        if row:
            reason = _str(p, "reason")
            push_to_installation(_int_id(row["LICENSE_ID"]), _js_string(row["INSTALLATION_ID"]), {
                "type": "activation.deactivated",
                "reason": reason if reason is not None else UNDEFINED,
            })
        return {"activationId": id}

    # ---------------------------------------------------------------- API clients
    # The secret and signing key are minted HERE, at apply time — never written
    # into the pending request. They are returned once to whoever applies.
    if op == "API_CLIENT_CREATE":
        product_ok = conn.execute(
            "SELECT product_id FROM products WHERE product_id = :p_id AND status = 'ACTIVE'",
            {"p_id": _num(p, "productId")},
        )
        if not product_ok.first:
            raise AppError(400, "VALIDATION_ERROR", "productId does not reference an active product.")
        client_key = random_hex(16)
        client_secret = random_client_secret()
        signing_key = random_hex(16)
        secret_hash = hash_password(client_secret, 12)
        r = conn.execute(
            """INSERT INTO api_clients (product_id, client_key, secret_hash, signing_key, name, status, created_by)
         VALUES (:p_product_id, :p_client_key, :p_secret_hash, :p_signing_key, :p_name, 'ACTIVE', :p_user)
         RETURNING client_id AS o_id""",
            {
                "p_product_id": _num(p, "productId"), "p_client_key": client_key,
                "p_secret_hash": secret_hash, "p_signing_key": signing_key,
                "p_name": _str(p, "name"), "p_user": acting_user_id, "o_id": OUT,
            },
        )
        new_id = _int_id(r.out_binds.get("o_id"))
        log_audit(conn, user_id=acting_user_id, action="APICLIENT_CREATED", entity_type="API_CLIENT",
                  entity_id=new_id, request_id=cid,
                  after={"productId": _num(p, "productId"), "name": _str(p, "name"), "clientKey": client_key})
        return {
            "clientId": new_id, "productId": _num(p, "productId"), "name": _str(p, "name"),
            "clientKey": client_key, "clientSecret": client_secret, "signingKey": signing_key, "status": "ACTIVE",
        }

    if op == "API_CLIENT_REVOKE":
        cur = conn.execute("SELECT status FROM api_clients WHERE client_id = :p_id FOR UPDATE", {"p_id": id})
        row = cur.first
        if not row:
            raise AppError(404, "NOT_FOUND", "API client not found.")
        if row["STATUS"] == "REVOKED":
            raise AppError(409, "CONFLICT", "API client is already revoked.")
        conn.execute(
            "UPDATE api_clients SET status = 'REVOKED', revoked_at = now() WHERE client_id = :p_id",
            {"p_id": id},
        )
        log_audit(conn, user_id=acting_user_id, action="APICLIENT_REVOKED", entity_type="API_CLIENT",
                  entity_id=id, request_id=cid, after={"reason": _str(p, "reason")})
        return {"clientId": id, "status": "REVOKED"}

    # ---------------------------------------------------------------- settings
    if op == "SETTING_UPDATE":
        settings = p.get("settings")
        if settings is None:
            settings = {}
        items = list(settings.items()) if isinstance(settings, dict) else []
        for key, value in items:
            conn.execute(
                """UPDATE settings SET setting_value = :p_value, updated_at = now(), updated_by = :p_user
            WHERE setting_key = :p_key""",
                {"p_value": _js_string(value), "p_user": acting_user_id, "p_key": key},
            )
        log_audit(conn, user_id=acting_user_id, action="SETTINGS_UPDATED", entity_type="SETTING",
                  entity_id=None, request_id=cid, before=_before(intent), after=settings)
        return {"updated": len(items)}

    return _unknown_operation(op)
