"""
/api/v1/license — the product API used by installed apps (Vehicle SIM, KStack,
KFlash, the SDKs). Every route sits behind the per-client rate limit
(middleware) and product client authentication (`client_ctx`).
"""
from __future__ import annotations

import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from .. import schema as z
from ..db import Row, transaction
from ..deps import Ctx, client_ctx, json_body
from ..errors import AppError
from ..query import fmt_date_only, to_camel
from ..respond import UNDEFINED, now_iso, ok
from ..services import live_channel
from ..services.api_log import log_api_request
from ..services.authz import build_authorization, denied_payload
from ..services.settings import get_offline_grace_days

router = APIRouter()

# Typed keys: KSTK-A1B2-C3D4-E5F6. Used by KStack, KFlash and anything new.
LICENSE_KEY_RE = re.compile(r"^[A-Z]{2,6}(-[A-Z0-9]{4}){3}$")  # prefix = products.key_prefix (2-6 letters)

# Vehicle SIM keys: base64url(payload).base64url(signature).
VBS_KEY_RE = re.compile(r"^[A-Za-z0-9_-]{16,512}\.[A-Za-z0-9_-]{16,512}$")


def _full(rx: re.Pattern, value: str) -> bool:
    # JS `$` matches only at the very end (no trailing-newline allowance like Python's `$`).
    m = rx.match(value)
    return m is not None and m.end() == len(value)


def is_license_key_shape(value: str) -> bool:
    """Input-sanity check only (either key shape); pkg_authorization decides validity."""
    return isinstance(value, str) and (_full(LICENSE_KEY_RE, value) or _full(VBS_KEY_RE, value))


TIMESTAMP_SKEW_MS = 5 * 60 * 1000

_base_fields = {
    "licenseKey": z.string().refine(is_license_key_shape, "Invalid license key format"),
    "productCode": z.string().min(1).max(30),
    "installationId": z.string().min(1).max(100),
    "timestamp": z.string().max(40).optional(),
}

activate_schema = z.object({
    **_base_fields,
    "deviceId": z.string().max(100).optional(),
    "deviceName": z.string().max(150).optional(),
    "machineFingerprint": z.string().max(128).optional(),
    "os": z.string().max(150).optional(),
    "appVersion": z.string().max(30).optional(),
})

validate_schema = z.object(dict(_base_fields))

heartbeat_schema = z.object({
    **_base_fields,
    "appVersion": z.string().max(30).optional(),
})


# ---------------------------------------------------------------------------
# Date.parse (the subset of formats V8 accepts that a client could plausibly send)
# ---------------------------------------------------------------------------
_ISO_RE = re.compile(
    r"^([+-][0-9]{6}|[0-9]{4})(?:-([0-9]{2})(?:-([0-9]{2}))?)?"
    r"(?:[Tt](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d+))?)?)?"
    r"([Zz]|[+-]\d{2}:\d{2})?$"
)
# V8's legacy fallback: "YYYY-MM-DD HH:mm[:ss[.sss]]" (local unless an offset is given)
_LEGACY_RE = re.compile(
    r"^\s*([0-9]{4})-([0-9]{1,2})-([0-9]{1,2})(?:(?:[Tt](?=[0-9]{2}:)| +)([0-9]{1,2}):(\d{2})(?::(\d{2})(?:\.(\d+))?)?)?"
    r"\s*(?:([Zz]|UTC|GMT)|([+-]\d{2}):?(\d{2}))?\s*$"
)
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _ms(dt: datetime) -> int:
    return (dt - _EPOCH) // timedelta(milliseconds=1)


def _mk(y: int, mo: int, d: int, h: int, mi: int, s: int, frac: str | None, tz: timezone | None) -> int | None:
    # V8 accepts day 1..31 in any month and rolls over (2026-02-30 -> 2026-03-02).
    if not (1 <= mo <= 12 and 1 <= d <= 31 and mi <= 59 and s <= 59):
        return None
    if h > 24 or (h == 24 and (mi or s or (frac and int(frac)))):
        return None
    try:
        base = datetime(y, mo, 1) + timedelta(days=d - 1, hours=h, minutes=mi, seconds=s)
    except (ValueError, OverflowError):
        return None
    ms = int((frac or "0")[:3].ljust(3, "0"))
    base = base + timedelta(milliseconds=ms)
    aware = base.replace(tzinfo=tz) if tz is not None else base.astimezone()
    return _ms(aware)


