"""/api/v1/admin/change-requests — the maker-checker approval queue."""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends

from ... import schema as z
from ...db import Binds, Conn, Row, transaction
from ...deps import Ctx, json_body, require
from ...errors import AppError, db_error_code
from ...query import id_param, paged_query, parse_list, parse_sort, qs, qs_enum, to_camel
from ...respond import ok
from ...services.audit import log_audit
from ...services.governance import apply_change

SELECT = """SELECT cr.request_id, cr.entity_type, cr.entity_id, cr.operation, cr.summary,
       cr.status, cr.requested_by, cr.requested_at, cr.request_note,
       cr.reviewed_by, cr.reviewed_at, cr.review_comment, cr.applied_at, cr.error_message,
       ru.username AS requested_by_name, vu.username AS reviewed_by_name"""

FROM = """FROM change_requests cr
  JOIN users ru ON ru.user_id = cr.requested_by
  LEFT JOIN users vu ON vu.user_id = cr.reviewed_by"""

SORT_WHITELIST = {
    "requestId": "cr.request_id",
    "requestedAt": "cr.requested_at",
    "status": "cr.status",
    "entityType": "cr.entity_type",
}

review_schema = z.object({"comment": z.string().max(1000).optional()})
reject_schema = review_schema.extend({"comment": z.string().min(3).max(1000)})


def load_request(conn: Conn, id: int) -> Row:
    """Reads one request with its payload, or 404s."""
    r = conn.execute(
        """SELECT cr.*, ru.username AS requested_by_name
       FROM change_requests cr JOIN users ru ON ru.user_id = cr.requested_by
      WHERE cr.request_id = :p_id""",
        {"p_id": id},
    )
    row = r.first
    if not row:
        raise AppError(404, "NOT_FOUND", "Change request not found.")
    return row


def _num(v: Any) -> Any:
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return v
    try:
        f = float(str(v))
        return int(f) if f.is_integer() else f
    except ValueError:
        return float("nan")


def _error_message(err: BaseException) -> str:
    """err.message as Node saw it: the AppError text, or the database's primary message."""
    if isinstance(err, AppError):
        return err.message
    code, msg = db_error_code(err)
    if code or msg:
        return msg
    return str(err)


router = APIRouter()


@router.get("")
def list_requests(ctx: Ctx = Depends(require("REQUEST_VIEW"))):
    q_ = ctx.query
    pp = parse_list(q_)
    order_by = parse_sort(qs(q_, "sort"), SORT_WHITELIST, "cr.request_id DESC")
    where: list[str] = ["1=1"]
    binds: Binds = {}

    status = qs_enum(q_, "status", ["PENDING", "APPROVED", "REJECTED", "CANCELLED", "FAILED"])
    if status:
        where.append("cr.status = :p_status")
        binds["p_status"] = status
    entity_type = qs(q_, "entityType")
    if entity_type:
        where.append("cr.entity_type = :p_entity_type")
        binds["p_entity_type"] = entity_type
    # "mine=1" scopes the list to the caller's own submissions.
    if qs(q_, "mine") == "1":
        where.append("cr.requested_by = :p_me")
        binds["p_me"] = ctx.user.user_id  # type: ignore[union-attr]

    with transaction() as conn:
        paged = paged_query(
            conn,
            select=SELECT,
            from_where=f"{FROM} WHERE {' AND '.join(where)}",
            binds=binds,
            order_by=order_by,
            page=pp.page,
            page_size=pp.page_size,
        )
        count_res = conn.execute("SELECT COUNT(*) AS pending FROM change_requests WHERE status = 'PENDING'")
        pending = (count_res.first or {}).get("PENDING")
        data = {**paged, "pendingTotal": _num(pending if pending is not None else 0)}
    return ok(data)


@router.get("/{id}")
def get_one(id: str, ctx: Ctx = Depends(require("REQUEST_VIEW"))):
    rid = id_param(id)
    with transaction() as conn:
        row = load_request(conn, rid)
        item = to_camel(row)
        # Stored as TEXT; parsed for the diff view.
        item["payload"] = json.loads(str(row["PAYLOAD"])) if row.get("PAYLOAD") else None
        item["beforeState"] = json.loads(str(row["BEFORE_STATE"])) if row.get("BEFORE_STATE") else None
    return ok(item)


