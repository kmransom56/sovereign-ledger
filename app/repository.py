"""DB read adapter: load domain objects from PostgreSQL.

This module is the bridge between storage and the pure domain core.
It reads rows from the database and constructs ``ledger/`` domain
objects — no business logic here, just row-to-value-object mapping.

All functions take a psycopg connection (or cursor) and return pure
domain values. Write paths are NOT here — posting goes through the
domain core (``ledger.entries.post_draft``) and the caller persists the
result; this module reads what was persisted.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import psycopg

from ledger.accounts import Account, AccountStatus, SUBTYPE_TAX_MAPPINGS
from ledger.types import AccountRef, AccountType, JournalEntry, JournalLine
from ledger.periods import FiscalPeriod, PeriodStatus

#: Map the DB's capitalized plural account_type to the domain enum value.
_DB_TYPE_MAP = {
    "assets": AccountType.ASSET,
    "liabilities": AccountType.LIABILITY,
    "equity": AccountType.EQUITY,
    "income": AccountType.INCOME,
    "expenses": AccountType.EXPENSE,
}


def load_accounts(conn: psycopg.Connection) -> list[Account]:
    """Load all accounts from the DB, ordered by name."""
    with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
        cur.execute(
            "SELECT name, account_type, subtype, tax_mapping, "
            "       (SELECT 1) AS exists_flag "
            "FROM accounts ORDER BY name"
        )
        rows = cur.fetchall()
    accounts: list[Account] = []
    for row in rows:
        # DB stores capitalized plurals ('Assets'); enum values are lowercase singular ('asset').
        raw_type = row["account_type"].lower()
        atype = _DB_TYPE_MAP.get(raw_type)
        if atype is None:
            continue  # skip rows with unknown account_type (e.g. test fixtures)
        try:
            accounts.append(Account(
                name=row["name"],
                type=atype,
                subtype=row["subtype"],
                tax_mapping=row["tax_mapping"],
                status=AccountStatus.ACTIVE,
            ))
        except (ValueError, TypeError):
            continue  # skip rows with invalid subtypes (e.g. test_db_core fixtures)
    return accounts


def load_account_by_name(conn: psycopg.Connection, name: str) -> Account | None:
    """Load a single account by name, or None."""
    with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
        cur.execute(
            "SELECT name, account_type, subtype, tax_mapping FROM accounts WHERE name = %s",
            (name,),
        )
        row = cur.fetchone()
    if row is None:
        return None
    return Account(
        name=row["name"],
        type=_DB_TYPE_MAP[row["account_type"].lower()],
        subtype=row["subtype"],
        tax_mapping=row["tax_mapping"],
        status=AccountStatus.ACTIVE,
    )


def load_periods(conn: psycopg.Connection) -> list[FiscalPeriod]:
    """Load all fiscal periods from the DB, ordered by start_date."""
    with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
        cur.execute(
            "SELECT name, year, start_date, end_date, status "
            "FROM fiscal_periods ORDER BY start_date"
        )
        rows = cur.fetchall()
    return [
        FiscalPeriod(
            name=row["name"],
            year=row["year"],
            start_date=row["start_date"],
            end_date=row["end_date"],
            status=PeriodStatus(row["status"]),
        )
        for row in rows
    ]


def load_journal_entries(conn: psycopg.Connection) -> list[JournalEntry]:
    """Load all journal entries with their lines, ordered by date then id."""
    with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
        cur.execute(
            "SELECT je.id AS entry_id, je.entry_date, je.description, "
            "       jl.account_id, a.name AS account_name, "
            "       a.account_type AS account_type, jl.amount_cents "
            "FROM journal_entries je "
            "JOIN journal_lines jl ON jl.entry_id = je.id "
            "JOIN accounts a ON a.id = jl.account_id "
            "ORDER BY je.entry_date, je.id, jl.id"
        )
        rows = cur.fetchall()

    entries: dict[int, dict[str, Any]] = {}
    for row in rows:
        eid = row["entry_id"]
        if eid not in entries:
            entries[eid] = {
                "entry_id": str(eid),
                "date": row["entry_date"],
                "description": row["description"],
                "lines": [],
            }
        atype = _DB_TYPE_MAP[row["account_type"].lower()]
        ref = AccountRef(
            code=row["account_name"].split(" ", 1)[0],
            name=row["account_name"],
            type=atype,
        )
        entries[eid]["lines"].append(JournalLine(account=ref, amount_cents=row["amount_cents"]))

    result: list[JournalEntry] = []
    for eid in sorted(entries):
        data = entries[eid]
        result.append(JournalEntry(
            entry_id=data["entry_id"],
            date=data["date"],
            description=data["description"],
            lines=tuple(data["lines"]),
        ))
    return result


def insert_journal_entry(
    conn: psycopg.Connection,
    entry: JournalEntry,
    fiscal_period_id: int,
) -> int:
    """Persist a journal entry and its lines; return the DB row id.

    This is the write path — the caller has already validated the entry
    through the domain core (``post_draft``). The DEFERRABLE trigger
    re-verifies balance at COMMIT.
    """
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO journal_entries (entry_date, description, fiscal_period_id) "
            "VALUES (%s, %s, %s) RETURNING id",
            (entry.date, entry.description, fiscal_period_id),
        )
        entry_db_id = cur.fetchone()[0]
        for line in entry.lines:
            cur.execute(
                "SELECT id FROM accounts WHERE name = %s",
                (line.account.name,),
            )
            account_row = cur.fetchone()
            if account_row is None:
                raise ValueError(f"account {line.account.name!r} not found in DB")
            account_id = account_row[0]
            cur.execute(
                "INSERT INTO journal_lines (entry_id, account_id, amount_cents) "
                "VALUES (%s, %s, %s)",
                (entry_db_id, account_id, line.amount_cents),
            )
    return entry_db_id


def find_period_for_date(
    conn: psycopg.Connection,
    day: date,
) -> FiscalPeriod | None:
    """Find the fiscal period covering ``day``, or None."""
    with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
        cur.execute(
            "SELECT name, year, start_date, end_date, status "
            "FROM fiscal_periods WHERE start_date <= %s AND end_date >= %s",
            (day, day),
        )
        row = cur.fetchone()
    if row is None:
        return None
    return FiscalPeriod(
        name=row["name"],
        year=row["year"],
        start_date=row["start_date"],
        end_date=row["end_date"],
        status=PeriodStatus(row["status"]),
    )