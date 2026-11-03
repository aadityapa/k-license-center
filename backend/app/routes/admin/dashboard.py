"""/api/v1/admin/dashboard — summary and the widget overview (DASHBOARD_VIEW)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends

from ...db import transaction
from ...deps import Ctx, require
from ...query import _js_number, rows_to_camel
from ...respond import ok
from ...services.dashboard_overview import build_overview, fetch_facts

router = APIRouter()


def _num(v: Any) -> float | int:
    """Number(v) for the values used here (None -> 0, as `?? 0` precedes every call)."""
    if v is None:
        return 0
    if isinstance(v, bool):
        return 1 if v else 0
    if isinstance(v, (int, float)):
        return v
    n = _js_number(str(v))
    if n is None:
        return float("nan")
    return int(n) if n.is_integer() else n


def _to_series(rows: list[dict[str, Any]] | None) -> list[Any]:
    """Expand sparse day-rows into a dense 14-day series ending today (local calendar)."""
    by_day: dict[str, Any] = {}
    for r in rows or []:
        by_day[str(r.get("DAY"))] = _num(r.get("CNT"))
    today = datetime.now(timezone.utc).astimezone().date()
    out: list[Any] = []
    for i in range(13, -1, -1):
        d = today - timedelta(days=i)
        v = by_day.get(d.isoformat())
        out.append(v if v is not None else 0)
    return out


@router.get("")
def summary(ctx: Ctx = Depends(require("DASHBOARD_VIEW"))):
    with transaction() as conn:
        totals_res = conn.execute(
            """SELECT
                 (SELECT COUNT(*) FROM products)                                   AS products,
                 (SELECT COUNT(*) FROM customers)                                  AS customers,
                 (SELECT COUNT(*) FROM licenses)                                   AS licenses,
                 (SELECT COUNT(*) FROM licenses WHERE status = 'ACTIVE')           AS active_licenses,
                 (SELECT COUNT(*) FROM licenses l
                   JOIN product_plans pp ON pp.plan_id = l.plan_id
                  WHERE l.status = 'ACTIVE' AND pp.plan_code = 'TRIAL')            AS trial_licenses,
                 (SELECT COUNT(*) FROM licenses
                   WHERE status = 'ACTIVE' AND expiry_date IS NOT NULL
                     AND expiry_date BETWEEN CURRENT_DATE AND CURRENT_DATE + 30) AS expiring_soon,
                 (SELECT COUNT(*) FROM licenses WHERE status = 'EXPIRED')          AS expired_licenses,
                 (SELECT COUNT(*) FROM licenses WHERE status = 'SUSPENDED')        AS suspended_licenses,
                 (SELECT COUNT(*) FROM licenses WHERE status = 'REVOKED')          AS revoked_licenses,
                 (SELECT COUNT(*) FROM license_activations WHERE status = 'ACTIVE') AS total_activations"""
        )

        by_status_res = conn.execute(
            "SELECT status, COUNT(*) AS cnt FROM licenses GROUP BY status ORDER BY status"
        )

        per_product_res = conn.execute(
            """SELECT p.product_id, p.product_code, p.product_name,
                      COUNT(l.license_id)                                    AS total_licenses,
                      SUM(CASE WHEN l.status = 'ACTIVE' THEN 1 ELSE 0 END)   AS active_licenses,
                      SUM(CASE WHEN l.status = 'ACTIVE' AND l.expiry_date IS NOT NULL
                                AND l.expiry_date BETWEEN CURRENT_DATE AND CURRENT_DATE + 30
                               THEN 1 ELSE 0 END)                            AS expiring_soon,
                      SUM(CASE WHEN l.status = 'EXPIRED' THEN 1 ELSE 0 END)  AS expired_licenses,
                      COALESCE(SUM(CASE WHEN l.status = 'ACTIVE' THEN l.current_activations ELSE 0 END), 0)
                                                                              AS activations
                 FROM products p
                 LEFT JOIN licenses l ON l.product_id = p.product_id
                GROUP BY p.product_id, p.product_code, p.product_name
                ORDER BY p.product_id"""
        )

        recent_licenses_res = conn.execute(
            """SELECT l.license_id, l.license_no, l.customer_id, l.status, l.created_at, l.expiry_date,
                      c.company_name AS customer_name, p.product_code, p.product_name, pp.plan_name
                 FROM licenses l
                 JOIN customers c      ON c.customer_id = l.customer_id
                 JOIN products p       ON p.product_id = l.product_id
                 JOIN product_plans pp ON pp.plan_id = l.plan_id
                ORDER BY l.created_at DESC
                FETCH FIRST 5 ROWS ONLY"""
        )

        recent_activations_res = conn.execute(
            """SELECT a.activation_id, a.license_id, l.license_no, c.company_name AS customer_name,
                      p.product_code, p.product_name, a.installation_id, a.device_name,
                      a.activated_at, a.status
                 FROM license_activations a
                 JOIN licenses l  ON l.license_id = a.license_id
                 JOIN customers c ON c.customer_id = l.customer_id
                 JOIN products p  ON p.product_id = l.product_id
                ORDER BY a.activated_at DESC
                FETCH FIRST 5 ROWS ONLY"""
        )

        upcoming_renewals_res = conn.execute(
            """SELECT l.license_id, l.license_no, l.customer_id, l.plan_id, l.status, l.expiry_date,
                      c.company_name AS customer_name, p.product_code, p.product_name, pp.plan_name
                 FROM licenses l
                 JOIN customers c      ON c.customer_id = l.customer_id
                 JOIN products p       ON p.product_id = l.product_id
                 JOIN product_plans pp ON pp.plan_id = l.plan_id
                WHERE l.status = 'ACTIVE' AND l.expiry_date IS NOT NULL
                  AND l.expiry_date BETWEEN CURRENT_DATE AND CURRENT_DATE + 30
                ORDER BY l.expiry_date ASC
                FETCH FIRST 10 ROWS ONLY"""
        )

        # 14-day series for the metric sparklines (real counts; empty days are 0).
        license_trend_res = conn.execute(
            """SELECT TO_CHAR(created_at::date, 'YYYY-MM-DD') AS day, COUNT(*) AS cnt
                 FROM licenses
                WHERE created_at >= CURRENT_DATE - 13
                GROUP BY created_at::date
                ORDER BY created_at::date"""
        )

        activation_trend_res = conn.execute(
            """SELECT TO_CHAR(activated_at::date, 'YYYY-MM-DD') AS day, COUNT(*) AS cnt
                 FROM license_activations
                WHERE activated_at >= CURRENT_DATE - 13
                GROUP BY activated_at::date
                ORDER BY activated_at::date"""
        )

        # Security posture from signals the system genuinely records.
        security_res = conn.execute(
            """SELECT
                 (SELECT COUNT(*) FROM api_request_logs
                   WHERE created_at >= now() - INTERVAL '1' DAY
                     AND result_code = 'UNAUTHORIZED_CLIENT')                  AS unauthorized_24h,
                 (SELECT COUNT(*) FROM api_request_logs
                   WHERE created_at >= now() - INTERVAL '1' DAY
                     AND result_code = 'RATE_LIMITED')                         AS rate_limited_24h,
                 (SELECT COUNT(*) FROM api_request_logs
                   WHERE created_at >= now() - INTERVAL '1' DAY
                     AND result_code IN ('INVALID_LICENSE','KEY_REVOKED','INVALID_PRODUCT',
                                         'LICENSE_REVOKED','ACTIVATION_LIMIT_REACHED'))
                                                                                AS denied_24h,
                 (SELECT COUNT(*) FROM users WHERE status = 'LOCKED')           AS locked_users,
                 (SELECT COUNT(*) FROM api_request_logs
                   WHERE created_at >= now() - INTERVAL '1' DAY)         AS requests_24h"""
        )

        recent_audit_res = conn.execute(
            """SELECT a.audit_id, a.action, a.entity_type, a.entity_id, a.actor, a.created_at
                 FROM audit_logs a
                ORDER BY a.audit_id DESC
                FETCH FIRST 8 ROWS ONLY"""
        )

    totals = rows_to_camel(totals_res.rows)
    totals_row = totals[0] if totals else {}
    licenses_by_status = [{"status": str(r.get("STATUS")), "count": _num(r.get("CNT"))} for r in by_status_res.rows]

    secs = rows_to_camel(security_res.rows)
    sec = secs[0] if secs else {}

    def g(d: dict[str, Any], k: str) -> Any:
        v = d.get(k)
        return _num(v if v is not None else 0)

    revoked = g(totals_row, "revokedLicenses")
    suspended = g(totals_row, "suspendedLicenses")
    unauthorized = g(sec, "unauthorized24h")
    rate_limited = g(sec, "rateLimited24h")
    denied = g(sec, "denied24h")
    locked_users = g(sec, "lockedUsers")

    # Transparent scoring: each signal has a fixed, documented weight.
    deductions = [
        {"key": "UNAUTHORIZED_CLIENT", "count": unauthorized, "weight": 12, "label": "Unauthorised API clients (24h)"},
        {"key": "LOCKED_USERS", "count": locked_users, "weight": 10, "label": "Locked admin accounts"},
        {"key": "RATE_LIMITED", "count": rate_limited, "weight": 5, "label": "Rate-limited callers (24h)"},
        {"key": "REVOKED", "count": revoked, "weight": 4, "label": "Revoked licences"},
        {"key": "DENIED", "count": denied, "weight": 2, "label": "Denied authorisation attempts (24h)"},
        {"key": "SUSPENDED", "count": suspended, "weight": 1, "label": "Suspended licences"},
    ]
    score = max(0, 100 - sum(min(d["count"], 5) * d["weight"] for d in deductions))
    posture = "VERIFIED" if score >= 85 else "ELEVATED" if score >= 60 else "AT_RISK"

    return ok({
        "totals": totals_row,
        "licensesByStatus": licenses_by_status,
        "security": {
            "score": score,
            "posture": posture,
            "requests24h": g(sec, "requests24h"),
            "signals": [{"key": d["key"], "label": d["label"], "count": d["count"]} for d in deductions],
        },
        "trends": {
            "licensesCreated": _to_series(license_trend_res.rows),
            "activations": _to_series(activation_trend_res.rows),
        },
        "products": rows_to_camel(per_product_res.rows),
        "recentLicenses": rows_to_camel(recent_licenses_res.rows),
        "recentActivations": rows_to_camel(recent_activations_res.rows),
        "upcomingRenewals": rows_to_camel(upcoming_renewals_res.rows),
        "recentAuditEvents": rows_to_camel(recent_audit_res.rows),
    })


_ALLOWED_DAYS = (7, 30, 90, 180, 365)


@router.get("/overview")
def overview(ctx: Ctx = Depends(require("DASHBOARD_VIEW"))):
    """KPIs vs the previous period, daily series, products, growth, status, health. ?days=7|30|90|180|365."""
    values = ctx.request.query_params.getlist("days")
    if not values:
        raw: float | None = 30.0
    elif len(values) == 1:
        raw = _js_number(values[0])  # Number('7') etc.; None = NaN
    else:
        raw = None  # Number(['a','b']) is NaN
    days = int(raw) if raw is not None and raw in _ALLOWED_DAYS else 30
    now = datetime.now(timezone.utc)
    since_d = now.astimezone().date() - timedelta(days=2 * days - 1)
    with transaction() as conn:
        facts = fetch_facts(conn, since_d.isoformat())
    return ok(build_overview(facts, days, now))
