"""AR posting adapters: bridge domain services to persistence (Step 9).

Responsibilities:
  - Load AccountRef objects from DB chart of accounts
  - Validate fiscal period is open (CK-5)
  - Validate customer is active (CK-6)
  - Execute gapless invoice numbering (D-10: lock counter row)
  - Serialize payment allocation with retry on SQLSTATE 40001 (D-7)
  - Persist journal entries, invoices, payments atomically

This module is NOT pure (it does database I/O), but it keeps domain logic
separate. All validation pre-calls go through here before reaching domain.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import TYPE_CHECKING

from ledger.customers import Customer
from ledger.invoices import InvoiceDraft, invoice_journal_entry
from ledger.payments import Payment, allocate_payment, payment_journal_entry
from ledger.recurring import RecurringTemplate, generate_invoice_for_cycle
from ledger.types import AccountRef, AccountType

if TYPE_CHECKING:
    import psycopg


class ARPostingError(Exception):
    """AR posting operation failed."""


class FiscalPeriodClosedError(ARPostingError):
    """Cannot post to a closed or locked fiscal period."""


class CustomerInactiveError(ARPostingError):
    """Customer is not active (cannot invoice)."""


class AccountNotFoundError(ARPostingError):
    """Account reference not found in chart of accounts."""


def load_account_refs(conn: psycopg.Connection, account_ids: list[int]) -> dict[int, AccountRef]:
    """Load AccountRef objects for given account IDs from chart of accounts.

    Args:
        conn: Database connection.
        account_ids: List of account IDs to load.

    Returns:
        Mapping of account_id → AccountRef.

    Raises:
        AccountNotFoundError: If any account ID not found.
    """
    if not account_ids:
        return {}

    placeholders = ",".join(["%s"] * len(account_ids))
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT id, name, account_type FROM accounts WHERE id IN ({placeholders})",
            account_ids,
        )
        rows = cur.fetchall()

    # Map DB account_type to AccountType enum
    type_map = {
        "Assets": AccountType.ASSET,
        "Liabilities": AccountType.LIABILITY,
        "Equity": AccountType.EQUITY,
        "Income": AccountType.INCOME,
        "Expenses": AccountType.EXPENSE,
    }

    refs = {}
    for account_id, name, db_type in rows:
        if db_type not in type_map:
            raise AccountNotFoundError(f"Unknown account type {db_type!r}")
        refs[account_id] = AccountRef(
            code=str(account_id),  # Use ID as code for now
            name=name,
            type=type_map[db_type],
        )

    # Verify all requested IDs were found
    missing = set(account_ids) - set(refs.keys())
    if missing:
        raise AccountNotFoundError(f"Accounts not found: {missing}")

    return refs


def validate_fiscal_period_open(
    conn: psycopg.Connection,
    fiscal_period_id: int,
) -> None:
    """Validate that fiscal period is open (CK-5).

    Args:
        conn: Database connection.
        fiscal_period_id: Period ID to check.

    Raises:
        FiscalPeriodClosedError: If period is closed or locked.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT status FROM fiscal_periods WHERE id = %s",
            (fiscal_period_id,),
        )
        row = cur.fetchone()

    if not row:
        raise FiscalPeriodClosedError(f"Fiscal period {fiscal_period_id} not found")

    status = row[0]
    if status != "open":
        raise FiscalPeriodClosedError(
            f"Fiscal period {fiscal_period_id} is {status!r}, cannot post"
        )


