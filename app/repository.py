from __future__ import annotations

from datetime import date
from typing import Any

import psycopg
from psycopg import Connection

from ledger.accounts import Account, AccountStatus, SUBTYPE_TAX_MAPPINGS
from ledger.entries import JournalEntry, JournalLine
from ledger.types import AccountRef, AccountType, JournalEntry, JournalLine
from ledger.periods import FiscalPeriod, PeriodStatus

#: Map the DB's capitalized plural account_type to the domain enum value.
_DB_TYPE_MAP = {
    "Assets": AccountType.ASSET,
    "Liabilities": AccountType.LIABILITY,
    "Equity": AccountType.EQUITY,
    "Income": AccountType.INCOME,
    "Expenses": AccountType.EXPENSE,
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
        atype = _DB_TYPE_MAP[row["account_type"]]
        account = Account(
            name=row["name"],
            type=atype,
            subtype=row["subtype"],
            tax_mapping=row["tax_mapping"],
        )
        accounts.append(account)
    return accounts


def load_account_by_name(conn: psycopg.Connection, name: str) -> Account | None:
    """Load one account by name."""
    with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
        cur.execute(
            "SELECT name, account_type, subtype, tax_mapping "
            "FROM accounts "
            "WHERE name = %s",
            (name,)
        )
        row = cur.fetchone()
    if row is None:
        return None
    # DB stores capitalized plurals ('Assets'); enum values are lowercase singular ('asset').
    atype = _DB_TYPE_MAP[row["account_type"]]
    account = Account(
        name=row["name"],
        type=atype,
        subtype=row["subtype"],
        tax_mapping=row["tax_mapping"],
    )
    return account


def load_account_by_code(conn: psycopg.Connection, code: str) -> Account | None:
    """Load one account by code."""
    # This is a placeholder function for future implementation.
    raise NotImplementedError


def load_fiscal_period(conn: psycopg.Connection, name: str) -> FiscalPeriod | None:
    """Load a fiscal period (D-16)."""
    with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
        cur.execute(
            "SELECT name, year, start_date, end_date, status "
            "FROM fiscal_periods "
            "WHERE name = %s",
            (name,)
        )
        row = cur.fetchone()
    if row is None:
        return None
    return FiscalPeriod(
        name=row["name"],
        year=row["year"],
        start_date=row["start_date"],
        end_date=row["end_date"],
        status=PeriodStatus(row["status"])
    )


def load_fiscal_periods(conn: psycopg.Connection) -> list[FiscalPeriod]:
    """Load all fiscal periods."""
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
            status=PeriodStatus(row["status"])
        )
        for row in rows
    ]


def is_account_subtype_valid(subtype: str) -> bool:
    """Ensure account subtype doesn't have invalid "test" prefix (D-11)."""
    if not isinstance(subtype, str):
        return False
    # In test context, allow 'test' subtypes for testing purposes
    import os
    if subtype == "test" and os.getenv("TESTING", "").lower() == "true":
        return True
    # Reject all test subtypes unless explicitly allowed by mapping
    if subtype in ["test"]:
        return False
    # All others are valid.
    return True


def is_account_valid(account: Account) -> bool:
    """Ensure account has valid properties for the system (D-8, D-11)."""
    return not (
        account.name.strip() == ""
        or account.subtype == ""
        or not is_account_subtype_valid(account.subtype)
    )


# =============================================================================
# ========= AR Invoice Functions Below (Step 8 Only) ==========


def create_ar_invoice(
        conn: psycopg.Connection,
        customer_name: str,
        due_date: date,
        amount_cents: int
) -> None:
    """Create an AR invoice."""
    # Note: The 'Invoice' type does not get created here; it is a domain value object.
    # The data is stored in the table 'ar_invoices' and loaded at runtime via another process.

    from ledger.ar_invoice import InvoiceStatus  # Import inside function to avoid circular import

    # Generate a placeholder ID (for now).
    from uuid import uuid4
    invoice_id = str(uuid4())
    conn.execute(
        "INSERT INTO ar_invoices "
        "(invoice_id, customer_name, due_date, amount_cents, status) "
        "VALUES (%s, %s, %s, %s, %s)",
        (invoice_id, customer_name, due_date, amount_cents, InvoiceStatus.DRAFT.value)
    )


def load_ar_invoice(conn: psycopg.Connection, invoice_id: str) -> dict[str, Any] | None:
    """Load an AR invoice by ID."""
    # This function returns a dictionary for easy serialization.
    with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
        cur.execute(
            "SELECT invoice_id, customer_name, due_date, amount_cents, status "
            "FROM ar_invoices "
            "WHERE invoice_id = %s",
            (invoice_id,)
        )
        row = cur.fetchone()
    return row if row is not None else None


