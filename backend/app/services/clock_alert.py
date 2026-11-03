"""
Clock-tamper alerts from installed apps (POST /api/v1/license/clock-alert).

When a user changes the computer's date/time, the app blocks itself and
reports it here. The report becomes a CRITICAL notification in the portal's
bell (event CLOCK_TAMPER), an audit-log entry, and a line in the API log.
Repeats from the same machine within 10 minutes are recorded once.

Input dict (ClockAlertInput): productId, productCode, installationId, licenseKey?,
kind, localTime?, referenceTime?, deltaSeconds?, deviceName?, appVersion?, ip?,
requestId?. Result: {"recorded", "duplicate", "licenseNo"}.
"""
from __future__ import annotations

import re
from typing import Any

from ..db import Conn
from ..respond import dumps
from .audit import log_audit


def record_clock_alert(conn: Conn, a: dict[str, Any]) -> dict[str, Any]:
    # The licence this machine runs on, when the key is one of ours for this product.
    license_id: int | None = None
    customer_id: int | None = None
    license_no: str | None = None
    customer_name: str | None = None
    if a.get("licenseKey"):
        r = conn.execute(
            """SELECT l.license_id AS clock_licence_id, l.customer_id, l.license_no, c.company_name
         FROM license_keys k
         JOIN licenses l  ON l.license_id = k.license_id
         JOIN customers c ON c.customer_id = l.customer_id
        WHERE k.license_key = :p_key AND l.product_id = :p_product_id""",
            {"p_key": a["licenseKey"], "p_product_id": a["productId"]},
        )
        row = r.first
        if row:
            license_id = int(row["CLOCK_LICENCE_ID"])
            customer_id = None if row["CUSTOMER_ID"] is None else int(row["CUSTOMER_ID"])
            license_no = None if row["LICENSE_NO"] is None else str(row["LICENSE_NO"])
            customer_name = None if row["COMPANY_NAME"] is None else str(row["COMPANY_NAME"])

    install = re.sub(r'["%_\\]', "", str(a["installationId"]))
    recent = conn.execute(
        """SELECT COUNT(*) AS recent_clock FROM notification_events
      WHERE event_type = 'CLOCK_TAMPER' AND payload LIKE :p_install AND payload LIKE :p_kind
        AND created_at > now() - INTERVAL '10 minutes'""",
        # Per kind: a date moved forward and then set back are two different events.
        {"p_install": f'%"installationId":"{install}"%', "p_kind": f'%"kind":"{re.sub(r"[^A-Z_]", "", str(a["kind"]))}"%'},
    )
    first = recent.first or {}
    if int(first.get("RECENT_CLOCK") or 0) > 0:
        return {"recorded": False, "duplicate": True, "licenseNo": license_no}

    def opt(k: str) -> Any:
        v = a.get(k)
        return v if v is not None else None

    payload = {
        # Moving the date forward is allowed by the app (reported only); setting it
        # back blocks the licence until it is reactivated.
        "severity": "WARNING" if a["kind"] == "MOVED_FORWARD" else "CRITICAL",
        "kind": a["kind"],
        "productCode": a["productCode"],
        "installationId": a["installationId"],
        "deviceName": opt("deviceName"),
        "licenseNo": license_no,
        "customerName": customer_name,
        "localTime": opt("localTime"),
        "referenceTime": opt("referenceTime"),
        "deltaSeconds": opt("deltaSeconds"),
        "appVersion": opt("appVersion"),
        "ip": opt("ip"),
    }
    conn.execute(
        """INSERT INTO notification_events (event_type, entity_type, entity_id, customer_id, payload, status)
     VALUES (:p_event_type, :p_entity_type, :p_id, :p_customer_id, :p_payload, 'PENDING')""",
        {
            "p_event_type": "CLOCK_TAMPER",
            "p_entity_type": "LICENSE" if license_id else "INSTALLATION",
            "p_id": license_id,
            "p_customer_id": customer_id,
            "p_payload": dumps(payload),
        },
    )
    log_audit(
        conn,
        actor="PRODUCT_CLIENT",
        action="CLOCK_TAMPER_DETECTED",
        entity_type="LICENSE" if license_id else "INSTALLATION",
        entity_id=license_id,
        request_id=a.get("requestId"),
        ip=a.get("ip"),
        after=payload,
    )
    return {"recorded": True, "duplicate": False, "licenseNo": license_no}
