"""User seed for the Sovereign Ledger (Step 4, D-12/CK-12).

Seeds two users:

* ``keith`` — admin role (full write access)
* ``accountant`` — accountant role (read-only)

Passwords are argon2id hashes (OWASP floor m=19456 KiB, t=2, p=1) generated
at seed time via argon2-cffi (D-12: direct call, never passlib).  The default
passwords are development-only and MUST be changed on first login in any
real deployment — the seed function accepts an optional override dict.

Idempotent: ON CONFLICT (username) DO NOTHING.
"""

from __future__ import annotations

import logging

import psycopg

log = logging.getLogger("seed.users")

DEFAULT_ADMIN_USERNAME = "keith"
DEFAULT_ADMIN_PASSWORD = "change-me-on-first-login"

DEFAULT_ACCOUNTANT_USERNAME = "accountant"
DEFAULT_ACCOUNTANT_PASSWORD = "read-only-audit"


def _argon2_hash(password: str) -> str:
    """Argon2id hash at OWASP floor (D-12, direct argon2-cffi call)."""
    from argon2 import PasswordHasher

    ph = PasswordHasher(
        time_cost=2,
        memory_cost=19456,
        parallelism=1,
    )
    return ph.hash(password)


def seed(
    conn: psycopg.Connection,
    *,
    passwords: dict[str, str] | None = None,
) -> int:
    """Insert admin and accountant users with argon2 hashes.

    Args:
        conn: psycopg connection to a migrated database.
        passwords: optional override {username: password} for non-default
            credentials (e.g. test fixtures).  Missing keys fall back to
            the module-level defaults.

    Returns:
        Number of rows actually inserted this run (0 on re-run).
    """
    pw = passwords or {}
    users = [
        (DEFAULT_ADMIN_USERNAME, _argon2_hash(pw.get(DEFAULT_ADMIN_USERNAME, DEFAULT_ADMIN_PASSWORD)), "admin"),
        (DEFAULT_ACCOUNTANT_USERNAME, _argon2_hash(pw.get(DEFAULT_ACCOUNTANT_USERNAME, DEFAULT_ACCOUNTANT_PASSWORD)), "accountant"),
    ]
    inserted = 0
    with conn.cursor() as cur:
        for username, password_hash, role in users:
            cur.execute(
                """
                INSERT INTO users (username, password_hash, role)
                VALUES (%s, %s, %s)
                ON CONFLICT (username) DO NOTHING
                """,
                (username, password_hash, role),
            )
            inserted += cur.rowcount
    return inserted