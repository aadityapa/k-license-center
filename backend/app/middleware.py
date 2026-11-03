"""
ASGI middleware: request id, security headers, rate limits and request logging.

Order (outermost first) mirrors the previous server:
  CoreMiddleware (request id, helmet headers, log)  ->  CORS  ->  LimitMiddleware  ->  routes
"""
from __future__ import annotations

import json
import time
import uuid

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .config import config
from .logger import logger
from .ratelimit import Limiter
from .respond import dumps, request_id_var

# helmet() defaults
SECURITY_HEADERS: list[tuple[bytes, bytes]] = [
    (b"content-security-policy",
     b"default-src 'self';base-uri 'self';font-src 'self' https: data:;form-action 'self';"
     b"frame-ancestors 'self';img-src 'self' data:;object-src 'none';script-src 'self';"
     b"script-src-attr 'none';style-src 'self' https: 'unsafe-inline';upgrade-insecure-requests"),
    (b"cross-origin-opener-policy", b"same-origin"),
    (b"cross-origin-resource-policy", b"same-origin"),
    (b"origin-agent-cluster", b"?1"),
    (b"referrer-policy", b"no-referrer"),
    (b"strict-transport-security", b"max-age=15552000; includeSubDomains"),
    (b"x-content-type-options", b"nosniff"),
    (b"x-dns-prefetch-control", b"off"),
    (b"x-download-options", b"noopen"),
    (b"x-frame-options", b"SAMEORIGIN"),
    (b"x-permitted-cross-domain-policies", b"none"),
    (b"x-xss-protection", b"0"),
]


def _client_ip(scope: Scope) -> str:
    for k, v in scope.get("headers") or []:
        if k == b"x-forwarded-for":
            parts = [p.strip() for p in v.decode("latin-1").split(",") if p.strip()]
            if parts:
                return parts[-1]
    c = scope.get("client")
    return c[0] if c else "unknown"


def _header(scope: Scope, name: bytes) -> str | None:
    for k, v in scope.get("headers") or []:
        if k == name:
            return v.decode("latin-1")
    return None


class CoreMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        rid = str(uuid.uuid4())
        token = request_id_var.set(rid)
        scope.setdefault("state", {})["request_id"] = rid
        # Express routing ignores a trailing slash: /api/v1/users/ == /api/v1/users
        path: str = scope.get("path", "")
        if len(path) > 1 and path.endswith("/"):
            scope["path"] = path.rstrip("/") or "/"
        started = time.monotonic()
        status_holder = {"status": 0}

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
                headers = list(message.get("headers") or [])
                existing = {k.lower() for k, _ in headers}
                for k, v in SECURITY_HEADERS:
                    if k not in existing:
                        headers.append((k, v))
                headers.append((b"x-request-id", rid.encode()))
                if b"access-control-expose-headers" not in existing:
                    headers.append((b"access-control-expose-headers", b"X-Request-Id"))
                for k, v in scope["state"].get("rl_headers", []):
                    headers.append((k, v))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            logger.info(
                "request completed",
                requestId=rid,
                method=scope.get("method"),
                # path only: query strings can carry license keys and must not be logged
                path=path,
                status=status_holder["status"],
                durationMs=int((time.monotonic() - started) * 1000),
            )
            request_id_var.reset(token)


BODY_LIMIT = 100 * 1024


class JsonBodyMiddleware:
    """
    express.json(): parses a JSON request body before routing and authentication,
    so malformed JSON is a 400 even for a request that would then fail sign-in.
    The parsed value is left in scope["state"]["json_body"] for deps.json_body,
    and the raw bytes are replayed to the app unchanged.
    """

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        ctype = (_header(scope, b"content-type") or "").split(";")[0].strip().lower()
        if not (ctype == "application/json" or ctype.endswith("+json")):
            await self.app(scope, receive, send)
            return
        chunks: list[bytes] = []
        size = 0
        too_large = False
        more = True
        while more:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body = message.get("body", b"")
            size += len(body)
            if size > BODY_LIMIT:
                too_large = True
            elif body:
                chunks.append(body)
            more = message.get("more_body", False)
        raw = b"".join(chunks)
        state = scope.setdefault("state", {})
        error: str | None = None
        if too_large:
            error = "Request body exceeds the allowed size."
        elif raw.strip():
            try:
                val = json.loads(raw.decode("utf-8"))
                # body-parser's strict mode accepts only objects and arrays.
                if not isinstance(val, (dict, list)):
                    raise ValueError
                state["json_body"] = val
            except (ValueError, UnicodeDecodeError):
                error = "Request body is not valid JSON."
        else:
            state["json_body"] = {}
        if error is not None:
            await _reject(scope, send, {"code": "VALIDATION_ERROR", "message": error}, status=400)
            return

        sent = False

        async def replay() -> Message:
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": raw, "more_body": False}
            return await receive()

        await self.app(scope, replay, send)


_RATE_LIMITED = {"code": "RATE_LIMITED", "message": "Too many requests. Please try again later."}


class LimitMiddleware:
    """Global limiter (every request) and the product-API limiter (per client key)."""

    def __init__(self, app: ASGIApp):
        self.app = app
        rl = config.rate_limit
        assert rl is not None
        self.global_limiter = Limiter(rl.window_ms, rl.max)
        self.license_limiter = Limiter(rl.license_window_ms, rl.license_max)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        state = scope.setdefault("state", {})
        ip = _client_ip(scope)
        hit = self.global_limiter.hit(ip)
        state["rl_headers"] = hit.headers()
        if not hit.allowed:
            await _reject(scope, send)
            return
        path = scope.get("path", "")
        if path == "/api/v1/license" or path.startswith("/api/v1/license/"):
            key = _header(scope, b"x-client-key") or ip
            h2 = self.license_limiter.hit(key)
            state["rl_headers"] = h2.headers()
            if not h2.allowed:
                await _reject(scope, send)
                return
        await self.app(scope, receive, send)


async def _reject(scope: Scope, send: Send, error: dict | None = None, status: int = 429) -> None:
    body = dumps({"success": False, "error": error or _RATE_LIMITED,
                  "requestId": scope.get("state", {}).get("request_id")}).encode()
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"application/json; charset=utf-8"),
                            (b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})
