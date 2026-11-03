"""
Live enforcement channel (Server-Sent Events).

Each running installation holds ONE persistent HTTP connection. When a licence
changes state the server pushes immediately, so a revoke reaches the product in
well under a second. Every event carries `serverTime`: the product treats this
stream as its trusted clock.

Thread-safe: `publish` is called from request worker threads after a commit;
frames are handed to each subscriber's asyncio queue on the event loop.
"""
from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncIterator

from ..logger import logger
from ..respond import dumps, now_iso

KEEPALIVE_S = 25.0
_CLOSE = object()


@dataclass
class Subscriber:
    id: int
    license_id: int
    installation_id: str
    loop: asyncio.AbstractEventLoop
    queue: asyncio.Queue
    connected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    closed: bool = False


_lock = threading.Lock()
_next_id = 1
_subscribers: dict[int, Subscriber] = {}


def _frame(event: dict[str, Any]) -> str:
    # SSE frame. The blank line terminates the event — without it nothing flushes.
    return f"event: {event['type']}\ndata: {dumps(event)}\n\n"


def _deliver(sub: Subscriber, item: Any) -> None:
    try:
        sub.loop.call_soon_threadsafe(sub.queue.put_nowait, item)
    except RuntimeError:  # loop closed
        sub.closed = True


def subscribe(license_id: int, installation_id: str) -> Subscriber:
    global _next_id
    loop = asyncio.get_running_loop()
    with _lock:
        sid = _next_id
        _next_id += 1
        sub = Subscriber(sid, license_id, installation_id, loop, asyncio.Queue())
        _subscribers[sid] = sub
        live = len(_subscribers)
    sub.queue.put_nowait(_frame({"type": "connected", "serverTime": now_iso(), "licenseId": license_id}))
    logger.info("live channel opened", licenseId=license_id, installationId=installation_id, live=live)
    return sub


def remove(sid: int) -> None:
    with _lock:
        sub = _subscribers.pop(sid, None)
        live = len(_subscribers)
    if sub is None:
        return
    if not sub.closed:
        sub.closed = True
        _deliver(sub, _CLOSE)
    logger.info("live channel closed", licenseId=sub.license_id, live=live)


async def stream(sub: Subscriber) -> AsyncIterator[str]:
    """The response body of one live connection: frames until closed, a heartbeat every 25 s."""
    try:
        while True:
            try:
                item = await asyncio.wait_for(sub.queue.get(), timeout=KEEPALIVE_S)
            except asyncio.TimeoutError:
                # A heartbeat doubles as a clock sync for the product.
                item = _frame({"type": "heartbeat", "serverTime": now_iso(), "licenseId": sub.license_id})
            if item is _CLOSE:
                return
            yield item
    finally:
        remove(sub.id)


def publish(license_id: int, event: dict[str, Any]) -> int:
    """Pushes to every connection for a licence. Call straight after the change commits."""
    payload = {**event, "serverTime": now_iso(), "licenseId": license_id}
    frame = _frame(payload)
    with _lock:
        targets = [s for s in _subscribers.values() if s.license_id == license_id]
    for sub in targets:
        _deliver(sub, frame)
        # A terminal decision closes the stream.
        if event.get("type") == "license.revoked":
            remove(sub.id)
    if targets:
        logger.info("live event pushed", licenseId=license_id, type=event.get("type"), delivered=len(targets))
    return len(targets)


def publish_to_installation(license_id: int, installation_id: str, event: dict[str, Any]) -> int:
    payload = {**event, "serverTime": now_iso(), "licenseId": license_id}
    frame = _frame(payload)
    with _lock:
        targets = [s for s in _subscribers.values()
                   if s.license_id == license_id and s.installation_id == installation_id]
    for sub in targets:
        _deliver(sub, frame)
        remove(sub.id)
    return len(targets)


def connection_stats() -> dict[str, Any]:
    by_license: dict[int, dict[str, Any]] = {}
    with _lock:
        subs = list(_subscribers.values())
    for s in subs:
        e = by_license.setdefault(s.license_id, {"installations": [], "since": s.connected_at})
        if s.installation_id not in e["installations"]:
            e["installations"].append(s.installation_id)
        if s.connected_at < e["since"]:
            e["since"] = s.connected_at
    from ..respond import iso

    return {
        "total": len(subs),
        "byLicense": [
            {"licenseId": lid, "installations": v["installations"], "since": iso(v["since"])}
            for lid, v in by_license.items()
        ],
    }


def is_online(license_id: int, installation_id: str) -> bool:
    with _lock:
        return any(s.license_id == license_id and s.installation_id == installation_id
                   for s in _subscribers.values())
