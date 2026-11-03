"""
A KStack/KFlash machine submits its own .lic request file, and polls for the
signed file. Port of tests/licRequest.test.ts (mocked SQL there; here the
inserted row and the statements sent are checked on the real database).
Each test uses its own hardware, so its fingerprint is unique.
"""
from __future__ import annotations

from urllib.parse import quote

import pytest

from app.services.karnex_lic_file import fingerprint, hardware_from, parse_karnex_lic
from support import data, error, lic_request_file, mac

pytestmark = pytest.mark.integration


def make_body(lic_file: str) -> dict:
    return {
        "licFile": lic_file,
        "email": "ops@pinnacletooling.example",
        "companyName": "Pinnacle Tooling Works",
        "hostName": "PINNACLE-SHOP-01",
        "appVersion": "1.8.2",
    }


def fp_of(lic_file: str) -> str:
    """Derived the same way the endpoint derives it, never hard-coded."""
    return fingerprint(hardware_from(parse_karnex_lic(lic_file)))


class TestLicRequest:
    def test_accepts_the_uploaded_lic_with_202_and_answers_with_the_fingerprint(self, client, db, sql_spy):
        m = mac()
        lic = lic_request_file("Kflash", m)
        fp = fp_of(lic)

        res = client.post("/api/v1/public/lic-request", json=make_body(lic))

        assert res.status_code == 202, res.text
        assert data(res)["received"] is True
        assert data(res)["fingerprint"] == fp
        rid = data(res)["requestId"]
        assert isinstance(rid, int)

        # The hardware identifiers are stored individually AND as the original file,
        # so the licence can be re-signed later without asking the customer again.
        row = db("""SELECT mac_address, cpu_id, bios_serial, motherboard_id, hw_fingerprint, lic_request_json,
                           status, license_id, product_id
                      FROM license_requests WHERE request_id = %s""", (rid,))[0]
        assert row["mac_address"] == m
        assert row["cpu_id"] == "BFEBFBFF000906A4"
        assert row["bios_serial"] == "R5PTCJ00S00322B"
        assert row["motherboard_id"] == "R521PTCJ000PE3MB"
        assert row["hw_fingerprint"] == fp
        assert "R521PTCJ000PE3MB" in row["lic_request_json"]
        assert row["status"] == "UNDER_REVIEW"
        insert = sql_spy.matching("INSERT INTO license_requests")
        assert len(insert) == 1
        assert insert[0][1]["p_fp"] == fp and insert[0][1]["p_mac"] == m

        # Nothing is issued here — a hardware-bound licence is a human decision.
        assert row["license_id"] is None
        assert not sql_spy.any("pkg_license.create_license")
        assert sql_spy.any("INSERT INTO notification_events")
        assert db("""SELECT COUNT(*) AS n FROM notification_events
                      WHERE entity_type = 'LICENSE_REQUEST' AND entity_id = %s""", (rid,))[0]["n"] == 1

    def test_returns_the_open_request_when_the_same_machine_asks_twice(self, client, db, sql_spy):
        lic = lic_request_file("Kflash", mac())
        first = client.post("/api/v1/public/lic-request", json=make_body(lic))
        second = client.post("/api/v1/public/lic-request", json=make_body(lic))

        assert first.status_code == 202
        assert second.status_code == 202
        # Same request, not a second one stacked in the reviewer's queue.
        assert data(second)["requestId"] == data(first)["requestId"]
        assert "already awaiting review" in data(second)["message"]
        assert db("SELECT COUNT(*) AS n FROM license_requests WHERE hw_fingerprint = %s", (fp_of(lic),))[0]["n"] == 1
        assert len(sql_spy.matching("INSERT INTO license_requests")) == 1

    def test_400s_a_lic_that_names_a_product_this_system_does_not_sell(self, client, db, sql_spy):
        lic = lic_request_file("Kflash", mac()).replace('"Kflash"', '"Kwidget"')
        res = client.post("/api/v1/public/lic-request", json=make_body(lic))

        assert res.status_code == 400
        assert error(res)["code"] == "VALIDATION_ERROR"
        assert "Kwidget" in error(res)["message"]
        assert not sql_spy.any("INSERT INTO license_requests")
        assert db("SELECT COUNT(*) AS n FROM license_requests WHERE hw_fingerprint = %s", (fp_of(lic),))[0]["n"] == 0


class TestLicStatus:
    def test_answers_approved_false_while_the_request_awaits_a_reviewer(self, client):
        lic = lic_request_file("Kflash", mac())
        asked = client.post("/api/v1/public/lic-request", json=make_body(lic))
        assert asked.status_code == 202

        res = client.get(f"/api/v1/public/lic-status/{quote(fp_of(lic), safe='')}")

        assert res.status_code == 200
        assert data(res)["approved"] is False
        assert data(res)["status"] == "UNDER_REVIEW"
        assert "awaiting approval" in data(res)["message"]
        # No partially-signed file is ever handed out.
        assert "licFile" not in data(res)
