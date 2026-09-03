"""AR Invoice domain logic unit tests (pure, no DB).

Tests:
* :func:`Invoice.__post_init__` — validation of fields.
* :func:`is_overdue` — checks past due date.
* :func:`update_invoice_status` — rules for status transitions.

CK-17: Business logic is encapsulated in pure functions.
"""

import pytest
from datetime import date, timedelta

from ledger.ar_invoice import (
    Invoice,
    InvoiceStatus,
    InvalidInvoiceError,
    is_overdue,
    update_invoice_status
)


def test_invoice_creation_validation() -> None:
    """CK-17: Fields must be valid."""
    # Valid invoice
    inv = Invoice(
        invoice_id="abc123",
        customer_name="Acme Corp",
        due_date=date(2026, 9, 15),
        amount_cents=42_00,
    )
    assert inv.invoice_id == "abc123"
    assert inv.customer_name == "Acme Corp"
    assert inv.due_date == date(2026, 9, 15)
    assert inv.amount_cents == 42_00

    # Invalid: no invoice_id
    with pytest.raises(InvalidInvoiceError, match="invoice_id must be non-empty"):
        Invoice(
            invoice_id="",
            customer_name="Acme Corp",
            due_date=date(2026, 9, 15),
            amount_cents=42_00,
        )

    # Invalid: no customer
    with pytest.raises(InvalidInvoiceError, match="customer_name must be non-empty"):
        Invoice(
            invoice_id="abc123",
            customer_name="",
            due_date=date(2026, 9, 15),
            amount_cents=42_00,
        )

    # Invalid: zero amount
    with pytest.raises(InvalidInvoiceError, match="amount_cents must be non-zero"):
        Invoice(
            invoice_id="abc123",
            customer_name="Acme Corp",
            due_date=date(2026, 9, 15),
            amount_cents=0,
        )


def test_invoice_overdue() -> None:
    """D-28: Check if an invoice has passed its due date."""
    # Not overdue
    inv = Invoice(
        invoice_id="abc123",
        customer_name="Acme Corp",
        due_date=date.today() + timedelta(days=1),  # Tomorrow
        amount_cents=42_00,
    )
    assert not is_overdue(inv)

    # Overdue
    inv = Invoice(
        invoice_id="xyz789",
        customer_name="Big Co",
        due_date=date.today() - timedelta(days=1),  # Yesterday
        amount_cents=50_00,
    )
    assert is_overdue(inv)


def test_update_invoice_status_transitions() -> None:
    """D-17: Status transitions must be valid."""
    inv = Invoice(
        invoice_id="abc123",
        customer_name="Acme Corp",
        due_date=date.today(),
        amount_cents=42_00,
        status=InvoiceStatus.DRAFT
    )

    # Valid transition
    new_inv = update_invoice_status(inv, InvoiceStatus.ISSUED)
    assert new_inv.status == InvoiceStatus.ISSUED

    # Invalid transition: DRAFT → PAID directly (should not be allowed)
    with pytest.raises(InvalidInvoiceError, match="invalid status transition"):
        update_invoice_status(inv, InvoiceStatus.PAID)

    # Valid transition
    inv_issued = update_invoice_status(inv, InvoiceStatus.ISSUED)
    # Issue → Payment
    new_inv2 = update_invoice_status(inv_issued, InvoiceStatus.PAID)
    assert new_inv2.status == InvoiceStatus.PAID

    # Invalid: Final state CANCELLED cannot transition
    with pytest.raises(InvalidInvoiceError, match="invalid status transition"):
        update_invoice_status(
            Invoice(
                invoice_id="abc123",
                customer_name="Acme Corp",
                due_date=date.today(),
                amount_cents=42_00,
                status=InvoiceStatus.CANCELLED
            ),
            InvoiceStatus.ISSUED
        )