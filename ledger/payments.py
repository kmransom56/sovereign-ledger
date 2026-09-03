"""Payment domain service for Sovereign Ledger AR.

Payment allocation across invoices with all-or-nothing semantics (D-7).
Overpayments create customer credits (liability) per HR-8, never income.

Key flows:
  - Allocate a payment across open invoices (CK-7).
  - If payment exceeds total due: allocate to invoices, residual → customer_credits.
  - Construct the balanced posting: Dr Bank / Cr AR (and Cr customer_credits liability if overpayment).

This service is pure: it does not touch the DB. The API layer handles serializable
transactions (D-7 retry wrapper); the domain layer ensures the allocation is
all-or-nothing by construction and atomicity (any partial state is invalid).

Locked decisions honored:
  - HR-1: entries must balance.
  - HR-8: overpayment → customer_credits (liability), never income.
  - CK-7: all-or-nothing allocation in serializable transaction.
  - D-3: money is signed integer USD cents.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import NamedTuple

from ledger.types import AccountRef, JournalEntry, JournalLine

__all__ = [
    "PaymentAllocation",
    "Payment",
    "allocate_payment",
    "payment_journal_entry",
    "PaymentError",
]


class PaymentError(ValueError):
    """Base error for payment domain operations."""


class InsufficientFundsError(PaymentError):
    """Allocation failed: not enough payment to cover allocations."""


class InvalidAllocationError(PaymentError):
    """Allocation data failed validation."""


class PaymentAllocationLine(NamedTuple):
    """One line in a payment allocation: invoice_id → amount applied."""

    invoice_id: int
    amount_cents: int


@dataclass(frozen=True, slots=True)
class Payment:
    """A payment record (money received from a customer).

    Attributes:
        id: Unique payment identifier (None for drafts).
        customer_id: Which customer made this payment.
        payment_date: When the payment was received.
        amount_cents: Total payment amount.
        memo: Payment memo (e.g., "Check #1234").
        bank_line_id: Optional reference to the bank line that triggered this.
        allocations: Sequence of (invoice_id, amount_cents) allocations.
        overpayment_cents: Any residual after invoices are paid (→ customer_credits).
        posted_entry_id: Journal entry ID (None until posted).
    """

    id: int | None
    customer_id: int
    payment_date: date
    amount_cents: int
    memo: str | None
    bank_line_id: int | None
    allocations: tuple[PaymentAllocationLine, ...] = ()
    overpayment_cents: int = 0
    posted_entry_id: int | None = None


def allocate_payment(
    payment_amount_cents: int,
    invoices: list[tuple[int, int]],  # (invoice_id, amount_due_cents)
) -> tuple[list[PaymentAllocationLine], int]:
    """Allocate a payment across invoices in order.

    Invoices are processed in order: if payment exceeds the first invoice's due
    amount, the residual is applied to the next, etc. If payment exceeds total
    due on all invoices, the residual is an overpayment (→ customer_credits).

    Args:
        payment_amount_cents: Total payment to allocate.
        invoices: List of (invoice_id, amount_due_cents) tuples, in order.

    Returns:
        A tuple (allocations, overpayment_cents):
          - allocations: List of (invoice_id, amount_applied_cents).
          - overpayment_cents: Any residual (0 if exact).

    Raises:
        InvalidAllocationError: If payment <= 0 or any invoice due < 0.
    """
    if payment_amount_cents <= 0:
        raise InvalidAllocationError("Payment amount must be > 0.")
    if any(due < 0 for _, due in invoices):
        raise InvalidAllocationError("Invoice due amount must be >= 0.")

    allocations: list[PaymentAllocationLine] = []
    remaining = payment_amount_cents

    for invoice_id, amount_due in invoices:
        if remaining <= 0:
            break
        if amount_due <= 0:
            continue  # Skip invoices with nothing due

        # Allocate min(remaining, amount_due) to this invoice
        allocated = min(remaining, amount_due)
        allocations.append(PaymentAllocationLine(invoice_id, allocated))
        remaining -= allocated

    overpayment = remaining

    return allocations, overpayment


def payment_journal_entry(
    payment: Payment,
    bank_account_ref: AccountRef,
    ar_account_ref: AccountRef,
    customer_credits_account_ref: AccountRef | None,
    entry_id: str,
) -> JournalEntry:
    """Construct the balanced journal entry for a payment.

    The entry posts: Dr Bank / Cr AR (and Cr customer_credits liability if overpayment).

    Entry structure:
      - Debit bank_account for payment_amount_cents
      - Credit AR account for payment_amount_cents
      - If overpayment > 0: Credit customer_credits liability for overpayment_cents
        (AR credit is reduced by overpayment; the residual overpayment is a liability)

    Balanced by construction.

    Args:
        payment: The payment with allocations and overpayment calculated.
        bank_account_ref: The bank account AccountRef to debit.
        ar_account_ref: The AR account AccountRef to credit.
        customer_credits_account_ref: The customer_credits liability AccountRef (required if overpayment > 0).
        entry_id: Unique identifier for this entry.

    Returns:
        A balanced JournalEntry ready to post.

    Raises:
        PaymentError: If overpayment > 0 but customer_credits_account_ref is None.
    """
    if payment.overpayment_cents > 0 and customer_credits_account_ref is None:
        raise PaymentError(
            "Overpayment detected but customer_credits_account_ref not provided."
        )

    lines: list[JournalLine] = []

    # Debit bank account for full payment
    lines.append(
        JournalLine.debit(bank_account_ref, payment.amount_cents)
    )

    # Credit AR for the allocated amount (payment - overpayment)
    ar_credit = payment.amount_cents - payment.overpayment_cents
    if ar_credit > 0:
        lines.append(
            JournalLine.credit(ar_account_ref, ar_credit)
        )

    # If overpayment, credit customer_credits liability
    if payment.overpayment_cents > 0:
        lines.append(
            JournalLine.credit(customer_credits_account_ref, payment.overpayment_cents)
        )

    entry = JournalEntry(
        entry_id=entry_id,
        date=payment.payment_date,
        description=f"Payment from Customer {payment.customer_id}",
        lines=tuple(lines),
    )

    return entry
