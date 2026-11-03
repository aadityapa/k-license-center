"""
Prepares a PRODUCTION database (run once, after the database is created):

    python -m scripts.prod_init
    docker compose run --rm api python -m scripts.prod_init        (AWS / Docker)

1. Builds / upgrades the tables (same as scripts.db_migrate).
2. Refuses if demo data was loaded (demo API clients) — production needs a clean database.
3. Gives every starter account still on the published default password
   (admin, maker, checker, viewer / Pass@100%) a new password, or locks it.
   The main `admin` must get a password (it cannot be locked).

Non-interactive (CI / cloud-init): set INIT_ADMIN_PASSWORD, and optionally
INIT_MAKER_PASSWORD / INIT_CHECKER_PASSWORD / INIT_VIEWER_PASSWORD; starter
accounts without one are locked. Also INIT_ADMIN_EMAIL to set the admin's e-mail.

Lost password:  python -m scripts.prod_init --reset-password <username>   (sets a new one, unlocks)

The API (NODE_ENV=production) refuses to start until this has been done.
"""
from __future__ import annotations

import getpass
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import connect_raw  # noqa: E402
from app.migrate import MigrationError, run_migrations  # noqa: E402
from app.security import hash_password  # noqa: E402
from app.services.prod_guard import DEFAULT_PASSWORDS, accounts_on_default_password, demo_clients  # noqa: E402

STARTER = ("admin", "maker", "checker", "viewer")


def strong_enough(pw: str) -> str | None:
    if len(pw) < 12:
        return "at least 12 characters"
    if not (re.search(r"[A-Za-z]", pw) and re.search(r"\d", pw) and re.search(r"[^A-Za-z0-9]", pw)):
        return "letters, digits and a symbol"
    if pw in DEFAULT_PASSWORDS:
        return "not a default password"
    return None


def ask_password(user: str, required: bool) -> str | None:
    env = os.environ.get(f"INIT_{user.upper()}_PASSWORD")
    if env:
        why = strong_enough(env)
        if why:
            raise SystemExit(f"INIT_{user.upper()}_PASSWORD is too weak: needs {why}.")
        return env
    if not sys.stdin.isatty():
        if required:
            raise SystemExit(f"Set INIT_{user.upper()}_PASSWORD (no terminal to ask on).")
        return None
    while True:
        hint = "" if required else " (Enter = lock this account)"
        pw = getpass.getpass(f"  New password for '{user}'{hint}: ")
        if not pw and not required:
            return None
        why = strong_enough(pw)
        if why:
            print(f"    Too weak — needs {why}.")
            continue
        if getpass.getpass("  Repeat: ") != pw:
            print("    The two passwords differ.")
            continue
        return pw


def reset_password(user: str) -> int:
    """--reset-password <user>: new password + unlock (lost password)."""
    conn = connect_raw()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM users WHERE username = %s", (user,))
            if not cur.fetchone():
                print(f"No user '{user}'.")
                return 1
        pw = ask_password(user, required=True)
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE users SET password_hash = %s, status = 'ACTIVE', failed_attempts = 0, updated_at = now() WHERE username = %s",
                (hash_password(pw, 12), user),
            )
            cur.execute(
                """INSERT INTO audit_logs (actor, action, entity_type, entity_id, after_state)
                   SELECT 'scripts:prod_init', 'USER_PASSWORD_RESET', 'USER', user_id, %s FROM users WHERE username = %s""",
                ('{"username": "%s"}' % user, user),
            )
        conn.commit()
        print(f"'{user}': new password set and account unlocked.")
        return 0
    finally:
        conn.close()


def main() -> int:
    if "--reset-password" in sys.argv:
        i = sys.argv.index("--reset-password")
        if i + 1 >= len(sys.argv):
            print("Usage: python -m scripts.prod_init --reset-password <username>")
            return 1
        return reset_password(sys.argv[i + 1])
    conn = connect_raw()
    try:
        print("1. Database tables")
        try:
            r = run_migrations(conn, log=lambda l: print("   " + l))
        except MigrationError as e:
            print(f"   Migration failed in {e.file}: {e.err}")
            return 1
        print(f"   {r.skipped_reason or f'{len(r.applied)} file(s) applied, up to date.'}")

        print("2. Demo data")
        demo = demo_clients(conn)
        if demo:
            print(f"   Demo API clients found ({', '.join(demo)}) — demo_data.sql was loaded into this database.")
            print("   Production must start from a clean database. Drop it, create it again and re-run this.")
            return 1
        print("   none (good)")

        print("3. Starter accounts")
        weak = accounts_on_default_password(conn)
        if not weak:
            print("   no account uses a default password (good)")
        for user in weak:
            if user not in STARTER:
                print(f"   '{user}' uses a default password — change it in the portal (Users → Edit).")
                continue
            pw = ask_password(user, required=(user == "admin"))
            with conn.cursor() as cur:
                if pw:
                    cur.execute(
                        "UPDATE users SET password_hash = %s, failed_attempts = 0, updated_at = now() WHERE username = %s",
                        (hash_password(pw, 12), user),
                    )
                    action = "USER_PASSWORD_SET"
                    print(f"   '{user}': new password set")
                else:
                    cur.execute("UPDATE users SET status = 'LOCKED', updated_at = now() WHERE username = %s", (user,))
                    action = "USER_LOCKED"
                    print(f"   '{user}': locked (unlock later in the portal: Users → Edit)")
                cur.execute(
                    """INSERT INTO audit_logs (actor, action, entity_type, entity_id, after_state)
                       SELECT 'scripts:prod_init', %s, 'USER', user_id, %s FROM users WHERE username = %s""",
                    (action, '{"username": "%s"}' % user, user),
                )
            conn.commit()

        email = os.environ.get("INIT_ADMIN_EMAIL")
        if email:
            with conn.cursor() as cur:
                cur.execute("UPDATE users SET email = %s, updated_at = now() WHERE username = 'admin'", (email,))
            conn.commit()
            print(f"   admin e-mail set to {email}")

        left = accounts_on_default_password(conn)
        if left:
            print(f"\nStill on a default password: {', '.join(left)} — the API will not start in production.")
            return 1
        print("\nReady for production. Start (or restart) the API.")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
