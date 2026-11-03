"""
The response envelope, identical to the previous API:

    { "success": true,  "data": ...,                         "requestId": "..." }
    { "success": false, "error": { "code": "...", "message": "..." }, "requestId": "..." }

JSON encoding follows JavaScript's JSON.stringify of the old driver's values:
timestamps -> ISO-8601 UTC with milliseconds ("2026-10-27T10:00:00.000Z"),
DATE -> local midnight as ISO UTC (what node-postgres produced), NUMERIC ->
plain numbers (25000, not 25000.0).
"""
from __future__ import annotations

import contextvars
import json
import math
from datetime import date, datetime, time, timezone
from decimal import Decimal
from typing import Any

from starlette.responses import Response

request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("request_id", default=None)


def iso(dt: datetime) -> str:
    """JavaScript Date.toISOString()."""
    if dt.tzinfo is None:
        dt = dt.astimezone()  # naive = local time
    u = dt.astimezone(timezone.utc)
    return u.strftime("%Y-%m-%dT%H:%M:%S.") + f"{u.microsecond // 1000:03d}Z"


def now_iso() -> str:
    return iso(datetime.now(timezone.utc))


def date_iso(d: date) -> str:
    """A DATE value as node-postgres + JSON.stringify rendered it: local midnight, in UTC."""
    return iso(datetime.combine(d, time(0)).astimezone())


def to_jsonable(v: Any) -> Any:
    if v is None or isinstance(v, (str, bool, int)):
        return v
    if isinstance(v, float):
        if math.isnan(v) or math.isinf(v):
            return None
        if v.is_integer() and abs(v) < 1e21:
            # JavaScript prints whole numbers without exponent up to 1e21, using the
            # shortest round-trip digits (1.2345678901234567e+19 -> 12345678901234567000).
            return int(v) if abs(v) < 2**53 else int(Decimal(repr(v)))
        return v
    if isinstance(v, Decimal):
        return int(v) if v == v.to_integral_value() else float(v)
    if isinstance(v, datetime):
        return iso(v)
    if isinstance(v, date):
        return date_iso(v)
    if isinstance(v, dict):
        return {str(k): to_jsonable(x) for k, x in v.items() if x is not _UNDEFINED}
    if isinstance(v, (list, tuple, set)):
        return [to_jsonable(x) for x in v]
    if isinstance(v, bytes):
        return v.decode("utf-8", "replace")
    return str(v)


class _Undefined:
    """A dict value that is dropped from JSON, like `undefined` in JavaScript."""

    def __repr__(self) -> str:  # pragma: no cover
        return "UNDEFINED"


_UNDEFINED = _Undefined()
UNDEFINED = _UNDEFINED


def dumps(v: Any) -> str:
    """JSON.stringify equivalent (compact)."""
    return json.dumps(to_jsonable(v), ensure_ascii=False, separators=(",", ":"))


class JSONResponse(Response):
    media_type = "application/json; charset=utf-8"

    def render(self, content: Any) -> bytes:
        return dumps(content).encode("utf-8")


def ok(data: Any, status: int = 200) -> JSONResponse:
    return JSONResponse({"success": True, "data": data, "requestId": request_id_var.get()}, status_code=status)


def pending_approval(change_request_id: int | None, summary: str) -> JSONResponse:
    """202 for a governed mutation queued for a checker instead of being applied."""
    data: dict[str, Any] = {"pendingApproval": True, "message": f"{summary} submitted for approval."}
    if change_request_id is not None:
        data = {"pendingApproval": True, "changeRequestId": change_request_id, "message": data["message"]}
    return ok(data, 202)


def fail(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        {"success": False, "error": {"code": code, "message": message}, "requestId": request_id_var.get()},
        status_code=status,
    )
