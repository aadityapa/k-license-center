"""
PostgreSQL access.

Every statement in the code base is written with named binds (``:p_name``).
They are translated to psycopg placeholders here, and — exactly like the
previous Node driver — every value is sent to PostgreSQL as untyped text, so
the server infers each parameter's type from where it is used. Result rows are
dicts keyed by UPPER-CASE column names; NUMERIC values come back as int/float.

    with transaction() as conn:
        r = conn.execute("SELECT ... WHERE id = :p_id", {"p_id": 5})
        r.rows            # list of dicts, keys upper-case
        r.rows_affected
        r.out_binds       # values asked for with OUT markers (see below)

An empty string bound to a parameter is stored as NULL (the convention the API
was built on), so a cleared optional form field reads back as "not set".
"""
from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Callable, Iterator, TypeVar

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from .config import config
from .logger import logger

Row = dict[str, Any]
Binds = dict[str, Any]
T = TypeVar("T")


# ---------------------------------------------------------------------------
# Output binds: `RETURNING x AS o_id` + {"o_id": OUT} -> r.out_binds["o_id"].
# ---------------------------------------------------------------------------
class _Out:
    __slots__ = ()

    def __repr__(self) -> str:  # pragma: no cover
        return "OUT"


OUT = _Out()


def is_out(v: Any) -> bool:
    return isinstance(v, _Out)


# ---------------------------------------------------------------------------
# SQL translation: :name -> %(name)s. String literals, quoted identifiers,
# comments and :: casts are skipped; every literal % is doubled for psycopg.
# ---------------------------------------------------------------------------
@dataclass
class Translated:
    text: str
    names: list[str]


_cache: dict[str, Translated] = {}
_cache_lock = threading.Lock()


def _is_ident_start(c: str) -> bool:
    return c.isascii() and (c.isalpha() or c == "_")


def _is_ident(c: str) -> bool:
    return c.isascii() and (c.isalnum() or c == "_")


def translate_sql(sql: str) -> Translated:
    hit = _cache.get(sql)
    if hit is not None:
        return hit
    names: list[str] = []
    seen: set[str] = set()
    out: list[str] = []
    i, n = 0, len(sql)

    def emit(s: str) -> None:
        out.append(s.replace("%", "%%"))

    while i < n:
        ch = sql[i]
        nxt = sql[i + 1] if i + 1 < n else ""
        if ch == "'":
            j = i + 1
            while j < n:
                if sql[j] == "'" and j + 1 < n and sql[j + 1] == "'":
                    j += 2
                elif sql[j] == "'":
                    break
                else:
                    j += 1
            emit(sql[i:j + 1])
            i = j + 1
            continue
        if ch == '"':
            j = sql.find('"', i + 1)
            end = n if j == -1 else j + 1
            emit(sql[i:end])
            i = end
            continue
        if ch == "-" and nxt == "-":
            j = sql.find("\n", i)
            end = n if j == -1 else j
            emit(sql[i:end])
            i = end
            continue
        if ch == "/" and nxt == "*":
            j = sql.find("*/", i + 2)
            end = n if j == -1 else j + 2
            emit(sql[i:end])
            i = end
            continue
        if ch == ":" and nxt == ":":
            out.append("::")
            i += 2
            continue
        if ch == ":" and nxt and _is_ident_start(nxt):
            j = i + 1
            while j < n and _is_ident(sql[j]):
                j += 1
            name = sql[i + 1:j]
            if name not in seen:
                seen.add(name)
                names.append(name)
            out.append(f"%({name})s")
            i = j
            continue
        emit(ch)
        i += 1

    t = Translated("".join(out), names)
    with _cache_lock:
        if len(_cache) < 2000:
            _cache[sql] = t
    return t


# ---------------------------------------------------------------------------
# Value conversion (to the database): everything as text, like node-postgres.
# ---------------------------------------------------------------------------
def _array_literal(items: list | tuple) -> str:
    parts = []
    for v in items:
        if v is None:
            parts.append("NULL")
        elif isinstance(v, (list, tuple)):
            parts.append(_array_literal(v))
        else:
            s = _to_text(v)
            parts.append('"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"')
    return "{" + ",".join(parts) + "}"


def _to_text(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(int(v))  # int(): an IntEnum member prints its name otherwise
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, float):
        return repr(v) if not v.is_integer() else str(int(v))
    if isinstance(v, datetime):
        return v.isoformat()
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, (dict,)):
        return json.dumps(v, separators=(",", ":"))
    if isinstance(v, bytes):
        return "\\x" + v.hex()
    return str(v)


def bind_value(v: Any) -> Any:
    if v is None or v == "":
        return None
    if isinstance(v, (list, tuple)):
        return _array_literal(v)
    return _to_text(v)


