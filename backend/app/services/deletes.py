"""
Delete operations for every kind of record shown in the portal's lists.

Each one is a governed change (see governance.apply_change): an admin's delete
applies at once, a maker's delete waits in Approvals. They run inside the
caller's transaction, re-check the record at apply time (it may have changed
since a maker asked), remove the rows that only belong to the record, detach
rows that merely point at it, and write an audit entry.

Records that other data depends on refuse instead of silently erasing that
data: a product or customer that still has licences must have its licences
deleted first (each licence has its own Delete).
"""
from __future__ import annotations

from typing import Any, Callable

from ..db import Conn
from ..errors import AppError
from .audit import log_audit
from .live_channel import publish as push_live


def _cancel_pending(conn: Conn, entity_type: str, entity_id: int) -> None:
    """Open change requests about a deleted record can no longer be applied."""
    conn.execute(
        """UPDATE change_requests
              SET status = 'CANCELLED', reviewed_at = now(),
                  review_comment = 'Record deleted'
            WHERE entity_type = :p_type AND entity_id = :p_id AND status = 'PENDING'
              AND operation NOT LIKE '%\\_DELETE' ESCAPE '\\'""",
        {"p_type": entity_type, "p_id": entity_id},
    )


def _audit(conn: Conn, user_id: int, action: str, entity_type: str, entity_id: int,
           correlation_id: str | None, before: Any) -> None:
    log_audit(conn, user_id=user_id, action=action, entity_type=entity_type,
              entity_id=entity_id, request_id=correlation_id, before=before)


def _count(conn: Conn, sql: str, binds: dict) -> int:
    r = conn.execute(sql, binds).first or {}
    return int(next(iter(r.values()), 0) or 0)


# ---------------------------------------------------------------- licences
def delete_license(conn: Conn, lid: int, user_id: int, cid: str | None, before: Any) -> dict:
    row = conn.execute("SELECT license_id, status FROM licenses WHERE license_id = :p_id FOR UPDATE",
                       {"p_id": lid}).first
    if not row:
        raise AppError(404, "NOT_FOUND", "License not found.")
    was_live = str(row["STATUS"]) in ("ACTIVE", "SUSPENDED")
    conn.execute("UPDATE license_requests SET license_id = NULL WHERE license_id = :p_id", {"p_id": lid})
    for table in ("license_activations", "license_keys", "license_renewals", "license_history"):
        conn.execute(f"DELETE FROM {table} WHERE license_id = :p_id", {"p_id": lid})
    conn.execute("DELETE FROM notification_events WHERE entity_type = 'LICENSE' AND entity_id = :p_id", {"p_id": lid})
    conn.execute("DELETE FROM licenses WHERE license_id = :p_id", {"p_id": lid})
    _cancel_pending(conn, "LICENSE", lid)
    _audit(conn, user_id, "LICENSE_DELETED", "LICENSE", lid, cid, before)
    if was_live:
        # Running installations stop at once, exactly as for a revoke.
        push_live(lid, {"type": "license.revoked", "reason": "This licence has been deleted. Please contact Karnex."})
    return {"licenseId": lid, "deleted": True}


# ---------------------------------------------------------------- products
def delete_product(conn: Conn, pid: int, user_id: int, cid: str | None, before: Any) -> dict:
    if not conn.execute("SELECT 1 FROM products WHERE product_id = :p_id FOR UPDATE", {"p_id": pid}).first:
        raise AppError(404, "NOT_FOUND", "Product not found.")
    n = _count(conn, "SELECT COUNT(*) AS n FROM licenses WHERE product_id = :p_id", {"p_id": pid})
    if n > 0:
        raise AppError(
            409, "PRODUCT_HAS_LICENSES",
            f"This product has {n} licence{'' if n == 1 else 's'}. Delete {'it' if n == 1 else 'them'} first "
            "(All Licences → Delete), then delete the product.",
        )
    conn.execute("UPDATE license_requests SET product_id = NULL, plan_id = NULL WHERE product_id = :p_id", {"p_id": pid})
    conn.execute(
        """UPDATE license_requests SET plan_id = NULL
            WHERE plan_id IN (SELECT plan_id FROM product_plans WHERE product_id = :p_id)""",
        {"p_id": pid},
    )
    conn.execute(
        """UPDATE api_request_logs SET client_id = NULL
            WHERE client_id IN (SELECT client_id FROM api_clients WHERE product_id = :p_id)""",
        {"p_id": pid},
    )
    conn.execute("DELETE FROM api_clients WHERE product_id = :p_id", {"p_id": pid})
    conn.execute("DELETE FROM product_plans WHERE product_id = :p_id", {"p_id": pid})
    conn.execute("DELETE FROM products WHERE product_id = :p_id", {"p_id": pid})
    _cancel_pending(conn, "PRODUCT", pid)
    _audit(conn, user_id, "PRODUCT_DELETED", "PRODUCT", pid, cid, before)
    return {"productId": pid, "deleted": True}


