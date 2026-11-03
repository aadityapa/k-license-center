"""Cached OFFLINE_GRACE_DAYS setting."""
from __future__ import annotations

import time

from ..db import Conn

_CACHE_TTL_S = 60.0
_DEFAULT_GRACE_DAYS = 7
_cache: tuple[float, float] | None = None  # (value, at)


def get_offline_grace_days(conn: Conn) -> float:
    global _cache
    if _cache is not None and time.monotonic() - _cache[1] < _CACHE_TTL_S:
        return _cache[0]
    r = conn.execute("SELECT setting_value FROM settings WHERE setting_key = :p_key", {"p_key": "OFFLINE_GRACE_DAYS"})
    raw = r.rows[0]["SETTING_VALUE"] if r.rows else None
    try:
        value = float(raw) if raw is not None and str(raw).strip() != "" else float("nan")
    except ValueError:
        value = float("nan")
    days = value if value == value and value not in (float("inf"),) and value > 0 else _DEFAULT_GRACE_DAYS
    if isinstance(days, float) and days.is_integer():
        days = int(days)
    _cache = (days, time.monotonic())
    return days


def clear_settings_cache() -> None:
    global _cache
    _cache = None
