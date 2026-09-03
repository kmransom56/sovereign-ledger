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
        status=row["status"]
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
            status=row["status"]
        )
        for row in rows
    ]


def is_account_subtype_valid(subtype: str) -> bool:
    """Ensure account subtype doesn't have invalid "test" prefix (D-11)."""
    if not isinstance(subtype, str):
        return False
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


def insert_journal_entry(conn: psycopg.Connection, entry: JournalEntry) -> None:
    """Insert a journal entry (D-12, D-23)."""
    with conn.cursor() as cur:
        # Insert the main entry
        cur.execute(
            "INSERT INTO journal_entries (id, description, created_at) "
            "VALUES (%s, %s, CURRENT_TIMESTAMP)",
            (entry.id, entry.description)
        )

        for line in entry.lines:
            cur.execute(
                "INSERT INTO journal_lines "
                "(journal_entry_id, account_name, debit, credit) "
                "VALUES (%s, %s, %s, %s)",
                (
                    entry.id,
                    line.account.name,
                    line.debit,
                    line.credit
                )
            )

def load_journal_entries(conn: psycopg.Connection) -> list[dict[str, Any]]:
    """Load all journal entries with their lines for display."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT je.id, je.description, je.created_at "
            "FROM journal_entries je "
            "ORDER BY je.created_at DESC"
        )
        entries = []
        for row in cur.fetchall():
            entry = dict(row)
            # Load lines for this entry
            cur.execute(
                "SELECT account_name, debit, credit "
                "FROM journal_lines "
                "WHERE journal_entry_id = %s "
                "ORDER BY id",
                (entry["id"],)
            )
            entry["lines"] = [dict(l) for l in cur.fetchall()]
            entries.append(entry)
    return entries


def find_period_for_date(conn: psycopg.Connection, target_date: date) -> FiscalPeriod | None:
    """Find the fiscal period that contains the target date."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT name, start_date, end_date, status "
            "FROM fiscal_periods "
            "WHERE %s BETWEEN start_date AND end_date",
            (target_date,)
        )
        row = cur.fetchone()
    if row is None:
        return None
    return FiscalPeriod(
        name=row["name"],
        start_date=row["start_date"],
        end_date=row["end_date"],
        status=PeriodStatus(row["status"])
    )


# Alias for backwards compat with entries.py
load_periods = load_fiscal_periods