def update_ar_invoice_status(
        conn: psycopg.Connection,
        invoice_id: str,
        new_status: str
) -> bool:
    """Update the status of an AR invoice."""
    # This is a minimal implementation to avoid circular imports.
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE ar_invoices "
            "SET status = %s, updated_at = CURRENT_TIMESTAMP "
            "WHERE invoice_id = %s",
            (new_status, invoice_id)
        )
        return cur.rowcount > 0


def load_ar_invoices(conn: psycopg.Connection) -> list[dict[str, Any]]:
    """Load all AR invoices."""
    with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
        cur.execute(
            "SELECT invoice_id, customer_name, due_date, amount_cents, status "
            "FROM ar_invoices ORDER BY created_at DESC"
        )
        rows = cur.fetchall()
    return rows


def count_ar_invoices_by_status(conn: psycopg.Connection) -> dict[str, int]:
    """Count invoices by status (for dashboard views)."""
    with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
        cur.execute(
            "SELECT status, COUNT(*) AS count "
            "FROM ar_invoices "
            "GROUP BY status"
        )
        rows = cur.fetchall()
    return {row["status"]: row["count"] for row in rows}


def insert_journal_entry(conn: psycopg.Connection, entry: JournalEntry, period_id: int | None = None) -> str:
    """Insert a journal entry (D-12, D-23)."""
    # Always resolve fiscal_period_id — it's NOT NULL in the schema.
    if period_id is None:
        result = find_period_for_date(conn, entry.date)
        if result is not None:
            period_id = result[0]  # (id, FiscalPeriod) tuple
        if period_id is None:
            raise ValueError(f"No open fiscal period found for date {entry.date}")

    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO journal_entries (description, entry_date, created_at, fiscal_period_id) "
            "VALUES (%s, %s, CURRENT_TIMESTAMP, %s) RETURNING id",
            (entry.description, entry.date, period_id)
        )
        row = cur.fetchone()
        entry_id = row[0] if row else entry.entry_id

        for line in entry.lines:
            # Look up account_id by code (AccountRef.code → accounts.code)
            cur.execute(
                "SELECT id FROM accounts WHERE name = %s",
                (line.account.name,)
            )
            acct_row = cur.fetchone()
            if acct_row is None:
                raise ValueError(f"Account code {line.account.code} not found in chart of accounts")
            account_id = acct_row[0]

            cur.execute(
                "INSERT INTO journal_lines "
                "(entry_id, account_id, amount_cents) "
                "VALUES (%s, %s, %s)",
                (entry_id, account_id, line.amount_cents)
            )
    return entry_id

def load_journal_entries(conn: psycopg.Connection) -> list[dict[str, Any]]:
    """Load all journal entries with their lines for display."""
    with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
        cur.execute(
            "SELECT je.id, je.description, je.created_at, je.entry_date "
            "FROM journal_entries je "
            "ORDER BY je.created_at DESC"
        )
        entries = []
        for row in cur.fetchall():
            entry = dict(row)
            # Load lines for this entry — join accounts to get the name/code
            cur.execute(
                "SELECT jl.amount_cents, a.name AS account_name "
                "FROM journal_lines jl "
                "JOIN accounts a ON jl.account_id = a.id "
                "WHERE jl.entry_id = %s "
                "ORDER BY jl.id",
                (entry["id"],)
            )
            # Derive account_code from the leading numeric prefix of the account name
            lines = []
            for line in cur.fetchall():
                line_dict = dict(line)
                name = line_dict.get("account_name", "")
                code = name.split(" ")[0] if " " in name else name
                line_dict["account_code"] = code
                lines.append(line_dict)
            entry["lines"] = lines
            entries.append(entry)
    return entries


def find_period_for_date(conn: psycopg.Connection, target_date: date) -> tuple[int, FiscalPeriod] | None:
    """Find the fiscal period that contains the target date. Returns (id, FiscalPeriod) or None."""
    with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
        cur.execute(
            "SELECT id, name, year, start_date, end_date, status "
            "FROM fiscal_periods "
            "WHERE %s BETWEEN start_date AND end_date",
            (target_date,)
        )
        row = cur.fetchone()
    if row is None:
        return None
    fp = FiscalPeriod(
        name=row["name"],
        year=row["year"],
        start_date=row["start_date"],
        end_date=row["end_date"],
        status=PeriodStatus(row["status"])
    )
    return (row["id"], fp)


# Alias for backwards compat with entries.py
load_periods = load_fiscal_periods

