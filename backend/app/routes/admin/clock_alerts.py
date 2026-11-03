"""
/api/v1/admin/clock-alerts — computers that blocked their licence after a clock
change, and reactivating them from the portal.
/api/v1/admin/system/time — the licence server's date and time (shown in the portal).
"""
from __future__ import annotations

import time as _time
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends

from ... import schema as z
from ...db import transaction
from ...deps import Ctx, admin_ctx, json_body, require
from ...query import qs_number
from ...respond import now_iso, ok, pending_approval

router = APIRouter()
system_router = APIRouter()

reactivate_schema = z.object({
    "installationId": z.string().trim().min(1).max(100),
    "productCode": z.string().trim().min(1).max(30),
    "note": z.string().max(500).optional(),
})


@router.get("")
def list_alerts(ctx: Ctx = Depends(require("LICENSE_VIEW"))):
    """Latest clock alert per computer (default: last 30 days) and whether it was reactivated."""
    from ...services.clock_reactivation import list_clock_alerts

    days = min(qs_number(ctx.query, "days") or 30, 365)
    with transaction() as conn:
        items = list_clock_alerts(conn, days)
    return ok({"items": items, "days": days, "serverTime": now_iso()})


@router.post("/reactivate")
def reactivate(ctx: Ctx = Depends(require("ACTIVATION_MANAGE")), body: Any = Depends(json_body)):
    """Reactivate a clock-blocked computer. The app picks it up on its next contact."""
    from ...services.governance import submit_or_apply

    b = reactivate_schema.parse(body)
    summary = f"Reactivate {b['productCode']} on computer {b['installationId']} after a clock block"
    result = submit_or_apply(ctx, {
        "entityType": "ACTIVATION",
        "entityId": None,
        "operation": "CLOCK_RELEASE",
        "summary": summary,
        "payload": {k: v for k, v in b.items()},
    })
    if not result.get("applied"):
        return pending_approval(result.get("requestId"), summary)
    return ok(result.get("data"))


@system_router.get("/time")
def server_time(_ctx: Ctx = Depends(admin_ctx)):
    """The licence server's current date and time, and its time zone."""
    local = datetime.now().astimezone()
    return ok({
        "serverTime": now_iso(),
        "timeZone": _time.tzname[0] if local.tzname() is None else local.tzname(),
        "utcOffsetMinutes": int((local.utcoffset() or 0).total_seconds() // 60) if local.utcoffset() else 0,
    })
