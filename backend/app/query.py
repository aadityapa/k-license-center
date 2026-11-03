"""Query-string helpers, paging, sorting and row -> camelCase conversion."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Mapping

from .db import Binds, Conn, Row
from .errors import AppError
from .respond import iso


def qs(query: Mapping[str, Any], name: str) -> str | None:
    """A query-string value as a trimmed string, or None."""
    v = query.get(name)
    if not isinstance(v, str):
        return None
    t = v.strip()
    return None if t == "" else t


def _js_number(raw: str) -> float | None:
    """Number(raw) in JavaScript, for the inputs that matter here."""
    s = raw.strip()
    if s == "":
        return 0.0
    try:
        if re.fullmatch(r"0[xX][0-9a-fA-F]+", s):
            return float(int(s, 16))
        return float(s)
    except ValueError:
        return None


js_number = _js_number


def _is_int(n: float | None) -> bool:
    return n is not None and n == n and n not in (float("inf"), float("-inf")) and float(n).is_integer()


def qs_number(query: Mapping[str, Any], name: str) -> int | None:
    raw = qs(query, name)
    if raw is None:
        return None
    n = _js_number(raw)
    if not _is_int(n) or n <= 0:
        raise AppError(400, "VALIDATION_ERROR", f"{name} must be a positive integer.")
    return int(n)


_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def qs_date(query: Mapping[str, Any], name: str) -> str | None:
    raw = qs(query, name)
    if raw is None:
        return None
    if not _DATE_RE.fullmatch(raw):
        raise AppError(400, "VALIDATION_ERROR", f"{name} must be formatted as YYYY-MM-DD.")
    return raw


def qs_enum(query: Mapping[str, Any], name: str, allowed: list[str] | tuple[str, ...]) -> str | None:
    raw = qs(query, name)
    if raw is None:
        return None
    if raw not in allowed:
        raise AppError(400, "VALIDATION_ERROR", f"{name} must be one of: {', '.join(allowed)}.")
    return raw


def id_param(raw: Any) -> int:
    n = _js_number(str(raw)) if raw is not None else None
    if raw is None or str(raw).strip() == "" or not _is_int(n) or n <= 0:
        raise AppError(400, "VALIDATION_ERROR", "The id parameter must be a positive integer.")
    return int(n)


@dataclass
class PageParams:
    page: int
    page_size: int


def parse_list(query: Mapping[str, Any]) -> PageParams:
    def clamp(raw: str | None, default: int, mx: int) -> int:
        if raw is None:
            return default
        n = _js_number(raw)
        if not _is_int(n) or n < 1:
            raise AppError(400, "VALIDATION_ERROR", "page and pageSize must be positive integers.")
        return min(int(n), mx)

    return PageParams(page=clamp(qs(query, "page"), 1, 1_000_000), page_size=clamp(qs(query, "pageSize"), 20, 100))


def parse_sort(raw: str | None, whitelist: dict[str, str], default: str) -> str:
    """'field', '-field' or 'field:desc' -> a whitelisted ORDER BY expression."""
    if not raw:
        return default
    key = raw
    direction = "ASC"
    if key.startswith("-"):
        key = key[1:]
        direction = "DESC"
    parts = key.split(":")
    name = parts[0] if parts else ""
    if len(parts) > 1 and parts[1]:
        direction = "DESC" if parts[1].lower() == "desc" else "ASC"
    col = whitelist.get(name)
    if not col:
        raise AppError(400, "VALIDATION_ERROR", f"Unsupported sort field: {name}")
    return f"{col} {direction}"


def camel_key(k: str) -> str:
    return re.sub(r"_([a-z0-9])", lambda m: m.group(1).upper(), k.lower())


BOOLEAN_FLAG_KEYS = {"isLifetime", "autoRenewal", "isPrimary"}


def to_camel(row: Row) -> Row:
    """UPPER_SNAKE row -> camelCase dict. Y/N flags in BOOLEAN_FLAG_KEYS become booleans;
    timestamps become ISO strings (DATE values stay date objects and are rendered by the encoder)."""
    out: Row = {}
    for k, v in row.items():
        key = camel_key(k)
        if key in BOOLEAN_FLAG_KEYS and v in ("Y", "N"):
            out[key] = v == "Y"
        elif isinstance(v, datetime):
            out[key] = iso(v)
        else:
            out[key] = v
    return out


def rows_to_camel(rows: list[Row] | None) -> list[Row]:
    return [to_camel(r) for r in (rows or [])]


def fmt_date_only(d: date | datetime) -> str:
    """YYYY-MM-DD of a DATE value (a datetime is taken in local time)."""
    if isinstance(d, datetime):
        if d.tzinfo is not None:
            d = d.astimezone()
        return d.strftime("%Y-%m-%d")
    return d.isoformat()


def paged_query(
    conn: Conn,
    *,
    select: str,
    from_where: str,
    binds: Binds,
    order_by: str,
    page: int,
    page_size: int,
) -> dict[str, Any]:
    count = conn.execute(f"SELECT COUNT(*) AS TOTAL {from_where}", binds)
    total = int((count.rows[0] if count.rows else {}).get("TOTAL") or 0)
    rows = conn.execute(
        f"{select} {from_where} ORDER BY {order_by} LIMIT :p_limit OFFSET :p_offset",
        {**binds, "p_offset": (page - 1) * page_size, "p_limit": page_size},
    )
    return {"items": rows_to_camel(rows.rows), "total": total, "page": page, "pageSize": page_size}