def _tz(z_or_off: str | None) -> timezone | None:
    if not z_or_off:
        return None
    if z_or_off.upper() in ("Z", "UTC", "GMT"):
        return timezone.utc
    sign = -1 if z_or_off[0] == "-" else 1
    hh, mm = z_or_off[1:].split(":") if ":" in z_or_off else (z_or_off[1:3], z_or_off[3:5])
    return timezone(sign * timedelta(hours=int(hh), minutes=int(mm)))


def js_date_parse(s: str) -> int | None:
    """Date.parse(s) in ms, or None for NaN."""
    m = _ISO_RE.match(s)
    if m:
        y_raw, mo, d, h, mi, sec, frac, zone = m.groups()
        if y_raw == "-000000":
            return None
        y = int(y_raw)
        has_time = h is not None
        tz = _tz(zone)
        if tz is None and not has_time:
            tz = timezone.utc  # date-only forms are UTC
        if not has_time and zone:
            return None
        return _mk(y, int(mo or 1), int(d or 1), int(h or 0), int(mi or 0), int(sec or 0), frac, tz)
    m = _LEGACY_RE.match(s)
    if m:
        y, mo, d, h, mi, sec, frac, zname, oh, om = m.groups()
        tz = _tz(zname) if zname else (_tz(f"{oh}:{om}") if oh else None)
        return _mk(int(y), int(mo), int(d), int(h or 0), int(mi or 0), int(sec or 0), frac, tz)
    try:  # RFC 2822 / Date.toString() style ("Tue Oct 28 2026 10:00:00 GMT+0000")
        from email.utils import parsedate_to_datetime

        dt = parsedate_to_datetime(re.sub(r"^(\w{3}) (\w{3}) (\d{1,2}) (\d{4})", r"\1, \3 \2 \4", s.strip())
                                   .split(" (")[0].replace("GMT+", "+").replace("GMT-", "-"))
        return _ms(dt if dt.tzinfo else dt.astimezone())
    except (TypeError, ValueError, IndexError):
        return None


def assert_fresh_timestamp(ts: str | None) -> None:
    """Replay guard: optional in v1, but when present must be within +/- 5 minutes."""
    if ts is None:
        return
    t = js_date_parse(ts)
    if t is None:
        raise AppError(400, "VALIDATION_ERROR", "timestamp must be an ISO-8601 date-time.")
    if abs(_now_ms() - t) > TIMESTAMP_SKEW_MS:
        raise AppError(400, "VALIDATION_ERROR", "timestamp is outside the allowed clock skew (+/-5 minutes).")


def _now_ms() -> int:
    return int(time.time() * 1000)


VALIDATE_PLSQL = """SELECT * FROM pkg_authorization.validate(
    p_license_key     => :p_license_key,
    p_product_id      => :p_product_id,
    p_installation_id => :p_installation_id,
    p_heartbeat       => :p_heartbeat,
    p_app_version     => :p_app_version)"""


def _key_binding(license_key: str) -> Row | None:
    with transaction() as conn:
        r = conn.execute(
            """SELECT l.vbs_machine_id, l.license_id
                 FROM license_keys k JOIN licenses l ON l.license_id = k.license_id
                WHERE k.license_key = :p_license_key AND k.status = 'ACTIVE'""",
            {"p_license_key": license_key},
        )
        return r.first


def bound_to_another_machine(license_key: str, installation_id: str) -> bool:
    """True when the licence behind this key is node-locked to a different machine."""
    row = _key_binding(license_key)
    bound = row.get("VBS_MACHINE_ID") if row else None
    if not isinstance(bound, str) or bound.strip() == "":
        return False
    return bound.strip().upper() != installation_id.strip().upper()


def trial_already_used(license_key: str, installation_id: str) -> bool:
    """True when this computer already had a trial of the same product on another licence."""
    from ..services.trial_guard import assert_trial_allowed_for_license

    row = _key_binding(license_key)
    if row is None or row.get("LICENSE_ID") is None:
        return False
    try:
        with transaction() as conn:
            assert_trial_allowed_for_license(conn, int(row["LICENSE_ID"]), [installation_id])
        return False
    except AppError as e:
        if e.code == "TRIAL_ALREADY_USED":
            return True
        raise


def _out(row: Row | None, name: str) -> Any:
    """An OUT bind as the Node driver returned it: the column of the first row, else null."""
    if not row:
        return None
    return row.get(name.upper())


