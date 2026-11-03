"""Fire-and-forget API_REQUEST_LOGS rows. License keys are stored as SHA-256 hashes only."""
from __future__ import annotations

import threading

from ..db import transaction
from ..logger import logger
from ..security import sha256_hex


def log_api_request(
    *,
    request_id: str,
    client_id: int | None,
    endpoint: str,
    method: str,
    result_code: str,
    http_status: int,
    duration_ms: int,
    license_key: str | None = None,
    ip: str | None = None,
) -> None:
    def run() -> None:
        try:
            with transaction() as conn:
                conn.execute(
                    """INSERT INTO api_request_logs
                         (request_id, client_id, endpoint, method, license_key_hash,
                          result_code, http_status, ip_address, duration_ms)
                       VALUES
                         (:p_request_id, :p_client_id, :p_endpoint, :p_method, :p_key_hash,
                          :p_result_code, :p_http_status, :p_ip, :p_duration_ms)""",
                    {
                        "p_request_id": request_id,
                        "p_client_id": client_id,
                        "p_endpoint": endpoint,
                        "p_method": method,
                        "p_key_hash": sha256_hex(license_key) if license_key else None,
                        "p_result_code": result_code,
                        "p_http_status": http_status,
                        "p_ip": ip,
                        "p_duration_ms": duration_ms,
                    },
                )
        except Exception:
            logger.warn("failed to write api request log", requestId=request_id)

    threading.Thread(target=run, daemon=True).start()
