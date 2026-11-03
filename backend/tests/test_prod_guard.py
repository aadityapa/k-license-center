"""Production guard: default passwords and demo data are detected (services/prod_guard)."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


def test_detects_default_passwords_and_demo_clients(database):
    from app.db import connect_raw
    from app.services.prod_guard import accounts_on_default_password, demo_clients, problems

    with connect_raw() as conn:
        weak = accounts_on_default_password(conn)
        assert "admin" in weak                       # the test database has the seeded accounts
        assert demo_clients(conn)                    # ... and the demo data
        p = problems(conn)
        assert any("default password" in x for x in p) and any("demo API clients" in x for x in p)


def test_public_signing_keys_match_the_server(client):
    from app.services.vbs_key import vbs_public_key_base64
    from scripts.set_app_public_key import valid_p256_spki

    r = client.get("/api/v1/public/signing-keys")
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["vbsPublicKeySpki"] == vbs_public_key_base64() and valid_p256_spki(d["vbsPublicKeySpki"])
    assert d["licencePublicKey"] and "PRIVATE" not in r.text
