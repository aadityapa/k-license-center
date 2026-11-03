"""
Production readiness checks on the database (NODE_ENV=production).

The API refuses to start in production while
  * a starter account (admin, maker, checker, viewer) can still sign in with a
    published default password (Pass@100% / ChangeMe@123), or
  * the demo API clients from database/postgres/demo/demo_data.sql exist.

`python -m scripts.prod_init` fixes the first; the second means demo data was
loaded into the production database — use a fresh database.
"""
from __future__ import annotations

from typing import Any

from ..security import check_password

DEFAULT_PASSWORDS = ("Pass@100%", "ChangeMe@123")


def accounts_on_default_password(conn: Any) -> list[str]:
    """Active accounts whose password is one of the published defaults."""
    with conn.cursor() as cur:
        cur.execute("SELECT username, password_hash FROM users WHERE status = 'ACTIVE' ORDER BY user_id")
        rows = cur.fetchall()
    out = []
    for r in rows:
        name, h = (r["username"], r["password_hash"]) if isinstance(r, dict) else (r[0], r[1])
        if any(check_password(p, str(h)) for p in DEFAULT_PASSWORDS):
            out.append(str(name))
    return out


def demo_clients(conn: Any) -> list[str]:
    with conn.cursor() as cur:
        cur.execute("SELECT client_key FROM api_clients WHERE client_key LIKE 'demo-%' AND status = 'ACTIVE'")
        rows = cur.fetchall()
    return [str(r["client_key"] if isinstance(r, dict) else r[0]) for r in rows]


def problems(conn: Any) -> list[str]:
    out = []
    users = accounts_on_default_password(conn)
    if users:
        out.append(
            f"accounts still on the default password: {', '.join(users)} — run `python -m scripts.prod_init` "
            "(Docker: `docker compose run --rm api python -m scripts.prod_init`)"
        )
    demo = demo_clients(conn)
    if demo:
        out.append(
            f"demo API clients found ({', '.join(demo)}): demo_data.sql was loaded — use a fresh production database"
        )
    return out


def assert_production_ready(conn: Any) -> None:
    p = problems(conn)
    if p:
        raise RuntimeError("Not safe to run in production: " + "; ".join(p))