def _result_code(data: dict[str, Any]) -> str:
    if data.get("authorized"):
        return "AUTHORIZED"
    reason = data.get("reason")
    return reason if reason is not None else "DENIED"


def _query_str(request: Request, name: str) -> str:
    """`typeof req.query[name] === 'string' ? req.query[name] : ''` (a repeated key is an array)."""
    values = request.query_params.getlist(name)
    return values[0] if len(values) == 1 else ""


# ---------------------------------------------------------------------------
@router.post("/activate")
def activate(ctx: Ctx = Depends(client_ctx), body: Any = Depends(json_body)):
    started = _now_ms()
    client = ctx.api_client
    assert client is not None
    b = activate_schema.parse(body)
    assert_fresh_timestamp(b.get("timestamp"))

    if b["productCode"] != client.product_code:
        data = denied_payload("INVALID_PRODUCT")
    elif bound_to_another_machine(b["licenseKey"], b["installationId"]):
        # A node-locked Vehicle SIM key names its machine: no seat for a copy elsewhere.
        data = denied_payload("WRONG_MACHINE")
    elif trial_already_used(b["licenseKey"], b["installationId"]):
        # One trial per computer and product.
        data = denied_payload("TRIAL_ALREADY_USED")
    else:
        with transaction() as conn:
            r = conn.execute(
                """SELECT * FROM pkg_authorization.activate(
                     p_license_key     => :p_license_key,
                     p_product_id      => :p_product_id,
                     p_installation_id => :p_installation_id,
                     p_device_id       => :p_device_id,
                     p_fingerprint     => :p_fingerprint,
                     p_device_name     => :p_device_name,
                     p_os_info         => :p_os_info,
                     p_app_version     => :p_app_version,
                     p_ip_address      => :p_ip_address,
                     p_request_id      => :p_request_id)""",
                {
                    "p_license_key": b["licenseKey"],
                    "p_product_id": client.product_id,
                    "p_installation_id": b["installationId"],
                    "p_device_id": b.get("deviceId"),
                    "p_fingerprint": b.get("machineFingerprint"),
                    "p_device_name": b.get("deviceName"),
                    "p_os_info": b.get("os"),
                    "p_app_version": b.get("appVersion"),
                    "p_ip_address": ctx.ip,
                    "p_request_id": ctx.request_id,
                },
            )
            out = r.first
            grace_days = get_offline_grace_days(conn) if _out(out, "o_authorized") == "Y" else 0

        data = build_authorization(
            authorized=_out(out, "o_authorized"),
            reason=_out(out, "o_reason"),
            status=_out(out, "o_status"),
            activation_id=_out(out, "o_activation_id"),
            expiry_date=_out(out, "o_expiry_date"),
            max_activations=_out(out, "o_max_act"),
            current_activations=_out(out, "o_cur_act"),
            license_key=b["licenseKey"],
            installation_id=b["installationId"],
            grace_days=grace_days,
            signing_key=client.signing_key,
        )

    log_api_request(
        request_id=ctx.request_id,
        client_id=client.client_id,
        endpoint="/api/v1/license/activate",
        method="POST",
        license_key=b["licenseKey"],
        result_code=_result_code(data),
        http_status=200,
        ip=ctx.ip,
        duration_ms=_now_ms() - started,
    )
    return ok(data)


def _validate_handler(ctx: Ctx, body: Any, heartbeat: bool):
    started = _now_ms()
    client = ctx.api_client
    assert client is not None
    b = (heartbeat_schema if heartbeat else validate_schema).parse(body)
    assert_fresh_timestamp(b.get("timestamp"))

    if b["productCode"] != client.product_code:
        data = denied_payload("INVALID_PRODUCT")
    else:
        with transaction() as conn:
            r = conn.execute(VALIDATE_PLSQL, {
                "p_license_key": b["licenseKey"],
                "p_product_id": client.product_id,
                "p_installation_id": b["installationId"],
                "p_heartbeat": "Y" if heartbeat else "N",
                "p_app_version": b.get("appVersion"),
            })
            out = r.first
            grace_days = get_offline_grace_days(conn) if _out(out, "o_authorized") == "Y" else 0

        data = build_authorization(
            authorized=_out(out, "o_authorized"),
            reason=_out(out, "o_reason"),
            status=_out(out, "o_status"),
            expiry_date=_out(out, "o_expiry_date"),
            max_activations=_out(out, "o_max_act"),
            current_activations=_out(out, "o_cur_act"),
            license_key=b["licenseKey"],
            installation_id=b["installationId"],
            grace_days=grace_days,
            signing_key=client.signing_key,
        )

    log_api_request(
        request_id=ctx.request_id,
        client_id=client.client_id,
        endpoint="/api/v1/license/heartbeat" if heartbeat else "/api/v1/license/validate",
        method="POST",
        license_key=b["licenseKey"],
        result_code=_result_code(data),
        http_status=200,
        ip=ctx.ip,
        duration_ms=_now_ms() - started,
    )
    return ok(data)


