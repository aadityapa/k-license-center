"""
Reactivation after a clock block: the app's own request is decided by the
server's time; an administrator's reactivation is collected by the app and
succeeds whatever the computer's clock says. Alerts are marked handled.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from support import VEHSIM, auth, data, error, uniq

pytestmark = pytest.mark.integration
API = "/api/v1"


def _iso(d: datetime) -> str:
    return d.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _alert(client, inst: str) -> None:
    now = datetime.now(timezone.utc)
    r = client.post(f"{API}/license/clock-alert", headers=VEHSIM, json={
        "productCode": "VEHICLESIM", "installationId": inst, "kind": "MOVED_BACK",
        "localTime": _iso(now - timedelta(days=30)), "referenceTime": _iso(now), "deltaSeconds": -30 * 86400,
        "deviceName": "CLOCK-PC"})
    assert r.status_code == 200 and data(r)["recorded"] is True


def test_app_reactivation_uses_server_time(client, login):
    inst = uniq("CLK")
    _alert(client, inst)
    now = datetime.now(timezone.utc)

    wrong = client.post(f"{API}/license/clock-reactivate", headers=VEHSIM, json={
        "productCode": "VEHICLESIM", "installationId": inst, "localTime": _iso(now - timedelta(days=3))})
    assert wrong.status_code == 200
    d = data(wrong)
    assert d["reactivated"] is False and "behind" in d["message"] and d["serverTime"]

    right = client.post(f"{API}/license/clock-reactivate", headers=VEHSIM, json={
        "productCode": "VEHICLESIM", "installationId": inst, "localTime": _iso(now + timedelta(seconds=40))})
    assert data(right)["reactivated"] is True and data(right)["adminReleased"] is False

    admin = login("admin")
    items = data(client.get(f"{API}/admin/clock-alerts", headers=auth(admin)))["items"]
    row = next(i for i in items if i["installationId"] == inst)
    assert row["state"] == "REACTIVATED" and row["deviceName"] == "CLOCK-PC"
    bell = data(client.get(f"{API}/admin/notifications", headers=auth(admin)))["items"]
    assert not [n for n in bell if n["eventType"] == "CLOCK_TAMPER"
                and (n.get("payload") or {}).get("installationId") == inst and n["status"] == "PENDING"]


def test_admin_reactivation_is_collected_by_the_app(client, login):
    inst = uniq("CLK")
    _alert(client, inst)
    admin, maker, viewer = login("admin"), login("maker"), login("viewer")

    t = client.get(f"{API}/license/time", headers=VEHSIM, params={"installationId": inst})
    assert data(t)["clockReleasePending"] is False
    assert "clockReleasePending" not in data(client.get(f"{API}/license/time", headers=VEHSIM))

    body = {"installationId": inst, "productCode": "VEHICLESIM", "note": "customer called"}
    assert client.post(f"{API}/admin/clock-alerts/reactivate", headers=auth(viewer), json=body).status_code == 403
    assert client.post(f"{API}/admin/clock-alerts/reactivate", headers=auth(maker), json=body).status_code == 202
    r = client.post(f"{API}/admin/clock-alerts/reactivate", headers=auth(admin), json=body)
    assert r.status_code == 200 and data(r)["releaseSent"] is True

    items = data(client.get(f"{API}/admin/clock-alerts", headers=auth(admin)))["items"]
    assert next(i for i in items if i["installationId"] == inst)["state"] == "RELEASE_SENT"
    assert data(client.get(f"{API}/license/time", headers=VEHSIM, params={"installationId": inst}))["clockReleasePending"] is True

    # Collected even though this computer's clock is still a week off.
    far = _iso(datetime.now(timezone.utc) - timedelta(days=7))
    c = client.post(f"{API}/license/clock-reactivate", headers=VEHSIM,
                    json={"productCode": "VEHICLESIM", "installationId": inst, "localTime": far})
    assert data(c)["reactivated"] is True and data(c)["adminReleased"] is True
    assert data(client.get(f"{API}/license/time", headers=VEHSIM, params={"installationId": inst}))["clockReleasePending"] is False
    items = data(client.get(f"{API}/admin/clock-alerts", headers=auth(admin)))["items"]
    assert next(i for i in items if i["installationId"] == inst)["state"] == "REACTIVATED"


def test_validation_and_server_time(client, login):
    bad = client.post(f"{API}/license/clock-reactivate", headers=VEHSIM,
                      json={"productCode": "VEHICLESIM", "installationId": "X", "localTime": "not a date"})
    assert bad.status_code == 400 and error(bad)["code"] == "VALIDATION_ERROR"
    other = client.post(f"{API}/license/clock-reactivate", headers=VEHSIM,
                        json={"productCode": "KSTACK", "installationId": "X", "localTime": "2026-01-01T00:00:00Z"})
    assert other.status_code == 400
    st = client.get(f"{API}/admin/system/time", headers=auth(login("viewer")))
    assert st.status_code == 200 and data(st)["serverTime"]
    assert client.get(f"{API}/admin/system/time").status_code == 401
