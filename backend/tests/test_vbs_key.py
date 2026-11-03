"""
Issuing Vehicle SIM keys from the portal, the app's request -> approve ->
collect flow, and the product API accepting the long key shape.

Port of the portal half of tests/vbsKey.test.ts. The key-format half (pure
functions: payload, epoch days, feature mask, V2/V3 signatures, P1363,
forged keys, refused grants) is in tests/test_keys.py::TestVbsKeyFormat.
"""
from __future__ import annotations

import pytest

from app.services.vbs_key import VbsEdition, VbsMode, parse_vbs_key, vbs_public_key_base64
from support import KSTACK, VEHSIM, auth, create_licence, data, error, machine_id

pytestmark = pytest.mark.integration

NODE_LOCKED = int(VbsMode.NodeLocked)
SUBSCRIPTION = int(VbsMode.Subscription)
PRO = int(VbsEdition.Pro)
ENTERPRISE = int(VbsEdition.Enterprise)


@pytest.fixture(scope="module")
def pub() -> str:
    """The public half of the configured signing key — what the Vehicle SIM build embeds."""
    return vbs_public_key_base64()


@pytest.fixture
def vehsim_licence(client, login) -> int:
    """A fresh ACTIVE Vehicle SIM licence (YEARLY), built through the real endpoints."""
    token = login("admin")
    products = data(client.get("/api/v1/admin/products", headers=auth(token)))["items"]
    vehsim = next(p for p in products if p["productCode"] == "VEHICLESIM")
    assert vehsim["keyFormat"] == "VBS_KEY"
    return create_licence(client, token, "VEHICLESIM", amount=25000)


def issue(client, token: str, lid: int, body: dict):
    return client.post(f"/api/v1/admin/licenses/{lid}/issue-vbs-key", headers=auth(token), json=body)


def test_mints_a_key_whose_grant_matches_what_was_asked_for(client, login, vehsim_licence, pub):
    mid = machine_id()
    res = issue(client, login("admin"), vehsim_licence, {
        "mode": NODE_LOCKED, "edition": ENTERPRISE, "features": ["Can", "Lin", "FlexRay", "Xcp"],
        "machineId": mid, "keyVersion": "V3",
    })
    assert res.status_code == 200, res.text
    assert data(res)["keyVersion"] == "V3"

    parsed = parse_vbs_key(data(res)["licenseKey"], pub)
    assert parsed["signatureValid"] is True
    assert parsed["features"] == ["Can", "Lin", "FlexRay", "Xcp"]
    assert parsed["machineId"] == mid
    # The licence number is carried in the key, so a support call can identify it.
    assert parsed["licenceNo"] == str(data(res)["licenceNo"])
    # Node-locked is perpetual by definition.
    assert parsed["expiry"] is None


def test_takes_the_expiry_from_the_licence_not_from_the_request(client, login, db, vehsim_licence, pub):
    res = issue(client, login("admin"), vehsim_licence, {
        "mode": SUBSCRIPTION, "edition": PRO, "features": ["Can"], "machineId": machine_id(), "keyVersion": "V3",
    })
    assert res.status_code == 200, res.text
    # The key's expiry is the licence's calendar date (the regression guard for
    # the day-loss bug where a DATE read as local midnight lost a day in IST).
    expiry = db("SELECT expiry_date FROM licenses WHERE license_id = %s", (vehsim_licence,))[0]["expiry_date"]
    assert parse_vbs_key(data(res)["licenseKey"], pub)["expiry"] == expiry.isoformat()


def test_refuses_a_node_locked_key_with_no_machine(client, login, vehsim_licence):
    res = issue(client, login("admin"), vehsim_licence,
                {"mode": NODE_LOCKED, "edition": PRO, "features": ["Can"], "keyVersion": "V3"})
    assert res.status_code == 400
    assert error(res)["code"] == "VALIDATION_ERROR"


