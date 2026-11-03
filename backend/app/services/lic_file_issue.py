"""
Issuing a signed .lic activation file by hand, for a machine that cannot
reach the portal.

KStack and KFlash machines normally post their own .lic request and collect
the signed file once approved. An air-gapped site cannot: the customer emails
the request file instead, a person uploads it here against the customer's
licence, and the signed file goes back the same way. The result is identical
to the online path -- same signature, same activation record.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from ..errors import AppError
from ..query import fmt_date_only
from .karnex_lic_file import fingerprint, hardware_from, issue_karnex_lic, parse_karnex_lic
from ..respond import UNDEFINED
from .vbs_key import _js_number, _js_str, _js_trim


def parse_uploaded_request(text: str) -> dict[str, Any]:
    """Parses an uploaded request, with errors a reviewer can act on."""
    try:
        parsed = parse_karnex_lic(text)
    except Exception as e:  # noqa: BLE001 - every failure becomes a reviewer-facing message
        msg = e.message if isinstance(e, AppError) else str(e)
        raise AppError(
            400, "VALIDATION_ERROR", f"That is not a readable .lic request file ({msg})."
        ) from None
    hw = hardware_from(parsed)
    if not hw["macAddress"] and not hw["cpuId"] and not hw["bios"] and not hw["motherBoardId"]:
        raise AppError(400, "VALIDATION_ERROR", "The .lic file carries no hardware identity to bind to.")
    return parsed


def issue_lic_file_for_license(
    conn: Any,
    license_id: int,
    lic_text: str,
    acting_user_id: int | None,
) -> dict[str, Any]:
    """Returns the LicFileIssueResult dict: activationId, licFile, fileName, fingerprint, reissued."""
    from .live_channel import publish as push_live
    from .trial_guard import assert_trial_allowed_for_license

    parsed = parse_uploaded_request(lic_text)
    fp = fingerprint(hardware_from(parsed))

    r = conn.execute(
        """SELECT l.license_no, l.status, l.expiry_date, l.max_activations, l.current_activations,
            c.company_name, p.product_code, p.product_name, p.key_format, pp.plan_name,
            (SELECT k.license_key FROM license_keys k
              WHERE k.license_id = l.license_id AND k.status = 'ACTIVE') AS license_key
       FROM licenses l
       JOIN customers c      ON c.customer_id = l.customer_id
       JOIN products p       ON p.product_id = l.product_id
       JOIN product_plans pp ON pp.plan_id = l.plan_id
      WHERE l.license_id = :p_license_id""",
        {"p_license_id": license_id},
    )
    row = r.rows[0] if r.rows else None
    if not row:
        raise AppError(404, "NOT_FOUND", "License not found.")

    if _js_str(row.get("KEY_FORMAT")) != "LIC_FILE":
        raise AppError(400, "VALIDATION_ERROR", f"{_js_str(row.get('PRODUCT_CODE'))} is not licensed with .lic files.")
    if _js_str(row.get("STATUS")) != "ACTIVE":
        raise AppError(
            409,
            "CONFLICT",
            f"Licence {_js_str(row.get('LICENSE_NO'))} is {_js_str(row.get('STATUS'))}; "
            "only an active licence can be issued.",
        )
    # The file names its product; it must be this licence's product, or a KFlash
    # request could be signed as a KStack licence.
    named = _js_trim(parsed["Product"]).upper()
    if named != _js_str(row.get("PRODUCT_CODE")).upper() and named != _js_str(row.get("PRODUCT_NAME")).upper():
        raise AppError(
            400,
            "VALIDATION_ERROR",
            f'The .lic file is for "{parsed["Product"]}", but licence {_js_str(row.get("LICENSE_NO"))} '
            f"is for {_js_str(row.get('PRODUCT_NAME'))}.",
        )
    if not row.get("LICENSE_KEY"):
        raise AppError(409, "CONFLICT", "This licence has no active key to issue against.")
    # A trial licence cannot go to a computer that already had a trial of this product.
    assert_trial_allowed_for_license(conn, license_id, [fp])

    # Same machine again: re-issue its file on the seat it already holds.
    existing = conn.execute(
        """SELECT activation_id FROM license_activations
      WHERE license_id = :p_license_id AND installation_id = :p_fp AND status = 'ACTIVE'""",
        {"p_license_id": license_id, "p_fp": fp},
    )
    existing_id = existing.rows[0].get("ACTIVATION_ID") if existing.rows else None

    cur = row.get("CURRENT_ACTIVATIONS")
    mx = row.get("MAX_ACTIVATIONS")
    if existing_id is None and _js_number(0 if cur is None else cur) >= _js_number(0 if mx is None else mx):
        raise AppError(
            409,
            "ACTIVATION_LIMIT_REACHED",
            f"All {_js_str(mx)} activations of {_js_str(row.get('LICENSE_NO'))} are in use. "
            "Deactivate a machine first, or renew with more seats.",
        )

    exp = row.get("EXPIRY_DATE")
    expiry = fmt_date_only(exp) if isinstance(exp, date) else None
    company = row.get("COMPANY_NAME")
    licence_no = row.get("LICENSE_NO")
    plan = row.get("PLAN_NAME")
    lic_file = issue_karnex_lic(
        parsed,
        {
            "customer": _js_str("" if company is None else company),
            "serialKey": _js_str(row.get("LICENSE_KEY")),
            "licenceNo": _js_str("" if licence_no is None else licence_no),
            "plan": _js_str("" if plan is None else plan),
            "expiry": expiry,
            "maxActivations": _js_number(1 if mx is None else mx),
        },
    )

    if existing_id is not None:
        activation_id = _js_number(existing_id)
        conn.execute(
            """UPDATE license_activations
          SET lic_file = :p_lic, lic_file_issued_at = now()
        WHERE activation_id = :p_activation_id""",
            {"p_lic": lic_file, "p_activation_id": activation_id},
        )
    else:
        conn.execute(
            """INSERT INTO license_activations
         (license_id, installation_id, machine_fingerprint, device_name, os_info,
          app_version, status, activated_at, lic_file_issued_at, lic_file)
       VALUES
         (:p_license_id, :p_installation_id, :p_fp, :p_device, :p_os,
          :p_app_version, 'ACTIVE', now(), now(), :p_lic)""",
            {
                "p_license_id": license_id,
                "p_installation_id": fp,
                "p_fp": fp,
                "p_device": parsed.get("MotherBoardId") or parsed.get("MacAddress") or None,
                "p_os": None,
                "p_app_version": None,
                "p_lic": lic_file,
            },
        )
        conn.execute(
            "UPDATE licenses SET current_activations = current_activations + 1 WHERE license_id = :p_id",
            {"p_id": license_id},
        )
        created = conn.execute(
            """SELECT activation_id FROM license_activations
        WHERE license_id = :p_license_id AND installation_id = :p_fp AND status = 'ACTIVE'""",
            {"p_license_id": license_id, "p_fp": fp},
        )
        activation_id = _js_number(created.rows[0].get("ACTIVATION_ID", UNDEFINED) if created.rows else UNDEFINED)

    push_live(license_id, {"type": "license.updated", "status": "ACTIVE", "expiry": expiry})

    _ = acting_user_id  # recorded by the governance audit around this call
    return {
        "activationId": activation_id,
        "licFile": lic_file,
        "fileName": f"{_js_str(row.get('PRODUCT_CODE')).lower()}-{_js_str(licence_no)}-{fp[:8]}.lic",
        "fingerprint": fp,
        "reissued": existing_id is not None,
    }
