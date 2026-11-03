"""
Delete on every kind of record: admin deletes apply at once, a maker's delete
waits for a checker, records that still own licences refuse, and a licence
delete removes everything that belonged to it.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from support import auth, data, error, uniq

pytestmark = pytest.mark.integration
API = "/api/v1"


def _setup(client, admin):
    """product -> plan -> customer -> active licence (+renewal) -> API client -> one activation"""
    code = uniq("DL")[:12]
    prod = data(client.post(f"{API}/admin/products", headers=auth(admin),
                            json={"productCode": code, "productName": f"Del {code}", "keyPrefix": "DLT"}))
    pid = prod["productId"]
    plan = data(client.post(f"{API}/admin/plans", headers=auth(admin), json={
        "productId": pid, "planCode": "YR", "planName": "Year", "durationDays": 365, "maxActivations": 2}))
    cust = data(client.post(f"{API}/admin/customers", headers=auth(admin),
                            json={"customerCode": uniq("DC"), "companyName": f"Del Co {code}"}))
    lic = data(client.post(f"{API}/admin/licenses", headers=auth(admin), json={
        "customerId": cust["customerId"], "productId": pid, "planId": plan["planId"], "amount": 100}))
    lid = lic["licenseId"]
    key = data(client.post(f"{API}/admin/licenses/{lid}/activate", headers=auth(admin), json={}))["licenseKey"]
    assert client.post(f"{API}/admin/licenses/{lid}/renew", headers=auth(admin), json={"amount": 10}).status_code == 200
    api = data(client.post(f"{API}/admin/api-clients", headers=auth(admin), json={"productId": pid, "name": "del client"}))
    hdr = {"x-client-key": api["clientKey"], "x-client-secret": api["clientSecret"]}
    act = client.post(f"{API}/license/activate", headers=hdr, json={
        "licenseKey": key, "productCode": code, "installationId": uniq("INST"),
        "timestamp": datetime.now(timezone.utc).isoformat()})
    assert act.status_code == 200, act.text
    return {"pid": pid, "plan": plan["planId"], "cust": cust["customerId"], "lid": lid,
            "client": api["clientId"], "code": code}


def test_full_delete_chain(client, login, db):
    admin, maker, checker = login("admin"), login("maker"), login("checker")
    s = _setup(client, admin)

    # A product (or customer) that still has licences refuses.
    r = client.delete(f"{API}/admin/products/{s['pid']}", headers=auth(admin))
    assert r.status_code == 409 and error(r)["code"] == "PRODUCT_HAS_LICENSES"

    # Maker deletes the activation -> approval -> seat freed.
    act_id = db("SELECT activation_id FROM license_activations WHERE license_id = %s", (s["lid"],))[0]["activation_id"]
    sub = client.delete(f"{API}/admin/activations/{act_id}", headers=auth(maker))
    assert sub.status_code == 202, sub.text
    assert db("SELECT COUNT(*) AS n FROM license_activations WHERE activation_id = %s", (act_id,))[0]["n"] == 1
    ok = client.post(f"{API}/admin/change-requests/{data(sub)['changeRequestId']}/approve",
                     headers=auth(checker), json={})
    assert ok.status_code == 200, ok.text
    assert db("SELECT COUNT(*) AS n FROM license_activations WHERE activation_id = %s", (act_id,))[0]["n"] == 0
    assert db("SELECT current_activations AS c FROM licenses WHERE license_id = %s", (s["lid"],))[0]["c"] == 0

    # Renewal record.
    ren = db("SELECT renewal_id FROM license_renewals WHERE license_id = %s", (s["lid"],))[0]["renewal_id"]
    assert client.delete(f"{API}/admin/renewals/{ren}", headers=auth(admin)).status_code == 200

    # The licence with everything under it.
    r = client.delete(f"{API}/admin/licenses/{s['lid']}", headers=auth(admin))
    assert r.status_code == 200, r.text
    assert data(r) == {"licenseId": s["lid"], "deleted": True}
    for table in ("licenses", "license_keys", "license_history", "license_renewals"):
        assert db(f"SELECT COUNT(*) AS n FROM {table} WHERE license_id = %s", (s["lid"],))[0]["n"] == 0
    assert client.get(f"{API}/admin/licenses/{s['lid']}", headers=auth(admin)).status_code == 404

    # API client, then the product with its plans.
    assert client.delete(f"{API}/admin/api-clients/{s['client']}", headers=auth(admin)).status_code == 200
    r = client.delete(f"{API}/admin/products/{s['pid']}", headers=auth(admin))
    assert r.status_code == 200, r.text
    assert db("SELECT COUNT(*) AS n FROM product_plans WHERE product_id = %s", (s["pid"],))[0]["n"] == 0
    assert client.delete(f"{API}/admin/customers/{s['cust']}", headers=auth(admin)).status_code == 200

    # Audit trail records each delete.
    actions = {r["action"] for r in db("SELECT action FROM audit_logs WHERE action LIKE '%%_DELETED'")}
    assert {"ACTIVATION_DELETED", "RENEWAL_DELETED", "LICENSE_DELETED", "API_CLIENT_DELETED", "PRODUCT_DELETED"} <= actions


def test_request_email_and_history(client, login, db):
    admin, maker, viewer = login("admin"), login("maker"), login("viewer")
    email = f"{uniq('del').lower()}@example.com"
    inv = client.post(f"{API}/admin/license-requests/invite", headers=auth(admin),
                      json={"email": email, "productCode": "KSTACK"})
    assert inv.status_code in (200, 201), inv.text
    rid = db("SELECT request_id FROM license_requests WHERE email = %s", (email,))[0]["request_id"]
    eid = db("SELECT email_id FROM email_outbox WHERE to_address = %s", (email,))[0]["email_id"]

    assert client.delete(f"{API}/admin/license-requests/{rid}", headers=auth(viewer)).status_code == 403
    assert client.delete(f"{API}/admin/license-requests/{rid}", headers=auth(admin)).status_code == 200
    assert client.delete(f"{API}/admin/license-requests/{rid}", headers=auth(admin)).status_code == 404
    assert client.delete(f"{API}/admin/email-outbox/{eid}", headers=auth(admin)).status_code == 200
    assert db("SELECT COUNT(*) AS n FROM email_outbox WHERE email_id = %s", (eid,))[0]["n"] == 0

    # Approval history: a pending request cannot be deleted, a finished one can (admin only).
    sub = client.put(f"{API}/admin/customers/1", headers=auth(maker), json={"city": "Delete Test"})
    crid = data(sub)["changeRequestId"]
    r = client.delete(f"{API}/admin/change-requests/{crid}", headers=auth(admin))
    assert r.status_code == 409 and error(r)["code"] == "REQUEST_PENDING"
    assert client.post(f"{API}/admin/change-requests/{crid}/cancel", headers=auth(maker)).status_code == 200
    assert client.delete(f"{API}/admin/change-requests/{crid}", headers=auth(maker)).status_code == 403
    assert client.delete(f"{API}/admin/change-requests/{crid}", headers=auth(admin)).status_code == 200
