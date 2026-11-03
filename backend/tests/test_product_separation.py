"""
Several Karnex apps (Vehicle SIM, KStack…) on one computer share its Machine ID:
requests and key collection (/public/vbs-request, /public/vbs-status) are per product.
"""
from __future__ import annotations

import pytest

from support import auth, data, machine_id

pytestmark = pytest.mark.integration


def test_requests_and_status_are_per_product(client, login, db):
    db("UPDATE products SET key_format = 'VBS_KEY' WHERE product_code = 'KSTACK'")
    try:
        mid = machine_id()
        common = {"machineId": mid, "hostName": "TWO-APPS-PC"}
        v = client.post("/api/v1/public/vbs-request", json={**common, "email": "v@two.example", "companyName": "Two Apps"},
                        headers={"x-forwarded-for": "10.9.0.1"})
        k = client.post("/api/v1/public/vbs-request",
                        json={**common, "email": "k@two.example", "companyName": "Two Apps", "productCode": "KSTACK"},
                        headers={"x-forwarded-for": "10.9.0.2"})
        assert v.status_code == 202 and k.status_code == 202
        assert data(v)["requestId"] != data(k)["requestId"]   # not merged as a duplicate

        checker = login("checker")
        r = client.post(f"/api/v1/admin/license-requests/{data(k)['requestId']}/approve", headers=auth(checker),
                        json={"planCode": "YEARLY", "amount": 10, "vbs": {"mode": 0, "edition": 2, "features": ["Can"]}})
        assert r.status_code == 200, r.text

        ks = data(client.get(f"/api/v1/public/vbs-status/{mid}", params={"productCode": "KSTACK"}))
        vs = data(client.get(f"/api/v1/public/vbs-status/{mid}"))          # default: VEHICLESIM
        assert ks["approved"] is True and ks["licenseKey"]
        assert vs["approved"] is False                                      # VehSim still waiting
    finally:
        db("UPDATE products SET key_format = 'LIC_FILE' WHERE product_code = 'KSTACK'")
