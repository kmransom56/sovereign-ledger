"""Starter chart of accounts (CoA) seed for the sovereign ledger.

A single-entity consulting/retail CoA with the five top-level account types
required by the ``accounts.account_type`` CHECK constraint in
``db/migrations/0001_core.sql`` (Assets / Liabilities / Equity / Income /
Expenses). Every row carries the ``subtype`` grouping used by reports and,
where applicable, a ``tax_mapping`` pointer consumed by ``tax/`` (P5:
Schedule C / Form 1099).

Seeding is IDEMPOTENT: rows are keyed on ``accounts.name`` (UNIQUE) and
re-running inserts nothing new and never mutates existing rows — consistent
with the append-only model (corrections are reversing entries, D-8).
"""

from __future__ import annotations

# (name, account_type, subtype, tax_mapping)
SEED_ACCOUNTS: tuple[tuple[str, str, str, str | None], ...] = (
    # --- Assets ---
    ("1000 Checking Account", "Assets", "bank", None),
    ("1010 Savings Account", "Assets", "bank", None),
    ("1200 Accounts Receivable", "Assets", "receivable", None),
    ("1500 Business Equipment", "Assets", "fixed_asset", "Form 4562"),
    # --- Liabilities ---
    ("2000 Accounts Payable", "Liabilities", "payable", None),
    ("2100 Credit Cards Payable", "Liabilities", "credit_card", None),
    # --- Equity ---
    ("3000 Owner's Capital", "Equity", "owner_equity", None),
    ("3900 Owner's Draws", "Equity", "owner_draws", None),
    # --- Income ---
    ("4000 Service Revenue", "Income", "operating_revenue", "Schedule C, Line 1"),
    ("4100 Interest Income", "Income", "other_income", "Schedule B, Part I"),
    # --- Expenses ---
    ("5000 Office Supplies", "Expenses", "operating_expense", "Schedule C, Line 18"),
    ("5100 Software & Subscriptions", "Expenses", "operating_expense", "Schedule C, Line 18"),
    ("5200 Rent Expense", "Expenses", "occupancy_expense", "Schedule C, Line 20b"),
    ("5300 Utilities", "Expenses", "occupancy_expense", "Schedule C, Line 25"),
    ("5400 Professional Fees", "Expenses", "professional_expense", "Schedule C, Line 17"),
)


def seed(conn) -> int:
    """Insert the starter CoA into a migrated database.

    Idempotent: ``ON CONFLICT (name) DO NOTHING``. Returns the number of rows
    actually inserted this run (0 on a re-run).
    """
    inserted = 0
    with conn.cursor() as cur:
        for name, account_type, subtype, tax_mapping in SEED_ACCOUNTS:
            cur.execute(
                """
                INSERT INTO accounts (name, account_type, subtype, tax_mapping)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (name) DO NOTHING
                """,
                (name, account_type, subtype, tax_mapping),
            )
            inserted += cur.rowcount  # 0 when the conflict path skipped
    return inserted