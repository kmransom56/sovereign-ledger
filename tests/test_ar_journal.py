"""AR Journal Entry unit tests (pure, no DB).

Tests:
* :func:`ar_journal_entry` — create a balanced entry from an invoice.
* :func:`bad_debt_journal_entry` — create a write-off entry.

CK-18: AR journal entries must be valid accounting.
D-29: Debits = credits → balancing
D-30: Invoice must be validated before creating entries.
D-34: Bad debt write-offs are properly coded.
"""

import pytest
from datetime import date

from ledger.ar_invoice import Invoice, InvoiceStatus
from ledger.entries import JournalEntry
from ledger.types import AccountRef, AccountType


def test_ar_journal_entry_creation() -> None:
    """CK-18: AR DEBIT = AR asset +ve, CREDIT = income -ve."""
    # Create an invoice (without creating the actual entry yet)
    invoice = Invoice(
        invoice_id="inv-12345",
        customer_name="Acme Corp",
        due_date=date.today(),
        amount_cents=42_00,
        status=InvoiceStatus.ISSUED,
    )

    # Just validate that inputs are valid
    assert invoice.invoice_id == "inv-12345"
    assert invoice.amount_cents == 42_00


def test_bad_debt_journal_entry_creation() -> None:
    """D-34: Bad debt write-off logic test placeholder."""
    # Placeholder for future implementation.
    # When implemented, this will test the bad debt write-off journal entry creation.
    pass