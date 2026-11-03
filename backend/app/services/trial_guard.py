"""
One trial per computer, per product.

A computer that has had a trial of a product — on any licence, even one later
renewed to a paid plan, revoked or deleted from the customer — cannot be given
another trial of that product. A paid plan is always allowed.

"Computer" is the machine identity the app reports (Vehicle SIM: the MAC+CPU
Machine ID; .lic products: the hardware fingerprint). It is matched against
the machine a licence was bound to and every machine that ever activated it.
"""
from __future__ import annotations

import re
from typing import Any, Iterable

from ..db import Conn
from ..errors import AppError

_TRIAL_RE = re.compile(r"^TRIAL", re.I)


def _js_string(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def _is_trial_code(code: Any) -> bool:
    return bool(_TRIAL_RE.search(_js_string(code if code is not None else "")))


def is_trial_plan(conn: Conn, plan_id: int) -> bool:
    """True when the plan is a trial plan (its code starts with TRIAL)."""
    r = conn.execute(
        "SELECT plan_code AS trial_check_code FROM product_plans WHERE plan_id = :p_plan_id",
        {"p_plan_id": plan_id},
    )
    row = r.first
    return _is_trial_code(row.get("TRIAL_CHECK_CODE") if row else None)


def find_prior_trial(
    conn: Conn,
    product_id: int,
    machine_ids: Iterable[str | None],
    exclude_license_id: int | None = None,
) -> dict[str, Any] | None:
    """The earlier trial licence this computer had for the product ({licenseId, licenseNo}), or None."""
    ids: list[str] = []
    for m in machine_ids:
        if not m or m.strip() == "":
            continue
        v = m.strip().upper()
        if v not in ids:
            ids.append(v)
    if not ids:
        return None
    r = conn.execute(
        """SELECT l.license_id, l.license_no AS prior_trial_licence
       FROM licenses l
       JOIN product_plans pp ON pp.plan_id = l.plan_id
      WHERE l.product_id = :p_product_id
        AND l.license_id <> :p_exclude
        AND (UPPER(pp.plan_code) LIKE 'TRIAL%'
             OR EXISTS (SELECT 1 FROM license_renewals r
                          JOIN product_plans p2 ON p2.plan_id = r.prev_plan_id
                         WHERE r.license_id = l.license_id AND UPPER(p2.plan_code) LIKE 'TRIAL%'))
        AND (UPPER(COALESCE(l.vbs_machine_id, '')) = ANY(CAST(:p_ids AS text[]))
             OR EXISTS (SELECT 1 FROM license_activations a
                         WHERE a.license_id = l.license_id
                           AND UPPER(a.installation_id) = ANY(CAST(:p_ids AS text[]))))
      ORDER BY l.license_id
      LIMIT 1""",
        {
            "p_product_id": product_id,
            "p_exclude": exclude_license_id if exclude_license_id is not None else 0,
            "p_ids": "{" + ",".join(re.sub(r'[{}",\\]', "", i) for i in ids) + "}",
        },
    )
    row = r.first
    if not row:
        return None
    return {"licenseId": int(row["LICENSE_ID"]), "licenseNo": _js_string(row["PRIOR_TRIAL_LICENCE"])}


def TRIAL_USED_MESSAGE(license_no: str) -> str:  # noqa: N802 - mirrors the TS export
    return (
        f"This computer has already used its trial of this product (licence {license_no}). "
        "A trial can be given once per computer — choose a paid plan instead."
    )


def assert_trial_allowed(conn: Conn, opts: dict[str, Any]) -> None:
    """Raises 409 TRIAL_ALREADY_USED when the plan is a trial and this computer already had one.

    `opts` = {"productId", "planId", "machineIds", "excludeLicenseId"?} (camelCase, as in TS)."""
    if not is_trial_plan(conn, opts["planId"]):
        return
    exclude = opts.get("excludeLicenseId")
    prior = find_prior_trial(conn, opts["productId"], opts.get("machineIds") or [], exclude)
    if prior:
        raise AppError(409, "TRIAL_ALREADY_USED", TRIAL_USED_MESSAGE(prior["licenseNo"]))


def assert_trial_allowed_for_license(conn: Conn, license_id: int, machine_ids: Iterable[str | None]) -> None:
    """Same check for an existing licence about to be bound to a computer."""
    r = conn.execute(
        "SELECT product_id AS trial_product_id, plan_id AS trial_plan_id FROM licenses WHERE license_id = :p_license_id",
        {"p_license_id": license_id},
    )
    row = r.first
    if not row:
        return
    assert_trial_allowed(conn, {
        "productId": int(row["TRIAL_PRODUCT_ID"]),
        "planId": int(row["TRIAL_PLAN_ID"]),
        "machineIds": list(machine_ids),
        "excludeLicenseId": license_id,
    })