@router.post("/validate")
def validate(ctx: Ctx = Depends(client_ctx), body: Any = Depends(json_body)):
    return _validate_handler(ctx, body, False)


@router.post("/heartbeat")
def heartbeat(ctx: Ctx = Depends(client_ctx), body: Any = Depends(json_body)):
    return _validate_handler(ctx, body, True)


@router.post("/deactivate")
def deactivate(ctx: Ctx = Depends(client_ctx), body: Any = Depends(json_body)):
    started = _now_ms()
    client = ctx.api_client
    assert client is not None
    b = validate_schema.parse(body)
    assert_fresh_timestamp(b.get("timestamp"))

    deactivated = False
    reason: str | None = None
    if b["productCode"] != client.product_code:
        reason = "INVALID_PRODUCT"
    else:
        with transaction() as conn:
            r = conn.execute(
                """SELECT * FROM pkg_authorization.deactivate(
                     p_license_key     => :p_license_key,
                     p_product_id      => :p_product_id,
                     p_installation_id => :p_installation_id,
                     p_request_id      => :p_request_id)""",
                {
                    "p_license_key": b["licenseKey"],
                    "p_product_id": client.product_id,
                    "p_installation_id": b["installationId"],
                    "p_request_id": ctx.request_id,
                },
            )
            out = r.first
        deactivated = _out(out, "o_success") == "Y"
        o_reason = _out(out, "o_reason")
        reason = None if deactivated else (o_reason if isinstance(o_reason, str) else "INVALID_LICENSE")

    log_api_request(
        request_id=ctx.request_id,
        client_id=client.client_id,
        endpoint="/api/v1/license/deactivate",
        method="POST",
        license_key=b["licenseKey"],
        result_code="DEACTIVATED" if deactivated else (reason if reason is not None else "DENIED"),
        http_status=200,
        ip=ctx.ip,
        duration_ms=_now_ms() - started,
    )
    return ok({"deactivated": deactivated, "reason": reason})


@router.get("/info")
def info(ctx: Ctx = Depends(client_ctx)):
    started = _now_ms()
    client = ctx.api_client
    assert client is not None
    license_key = _query_str(ctx.request, "licenseKey")
    product_code = _query_str(ctx.request, "productCode")
    if not is_license_key_shape(license_key):
        raise AppError(400, "VALIDATION_ERROR", "licenseKey is missing or malformed.")
    if product_code != client.product_code:
        raise AppError(400, "INVALID_PRODUCT", "License does not belong to this product.")

    with transaction() as conn:
        r = conn.execute(
            """SELECT l.status, l.start_date, l.expiry_date, l.max_activations, l.current_activations,
                      pp.plan_code, pp.plan_name, p.product_code, p.product_name,
                      c.company_name, k.status AS key_status
                 FROM license_keys k
                 JOIN licenses l       ON l.license_id = k.license_id
                 JOIN product_plans pp ON pp.plan_id = l.plan_id
                 JOIN products p       ON p.product_id = l.product_id
                 JOIN customers c      ON c.customer_id = l.customer_id
                WHERE k.license_key = :p_license_key
                  AND l.product_id = :p_product_id""",
            {"p_license_key": license_key, "p_product_id": client.product_id},
        )
        row = r.first

    log_api_request(
        request_id=ctx.request_id,
        client_id=client.client_id,
        endpoint="/api/v1/license/info",
        method="GET",
        license_key=license_key,
        result_code="OK" if row else "NOT_FOUND",
        http_status=200 if row else 404,
        ip=ctx.ip,
        duration_ms=_now_ms() - started,
    )

    if not row:
        raise AppError(404, "NOT_FOUND", "License not found.")
    c = to_camel(row)
    from datetime import date as _date

    sd, ed = row.get("START_DATE"), row.get("EXPIRY_DATE")
    return ok({
        "status": c.get("status", UNDEFINED),
        "keyStatus": c.get("keyStatus", UNDEFINED),
        "productCode": c.get("productCode", UNDEFINED),
        "productName": c.get("productName", UNDEFINED),
        "planCode": c.get("planCode", UNDEFINED),
        "planName": c.get("planName", UNDEFINED),
        "companyName": c.get("companyName", UNDEFINED),
        "startDate": fmt_date_only(sd) if isinstance(sd, _date) else None,
        "expiryDate": fmt_date_only(ed) if isinstance(ed, _date) else None,
        "maxActivations": c.get("maxActivations", UNDEFINED),
        "currentActivations": c.get("currentActivations", UNDEFINED),
    })


