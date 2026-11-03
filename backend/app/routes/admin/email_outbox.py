"""
/api/v1/admin/email-outbox — the email outbox screen.

Every outgoing message is written to EMAIL_OUTBOX before any delivery is
attempted (see services/mailer.py), so this is both the delivery log and —
while SMTP is unconfigured — the only place the messages can be read. That is
why the detail endpoint returns the full body.

Read-only apart from retry, and retry is not routed through submit_or_apply:
re-attempting a message that was already composed changes no business data.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from ...db import Binds, transaction
from ...deps import Ctx, require
from ...errors import AppError
from ...query import id_param, paged_query, parse_list, parse_sort, qs, qs_enum, to_camel
from ...respond import ok
from ...services.audit import log_audit
from ...services.mailer import retry

router = APIRouter()

SELECT = """SELECT o.email_id, o.to_address, o.subject, o.template, o.related_type,
       o.related_id, o.status, o.attempts, o.error_message, o.created_at, o.sent_at"""

FROM = "FROM email_outbox o"

SORT_WHITELIST = {
    "emailId": "o.email_id",
    "toAddress": "o.to_address",
    "status": "o.status",
    "template": "o.template",
    "createdAt": "o.created_at",
    "sentAt": "o.sent_at",
}


@router.get("")
def list_outbox(ctx: Ctx = Depends(require("EMAIL_OUTBOX_VIEW"))):
    q = ctx.query
    pp = parse_list(q)
    # Newest first: an operator chasing a message that has just gone out
    # should not have to page to the end.
    order_by = parse_sort(qs(q, "sort"), SORT_WHITELIST, "o.email_id DESC")
    where = ["1=1"]
    binds: Binds = {}

    status = qs_enum(q, "status", ["QUEUED", "SENT", "FAILED", "SKIPPED"])
    if status:
        where.append("o.status = :p_status")
        binds["p_status"] = status
    text = qs(q, "q")
    if text:
        where.append(
            """(UPPER(o.to_address) LIKE '%' || UPPER(:p_q) || '%'
            OR UPPER(o.subject) LIKE '%' || UPPER(:p_q) || '%')"""
        )
        binds["p_q"] = text

    with transaction() as conn:
        data = paged_query(
            conn,
            select=SELECT,
            from_where=f"{FROM} WHERE {' AND '.join(where)}",
            binds=binds,
            order_by=order_by,
            page=pp.page,
            page_size=pp.page_size,
        )
    return ok(data)


@router.get("/{id}")
def get_message(id: str, ctx: Ctx = Depends(require("EMAIL_OUTBOX_VIEW"))):
    eid = id_param(id)
    with transaction() as conn:
        r = conn.execute(
            """SELECT o.email_id, o.to_address, o.subject, o.body_text, o.template,
                  o.related_type, o.related_id, o.status, o.attempts, o.error_message,
                  o.created_at, o.sent_at
             FROM email_outbox o WHERE o.email_id = :p_id""",
            {"p_id": eid},
        )
        found = r.first
        if not found:
            raise AppError(404, "NOT_FOUND", "Outbox message not found.")
    return ok(to_camel(found))


@router.post("/{id}/retry")
def retry_message(id: str, ctx: Ctx = Depends(require("REQUEST_LICENSE_MANAGE"))):
    eid = id_param(id)
    user = ctx.user
    assert user is not None
    with transaction() as conn:
        result: dict[str, Any] = retry(conn, eid)
        log_audit(
            conn,
            user_id=user.user_id,
            action="EMAIL_RETRIED",
            entity_type="EMAIL_OUTBOX",
            entity_id=eid,
            request_id=ctx.request_id,
            ip=ctx.ip,
            after={"status": result["status"], "delivered": result["delivered"]},
        )
    return ok({"emailId": eid, **result})


# ---- Delete (maker-checker: admin applies at once, a maker's delete waits in Approvals)
@router.delete("/{id}")
def delete_message(id: str, ctx: Ctx = Depends(require("EMAIL_OUTBOX_VIEW"))):
    from ...query import id_param as _id
    from ...services.deletes import governed_delete

    eid = _id(id)
    with transaction() as conn:
        row = conn.execute(
            "SELECT email_id, to_address, subject, template, status, created_at FROM email_outbox WHERE email_id = :p_id",
            {"p_id": eid},
        ).first
    if not row:
        raise AppError(404, "NOT_FOUND", "Message not found.")
    summary = f"Delete e-mail to {row['TO_ADDRESS']}: {str(row['SUBJECT'])[:120]}"
    before = {"emailId": eid, "toAddress": row["TO_ADDRESS"], "subject": row["SUBJECT"],
              "template": row["TEMPLATE"], "status": row["STATUS"]}
    return governed_delete(ctx, "EMAIL", eid, "EMAIL_DELETE", summary, before)
