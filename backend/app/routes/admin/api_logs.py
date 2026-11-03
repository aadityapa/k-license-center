"""/api/v1/admin/api-logs — product API request log (AUDIT_VIEW)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from ...db import Binds, transaction
from ...deps import Ctx, require
from ...query import paged_query, parse_list, parse_sort, qs, qs_date, qs_number
from ...respond import ok

router = APIRouter()

SELECT = """SELECT g.log_id, g.request_id, g.client_id, c.name AS client_name, c.client_key, g.endpoint,
       g.method, g.license_key_hash, g.result_code, g.http_status, g.ip_address,
       g.duration_ms, g.created_at"""

FROM = "FROM api_request_logs g LEFT JOIN api_clients c ON c.client_id = g.client_id"

SORT_WHITELIST: dict[str, str] = {
    "logId": "g.log_id",
    "endpoint": "g.endpoint",
    "resultCode": "g.result_code",
    "httpStatus": "g.http_status",
    "durationMs": "g.duration_ms",
    "createdAt": "g.created_at",
}


@router.get("")
def list_api_logs(ctx: Ctx = Depends(require("AUDIT_VIEW"))):
    q_ = ctx.query
    pl = parse_list(q_)
    order_by = parse_sort(qs(q_, "sort"), SORT_WHITELIST, "g.log_id DESC")
    where: list[str] = ["1=1"]
    binds: Binds = {}

    client_id = qs_number(q_, "clientId")
    if client_id is not None:
        where.append("g.client_id = :p_client_id")
        binds["p_client_id"] = client_id
    endpoint = qs(q_, "endpoint")
    if endpoint:
        where.append("UPPER(g.endpoint) LIKE '%' || UPPER(:p_endpoint) || '%'")
        binds["p_endpoint"] = endpoint
    result_code = qs(q_, "resultCode")
    if result_code:
        where.append("UPPER(g.result_code) = UPPER(:p_result_code)")
        binds["p_result_code"] = result_code
    from_ = qs_date(q_, "createdFrom")
    if from_ is not None:
        where.append("g.created_at >= TO_DATE(:p_from, 'YYYY-MM-DD')")
        binds["p_from"] = from_
    to = qs_date(q_, "createdTo")
    if to is not None:
        where.append("g.created_at < TO_DATE(:p_to, 'YYYY-MM-DD') + 1")
        binds["p_to"] = to
    q = qs(q_, "q")
    if q:
        where.append(
            """(UPPER(g.endpoint) LIKE '%' || UPPER(:p_q) || '%'
            OR UPPER(COALESCE(g.request_id, ' ')) LIKE '%' || UPPER(:p_q) || '%'
            OR UPPER(COALESCE(g.ip_address, ' ')) LIKE '%' || UPPER(:p_q) || '%')"""
        )
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
    return ok(data)
