"""
Applies database/postgres/NNN_*.sql files that have not been applied yet.

Used by `python -m scripts.db_migrate` and automatically when the API starts
(AUTO_MIGRATE, on by default). Each file runs in its own transaction and is
recorded in schema_migrations (same table and checksums as before, so an
existing database carries straight on); a file that fails is rolled back and
stops the run.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import psycopg

from .config import PROJECT_ROOT

MIGRATIONS_DIR = PROJECT_ROOT / "database" / "postgres"


@dataclass
class MigrationResult:
    applied: list[str] = field(default_factory=list)
    pending: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)
    skipped_reason: str | None = None


class MigrationError(Exception):
    def __init__(self, file: str, err: Exception):
        super().__init__(str(err))
        self.file = file
        self.err = err
        self.sqlstate = getattr(err, "sqlstate", None)


def migration_files(d: Path = MIGRATIONS_DIR) -> list[str]:
    if not d.is_dir():
        return []
    return sorted(p.name for p in d.iterdir() if re.fullmatch(r"\d{3}_.+\.sql", p.name))


def run_migrations(
    conn: psycopg.Connection,
    status_only: bool = False,
    d: Path = MIGRATIONS_DIR,
    log: Callable[[str], None] = lambda _l: None,
) -> MigrationResult:
    files = migration_files(d)
    result = MigrationResult()
    if not files:
        result.skipped_reason = f"no migration files in {d}"
        return result

    with conn.cursor() as cur:
        cur.execute(
            "SELECT to_regclass('schema_migrations') IS NOT NULL, to_regclass('users') IS NOT NULL"
        )
        tracked, has_tables = cur.fetchone()
    conn.commit()
    if not tracked and has_tables:
        result.skipped_reason = (
            "tables exist but schema_migrations does not (database built by hand) — apply new files manually"
        )
        return result

    if not status_only:
        with conn.cursor() as cur:
            cur.execute(
                """CREATE TABLE IF NOT EXISTS schema_migrations (
                     filename   VARCHAR(200) PRIMARY KEY,
                     checksum   VARCHAR(64)  NOT NULL,
                     applied_at TIMESTAMPTZ  DEFAULT now() NOT NULL
                   )"""
            )
        conn.commit()

    done: dict[str, str] = {}
    if tracked:
        with conn.cursor() as cur:
            cur.execute("SELECT filename, checksum FROM schema_migrations")
            done = {str(a): str(b) for a, b in cur.fetchall()}
        conn.commit()

    for name in files:
        raw = (d / name).read_bytes()
        checksum = hashlib.sha256(raw).hexdigest()
        prev = done.get(name)
        if prev is not None:
            if prev != checksum:
                result.changed.append(name)
                log(f"  ! {name} has changed since it was applied — not re-run. Put changes in a new file.")
            else:
                log(f"  = {name} (already applied)")
            continue
        if status_only:
            result.pending.append(name)
            log(f"  - {name} (pending)")
            continue
        try:
            with conn.cursor() as cur:
                cur.execute(raw.decode("utf-8"))  # no parameters: run as a script
                cur.execute(
                    "INSERT INTO schema_migrations (filename, checksum) VALUES (%s, %s)", (name, checksum)
                )
            conn.commit()
            result.applied.append(name)
            log(f"  + {name} ... ok")
        except Exception as err:
            conn.rollback()
            log(f"  + {name} ... FAILED")
            raise MigrationError(name, err) from err
    return result
