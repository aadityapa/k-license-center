"""
/api/v1/admin: authentication, permissions, error mapping and the maker-checker
gate. Port of tests/admin.test.ts — there the SQL layer was mocked; here every
case runs against the real PostgreSQL demo database, and the "which statements
ran" assertions use the pass-through `sql_spy` plus the rows left in the DB.
"""
from __future__ import annotations

import pytest

from support import auth, create_licence, data, error, raw_token, token_with

pytestmark = pytest.mark.integration


def test_rejects_requests_without_a_token(client):
    res = client.get("/api/v1/admin/products")
    assert res.status_code == 401
    assert error(res)["code"] == "UNAUTHORIZED"


def test_rejects_a_token_missing_the_required_permission(client, sql_spy):
    res = client.get("/api/v1/admin/products", headers=auth(token_with(["LICENSE_VIEW"])))
    assert res.status_code == 403
    body = res.json()
    assert body["success"] is False
    assert body["error"]["code"] == "FORBIDDEN"
    assert body["requestId"]
    assert sql_spy.calls == []  # refused before any SQL ran


def test_lists_products_with_the_paging_envelope(client, db):
    res = client.get("/api/v1/admin/products", headers=auth(token_with(["PRODUCT_VIEW"])))
    assert res.status_code == 200
    page = data(res)
    total = db("SELECT COUNT(*) AS n FROM products")[0]["n"]
    assert page["total"] == total
    assert page["page"] == 1
    assert page["pageSize"] == 20
    assert len(page["items"]) == total
    kstack = next(p for p in page["items"] if p["productId"] == 1)
    assert kstack["productCode"] == "KSTACK"
    assert kstack["keyPrefix"] == "KSTK"


def test_maps_a_plpgsql_raise_to_409_without_leaking_database_text(client, login):
    # A DRAFT licence cannot be suspended: pkg_license.change_status RAISEs
    # INVALID_STATE_TRANSITION (SQLSTATE P0001).
    admin = login("admin")
    lid = create_licence(client, admin, "KSTACK", activate=False)
    res = client.post(f"/api/v1/admin/licenses/{lid}/suspend",
                      headers=auth(token_with(["LICENSE_MANAGE"])), json={"reason": "Payment overdue"})
    assert res.status_code == 409
    assert error(res)["code"] == "INVALID_STATE_TRANSITION"
    assert "pkg_license" not in error(res)["message"]
    assert "PL/pgSQL" not in error(res)["message"]


def test_maps_unknown_database_errors_to_internal_error_without_detail(client, db):
    # A real "relation does not exist" (42P01) from PostgreSQL.
    db("ALTER TABLE products RENAME TO products_hidden_by_test")
    try:
        res = client.get("/api/v1/admin/products", headers=auth(token_with(["PRODUCT_VIEW"])))
    finally:
        db("ALTER TABLE products_hidden_by_test RENAME TO products")
    assert res.status_code == 500
    assert error(res)["code"] == "INTERNAL_ERROR"
    assert "relation" not in error(res)["message"]
    assert "products" not in error(res)["message"]


def test_rejects_a_suspend_without_reason(client):
    res = client.post("/api/v1/admin/licenses/42/suspend", headers=auth(token_with(["LICENSE_MANAGE"])), json={})
    assert res.status_code == 400
    assert error(res)["code"] == "VALIDATION_ERROR"


# ------------------------------------------------------------- maker-checker
class TestApprovalGate:
    def test_applies_immediately_for_an_admin_holding_approval_bypass(self, client, login, db, sql_spy):
        lid = create_licence(client, login("admin"), "KSTACK")
        lic_no = db("SELECT license_no FROM licenses WHERE license_id = %s", (lid,))[0]["license_no"]
        sql_spy.clear()

        res = client.post(f"/api/v1/admin/licenses/{lid}/suspend",
                          headers=auth(token_with(["LICENSE_MANAGE"])), json={"reason": "Payment overdue"})

        assert res.status_code == 200
        assert data(res)["licenseNo"] == lic_no
        assert data(res)["status"] == "SUSPENDED"
        assert "pendingApproval" not in data(res)
        # The real mutation ran, and no change request was written.
        assert sql_spy.any("pkg_license.suspend_license")
        assert not sql_spy.any("INSERT INTO change_requests")
        assert db("SELECT status FROM licenses WHERE license_id = %s", (lid,))[0]["status"] == "SUSPENDED"
        assert db("SELECT COUNT(*) AS n FROM change_requests WHERE entity_type = 'LICENSE' AND entity_id = %s",
                  (lid,))[0]["n"] == 0

    def test_queues_a_pending_change_request_for_a_maker_and_runs_no_mutation(self, client, login, db, user_id,
                                                                               sql_spy):
        lid = create_licence(client, login("admin"), "KSTACK", customer_id=1)
        lic_no = db("SELECT license_no FROM licenses WHERE license_id = %s", (lid,))[0]["license_no"]
        maker = raw_token(["LICENSE_REVOKE", "REQUEST_SUBMIT"], user_id("maker"), "maker")
        sql_spy.clear()

        res = client.post(f"/api/v1/admin/licenses/{lid}/revoke", headers=auth(maker), json={"reason": "non-payment"})

        assert res.status_code == 202
        body = res.json()
        assert body["success"] is True
        assert body["data"]["pendingApproval"] is True
        cr_id = body["data"]["changeRequestId"]
        assert isinstance(cr_id, int)
        assert body["data"]["message"] == (
            f'Revoke licence {lic_no} for "Acme Distributors Pvt Ltd" (reason: non-payment) submitted for approval.'
        )
        assert sql_spy.any("INSERT INTO change_requests")
        assert not sql_spy.any("pkg_license.revoke_license")
        cr = db("SELECT entity_type, entity_id, status, requested_by FROM change_requests WHERE request_id = %s",
                (cr_id,))[0]
        assert cr == {"entity_type": "LICENSE", "entity_id": lid, "status": "PENDING",
                      "requested_by": user_id("maker")}
        assert db("SELECT status FROM licenses WHERE license_id = %s", (lid,))[0]["status"] == "ACTIVE"

    def test_rejects_a_user_with_neither_approval_bypass_nor_request_submit(self, client, login, db, user_id,
                                                                             sql_spy):
        lid = create_licence(client, login("admin"), "KSTACK")
        # A checker: may approve other people's changes, may not make their own.
        checker = raw_token(["LICENSE_REVOKE", "REQUEST_APPROVE"], user_id("checker"), "checker")
        sql_spy.clear()

        res = client.post(f"/api/v1/admin/licenses/{lid}/revoke", headers=auth(checker), json={"reason": "non-payment"})

        assert res.status_code == 403
        assert error(res)["code"] == "FORBIDDEN"
        assert not sql_spy.any("INSERT INTO change_requests")
        assert not sql_spy.any("pkg_license.revoke_license")
        assert db("SELECT status FROM licenses WHERE license_id = %s", (lid,))[0]["status"] == "ACTIVE"
        assert db("SELECT COUNT(*) AS n FROM change_requests WHERE entity_type = 'LICENSE' AND entity_id = %s",
                  (lid,))[0]["n"] == 0


def test_returns_the_not_found_envelope_for_unknown_routes(client):
    res = client.get("/api/v1/nope")
    assert res.status_code == 404
    assert error(res)["code"] == "NOT_FOUND"
    assert res.json()["requestId"]
