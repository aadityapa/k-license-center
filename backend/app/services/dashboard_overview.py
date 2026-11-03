"""
Data for the admin dashboard (GET /admin/dashboard/overview?days=30).

Every number is computed from records the system really holds — nothing is
sampled or invented. Two definitions worth knowing:

  Revenue  = the amount entered for each licence (or, for older licences
             without one, its plan price), counted on the day it was
             activated, + the amount of each renewal on its date.
  Change % = this period vs the period of the same length just before it.

Dates follow the previous implementation: calendar days are taken in the
server's local time zone, and timestamps are compared with millisecond
precision (JavaScript Date).
"""
from __future__ import annotations

import math
import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from ..db import Conn, Row
from ..respond import date_iso, iso

DENIAL_CODES = ["INVALID_LICENSE", "KEY_REVOKED", "INVALID_PRODUCT", "LICENSE_REVOKED",
                "ACTIVATION_LIMIT_REACHED", "LICENSE_EXPIRED", "LICENSE_SUSPENDED", "WRONG_MACHINE"]

_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# JavaScript Date helpers (local calendar, millisecond precision)
# ---------------------------------------------------------------------------
def _local_midnight(d: date) -> datetime:
    """new Date(y, m, d): local midnight as an aware datetime."""
    return datetime.combine(d, time(0)).astimezone()


def _day(d: datetime) -> str:
    """YYYY-MM-DD from local date parts."""
    return d.astimezone().strftime("%Y-%m-%d")


