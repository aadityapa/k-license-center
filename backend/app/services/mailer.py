"""
Outgoing email.

Every message is written to EMAIL_OUTBOX first, then sent. That ordering is
deliberate: the flow works end to end before SMTP credentials exist (messages
simply stay QUEUED and are previewable in the admin UI), and once credentials
are set there is still a durable record of what was sent to whom.

Configure by setting SMTP_HOST / SMTP_PORT / SMTP_USER / SMTP_PASSWORD /
MAIL_FROM in backend/.env. With SMTP_HOST unset the mailer runs in queue-only
mode and says so in the logs rather than pretending to deliver.

Messages are plain dicts with the keys of the previous MailMessage interface:
``{"to", "subject", "body", "template", "relatedType"?, "relatedId"?}``.
"""
from __future__ import annotations

import re
import smtplib
import socket
import ssl
import threading
import time
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Any

from ..config import config
from ..db import OUT, Conn, transaction
from ..errors import AppError
from ..logger import logger

MailMessage = dict  # {"to", "subject", "body", "template", "relatedType"?, "relatedId"?}

_SMTP_TIMEOUT_S = 60


def _ehlo_name() -> str:
    """The EHLO name nodemailer used: the host name when it is dotted, else [127.0.0.1].
    (smtplib's default, socket.getfqdn(), can block for seconds on a reverse DNS lookup.)"""
    try:
        name = socket.gethostname() or ""
    except OSError:
        name = ""
    if "." not in name:
        return "[127.0.0.1]"
    if re.fullmatch(r"[0-9.]+|[0-9a-fA-F:]+", name):
        return f"[{name}]"
    return name


@dataclass
class _Transport:
    host: str
    port: int
    secure: bool
    user: str
    password: str

    def send_mail(self, *, sender: str, to: str, subject: str, text: str) -> None:
        """One message over SMTP: implicit TLS on 465, otherwise STARTTLS when the server offers it."""
        msg = EmailMessage()
        msg["From"] = sender
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(text, charset="utf-8")
        ctx = ssl.create_default_context()
        name = _ehlo_name()
        if self.secure:
            smtp: smtplib.SMTP = smtplib.SMTP_SSL(
                self.host, self.port, local_hostname=name, timeout=_SMTP_TIMEOUT_S, context=ctx
            )
        else:
            smtp = smtplib.SMTP(self.host, self.port, local_hostname=name, timeout=_SMTP_TIMEOUT_S)
        try:
            smtp.ehlo()
            if not self.secure and smtp.has_extn("starttls"):
                smtp.starttls(context=ctx)
                smtp.ehlo()
            if self.user:
                smtp.login(self.user, self.password)
            smtp.send_message(msg)
        finally:
            try:
                smtp.quit()
            except Exception:  # noqa: BLE001 - the connection may already be gone
                try:
                    smtp.close()
                except Exception:  # noqa: BLE001
                    pass


_transporter: _Transport | None = None
_warned_unconfigured = False
_lock = threading.Lock()


def _get_transport() -> _Transport | None:
    """None when SMTP is not configured — callers then leave the message queued."""
    global _transporter, _warned_unconfigured
    if not config.smtp.host:
        with _lock:
            if not _warned_unconfigured:
                logger.warn(
                    "SMTP is not configured (SMTP_HOST unset) — emails will be queued in EMAIL_OUTBOX "
                    "and visible in the admin UI, but not delivered. Set SMTP_* in .env to send."
                )
                _warned_unconfigured = True
        return None
    with _lock:
        if _transporter is None:
            _transporter = _Transport(
                host=config.smtp.host,
                port=config.smtp.port,
                secure=config.smtp.port == 465,
                user=config.smtp.user,
                password=config.smtp.password,
            )
        return _transporter


def _err_message(err: BaseException) -> str:
    return str(err)[:1000]