def _stream_row(license_key: str, installation_id: str, product_id: int) -> Row | None:
    with transaction() as conn:
        r = conn.execute(
            """SELECT l.license_id, l.status, a.status AS activation_status
                 FROM license_keys k
                 JOIN licenses l ON l.license_id = k.license_id
                 LEFT JOIN license_activations a
                        ON a.license_id = l.license_id
                       AND a.installation_id = :p_installation_id
                       AND a.status = 'ACTIVE'
                WHERE k.license_key = :p_license_key
                  AND k.status = 'ACTIVE'
                  AND l.product_id = :p_product_id""",
            {
                "p_license_key": license_key,
                "p_installation_id": installation_id,
                "p_product_id": product_id,
            },
        )
        return r.first


def _js_string(v: Any) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)


@router.get("/stream")
async def stream(ctx: Ctx = Depends(client_ctx)):
    """
    Live enforcement stream (Server-Sent Events):
      GET /api/v1/license/stream?licenseKey=...&installationId=...
    Every frame carries `serverTime`, the product's trusted clock.
    """
    client = ctx.api_client
    assert client is not None
    license_key = _query_str(ctx.request, "licenseKey")
    installation_id = _query_str(ctx.request, "installationId")

    if not is_license_key_shape(license_key):
        raise AppError(400, "VALIDATION_ERROR", "licenseKey is missing or malformed.")
    if not installation_id:
        raise AppError(400, "VALIDATION_ERROR", "installationId is required.")

    # Only an ACTIVE licence of this client's product, with this installation activated.
    row = await run_in_threadpool(_stream_row, license_key, installation_id, client.product_id)

    if not row:
        raise AppError(404, "INVALID_LICENSE", "License not found for this product.")
    if row.get("STATUS") != "ACTIVE":
        raise AppError(403, "LICENSE_NOT_ACTIVE", f"License is {_js_string(row.get('STATUS'))}.")
    if row.get("ACTIVATION_STATUS") != "ACTIVE":
        raise AppError(403, "INVALID_ACTIVATION", "This installation is not activated.")

    license_id = int(row["LICENSE_ID"])
    sub = live_channel.subscribe(license_id, installation_id)

    log_api_request(
        request_id=ctx.request_id,
        client_id=client.client_id,
        endpoint="/api/v1/license/stream",
        method="GET",
        license_key=license_key,
        result_code="STREAM_OPEN",
        http_status=200,
        ip=ctx.ip,
        duration_ms=0,
    )

    return StreamingResponse(
        live_channel.stream(sub),
        status_code=200,
        media_type=None,
        headers={
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            # Tells nginx and friends not to buffer, which would defeat the point.
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/time")
def server_time(ctx: Ctx = Depends(client_ctx)):
    """The server's current time — the installed app's trusted clock.
    With ?installationId=..., also says whether an administrator has reactivated
    that installation after a clock block (the app then calls /clock-reactivate)."""
    data: dict[str, Any] = {"serverTime": now_iso()}
    inst = ctx.request.query_params.get("installationId")
    if isinstance(inst, str) and inst.strip():
        from ..services.clock_reactivation import pending_admin_release

        client = ctx.api_client
        assert client is not None
        with transaction() as conn:
            data["clockReleasePending"] = pending_admin_release(conn, client.product_id, inst.strip()[:100]) is not None
    return ok(data)


clock_reactivate_schema = z.object({
    "productCode": z.string().min(1).max(30),
    "installationId": z.string().min(1).max(100),
    "localTime": z.string().min(1).max(40),
    "licenseKey": z.string().max(600).nullish(),
    "deviceName": z.string().max(150).nullish(),
})


@router.post("/clock-reactivate")
def clock_reactivate(ctx: Ctx = Depends(client_ctx), body: Any = Depends(json_body)):
    """The app asks to be reactivated after a clock block. The server's time decides."""
    from ..services.clock_reactivation import app_reactivate

    started = _now_ms()
    client = ctx.api_client
    assert client is not None
    b = clock_reactivate_schema.parse(body)
    if b["productCode"] != client.product_code:
        raise AppError(400, "INVALID_PRODUCT", "This client is not registered for that product.")
    with transaction() as conn:
        result = app_reactivate(conn, product_id=client.product_id, installation_id=b["installationId"],
                                local_time=b["localTime"], ip=ctx.ip, request_id=ctx.request_id)
    log_api_request(
        request_id=ctx.request_id, client_id=client.client_id, endpoint="/api/v1/license/clock-reactivate",
        method="POST", license_key=b.get("licenseKey"),
        result_code="CLOCK_REACTIVATED" if result["reactivated"] else "CLOCK_STILL_WRONG",
        http_status=200, ip=ctx.ip, duration_ms=_now_ms() - started,
    )
    return ok(result)


clock_alert_schema = z.object({
    "productCode": z.string().min(1).max(30),
    "installationId": z.string().min(1).max(100),
    "licenseKey": z.string().max(600).nullish(),
    "kind": z.enum(["MOVED_BACK", "MOVED_FORWARD", "WRONG_TIME"]),
    "localTime": z.string().max(40).nullish(),
    "referenceTime": z.string().max(40).nullish(),
    "deltaSeconds": z.number().finite().nullish(),
    "deviceName": z.string().max(150).nullish(),
    "appVersion": z.string().max(30).nullish(),
    "timestamp": z.string().max(40).optional(),
})


@router.post("/clock-alert")
def clock_alert(ctx: Ctx = Depends(client_ctx), body: Any = Depends(json_body)):
    """The app reports that the computer's date/time was changed; the portal raises a CRITICAL alert."""
    from ..services.clock_alert import record_clock_alert

    started = _now_ms()
    client = ctx.api_client
    assert client is not None
    b = clock_alert_schema.parse(body)
    if b["productCode"] != client.product_code:
        raise AppError(400, "INVALID_PRODUCT", "This client is not registered for that product.")
    with transaction() as conn:
        result = record_clock_alert(conn, {
            "productId": client.product_id,
            "productCode": client.product_code,
            "installationId": b["installationId"],
            "licenseKey": b.get("licenseKey"),
            "kind": b["kind"],
            "localTime": b.get("localTime"),
            "referenceTime": b.get("referenceTime"),
            "deltaSeconds": b.get("deltaSeconds"),
            "deviceName": b.get("deviceName"),
            "appVersion": b.get("appVersion"),
            "ip": ctx.ip,
            "requestId": ctx.request_id,
        })
    log_api_request(
        request_id=ctx.request_id,
        client_id=client.client_id,
        endpoint="/api/v1/license/clock-alert",
        method="POST",
        license_key=b.get("licenseKey"),
        result_code="CLOCK_TAMPER",
        http_status=200,
        ip=ctx.ip,
        duration_ms=_now_ms() - started,
    )
    recorded = result.get("recorded", UNDEFINED) if isinstance(result, dict) else UNDEFINED
    return ok({"received": True, "recorded": recorded, "serverTime": now_iso()})


# ---------------------------------------------------------------------------
# Short typed key -> signed key for this computer
# ---------------------------------------------------------------------------
redeem_schema = z.object({
    "productCode": z.string().min(1).max(30),
    "licenseKey": z.string().trim().to_upper().regex(r"^[A-Z]{2,6}(-[A-Z0-9]{4}){3}$", "Invalid license key format"),
    "installationId": z.string().trim().min(8).max(100),
    "deviceName": z.string().max(150).nullish(),
})


@router.post("/redeem-key")
def redeem_key(ctx: Ctx = Depends(client_ctx), body: Any = Depends(json_body)):
    """
    For apps that run on signed keys (Vehicle SIM, KSTACK): the customer types the short
    licence key (PREFIX-XXXX-XXXX-XXXX) shown in the portal; the server exchanges it for the
    signed key bound to this computer (same grant as the licence) and retires the short key.
    The same computer asking again gets its signed key back; another computer is refused.
    """
    from ..services.audit import log_audit
    from ..services.vbs_issue import issue_vbs_key_for_license
    from ..services.vbs_key import VBS_FEATURES

    started = _now_ms()
    client = ctx.api_client
    assert client is not None
    b = redeem_schema.parse(body)
    if b["productCode"].upper() != client.product_code:
        raise AppError(400, "INVALID_PRODUCT", "This client is not registered for that product.")
    machine = b["installationId"].upper()
    with transaction() as conn:
        row = conn.execute(
            """SELECT k.status AS key_status, l.license_id, l.license_no, l.status, l.expiry_date,
                      l.vbs_mode, l.vbs_edition, l.vbs_features, l.vbs_machine_id, p.key_format
                 FROM license_keys k
                 JOIN licenses l ON l.license_id = k.license_id
                 JOIN products p ON p.product_id = l.product_id
                WHERE k.license_key = :p_key AND l.product_id = :p_product
                ORDER BY k.generated_at DESC LIMIT 1""",
            {"p_key": b["licenseKey"], "p_product": client.product_id},
        ).first
        if not row:
            raise AppError(404, "INVALID_LICENSE", "This licence key is not known for this product. Check it and try again.")
        if row["KEY_FORMAT"] != "VBS_KEY":
            raise AppError(400, "VALIDATION_ERROR", "This product does not use signed licence keys.")
        if row["STATUS"] in ("REVOKED", "SUSPENDED", "EXPIRED", "CANCELLED"):
            code = {"REVOKED": "LICENSE_REVOKED", "SUSPENDED": "LICENSE_SUSPENDED", "EXPIRED": "LICENSE_EXPIRED"}.get(row["STATUS"], "LICENSE_NOT_ACTIVE")
            raise AppError(409, code, f"This licence is {str(row['STATUS']).lower()}. Please contact Karnex.")
        lid = int(row["LICENSE_ID"])
        bound = (row["VBS_MACHINE_ID"] or "").strip().upper()
        if row["KEY_STATUS"] != "ACTIVE":
            # Already exchanged: only the computer it was exchanged for gets its key again.
            if bound and bound == machine:
                cur = conn.execute(
                    "SELECT license_key FROM license_keys WHERE license_id = :p_id AND status = 'ACTIVE'",
                    {"p_id": lid},
                ).first
                if cur and not LICENSE_KEY_RE.match(str(cur["LICENSE_KEY"])):
                    return ok({"licenseKey": cur["LICENSE_KEY"], "licenceNo": row["LICENSE_NO"],
                               "expiry": fmt_date_only(row["EXPIRY_DATE"]) if row["EXPIRY_DATE"] else None,
                               "redeemed": False})
            raise AppError(409, "KEY_REVOKED",
                           "This licence key has already been used on another computer. Ask Karnex for a new key.")
        if row["STATUS"] not in ("ACTIVE", "DRAFT"):
            raise AppError(409, "LICENSE_NOT_ACTIVE", "This licence is not active. Please contact Karnex.")
        mode = row["VBS_MODE"]
        if mode is None:
            mode = 1 if row["EXPIRY_DATE"] else 0
        edition = row["VBS_EDITION"] if row["VBS_EDITION"] is not None else 2
        mask = row["VBS_FEATURES"]
        features = [n for n, bit in VBS_FEATURES.items() if mask is None or int(mask) & int(bit)]
        issued = issue_vbs_key_for_license(conn, lid, {
            "mode": int(mode), "edition": int(edition), "features": features,
            "machineId": machine, "keyVersion": "V3",
        }, None)
        log_audit(conn, actor="PRODUCT_CLIENT", action="KEY_REDEEMED", entity_type="LICENSE", entity_id=lid,
                  request_id=ctx.request_id, ip=ctx.ip,
                  after={"machineId": machine, "deviceName": b.get("deviceName"), "productCode": client.product_code})
    log_api_request(request_id=ctx.request_id, client_id=client.client_id, endpoint="/api/v1/license/redeem-key",
                    method="POST", license_key=b["licenseKey"], result_code="KEY_REDEEMED", http_status=200,
                    ip=ctx.ip, duration_ms=_now_ms() - started)
    return ok({"licenseKey": issued["licenseKey"], "licenceNo": issued["licenceNo"], "expiry": issued["expiry"],
               "redeemed": True})
