"""
K License Authorization System — REST API (FastAPI + PostgreSQL).

Run:  python run.py           (or: uvicorn app.main:app --port 3001)
"""
from __future__ import annotations

import re
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.cors import CORSMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send

from .config import config
from .db import close_pool, execute, init_pool
from .errors import AppError, db_error_code, to_app_error
from .jobs import start_expiry_job, stop_expiry_job
from .logger import logger
from .middleware import CoreMiddleware, JsonBodyMiddleware, LimitMiddleware
from .respond import JSONResponse, fail, ok, request_id_var


def _check_production_database() -> None:
    """Refuse to serve customers with published default passwords or demo data (services/prod_guard)."""
    from .db import connect_raw
    from .services.prod_guard import assert_production_ready

    with connect_raw() as conn:
        assert_production_ready(conn)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if config.auth_disabled:
        logger.warn("*** AUTH_DISABLED enabled — login is bypassed, every request acts as admin. NOT for production ***")
    await run_in_threadpool(init_pool)
    if config.env == "production":
        await run_in_threadpool(_check_production_database)
    start_expiry_job()
    logger.info("K License API listening", port=config.port, env=config.env)
    try:
        yield
    finally:
        stop_expiry_job()
        await run_in_threadpool(close_pool)


# Admin sections whose whole router required one permission (router.use(requirePermission)):
# an unknown path inside them answered 403 before 404.
_ROUTER_PERMISSION = {
    "activations": "ACTIVATION_MANAGE", "api-clients": "APICLIENT_MANAGE",
    "api-logs": "AUDIT_VIEW", "audit-logs": "AUDIT_VIEW", "dashboard": "DASHBOARD_VIEW",
    "license-keys": "LICENSE_VIEW", "renewals": "LICENSE_VIEW", "roles": "USER_MANAGE",
    "permissions": "USER_MANAGE", "settings": "SETTINGS_MANAGE", "users": "USER_MANAGE",
}


class ErrorMiddleware:
    """Innermost: turns any unhandled exception into the standard error envelope."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = {"v": False}

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                started["v"] = True
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception as err:  # noqa: BLE001
            app_err = to_app_error(err)
            if app_err.status >= 500:
                logger.error("request failed", exc=True, requestId=request_id_var.get())
            if started["v"]:
                return
            resp = fail(app_err.status, app_err.code, app_err.message)
            await resp(scope, receive, send)


def create_app() -> FastAPI:
    app = FastAPI(
        title="K License API",
        lifespan=lifespan,
        docs_url=None, redoc_url=None, openapi_url=None,
        redirect_slashes=False,
        default_response_class=JSONResponse,
    )

    @app.exception_handler(AppError)
    async def _app_error(_request: Request, exc: AppError):
        return fail(exc.status, exc.code, exc.message)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException):
        if exc.status_code in (404, 405):
            # Express ran the router's guards before deciding "no such route".
            path = request.url.path
            try:
                if path.startswith("/api/v1/admin/") or path == "/api/v1/admin":
                    from .deps import authenticate

                    user = authenticate(request)
                    section = path[len("/api/v1/admin/"):].split("/")[0]
                    perm = _ROUTER_PERMISSION.get(section)
                    if perm and perm not in user.permissions:
                        raise AppError(403, "FORBIDDEN", f"Missing required permission: {perm}.")
                elif path.startswith("/api/v1/license/") or path == "/api/v1/license":
                    from .deps import authenticate_client

                    await run_in_threadpool(authenticate_client, request)
            except AppError as e:
                return fail(e.status, e.code, e.message)
            return fail(404, "NOT_FOUND", "Resource not found.")
        return fail(exc.status_code, "INTERNAL_ERROR" if exc.status_code >= 500 else "VALIDATION_ERROR", str(exc.detail))

    from fastapi.exceptions import RequestValidationError

    @app.exception_handler(RequestValidationError)
    async def _validation(_request: Request, exc: RequestValidationError):
        detail = "; ".join(
            f"{'.'.join(str(p) for p in e.get('loc', [])[1:]) or 'body'}: {e.get('msg')}" for e in exc.errors()
        )
        return fail(400, "VALIDATION_ERROR", detail or "Invalid request.")

    @app.get("/health")
    def health():
        return ok({"status": "up"})

    @app.get("/health/db")
    def health_db():
        try:
            execute("SELECT COUNT(*) AS n FROM users", {})
            return ok({"db": "up", "schema": "ok"})
        except Exception as err:  # noqa: BLE001
            code, msg = db_error_code(err)
            text = f"{code} {msg} {err}"
            logger.error("DB health check failed", exc=True)
            if code == "42P01":
                m = "Connected, but the tables are missing — run database/postgres/run_all.sql (or python -m scripts.db_migrate)."
            elif code in ("28P01", "28000"):
                m = "PostgreSQL rejected the credentials — check DB_USER/DB_PASSWORD in .env."
            elif code == "3D000":
                m = "The database named in DB_NAME does not exist — create it in pgAdmin first."
            elif re.search(r"refused|could not translate|timeout|timed out|connection", text, re.I):
                m = "Cannot reach PostgreSQL — check DB_HOST/DB_PORT and that the service is running."
            else:
                m = "Database check failed — see server logs."
            return fail(503, "DB_UNAVAILABLE", m)

    from .routes import admin, auth, license, public

    app.include_router(public.router, prefix="/api/v1/public")
    app.include_router(auth.router, prefix="/api/v1/auth")
    app.include_router(license.router, prefix="/api/v1/license")
    app.include_router(admin.router, prefix="/api/v1/admin")

    # Added innermost-first: Error <- Limit <- JSON body <- CORS <- Core (outermost)
    app.add_middleware(ErrorMiddleware)
    app.add_middleware(LimitMiddleware)
    app.add_middleware(JsonBodyMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.cors_origins,
        allow_methods=["GET", "HEAD", "PUT", "PATCH", "POST", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-Client-Key", "X-Client-Secret"],
        expose_headers=["X-Request-Id"],
    )
    app.add_middleware(CoreMiddleware)
    return app


app = create_app()
