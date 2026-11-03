"""
The amount charged for a licence (licenses.amount, 007_license_amount.sql).
Compulsory when a licence is created or a request is approved; it is the
revenue the dashboard counts for that licence.
"""
from __future__ import annotations

import math

from .. import schema as z
from ..db import Conn

amount_field = (
    z.number(required_error="Amount is required.", invalid_type_error="Amount must be a number.")
    .nonnegative("Amount cannot be negative.")
    .max(9_999_999_999, "Amount is too large.")
)


def set_license_amount(conn: Conn, license_id: int, amount: float) -> None:
    conn.execute(
        "UPDATE licenses SET amount = :p_amount, updated_at = now() WHERE license_id = :p_license_id",
        {"p_amount": math.floor(amount * 100 + 0.5) / 100, "p_license_id": license_id},  # Math.round
    )
