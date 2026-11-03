"""
A customer may type the short licence key shown in the portal (VSIM-XXXX-XXXX-XXXX) into Vehicle SIM
or KSTACK. Those apps run on signed keys, so /license/redeem-key exchanges the short key for the
signed key of that computer.
"""
from __future__ import annotations

import pytest

from support import KSTACK, VEHSIM, active_key, create_licence, data, machine_id

pytestmark = pytest.mark.integration
API = "/api/v1"


def _redeem(client, key: str, mid: str, headers=VEHSIM, product: str = "VEHICLESIM"):
    return client.post(f"{API}/license/redeem-key", headers=headers, json={
        "productCode": product, "licenseKey": key, "installationId": mid, "deviceName": "BENCH-PC",
    })


def test_signed_key_products_get_no_temporary_key(client, login):
    """Migration 009: activating a Vehicle SIM / KSTACK licence mints no PREF-XXXX key."""
    admin = login("admin")
    lid = create_licence(client, admin, "VEHICLESIM", amount=1000)
    keys = data(client.get(f"{API}/admin/license-keys?licenseId={lid}", headers={"authorization": f"Bearer {admin}"}))
    assert keys["items"] == []


def test_short_key_is_exchanged_for_this_computers_signed_key(client, login, db):
    admin = login("admin")
    lid = create_licence(client, admin, "VEHICLESIM", amount=1000)
    # A licence from before migration 009 still carries a short key.
    short = db("SELECT pkg_license_key.generate_key(%s, NULL, NULL, 'N') AS k", (lid,))[0]["k"]
    mid = machine_id()

    r = _redeem(client, f"  {short.lower()} ", mid)
    assert r.status_code == 200, r.text
    signed = data(r)["licenseKey"]
    assert data(r)["redeemed"] is True and "." in signed and len(signed) > 40

    # The signed key activates on that computer.
    act = client.post(f"{API}/license/activate", headers=VEHSIM, json={
        "licenseKey": signed, "productCode": "VEHICLESIM", "installationId": mid, "machineFingerprint": mid,
        "deviceName": "BENCH-PC", "appVersion": "1.0.0",
    })
    assert act.status_code == 200 and data(act)["authorized"] is True, act.text

    # Same computer again (e.g. reinstall): gets its signed key back.
    again = _redeem(client, short, mid)
    assert again.status_code == 200 and data(again)["licenseKey"] == signed and data(again)["redeemed"] is False

    # Another computer: refused.
    other = _redeem(client, short, machine_id())
    assert other.status_code == 409 and other.json()["error"]["code"] == "KEY_REVOKED"


def test_unknown_key_wrong_product_and_lic_file_products(client, login, db):
    assert _redeem(client, "VSIM-AAAA-BBBB-CCCC", machine_id()).status_code == 404
    assert _redeem(client, "VSIM-AAAA-BBBB", machine_id()).status_code == 400          # not a short key
    assert _redeem(client, "VSIM-AAAA-BBBB-CCCC", machine_id(), product="KSTACK").status_code == 400

    # A product that uses .lic files has nothing to exchange.
    db("UPDATE products SET key_format = 'LIC_FILE' WHERE product_code = 'KSTACK'")
    admin = login("admin")
    lid = create_licence(client, admin, "KSTACK", amount=1000)
    short = active_key(client, admin, lid)
    r = _redeem(client, short, machine_id(), headers=KSTACK, product="KSTACK")
    assert r.status_code == 400, r.text
