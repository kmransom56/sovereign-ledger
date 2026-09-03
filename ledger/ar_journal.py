"""AR journal-entry domain logic (Step 8, CK-18).

Pure functions that compute AR journal entries from invoices.

D-18: AR account type → ASSET, subtype "AR"
CK-18: AR journal entries:
  * DEBIT: ASSET: AR (account), +ve cents
  * CREDIT: INCOME (liability, expense) or liability/asset for bad debt
  * DEBIT: ASSET: BAD_DEBT (account) for bad debt (D-34)
  * CREDIT: ASSET: BAD_DEBT for writing off bad debt

This module implements:
* :func:`ar_journal_entry` — compute an entry from invoice.
* :func:`bad_debt_journal_entry` — write-off bad debt entry.
"""

# Standard library imports
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Optional

from ledger.engine import JournalEntry, JournalLine, create_entry
from ledger.entries import validate_entry
from ledger.types import AccountRef, AccountType, Money, JournalEntry


@dataclass(frozen=True, slots=True)
class ARAccountConfig:
    """AR-specific account references."""
    ar_account: AccountRef  # ASSET with subtype "AR"
    income_account: AccountRef  # Default INCOME (e.g. 4000 Service Revenue)
    bad_debt_account: Optional[AccountRef] = None

    def __post_init__(self) -> None:
        if self.ar_account.type != AccountType.ASSET:
            raise ValueError("ar_account must be of type ASSET")
        # D-18: AR account type → ASSET, but with subtype "AR"
        if self.ar_account.subtype != "AR":
            raise ValueError("ar_account must have subtype 'AR'")
        if self.income_account.type != AccountType.INCOME:
            raise ValueError("income_account must be of type INCOME")


def ar_journal_entry(
    invoice: Invoice,
    ar_config: ARAccountConfig,
    entry_id: Optional[str] = None,
) -> JournalEntry:
    """Compute a journal entry from an AR invoice.

    CK-18, D-29: DEBIT AR asset +ve, CREDIT income -ve
    """
    # D-30: Invoice must be valid before generating JEs.
    validate_invoice(invoice)
    # D-29: Journal entry must balance
    #   ASSET(AR) DEBIT amount_cents (positive)
    #   INCOME CREDIT amount_cents (negative, offsetting DEBIT)
    ar_debit = JournalLine(
        account=ar_config.ar_account,
        debit=invoice.amount_cents,
        credit=0,
        description=f"AR invoice {invoice.invoice_id}",
    )
    income_credit = JournalLine(
        account=ar_config.income_account,
        debit=0,
        credit=-invoice.amount_cents,
        description=f"AR invoice {invoice.invoice_id}",
    )

    # CK-18: Create balanced, validating entry.
    entry = create_entry(
        lines=[ar_debit, income_credit],
        description=f"AR invoice {invoice.invoice_id} ({invoice.customer_name})",
        entry_id=entry_id,
        validate=True,
    )
    
    # Validate the entry is correct (double-checking)
    validate_entry(entry)
    return entry


def bad_debt_journal_entry(
    invoice: Invoice,
    ar_config: ARAccountConfig,
    entry_id: Optional[str] = None,
) -> JournalEntry:
    """Compute a journal entry for bad debt write-off.

    D-34: AR BAD_DEBT_ACCOUNT (ASSET) CREDIT
        → ASSET BAD_DEBT DEBIT (for loss)
    """
    if not ar_config.bad_debt_account:
        raise ValueError("ar_config must specify bad_debt_account for write-off")

    # D-34: Write-off is credit to BAD_DEBT account (to remove the debt),
    #       and debit to AR asset (to reduce the amount owed).
    bad_debt_credit = JournalLine(
        account=ar_config.bad_debt_account,
        debit=0,
        credit=invoice.amount_cents,  # Credit means positive
        description=f"Bad debt write-off {invoice.invoice_id}",
    )
    ar_debit = JournalLine(
        account=ar_config.ar_account,
        debit=invoice.amount_cents,  # DR
        credit=0,
        description=f"Bad debt write-off {invoice.invoice_id}",
    )

    entry = create_entry(
        lines=[bad_debt_credit, ar_debit],
        description=f"Bad debt write-off for invoice {invoice.invoice_id}",
        entry_id=entry_id,
        validate=True,
    )
    
    # Validate the entry is correct (double-checking)
    validate_entry(entry)
    return entry