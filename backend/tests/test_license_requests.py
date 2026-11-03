"""
Public licence requests (start -> emailed form -> submit) and their admin
review. Port of tests/licenseRequests.test.ts: the mocked rows become real
requests created through the public endpoints, each with its own address.
"""
from __future__ import annotations

import pytest

from support import auth, data, error, token_with, uniq

pytestmark = pytest.mark.integration

SUBMIT = {
    "companyName": "Harbour Logistics Pvt Ltd",
    "contactPerson": "Meera Nair",
    "contactPhone": "+91-9820011223",
    "planCode": "TRIAL",
}


def manage() -> dict[str, str]:
    return auth(token_with(["REQUEST_LICENSE_VIEW", "REQUEST_LICENSE_MANAGE"]))


def start(client, db, product_code: str = "KSTACK") -> tuple[int, str, str]:
    """A fresh INVITED request: (requestId, form token, email)."""
    email = f"buyer-{uniq().lower()}@harbour.example"
    res = client.post("/api/v1/public/license-requests", json={"email": email, "productCode": product_code})
    assert res.status_code == 202, res.text
    rid = int(data(res)["requestId"])
    token = db("SELECT request_token FROM license_requests WHERE request_id = %s", (rid,))[0]["request_token"]
    return rid, token, email


def submitted(client, db, plan_code: str) -> int:
    rid, token, _ = start(client, db)
    res = client.post(f"/api/v1/public/license-requests/{token}", json={**SUBMIT, "planCode": plan_code})
    assert res.status_code == 200, res.text
    return rid


def _request(db, rid: int) -> dict:
    return db("SELECT status, license_id, email FROM license_requests WHERE request_id = %s", (rid,))[0]


class TestPublic:
    def test_accepts_a_start_request_with_202_and_a_non_committal_message(self, client, db):
        email = f"buyer-{uniq().lower()}@harbour.example"
        res = client.post("/api/v1/public/license-requests", json={"email": email, "productCode": "KSTACK"})

        assert res.status_code == 202
        assert data(res)["submitted"] is True
        rid = data(res)["requestId"]
        assert isinstance(rid, int)
        # The reply must not reveal whether the address was already known.
        assert "If that address is valid" in data(res)["message"]
        row = _request(db, rid)
        assert row["email"] == email and row["status"] == "INVITED"

    def test_404s_the_form_when_the_token_is_not_recognised(self, client):
        res = client.get("/api/v1/public/license-requests/not-a-real-token")
        assert res.status_code == 404
        assert error(res)["code"] == "NOT_FOUND"

    def test_auto_issues_a_licence_when_the_submitted_plan_is_trial(self, client, db, sql_spy):
        rid, token, email = start(client, db)
        sql_spy.clear()

        res = client.post(f"/api/v1/public/license-requests/{token}", json=SUBMIT)

        assert res.status_code == 200, res.text
        assert data(res)["issued"] is True
        row = _request(db, rid)
        lic = db("SELECT license_no, status FROM licenses WHERE license_id = %s", (row["license_id"],))[0]
        assert data(res)["licenseNo"] == lic["license_no"]
        assert row["status"] == "AUTO_ISSUED"
        assert lic["status"] == "ACTIVE"
        assert sql_spy.any("pkg_license.activate_license")
        # The key goes only to the verified mailbox, never into the HTTP response.
        key = db("SELECT license_key FROM license_keys WHERE license_id = %s AND status = 'ACTIVE'",
                 (row["license_id"],))[0]["license_key"]
        assert key not in res.text
        mails = db("SELECT body_text FROM email_outbox WHERE to_address = %s", (email,))
        assert any(key in m["body_text"] for m in mails)

    def test_queues_a_paid_plan_for_review_instead_of_issuing(self, client, db, sql_spy):
        rid, token, _ = start(client, db)
        sql_spy.clear()

        res = client.post(f"/api/v1/public/license-requests/{token}", json={**SUBMIT, "planCode": "YEARLY"})

        assert res.status_code == 200
        assert data(res)["issued"] is False
        row = _request(db, rid)
        assert row["status"] == "UNDER_REVIEW"
        assert row["license_id"] is None
        assert not sql_spy.any("pkg_license.create_license")


class TestAdmin:
    def test_refuses_to_approve_without_an_amount_or_a_plan(self, client, db, sql_spy):
        rid = submitted(client, db, "YEARLY")
        sql_spy.clear()
        for body in ({"planCode": "YEARLY"}, {"amount": 500}, {}):
            res = client.post(f"/api/v1/admin/license-requests/{rid}/approve", headers=manage(), json=body)
            assert res.status_code == 400, body
            assert error(res)["code"] == "VALIDATION_ERROR"
        assert not sql_spy.any("pkg_license.create_license")
        assert _request(db, rid)["status"] == "UNDER_REVIEW"

    def test_409s_when_approving_a_request_that_is_not_under_review(self, client, db, sql_spy):
        rid = submitted(client, db, "TRIAL")  # AUTO_ISSUED
        sql_spy.clear()
        res = client.post(f"/api/v1/admin/license-requests/{rid}/approve", headers=manage(),
                          json={"planCode": "YEARLY", "amount": 1000})
        assert res.status_code == 409
        assert error(res)["code"] == "CONFLICT"
        assert not sql_spy.any("pkg_license.create_license")

    def test_400s_a_rejection_with_no_comment_before_touching_the_database(self, client, db, sql_spy):
        rid = submitted(client, db, "YEARLY")
        sql_spy.clear()
        res = client.post(f"/api/v1/admin/license-requests/{rid}/reject", headers=manage(), json={})
        assert res.status_code == 400
        assert error(res)["code"] == "VALIDATION_ERROR"
        assert sql_spy.calls == []

    def test_rejects_an_under_review_request_and_notifies_the_requester(self, client, db):
        rid = submitted(client, db, "YEARLY")
        email = _request(db, rid)["email"]
        res = client.post(f"/api/v1/admin/license-requests/{rid}/reject", headers=manage(),
                          json={"comment": "Domain could not be verified."})

        assert res.status_code == 200
        assert data(res)["requestId"] == rid
        assert data(res)["status"] == "REJECTED"
        assert _request(db, rid)["status"] == "REJECTED"
        mails = db("SELECT template, body_text FROM email_outbox WHERE to_address = %s AND template = 'REQUEST_REJECTED'",
                   (email,))
        assert len(mails) == 1
        assert "Domain could not be verified." in mails[0]["body_text"]

    def test_requires_request_license_view_to_list_requests(self, client, sql_spy):
        res = client.get("/api/v1/admin/license-requests", headers=auth(token_with(["LICENSE_VIEW"])))
        assert res.status_code == 403
        assert error(res)["code"] == "FORBIDDEN"
        assert sql_spy.calls == []
