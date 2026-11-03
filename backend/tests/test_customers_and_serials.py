"""
Customer create / edit / delete, the per-licence serial number and UUID, the
compulsory amount, and deleting plans and revoked keys — through the real
maker-checker path. Port of tests/customersAndSerials.test.ts.
"""
from __future__ import annotations

import re
from urllib.parse import quote

import pytest

from support import active_key, auth, create_licence, data, error, uniq

pytestmark = pytest.mark.integration

SERIAL_RE = re.compile(r"^SN-[A-Z]{4}-[A-HJ-KM-NP-Z2-9]{4}-[A-HJ-KM-NP-Z2-9]{4}$")
UUID4_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")


def _new_customer(client, token, name: str) -> int:
    code = uniq("CUST-")
    res = client.post("/api/v1/admin/customers", headers=auth(token), json={
        "customerCode": code, "companyName": name, "contactPerson": "A Person", "email": f"{code.lower()}@temp.example",
    })
    assert res.status_code == 201, res.text
    return int(data(res)["customerId"])


class TestCustomers:
    def test_creates_edits_and_deletes_a_customer_with_no_licences(self, client, login):
        admin = login("admin")
        cid = _new_customer(client, admin, "Temp Traders")

        edited = client.put(f"/api/v1/admin/customers/{cid}", headers=auth(admin), json={"city": "Pune"})
        assert edited.status_code == 200
        assert data(edited)["city"] == "Pune"

        deleted = client.delete(f"/api/v1/admin/customers/{cid}", headers=auth(admin))
        assert deleted.status_code == 200
        assert data(deleted)["deleted"] is True
        assert client.get(f"/api/v1/admin/customers/{cid}", headers=auth(admin)).status_code == 404

    def test_refuses_to_delete_a_customer_who_has_licences_and_says_why(self, client, login):
        admin = login("admin")
        res = client.delete("/api/v1/admin/customers/1", headers=auth(admin))
        assert res.status_code == 409
        assert error(res)["code"] == "CUSTOMER_HAS_LICENSES"
        assert "Inactive" in error(res)["message"]
        assert client.get("/api/v1/admin/customers/1", headers=auth(admin)).status_code == 200

    def test_a_makers_delete_waits_for_a_checker(self, client, login):
        admin = login("admin")
        cid = _new_customer(client, admin, "Duplicate Entry Ltd")
        pending = client.delete(f"/api/v1/admin/customers/{cid}", headers=auth(login("maker")))
        assert pending.status_code == 202
        assert client.get(f"/api/v1/admin/customers/{cid}", headers=auth(admin)).status_code == 200

        approved = client.post(f"/api/v1/admin/change-requests/{data(pending)['changeRequestId']}/approve",
                               headers=auth(login("checker")), json={})
        assert approved.status_code == 200
        assert client.get(f"/api/v1/admin/customers/{cid}", headers=auth(admin)).status_code == 404


