"""AP posting: bill creation, payment recording, reconciliation (Step 12).

Handles double-entry accounting for bills and payments. Bill posting creates:
  Dr. Expense Account(s)
  Cr. Accounts Payable Liability

Payment posting creates:
  Dr. Accounts Payable Liability
  Cr. Bank / Cash Account
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import TYPE_CHECKING

from ledger.accounts import Account, AccountStatus
from ledger.entries import new_draft, post_draft
from ledger.periods import FiscalPeriod, PeriodStatus
from ledger.types import AccountType

if TYPE_CHECKING:
    import psycopg

#: Map the DB's capitalized plural account_type to the domain enum value.
_DB_TYPE_MAP = {
    "assets": AccountType.ASSET,
    "liabilities": AccountType.LIABILITY,
    "equity": AccountType.EQUITY,
    "income": AccountType.INCOME,
    "expenses": AccountType.EXPENSE,
}


class APPostingError(Exception):
    """Base exception for AP posting failures."""

    pass


class VendorNotFoundError(APPostingError):
    """Vendor does not exist."""

    pass


class BillAlreadyPostedError(APPostingError):
    """Bill has already been posted."""

    pass


class InvalidPaymentError(APPostingError):
    """Payment validation failed."""

    pass


def load_vendor(conn: psycopg.Connection, vendor_id: int) -> dict:
    """Load vendor by ID."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, name, tax_id, email, payment_terms, is_active FROM vendors WHERE id = %s",
            (vendor_id,),
        )
        row = cur.fetchone()
        if not row:
            raise VendorNotFoundError(f"Vendor {vendor_id} not found")

        return {
            "id": row[0],
            "name": row[1],
            "tax_id": row[2],
            "email": row[3],
            "payment_terms": row[4],
            "is_active": row[5],
        }


def load_expense_category(
    conn: psycopg.Connection, category_id: int, id_to_account: dict[int, Account]
) -> Account:
    """Load expense category with account mapping.

    Args:
        conn: Database connection.
        category_id: Expense category ID.
        id_to_account: Mapping of account IDs to Account objects.

    Returns:
        Account object for the expense category.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, code, name, account_id, tax_deductible FROM expense_categories WHERE id = %s",
            (category_id,),
        )
        row = cur.fetchone()
        if not row:
            raise APPostingError(f"Expense category {category_id} not found")

        cat_id, code, name, acct_id, tax_deductible = row

        if not acct_id:
            raise APPostingError(f"Expense category {category_id} has no account mapping")

        if acct_id not in id_to_account:
            raise APPostingError(f"Account {acct_id} for category {category_id} not found")

        return id_to_account[acct_id]


def load_accounts_catalog(conn: psycopg.Connection) -> tuple[dict[int, Account], dict[str, int], dict[Account, AccountStatus]]:
    """Load all accounts from chart of accounts.

    Returns:
        Tuple of (id_to_account mapping, name_to_id mapping, account catalog for post_draft).
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, name, account_type, subtype, tax_mapping FROM accounts WHERE is_active = true ORDER BY name"
        )
        rows = cur.fetchall()

    id_to_account = {}
    name_to_id = {}
    catalog = {}

    for row in rows:
        acct_id, name, acct_type, subtype, tax_mapping = row
        # DB stores capitalized plurals ('Assets'); enum values are lowercase singular ('asset').
        raw_type = acct_type.lower()
        atype = _DB_TYPE_MAP.get(raw_type)
        if atype is None:
            continue  # skip rows with unknown account_type

        try:
            account = Account(
                name=name,
                type=atype,
                subtype=subtype,
                tax_mapping=tax_mapping,
                status=AccountStatus.ACTIVE,
            )
            id_to_account[acct_id] = account
            name_to_id[name] = acct_id
            # All loaded accounts are ACTIVE for posting
            catalog[account] = AccountStatus.ACTIVE
        except (ValueError, TypeError):
            continue  # skip rows with invalid subtypes

    return id_to_account, name_to_id, catalog


