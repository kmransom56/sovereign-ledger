"""AR Invoice domain logic (Step 8, CK-17).

Pure functions that build and validate AR invoices.

An ``Invoice`` is an immutable value object with these fields:
* ``invoice_id``: unique UUID string.
* ``customer_name``: non-empty string.
* ``due_date``: Date.
* ``amount_cents``: signed int.
* ``status``: ``InvoiceStatus`` (D-17).
* ``created_at``: ``datetime`` of creation (auto-populated).
"""

# Standard library imports
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Optional

from ledger.types import AccountType, Money


class InvoiceStatus(Enum):
    """Invoice lifecycle status.

    D-17:
      * ``DRAFT`` — created but not yet issued to customer (default)
      * ``ISSUED`` — sent to customer, awaiting payment
      * ``PAID`` — payment received
      * ``OVERDUE`` — past due date (but still possible to pay)
      * ``CANCELLED`` — no longer valid

    The enum is ordered by lifecycle, with ``DRAFT`` the earliest.
    """
    DRAFT = "draft"
    ISSUED = "issued"
    PAID = "paid"
    OVERDUE = "overdue"
    CANCELLED = "cancelled"

    def __lt__(self, other: InvoiceStatus) -> bool:
        if not isinstance(other, InvoiceStatus):
            raise TypeError(f"can only compare InvoiceStatus to InvoiceStatus, got {type(other)}")
        # D-17: Lifecycle status order, earliest first
        ORDER = [InvoiceStatus.DRAFT, InvoiceStatus.ISSUED, InvoiceStatus.PAID,
                InvoiceStatus.OVERDUE, InvoiceStatus.CANCELLED]
        try:
            return ORDER.index(self) < ORDER.index(other)
        except ValueError as e:
            raise ValueError(f"unknown InvoiceStatus: {self}") from e


class InvalidInvoiceError(ValueError):
    """Raised when an invoice does not conform to business rules (CK-17)."""
    pass


@dataclass(frozen=True, slots=True)
class Invoice:
    """Immutable value object for AR entries.

    CK-17: Fields must be validated.
    """
    invoice_id: str
    customer_name: str
    due_date: date
    amount_cents: Money
    status: InvoiceStatus = InvoiceStatus.DRAFT
    created_at: datetime = field(default_factory=datetime.now)

    def __post_init__(self) -> None:
        if not self.invoice_id:
            raise InvalidInvoiceError("invoice_id must be non-empty")
        if not self.customer_name:
            raise InvalidInvoiceError("customer_name must be non-empty")
        # The due date is checked at creation but can change via status transitions.
        if self.due_date is None:
            raise InvalidInvoiceError("due_date must be set")
        # Must have at least one cent (D-27).
        if abs(self.amount_cents) == 0:
            raise InvalidInvoiceError("amount_cents must be non-zero")


# Placeholder for future AR line item details
# class InvoiceItem:
#     """Line item within an invoice."""
#     description: str
#     quantity: int
#     unit_price_cents: Money

#     def __post_init__(self):
#         if self.quantity <= 0:
#             raise InvalidInvoiceError("quantity must be positive")


def validate_invoice(invoice: Invoice) -> None:
    """Validate the invoice's integrity and business rules.

    CK-17, D-27: Must be non-zero.
    """
    if not isinstance(invoice, Invoice):
        raise TypeError("validate_invoice() expects an Invoice")
    # Already checked in __post_init__, but explicitly validate again at the API boundary.
    _ = Invoice(  # Rebuild to trigger __post_init__
        invoice_id=invoice.invoice_id,
        customer_name=invoice.customer_name,
        due_date=invoice.due_date,
        amount_cents=invoice.amount_cents,
        status=invoice.status
    )


def is_overdue(invoice: Invoice) -> bool:
    """Check if an invoice is past its due date (D-28)."""
    return invoice.due_date < date.today()


def update_invoice_status(invoice: Invoice, new_status: InvoiceStatus) -> Invoice:
    """Update invoice status with business rule validation (CK-17).

    Raises InvalidInvoiceError if transition is invalid.
    """
    # D-17: Status transition validation
    # DRAFT → ISSUED → {PAID,OVERDUE,CANCELLED}
    # PAID → {PAID,OVERDUE} — can become overdue after payment
    # OVERDUE → {OVERDUE,PAID} — can become paid even when overdue
    ALLOWED_TRANSITIONS = {
        InvoiceStatus.DRAFT: [InvoiceStatus.ISSUED],
        InvoiceStatus.ISSUED: [InvoiceStatus.PAID, InvoiceStatus.OVERDUE, InvoiceStatus.CANCELLED],
        InvoiceStatus.PAID: [InvoiceStatus.PAID, InvoiceStatus.OVERDUE],
        InvoiceStatus.OVERDUE: [InvoiceStatus.PAID, InvoiceStatus.OVERDUE],  # Overdue invoices can be paid.
        InvoiceStatus.CANCELLED: [],  # Final state
    }

    if new_status not in ALLOWED_TRANSITIONS.get(invoice.status, []):
        allowed = ALLOWED_TRANSITIONS.get(invoice.status, [])
        raise InvalidInvoiceError(
            f"invalid status transition from {invoice.status.value} to {new_status.value}: "
            f"allowed transitions are {allowed}"
        )

    return Invoice(
        invoice_id=invoice.invoice_id,
        customer_name=invoice.customer_name,
        due_date=invoice.due_date,
        amount_cents=invoice.amount_cents,
        status=new_status
    )