"""/api/v1/admin/audit-logs — the audit trail (AUDIT_VIEW)."""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends

from ...db import Binds, transaction
from ...deps import Ctx, require
from ...query import paged_query, parse_list, parse_sort, qs, qs_date, qs_number
from ...respond import ok

router = APIRouter()

SELECT = """SELECT a.audit_id, a.user_id, u.username, a.actor, a.action, a.entity_type,
       a.entity_id, a.request_id, a.ip_address, a.before_state, a.after_state, a.created_at"""

FROM = "FROM audit_logs a LEFT JOIN users u ON u.user_id = a.user_id"

SORT_WHITELIST: dict[str, str] = {
    "auditId": "a.audit_id",
    "action": "a.action",
    "entityType": "a.entity_type",
    "createdAt": "a.created_at",
}


def _reject_constant(name: str) -> Any:
    raise ValueError(name)  # JSON.parse has no NaN / Infinity


def parse_json_state(value: Any) -> Any:
    if not isinstance(value, str) or value == "":
        return None
    try:
        return json.loads(value, parse_constant=_reject_constant)
    except ValueError:
        return value


@router.get("")
def list_audit_logs(ctx: Ctx = Depends(require("AUDIT_VIEW"))):
    q_ = ctx.query
    pl = parse_list(q_)
    order_by = parse_sort(qs(q_, "sort"), SORT_WHITELIST, "a.audit_id DESC")
    where: list[str] = ["1=1"]
    binds: Binds = {}

    entity = qs(q_, "entity")
    if entity:
        where.append("UPPER(a.entity_type) = UPPER(:p_entity)")
        binds["p_entity"] = entity
    entity_id = qs_number(q_, "entityId")
    if entity_id is not None:
        where.append("a.entity_id = :p_entity_id")
        binds["p_entity_id"] = entity_id
    action = qs(q_, "action")
    if action:
        where.append("UPPER(a.action) = UPPER(:p_action)")
        binds["p_action"] = action
    user_id = qs_number(q_, "userId")
    if user_id is not None:
        where.append("a.user_id = :p_user_id")
        binds["p_user_id"] = user_id
    from_ = qs_date(q_, "createdFrom")
    if from_ is not None:
        where.append("a.created_at >= TO_DATE(:p_from, 'YYYY-MM-DD')")
        binds["p_from"] = from_
    to = qs_date(q_, "createdTo")
    if to is not None:
        where.append("a.created_at < TO_DATE(:p_to, 'YYYY-MM-DD') + 1")
        binds["p_to"] = to
    q = qs(q_, "q")
    if q:
        where.append("UPPER(a.actor) LIKE '%' || UPPER(:p_q) || '%'")
        binds["p_q"] = q

    with transaction() as conn:
        data: Any = paged_query(
            conn,
            select=SELECT,
            from_where=f"{FROM} WHERE {' AND '.join(where)}",
            binds=binds,
            order_by=order_by,
            page=pl.page,
            page_size=pl.page_size,
        )
    data["items"] = [
        {**item, "beforeState": parse_json_state(item.get("beforeState")),
         "afterState": parse_json_state(item.get("afterState"))}
        for item in data["items"]
    ]
    return ok(data)