class TestSerialAndUid:
    def test_every_licence_has_a_unique_serial_and_uuid_in_the_documented_formats(self, client, login):
        admin = login("admin")
        res = client.get("/api/v1/admin/licenses?pageSize=100", headers=auth(admin))
        items = data(res)["items"]
        assert len(items) > 3
        for lic in items:
            assert SERIAL_RE.match(lic["serialNo"]), lic["serialNo"]
            assert UUID4_RE.match(lic["licenseUid"]), lic["licenseUid"]
        assert len({lic["serialNo"] for lic in items}) == len(items)
        assert len({lic["licenseUid"] for lic in items}) == len(items)

    def test_a_new_licence_gets_them_with_its_products_prefix(self, client, login):
        admin = login("admin")
        created = client.post("/api/v1/admin/licenses", headers=auth(admin),
                              json={"customerId": 2, "productId": 3, "planId": 11, "amount": 15000, "autoRenewal": False})
        assert created.status_code == 201
        lic = client.get(f"/api/v1/admin/licenses/{data(created)['licenseId']}", headers=auth(admin))
        assert data(lic)["serialNo"].startswith("SN-VSIM-")
        assert re.match(r"^[0-9a-f-]{36}$", data(lic)["licenseUid"])

    def test_a_licence_can_be_found_by_serial_uuid_number_or_customer(self, client, login):
        admin = login("admin")
        one = data(client.get("/api/v1/admin/licenses?pageSize=1", headers=auth(admin)))["items"][0]
        for q in (one["serialNo"], one["serialNo"].lower(), one["licenseUid"], one["licenseNo"], one["customerName"]):
            # pageSize=100: other tests add licences for the same customer.
            found = client.get(f"/api/v1/admin/licenses?q={quote(q)}&pageSize=100", headers=auth(admin))
            assert one["licenseId"] in [lic["licenseId"] for lic in data(found)["items"]], q

    def test_refuses_a_licence_without_an_amount_and_stores_the_amount_given(self, client, login):
        admin = login("admin")
        base = {"customerId": 2, "productId": 3, "planId": 11, "autoRenewal": False}
        missing = client.post("/api/v1/admin/licenses", headers=auth(admin), json=base)
        assert missing.status_code == 400
        assert "amount" in error(missing)["message"].lower()

        negative = client.post("/api/v1/admin/licenses", headers=auth(admin), json={**base, "amount": -5})
        assert negative.status_code == 400

        created = client.post("/api/v1/admin/licenses", headers=auth(admin), json={**base, "amount": 12345.5})
        assert created.status_code == 201
        detail = client.get(f"/api/v1/admin/licenses/{data(created)['licenseId']}", headers=auth(admin))
        assert float(data(detail)["amount"]) == 12345.5


class TestDeletingPlansAndRevokedKeys:
    def test_deletes_an_unused_plan_and_refuses_a_plan_licences_use(self, client, login):
        admin = login("admin")
        plans = data(client.get("/api/v1/admin/plans?productId=1&pageSize=100", headers=auth(admin)))["items"]
        used = next(p for p in plans if p["planCode"] == "YEARLY")
        refused = client.delete(f"/api/v1/admin/plans/{used['planId']}", headers=auth(admin))
        assert refused.status_code == 409
        assert error(refused)["code"] == "PLAN_IN_USE"

        code = uniq("TMP")
        created = client.post("/api/v1/admin/plans", headers=auth(admin), json={
            "productId": 1, "planCode": code, "planName": "Temporary", "durationDays": 10, "maxActivations": 1,
        })
        assert created.status_code == 201, created.text
        deleted = client.delete(f"/api/v1/admin/plans/{data(created)['planId']}", headers=auth(admin))
        assert deleted.status_code == 200
        after = data(client.get("/api/v1/admin/plans?productId=1&pageSize=100", headers=auth(admin)))["items"]
        assert not any(p["planCode"] == code for p in after)

    def test_deletes_a_revoked_key_refuses_the_live_one_and_a_maker_only_requests_it(self, client, login):
        admin = login("admin")
        lid = create_licence(client, admin, "KSTACK")
        keys = data(client.get(f"/api/v1/admin/license-keys?licenseId={lid}&pageSize=100", headers=auth(admin)))["items"]
        active = next(k for k in keys if k["status"] == "ACTIVE")
        live = client.delete(f"/api/v1/admin/license-keys/{active['keyId']}", headers=auth(admin))
        assert live.status_code == 409
        assert error(live)["code"] == "KEY_ACTIVE"

        # make a revoked key: regenerate the active one
        regen = client.post(f"/api/v1/admin/licenses/{lid}/regenerate-key", headers=auth(admin),
                            json={"reason": "test rotate"})
        assert regen.status_code == 200, regen.text
        assert active_key(client, admin, lid) != active["licenseKey"]
        revoked = data(client.get(f"/api/v1/admin/license-keys?licenseId={lid}&status=REVOKED",
                                  headers=auth(admin)))["items"][0]
        assert revoked["keyId"] == active["keyId"]

        queued = client.delete(f"/api/v1/admin/license-keys/{revoked['keyId']}", headers=auth(login("maker")))
        assert queued.status_code == 202

        deleted = client.delete(f"/api/v1/admin/license-keys/{revoked['keyId']}", headers=auth(admin))
        assert deleted.status_code == 200
        gone = data(client.get(f"/api/v1/admin/license-keys?licenseId={lid}", headers=auth(admin)))["items"]
        assert not any(k["keyId"] == revoked["keyId"] for k in gone)
