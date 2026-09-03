#!/usr/bin/env python3
"""Wave CSV → opening-balance entries (Step 5, CK-1/T-8).

Imports a Wave accounting CSV export and posts the opening balances
as a single balanced journal entry via the Step 3
:func:`ledger.accounts.opening_balance_entry` helper.

Wave CSV export format (the standard account balances export):
    Account,Type,Debit,Credit
    1000 Checking Account,Asset,1500.00,
    2000 Accounts Payable,Liability,,450.00
    3000 Owner's Capital,Equity,,800.00
    ...

The script:
1. Parses the CSV (charset-normalizer for cp1252 safety — trap 12).
2. Maps each row to the matching account in the DB by name.
3. Calls opening_balance_entry() to build a balanced entry (residual
   absorbed by the opening_bank account).
4. Inserts the entry into the DB.

Usage:
    DATABASE_URL=postgresql://... \
        uv run python scripts/wave_cutover_import.py --csv wave_export.csv \
            --opening-bank "1000 Checking Account" --date 2026-01-01
"""

from __future__ import annotations

import argparse
import csv
import logging
import sys
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import psycopg

from ledger.accounts import Account, AccountStatus, AccountType
from ledger.accounts import opening_balance_entry
from app.repository import load_accounts, insert_journal_entry, find_period_for_date

log = logging.getLogger("wave_cutover")

#: Column headers we accept (case-insensitive, whitespace-trimmed).
REQUIRED_COLS = {"account", "debit", "credit"}


def _detect_encoding(path: Path) -> str:
    """Detect the file encoding (trap 12: Wave exports are often cp1252)."""
    try:
        from charset_normalizer import from_path
        result = from_path(str(path))
        if result.best():
            return result.best().encoding
    except ImportError:
        pass
    return "utf-8"


def parse_wave_csv(path: Path) -> list[tuple[str, str, int, int]]:
    """Parse a Wave CSV export into (name, type, debit_cents, credit_cents) rows.

    Returns:
        List of (account_name, account_type, debit_cents, credit_cents).
        debit_cents and credit_cents are non-negative integers; one is 0
        unless both sides are populated (which Wave doesn't do, but we
        handle gracefully).
    """
    encoding = _detect_encoding(path)
    rows: list[tuple[str, str, int, int]] = []
    with open(path, encoding=encoding, newline="") as f:
        reader = csv.DictReader(f)
        headers = {h.strip().lower() for h in (reader.fieldnames or [])}
        if not REQUIRED_COLS.issubset(headers):
            missing = REQUIRED_COLS - headers
            raise ValueError(
                f"Wave CSV missing required columns {missing}; found {headers}"
            )
        for i, row in enumerate(reader, start=2):
            name = (row.get("account") or row.get("Account") or "").strip()
            if not name:
                continue  # skip blank rows
            acct_type = (row.get("type") or row.get("Type") or "").strip()
            debit_str = (row.get("debit") or row.get("Debit") or "").strip()
            credit_str = (row.get("credit") or row.get("Credit") or "").strip()

            debit_cents = _parse_money(debit_str, f"row {i} debit")
            credit_cents = _parse_money(credit_str, f"row {i} credit")
            rows.append((name, acct_type, debit_cents, credit_cents))
    return rows


def _parse_money(s: str, ctx: str) -> int:
    """Parse a money string to integer cents (0 for empty)."""
    if not s:
        return 0
    try:
        d = Decimal(s.replace(",", ""))  # strip thousands separators
    except InvalidOperation:
        raise ValueError(f"invalid money value {s!r} in {ctx}")
    from ledger.types import cents_from_decimal
    return cents_from_decimal(d)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(name)s: %(message)s")

    parser = argparse.ArgumentParser(description="Import Wave CSV export as opening balances.")
    parser.add_argument("--csv", required=True, help="Path to Wave CSV export.")
    parser.add_argument("--opening-bank", required=True, help="Opening bank account name.")
    parser.add_argument("--date", required=True, help="Opening balance date (YYYY-MM-DD).")
    parser.add_argument("--entry-id", default=None, help="Override entry id (default: OB-<date>).")
    args = parser.parse_args()

    csv_path = Path(args.csv)
    if not csv_path.is_file():
        print(f"error: CSV file not found: {csv_path}", file=sys.stderr)
        return 1

    entry_date = date.fromisoformat(args.date)

    from db.session import database_url

    with psycopg.connect(database_url()) as conn:
        # Load accounts from DB.
        db_accounts = load_accounts(conn)
        name_to_account = {a.name: a for a in db_accounts}

        # Parse Wave CSV.
        wave_rows = parse_wave_csv(csv_path)
        if not wave_rows:
            print("error: no rows found in Wave CSV", file=sys.stderr)
            return 1

        # Separate debit-normal and credit-normal balances.
        debit_balances: dict[Account, int] = {}
        credit_balances: dict[Account, int] = {}

        for name, acct_type, debit_cents, credit_cents in wave_rows:
            acct = name_to_account.get(name)
            if acct is None:
                log.warning("account %r not found in DB — skipping", name)
                continue
            if debit_cents > 0:
                debit_balances[acct] = debit_balances.get(acct, 0) + debit_cents
            if credit_cents > 0:
                credit_balances[acct] = credit_balances.get(acct, 0) + credit_cents

        opening_bank = name_to_account.get(args.opening_bank)
        if opening_bank is None:
            print(f"error: opening bank account {args.opening_bank!r} not found in DB", file=sys.stderr)
            return 1

        # Build the opening-balance entry.
        try:
            entry = opening_balance_entry(
                debit_balances=debit_balances,
                credit_balances=credit_balances,
                opening_bank=opening_bank,
                entry_date=entry_date,
                entry_id=args.entry_id,
            )
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1

        # Persist to DB.
        period = find_period_for_date(conn, entry_date)
        if period is None:
            print(f"error: no fiscal period covers {entry_date.isoformat()}", file=sys.stderr)
            return 1

        # Get the period's DB id.
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM fiscal_periods WHERE name = %s",
                (period.name,),
            )
            row = cur.fetchone()
            if row is None:
                print(f"error: fiscal period {period.name!r} not found in DB", file=sys.stderr)
                return 1
            period_id = row[0]

        try:
            entry_db_id = insert_journal_entry(conn, entry, period_id)
            conn.commit()
        except Exception as exc:
            conn.rollback()
            print(f"error: failed to persist opening-balance entry: {exc}", file=sys.stderr)
            return 1

    print(f"wave_cutover_import: opening-balance entry {entry_db_id} posted ({entry.entry_id})")
    print(f"  debit total: {sum(l.amount_cents for l in entry.lines if l.amount_cents > 0)} cents")
    print(f"  credit total: {-sum(l.amount_cents for l in entry.lines if l.amount_cents < 0)} cents")
    print(f"  lines: {len(entry.lines)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())