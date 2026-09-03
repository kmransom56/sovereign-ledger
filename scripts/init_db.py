#!/usr/bin/env python3
"""Apply sovereign-ledger SQL migrations in numeric order, then seed.

Contract (db/migrations/README.md, decision D-5 — NO Alembic/SQLAlchemy):
- migrations are plain ordered SQL files ``NNNN_name.sql`` in db/migrations;
- applied strictly in ascending numeric order: gaps abort, out-of-order
  application is refused;
- applied files are recorded in ``schema_migrations`` (name + applied_at) so
  re-runs are idempotent — applied files are skipped, new files append in
  order.

Usage (against the scratch Postgres, or the quadlet in Step 5):
    DATABASE_URL=postgresql://ledger:ledger@127.0.0.1:11241/ledger \
        uv run python scripts/init_db.py

The DSN comes from the ``DATABASE_URL`` env var (default in
``db.session.database_url``). This script deliberately does NOT import
``config.settings`` — settings wiring is deferred to Step 5.

Importable: tests use ``from scripts.init_db import main`` (namespace package;
the repo root must be on ``sys.path`` — tests/conftest.py arranges that).
"""

from __future__ import annotations

import logging
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import psycopg

from db.seed.chart_of_accounts import seed as seed_coa
from db.seed.users import seed as seed_users
from db.seed.fiscal_periods import seed as seed_periods
from db.session import database_url

log = logging.getLogger("init_db")

MIGRATIONS_DIR = REPO_ROOT / "db" / "migrations"
MIGRATION_RE = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")


def migration_files() -> list[tuple[int, Path]]:
    """All migration files sorted numerically; abort on gaps (README rule)."""
    found: list[tuple[int, Path]] = []
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        match = MIGRATION_RE.match(path.name)
        if match is None:
            raise RuntimeError(
                f"migration file {path.name!r} does not match the NNNN_name.sql "
                "contract (db/migrations/README.md)"
            )
        found.append((int(match.group(1)), path))
    if not found:
        raise RuntimeError(f"no migration files found in {MIGRATIONS_DIR}")
    found.sort(key=lambda item: item[0])
    nums = [num for num, _ in found]
    if nums != list(range(nums[0], nums[0] + len(nums))):
        raise RuntimeError(
            f"migration numbering has gaps: {nums} "
            "(db/migrations/README.md refusal-of-gaps rule)"
        )
    if nums[0] != 1:
        raise RuntimeError(
            f"migrations must start at 0001; first file is {nums[0]:04d}"
        )
    return found


def apply_migrations(conn: psycopg.Connection) -> list[str]:
    """Apply unapplied migrations in numeric order; return names applied now."""
    files = migration_files()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            name       TEXT PRIMARY KEY,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    applied = {
        row[0] for row in conn.execute("SELECT name FROM schema_migrations")
    }
    highest_applied = max((int(name[:4]) for name in applied), default=0)

    newly_applied: list[str] = []
    for num, path in files:
        if path.name in applied:
            continue
        if num < highest_applied:
            raise RuntimeError(
                f"refusing out-of-order migration {path.name!r}: "
                f"{highest_applied:04d}_* is already applied"
            )
        # One migration = one atomic unit: if any statement fails, neither the
        # DDL nor the schema_migrations bookkeeping row survives.
        with conn.transaction():
            conn.execute(path.read_text(encoding="utf-8"))
            conn.execute(
                "INSERT INTO schema_migrations (name) VALUES (%s)", (path.name,)
            )
        highest_applied = num
        newly_applied.append(path.name)
        log.info("applied migration %s", path.name)
    return newly_applied


def seed(conn: psycopg.Connection) -> tuple[int, int, int]:
    coa_count = seed_coa(conn)
    user_count = seed_users(conn)
    period_count = seed_periods(conn)
    return coa_count, user_count, period_count


def main() -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)-7s %(name)s: %(message)s"
    )
    with psycopg.connect(database_url()) as conn:
        newly_applied = apply_migrations(conn)
        coa_count, user_count, period_count = seed(conn)
    print(
        "init_db: migrations applied now: "
        f"{newly_applied or '(none — already up to date)'}"
    )
    print(f"init_db: chart-of-accounts rows inserted this run: {coa_count}")
    print(f"init_db: user rows inserted this run: {user_count}")
    print(f"init_db: fiscal period rows inserted this run: {period_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())