@router.post("/{id}/approve")
def approve(id: str, ctx: Ctx = Depends(require("REQUEST_APPROVE")), body: Any = Depends(json_body)):
    data_in = review_schema.parse(body)
    rid = id_param(id)
    user = ctx.user
    assert user is not None
    comment = data_in.get("comment")

    failed: BaseException | None = None
    with transaction() as conn:
        # Lock so two checkers cannot approve the same request concurrently.
        lock_res = conn.execute(
            """SELECT request_id, status, requested_by, entity_type, entity_id, operation, summary, payload, before_state
             FROM change_requests WHERE request_id = :p_id FOR UPDATE""",
            {"p_id": rid},
        )
        row = lock_res.first
        if not row:
            raise AppError(404, "NOT_FOUND", "Change request not found.")
        if row["STATUS"] != "PENDING":
            raise AppError(409, "CONFLICT", f"This request is already {str(row['STATUS']).lower()}.")
        # Separation of duties: never approve your own submission.
        if _num(row["REQUESTED_BY"]) == user.user_id:
            raise AppError(
                403,
                "FORBIDDEN",
                "You cannot approve a change you submitted yourself. Another checker must review it.",
            )

        entity_id = None if row["ENTITY_ID"] is None else _num(row["ENTITY_ID"])
        intent: dict[str, Any] = {
            "entityType": str(row["ENTITY_TYPE"]),
            "entityId": entity_id,
            "operation": str(row["OPERATION"]),
            "summary": str(row["SUMMARY"]),
            "payload": json.loads(str(row["PAYLOAD"])) if row["PAYLOAD"] else {},
        }
        if row["BEFORE_STATE"]:
            intent["before"] = json.loads(str(row["BEFORE_STATE"]))

        # The apply runs under a savepoint. If it fails only its own work is
        # undone; the request row (still locked) is then marked FAILED in the
        # same transaction, which commits, and the original error is raised
        # afterwards.
        result: Any = None
        conn.execute("SAVEPOINT apply_change", {})
        try:
            result = apply_change(conn, intent, user.user_id, ctx.request_id)
            conn.execute("RELEASE SAVEPOINT apply_change", {})
        except Exception as err:  # noqa: BLE001
            conn.execute("ROLLBACK TO SAVEPOINT apply_change", {})
            message = _error_message(err)[:2000]
            conn.execute(
                """UPDATE change_requests
                SET status = 'FAILED', reviewed_by = :p_user, reviewed_at = now(),
                    review_comment = :p_comment, error_message = :p_err
              WHERE request_id = :p_id""",
                {"p_user": user.user_id, "p_comment": comment, "p_err": message, "p_id": rid},
            )
            failed = err

        if failed is None:
            conn.execute(
                """UPDATE change_requests
              SET status = 'APPROVED', reviewed_by = :p_user, reviewed_at = now(),
                  review_comment = :p_comment, applied_at = now()
            WHERE request_id = :p_id""",
                {"p_user": user.user_id, "p_comment": comment, "p_id": rid},
            )
            log_audit(
                conn,
                user_id=user.user_id,
                action="CHANGE_APPROVED",
                entity_type=str(row["ENTITY_TYPE"]),
                entity_id=entity_id,
                request_id=ctx.request_id,
                after={"changeRequestId": rid, "operation": intent["operation"], "result": result},
            )
            data = {"requestId": rid, "status": "APPROVED", "result": result}
    if failed is not None:
        raise failed
    return ok(data)


@router.post("/{id}/reject")
def reject(id: str, ctx: Ctx = Depends(require("REQUEST_APPROVE")), body: Any = Depends(json_body)):
    data_in = reject_schema.parse(body)
    rid = id_param(id)
    user = ctx.user
    assert user is not None
    comment = data_in["comment"]
    with transaction() as conn:
        row = load_request(conn, rid)
        if row["STATUS"] != "PENDING":
            raise AppError(409, "CONFLICT", f"This request is already {str(row['STATUS']).lower()}.")
        if _num(row["REQUESTED_BY"]) == user.user_id:
            raise AppError(403, "FORBIDDEN", "You cannot review a change you submitted yourself.")
        conn.execute(
            """UPDATE change_requests
              SET status = 'REJECTED', reviewed_by = :p_user, reviewed_at = now(),
                  review_comment = :p_comment
            WHERE request_id = :p_id""",
            {"p_user": user.user_id, "p_comment": comment, "p_id": rid},
        )
        log_audit(
            conn,
            user_id=user.user_id,
            action="CHANGE_REJECTED",
            entity_type=str(row["ENTITY_TYPE"]),
            entity_id=None if row["ENTITY_ID"] is None else _num(row["ENTITY_ID"]),
            request_id=ctx.request_id,
            after={"changeRequestId": rid, "comment": comment},
        )
    return ok({"requestId": rid, "status": "REJECTED"})


@router.post("/{id}/cancel")
def cancel(id: str, ctx: Ctx = Depends(require("REQUEST_SUBMIT"))):
    """A maker may withdraw their own pending request."""
    rid = id_param(id)
    user = ctx.user
    assert user is not None
    with transaction() as conn:
        row = load_request(conn, rid)
        if _num(row["REQUESTED_BY"]) != user.user_id:
            raise AppError(403, "FORBIDDEN", "You can only cancel your own requests.")
        if row["STATUS"] != "PENDING":
            raise AppError(409, "CONFLICT", "Only pending requests can be cancelled.")
        conn.execute(
            """UPDATE change_requests SET status = 'CANCELLED', reviewed_at = now()
            WHERE request_id = :p_id""",
            {"p_id": rid},
        )
    return ok({"requestId": rid, "status": "CANCELLED"})


# ---- Delete (maker-checker: admin applies at once, a maker's delete waits in Approvals)
@router.delete("/{id}")
def delete_one(id: str, ctx: Ctx = Depends(require("REQUEST_APPROVE"))):
    """Remove a finished approval record from the history (admin only). Pending
    requests must be approved, rejected or cancelled first."""
    rid = id_param(id)
    if not ctx.has("APPROVAL_BYPASS"):
        raise AppError(403, "FORBIDDEN", "Only an administrator can delete approval history.")
    with transaction() as conn:
        row = load_request(conn, rid)  # 404s
        if row["STATUS"] == "PENDING":
            raise AppError(409, "REQUEST_PENDING",
                           "This request is still waiting for a decision. Approve, reject or cancel it first.")
        conn.execute("DELETE FROM change_requests WHERE request_id = :p_id", {"p_id": rid})
        log_audit(conn, user_id=ctx.user.user_id, action="CHANGE_REQUEST_DELETED", entity_type="CHANGE_REQUEST",
                  entity_id=rid, request_id=ctx.request_id,
                  before={"operation": row["OPERATION"], "summary": row["SUMMARY"], "status": row["STATUS"]})
    return ok({"requestId": rid, "deleted": True})
