"""
In-memory fixed-window rate limiting (what express-rate-limit's memory store did),
with the standard RateLimit-* response headers.
"""
from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass

from fastapi import Request


@dataclass
class Hit:
    allowed: bool
    limit: int
    remaining: int
    reset_seconds: int
    window_seconds: int

    def headers(self) -> list[tuple[bytes, bytes]]:
        return [
            (b"ratelimit-policy", f"{self.limit};w={self.window_seconds}".encode()),
            (b"ratelimit-limit", str(self.limit).encode()),
            (b"ratelimit-remaining", str(self.remaining).encode()),
            (b"ratelimit-reset", str(self.reset_seconds).encode()),
        ]


class Limiter:
    def __init__(self, window_ms: int, limit: int):
        self.window = window_ms / 1000.0
        self.limit = limit
        self._hits: dict[str, tuple[int, float]] = {}
        self._lock = threading.Lock()
        self._last_sweep = time.monotonic()

    def hit(self, key: str) -> Hit:
        now = time.monotonic()
        with self._lock:
            if now - self._last_sweep > self.window:
                self._hits = {k: v for k, v in self._hits.items() if v[1] > now}
                self._last_sweep = now
            count, reset_at = self._hits.get(key, (0, 0.0))
            if reset_at <= now:
                count, reset_at = 0, now + self.window
            count += 1
            self._hits[key] = (count, reset_at)
        return Hit(
            allowed=count <= self.limit,
            limit=self.limit,
            remaining=max(0, self.limit - count),
            reset_seconds=max(0, math.ceil(reset_at - now)),
            window_seconds=int(self.window),
        )

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


ALL_LIMITERS: list[Limiter] = []


def route_limit(window_ms: int, limit: int, message: str = "Too many requests. Please try again later."):
    """A FastAPI dependency limiting one route (or group of routes sharing it) per client IP.

        form_limit = route_limit(15 * 60 * 1000, 30, "Too many requests. Try again later.")
        @router.get("/catalogue", dependencies=[Depends(form_limit)])
    """
    from .deps import client_ip
    from .errors import AppError

    limiter = Limiter(window_ms, limit)
    ALL_LIMITERS.append(limiter)

    def dep(request: Request) -> None:
        hit = limiter.hit(client_ip(request) or "unknown")
        request.scope.setdefault("state", {})["rl_headers"] = hit.headers()
        if not hit.allowed:
            raise AppError(429, "RATE_LIMITED", message)

    dep.limiter = limiter  # type: ignore[attr-defined]
    return dep
