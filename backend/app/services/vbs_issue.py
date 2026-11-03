"""
Minting a Vehicle SIM key for an existing licence.

One implementation, used by both paths that can issue a Vehicle SIM key:

  - a person in the portal, on the licence page (governance LICENSE_ISSUE_VBS)
  - approval of a request the app raised itself (issue_license_for_request)

so what the customer receives cannot depend on which door it came through.

VbsIssueInput (dict): mode, edition, features (list of names), machineId,
licensedTo (optional), keyVersion ('V2' | 'V3').
VbsIssueResult (dict): licenseKey, keyVersion, licenceNo, licensedTo, expiry.
"""
from __future__ import annotations

import hashlib
from datetime import date
from enum import IntEnum
from typing import Any

from ..errors import AppError
from ..query import fmt_date_only
from ..respond import UNDEFINED
from .vbs_key import (
    VbsMode,
    _js_str,
    _js_trim,
    _js_truthy,
    _json_parse,
    features_to_mask,
    generate_v2_key,
    generate_v3_key,
)


def parse_vbs_request_json(raw: Any) -> dict[str, Any] | None:
    """The shape the Vehicle SIM app posts when it asks for a licence itself
    (license_requests.lic_request_json); None when it is not a VBS_KEY request."""
    if not isinstance(raw, str):
        return None
    try:
        v = _json_parse(raw)
    except (ValueError, RecursionError):
        return None
    if isinstance(v, dict) and v.get("kind") == "VBS_KEY" and isinstance(v.get("machineId"), str):
        return v
    return None


def _bind(v: Any) -> Any:
    """A value as node-postgres would have sent it (enum members as plain numbers)."""
    if v is UNDEFINED:
        return None
    if isinstance(v, IntEnum):
        return int(v)
    return v


def issue_vbs_key_for_license(
    conn: Any,
    license_id: int,
    input: dict[str, Any],  # noqa: A002 - same name as the TypeScript parameter
    acting_user_id: int | None,
) -> dict[str, Any]:
    from .live_channel import publish as push_live
    from .trial_guard import assert_trial_allowed_for_license

    lic = conn.execute(
        """SELECT l.license_no, l.serial_no, l.status, l.expiry_date, l.max_activations,
            c.company_name, p.product_code, p.key_format
       FROM licenses l
       JOIN customers c ON c.customer_id = l.customer_id
       JOIN products p  ON p.product_id = l.product_id
      WHERE l.license_id = :p_license_id""",
        {"p_license_id": license_id},
    )
    row = lic.rows[0] if lic.rows else None
    if not row:
        raise AppError(404, "NOT_FOUND", "License not found.")
    if _js_str(row.get("KEY_FORMAT")) != "VBS_KEY":
        raise AppError(400, "VALIDATION_ERROR", f"{_js_str(row.get('PRODUCT_CODE'))} does not use Vehicle SIM keys.")

    mode = input.get("mode", UNDEFINED)
    # Node-locked keys are perpetual by design; everything else expires with
    # the licence. fmt_date_only, not an ISO timestamp: a DATE is a calendar day.
    is_node_locked = isinstance(mode, (int, float)) and not isinstance(mode, bool) and mode == VbsMode.NodeLocked
    exp = row.get("EXPIRY_DATE")
    expiry = None if is_node_locked else (fmt_date_only(exp) if isinstance(exp, date) else None)

    # A trial licence cannot go to a computer that already had a trial of this product.
    assert_trial_allowed_for_license(conn, license_id, [input.get("machineId")])

    lt = input.get("licensedTo")
    trimmed = _js_trim(lt) if isinstance(lt, str) else None
    company = row.get("COMPANY_NAME")
    licensed_to = trimmed or _js_str("" if company is None else company)
    licence_no_raw = row.get("LICENSE_NO")
    licence_no = _js_str("" if licence_no_raw is None else licence_no_raw)
    machine_id = _js_trim(input["machineId"])

    grant = {
        "mode": mode,
        "edition": input.get("edition", UNDEFINED),
        "licensedTo": licensed_to,
        "expiry": expiry,
        "featureMask": features_to_mask(input["features"]),
        "machineId": machine_id,
    }

    serial_no = _js_str(row.get("SERIAL_NO")) if _js_truthy(row.get("SERIAL_NO")) else None
    key_version = input.get("keyVersion")
    key = generate_v2_key(grant) if key_version == "V2" else generate_v3_key(grant, licence_no, serial_no)

    # Record the grant on the licence so the portal can show what was sold.
    conn.execute(
        """UPDATE licenses
        SET vbs_mode = :p_mode, vbs_edition = :p_edition,
            vbs_features = :p_features, vbs_machine_id = :p_machine_id,
            updated_at = now()
      WHERE license_id = :p_license_id""",
        {
            "p_mode": _bind(grant["mode"]),
            "p_edition": _bind(grant["edition"]),
            "p_features": grant["featureMask"],
            "p_machine_id": machine_id or None,
            "p_license_id": license_id,
        },
    )

    # One live key per licence: supersede any previous one. Must precede the
    # insert because of the uq_one_active_key index.
    conn.execute(
        """UPDATE license_keys
        SET status = 'REVOKED', revoked_at = now()
      WHERE license_id = :p_license_id AND status = 'ACTIVE'""",
        {"p_license_id": license_id},
    )

    conn.execute(
        """INSERT INTO license_keys (license_id, license_key, key_hash, key_version,
                               status, generated_at, generated_by)
     VALUES (:p_license_id, :p_key, :p_key_hash, :p_version,
             'ACTIVE', now(), :p_user_id)""",
        {
            "p_license_id": license_id,
            "p_key": key,
            # Same hash pkg_license_key.hash_key stores.
            "p_key_hash": hashlib.sha256(key.encode("utf-8")).hexdigest(),
            "p_version": _bind(key_version),
            "p_user_id": acting_user_id,
        },
    )

    # Connected installations pick up the new entitlement without a restart.
    status = row.get("STATUS")
    push_live(license_id, {"type": "license.updated", "status": _js_str("" if status is None else status)})

    return {
        "licenseKey": key,
        "keyVersion": key_version,
        "licenceNo": licence_no,
        "licensedTo": licensed_to,
        "expiry": expiry,
    }
