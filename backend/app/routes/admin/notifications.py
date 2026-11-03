"""
/api/v1/admin/notifications — the portal bell.

notification_events is written whenever something outside the portal needs a
person's attention — a product or a prospect raising a licence request, a
licence nearing expiry, a clock-tamper alert. This is the read side: what is
still PENDING, and the act of a reviewer acknowledging it (PENDING -> SENT).

Acknowledging is shared, not per user: one desk, one queue.
"""
from __future__ import annotations

import json
import math
from typing import Any

from fastapi import APIRouter, Depends

from ... import schema as z
from ...db import transaction
from ...deps import Ctx, json_body, require
from ...query import rows_to_camel
from ...respond import ok
from ..public import _js_number

router = APIRouter()

ack_schema = z.object({
    # Event ids to acknowledge; omit to acknowledge everything pending.
    "eventIds": z.array(z.number().int().positive()).max(500).optional(),
})


def _parse_payload(raw: Any) -> Any:
    if not isinstance(raw, str):
        return raw
    try:
        return json.loads(raw)
    except ValueError:
        return raw


def _limit(ctx: Ctx) -> int | float:
    """Math.min(Math.max(Number(req.query.limit ?? 20) || 20, 1), 100)"""
    values = ctx.request.query_params.getlist("limit")
    if not values:
        n: Any = 20
    elif len(values) > 1:
        n = _js_number(values)  # an array, as Express parsed a repeated key
    else:
        n = _js_number(values[0])
    if n == 0 or (isinstance(n, float) and math.isnan(n)):
        n = 20
    return min(max(n, 1), 100)


@router.get("")
def list_notifications(ctx: Ctx = Depends(require("DASHBOARD_VIEW"))):
    """Unread first, newest first; capped so the bell stays cheap to poll."""
    limit = _limit(ctx)
    with transaction() as conn:
        r = conn.execute(
            """SELECT event_id, event_type, entity_type, entity_id, customer_id,
                  payload, status, created_at
             FROM notification_events
            WHERE status IN ('PENDING','SENT')
            ORDER BY CASE WHEN status = 'PENDING' THEN 0 ELSE 1 END, created_at DESC, event_id DESC
            LIMIT :p_limit""",
            {"p_limit": limit},
        )
        unread = conn.execute(
            "SELECT COUNT(*) AS n FROM notification_events WHERE status = 'PENDING'",
            {},
        )
        items = [{**n, "payload": _parse_payload(n.get("payload"))} for n in rows_to_camel(r.rows)]
        first = unread.first or {}
        data = {"items": items, "unread": int(first.get("N") or 0)}
    return ok(data)


@router.post("/ack")
def ack(ctx: Ctx = Depends(require("DASHBOARD_VIEW")), body: Any = Depends(json_body)):
    b = ack_schema.parse(body)
    with transaction() as conn:
        ids = b.get("eventIds")
        if ids and len(ids) > 0:
            count = 0
            for eid in ids:
                r = conn.execute(
                    """UPDATE notification_events SET status = 'SENT', processed_at = now()
                WHERE event_id = :p_id AND status = 'PENDING'""",
                    {"p_id": eid},
                )
                count += r.rows_affected or 0
            n = count
        else:
            r = conn.execute(
                """UPDATE notification_events SET status = 'SENT', processed_at = now()
            WHERE status = 'PENDING'""",
                {},
            )
            n = r.rows_affected or 0
    return ok({"acknowledged": n})
