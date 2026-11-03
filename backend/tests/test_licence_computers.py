"""The licence page shows the computer the licence is bound to, with the hardware the app reported."""
from __future__ import annotations

import pytest

from support import auth, data, machine_id

pytestmark = pytest.mark.integration


def test_licence_detail_lists_the_requesting_computer(client, login):
    mid = machine_id()
    asked = client.post("/api/v1/public/vbs-request", json={
        "machineId": mid, "email": "hw@detail.example", "companyName": "Detail Works",
        "hostName": "BENCH-HW", "appVersion": "2.0.1",
        "macAddress": "C403A843DD85", "cpuId": "BFEBFBFF000906A4", "biosSerial": "R5PTCJ00S00322B",
        "motherboardId": "R521PTCJ000PE3MB", "osName": "Microsoft Windows 11 Pro", "osVersion": "10.0.22631",
    }, headers={"x-forwarded-for": "10.8.0.77"})
    assert asked.status_code == 202, asked.text
    admin = login("admin")
    ok = client.post(f"/api/v1/admin/license-requests/{data(asked)['requestId']}/approve", headers=auth(admin),
                     json={"planCode": "YEARLY", "amount": 1, "vbs": {"mode": 1, "edition": 2, "features": ["Can"]}})
    assert ok.status_code == 200, ok.text
    lid = data(ok)["licenseId"] if "licenseId" in data(ok) else data(ok)["license"]["licenseId"]

    d = data(client.get(f"/api/v1/admin/licenses/{lid}", headers=auth(admin)))
    assert d["vbsMachineId"] == mid
    [pc] = d["computers"]
    assert pc["machineId"] == mid and pc["boundToKey"] is True
    assert pc["macAddress"] == "C403A843DD85" and pc["cpuId"] == "BFEBFBFF000906A4"
    assert pc["biosSerial"] == "R5PTCJ00S00322B" and pc["motherboardId"] == "R521PTCJ000PE3MB"
    assert pc["hostName"] == "BENCH-HW" and pc["osName"].startswith("Microsoft Windows 11 Pro")
