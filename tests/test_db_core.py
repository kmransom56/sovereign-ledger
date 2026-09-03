"""DB core tests for the sovereign ledger (Step 2 acceptance).

Runs against the session-scoped scratch PostgreSQL 16 fixture (tests/
conftest.py): podman postgres:16-alpine on 127.0.0.1:11241, database
ledger_test, migrated + seeded by scripts/init_db.py.

Three test groups (work order 02-schema-triggers-persistence.md):
  1. HR-1 at the storage boundary — an unbalanced journal entry raises at
     COMMIT (deferred constraint trigger, SKILL.md trap 4) and NOTHING is
     stored (row counts back to zero after the failed commit).
  2. HR-2 — the ledger_app role cannot UPDATE or DELETE any of the four
     append-only tables (permission denied; REVOKE enforced).
  3. D-7 retry wrapper — stubbed connection: SerializationFailure (SQLSTATE
     40001) is retried a bounded number of times then re-raised; any other
     error surfaces immediately with no retry.
"""

from __future__ import annotations

import psycopg
import pytest

from db.session import serializable_tx
from psycopg import errors as pgerr
from psycopg.rows import dict_row

# ----------------------------------------------------------------- helpers --


def _make_period(conn: psycopg.Connection) -> int:
    row = conn.execute(
        """
        INSERT INTO fiscal_periods (name, year, start_date, end_date)
        VALUES (%s, %s, %s, %s) RETURNING id
        """,
        ("2099-01", 2099, "2099-01-01", "2099-01-31"),
    ).fetchone()
    return row["id"]


def _counts(conn: psycopg.Connection) -> dict[str, int]:
    return {
        table: conn.execute(
            f"SELECT COUNT(*) AS n FROM {table}"  # noqa: S608 - fixed names
        ).fetchone()["n"]
        for table in (
            "fiscal_periods", "accounts", "journal_entries", "journal_lines",
        )
    }


# ------------------------------------------- 1. HR-1: deferred balance gate --

def test_unbalanced_entry_rejected_at_commit_and_nothing_stored(scratch_pg):
    """Trap-4 semantics: INSERTs succeed, COMMIT raises, zero rows remain."""
    dsn = scratch_pg
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        before = _counts(conn)
        period_id = _make_period(conn)

        entry_id = conn.execute(
            """
            INSERT INTO journal_entries (entry_date, description,
                                         fiscal_period_id)
            VALUES (%s, %s, %s) RETURNING id
            """,
            ("2099-01-15", "unbalanced: 100 vs 90", period_id),
        ).fetchone()["id"]

        acct_a = conn.execute(
            """
            INSERT INTO accounts (name, account_type, subtype)
            VALUES ('9990 Test Asset', 'Assets', 'test') RETURNING id
            """
        ).fetchone()["id"]
        acct_b = conn.execute(
            """
            INSERT INTO accounts (name, account_type, subtype)
            VALUES ('9991 Test Expense', 'Expenses', 'test') RETURNING id
            """
        ).fetchone()["id"]

        # 100 debit vs 90 credit -> sums to +10 cents, NOT zero. The INSERTs
        # themselves must succeed (trigger is DEFERRED).
        conn.execute(
            """
            INSERT INTO journal_lines (entry_id, account_id, amount_cents)
            VALUES (%s, %s, %s)
            """,
            (entry_id, acct_a, 100),
        )
        conn.execute(
            """
            INSERT INTO journal_lines (entry_id, account_id, amount_cents)
            VALUES (%s, %s, %s)
            """,
            (entry_id, acct_b, 90),
        )

        # The error fires at COMMIT, not at INSERT.
        with pytest.raises(psycopg.Error) as excinfo:
            conn.commit()

        msg = str(excinfo.value)
        assert "not balanced" in msg, msg

    # Everything the failed transaction wrote is rolled back: the entry, both
    # lines, the accounts, and the period. Row counts are unchanged.
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        after = _counts(conn)
    assert after == before, f"rows leaked from failed commit: {before} -> {after}"