def _to_date(v: Any) -> datetime | None:
    if isinstance(v, datetime):
        dt = v if v.tzinfo is not None else v.astimezone()
        # Date has millisecond precision.
        return dt.replace(microsecond=(dt.microsecond // 1000) * 1000)
    if isinstance(v, date):
        return _local_midnight(v)
    if isinstance(v, str) and v:
        try:
            if len(v) == 10:
                return _local_midnight(date.fromisoformat(v))
            dt = datetime.fromisoformat(re.sub(r"[Zz]$", "+00:00", v))
            return _to_date(dt)
        except ValueError:
            return None
    return None


def _ms(d: datetime | None) -> int:
    return 0 if d is None else (d - _EPOCH) // timedelta(milliseconds=1)


def _js_iso(v: Any) -> str | None:
    """toDate(v)?.toISOString() ?? null"""
    if isinstance(v, datetime):
        return iso(v)
    if isinstance(v, date):
        return date_iso(v)
    d = _to_date(v)
    return iso(d) if d is not None else None


def _n(v: Any) -> float | int:
    """v == null || v === '' ? 0 : Number(v) || 0"""
    if v is None or v == "":
        return 0
    if isinstance(v, bool):
        return 1 if v else 0
    if isinstance(v, (int, float)):
        if isinstance(v, float) and (math.isnan(v)):
            return 0
        return v
    try:
        f = float(str(v).strip()) if str(v).strip() != "" else 0.0
    except ValueError:
        return 0
    if math.isnan(f):
        return 0
    return int(f) if f.is_integer() and abs(f) < 2**53 else f


def _s(v: Any) -> str:
    """String(v)"""
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float):
        if v.is_integer():
            return str(int(v))
        return repr(v)
    return str(v)


def _round(x: float) -> int:
    """Math.round"""
    return math.floor(x + 0.5)


# ---------------------------------------------------------------------------
def fetch_facts(conn: Conn, since: str) -> dict[str, Any]:
    """PostgreSQL facts. `since` = first day of the previous period (YYYY-MM-DD)."""
    lic = conn.execute(
        """SELECT l.license_id, l.license_no, l.customer_id, l.product_id, l.status, l.start_date,
                  l.expiry_date, l.created_at, l.current_activations, l.max_activations,
                  COALESCE(l.amount, pp.price) AS price, pp.plan_name, pp.plan_code, p.product_code, p.product_name,
                  c.company_name AS customer_name
             FROM licenses l
             JOIN product_plans pp ON pp.plan_id = l.plan_id
             JOIN products p       ON p.product_id = l.product_id
             JOIN customers c      ON c.customer_id = l.customer_id""",
        {},
    )
    act = conn.execute(
        """SELECT a.activation_id, a.license_id, a.device_name, a.installation_id, a.os_info,
                  a.status, a.activated_at
             FROM license_activations a
            WHERE a.activated_at >= CAST(:p_since AS date)""",
        {"p_since": since},
    )
    recent_act = conn.execute(
        """SELECT a.activation_id, a.license_id, a.device_name, a.installation_id, a.os_info,
                  a.status, a.activated_at
             FROM license_activations a
            ORDER BY a.activated_at DESC, a.activation_id DESC
            LIMIT 8""",
        {},
    )
    ren = conn.execute(
        """SELECT r.license_id, r.renewal_date, r.amount
             FROM license_renewals r
            WHERE r.renewal_date >= CAST(:p_since AS date)""",
        {"p_since": since},
    )
    cust = conn.execute(
        """SELECT customer_id, customer_code, company_name, contact_person, email, status, created_at
             FROM customers""",
        {},
    )
    api = conn.execute(
        """SELECT COUNT(*) AS total,
                  COALESCE(SUM(CASE WHEN http_status >= 500 THEN 1 ELSE 0 END), 0) AS errors,
                  COALESCE(SUM(CASE WHEN result_code = ANY(CAST(:p_denials AS text[])) THEN 1 ELSE 0 END), 0) AS denied,
                  COALESCE(SUM(CASE WHEN result_code = 'UNAUTHORIZED_CLIENT' THEN 1 ELSE 0 END), 0) AS unauthorized,
                  COALESCE(SUM(CASE WHEN endpoint LIKE '%/activate'
                                     AND result_code = ANY(CAST(:p_denials AS text[])) THEN 1 ELSE 0 END), 0) AS failed_acts
             FROM api_request_logs
            WHERE created_at >= now() - INTERVAL '1 day'""",
        {"p_denials": "{" + ",".join(DENIAL_CODES) + "}"},
    )
    pend = conn.execute(
        """SELECT (SELECT COUNT(*) FROM change_requests WHERE status = 'PENDING')        AS changes,
                  (SELECT COUNT(*) FROM license_requests WHERE status = 'UNDER_REVIEW')  AS requests,
                  (SELECT COUNT(*) FROM email_outbox WHERE status = 'FAILED')            AS emails,
                  (SELECT COUNT(*) FROM notification_events
                    WHERE event_type = 'CLOCK_TAMPER' AND created_at > now() - INTERVAL '7 days') AS clock_alerts""",
        {},
    )
    a = api.first or {}
    p = pend.first or {}
    return {
        "licenses": lic.rows,
        "activations": act.rows,
        "recentActivations": recent_act.rows,
        "renewals": ren.rows,
        "customers": cust.rows,
        "api24h": {
            "total": _n(a.get("TOTAL")), "errors": _n(a.get("ERRORS")), "denied": _n(a.get("DENIED")),
            "unauthorized": _n(a.get("UNAUTHORIZED")), "failedActivations": _n(a.get("FAILED_ACTS")),
        },
        "pendingChanges": _n(p.get("CHANGES")),
        "pendingRequests": _n(p.get("REQUESTS")),
        "failedEmails": _n(p.get("EMAILS")),
        "clockAlerts": _n(p.get("CLOCK_ALERTS")),
    }


def is_denial(code: Any) -> bool:
    return _s(code) in DENIAL_CODES


def _pct(cur: float, prev: float) -> float | None:
    if prev == 0:
        return 0 if cur == 0 else None
    return _round(((cur - prev) / prev) * 1000) / 10


def build_overview(f: dict[str, Any], days: int, now: datetime | None = None) -> dict[str, Any]:
    """Turns facts into the dashboard payload. `days` = period length (7..365)."""
    if now is None:
        now = datetime.now(timezone.utc)
    today_d = now.astimezone().date()
    today = _local_midnight(today_d)
    from_d = today_d - timedelta(days=days - 1)                # period = [from, today]
    prev_from_d = from_d - timedelta(days=days)                 # previous = [prevFrom, from)
    from_ = _local_midnight(from_d)
    prev_from = _local_midnight(prev_from_d)

    def in_cur(d: datetime | None) -> bool:
        return d is not None and d >= from_

    def in_prev(d: datetime | None) -> bool:
        return d is not None and prev_from <= d < from_

    licenses: list[Row] = f["licenses"]
    lic_by_id: dict[Any, Row] = {}
    for l in licenses:
        lic_by_id[_n(l.get("LICENSE_ID"))] = l

    # ---- revenue events: activation of a priced licence, and renewals ----
    revenue: list[dict[str, Any]] = []
    for l in licenses:
        d = _to_date(l.get("START_DATE"))
        if d and _n(l.get("PRICE")) > 0:
            revenue.append({"date": d, "amount": _n(l.get("PRICE")), "productCode": _s(l.get("PRODUCT_CODE"))})
    for r in f["renewals"]:
        d = _to_date(r.get("RENEWAL_DATE"))
        l = lic_by_id.get(_n(r.get("LICENSE_ID")))
        if d and _n(r.get("AMOUNT")) > 0:
            pc = l.get("PRODUCT_CODE") if l is not None else None
            revenue.append({"date": d, "amount": _n(r.get("AMOUNT")), "productCode": _s(pc if pc is not None else "")})

    def total(xs: list[dict[str, Any]]) -> float:
        s: float = 0
        for e in xs:
            s = s + e["amount"]
        return s

    rev_cur = total([e for e in revenue if in_cur(e["date"])])
    rev_prev = total([e for e in revenue if in_prev(e["date"])])

    lic_cur = len([l for l in licenses if in_cur(_to_date(l.get("CREATED_AT")))])
    lic_prev = len([l for l in licenses if in_prev(_to_date(l.get("CREATED_AT")))])
    act_cur = len([a for a in f["activations"] if in_cur(_to_date(a.get("ACTIVATED_AT")))])
    act_prev = len([a for a in f["activations"] if in_prev(_to_date(a.get("ACTIVATED_AT")))])

    active_customer_ids = {_n(l.get("CUSTOMER_ID")) for l in licenses if l.get("STATUS") == "ACTIVE"}
    new_cust_cur = len([c for c in f["customers"] if in_cur(_to_date(c.get("CREATED_AT")))])
    new_cust_prev = len([c for c in f["customers"] if in_prev(_to_date(c.get("CREATED_AT")))])

    # ---- daily series over the period ----
    series: list[dict[str, Any]] = []
    idx: dict[str, int] = {}
    cur_d = from_d
    while cur_d <= today_d:
        key = cur_d.isoformat()
        idx[key] = len(series)
        series.append({"date": key, "revenue": 0, "licenses": 0, "activations": 0})
        cur_d = cur_d + timedelta(days=1)

    def bump(d: datetime | None, k: str, v: Any = 1) -> None:
        if not d:
            return
        i = idx.get(_day(d))
        if i is not None:
            series[i][k] += v

    for e in revenue:
        bump(e["date"], "revenue", e["amount"])
    for l in licenses:
        bump(_to_date(l.get("CREATED_AT")), "licenses")
    for a in f["activations"]:
        bump(_to_date(a.get("ACTIVATED_AT")), "activations")

    # ---- products in the period ----
    prod: dict[str, dict[str, Any]] = {}
    for l in licenses:
        code = _s(l.get("PRODUCT_CODE"))
        p = prod.get(code) or {"productCode": code, "productName": _s(l.get("PRODUCT_NAME")),
                               "licenses": 0, "revenue": 0, "active": 0, "total": 0}
        p["total"] += 1
        if l.get("STATUS") == "ACTIVE":
            p["active"] += 1
        if in_cur(_to_date(l.get("CREATED_AT"))):
            p["licenses"] += 1
        prod[code] = p
    for e in revenue:
        if in_cur(e["date"]) and e["productCode"] in prod:
            prod[e["productCode"]]["revenue"] += e["amount"]
    products = sorted(prod.values(), key=lambda x: (-x["revenue"], -x["licenses"], -x["total"]))

    # ---- customer growth: last 6 calendar months ----
    created = [_to_date(c.get("CREATED_AT")) for c in f["customers"]]
    months: list[dict[str, Any]] = []
    for i in range(5, -1, -1):
        m0 = today_d.year * 12 + (today_d.month - 1) - i
        start_d = date(m0 // 12, m0 % 12 + 1, 1)
        end_d = date((m0 + 1) // 12, (m0 + 1) % 12 + 1, 1)
        start, end = _local_midnight(start_d), _local_midnight(end_d)
        months.append({
            "month": f"{start_d.year}-{start_d.month:02d}",
            "label": _MONTHS[start_d.month - 1],
            "newCustomers": len([d for d in created if d and start <= d < end]),
            "totalCustomers": len([d for d in created if d and d < end]),
        })

    # ---- licence status ----
    in30 = _local_midnight(today_d + timedelta(days=30))
    in7 = _local_midnight(today_d + timedelta(days=7))
    status_count: dict[str, int] = {}
    for l in licenses:
        k = _s(l.get("STATUS"))
        status_count[k] = status_count.get(k, 0) + 1

    def expiring(limit: datetime) -> int:
        c = 0
        for l in licenses:
            e = _to_date(l.get("EXPIRY_DATE"))
            if l.get("STATUS") == "ACTIVE" and e is not None and today <= e <= limit:
                c += 1
        return c

    expiring_soon = expiring(in30)
    expiring7 = expiring(in7)

    # ---- top customers by seats in use ----
    seats: dict[Any, dict[str, Any]] = {}
    for l in licenses:
        if l.get("STATUS") != "ACTIVE":
            continue
        cid = _n(l.get("CUSTOMER_ID"))
        s = seats.get(cid) or {"customerId": cid, "customerName": _s(l.get("CUSTOMER_NAME")), "seats": 0, "licenses": 0}
        s["seats"] += _n(l.get("CURRENT_ACTIVATIONS"))
        s["licenses"] += 1
        seats[cid] = s
    top_customers = sorted(seats.values(), key=lambda x: (-x["seats"], -x["licenses"]))[:6]

    # ---- recent tables ----
    def date_only(v: Any) -> str | None:
        d = _to_date(v)
        return _day(d) if d else None

    recent_licenses = [
        {
            "licenseId": _n(l.get("LICENSE_ID")), "licenseNo": _s(l.get("LICENSE_NO")),
            "customerId": _n(l.get("CUSTOMER_ID")), "customerName": _s(l.get("CUSTOMER_NAME")),
            "productCode": _s(l.get("PRODUCT_CODE")), "productName": _s(l.get("PRODUCT_NAME")),
            "planName": _s(l.get("PLAN_NAME")), "status": _s(l.get("STATUS")),
            "createdAt": _js_iso(l.get("CREATED_AT")), "expiryDate": date_only(l.get("EXPIRY_DATE")),
        }
        for l in sorted(licenses, key=lambda x: (-_ms(_to_date(x.get("CREATED_AT"))), -_n(x.get("LICENSE_ID"))))[:8]
    ]

    recent_activations = []
    for a in f["recentActivations"]:
        l = lic_by_id.get(_n(a.get("LICENSE_ID")))

        def lv(k: str) -> str:
            v = l.get(k) if l is not None else None
            return _s(v if v is not None else "")

        dn = a.get("DEVICE_NAME")
        inst = a.get("INSTALLATION_ID")
        recent_activations.append({
            "activationId": _n(a.get("ACTIVATION_ID")), "licenseId": _n(a.get("LICENSE_ID")),
            "licenseNo": lv("LICENSE_NO"), "productName": lv("PRODUCT_NAME"), "customerName": lv("CUSTOMER_NAME"),
            "deviceName": dn if dn is not None else _s(inst if inst is not None else ""),
            "osInfo": a.get("OS_INFO"), "status": _s(a.get("STATUS")), "activatedAt": _js_iso(a.get("ACTIVATED_AT")),
        })

    recent_customers = [
        {
            "customerId": _n(c.get("CUSTOMER_ID")), "companyName": _s(c.get("COMPANY_NAME")),
            "contactPerson": c.get("CONTACT_PERSON"), "email": c.get("EMAIL"), "status": _s(c.get("STATUS")),
            "createdAt": _js_iso(c.get("CREATED_AT")),
            "activeLicenses": len([l for l in licenses
                                   if _n(l.get("CUSTOMER_ID")) == _n(c.get("CUSTOMER_ID")) and l.get("STATUS") == "ACTIVE"]),
        }
        for c in sorted(f["customers"], key=lambda x: (-_ms(_to_date(x.get("CREATED_AT"))), -_n(x.get("CUSTOMER_ID"))))[:8]
    ]

    api = f["api24h"]
    api_ok = 100 if api["total"] == 0 else _round(((api["total"] - api["errors"]) / api["total"]) * 1000) / 10
    auth_ok = 100 if api["total"] == 0 else _round(
        ((api["total"] - api["denied"] - api["unauthorized"]) / api["total"]) * 1000) / 10

    return {
        "period": {"days": days, "from": from_d.isoformat(), "to": today_d.isoformat(), "previousFrom": prev_from_d.isoformat()},
        "kpis": {
            "revenue": {"value": rev_cur, "previous": rev_prev, "changePct": _pct(rev_cur, rev_prev)},
            "licenses": {"value": len(licenses), "periodNew": lic_cur, "previous": lic_prev, "changePct": _pct(lic_cur, lic_prev)},
            "activeCustomers": {"value": len(active_customer_ids), "periodNew": new_cust_cur, "previous": new_cust_prev,
                                "changePct": _pct(new_cust_cur, new_cust_prev)},
            "activations": {"value": act_cur, "previous": act_prev, "changePct": _pct(act_cur, act_prev)},
        },
        "series": series,
        "products": products,
        "customerGrowth": months,
        "licenseStatus": {
            "total": len(licenses),
            "active": status_count.get("ACTIVE", 0),
            "draft": status_count.get("DRAFT", 0),
            "suspended": status_count.get("SUSPENDED", 0),
            "expired": status_count.get("EXPIRED", 0),
            "revoked": status_count.get("REVOKED", 0),
            "cancelled": status_count.get("CANCELLED", 0),
            "expiringSoon": expiring_soon,
        },
        "health": {
            "apiSuccessPct": api_ok,
            "authSuccessPct": auth_ok,
            "database": "UP",
            "requests24h": api["total"],
            "securityAlerts": api["unauthorized"],
            "failedActivations24h": api["failedActivations"],
            "pendingRequests": f["pendingRequests"],
            "clockAlerts7d": f["clockAlerts"],
        },
        "pendingActions": [
            {"key": "clock", "label": "clock-tampering alerts from apps (7 days)", "count": f["clockAlerts"], "to": "/audit-logs"},
            {"key": "changes", "label": "change requests waiting for approval", "count": f["pendingChanges"], "to": "/approvals"},
            {"key": "requests", "label": "licence requests to review", "count": f["pendingRequests"], "to": "/license-requests"},
            {"key": "expiring", "label": "licences expiring within 7 days", "count": expiring7,
             "to": "/licenses?status=ACTIVE&sort=expiryDate"},
            {"key": "failedActs", "label": "failed activation attempts (24h)", "count": api["failedActivations"], "to": "/api-logs"},
            {"key": "security", "label": "unauthorised API calls (24h)", "count": api["unauthorized"], "to": "/api-logs"},
            {"key": "emails", "label": "emails that failed to send", "count": f["failedEmails"], "to": "/email-outbox"},
        ],
        "topCustomers": top_customers,
        "recentLicenses": recent_licenses,
        "recentActivations": recent_activations,
        "recentCustomers": recent_customers,
    }