def test_refuses_any_vehicle_sim_key_without_a_machine_subscription_included(client, login, vehsim_licence):
    res = issue(client, login("admin"), vehsim_licence,
                {"mode": SUBSCRIPTION, "edition": PRO, "features": ["Can"], "keyVersion": "V3"})
    assert res.status_code == 400
    assert "Machine ID is required" in res.text


def test_refuses_to_put_a_vehicle_sim_key_on_another_products_licence(client, login):
    token = login("admin")
    licences = data(client.get("/api/v1/admin/licenses?limit=50", headers=auth(token)))["items"]
    kstack = next(lic for lic in licences if lic["productCode"] == "KSTACK")
    res = issue(client, token, kstack["licenseId"], {
        "mode": SUBSCRIPTION, "edition": PRO, "features": ["Can"], "machineId": machine_id(), "keyVersion": "V3",
    })
    assert res.status_code == 400
    assert "does not use Vehicle SIM keys" in error(res)["message"]


def test_supersedes_the_previous_key_so_only_one_is_ever_live(client, login, vehsim_licence):
    token = login("admin")
    body = {"mode": NODE_LOCKED, "edition": PRO, "features": ["Can"], "machineId": machine_id(), "keyVersion": "V3"}
    first = issue(client, token, vehsim_licence, body)
    second = issue(client, token, vehsim_licence, {**body, "features": ["Can", "Lin"]})
    assert first.status_code == 200
    assert second.status_code == 200
    assert data(second)["licenseKey"] != data(first)["licenseKey"]

    keys = data(client.get(f"/api/v1/admin/license-keys?licenseId={vehsim_licence}", headers=auth(token)))["items"]
    active = [k for k in keys if k["status"] == "ACTIVE"]
    assert len(active) == 1
    assert active[0]["licenseKey"] == data(second)["licenseKey"]


def test_refuses_to_regenerate_a_typed_key_for_vehicle_sim(client, login, vehsim_licence):
    res = client.post(f"/api/v1/admin/licenses/{vehsim_licence}/regenerate-key", headers=auth(login("admin")),
                      json={"reason": "customer lost the key"})
    assert res.status_code == 400
    assert "Vehicle SIM Key panel" in error(res)["message"]


def test_request_from_the_app_approve_in_the_portal_the_app_collects_a_bound_key(client, login, pub):
    mid = machine_id()

    # 1. The customer clicks "Request licence" in the app. Nothing is issued.
    asked = client.post("/api/v1/public/vbs-request", json={
        "machineId": mid, "email": "ops@pinnacle.example", "companyName": "Pinnacle Tooling Works",
        "hostName": "BENCH-07", "appVersion": "1.0.14",
        "macAddress": "C403A843DD85", "cpuId": "BFEBFBFF000906A4", "biosSerial": "R5PTCJ00S00322B",
        "motherboardId": "R521PTCJ000PE3MB", "osName": "Microsoft Windows 11 Pro", "osVersion": "10.0.22631",
        "edition": ENTERPRISE, "mode": NODE_LOCKED, "features": ["Can", "Lin", "FlexRay"],
    })
    assert asked.status_code == 202, asked.text
    assert data(asked)["received"] is True
    rid = data(asked)["requestId"]

    # A second click from the same machine does not stack a second request.
    again = client.post("/api/v1/public/vbs-request", json={
        "machineId": mid, "email": "ops@pinnacle.example", "companyName": "Pinnacle Tooling Works",
    })
    assert data(again)["requestId"] == rid

    # 2. The app polls: still waiting.
    assert data(client.get(f"/api/v1/public/vbs-status/{mid}"))["approved"] is False

    # The reviewer sees the full hardware identity, not just the Machine ID.
    token = login("admin")
    detail = data(client.get(f"/api/v1/admin/license-requests/{rid}", headers=auth(token)))
    assert detail["macAddress"] == "C403A843DD85"
    assert detail["cpuId"] == "BFEBFBFF000906A4"
    assert detail["biosSerial"] == "R5PTCJ00S00322B"
    assert detail["motherboardId"] == "R521PTCJ000PE3MB"
    assert detail["osName"] == "Microsoft Windows 11 Pro"

    # 3. The reviewer approves — and grants LESS than was asked for.
    approved = client.post(f"/api/v1/admin/license-requests/{rid}/approve", headers=auth(token), json={
        "planCode": "YEARLY", "amount": 25000, "vbs": {"edition": PRO, "mode": NODE_LOCKED, "features": ["Can", "Lin"]},
    })
    assert approved.status_code == 200, approved.text

    # 4. The app polls again and gets a key bound to its machine, carrying the
    #    reviewer's grant rather than the app's suggestion.
    done = data(client.get(f"/api/v1/public/vbs-status/{mid}"))
    assert done["approved"] is True
    parsed = parse_vbs_key(done["licenseKey"], pub)
    assert parsed["signatureValid"] is True
    assert parsed["machineId"] == mid
    assert parsed["edition"] == PRO
    assert parsed["features"] == ["Can", "Lin"]
    assert parsed["licenceNo"] == str(data(approved)["licenseNo"])

    # The machine is a known installation, so the live channel and revoke reach it.
    acts = data(client.get(f"/api/v1/admin/activations?search={mid}", headers=auth(token)))["items"]
    mine = next((a for a in acts if a["installationId"] == mid), None)
    assert mine is not None and mine["status"] == "ACTIVE"


