"""
Creates / upgrades the PostgreSQL database from database/postgres/*.sql.

    python -m scripts.db_migrate            apply every file not yet applied
    python -m scripts.db_migrate --status   list applied / pending, change nothing

Connection comes from backend/.env exactly as the server reads it
(DATABASE_URL, or DB_HOST / DB_PORT / DB_NAME / DB_USER / DB_PASSWORD).
Files run in name order, each in its own transaction, and are recorded in
schema_migrations so a file is never applied twice. Never edit a file that has
already been applied to a live database — add a new NNN_<what>.sql instead.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import connect_raw  # noqa: E402
from app.migrate import MigrationError, run_migrations  # noqa: E402


def main() -> int:
    status_only = "--status" in sys.argv
    try:
        conn = connect_raw()
    except Exception as err:  # noqa: BLE001
        return _explain(err)
    try:
        r = run_migrations(conn, status_only=status_only, log=print)
        if r.skipped_reason:
            print(f"Nothing done: {r.skipped_reason}.")
        else:
            print("Status only — nothing changed." if status_only else f"Done. {len(r.applied)} file(s) applied.")
        return 0
    except MigrationError as err:
        print(f"\nMigration failed in {err.file}: {err.err}")
        return _explain(err.err, printed=True)
    finally:
        conn.close()


def _explain(err: BaseException, printed: bool = False) -> int:
    code = getattr(err, "sqlstate", None) or ""
    text = str(err)
    if not printed:
        print(f"\nMigration failed: {text.strip()}{f' (SQLSTATE {code})' if code else ''}")
    if code == "28P01" or "password authentication failed" in text:
        print("Check DB_USER / DB_PASSWORD in backend/.env.")
    if code == "3D000" or "does not exist" in text and "database" in text:
        print("The database does not exist yet: create it in pgAdmin first (see database/postgres/README.md).")
    if "Connection refused" in text or "could not connect" in text:
        print("PostgreSQL is not reachable on DB_HOST:DB_PORT — is the service running?")
    if code == "42P07":
        print("Tables already exist (created by hand?). Use an empty database, or record the files in schema_migrations.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