def validate_customer_active(
    conn: psycopg.Connection,
    customer_id: int,
) -> Customer:
    """Load customer and verify it's active (CK-6).

    Args:
        conn: Database connection.
        customer_id: Customer ID to check.

    Returns:
        Customer object.

    Raises:
        CustomerInactiveError: If customer is not active.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, name, tax_id, email, address, notes, status, created_at "
            "FROM customers WHERE id = %s",
            (customer_id,),
        )
        row = cur.fetchone()

    if not row:
        raise CustomerInactiveError(f"Customer {customer_id} not found")

    customer = Customer(
        id=row[0],
        name=row[1],
        tax_id=row[2],
        email=row[3],
        address=row[4],
        notes=row[5],
        status=row[6],
        created_at=row[7],
    )

    if customer.status != "active":
        raise CustomerInactiveError(
            f"Customer {customer_id} is {customer.status!r}, cannot invoice"
        )

    return customer


def post_invoice(
    conn: psycopg.Connection,
    draft: InvoiceDraft,
    ar_account_id: int,
    fiscal_period_id: int,
) -> int:
    """Post an invoice draft to the ledger (CK-5).

    Creates balanced journal entry (Dr AR / Cr Income), assigns gapless invoice
    number (D-10), and inserts all records in one transaction.

    Args:
        conn: Database connection.
        draft: Invoice draft ready to post.
        ar_account_id: AR asset account ID.
        fiscal_period_id: Open fiscal period ID.

    Returns:
        Newly posted invoice ID.

    Raises:
        FiscalPeriodClosedError: If period is not open.
        CustomerInactiveError: If customer is not active.
        AccountNotFoundError: If account IDs not found.
        ARPostingError: If posting fails.
    """
    # Validate preconditions
    validate_fiscal_period_open(conn, fiscal_period_id)
    validate_customer_active(conn, draft.customer_id)

    # Collect all income account IDs from line items
    line_account_ids = [line.account_id for line in draft.lines]
    all_account_ids = [ar_account_id] + line_account_ids

    # Load all account references
    account_refs = load_account_refs(conn, all_account_ids)
    ar_account_ref = account_refs[ar_account_id]
    income_refs = {line.account_id: account_refs[line.account_id] for line in draft.lines}

    # Generate entry ID (deterministic based on customer + date)
    entry_id = f"inv-{draft.customer_id}-{draft.issue_date.isoformat()}-{uuid.uuid4().hex[:8]}"

    # Construct balanced journal entry
    entry, total_amount_cents = invoice_journal_entry(
        draft,
        ar_account_ref=ar_account_ref,
        income_account_refs=income_refs,
        entry_id=entry_id,
    )

    # Post in transaction: get gapless number, insert all records
    try:
        with conn.transaction():
            # D-10: Lock counter row, get next invoice number
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT next_number FROM invoice_number_counter FOR UPDATE"
                )
                row = cur.fetchone()
                if not row:
                    # Initialize counter if missing
                    cur.execute(
                        "INSERT INTO invoice_number_counter (next_number) VALUES (1001) "
                        "ON CONFLICT DO NOTHING"
                    )
                    cur.execute(
                        "SELECT next_number FROM invoice_number_counter FOR UPDATE"
                    )
                    row = cur.fetchone()

                invoice_number = row[0]

            # Insert journal entry + lines
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO journal_entries (id, entry_date, description, fiscal_period_id) "
                    "VALUES (%s, %s, %s, %s) RETURNING id",
                    (entry.entry_id, entry.date, entry.description, fiscal_period_id),
                )
                posted_entry_id = cur.fetchone()[0]

                # Insert journal lines
                for line in entry.lines:
                    cur.execute(
                        "INSERT INTO journal_lines (journal_entry_id, account_id, amount_cents) "
                        "VALUES (%s, %s, %s)",
                        (posted_entry_id, int(line.account.code), line.amount_cents),
                    )

            # Insert invoice
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO invoices "
                    "(customer_id, invoice_number, issue_date, due_date, memo, "
                    "total_amount_cents, status, posted_entry_id) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
                    (
                        draft.customer_id,
                        invoice_number,
                        draft.issue_date,
                        draft.due_date,
                        draft.memo,
                        total_amount_cents,
                        "posted",
                        posted_entry_id,
                    ),
                )
                invoice_id = cur.fetchone()[0]

                # Insert invoice lines
                for line in draft.lines:
                    cur.execute(
                        "INSERT INTO invoice_lines "
                        "(invoice_id, account_id, description, quantity, unit_price_cents, amount_cents) "
                        "VALUES (%s, %s, %s, %s, %s, %s)",
                        (
                            invoice_id,
                            line.account_id,
                            line.description,
                            line.quantity,
                            line.unit_price_cents,
                            line.amount_cents,
                        ),
                    )

                # Increment counter
                cur.execute(
                    "UPDATE invoice_number_counter SET next_number = next_number + 1"
                )

        conn.commit()
        return invoice_id
    except Exception as exc:
        conn.rollback()
        raise ARPostingError(f"Failed to post invoice: {exc}") from exc


def post_payment(
    conn: psycopg.Connection,
    payment: Payment,
    bank_account_id: int,
    ar_account_id: int,
    customer_credits_account_id: int,
    fiscal_period_id: int,
    retries: int = 3,
) -> int:
    """Post a payment with serializable allocation retry (D-7).

    Allocates payment across invoices, creates journal entry, and records
    payment allocation in one atomic transaction. Retries on SQLSTATE 40001
    (serialization failure) up to `retries` times.

    Args:
        conn: Database connection.
        payment: Payment with pre-calculated allocations and overpayment.
        bank_account_id: Bank account ID.
        ar_account_id: AR asset account ID.
        customer_credits_account_id: Customer credits liability account ID.
        fiscal_period_id: Open fiscal period ID.
        retries: Max retry attempts on serialization failure.

    Returns:
        Newly posted payment ID.

    Raises:
        FiscalPeriodClosedError: If period is not open.
        AccountNotFoundError: If account IDs not found.
        ARPostingError: If posting fails after retries.
    """
    validate_fiscal_period_open(conn, fiscal_period_id)

    # Load account references
    account_ids = [bank_account_id, ar_account_id, customer_credits_account_id]
    account_refs = load_account_refs(conn, account_ids)

    for attempt in range(retries):
        try:
            with conn.transaction(isolation="serializable"):
                # Generate entry ID
                entry_id = f"pmt-{payment.customer_id}-{payment.payment_date.isoformat()}-{uuid.uuid4().hex[:8]}"

                # Construct journal entry
                entry = payment_journal_entry(
                    payment,
                    bank_account_ref=account_refs[bank_account_id],
                    ar_account_ref=account_refs[ar_account_id],
                    customer_credits_account_ref=account_refs[customer_credits_account_id],
                    entry_id=entry_id,
                )

                # Insert journal entry + lines
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO journal_entries (id, entry_date, description, fiscal_period_id) "
                        "VALUES (%s, %s, %s, %s) RETURNING id",
                        (entry.entry_id, entry.date, entry.description, fiscal_period_id),
                    )
                    posted_entry_id = cur.fetchone()[0]

                    for line in entry.lines:
                        cur.execute(
                            "INSERT INTO journal_lines (journal_entry_id, account_id, amount_cents) "
                            "VALUES (%s, %s, %s)",
                            (posted_entry_id, int(line.account.code), line.amount_cents),
                        )

                # Insert payment
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO payments "
                        "(customer_id, payment_date, amount_cents, memo, bank_line_id, "
                        "overpayment_cents, posted_entry_id) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
                        (
                            payment.customer_id,
                            payment.payment_date,
                            payment.amount_cents,
                            payment.memo,
                            payment.bank_line_id,
                            payment.overpayment_cents,
                            posted_entry_id,
                        ),
                    )
                    payment_id = cur.fetchone()[0]

                    # Insert allocations
                    for alloc in payment.allocations:
                        cur.execute(
                            "INSERT INTO payment_allocations (payment_id, invoice_id, amount_cents) "
                            "VALUES (%s, %s, %s)",
                            (payment_id, alloc.invoice_id, alloc.amount_cents),
                        )

                        # Mark invoice paid
                        cur.execute(
                            "UPDATE invoices SET status = %s WHERE id = %s",
                            ("paid", alloc.invoice_id),
                        )

                    # Create customer_credits record if overpayment
                    if payment.overpayment_cents > 0:
                        cur.execute(
                            "INSERT INTO customer_credits (customer_id, amount_cents, created_at) "
                            "VALUES (%s, %s, CURRENT_DATE)",
                            (payment.customer_id, payment.overpayment_cents),
                        )

            conn.commit()
            return payment_id

        except Exception as exc:
            conn.rollback()
            # Check if serialization failure — if so, retry
            if hasattr(exc, "sqlstate") and exc.sqlstate == "40001":
                if attempt < retries - 1:
                    continue
            raise ARPostingError(f"Failed to post payment (attempt {attempt + 1}/{retries}): {exc}") from exc

    raise ARPostingError(f"Payment posting failed after {retries} retries")


def generate_and_post_recurring(
    conn: psycopg.Connection,
    template_id: int,
    cycle_date: date,
) -> tuple[int | None, str | None]:
    """Generate and post invoice for a recurring template cycle.

    Calls domain layer `generate_invoice_for_cycle()`, posts via `post_invoice()`,
    and records result in `recurring_generations` table.

    Args:
        conn: Database connection.
        template_id: Recurring template ID.
        cycle_date: Generation cycle date (e.g., 2026-09-01).

    Returns:
        Tuple (invoice_id, error_message):
          - (invoice_id, None) on success
          - (None, error_message) on failure
    """
    try:
        # Load template
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, customer_id, name, description, amount_cents, due_days_offset, "
                "status, active_from, active_until, line_account_id, created_at "
                "FROM recurring_templates WHERE id = %s",
                (template_id,),
            )
            row = cur.fetchone()

        if not row:
            return None, f"Template {template_id} not found"

        template = RecurringTemplate(
            id=row[0],
            customer_id=row[1],
            name=row[2],
            description=row[3],
            amount_cents=row[4],
            due_days_offset=row[5],
            status=row[6],
            active_from=row[7],
            active_until=row[8],
            line_account_id=row[9],
            created_at=row[10],
        )

        # Generate invoice draft
        result = generate_invoice_for_cycle(template, cycle_date)
        if result.error:
            return None, result.error

        invoice_draft = result.invoice_draft

        # Get AR account and fiscal period (hardcoded for now - can be config)
        # TODO: Make configurable
        ar_account_id = 1  # Placeholder
        fiscal_period_id = 1  # Placeholder

        # Post invoice
        invoice_id = post_invoice(conn, invoice_draft, ar_account_id, fiscal_period_id)

        # Record success in recurring_generations
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO recurring_generations (template_id, cycle_date, invoice_id, success, error_message) "
                "VALUES (%s, %s, %s, %s, %s)",
                (template_id, cycle_date, invoice_id, True, None),
            )
        conn.commit()

        return invoice_id, None

    except Exception as exc:
        conn.rollback()
        error_msg = f"{type(exc).__name__}: {exc}"

        # Record failure
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO recurring_generations (template_id, cycle_date, success, error_message) "
                    "VALUES (%s, %s, %s, %s)",
                    (template_id, cycle_date, False, error_msg),
                )
            conn.commit()
        except Exception:
            pass  # Best effort

        return None, error_msg