# ---------------------------------------------------------------------------
# Value conversion (from the database).
# ---------------------------------------------------------------------------
def _from_db(v: Any) -> Any:
    if isinstance(v, Decimal):
        if v == v.to_integral_value():
            return int(v)
        return float(v)
    return v


def _row(raw: dict) -> Row:
    return {k.upper(): _from_db(v) for k, v in raw.items()}


@dataclass
class DbResult:
    rows: list[Row] = field(default_factory=list)
    rows_affected: int = 0
    out_binds: Row = field(default_factory=dict)

    @property
    def first(self) -> Row | None:
        return self.rows[0] if self.rows else None


class Conn:
    """One pooled connection inside one transaction."""

    def __init__(self, raw: psycopg.Connection):
        self.raw = raw

    def execute(self, sql: str, binds: Binds | None = None) -> DbResult:
        binds = binds or {}
        t = translate_sql(sql)
        out_names = [k for k, v in binds.items() if is_out(v)]
        params: dict[str, Any] = {}
        for name in t.names:
            if name not in binds:
                raise RuntimeError(f"Missing bind :{name}")
            v = binds[name]
            if is_out(v):
                raise RuntimeError(f"Out bind :{name} used inside the SQL text; return it as a column named {name} instead")
            params[name] = bind_value(v)
        with self.raw.cursor(row_factory=dict_row) as cur:
            # Always pass a mapping (even empty) so the doubled %% are un-doubled.
            cur.execute(t.text, params, prepare=False)
            rows: list[Row] = []
            if cur.description is not None:
                rows = [_row(r) for r in cur.fetchall()]
            affected = cur.rowcount if cur.rowcount is not None and cur.rowcount >= 0 else 0
        out: Row = {}
        if out_names:
            first = rows[0] if rows else {}
            for name in out_names:
                out[name] = first.get(name.upper())
        return DbResult(rows=rows, rows_affected=affected, out_binds=out)


# ---------------------------------------------------------------------------
# Pool
# ---------------------------------------------------------------------------
_pool: ConnectionPool | None = None


def _conninfo() -> dict[str, Any]:
    c = config.db
    kw: dict[str, Any] = {"application_name": "k-license-api", "connect_timeout": 10}
    if c.ssl:
        kw["sslmode"] = "verify-full" if c.ssl_reject_unauthorized else "require"
    if c.timezone:
        kw["options"] = f"-c TimeZone={c.timezone}"
    if c.url:
        return {"conninfo": c.url, **kw}
    return {
        "conninfo": "",
        "host": c.host, "port": c.port, "dbname": c.database,
        "user": c.user, "password": c.password, **kw,
    }


def connect_raw(autocommit: bool = False) -> psycopg.Connection:
    """A standalone connection (scripts, migrations)."""
    info = _conninfo()
    conninfo = info.pop("conninfo")
    return psycopg.connect(conninfo, autocommit=autocommit, **info)


def init_pool() -> None:
    global _pool
    if _pool is not None:
        return
    info = _conninfo()
    conninfo = info.pop("conninfo")
    pool = ConnectionPool(
        conninfo=conninfo,
        kwargs=info,
        min_size=1,
        max_size=config.db.pool_max,
        max_idle=30,
        timeout=10,
        open=False,
        name="klicense",
    )
    pool.open(wait=True, timeout=15)
    _pool = pool

    from .migrate import run_migrations  # local import: migrate uses this module

    with pool.connection() as raw:
        if config.db.auto_migrate:
            m = run_migrations(raw)
            if m.applied:
                logger.info("database upgraded", applied=m.applied)
            if m.changed:
                logger.warn("applied migration files were edited afterwards", changed=m.changed)
            if m.skipped_reason:
                logger.warn(f"auto-migrate skipped: {m.skipped_reason}")
        with raw.cursor() as cur:
            cur.execute("SELECT current_setting('server_version'), current_setting('TimeZone')")
            ver, tz = cur.fetchone()
        raw.commit()
        logger.info(
            "PostgreSQL connection pool started",
            server=ver, timeZone=tz,
            database="(DATABASE_URL)" if config.db.url else config.db.database,
        )


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None
        logger.info("PostgreSQL connection pool closed")


@contextmanager
def transaction() -> Iterator[Conn]:
    """A pooled connection as one transaction: commit on success, rollback on error."""
    if _pool is None:
        raise RuntimeError("Database pool is not initialized")
    with _pool.connection() as raw:
        try:
            yield Conn(raw)
            raw.commit()
        except BaseException:
            try:
                raw.rollback()
            except Exception:  # pragma: no cover
                logger.error("rollback failed", exc=True)
            raise


def with_connection(fn: Callable[[Conn], T]) -> T:
    with transaction() as conn:
        return fn(conn)


def execute(sql: str, binds: Binds | None = None) -> DbResult:
    """One-shot statement in its own transaction."""
    with transaction() as conn:
        return conn.execute(sql, binds)
