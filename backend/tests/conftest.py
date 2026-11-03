"""
Shared pytest set-up for the backend suite.

Unit tests (pure functions: key formats, file formats, crypto) need nothing.
Integration tests (the HTTP API through FastAPI's TestClient) need a real
PostgreSQL: a throwaway database is (re)created for the session, the
migrations are applied with ``app.migrate.run_migrations`` and the demo data
(``database/postgres/demo/demo_data.sql``) is loaded, exactly like a fresh
installation. When PostgreSQL cannot be reached, every test that uses the
``client`` fixture is skipped with the reason; unit tests still run.

Connection: the usual ``DATABASE_URL`` or ``DB_HOST`` / ``DB_PORT`` /
``DB_USER`` / ``DB_PASSWORD`` (environment first, then ``backend/.env``).
The role needs CREATEDB. The database name is ``TEST_DB_NAME``
(default ``klicense_test``) — it is DROPPED and re-created on every run, so it
is never allowed to be the application's own ``DB_NAME``.

    DB_HOST=127.0.0.1 DB_PORT=5432 DB_USER=klicense DB_PASSWORD=... python -m pytest
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Callable, Iterator

import pytest

BACKEND = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND.parent
DEMO_DATA = PROJECT_ROOT / "database" / "postgres" / "demo" / "demo_data.sql"
for _p in (str(BACKEND), str(Path(__file__).resolve().parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ---------------------------------------------------------------------------
# Environment — must be in place BEFORE anything imports `app` (app.config is
# read once, at import). conftest.py is imported before any test module.
# ---------------------------------------------------------------------------
try:
    from dotenv import dotenv_values

    _DOTENV: dict[str, Any] = dict(dotenv_values(BACKEND / ".env")) if (BACKEND / ".env").exists() else {}
except ImportError:  # pragma: no cover
    _DOTENV = {}


def _setting(name: str, default: str = "") -> str:
    v = os.environ.get(name)
    if v is None:
        v = _DOTENV.get(name)
    return default if v is None else str(v)


TEST_DB_NAME = os.environ.get("TEST_DB_NAME", "klicense_test") or "klicense_test"
_APP_DB_NAME = _setting("DB_NAME", "klicense") or "klicense"
_DATABASE_URL = _setting("DATABASE_URL")


def _connection_params(dbname: str) -> dict[str, Any]:
    """psycopg.connect() keyword arguments for `dbname` on the configured server."""
    if _DATABASE_URL:
        from psycopg.conninfo import conninfo_to_dict

        params: dict[str, Any] = dict(conninfo_to_dict(_DATABASE_URL))
        params["dbname"] = dbname
    else:
        params = {
            "host": _setting("DB_HOST", "localhost") or "localhost",
            "port": int(_setting("DB_PORT", "5432") or "5432"),
            "user": _setting("DB_USER"),
            "password": _setting("DB_PASSWORD"),
            "dbname": dbname,
        }
    params["connect_timeout"] = 5
    return params


def _url_db_name() -> str | None:
    if not _DATABASE_URL:
        return None
    from psycopg.conninfo import conninfo_to_dict

    return str(conninfo_to_dict(_DATABASE_URL).get("dbname") or "") or None


# The test signing keys are the throwaway ones from vitest.config.ts — never a
# real one. Rate limits are lifted: the suite logs in and calls the product API
# far more often than one person would.
_TEST_ENV = {
    "NODE_ENV": "test",
    "AUTH_DISABLED": "false",
    "DB_MOCK": "false",
    "AUTO_MIGRATE": "false",  # the fixture migrates; the app must not race it
    "LOG_LEVEL": os.environ.get("LOG_LEVEL", "warn"),
    "SMTP_HOST": "",  # mail is queued in email_outbox, never sent
    "JWT_SECRET": "pytest-only-jwt-secret-pytest-only-jwt-secret",
    "LICENCE_SIGNING_KEY": "MC4CAQAwBQYDK2VwBCIEIBF24EYgwYktawquTKzcpKKfs+tY+N6Sj21Ka7c16t9U",
    "VBS_SIGNING_KEY": (
        "MIGHAgEAMBMGByqGSM49AgEGCCqGSM49AwEHBG0wawIBAQQghLrZELHRmHsRa6nxkV/3z0eJBs11wFCI5Rin3oA0REGhRANCAASgu1QF"
        "QNZKJZwAAuteQFvB7XXoPI0FumlgmW3eI35l/tiqm683GcHxI6sp2gcY9QyKbcx3JBO7yRsgi17Ol9Y/"
    ),
    "RATE_LIMIT_MAX": "1000000",
    "RATE_LIMIT_LOGIN_MAX": "1000000",
    "RATE_LIMIT_LICENSE_MAX": "1000000",
    "DB_NAME": TEST_DB_NAME,
}
os.environ.update(_TEST_ENV)
if _DATABASE_URL:
    # DATABASE_URL wins over DB_NAME in app.config, so point it at the test DB too.
    from psycopg.conninfo import make_conninfo

    os.environ["DATABASE_URL"] = make_conninfo(_DATABASE_URL, dbname=TEST_DB_NAME)


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "integration: needs PostgreSQL (skipped when it cannot be reached)")


def pytest_terminal_summary(terminalreporter: Any) -> None:
    if _STATE.reason:
        terminalreporter.write_line(f"integration tests skipped: {_STATE.reason}", yellow=True)
    elif _STATE.ready:
        terminalreporter.write_line(f"integration tests ran against the throwaway database {TEST_DB_NAME!r}")


# ---------------------------------------------------------------------------
# The throwaway database
# ---------------------------------------------------------------------------
class _DbState:
    ready: bool = False
    reason: str = ""


_STATE = _DbState()


def _create_database() -> None:
    import psycopg
    from psycopg import sql

    protected = {_APP_DB_NAME, _url_db_name() or _APP_DB_NAME, "postgres", "template0", "template1"}
    if TEST_DB_NAME in protected:
        raise RuntimeError(
            f"TEST_DB_NAME={TEST_DB_NAME!r} is the application's own database (or a system one); "
            "the suite drops its test database, so it refuses to run against that name."
        )
    with psycopg.connect(**_connection_params("postgres"), autocommit=True) as admin:
        admin.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s AND pid <> pg_backend_pid()",
            (TEST_DB_NAME,),
        )
        admin.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(TEST_DB_NAME)))
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(TEST_DB_NAME)))

    from app.migrate import run_migrations

    with psycopg.connect(**_connection_params(TEST_DB_NAME)) as conn:
        result = run_migrations(conn)
        if not result.applied:
            raise RuntimeError(f"no migrations applied ({result.skipped_reason})")
    with psycopg.connect(**_connection_params(TEST_DB_NAME), autocommit=True) as conn:
        conn.execute(DEMO_DATA.read_text(encoding="utf-8"))  # no parameters: runs as a script


@pytest.fixture(scope="session")
def database() -> Iterator[None]:
    """Creates the test database once per session (or records why it cannot)."""
    if not _STATE.ready and not _STATE.reason:
        try:
            import psycopg

            with psycopg.connect(**_connection_params("postgres"), autocommit=True):
                pass
        except Exception as err:  # noqa: BLE001
            p = _connection_params("postgres")
            _STATE.reason = (
                f"PostgreSQL not reachable at {p.get('host')}:{p.get('port')} as {p.get('user')!r} "
                f"({type(err).__name__}: {str(err).strip().splitlines()[0] if str(err).strip() else ''}) — "
                "set DB_HOST/DB_PORT/DB_USER/DB_PASSWORD or DATABASE_URL to run the integration tests"
            )
        else:
            _create_database()  # a failure here is an error, not a skip
            _STATE.ready = True
    if not _STATE.ready:
        pytest.skip(_STATE.reason)
    yield


@pytest.fixture(scope="session")
def client(database: None) -> Iterator[Any]:
    """The FastAPI app over HTTP, with its lifespan (connection pool, expiry job) running."""
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def db(database: None) -> Iterator[Callable[..., list[dict[str, Any]]]]:
    """Direct SQL on the test database (autocommit): db("SELECT ... WHERE x = %s", (1,)) -> rows."""
    import psycopg
    from psycopg.rows import dict_row

    conn = psycopg.connect(**_connection_params(TEST_DB_NAME), autocommit=True, row_factory=dict_row)

    def run(query: str, params: tuple | list | dict | None = None) -> list[dict[str, Any]]:
        with conn.cursor() as cur:
            cur.execute(query, params)
            return list(cur.fetchall()) if cur.description is not None else []

    try:
        yield run
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Helpers as fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def login(client: Any) -> Callable[[str], str]:
    """login("maker") -> bearer token; one real login per user per session."""
    cache: dict[str, str] = {}

    def do(username: str) -> str:
        if username not in cache:
            res = client.post("/api/v1/auth/login", json={"username": username, "password": "Pass@100%"})
            assert res.status_code == 200, res.text
            cache[username] = str(res.json()["data"]["token"])
        return cache[username]

    return do


@pytest.fixture(scope="session")
def user_id(db: Callable[..., list[dict[str, Any]]]) -> Callable[[str], int]:
    def get(username: str) -> int:
        return int(db("SELECT user_id FROM users WHERE username = %s", (username,))[0]["user_id"])

    return get


@pytest.fixture(autouse=True)
def _fresh_rate_limits() -> None:
    """Each test starts with empty per-route limiters (the public request routes
    allow 5 starts per hour per IP — in vitest every file built its own app)."""
    rl = sys.modules.get("app.ratelimit")
    if rl is not None:
        for limiter in rl.ALL_LIMITERS:
            limiter.reset()


class SqlSpy:
    """Every statement the app sent through app.db.Conn.execute while the spy was on."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    @property
    def sqls(self) -> list[str]:
        return [s for s, _ in self.calls]

    def any(self, fragment: str) -> bool:
        return any(fragment in s for s in self.sqls)

    def matching(self, fragment: str) -> list[tuple[str, dict[str, Any]]]:
        return [c for c in self.calls if fragment in c[0]]

    def clear(self) -> None:
        self.calls.clear()


@pytest.fixture
def sql_spy(monkeypatch: pytest.MonkeyPatch, client: Any) -> SqlSpy:
    """Pass-through spy on the SQL layer (the Python stand-in for vitest's executeMock call log)."""
    import re

    from app import db as app_db

    spy = SqlSpy()
    original = app_db.Conn.execute

    # Background work that is not part of the request under test.
    background = ("pkg_license.expire_due_licenses()", "SET last_used_at = now()")

    def spying(self: Any, sql_text: str, binds: dict[str, Any] | None = None) -> Any:
        s = re.sub(r"\s+", " ", sql_text).strip()
        if not any(b in s for b in background):
            spy.calls.append((s, dict(binds or {})))
        return original(self, sql_text, binds)

    monkeypatch.setattr(app_db.Conn, "execute", spying)
    return spy
