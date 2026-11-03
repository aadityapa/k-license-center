"""Signed authorization payloads returned to product clients."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from ..query import fmt_date_only
from ..respond import iso
from ..security import hmac_sha256_hex


def denied_payload(reason: str) -> dict[str, Any]:
    return {"authorized": False, "status": "DENIED", "reason": reason}


def build_authorization(
    *,
    authorized: Any,
    reason: Any,
    status: Any,
    expiry_date: Any,
    max_activations: Any,
    current_activations: Any,
    license_key: str,
    installation_id: str,
    grace_days: float,
    signing_key: str,
    activation_id: Any = None,
) -> dict[str, Any]:
    """
    Payload with the offline-grace deadline and an HMAC-SHA256 signature over
    `licenseKey|installationId|status|expiryDate|nextValidationDeadline`
    using the API client's signing key.
    """
    if authorized != "Y":
        return denied_payload(reason if isinstance(reason, str) else "INVALID_LICENSE")

    st = status if isinstance(status, str) else "ACTIVE"
    now = datetime.now(timezone.utc)
    deadline = now + timedelta(milliseconds=grace_days * 86_400_000)
    exp = fmt_date_only(expiry_date) if isinstance(expiry_date, (date, datetime)) else None
    last_authorized_at = iso(now)
    next_deadline = iso(deadline)
    signature = hmac_sha256_hex(
        signing_key, f"{license_key}|{installation_id}|{st}|{exp or ''}|{next_deadline}"
    )
    payload: dict[str, Any] = {
        "authorized": True,
        "status": st,
        "reason": None,
        "expiryDate": exp,
        "maxActivations": _num(max_activations),
        "currentActivations": _num(current_activations),
        "offlineGraceDays": grace_days,
        "lastAuthorizedAt": last_authorized_at,
        "nextValidationDeadline": next_deadline,
        "signature": signature,
    }
    if activation_id is not None:
        payload["activationId"] = _num(activation_id)
    return payload


def _num(v: Any) -> Any:
    if v is None:
        return 0
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return int(f) if f.is_integer() else f
