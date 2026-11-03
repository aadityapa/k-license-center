"""
Clock-tamper alerts, one trial per computer, server time and the encrypted
licensing file. Port of tests/clockTrialConfig.test.ts.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from scripts.licensing_file import decrypt_licensing_config, encrypt_licensing_config
from support import KSTACK, VEHSIM, auth, data, error, machine_id, uniq


# ------------------------------------------------------------------ unit
def test_encrypted_licensing_file_round_trips_and_any_edit_makes_it_unreadable():
    settings = {"baseUrl": "https://license.karnex.in/api/v1", "clientKey": "k", "clientSecret": "s3cr3t",
                "productCode": "VEHICLESIM"}
    text = encrypt_licensing_config(settings)
    assert text.startswith("KLC1:")
    assert "s3cr3t" not in text
    assert decrypt_licensing_config(text) == settings

    # flip one character of the ciphertext
    body = text.strip()
    i = len(body) - 10
    flipped = body[:i] + ("B" if body[i] == "A" else "A") + body[i + 1:]
    assert decrypt_licensing_config(flipped) is None
    assert decrypt_licensing_config('{"baseUrl":"x"}') is None


# ------------------------------------------------------------------ integration
@pytest.mark.integration
class TestClockTamperAlert:
    def test_becomes_a_critical_notification_once_per_machine_per_10_minutes(self, client, login):
        inst = uniq("CLOCKTEST")
        body = {
            "productCode": "VEHICLESIM",
            "installationId": inst,
            "kind": "MOVED_BACK",
            "localTime": "2026-01-01T00:00:00.000Z",
            "referenceTime": "2026-10-27T10:00:00.000Z",
            "deltaSeconds": -25_000_000,
            "deviceName": "BENCH-CLOCK",
            "appVersion": "1.0.47",
        }
        first = client.post("/api/v1/license/clock-alert", headers=VEHSIM, json=body)
        assert first.status_code == 200
        assert data(first)["recorded"] is True
        assert isinstance(data(first)["serverTime"], str)

        again = client.post("/api/v1/license/clock-alert", headers=VEHSIM, json=body)
        assert again.status_code == 200
        assert data(again)["recorded"] is False

        admin = login("admin")
        bell = client.get("/api/v1/admin/notifications", headers=auth(admin))
        assert bell.status_code == 200
        alerts = [n for n in data(bell)["items"]
                  if n["eventType"] == "CLOCK_TAMPER" and (n.get("payload") or {}).get("installationId") == inst]
        assert len(alerts) == 1
        assert alerts[0]["payload"]["severity"] == "CRITICAL"
        assert alerts[0]["payload"]["deviceName"] == "BENCH-CLOCK"

        dash = client.get("/api/v1/admin/dashboard/overview?days=30", headers=auth(admin))
        assert dash.json().get("error") is None
        clock = next((a for a in data(dash)["pendingActions"] if a["key"] == "clock"), None)
        assert clock is not None and clock["count"] >= 1

    def test_refuses_an_unknown_kind_and_a_client_of_another_product(self, client):
        bad = client.post("/api/v1/license/clock-alert", headers=VEHSIM,
                          json={"productCode": "VEHICLESIM", "installationId": "X1", "kind": "SOMETHING"})
        assert bad.status_code == 400
        other = client.post("/api/v1/license/clock-alert", headers=KSTACK,
                            json={"productCode": "VEHICLESIM", "installationId": "X1", "kind": "MOVED_BACK"})
        assert other.status_code == 400


@pytest.mark.integration
def test_one_trial_per_computer_then_a_paid_plan(client, login):
    mid = machine_id()
    email = f"trial-{mid.lower()}@onceonly.example"
    grant = {"vbs": {"mode": 0, "edition": 2, "features": ["Can"]}}

    def ask() -> int:
        r = client.post("/api/v1/public/vbs-request", json={
            "machineId": mid, "email": email, "companyName": "Once Only Ltd", "hostName": "ONCE-PC",
        })
        assert r.status_code == 202, r.text
        return int(data(r)["requestId"])

    checker = login("checker")
    first = ask()
    ok1 = client.post(f"/api/v1/admin/license-requests/{first}/approve", headers=auth(checker),
                      json={"planCode": "TRIAL", "amount": 0, **grant})
    assert ok1.status_code == 200, ok1.text

    # The app gets its key, so the trial licence is now bound to this computer.
    status = client.get(f"/api/v1/public/vbs-status/{mid}")
    assert data(status)["approved"] is True

    # Later the same computer asks again.
    second = ask()
    assert second != first
    detail = client.get(f"/api/v1/admin/license-requests/{second}", headers=auth(checker))
    assert (data(detail).get("priorTrial") or {}).get("licenseNo")

    refused = client.post(f"/api/v1/admin/license-requests/{second}/approve", headers=auth(checker),
                          json={"planCode": "TRIAL", "amount": 0, **grant})
    assert refused.status_code == 409
    assert error(refused)["code"] == "TRIAL_ALREADY_USED"
    assert "once per computer" in error(refused)["message"]

    paid = client.post(f"/api/v1/admin/license-requests/{second}/approve", headers=auth(checker),
                       json={"planCode": "YEARLY", "amount": 25000, **grant})
    assert paid.status_code == 200, paid.text


@pytest.mark.integration
def test_server_time_for_a_known_client_and_refused_for_unknown_clients(client):
    r = client.get("/api/v1/license/time", headers=VEHSIM)
    assert r.status_code == 200
    server = datetime.fromisoformat(data(r)["serverTime"].replace("Z", "+00:00"))
    assert abs((server - datetime.now(timezone.utc)).total_seconds()) < 5
    anon = client.get("/api/v1/license/time")
    assert anon.status_code == 401
