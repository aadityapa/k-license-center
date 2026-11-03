"""
/api/v1/license — the product API (X-Client-Key / X-Client-Secret).
Port of tests/license.test.ts: the mocked pkg_authorization OUT binds become
real licences in the states each case needs, used through the demo KStack client.
"""
from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timedelta, timezone

import pytest

from support import KSTACK, SIGNING_KEYS, active_key, create_licence, data, error, uniq

pytestmark = pytest.mark.integration


def _inst() -> str:
    return uniq("stable-guid-")


def _licence(client, login, plan_code: str = "YEARLY") -> tuple[int, str]:
    token = login("admin")
    lid = create_licence(client, token, "KSTACK", plan_code=plan_code)
    return lid, active_key(client, token, lid)


def test_activate_answers_an_authorized_signed_response(client, login, db):
    lid, key = _licence(client, login)
    inst = _inst()
    res = client.post("/api/v1/license/activate", headers=KSTACK, json={
        "licenseKey": key, "productCode": "KSTACK", "installationId": inst,
        "deviceName": "PC-001", "os": "Windows 11", "appVersion": "2.4.1",
    })

    assert res.status_code == 200, res.text
    assert res.json()["success"] is True
    d = data(res)
    lic = db("SELECT expiry_date, max_activations FROM licenses WHERE license_id = %s", (lid,))[0]
    act = db("SELECT activation_id FROM license_activations WHERE license_id = %s AND installation_id = %s",
             (lid, inst))[0]
    grace = int(db("SELECT setting_value FROM settings WHERE setting_key = 'OFFLINE_GRACE_DAYS'")[0]["setting_value"])
    expiry = lic["expiry_date"].isoformat()
    assert d["authorized"] is True
    assert d["status"] == "ACTIVE"
    assert d["activationId"] == act["activation_id"]
    assert d["expiryDate"] == expiry
    assert d["maxActivations"] == lic["max_activations"]
    assert d["currentActivations"] == 1
    assert d["offlineGraceDays"] == grace
    assert d["reason"] is None
    assert d["lastAuthorizedAt"]
    assert d["nextValidationDeadline"]

    expected = hmac.new(
        SIGNING_KEYS["KSTACK"].encode(),
        f"{key}|{inst}|ACTIVE|{expiry}|{d['nextValidationDeadline']}".encode(),
        hashlib.sha256,
    ).hexdigest()
    assert d["signature"] == expected


def test_activate_at_the_activation_limit_is_an_http_200_denial(client, login):
    _, key = _licence(client, login, plan_code="TRIAL")  # 1 seat
    first = client.post("/api/v1/license/activate", headers=KSTACK,
                        json={"licenseKey": key, "productCode": "KSTACK", "installationId": _inst()})
    assert data(first)["authorized"] is True

    res = client.post("/api/v1/license/activate", headers=KSTACK,
                      json={"licenseKey": key, "productCode": "KSTACK", "installationId": _inst()})
    assert res.status_code == 200
    assert data(res) == {"authorized": False, "status": "DENIED", "reason": "ACTIVATION_LIMIT_REACHED"}


@pytest.mark.parametrize("reason", ["LICENSE_EXPIRED", "LICENSE_SUSPENDED", "LICENSE_REVOKED", "INVALID_ACTIVATION"])
def test_validate_passes_through_the_denial_reason(client, login, db, reason):
    lid, key = _licence(client, login)
    inst = _inst()
    act = client.post("/api/v1/license/activate", headers=KSTACK,
                      json={"licenseKey": key, "productCode": "KSTACK", "installationId": inst})
    assert data(act)["authorized"] is True

    if reason == "LICENSE_EXPIRED":
        db("UPDATE licenses SET expiry_date = CURRENT_DATE - 1 WHERE license_id = %s", (lid,))
    elif reason == "LICENSE_SUSPENDED":
        db("UPDATE licenses SET status = 'SUSPENDED' WHERE license_id = %s", (lid,))
    elif reason == "LICENSE_REVOKED":
        # The revoke endpoint also revokes the key (-> INVALID_LICENSE); a revoked
        # licence whose key is still ACTIVE is what yields LICENSE_REVOKED.
        db("UPDATE licenses SET status = 'REVOKED' WHERE license_id = %s", (lid,))
    else:
        inst = _inst()  # never activated

    res = client.post("/api/v1/license/validate", headers=KSTACK,
                      json={"licenseKey": key, "productCode": "KSTACK", "installationId": inst})
    assert res.status_code == 200
    assert data(res) == {"authorized": False, "status": "DENIED", "reason": reason}


def test_rejects_unknown_client_credentials(client):
    res = client.post("/api/v1/license/validate", headers={"X-Client-Key": "unknown-key", "X-Client-Secret": "whatever"},
                      json={"licenseKey": "KSTK-7H4P-X92M-Q81Z", "productCode": "KSTACK", "installationId": _inst()})
    assert res.status_code == 401
    assert error(res)["code"] == "UNAUTHORIZED_CLIENT"


def test_rejects_a_known_client_key_with_the_wrong_secret(client):
    res = client.post("/api/v1/license/validate",
                      headers={"X-Client-Key": KSTACK["x-client-key"], "X-Client-Secret": "not-the-secret"},
                      json={"licenseKey": "KSTK-7H4P-X92M-Q81Z", "productCode": "KSTACK", "installationId": _inst()})
    assert res.status_code == 401
    assert error(res)["code"] == "UNAUTHORIZED_CLIENT"


def test_rejects_a_malformed_license_key(client):
    res = client.post("/api/v1/license/activate", headers=KSTACK,
                      json={"licenseKey": "not-a-key", "productCode": "KSTACK", "installationId": _inst()})
    assert res.status_code == 400
    assert error(res)["code"] == "VALIDATION_ERROR"


def test_rejects_a_stale_timestamp(client):
    stale = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    res = client.post("/api/v1/license/validate", headers=KSTACK, json={
        "licenseKey": "KSTK-7H4P-X92M-Q81Z", "productCode": "KSTACK", "installationId": _inst(), "timestamp": stale,
    })
    assert res.status_code == 400
    assert error(res)["code"] == "VALIDATION_ERROR"


def test_the_error_envelope_carries_a_request_id_matching_the_header(client):
    res = client.post("/api/v1/license/validate", headers={"X-Client-Key": "nope", "X-Client-Secret": "nope"},
                      json={"licenseKey": "KSTK-7H4P-X92M-Q81Z", "productCode": "KSTACK", "installationId": _inst()})
    body = res.json()
    assert set(body) == {"success", "error", "requestId"}
    assert body["success"] is False
    assert set(body["error"]) == {"code", "message"}
    assert body["error"]["code"] == "UNAUTHORIZED_CLIENT"
    assert isinstance(body["error"]["message"], str)
    assert isinstance(body["requestId"], str)
    assert res.headers["x-request-id"] == body["requestId"]
