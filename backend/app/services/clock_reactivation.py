"""
Reactivating an installation that blocked itself after its clock was set back.

  * The app's "Reactivate" button calls POST /license/clock-reactivate with the
    computer's current time. The server compares it with its own time: within
    SKEW_TOLERANCE the installation is reactivated, otherwise the user is told
    to set the correct date/time (the server's time is returned to show them).
  * An administrator can reactivate an installation from the portal
    (operation CLOCK_RELEASE). The app sees it on its next contact
    (GET /license/time?installationId=...) and collects it with the same call,
    which then succeeds whatever the computer's clock says.
Either way the open CLOCK_TAMPER alerts of that installation are marked handled.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

from ..db import Conn
from ..errors import AppError
from ..respond import iso
from .audit import log_audit

SKEW_TOLERANCE = timedelta(minutes=10)


def _pattern(installation_id: str) -> str:
    install = re.sub(r'["%_\\]', "", installation_id)
    return f'%"installationId":"{install}"%'


def parse_time(v: Any) -> datetime | None:
    if not isinstance(v, str) or not v.strip():
        return None
    s = v.strip().replace("Z", "+00:00").replace("z", "+00:00")
    # .NET writes 7 fractional digits; Python 3.10 reads at most 6.
    s = re.sub(r"(\.\d{6})\d+", r"\1", s)
    try:
        d = datetime.fromisoformat(s)
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def describe(delta: timedelta) -> str:
    secs = int(abs(delta.total_seconds()))
    days, rem = divmod(secs, 86400)
    hours, rem = divmod(rem, 3600)
    mins = rem // 60
    parts = []
    if days:
        parts.append(f"{days} day{'s' if days != 1 else ''}")
    if hours:
        parts.append(f"{hours} hr{'s' if hours != 1 else ''}")
    if not days and mins:
        parts.append(f"{mins} min")
    return " ".join(parts) or "less than a minute"


def pending_admin_release(conn: Conn, product_id: int, installation_id: str) -> dict | None:
    return conn.execute(
        """SELECT reactivation_id FROM clock_reactivations
            WHERE product_id = :p_product AND installation_id = :p_install
              AND source = 'ADMIN' AND collected_at IS NULL
            ORDER BY requested_at DESC LIMIT 1""",
        {"p_product": product_id, "p_install": installation_id},
    ).first


def resolve_alerts(conn: Conn, installation_id: str) -> int:
    r = conn.execute(
        """UPDATE notification_events SET status = 'SENT', processed_at = now()
            WHERE event_type = 'CLOCK_TAMPER' AND status = 'PENDING' AND payload LIKE :p_install""",
        {"p_install": _pattern(installation_id)},
    )
    return r.rows_affected or 0


def app_reactivate(conn: Conn, *, product_id: int, installation_id: str, local_time: Any,
                   ip: str | None, request_id: str | None) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    server_time = iso(now)
    pending = pending_admin_release(conn, product_id, installation_id)
    if pending:
        conn.execute("UPDATE clock_reactivations SET collected_at = now() WHERE reactivation_id = :p_id",
                     {"p_id": pending["REACTIVATION_ID"]})
        resolve_alerts(conn, installation_id)
        log_audit(conn, actor="PRODUCT_CLIENT", action="CLOCK_REACTIVATED", entity_type="INSTALLATION",
                  request_id=request_id, ip=ip,
                  after={"installationId": installation_id, "source": "ADMIN", "localTime": local_time})
        return {"serverTime": server_time, "reactivated": True, "adminReleased": True,
                "message": "Licence reactivated by Karnex."}

    local = parse_time(local_time)
    if local is None:
        raise AppError(400, "VALIDATION_ERROR", "localTime: Invalid date/time")
    delta = local - now
    if abs(delta) > SKEW_TOLERANCE:
        direction = "behind" if delta < timedelta(0) else "ahead of"
        return {
            "serverTime": server_time, "reactivated": False, "adminReleased": False,
            "deltaSeconds": round(delta.total_seconds()),
            "message": f"This computer's date/time is {describe(delta)} {direction} the Karnex licence server. "
                       "Set the correct date and time, then press Reactivate again.",
        }
    conn.execute(
        """INSERT INTO clock_reactivations (product_id, installation_id, source, collected_at, local_time)
           VALUES (:p_product, :p_install, 'APP', now(), :p_local)""",
        {"p_product": product_id, "p_install": installation_id, "p_local": str(local_time)[:40]},
    )
    resolve_alerts(conn, installation_id)
    log_audit(conn, actor="PRODUCT_CLIENT", action="CLOCK_REACTIVATED", entity_type="INSTALLATION",
              request_id=request_id, ip=ip,
              after={"installationId": installation_id, "source": "APP", "localTime": local_time})
    return {"serverTime": server_time, "reactivated": True, "adminReleased": False,
            "deltaSeconds": round(delta.total_seconds()), "message": "Licence reactivated."}


def admin_release(conn: Conn, *, product_code: str, installation_id: str, user_id: int,
                  correlation_id: str | None, note: str | None) -> dict[str, Any]:
    """Governed operation CLOCK_RELEASE: let a clock-blocked installation run again."""
    p = conn.execute("SELECT product_id FROM products WHERE product_code = :p_code", {"p_code": product_code}).first
    if not p:
        raise AppError(404, "NOT_FOUND", "Product not found.")
    pid = int(p["PRODUCT_ID"])
    if pending_admin_release(conn, pid, installation_id) is None:
        conn.execute(
            """INSERT INTO clock_reactivations (product_id, installation_id, source, requested_by, note)
               VALUES (:p_product, :p_install, 'ADMIN', :p_user, :p_note)""",
            {"p_product": pid, "p_install": installation_id, "p_user": user_id, "p_note": (note or None)},
        )
    log_audit(conn, user_id=user_id, action="CLOCK_RELEASE_SENT", entity_type="INSTALLATION",
              request_id=correlation_id, after={"installationId": installation_id, "productCode": product_code,
                                                "note": note})
    return {"installationId": installation_id, "productCode": product_code, "releaseSent": True}


def list_clock_alerts(conn: Conn, days: int) -> list[dict[str, Any]]:
    """Latest clock alert per installation in the period, with its reactivation state."""
    rows = conn.execute(
        """SELECT e.event_id, e.payload, e.created_at, e.status
             FROM notification_events e
            WHERE e.event_type = 'CLOCK_TAMPER' AND e.created_at > now() - make_interval(days => :p_days)
            ORDER BY e.created_at DESC""",
        {"p_days": days},
    ).rows
    import json

    seen: dict[str, dict[str, Any]] = {}
    for r in rows:
        try:
            p = json.loads(r["PAYLOAD"] or "{}")
        except ValueError:
            continue
        inst = str(p.get("installationId") or "")
        if not inst or inst in seen:
            continue
        seen[inst] = {
            "eventId": r["EVENT_ID"], "alertAt": r["CREATED_AT"], "installationId": inst,
            "productCode": p.get("productCode"), "deviceName": p.get("deviceName"),
            "licenseNo": p.get("licenseNo"), "customerName": p.get("customerName"), "kind": p.get("kind"),
            "localTime": p.get("localTime"), "referenceTime": p.get("referenceTime"),
            "deltaSeconds": p.get("deltaSeconds"), "appVersion": p.get("appVersion"),
        }
    out = []
    for inst, a in seen.items():
        last = conn.execute(
            """SELECT r.source, r.requested_at, r.collected_at, u.username
                 FROM clock_reactivations r LEFT JOIN users u ON u.user_id = r.requested_by
                WHERE r.installation_id = :p_install ORDER BY r.requested_at DESC LIMIT 1""",
            {"p_install": inst},
        ).first
        state = "ALLOWED" if a["kind"] == "MOVED_FORWARD" else "BLOCKED"
        if state == "ALLOWED":
            pass
        elif last and last["REQUESTED_AT"] >= a["alertAt"]:
            if last["SOURCE"] == "ADMIN" and last["COLLECTED_AT"] is None:
                state = "RELEASE_SENT"
            else:
                state = "REACTIVATED"
        a.update({
            "state": state,
            "reactivatedBy": None if not last or last["REQUESTED_AT"] < a["alertAt"] else
            (last["USERNAME"] if last["SOURCE"] == "ADMIN" else "the user (app)"),
            "reactivationRequestedAt": last["REQUESTED_AT"] if last and last["REQUESTED_AT"] >= a["alertAt"] else None,
            "reactivatedAt": last["COLLECTED_AT"] if last and last["REQUESTED_AT"] >= a["alertAt"] else None,
        })
        out.append(a)
    return out
