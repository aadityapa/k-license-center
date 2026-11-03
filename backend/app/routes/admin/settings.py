"""/api/v1/admin/settings — system settings (SETTINGS_MANAGE); updates go through governance."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from ... import schema as z
from ...db import transaction
from ...deps import Ctx, json_body, require
from ...errors import AppError
from ...query import rows_to_camel
from ...respond import ok, pending_approval
from ...services.settings import clear_settings_cache

router = APIRouter()

put_schema = z.object({
    "settings": z.record(z.string().min(1).max(50), z.string().min(1).max(500)),
}).refine(lambda b: len(b["settings"]) > 0, "settings must not be empty")

_LIST_SQL = "SELECT setting_key, setting_value, description, updated_at, updated_by FROM settings ORDER BY setting_key"


def _js_string(v: Any) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


@router.get("")
def get_settings(ctx: Ctx = Depends(require("SETTINGS_MANAGE"))):
    with transaction() as conn:
        items = rows_to_camel(conn.execute(_LIST_SQL).rows)
    return ok({"items": items})


@router.put("")
def update_settings(ctx: Ctx = Depends(require("SETTINGS_MANAGE")), body: Any = Depends(json_body)):
    from ...services.governance import submit_or_apply

    data = put_schema.parse(body)
    settings: dict[str, str] = data["settings"]
    keys = list(settings.keys())

    # Reject unknown keys before anything is submitted.
    with transaction() as conn:
        r = conn.execute("SELECT setting_key, setting_value FROM settings ORDER BY setting_key")
        current = {_js_string(row["SETTING_KEY"]): _js_string(row["SETTING_VALUE"]) for row in r.rows}
    for key in keys:
        if key not in current:
            raise AppError(400, "VALIDATION_ERROR", f"Unknown setting key: {key}")

    summary = f"Update {len(keys)} setting{'' if len(keys) == 1 else 's'}: {', '.join(keys)}"
    result = submit_or_apply(ctx, {
        "entityType": "SETTING",
        "operation": "SETTING_UPDATE",
        "summary": summary,
        "payload": {"settings": settings},
        "before": {k: current.get(k) for k in keys},
    })
    if not result.get("applied"):
        return pending_approval(result.get("requestId"), summary)

    with transaction() as conn:
        items = rows_to_camel(conn.execute(_LIST_SQL).rows)
    clear_settings_cache()
    return ok({"items": items})
