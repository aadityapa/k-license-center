"""
An approved change must actually change the record (maker submits, checker
approves, the row is updated). Port of tests/governanceApply.test.ts.
"""
from __future__ import annotations

import pytest

from support import auth, data, uniq

pytestmark = pytest.mark.integration


def maker_then_checker(client, login, path: str, body: dict) -> None:
    sub = client.put(f"/api/v1{path}", headers=auth(login("maker")), json=body)
    assert sub.status_code == 202, sub.text
    approved = client.post(f"/api/v1/admin/change-requests/{data(sub)['changeRequestId']}/approve",
                           headers=auth(login("checker")), json={})
    assert approved.status_code == 200, approved.text
    assert data(approved)["status"] == "APPROVED"


def test_customer(client, login):
    maker_then_checker(client, login, "/admin/customers/1", {"contactPerson": "Changed By Maker", "city": "Nagpur"})
    after = client.get("/api/v1/admin/customers/1", headers=auth(login("admin")))
    assert data(after)["contactPerson"] == "Changed By Maker"
    assert data(after)["city"] == "Nagpur"


def test_product(client, login):
    maker_then_checker(client, login, "/admin/products/1", {"description": "Updated through maker-checker"})
    after = client.get("/api/v1/admin/products/1", headers=auth(login("admin")))
    assert data(after)["description"] == "Updated through maker-checker"


def test_plan(client, login):
    admin = login("admin")
    # A plan of its own, so renaming it cannot disturb other tests.
    created = client.post("/api/v1/admin/plans", headers=auth(admin), json={
        "productId": 1, "planCode": uniq("GOV"), "planName": "Before Rename", "durationDays": 30, "maxActivations": 1,
    })
    assert created.status_code == 201, created.text
    pid = data(created)["planId"]
    plans = data(client.get("/api/v1/admin/plans?productId=1&limit=50", headers=auth(admin)))["items"]
    assert any(p["planId"] == pid for p in plans)

    maker_then_checker(client, login, f"/admin/plans/{pid}", {"planName": "Renamed Plan"})
    after = client.get(f"/api/v1/admin/plans/{pid}", headers=auth(admin))
    assert data(after)["planName"] == "Renamed Plan"


def test_admin_edit_applies_immediately(client, login):
    admin = login("admin")
    r = client.put("/api/v1/admin/customers/2", headers=auth(admin), json={"contactPerson": "Direct Admin Edit"})
    assert r.status_code == 200
    after = client.get("/api/v1/admin/customers/2", headers=auth(admin))
    assert data(after)["contactPerson"] == "Direct Admin Edit"


def test_a_checker_can_read_plans_but_not_change_them(client, login):
    checker = login("checker")
    res = client.get("/api/v1/admin/plans?productId=3&status=ACTIVE&pageSize=100", headers=auth(checker))
    assert res.status_code == 200
    assert len(data(res)["items"]) > 0
    write = client.post("/api/v1/admin/plans", headers=auth(checker), json={
        "productId": 3, "planCode": "X", "planName": "X", "durationDays": 1, "maxActivations": 1,
    })
    assert write.status_code == 403
