"""
Issuing a .lic activation file by hand, for a KStack/KFlash machine that
cannot reach the portal. Port of tests/licFileIssue.test.ts.
"""
from __future__ import annotations

import re

import pytest

from app.services.karnex_lic_file import hardware_from, parse_karnex_lic, verify_karnex_lic
from support import auth, create_licence, data, error, lic_request_file, mac

pytestmark = pytest.mark.integration


def issue(client, token: str, lid: int, lic_file: str):
    return client.post(f"/api/v1/admin/licenses/{lid}/issue-lic-file", headers=auth(token), json={"licFile": lic_file})


def current_activations(client, token: str, lid: int) -> int:
    return data(client.get(f"/api/v1/admin/licenses/{lid}", headers=auth(token)))["currentActivations"]


def test_signs_the_uploaded_request_binds_it_to_that_machine_and_records_the_seat(client, login):
    token = login("admin")
    lid = create_licence(client, token, "KFLASH")
    upload = lic_request_file("Kflash", mac())

    res = issue(client, token, lid, upload)
    assert res.status_code == 200, res.text
    assert data(res)["reissued"] is False
    assert re.match(r"^kflash-LIC-.*\.lic$", data(res)["fileName"])

    # The product's own verification: genuine, and only for this hardware.
    issued = data(res)["licFile"]
    hw = hardware_from(parse_karnex_lic(upload))
    assert verify_karnex_lic(issued, hw)["valid"] is True
    assert verify_karnex_lic(issued, {**hw, "macAddress": "000000000001"})["valid"] is False
    file = parse_karnex_lic(issued)
    assert file["Customer"] != ""
    assert file["SerialKey"].startswith("KFLH-")

    # The machine is a known installation with its file stored for re-download.
    dl = client.get(f"/api/v1/admin/activations/{data(res)['activationId']}/lic-file", headers=auth(token))
    assert dl.status_code == 200
    assert re.search(r'attachment; filename=".*\.lic"', dl.headers["content-disposition"])
    assert dl.text == issued

    assert current_activations(client, token, lid) == 1


def test_reissues_on_the_same_seat_when_the_same_machine_asks_again(client, login):
    token = login("admin")
    lid = create_licence(client, token, "KFLASH")
    upload = lic_request_file("Kflash", mac())
    assert issue(client, token, lid, upload).status_code == 200
    again = issue(client, token, lid, upload)
    assert again.status_code == 200
    assert data(again)["reissued"] is True
    assert current_activations(client, token, lid) == 1


def test_refuses_a_file_for_a_different_product(client, login):
    token = login("admin")
    lid = create_licence(client, token, "KSTACK")
    res = issue(client, token, lid, lic_request_file("Kflash", mac()))
    assert res.status_code == 400
    assert 'is for "Kflash"' in error(res)["message"]


def test_refuses_a_file_that_is_not_a_lic_request(client, login):
    token = login("admin")
    lid = create_licence(client, token, "KFLASH")
    res = issue(client, token, lid, "this is a word document")
    assert res.status_code == 400
    assert current_activations(client, token, lid) == 0


def test_refuses_a_vehicle_sim_licence_which_does_not_use_lic_files(client, login):
    token = login("admin")
    lid = create_licence(client, token, "VEHICLESIM")
    res = issue(client, token, lid, lic_request_file("Vehicle SIM", mac()))
    assert res.status_code == 400


def test_stops_at_the_seat_limit(client, login):
    token = login("admin")
    lid = create_licence(client, token, "KFLASH", plan_code="TRIAL")  # 1 seat
    first = issue(client, token, lid, lic_request_file("Kflash", mac()))
    assert first.status_code == 200, first.text
    second = issue(client, token, lid, lic_request_file("Kflash", mac()))
    assert second.status_code == 409
    assert error(second)["code"] == "ACTIVATION_LIMIT_REACHED"


def test_a_makers_upload_issues_nothing_until_a_checker_approves_it(client, login):
    admin = login("admin")
    lid = create_licence(client, admin, "KFLASH")
    pending = issue(client, login("maker"), lid, lic_request_file("Kflash", mac()))
    assert pending.status_code == 202
    assert current_activations(client, admin, lid) == 0

    approved = client.post(f"/api/v1/admin/change-requests/{data(pending)['changeRequestId']}/approve",
                           headers=auth(login("checker")), json={"comment": "PO received"})
    assert approved.status_code == 200, approved.text

    lic = data(client.get(f"/api/v1/admin/licenses/{lid}", headers=auth(admin)))
    assert lic["currentActivations"] == 1
    act = lic["activations"][0]
    dl = client.get(f"/api/v1/admin/activations/{act['activationId']}/lic-file", headers=auth(admin))
    assert dl.status_code == 200
    assert verify_karnex_lic(dl.text)["valid"] is True