def test_accepts_a_request_where_some_hardware_fields_are_null(client):
    # The app serialises anything WMI could not read as JSON null; over-long
    # descriptive text is clipped to the column, never rejected.
    res = client.post("/api/v1/public/vbs-request", json={
        "machineId": machine_id(), "email": "it_support@karnex.in", "companyName": "Karnex",
        "contactPerson": "aaditya", "contactPhone": None, "hostName": "DESKTOP-36TT33L", "appVersion": "1.0.0.0",
        "macAddress": "C403A843DD85", "cpuId": "BFEBFBFF000906A4",
        "biosSerial": "no serial; firmware American Megatrends International, LLC. 1.70 04/12/2023",
        "motherboardId": None, "osName": "Microsoft Windows 10 Pro", "osVersion": "10.0.19045.0",
        "edition": 2, "mode": 0, "features": ["Can", "Lin", "FlexRay", "Ethernet", "Rs232", "Debugger", "Xcp"],
    })
    assert res.status_code == 202, res.text
    assert data(res)["received"] is True


def test_refuses_a_malformed_machine_id_from_the_app(client):
    res = client.post("/api/v1/public/vbs-request",
                      json={"machineId": "not-hex!", "email": "x@y.example", "companyName": "Acme"})
    assert res.status_code == 400


def test_a_vehicle_sim_install_activates_with_its_long_key_shape(client, login, vehsim_licence):
    mid = machine_id()
    issued = issue(client, login("admin"), vehsim_licence, {
        "mode": SUBSCRIPTION, "edition": PRO, "features": ["Can", "Lin"], "machineId": mid, "keyVersion": "V3",
    })
    key = data(issued)["licenseKey"]
    # The product API used to accept only PREF-XXXX-XXXX-XXXX.
    assert len(key) > 40

    activate = client.post("/api/v1/license/activate", headers=VEHSIM, json={
        "licenseKey": key, "productCode": "VEHICLESIM", "installationId": mid, "machineFingerprint": mid,
        "deviceName": "BENCH-01", "appVersion": "1.0.0",
    })
    assert activate.status_code == 200, activate.text
    assert data(activate)["authorized"] is True

    # A client for a different product must not be able to use this key.
    wrong = client.post("/api/v1/license/heartbeat", headers=KSTACK,
                        json={"licenseKey": key, "productCode": "KSTACK", "installationId": mid})
    assert data(wrong)["authorized"] is False
    assert data(wrong)["reason"] == "INVALID_PRODUCT"