def load_fiscal_periods(conn: psycopg.Connection) -> list[FiscalPeriod]:
    """Load fiscal periods from database."""
    with conn.cursor() as cur:
        cur.execute("SELECT name, year, start_date, end_date, status FROM fiscal_periods ORDER BY start_date")
        rows = cur.fetchall()

    periods = []
    for row in rows:
        name, year, start_date, end_date, status = row
        # Map DB status to PeriodStatus enum
        pstatus = PeriodStatus(status)
        periods.append(FiscalPeriod(name=name, year=year, start_date=start_date, end_date=end_date, status=pstatus))

    return periods


def load_ap_liability_account(conn: psycopg.Connection, name_to_id: dict[str, int]) -> tuple[Account, int]:
    """Load Accounts Payable liability account (standard account code).

    Args:
        conn: Database connection.
        name_to_id: Mapping of account names to database IDs.

    Returns:
        Tuple of (Account object, account_id).
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT name, account_type, subtype, tax_mapping FROM accounts WHERE code = %s",
            ("2100",),  # Standard AP account
        )
        row = cur.fetchone()
        if not row:
            raise APPostingError("Accounts Payable account (2100) not found in Chart of Accounts")

        name, acct_type, subtype, tax_mapping = row
        raw_type = acct_type.lower()
        atype = _DB_TYPE_MAP.get(raw_type)
        if atype is None:
            raise APPostingError("Accounts Payable account has unknown account_type")

        account = Account(
            name=name,
            type=atype,
            subtype=subtype,
            tax_mapping=tax_mapping,
            status=AccountStatus.ACTIVE,
        )
        acct_id = name_to_id.get(name)
        if acct_id is None:
            raise APPostingError(f"Accounts Payable account {name} not found in accounts cache")
        return account, acct_id


def post_bill(
    conn: psycopg.Connection,
    bill_number: str,
    vendor_id: int,
    bill_date: date,
    due_date: date,
    memo: str | None,
    period_end: date | None,
    bill_items: list[dict],
    fiscal_period_id: int,
    reference: str | None = None,
) -> dict:
    """Post a bill to the ledger with double-entry accounting.

    Creates journal entry:
      Dr. Expense Account(s)  (by category)
      Cr. Accounts Payable    (liability)

    Args:
        bill_number: Unique bill identifier
        vendor_id: Vendor reference
        bill_date: Invoice date from vendor
        due_date: Payment due date
        memo: Bill description
        period_end: Period for recurring expenses
        bill_items: List of {"expense_category_id": int, "description": str,
                            "quantity": float, "unit_price_cents": int,
                            "business_use_percent": float (0-100)}
        fiscal_period_id: Accounting period
        reference: Optional reference for tracing

    Returns:
        Dict with bill_id, bill_number, total_cents, posted_entry_id
    """
    # Validate vendor exists
    vendor = load_vendor(conn, vendor_id)
    if not vendor["is_active"]:
        raise APPostingError(f"Vendor {vendor_id} is inactive")

    # Load accounts catalog and AP liability account
    id_to_account, name_to_id, catalog = load_accounts_catalog(conn)
    ap_account, ap_account_id = load_ap_liability_account(conn, name_to_id)

    # Load fiscal periods
    periods = load_fiscal_periods(conn)

    # Calculate totals and build line mapping
    total_amount_cents = 0
    total_deductible_cents = 0
    line_data = []

    for item in bill_items:
        expense_account = load_expense_category(conn, item["expense_category_id"], id_to_account)

        qty = item.get("quantity", 1.0)
        unit_price = item["unit_price_cents"]
        business_use = item.get("business_use_percent", 100.0)

        # Calculate line amount
        amount_cents = int(qty * unit_price)
        deductible_cents = int(amount_cents * business_use / 100.0)

        total_amount_cents += amount_cents
        total_deductible_cents += deductible_cents

        line_data.append(
            {
                "expense_category_id": item["expense_category_id"],
                "expense_account": expense_account,
                "description": item["description"],
                "amount_cents": amount_cents,
                "deductible_cents": deductible_cents,
                "business_use_percent": business_use,
            }
        )

    try:
        with conn.cursor() as cur:
            # Insert bill record
            cur.execute(
                """
                INSERT INTO bills
                (bill_number, vendor_id, bill_date, due_date, period_end,
                 total_amount_cents, status, memo)
                VALUES (%s, %s, %s, %s, %s, %s, 'posted', %s)
                RETURNING id
                """,
                (
                    bill_number,
                    vendor_id,
                    bill_date,
                    due_date,
                    period_end,
                    total_amount_cents,
                    memo,
                ),
            )
            bill_id = cur.fetchone()[0]

            # Insert bill line items
            for line in line_data:
                cur.execute(
                    """
                    INSERT INTO bill_items
                    (bill_id, expense_category_id, description,
                     quantity, unit_price_cents, amount_cents,
                     business_use_percent, deductible_amount_cents)
                    VALUES (%s, %s, %s, 1, %s, %s, %s, %s)
                    """,
                    (
                        bill_id,
                        line["expense_category_id"],
                        line["description"],
                        line["amount_cents"],
                        line["amount_cents"],
                        line["business_use_percent"],
                        line["deductible_cents"],
                    ),
                )

            # Build journal entry sides: Dr. Expense / Cr. AP
            # Positive = debit, negative = credit
            sides = []

            # Add debit entries for each expense category (using FULL amount)
            # Deductible amount is tracked separately in bill_items for tax reporting
            for line in line_data:
                sides.append((line["expense_account"], line["amount_cents"]))

            # Add credit entry for AP liability (full amount)
            sides.append((ap_account, -total_amount_cents))

            # Create and post journal entry
            draft = new_draft(
                draft_id=str(uuid.uuid4()),
                entry_date=bill_date,
                description=reference or f"Bill {bill_number}",
                sides=sides,
            )

            posted_entry = post_draft(draft, periods, catalog)

            # Insert journal entry to database
            cur.execute(
                "INSERT INTO journal_entries (entry_date, description, fiscal_period_id) "
                "VALUES (%s, %s, %s) RETURNING id",
                (posted_entry.entry.date, posted_entry.entry.description, fiscal_period_id),
            )
            entry_id_result = cur.fetchone()[0]

            # Insert journal entry lines (converting Account to account_id via name lookup)
            for line in posted_entry.entry.lines:
                acct_id = name_to_id.get(line.account.name)
                if acct_id is None:
                    raise APPostingError(f"Account {line.account.name} not found in DB")
                cur.execute(
                    """
                    INSERT INTO journal_lines
                    (entry_id, account_id, amount_cents)
                    VALUES (%s, %s, %s)
                    """,
                    (entry_id_result, acct_id, line.amount_cents),
                )

            # Link bill to journal entry
            cur.execute(
                "UPDATE bills SET posted_entry_id = %s WHERE id = %s",
                (entry_id_result, bill_id),
            )

        conn.commit()

        return {
            "bill_id": bill_id,
            "bill_number": bill_number,
            "vendor_id": vendor_id,
            "total_amount_cents": total_amount_cents,
            "deductible_amount_cents": total_deductible_cents,
            "posted_entry_id": entry_id_result,
        }

    except APPostingError:
        raise
    except Exception as exc:
        conn.rollback()
        raise APPostingError(f"Failed to post bill: {exc}") from exc


def record_payment(
    conn: psycopg.Connection,
    bill_id: int,
    payment_date: date,
    amount_cents: int,
    payment_method: str,
    reference_number: str | None = None,
    memo: str | None = None,
    fiscal_period_id: int | None = None,
    bank_account_id: int | None = None,
) -> dict:
    """Record a payment against a bill.

    Creates journal entry:
      Dr. Accounts Payable (reduce liability)
      Cr. Bank / Cash Account

    Args:
        bill_id: Bill to pay
        payment_date: Date of payment
        amount_cents: Payment amount
        payment_method: "check", "ach", "credit_card", etc.
        reference_number: Check#, ACH ref, etc.
        memo: Optional notes
        fiscal_period_id: Accounting period (if not provided, uses bill's period)
        bank_account_id: Account to credit (if not provided, uses default bank)

    Returns:
        Dict with payment_id, bill_id, amount_cents, posted_entry_id
    """
    try:
        with conn.cursor() as cur:
            # Get bill details
            cur.execute(
                "SELECT id, bill_number, vendor_id, total_amount_cents, paid_amount_cents FROM bills WHERE id = %s",
                (bill_id,),
            )
            bill = cur.fetchone()
            if not bill:
                raise APPostingError(f"Bill {bill_id} not found")

            bill_id_result, bill_number, vendor_id, total_amount, current_paid = bill

            # Validate payment amount
            if amount_cents <= 0:
                raise InvalidPaymentError("Payment amount must be positive")

            new_paid = current_paid + amount_cents
            if new_paid > total_amount:
                # Allow overpayment but cap it
                new_paid = total_amount

            # Get vendor for reference
            vendor = load_vendor(conn, vendor_id)

            # Load accounts catalog and AP liability account
            id_to_account, name_to_id, catalog = load_accounts_catalog(conn)
            ap_account, ap_account_id = load_ap_liability_account(conn, name_to_id)

            # Load fiscal periods
            periods = load_fiscal_periods(conn)

            # If no bank account specified, use default checking (1010)
            if not bank_account_id:
                if not name_to_id:  # Should not happen, but check
                    raise APPostingError("No accounts loaded from database")
                # Find the checking account in the loaded catalog
                bank_account = None
                for acct in id_to_account.values():
                    if acct.name.startswith("1010"):
                        bank_account = acct
                        break
                if not bank_account:
                    raise APPostingError("Default bank account (1010) not found")
            else:
                bank_account = id_to_account.get(bank_account_id)
                if not bank_account:
                    raise APPostingError(f"Bank account {bank_account_id} not found")

            # Get fiscal period if not provided
            if not fiscal_period_id:
                cur.execute(
                    "SELECT id FROM fiscal_periods "
                    "WHERE %s BETWEEN start_date AND end_date",
                    (payment_date,),
                )
                period_row = cur.fetchone()
                if not period_row:
                    raise APPostingError(f"No fiscal period found for {payment_date}")
                fiscal_period_id = period_row[0]

            # Build journal entry sides: Dr. AP / Cr. Bank
            # Positive = debit, negative = credit
            sides = [
                (ap_account, amount_cents),  # Debit AP
                (bank_account, -amount_cents),  # Credit bank
            ]

            # Create and post journal entry
            draft = new_draft(
                draft_id=str(uuid.uuid4()),
                entry_date=payment_date,
                description=reference_number or f"Payment to {vendor['name']}",
                sides=sides,
            )

            posted_entry = post_draft(draft, periods, catalog)

            # Insert journal entry to database
            cur.execute(
                "INSERT INTO journal_entries (entry_date, description, fiscal_period_id) "
                "VALUES (%s, %s, %s) RETURNING id",
                (posted_entry.entry.date, posted_entry.entry.description, fiscal_period_id),
            )
            posted_entry_id = cur.fetchone()[0]

            # Insert journal entry lines (converting Account to account_id via name lookup)
            for line in posted_entry.entry.lines:
                acct_id = name_to_id.get(line.account.name)
                if acct_id is None:
                    raise APPostingError(f"Account {line.account.name} not found in DB")
                cur.execute(
                    """
                    INSERT INTO journal_lines
                    (entry_id, account_id, amount_cents)
                    VALUES (%s, %s, %s)
                    """,
                    (posted_entry_id, acct_id, line.amount_cents),
                )

            # Record payment
            cur.execute(
                """
                INSERT INTO bill_payments
                (bill_id, payment_date, amount_cents, payment_method,
                 reference_number, posted_entry_id, memo)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    bill_id,
                    payment_date,
                    amount_cents,
                    payment_method,
                    reference_number,
                    posted_entry_id,
                    memo,
                ),
            )
            payment_id = cur.fetchone()[0]

            # Update bill paid amount and status
            new_status = "paid" if new_paid >= total_amount else "posted"
            cur.execute(
                "UPDATE bills SET paid_amount_cents = %s, status = %s WHERE id = %s",
                (new_paid, new_status, bill_id),
            )

        conn.commit()

        return {
            "payment_id": payment_id,
            "bill_id": bill_id,
            "amount_cents": amount_cents,
            "new_paid_total": new_paid,
            "outstanding_cents": total_amount - new_paid,
            "posted_entry_id": posted_entry_id,
        }

    except APPostingError:
        raise
    except Exception as exc:
        conn.rollback()
        raise APPostingError(f"Failed to record payment: {exc}") from exc