def send_mail(conn: Conn, msg: MailMessage) -> int:
    """
    Queues a message and attempts delivery. Never throws: a mail failure must not
    roll back the business transaction that triggered it (a licence is still
    issued even if the notification bounces). Failures are recorded on the row.
    """
    r = conn.execute(
        """INSERT INTO email_outbox (to_address, subject, body_text, template, related_type, related_id, status)
     VALUES (:p_to, :p_subject, :p_body, :p_template, :p_rel_type, :p_rel_id, 'QUEUED')
     RETURNING email_id AS o_id""",
        {
            "p_to": msg["to"],
            "p_subject": str(msg["subject"])[:300],
            "p_body": msg["body"],
            "p_template": msg["template"],
            "p_rel_type": msg.get("relatedType"),
            "p_rel_id": msg.get("relatedId"),
            "o_id": OUT,
        },
    )
    email_id = int(r.out_binds.get("o_id") or 0)

    transport = _get_transport()
    if transport is None:
        return email_id

    # Deliver outside the caller's transaction so a slow SMTP server cannot hold
    # a database row lock. Status is updated on its own connection.
    to, subject, body, template = msg["to"], msg["subject"], msg["body"], msg["template"]

    def record(sql: str, binds: dict[str, Any]) -> None:
        # The row was inserted by the caller's still-open transaction; a fast SMTP
        # answer can arrive before that commits, so wait (briefly) until it is visible.
        for _ in range(100):
            with transaction() as c:
                if c.execute(sql, binds).rows_affected > 0:
                    return
            time.sleep(0.1)

    def deliver() -> None:
        try:
            transport.send_mail(sender=config.smtp.sender, to=to, subject=subject, text=body)
            record(
                """UPDATE email_outbox SET status = 'SENT', sent_at = now(), attempts = attempts + 1
            WHERE email_id = :p_id""",
                {"p_id": email_id},
            )
            logger.info("email sent", emailId=email_id, to=to, template=template)
        except Exception as err:  # noqa: BLE001
            message = _err_message(err)
            logger.error("email delivery failed", exc=True, emailId=email_id)
            try:
                record(
                    """UPDATE email_outbox SET status = 'FAILED', attempts = attempts + 1, error_message = :p_err
            WHERE email_id = :p_id""",
                    {"p_err": message, "p_id": email_id},
                )
            except Exception:  # noqa: BLE001
                pass

    threading.Thread(target=deliver, daemon=True).start()
    return email_id


def retry(conn: Conn, email_id: int) -> dict[str, Any]:
    """
    Re-attempts delivery of one already-queued message. Unlike send_mail this is
    synchronous from the caller's point of view: the admin pressed "retry" and
    wants to be told what happened, so the outcome is reported rather than
    fire-and-forget. Returns SKIPPED (not SENT) when SMTP is unconfigured, so the
    UI never claims a delivery that could not have happened.

    Returns ``{"delivered": bool, "status": "SENT"|"FAILED"|"SKIPPED", "message": str}``.
    """
    r = conn.execute(
        """SELECT email_id, to_address, subject, body_text, template, status
       FROM email_outbox WHERE email_id = :p_id""",
        {"p_id": email_id},
    )
    row = r.first
    if not row:
        raise AppError(404, "NOT_FOUND", "Outbox message not found.")
    status = str(row["STATUS"])
    if status not in ("FAILED", "QUEUED"):
        raise AppError(409, "CONFLICT", f"Only a FAILED or QUEUED message can be retried; this one is {status}.")

    transport = _get_transport()
    if transport is None:
        conn.execute(
            """UPDATE email_outbox SET status = 'SKIPPED', error_message = :p_err
        WHERE email_id = :p_id""",
            {
                "p_err": "SMTP is not configured (SMTP_HOST unset) — nothing was sent.",
                "p_id": email_id,
            },
        )
        return {
            "delivered": False,
            "status": "SKIPPED",
            "message": (
                "SMTP is not configured (SMTP_HOST is unset), so nothing was sent. "
                "Set SMTP_HOST / SMTP_PORT / SMTP_USER / SMTP_PASSWORD in backend/.env and retry."
            ),
        }

    try:
        transport.send_mail(
            sender=config.smtp.sender,
            to=str(row["TO_ADDRESS"]),
            subject=str(row["SUBJECT"]),
            text=str(row["BODY_TEXT"] if row["BODY_TEXT"] is not None else ""),
        )
        conn.execute(
            """UPDATE email_outbox SET status = 'SENT', sent_at = now(), attempts = attempts + 1,
              error_message = NULL
        WHERE email_id = :p_id""",
            {"p_id": email_id},
        )
        logger.info("email re-sent after retry", emailId=email_id, template=row["TEMPLATE"])
        return {"delivered": True, "status": "SENT", "message": f"Message delivered to {row['TO_ADDRESS']}."}
    except Exception as err:  # noqa: BLE001
        message = _err_message(err)
        logger.error("email retry failed", exc=True, emailId=email_id)
        conn.execute(
            """UPDATE email_outbox SET status = 'FAILED', attempts = attempts + 1, error_message = :p_err
        WHERE email_id = :p_id""",
            {"p_err": message, "p_id": email_id},
        )
        return {"delivered": False, "status": "FAILED", "message": f"Delivery failed again: {message}"}