# ---------------------------------------------------------------- activations
def delete_activation(conn: Conn, aid: int, user_id: int, cid: str | None, before: Any) -> dict:
    from .live_channel import publish_to_installation

    row = conn.execute(
        "SELECT license_id, installation_id, status FROM license_activations WHERE activation_id = :p_id FOR UPDATE",
        {"p_id": aid},
    ).first
    if not row:
        raise AppError(404, "NOT_FOUND", "Activation not found.")
    lid = int(row["LICENSE_ID"])
    if row["STATUS"] == "ACTIVE":
        conn.execute(
            """UPDATE licenses SET current_activations = GREATEST(current_activations - 1, 0), updated_at = now()
                WHERE license_id = :p_id""",
            {"p_id": lid},
        )
    conn.execute("DELETE FROM license_activations WHERE activation_id = :p_id", {"p_id": aid})
    _cancel_pending(conn, "ACTIVATION", aid)
    _audit(conn, user_id, "ACTIVATION_DELETED", "ACTIVATION", aid, cid, before)
    if row["STATUS"] == "ACTIVE":
        publish_to_installation(lid, str(row["INSTALLATION_ID"]), {
            "type": "activation.deactivated", "reason": "This installation was removed by the administrator.",
        })
    return {"activationId": aid, "deleted": True}


# ---------------------------------------------------------------- renewals
def delete_renewal(conn: Conn, rid: int, user_id: int, cid: str | None, before: Any) -> dict:
    """Removes the renewal record only; the licence keeps its current plan and expiry."""
    r = conn.execute("DELETE FROM license_renewals WHERE renewal_id = :p_id", {"p_id": rid})
    if (r.rows_affected or 0) == 0:
        raise AppError(404, "NOT_FOUND", "Renewal not found.")
    _audit(conn, user_id, "RENEWAL_DELETED", "RENEWAL", rid, cid, before)
    return {"renewalId": rid, "deleted": True}


# ---------------------------------------------------------------- API clients
def delete_api_client(conn: Conn, cid_: int, user_id: int, cid: str | None, before: Any) -> dict:
    if not conn.execute("SELECT 1 FROM api_clients WHERE client_id = :p_id FOR UPDATE", {"p_id": cid_}).first:
        raise AppError(404, "NOT_FOUND", "API client not found.")
    conn.execute("UPDATE api_request_logs SET client_id = NULL WHERE client_id = :p_id", {"p_id": cid_})
    conn.execute("DELETE FROM api_clients WHERE client_id = :p_id", {"p_id": cid_})
    _cancel_pending(conn, "API_CLIENT", cid_)
    _audit(conn, user_id, "API_CLIENT_DELETED", "API_CLIENT", cid_, cid, before)
    return {"clientId": cid_, "deleted": True}


# ---------------------------------------------------------------- licence requests
def delete_license_request(conn: Conn, rid: int, user_id: int, cid: str | None, before: Any) -> dict:
    """Removes the request record. A licence it already produced stays (delete it separately)."""
    r = conn.execute("DELETE FROM license_requests WHERE request_id = :p_id", {"p_id": rid})
    if (r.rows_affected or 0) == 0:
        raise AppError(404, "NOT_FOUND", "Request not found.")
    conn.execute(
        "DELETE FROM notification_events WHERE entity_type = 'LICENSE_REQUEST' AND entity_id = :p_id", {"p_id": rid}
    )
    _audit(conn, user_id, "LICENSE_REQUEST_DELETED", "LICENSE_REQUEST", rid, cid, before)
    return {"requestId": rid, "deleted": True}


# ---------------------------------------------------------------- email outbox
def delete_email(conn: Conn, eid: int, user_id: int, cid: str | None, before: Any) -> dict:
    r = conn.execute("DELETE FROM email_outbox WHERE email_id = :p_id", {"p_id": eid})
    if (r.rows_affected or 0) == 0:
        raise AppError(404, "NOT_FOUND", "Message not found.")
    _audit(conn, user_id, "EMAIL_DELETED", "EMAIL", eid, cid, before)
    return {"emailId": eid, "deleted": True}


DELETE_OPS: dict[str, Callable[[Conn, int, int, str | None, Any], dict]] = {
    "LICENSE_DELETE": delete_license,
    "PRODUCT_DELETE": delete_product,
    "ACTIVATION_DELETE": delete_activation,
    "RENEWAL_DELETE": delete_renewal,
    "API_CLIENT_DELETE": delete_api_client,
    "LICENSE_REQUEST_DELETE": delete_license_request,
    "EMAIL_DELETE": delete_email,
}


def governed_delete(ctx: Any, entity_type: str, entity_id: int, operation: str, summary: str, before: Any):
    """Route helper: submit the delete through maker-checker and build the HTTP response."""
    from ..respond import ok, pending_approval
    from .governance import submit_or_apply

    result = submit_or_apply(ctx, {
        "entityType": entity_type,
        "entityId": entity_id,
        "operation": operation,
        "summary": summary,
        "payload": {},
        "before": before,
    })
    if not result.get("applied"):
        return pending_approval(result.get("requestId"), summary)
    return ok(result.get("data"))