def test_balanced_entry_commits_and_persists(scratch_pg):
    """Control case: a balanced two-line entry stores cleanly."""
    dsn = scratch_pg
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        period_id = _make_period(conn)
        acct_a = conn.execute(
            """
            INSERT INTO accounts (name, account_type, subtype)
            VALUES ('9992 Test Bank', 'Assets', 'test') RETURNING id
            """
        ).fetchone()["id"]
        acct_b = conn.execute(
            """
            INSERT INTO accounts (name, account_type, subtype)
            VALUES ('9993 Test Revenue', 'Income', 'test') RETURNING id
            """
        ).fetchone()["id"]
        entry_id = conn.execute(
            """
            INSERT INTO journal_entries (entry_date, description,
                                         fiscal_period_id)
            VALUES (%s, %s, %s) RETURNING id
            """,
            ("2099-01-16", "balanced: 250/250", period_id),
        ).fetchone()["id"]
        conn.execute(
            """
            INSERT INTO journal_lines (entry_id, account_id, amount_cents)
            VALUES (%s, %s, 250), (%s, %s, -250)
            """,
            (entry_id, acct_a, entry_id, acct_b),
        )
        conn.commit()

        line_count = conn.execute(
            "SELECT COUNT(*) AS n FROM journal_lines WHERE entry_id = %s",
            (entry_id,),
        ).fetchone()["n"]
        assert line_count == 2


# --------------------------------------- 2. HR-2: app-role UPDATE/DELETE ban --

APP_ONLY_TABLES = ("accounts", "journal_entries", "journal_lines",
                   "fiscal_periods")


@pytest.fixture(scope="module")
def app_role_conn(scratch_pg):
    """A connection acting AS ledger_app (the migration's NOLOGIN app role).

    SET ROLE is committed immediately so the role persists across the module's
    tests — a rollback() later must not revert it (implicit-transaction trap).
    """
    with psycopg.connect(scratch_pg) as conn:
        conn.execute("SET ROLE ledger_app")
        conn.commit()
        yield conn
        conn.rollback()  # nothing was ever written by the probes; be tidy


@pytest.mark.parametrize("table", APP_ONLY_TABLES)
def test_app_role_cannot_update_append_only_tables(app_role_conn, table):
    # Probe a non-identity column: `SET id = id` fails in the rewrite phase
    # (GENERATED ALWAYS AS IDENTITY) BEFORE the ACL check, which would mask
    # the permission denial this test is proving.
    probe_col = {"accounts": "name", "journal_entries": "description",
                 "journal_lines": "memo", "fiscal_periods": "status"}[table]
    with pytest.raises(psycopg.Error) as excinfo:
        app_role_conn.execute(f"UPDATE {table} SET {probe_col} = {probe_col}")  # noqa: S608
    app_role_conn.rollback()
    assert isinstance(excinfo.value, pgerr.InsufficientPrivilege), (
        f"expected permission denied on UPDATE {table}, got: "
        f"{type(excinfo.value).__name__}: {excinfo.value}"
    )


@pytest.mark.parametrize("table", APP_ONLY_TABLES)
def test_app_role_cannot_delete_append_only_tables(app_role_conn, table):
    with pytest.raises(psycopg.Error) as excinfo:
        app_role_conn.execute(f"DELETE FROM {table}")  # noqa: S608
    app_role_conn.rollback()
    assert isinstance(excinfo.value, pgerr.InsufficientPrivilege), (
        f"expected permission denied on DELETE {table}, got: "
        f"{type(excinfo.value).__name__}: {excinfo.value}"
    )


def test_app_role_can_still_read(app_role_conn):
    """HR-2 is a privilege floor, not a wall: SELECT must keep working."""
    app_role_conn.execute("SELECT COUNT(*) FROM accounts")
    app_role_conn.rollback()


def test_owner_update_blocked_by_trigger(scratch_pg):
    """The block-UPDATE/DELETE triggers fire even for the table owner."""
    with psycopg.connect(scratch_pg) as conn:
        conn.execute(
            "INSERT INTO accounts (name, account_type, subtype) "
            "VALUES ('9994 Trigger Probe', 'Assets', 'test')"
        )
        with pytest.raises(psycopg.Error) as excinfo:
            conn.execute(
                "UPDATE accounts SET name = 'x' WHERE name = '9994 Trigger Probe'"
            )
        conn.rollback()
        assert "append-only" in str(excinfo.value), str(excinfo.value)

        conn.execute(
            "INSERT INTO accounts (name, account_type, subtype) "
            "VALUES ('9995 Trigger Probe 2', 'Assets', 'test')"
        )
        with pytest.raises(psycopg.Error) as excinfo:
            conn.execute("DELETE FROM accounts WHERE name = '9995 Trigger Probe 2'")
        conn.rollback()
        assert "append-only" in str(excinfo.value), str(excinfo.value)