# ------------------------------------------------------------------ templates

SIGNATURE = "\n\n—\nKarnex Licence Desk\nThis is an automated message."


def invite_email(opts: dict[str, Any]) -> MailMessage:
    """opts: {to, productName, link, expiresHours, invitedBy?}"""
    invited_by = opts.get("invitedBy")
    who = f"{invited_by} has invited you to" if invited_by else "You asked to"
    return {
        "to": opts["to"],
        "template": "REQUEST_INVITE",
        "subject": f"Complete your {opts['productName']} licence request",
        "body": (
            f"Hello,\n\n{who} request a licence for {opts['productName']}.\n\n"
            "Please complete your details using the link below. It is personal to you and "
            f"expires in {_js_str(opts['expiresHours'])} hours:\n\n{opts['link']}\n\n"
            "You will be asked for your company name, domain, contact number and basic "
            "details of the system you plan to install on."
            + SIGNATURE
        ),
    }


def license_issued_email(opts: dict[str, Any]) -> MailMessage:
    """opts: {to, productName, planName, licenseKey, licenseNo, expiryDate, maxActivations}"""
    expiry = f"Valid until: {opts['expiryDate']}" if opts.get("expiryDate") else "Validity: no expiry (lifetime)"
    if not opts.get("licenseKey"):
        # Signed-key products: the key is made for the customer's PC, from inside the app.
        return {
            "to": opts["to"],
            "template": "LICENSE_ISSUED",
            "subject": f"Your {opts['productName']} licence",
            "body": (
                f"Hello,\n\nYour {opts['productName']} licence is ready.\n\n"
                f"Licence number : {opts['licenseNo']}\n"
                f"Plan           : {opts['planName']}\n"
                f"{expiry}\n"
                f"Activations    : up to {_js_str(opts['maxActivations'])}\n\n"
                f"To activate, open {opts['productName']} on the computer, choose Licence -> "
                "Sync automatically and send the request (or press Sync now). The licence key is "
                "made for that computer and activates by itself."
                + SIGNATURE
            ),
        }
    return {
        "to": opts["to"],
        "template": "LICENSE_ISSUED",
        "subject": f"Your {opts['productName']} licence key",
        "body": (
            f"Hello,\n\nYour {opts['productName']} licence is ready.\n\n"
            f"Licence number : {opts['licenseNo']}\n"
            f"Plan           : {opts['planName']}\n"
            f"Licence key    : {opts['licenseKey']}\n"
            f"{expiry}\n"
            f"Activations    : up to {_js_str(opts['maxActivations'])}\n\n"
            f"Enter this key in {opts['productName']} to activate your installation. "
            "Keep it safe — anyone with the key can use one of your activation slots."
            + SIGNATURE
        ),
    }


def request_received_email(opts: dict[str, Any]) -> MailMessage:
    """opts: {to, productName, planName}"""
    return {
        "to": opts["to"],
        "template": "REQUEST_RECEIVED",
        "subject": f"We have received your {opts['productName']} licence request",
        "body": (
            f"Hello,\n\nThank you — we have received your request for {opts['productName']} "
            f"on the {opts['planName']} plan.\n\n"
            "Our team will review the details and come back to you. You do not need to do "
            "anything further for now."
            + SIGNATURE
        ),
    }


def request_rejected_email(opts: dict[str, Any]) -> MailMessage:
    """opts: {to, productName, reason}"""
    return {
        "to": opts["to"],
        "template": "REQUEST_REJECTED",
        "subject": f"About your {opts['productName']} licence request",
        "body": (
            f"Hello,\n\nWe are unable to proceed with your {opts['productName']} licence request "
            f"at this time.\n\nReason: {opts['reason']}\n\n"
            "If you believe this is a mistake, please reply to your account contact at Karnex."
            + SIGNATURE
        ),
    }


def _js_str(v: Any) -> str:
    """String(n) for the numbers interpolated into templates (72, not 72.0)."""
    if isinstance(v, float):
        if v != v:
            return "NaN"
        if v.is_integer():
            return str(int(v))
    return str(v)
