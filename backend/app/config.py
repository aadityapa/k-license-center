"""Environment configuration (backend/.env). Same variable names as before."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

try:  # python-dotenv never overrides variables already set in the environment
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:  # pragma: no cover
    pass

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND_DIR.parent


def _env(name: str, default: str = "") -> str:
    v = os.environ.get(name)
    return default if v is None else v


def _flag(v: str) -> bool:
    return v.strip().lower() in ("true", "1", "yes")


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        n = int(float(raw))
    except ValueError as e:
        raise RuntimeError(f"Invalid environment configuration: {name}: Expected number") from e
    if n <= 0:
        raise RuntimeError(f"Invalid environment configuration: {name}: Number must be greater than 0")
    return n


def parse_duration_seconds(v: str) -> int:
    """'8h', '30m', '1d', '3600' (seconds), like jsonwebtoken's expiresIn."""
    s = v.strip()
    if re.fullmatch(r"\d+", s):
        return int(s)
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(ms|s|m|h|d|w|y)", s, re.I)
    if not m:
        raise RuntimeError("JWT_EXPIRES_IN must look like 8h, 30m, 1d or a number of seconds")
    n = float(m.group(1))
    mult = {"ms": 0.001, "s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800, "y": 31557600}[m.group(2).lower()]
    return int(n * mult)


# The development signing keys checked into this repository. A production
# server must never start with either one.
DEV_LICENCE_SIGNING_KEY = "MC4CAQAwBQYDK2VwBCIEIBF24EYgwYktawquTKzcpKKfs+tY+N6Sj21Ka7c16t9U"
DEV_VBS_SIGNING_KEY = (
    "MIGHAgEAMBMGByqGSM49AgEGCCqGSM49AwEHBG0wawIBAQQgKwYaKb2yDSvRqIfNsrs1kHijis8Q0g31qpWMtaNuXluhRANCAARy"
    "FOb9fR+FkgwviM0397mVMDwjeOF3oAVsM2IKoDzg1k01HkkO1DmtAKJsDRFpcMNdK+hZ7SXGTHvctQ06E/QJ"
)


@dataclass
class DbConfig:
    url: str
    host: str
    port: int
    database: str
    user: str
    password: str
    ssl: bool
    ssl_reject_unauthorized: bool
    pool_max: int
    timezone: str
    auto_migrate: bool


@dataclass
class SmtpConfig:
    host: str
    port: int
    user: str
    password: str
    sender: str


@dataclass
class RateLimitConfig:
    window_ms: int
    max: int
    login_window_ms: int
    login_max: int
    license_window_ms: int
    license_max: int


@dataclass
class Config:
    env: str
    port: int
    log_level: str
    auth_disabled: bool
    db: DbConfig
    smtp: SmtpConfig
    licence_signing_key: str
    vbs_signing_key: str
    jwt_secret: str
    jwt_expires_in: str
    jwt_expires_seconds: int
    cors_origins: list[str] = field(default_factory=list)
    rate_limit: RateLimitConfig | None = None


def load_config() -> Config:
    env = _env("NODE_ENV", _env("APP_ENV", "development")) or "development"
    if env not in ("development", "test", "production"):
        raise RuntimeError("Invalid environment configuration: NODE_ENV must be development, test or production")
    auth_disabled = _flag(_env("AUTH_DISABLED", "false"))
    tz = _env("DB_TIMEZONE", "")
    if tz and not re.fullmatch(r"[A-Za-z0-9_+\-/]+", tz):
        raise RuntimeError("DB_TIMEZONE must be a time zone name such as Asia/Kolkata")
    if env == "production" and auth_disabled:
        raise RuntimeError("AUTH_DISABLED must not be enabled in production")
    if _flag(_env("DB_MOCK", "false")):
        # The in-memory demo engine was removed: the server always uses PostgreSQL.
        raise RuntimeError(
            "DB_MOCK is no longer supported — the server runs on PostgreSQL only. "
            "Remove DB_MOCK from backend/.env (load database/postgres/demo/demo_data.sql for demo data)."
        )

    licence_key = _env("LICENCE_SIGNING_KEY")
    vbs_key = _env("VBS_SIGNING_KEY")
    jwt_secret = _env("JWT_SECRET", "dev-only-jwt-secret-do-not-use-in-production") or "dev-only-jwt-secret-do-not-use-in-production"

    if env == "production":
        missing = [k for k in ("JWT_SECRET", "LICENCE_SIGNING_KEY", "VBS_SIGNING_KEY") if not os.environ.get(k)]
        if not os.environ.get("DATABASE_URL") and (not os.environ.get("DB_USER") or not os.environ.get("DB_PASSWORD")):
            missing.append("DATABASE_URL (or DB_USER + DB_PASSWORD)")
        if missing:
            raise RuntimeError(f"Missing required environment variables in production: {', '.join(missing)}")
        if len(jwt_secret) < 32:
            raise RuntimeError("JWT_SECRET must be at least 32 characters in production")
        if licence_key == DEV_LICENCE_SIGNING_KEY or vbs_key == DEV_VBS_SIGNING_KEY:
            raise RuntimeError(
                "LICENCE_SIGNING_KEY / VBS_SIGNING_KEY are the development keys from the repository. "
                "Run `python -m scripts.keygen` and use the generated keys in production."
            )

    jwt_expires_in = _env("JWT_EXPIRES_IN", "8h") or "8h"
    return Config(
        env=env,
        port=_int("PORT", 3001),
        log_level=_env("LOG_LEVEL", "info") or "info",
        auth_disabled=auth_disabled,
        db=DbConfig(
            url=_env("DATABASE_URL"),
            host=_env("DB_HOST", "localhost") or "localhost",
            port=_int("DB_PORT", 5432),
            database=_env("DB_NAME", "klicense") or "klicense",
            user=_env("DB_USER"),
            password=_env("DB_PASSWORD"),
            ssl=_flag(_env("DB_SSL", "false")),
            ssl_reject_unauthorized=_flag(_env("DB_SSL_REJECT_UNAUTHORIZED", "true")),
            pool_max=_int("DB_POOL_MAX", 10),
            timezone=tz,
            auto_migrate=_flag(_env("AUTO_MIGRATE", "true")),
        ),
        smtp=SmtpConfig(
            host=_env("SMTP_HOST"),
            port=_int("SMTP_PORT", 587),
            user=_env("SMTP_USER"),
            password=_env("SMTP_PASSWORD"),
            sender=_env("MAIL_FROM", "Karnex License Center <no-reply@karnex.in>") or "Karnex License Center <no-reply@karnex.in>",
        ),
        licence_signing_key=licence_key,
        vbs_signing_key=vbs_key,
        jwt_secret=jwt_secret,
        jwt_expires_in=jwt_expires_in,
        jwt_expires_seconds=parse_duration_seconds(jwt_expires_in),
        cors_origins=[s.strip() for s in _env("CORS_ORIGINS", "http://localhost:5173").split(",") if s.strip()],
        rate_limit=RateLimitConfig(
            window_ms=_int("RATE_LIMIT_WINDOW_MS", 900_000),
            max=_int("RATE_LIMIT_MAX", 300),
            login_window_ms=_int("RATE_LIMIT_LOGIN_WINDOW_MS", 900_000),
            login_max=_int("RATE_LIMIT_LOGIN_MAX", 10),
            license_window_ms=_int("RATE_LIMIT_LICENSE_WINDOW_MS", 60_000),
            license_max=_int("RATE_LIMIT_LICENSE_MAX", 120),
        ),
    )


config = load_config()
