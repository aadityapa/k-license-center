"""
Licence expiry job.

pkg_license.expire_due_licenses() flips overdue ACTIVE/SUSPENDED licences to
EXPIRED and queues the 30/15/7-day warning events. It is idempotent, so it runs
15 seconds after start-up and then every hour; a server that was down at
midnight catches up on its next run. Licence checks never wait for it —
pkg_authorization expires an overdue licence lazily on first use.
"""
from __future__ import annotations

import threading

from .db import transaction
from .logger import logger

INTERVAL_S = 60 * 60
_stop = threading.Event()
_thread: threading.Thread | None = None


def run_expiry_once() -> int:
    with transaction() as conn:
        r = conn.execute("SELECT pkg_license.expire_due_licenses() AS expired", {})
    return int((r.first or {}).get("EXPIRED") or 0)


def _loop() -> None:
    delay = 15.0
    while not _stop.wait(delay):
        try:
            n = run_expiry_once()
            if n > 0:
                logger.info("expiry job: licences expired", expired=n)
        except Exception:
            logger.error("expiry job failed", exc=True)
        delay = INTERVAL_S


def start_expiry_job() -> None:
    global _thread
    if _thread is not None:
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="expiry-job", daemon=True)
    _thread.start()


def stop_expiry_job() -> None:
    global _thread
    _stop.set()
    _thread = None
