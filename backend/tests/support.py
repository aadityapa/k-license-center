"""Small helpers shared by the integration tests (the port of tests/helpers/*.ts)."""
from __future__ import annotations

import json
import time
import uuid
from typing import Any

import jwt

PASSWORD = "Pass@100%"

# Product API clients from database/postgres/demo/demo_data.sql.
VEHSIM = {"x-client-key": "demo-vehsim-client", "x-client-secret": "demo-secret-vehsim"}
KSTACK = {"x-client-key": "demo-kstack-client", "x-client-secret": "demo-secret-kstack"}
KFLASH = {"x-client-key": "demo-kflash-client", "x-client-secret": "demo-secret-kflash"}
SIGNING_KEYS = {
    "KSTACK": "demo-signing-key-kstack-0123456789abcdef",
    "KFLASH": "demo-signing-key-kflash-0123456789abcdef",
    "VEHICLESIM": "demo-signing-key-vehsim-0123456789abcdef",
}


def auth(token: str) -> dict[str, str]:
    return {"authorization": f"Bearer {token}"}


def raw_token(permissions: list[str], user_id: int = 1, username: str = "admin") -> str:
    """A JWT with exactly the permissions given — nothing added (testUtils.rawToken)."""
    from app.config import config

    now = int(time.time())
    return jwt.encode(
        {"sub": str(user_id), "username": username, "permissions": permissions, "iat": now, "exp": now + 3600},
        config.jwt_secret,
        algorithm="HS256",
    )


def token_with(permissions: list[str], user_id: int = 1, username: str = "admin") -> str:
    """Like the seeded admin: APPROVAL_BYPASS is added, so governed writes apply at once (testUtils.tokenWith)."""
    perms = permissions if "APPROVAL_BYPASS" in permissions else [*permissions, "APPROVAL_BYPASS"]
    return raw_token(perms, user_id, username)


def uniq(prefix: str = "") -> str:
    """A short unique suffix, so tests do not depend on each other or on run order."""
    return f"{prefix}{uuid.uuid4().hex[:8].upper()}"


def machine_id() -> str:
    """A fresh 16-hex-digit Vehicle SIM Machine ID."""
    return uuid.uuid4().hex[:16].upper()


def mac() -> str:
    return uuid.uuid4().hex[:12].upper()


def data(res: Any) -> Any:
    return res.json()["data"]


def error(res: Any) -> dict[str, Any]:
    return res.json()["error"]


def lic_request_file(product: str, mac_address: str) -> str:
    """The customer's own .lic request file, in the shape the products write it."""
    return json.dumps({
        "Product": product,
        "Customer": "",
        "MacAddress": mac_address,
        "CPUID": "BFEBFBFF000906A4",
        "BIOS": "R5PTCJ00S00322B",
        "MotherBoardId": "R521PTCJ000PE3MB",
        "SerialKey": "",
        "Key": "",
    }, separators=(",", ":"))


def product_id(client: Any, token: str, product_code: str) -> int:
    res = client.get("/api/v1/admin/products", headers=auth(token))
    assert res.status_code == 200, res.text
    return int(next(p for p in data(res)["items"] if p["productCode"] == product_code)["productId"])


def plan_id(client: Any, token: str, prod_id: int, plan_code: str) -> int:
    res = client.get(f"/api/v1/admin/plans?productId={prod_id}&limit=50", headers=auth(token))
    assert res.status_code == 200, res.text
    return int(next(p for p in data(res)["items"] if p["planCode"] == plan_code)["planId"])


def create_licence(client: Any, token: str, product_code: str, plan_code: str = "YEARLY",
                   customer_id: int = 1, amount: float = 5000, activate: bool = True) -> int:
    """A fresh licence built through the real endpoints (ACTIVE unless activate=False)."""
    pid = product_id(client, token, product_code)
    created = client.post("/api/v1/admin/licenses", headers=auth(token), json={
        "customerId": customer_id, "productId": pid, "planId": plan_id(client, token, pid, plan_code),
        "amount": amount, "autoRenewal": False,
    })
    assert created.status_code == 201, created.text
    lid = int(data(created)["licenseId"])
    if activate:
        act = client.post(f"/api/v1/admin/licenses/{lid}/activate", headers=auth(token), json={})
        assert act.status_code == 200, act.text
    return lid


def active_key(client: Any, token: str, licence_id: int) -> str:
    res = client.get(f"/api/v1/admin/license-keys?licenseId={licence_id}&status=ACTIVE", headers=auth(token))
    assert res.status_code == 200, res.text
    items = data(res)["items"]
    assert len(items) == 1, items
    return str(items[0]["licenseKey"])
