"""
Per-request context and the FastAPI dependencies that build it.

Route handlers are plain (synchronous) functions taking a `Ctx`:

    @router.get("/{id}")
    def get_one(id: str, ctx: Ctx = Depends(require("CUSTOMER_VIEW"))):
        ...

    @router.post("")
    def create(ctx: Ctx = Depends(require("CUSTOMER_MANAGE")), body: Any = Depends(json_body)):
        data = create_schema.parse(body)

`require(perm)` authenticates the admin (Bearer JWT) and checks one permission;
`admin_ctx` only authenticates; `client_ctx` authenticates a product API client
(X-Client-Key / X-Client-Secret); `public_ctx` is the anonymous context.
"""
from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

import jwt
from fastapi import Request

from .config import config
from .db import transaction
from .errors import AppError
from .logger import logger
from .respond import request_id_var
from .security import DUMMY_HASH, check_password, decode_token
from .services.session_revocation import is_revoked

# Every permission in the system — used only by the AUTH_DISABLED demo bypass.
ALL_PERMISSIONS = [
    "DASHBOARD_VIEW", "PRODUCT_VIEW", "PRODUCT_MANAGE", "PLAN_MANAGE",
    "CUSTOMER_VIEW", "CUSTOMER_MANAGE", "LICENSE_VIEW", "LICENSE_CREATE",
    "LICENSE_MANAGE", "LICENSE_REVOKE", "ACTIVATION_MANAGE", "APICLIENT_MANAGE",
    "USER_MANAGE", "AUDIT_VIEW", "SETTINGS_MANAGE",
    "REQUEST_VIEW", "REQUEST_APPROVE", "APPROVAL_BYPASS",
    "REQUEST_LICENSE_VIEW", "REQUEST_LICENSE_MANAGE", "EMAIL_OUTBOX_VIEW",
]


@dataclass
class User:
    user_id: int
    username: str
    permissions: list[str]


@dataclass
class ApiClient:
    client_id: int
    product_id: int
    product_code: str
    signing_key: str


@dataclass
class Ctx:
    request: Request
    request_id: str
    user: User | None = None
    api_client: ApiClient | None = None
    started: float = field(default_factory=time.monotonic)

    @property
    def ip(self) -> str | None:
        return client_ip(self.request)

    def has(self, perm: str) -> bool:
        return self.user is not None and perm in self.user.permissions

    @property
    def query(self) -> dict[str, str]:
        return dict(self.request.query_params)

    def header(self, name: str) -> str | None:
        return self.request.headers.get(name)


def client_ip(request: Request) -> str | None:
    """Express `req.ip` with 'trust proxy' = 1: the last X-Forwarded-For hop, else the peer."""
    xff = request.headers.get("x-forwarded-for")
    if xff:
        parts = [p.strip() for p in xff.split(",") if p.strip()]
        if parts:
            return parts[-1]
    return request.client.host if request.client else None


def _rid(request: Request) -> str:
    rid = getattr(request.state, "request_id", None) or request_id_var.get() or ""
    return rid


def public_ctx(request: Request) -> Ctx:
    return Ctx(request=request, request_id=_rid(request))


def authenticate(request: Request) -> User:
    if config.auth_disabled:
        return User(user_id=1, username="admin", permissions=list(ALL_PERMISSIONS))
    header = request.headers.get("authorization")
    if not header or not header.startswith("Bearer "):
        raise AppError(401, "UNAUTHORIZED", "Missing or malformed Authorization header.")
    try:
        decoded = decode_token(header[7:])
    except jwt.PyJWTError:
        raise AppError(401, "UNAUTHORIZED", "Invalid or expired token.") from None
    try:
        user_id = int(str(decoded.get("sub")))
    except (TypeError, ValueError):
        user_id = 0
    if user_id <= 0:
        raise AppError(401, "UNAUTHORIZED", "Invalid token payload.")
    iat = decoded.get("iat")
    if is_revoked(user_id, iat if isinstance(iat, int) else None):
        raise AppError(401, "UNAUTHORIZED", "Your session has ended. Please sign in again.")
    perms = decoded.get("permissions")
    return User(
        user_id=user_id,
        username=decoded.get("username") if isinstance(decoded.get("username"), str) else "",
        permissions=[str(p) for p in perms] if isinstance(perms, list) else [],
    )


def admin_ctx(request: Request) -> Ctx:
    return Ctx(request=request, request_id=_rid(request), user=authenticate(request))


def require(perm: str) -> Callable[[Request], Ctx]:
    """Dependency: an authenticated admin holding `perm`."""

    def dep(request: Request) -> Ctx:
        ctx = admin_ctx(request)
        if perm not in ctx.user.permissions:  # type: ignore[union-attr]
            raise AppError(403, "FORBIDDEN", f"Missing required permission: {perm}.")
        return ctx

    dep.__name__ = f"require_{perm}"
    return dep


def check_perm(ctx: Ctx, perm: str) -> None:
    if not ctx.has(perm):
        raise AppError(403, "FORBIDDEN", f"Missing required permission: {perm}.")


# ---------------------------------------------------------------------------
# Product API clients
# ---------------------------------------------------------------------------
_LAST_USED_THROTTLE_S = 60.0
_last_touched: dict[int, float] = {}
_touch_lock = threading.Lock()


def _touch_last_used(client_id: int) -> None:
    now = time.monotonic()
    with _touch_lock:
        if _last_touched.get(client_id, -1e18) > now - _LAST_USED_THROTTLE_S:
            return
        _last_touched[client_id] = now

    def run() -> None:
        try:
            with transaction() as conn:
                conn.execute("UPDATE api_clients SET last_used_at = now() WHERE client_id = :p_client_id",
                             {"p_client_id": client_id})
        except Exception:
            logger.warn("failed to update api client last_used_at", clientId=client_id)

    threading.Thread(target=run, daemon=True).start()


def authenticate_client(request: Request) -> ApiClient:
    key = request.headers.get("x-client-key")
    secret = request.headers.get("x-client-secret")
    if not key or not secret:
        raise AppError(401, "UNAUTHORIZED_CLIENT", "Missing client credentials.")
    with transaction() as conn:
        r = conn.execute(
            """SELECT c.client_id, c.product_id, c.secret_hash, c.signing_key, c.status, p.product_code
                 FROM api_clients c
                 JOIN products p ON p.product_id = c.product_id
                WHERE c.client_key = :p_client_key""",
            {"p_client_key": key},
        )
    row = r.first
    secret_ok = check_password(secret, str(row["SECRET_HASH"]) if row else DUMMY_HASH)
    if not row or not secret_ok or row["STATUS"] != "ACTIVE":
        raise AppError(401, "UNAUTHORIZED_CLIENT", "Invalid client credentials.")
    client = ApiClient(
        client_id=int(row["CLIENT_ID"]),
        product_id=int(row["PRODUCT_ID"]),
        product_code=str(row["PRODUCT_CODE"]),
        signing_key=str(row["SIGNING_KEY"]),
    )
    _touch_last_used(client.client_id)
    return client


def client_ctx(request: Request) -> Ctx:
    return Ctx(request=request, request_id=_rid(request), api_client=authenticate_client(request))


# ---------------------------------------------------------------------------
# JSON body (express.json(): 100 kB limit, {} when the body is not JSON)
# ---------------------------------------------------------------------------
BODY_LIMIT = 100 * 1024


async def json_body(request: Request) -> Any:
    """The JSON body, parsed by middleware.JsonBodyMiddleware ({} when there is none)."""
    state = request.scope.get("state") or {}
    if "json_body" in state:
        return state["json_body"]
    return {}
