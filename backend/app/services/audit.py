"""AUDIT_LOGS rows via pkg_audit, for mutations the database functions do not audit themselves."""
from __future__ import annotations

from typing import Any

from ..db import Conn
from ..respond import UNDEFINED, dumps


def log_audit(
    conn: Conn,
    *,
    action: str,
    entity_type: str,
    user_id: int | None = None,
    actor: str | None = None,
    entity_id: int | None = None,
    request_id: str | None = None,
    ip: str | None = None,
    before: Any = UNDEFINED,
    after: Any = UNDEFINED,
) -> None:
    """`before` / `after` are stored as JSON; leave them out to store NULL (pass None to store JSON null)."""
    conn.execute(
        """SELECT pkg_audit.log_event(
               p_user_id      => :p_user_id,
               p_actor        => :p_actor,
               p_action       => :p_action,
               p_entity_type  => :p_entity_type,
               p_entity_id    => :p_entity_id,
               p_request_id   => :p_request_id,
               p_ip_address   => :p_ip_address,
               p_before_state => :p_before_state,
               p_after_state  => :p_after_state)""",
        {
            "p_user_id": user_id,
            "p_actor": actor,
            "p_action": action,
            "p_entity_type": entity_type,
            "p_entity_id": entity_id,
            "p_request_id": request_id,
            "p_ip_address": ip,
            "p_before_state": None if before is UNDEFINED else dumps(before),
            "p_after_state": None if after is UNDEFINED else dumps(after),
        },
    )
