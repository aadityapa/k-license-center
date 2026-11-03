"""
POST /api/v1/auth/login. Port of tests/auth.test.ts: the mocked user row is a
real user created for each test (so failed-attempt counting never touches the
shared demo accounts), and "the UPDATE ran" becomes "the row changed".
"""
from __future__ import annotations

import pytest

from support import data, error, uniq

pytestmark = pytest.mark.integration

PASSWORD = "Correct#123"


@pytest.fixture
def fresh_user(db):
    """An ACTIVE user with the VIEWER role and a known password."""
    from app.security import hash_password

    name = uniq("pytest_").lower()
    row = db(
        """INSERT INTO users (username, email, full_name, password_hash, status, failed_attempts)
           VALUES (%s, %s, 'Pytest User', %s, 'ACTIVE', 0) RETURNING user_id""",
        (name, f"{name}@pytest.example", hash_password(PASSWORD, 4)),
    )
    uid = int(row[0]["user_id"])
    db("INSERT INTO user_roles (user_id, role_id) SELECT %s, role_id FROM roles WHERE role_code = 'VIEWER'", (uid,))
    return {"userId": uid, "username": name}


def _user(db, uid: int) -> dict:
    return db("SELECT status, failed_attempts, last_login_at FROM users WHERE user_id = %s", (uid,))[0]


def test_returns_a_token_and_the_user_with_permissions(client, db, fresh_user, sql_spy):
    db("UPDATE users SET failed_attempts = 2 WHERE user_id = %s", (fresh_user["userId"],))
    sql_spy.clear()

    res = client.post("/api/v1/auth/login", json={"username": fresh_user["username"], "password": PASSWORD})

    assert res.status_code == 200
    body = res.json()
    assert body["success"] is True
    assert isinstance(body["data"]["token"], str) and body["data"]["token"]
    user = body["data"]["user"]
    assert user["userId"] == fresh_user["userId"]
    assert user["username"] == fresh_user["username"]
    expected = db(
        """SELECT DISTINCT p.perm_code FROM role_permissions rp JOIN roles r USING (role_id)
             JOIN permissions p USING (perm_id) WHERE r.role_code = 'VIEWER'"""
    )
    assert sorted(user["permissions"]) == sorted(r["perm_code"] for r in expected)
    assert len(user["permissions"]) == len(set(user["permissions"]))
    assert body["requestId"]
    # The failed-attempt counter was reset, once, and committed.
    assert len(sql_spy.matching("failed_attempts = 0")) == 1
    after = _user(db, fresh_user["userId"])
    assert after["failed_attempts"] == 0
    assert after["last_login_at"] is not None


def test_rejects_a_wrong_password_and_increments_failed_attempts(client, db, fresh_user, sql_spy):
    res = client.post("/api/v1/auth/login", json={"username": fresh_user["username"], "password": "wrong-password"})

    assert res.status_code == 401
    assert res.json()["success"] is False
    assert error(res)["code"] == "UNAUTHORIZED"
    assert len(sql_spy.matching("failed_attempts + 1")) == 1
    assert _user(db, fresh_user["userId"])["failed_attempts"] == 1  # committed although the login failed


def test_rejects_a_locked_account_even_with_the_right_password(client, db, fresh_user, sql_spy):
    db("UPDATE users SET status = 'LOCKED' WHERE user_id = %s", (fresh_user["userId"],))
    sql_spy.clear()

    res = client.post("/api/v1/auth/login", json={"username": fresh_user["username"], "password": PASSWORD})

    assert res.status_code == 401
    assert error(res)["code"] == "UNAUTHORIZED"
    assert "locked" in error(res)["message"].lower()
    # Refused without comparing the password: nothing was written.
    assert not sql_spy.any("UPDATE users")
    assert _user(db, fresh_user["userId"])["failed_attempts"] == 0


def test_rejects_an_invalid_body_before_touching_the_database(client, sql_spy):
    res = client.post("/api/v1/auth/login", json={"username": "admin"})
    assert res.status_code == 400
    assert error(res)["code"] == "VALIDATION_ERROR"
    assert sql_spy.calls == []


def test_the_token_works_on_the_admin_api(client, fresh_user):
    res = client.post("/api/v1/auth/login", json={"username": fresh_user["username"], "password": PASSWORD})
    me = client.get("/api/v1/auth/me", headers={"authorization": f"Bearer {data(res)['token']}"})
    assert me.status_code == 200
    assert data(me)["username"] == fresh_user["username"]