# ------------------------------------------------- 3. D-7: retry wrapper ----


class _StubConn:
    """Minimal connection stand-in for serializable_tx unit tests.

    `behaviors` is a list: each item is consumed at COMMIT time (clean
    ``__exit__``) — an Exception to raise there (simulating a 40001 that
    surfaces at COMMIT) or None for a successful commit. Work-body exceptions
    propagate untouched. Records every attempt and every executed SQL
    statement so tests can assert retry counts and the per-transaction
    SERIALIZABLE scoping exactly.
    """

    def __init__(self, behaviors: list):
        self.behaviors = list(behaviors)
        self.attempts = 0
        self.statements: list[str] = []

    class _Tx:
        def __init__(self, conn):
            self.conn = conn

        def __enter__(self):
            self.conn.attempts += 1
            return self

        def __exit__(self, exc_type, exc, tb):
            if exc_type is not None:
                return False  # work-body failure: propagate untouched
            # Clean body == COMMIT time: the queued behavior fires here,
            # because that is where a real serialization failure surfaces.
            behavior = self.conn.behaviors.pop(0) if self.conn.behaviors else None
            if behavior is not None:
                raise behavior
            return False

    def transaction(self, savepoint_name=None, force_rollback=False):
        # psycopg 3.3.5 signature: serializable_tx must open a real
        # transaction, never a savepoint of an outer one.
        assert savepoint_name is None
        return _StubConn._Tx(self)

    def execute(self, sql, params=None):
        self.statements.append(sql)


def test_retry_wrapper_retries_serialization_failure_bounded(scratch_pg):
    """40001 is retried up to max_attempts, then the last failure re-raises."""
    fail = pgerr.SerializationFailure("40001: could not serialize access")
    conn = _StubConn([fail, fail, fail, fail])  # every attempt fails

    with pytest.raises(pgerr.SerializationFailure):
        serializable_tx(conn, lambda c: "never", max_attempts=4, backoff_s=0.001)

    assert conn.attempts == 4  # bounded: exactly max_attempts, no infinite loop
    # SERIALIZABLE was scoped per-transaction on every attempt (D-7), even the
    # ones that failed at COMMIT — SET TRANSACTION always ran first.
    assert conn.statements.count(
        "SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"
    ) == 4
    assert conn.statements[0] == "SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"


def test_retry_wrapper_eventually_succeeds_after_failures(scratch_pg):
    fail = pgerr.SerializationFailure("40001: could not serialize access")
    conn = _StubConn([fail, fail, None])  # fails twice, then succeeds

    result = serializable_tx(conn, lambda c: "ok", max_attempts=5, backoff_s=0.001)
    assert result == "ok"
    assert conn.attempts == 3


def test_retry_wrapper_surfaces_non_40001_immediately(scratch_pg):
    """Deadlock/bugs/etc. must NOT be retried — they surface on attempt 1."""
    boom = pgerr.DeadlockDetected("40P01: deadlock detected")
    conn = _StubConn([boom])

    with pytest.raises(pgerr.DeadlockDetected):
        serializable_tx(conn, lambda c: None, max_attempts=5, backoff_s=0.001)

    assert conn.attempts == 1  # no retry for non-SerializationFailure


def test_retry_wrapper_work_runs_fully_each_attempt(scratch_pg):
    """Each attempt re-runs the whole work block from scratch (trap 5)."""
    calls: list[int] = []
    fail = pgerr.SerializationFailure("40001")

    def work(conn):
        calls.append(len(calls) + 1)
        if len(calls) < 3:
            raise fail
        return len(calls)

    conn = _StubConn([None, None, None])
    assert serializable_tx(conn, work, max_attempts=5, backoff_s=0.001) == 3
    assert calls == [1, 2, 3]