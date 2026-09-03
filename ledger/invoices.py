"""Invoice domain service for Sovereign Ledger AR.

Invoices post immediately upon creation (not on send): Dr AR / Cr Income in one
balanced entry. This is the critical AR flow per CK-5.

Every invoice carries line items, each tied to an income account for tax mapping.
The pure domain constructs the balanced entry; persistence is the caller's job
(entry posting, invoice + line insertion, status update, all in one xn).

Locked decisions honored:
  - HR-1: entries must balance (sum of lines = total_amount)
  - CK-5: invoice posts immediately as Dr AR / Cr Income
  - D-3: money is signed integer USD cents
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Literal

from ledger.engine import PostedEntry, post
from ledger.types import AccountRef, JournalEntry, JournalLine, Money

__all__ = [
    "Invoice",
    "InvoiceLine",
    "InvoiceDraft",
    "InvoiceStatus",
    "new_invoice_draft",
    "add_line_to_draft",
    "invoice_journal_entry",
    "DraftInvoiceError",
]


InvoiceStatus = Literal["draft", "posted", "paid", "void"]


@dataclass(frozen=True, slots=True)
class InvoiceLine:
    """A single line item on an invoice.

    Attributes:
        id: Unique line identifier (None for drafts).
        invoice_id: Parent invoice id (None for drafts).
        account_id: Income account for this line (tied to P&L).
        description: Human-readable description (e.g., "Monthly service").
        quantity: Number of units (must be > 0).
        unit_price_cents: Price per unit in signed cents (must be >= 0).
        amount_cents: quantity * unit_price_cents (cached, must match).
    """

    id: int | None
    invoice_id: int | None
    account_id: int
    description: str
    quantity: int
    unit_price_cents: int
    amount_cents: int


@dataclass(frozen=True, slots=True)
class Invoice:
    """A posted invoice record.

    Attributes:
        id: Unique invoice identifier (from DB sequence, never None).
        invoice_number: Gapless invoice number (e.g., 1001).
        customer_id: Which customer owns this invoice.
        issue_date: When the invoice was sent.
        due_date: When payment is due.
        memo: Customer-facing description.
        total_amount_cents: Sum of all line amounts (must equal SUM(lines)).
        status: Lifecycle (draft → posted → paid/void).
        posted_entry_id: The journal entry ID (None until posted).
        lines: Sequence of InvoiceLine objects.
        created_at: Timestamp from DB.
    """

    id: int | None
    invoice_number: int | None
    customer_id: int
    issue_date: date
    due_date: date
    memo: str | None
    total_amount_cents: int
    status: InvoiceStatus
    posted_entry_id: int | None
    lines: tuple[InvoiceLine, ...] = ()
    created_at: date | None = None


@dataclass(frozen=True, slots=True)
class InvoiceDraft:
    """A reviewable invoice draft (not yet posted).

    Drafts accumulate line items and are validated before posting.
    Draft lines are unbalanced (being accumulated) and become balanced
    only once all lines are added and the total is reached.

    Attributes:
        customer_id: Which customer this invoice is for.
        issue_date: When the invoice is/will be dated.
        due_date: When payment is due.
        memo: Customer-facing description (optional).
        lines: Accumulated line items (may be unbalanced mid-draft).
        total_amount_cents: The expected total (for validation at post time).
    """

    customer_id: int
    issue_date: date
    due_date: date
    memo: str | None
    lines: list[InvoiceLine] = field(default_factory=list)
    total_amount_cents: int = 0


class DraftInvoiceError(ValueError):
    """A draft invoice failed validation before posting."""


def new_invoice_draft(
    customer_id: int,
    issue_date: date,
    due_date: date,
    memo: str | None = None,
) -> InvoiceDraft:
    """Start a new invoice draft.

    Args:
        customer_id: The customer being invoiced.
        issue_date: Invoice date.
        due_date: Due date (must be >= issue_date).
        memo: Optional description for the customer.

    Returns:
        An empty InvoiceDraft ready for line items.

    Raises:
        DraftInvoiceError: If due_date < issue_date.
    """
    if due_date < issue_date:
        raise DraftInvoiceError("Due date must be >= issue date.")

    return InvoiceDraft(
        customer_id=customer_id,
        issue_date=issue_date,
        due_date=due_date,
        memo=memo,
        lines=[],
        total_amount_cents=0,
    )


def add_line_to_draft(
    draft: InvoiceDraft,
    account_id: int,
    description: str,
    quantity: int,
    unit_price_cents: int,
) -> InvoiceDraft:
    """Add a line item to an invoice draft.

    Args:
        draft: The invoice draft to add to.
        account_id: Income account for this line.
        description: What is being billed.
        quantity: Number of units (must be > 0).
        unit_price_cents: Price per unit in cents (must be >= 0).

    Returns:
        A new InvoiceDraft with the line added and total updated.

    Raises:
        DraftInvoiceError: If quantity <= 0 or unit_price_cents < 0.
    """
    if quantity <= 0:
        raise DraftInvoiceError("Quantity must be > 0.")
    if unit_price_cents < 0:
        raise DraftInvoiceError("Unit price must be >= 0.")

    amount_cents = quantity * unit_price_cents
    line = InvoiceLine(
        id=None,
        invoice_id=None,
        account_id=account_id,
        description=description.strip(),
        quantity=quantity,
        unit_price_cents=unit_price_cents,
        amount_cents=amount_cents,
    )

    new_lines = draft.lines + [line]
    new_total = sum(l.amount_cents for l in new_lines)

    return InvoiceDraft(
        customer_id=draft.customer_id,
        issue_date=draft.issue_date,
        due_date=draft.due_date,
        memo=draft.memo,
        lines=new_lines,
        total_amount_cents=new_total,
    )


def invoice_journal_entry(
    draft: InvoiceDraft,
    ar_account_ref: AccountRef,
    income_account_refs: dict[int, AccountRef],
    entry_id: str,
) -> tuple[JournalEntry, int]:
    """Construct the balanced journal entry for an invoice.

    CK-5: Invoice posts immediately as Dr AR / Cr Income.
    The entry has (num_lines + 1) journal lines:
      - One debit on the AR account for total_amount_cents
      - One credit on each line's income account for its amount

    This entry is balanced by construction and ready for posting.

    Args:
        draft: The invoice draft (must have lines).
        ar_account_ref: The AR account AccountRef to debit.
        income_account_refs: Mapping of account_id → AccountRef for line items.
        entry_id: Unique identifier for this entry.

    Returns:
        A tuple (JournalEntry, total_amount_cents):
          - entry: Balanced JournalEntry ready to post.
          - total_amount_cents: The invoice total (for the invoice record).

    Raises:
        DraftInvoiceError: If draft has no lines, total is 0, or account references missing.
    """
    if not draft.lines:
        raise DraftInvoiceError("Invoice must have at least one line item.")
    if draft.total_amount_cents <= 0:
        raise DraftInvoiceError("Invoice total must be > 0.")

    # Construct lines: Dr AR / Cr each line's income account
    lines: list[JournalLine] = []

    # Debit AR account for total
    lines.append(
        JournalLine.debit(ar_account_ref, draft.total_amount_cents)
    )

    # Credit each line's income account
    for line in draft.lines:
        if line.account_id not in income_account_refs:
            raise DraftInvoiceError(
                f"Account reference not found for account {line.account_id}"
            )
        account_ref = income_account_refs[line.account_id]
        lines.append(
            JournalLine.credit(account_ref, line.amount_cents)
        )

    entry = JournalEntry(
        entry_id=entry_id,
        date=draft.issue_date,
        description=f"Invoice - Customer {draft.customer_id}",
        lines=tuple(lines),
    )

    return entry, draft.total_amount_cents


def mark_paid(
    invoice: Invoice,
) -> Invoice:
    """Transition an invoice to Paid status.

    Args:
        invoice: The invoice to mark paid.

    Returns:
        A new Invoice with status='paid'.
    """
    return Invoice(
        id=invoice.id,
        invoice_number=invoice.invoice_number,
        customer_id=invoice.customer_id,
        issue_date=invoice.issue_date,
        due_date=invoice.due_date,
        memo=invoice.memo,
        total_amount_cents=invoice.total_amount_cents,
        status="paid",
        posted_entry_id=invoice.posted_entry_id,
        lines=invoice.lines,
        created_at=invoice.created_at,
    )


def mark_void(
    invoice: Invoice,
) -> Invoice:
    """Transition an invoice to Void status.

    Void invoices are historical records; they are never deleted.

    Args:
        invoice: The invoice to mark void.

    Returns:
        A new Invoice with status='void'.
    """
    return Invoice(
        id=invoice.id,
        invoice_number=invoice.invoice_number,
        customer_id=invoice.customer_id,
        issue_date=invoice.issue_date,
        due_date=invoice.due_date,
        memo=invoice.memo,
        total_amount_cents=invoice.total_amount_cents,
        status="void",
        posted_entry_id=invoice.posted_entry_id,
        lines=invoice.lines,
        created_at=invoice.created_at,
    )
