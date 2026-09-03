"""Sovereign Ledger database session layer.

PostgreSQL 16 is the sole system of record (D-2); access is psycopg 3.3.5 in
sync mode with ``dict_row`` rows (D-4). This module provides:

- ``make_pool``        -- psycopg_pool ConnectionPool factory (dict_row rows)
- ``serializable_tx``  -- bounded retry wrapper for money-mutation transactions
                          (SERIALIZABLE + SQLSTATE 40001 backoff; SKILL.md trap 5)
- ``run_serializable`` -- pool-level convenience around ``serializable_tx``
- ``database_url``     -- DSN resolution

SERIALIZABLE is scoped to money mutations only (posting, allocation, period
close) per D-7; plain reads stay READ COMMITTED -- do not wrap read-only work
in ``serializable_tx``.

DSN policy: the connection string is read from the ``DATABASE_URL`` environment
variable, defaulting to ``postgresql://ledger:ledger@127.0.0.1:11241/ledger``.
This module deliberately does NOT import ``config.settings`` -- the settings
integration is deferred to Step 5 wiring.

Dependency note: ``make_pool`` needs the ``psycopg_pool`` distribution (PyPI:
``psycopg-pool``), which the pinned scaffold does not currently include. The
import is deliberately lazy so that non-pool consumers (``scripts/init_db.py``)
run under a bare ``uv run``; pool users run with
``uv run --with psycopg-pool ...`` until the pin lands in pyproject.toml.
"""

from __future__ import annotations

import logging
import os
import time
from typing import TYPE_CHECKING, Callable, TypeVar

from psycopg.errors import SerializationFailure  # SQLSTATE 40001
from psycopg.rows import dict_row

if TYPE_CHECKING:  # pragma: no cover - typing only
    from psycopg_pool import ConnectionPool

T = TypeVar("T")

log = logging.getLogger(__name__)

DEFAULT_DSN = "postgresql://ledger:ledger@127.0.0.1:11241/ledger"


def database_url() -> str:
    """Resolve the DSN: ``DATABASE_URL`` env var, else the local default."""
    return os.environ.get("DATABASE_URL", DEFAULT_DSN)


def make_pool(
    dsn: str | None = None,
    *,
    min_size: int = 1,
    max_size: int = 5,
    open_pool: bool = True,
    name: str = "sovereign-ledger",
    conn_kwargs: dict | None = None,
) -> "ConnectionPool":
    """Create a psycopg_pool ``ConnectionPool`` (sync connections, dict rows).

    Pool shape is explicit rather than defaulted silently: ``min_size`` /
    ``max_size`` connections held open, rows returned as dicts (D-4). Pass
    ``open_pool=False`` to construct without connecting (e.g. unit tests).

    Requires the ``psycopg_pool`` package (see module docstring).
    """
    try:
        from psycopg_pool import ConnectionPool
    except ImportError as exc:  # pragma: no cover - depends on env
        raise ImportError(
            "psycopg_pool is required for make_pool() but is not installed in "
            "the project venv. Run with: uv run --with psycopg-pool <cmd>"
        ) from exc

    kwargs: dict = {"row_factory": dict_row}
    if conn_kwargs:
        kwargs.update(conn_kwargs)
    return ConnectionPool(
        conninfo=dsn or database_url(),
        min_size=min_size,
        max_size=max_size,
        name=name,
        open=open_pool,
        kwargs=kwargs,
    )


def serializable_tx(
    conn,
    work: Callable[[object], T],
    *,
    max_attempts: int = 5,
    backoff_s: float = 0.05,
) -> T:
    """Run ``work(conn)`` inside a SERIALIZABLE transaction with bounded retry
    on SQLSTATE 40001 (``SerializationFailure``) -- SKILL.md trap 5 pattern.

    Semantics:
    - the whole block re-runs from scratch on each attempt: ``work`` must be a
      complete money-mutation transaction, not an incremental step (a failed
      attempt is rolled back entirely anyway);
    - the connection must be idle (not inside another transaction) when the
      wrapper is entered: the isolation level is applied per-transaction via
      ``SET TRANSACTION ISOLATION LEVEL SERIALIZABLE`` as the FIRST statement
      of the block (psycopg 3.3.5 removed the ``transaction(isolation_level=)`
      kwarg that the SKILL.md trap-5 snippet shows; per-transaction SET
      TRANSACTION is the 3.3.5 equivalent and scopes SERIALIZABLE to exactly
      this transaction, so reads elsewhere stay READ COMMITTED per D-7);
    - ONLY ``SerializationFailure`` is retried; every other error (deadlock,
      integrity violation, connection loss, plain bugs) surfaces immediately;
    - after ``max_attempts`` failed attempts the final ``SerializationFailure``
      is re-raised -- bounded, never an infinite loop;
    - backoff is exponential: ``backoff_s * 2**attempt`` (0.05, 0.1, 0.2, ...);
    - every retry is logged at WARNING so masked contention stays observable.
    """
    for attempt in range(max_attempts):
        try:
            with conn.transaction():
                # Must precede any other statement of the transaction
                # (SQL requires SET TRANSACTION before queries in the tx).
                conn.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
                return work(conn)
        except SerializationFailure:
            if attempt == max_attempts - 1:
                raise
            delay = backoff_s * 2**attempt
            log.warning(
                "SQLSTATE 40001 serialization failure -- retry %d/%d in %.3fs",
                attempt + 1,
                max_attempts,
                delay,
            )
            time.sleep(delay)
    raise AssertionError("unreachable: retry loop always returns or raises")


def run_serializable(
    pool: "ConnectionPool",
    work: Callable[[object], T],
    *,
    max_attempts: int = 5,
    backoff_s: float = 0.05,
) -> T:
    """Check a connection out of ``pool`` and run ``serializable_tx`` on it."""
    with pool.connection() as conn:
        return serializable_tx(
            conn, work, max_attempts=max_attempts, backoff_s=backoff_s
        )