"""Tax summary reports: liability by period, jurisdiction, and filing status (Step 11).

Computes tax liability views useful for:
  - Understanding current tax obligations
  - Planning tax payments
  - Tracking filing status
  - Reconciling tax accounts
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


class TaxSummaryError(ValueError):
    """Base error for tax summary operations."""


@dataclass(frozen=True, slots=True)
class TaxLiabilityRow:
    """One row of tax liability data by jurisdiction and period.

    Attributes:
        jurisdiction_code: Tax jurisdiction (e.g., "CA", "TX")
        jurisdiction_name: Human-readable name
        period_end: End date of the tax period
        collected_cents: Total tax collected (signed integer)
        paid_cents: Amount paid to jurisdiction
        balance_cents: Outstanding balance (collected - paid)
        status: Liability status (accrued, paid, settled, filed)
    """

    jurisdiction_code: str
    jurisdiction_name: str
    period_end: date
    collected_cents: int
    paid_cents: int
    balance_cents: int
    status: str


@dataclass(frozen=True, slots=True)
class TaxLiabilitySummary:
    """Summary of all tax liabilities.

    Attributes:
        rows: List of liability rows by jurisdiction and period
        total_collected_cents: Sum of all tax collected
        total_paid_cents: Sum of all tax paid
        total_balance_cents: Outstanding tax (collected - paid)
    """

    rows: tuple[TaxLiabilityRow, ...]
    total_collected_cents: int
    total_paid_cents: int
    total_balance_cents: int


@dataclass(frozen=True, slots=True)
class TaxByJurisdictionRow:
    """Tax breakdown by jurisdiction (all periods combined).

    Attributes:
        jurisdiction_code: Tax jurisdiction code
        jurisdiction_name: Human-readable name
        tax_type: Type of tax (sales_tax, vat, etc.)
        active: Whether jurisdiction is active
        total_collected_cents: Total tax collected across all periods
        total_paid_cents: Total tax paid across all periods
        outstanding_cents: Current outstanding balance
        period_count: Number of periods with activity
    """

    jurisdiction_code: str
    jurisdiction_name: str
    tax_type: str
    active: bool
    total_collected_cents: int
    total_paid_cents: int
    outstanding_cents: int
    period_count: int


@dataclass(frozen=True, slots=True)
class TaxByJurisdictionSummary:
    """Summary of taxes by jurisdiction.

    Attributes:
        rows: Tax data grouped by jurisdiction
        total_collected_cents: Grand total collected
        total_paid_cents: Grand total paid
        total_outstanding_cents: Grand total outstanding
        jurisdiction_count: Number of jurisdictions with activity
    """

    rows: tuple[TaxByJurisdictionRow, ...]
    total_collected_cents: int
    total_paid_cents: int
    total_outstanding_cents: int
    jurisdiction_count: int


@dataclass(frozen=True, slots=True)
class TaxFilingStatusRow:
    """Tax filing status by jurisdiction and period.

    Attributes:
        jurisdiction_code: Tax jurisdiction
        jurisdiction_name: Human-readable name
        period_start: Start of filing period
        period_end: End of filing period
        filing_type: Type (monthly, quarterly, annual)
        status: Filing status (draft, filed, paid, reconciled)
        total_sales_cents: Total sales in period
        tax_collected_cents: Tax collected in period
        tax_paid_cents: Tax paid on this filing
        filing_date: Date the filing was submitted
        reference_number: Confirmation number from jurisdiction
    """

    jurisdiction_code: str
    jurisdiction_name: str
    period_start: date
    period_end: date
    filing_type: str
    status: str
    total_sales_cents: int
    tax_collected_cents: int
    tax_paid_cents: int
    filing_date: date | None
    reference_number: str | None


@dataclass(frozen=True, slots=True)
class TaxFilingStatusSummary:
    """Summary of tax filing status across jurisdictions.

    Attributes:
        rows: Filing status rows
        pending_count: Number of draft filings awaiting submission
        filed_count: Number of filings submitted
        paid_count: Number of filings marked paid
        reconciled_count: Number of filings reconciled
    """

    rows: tuple[TaxFilingStatusRow, ...]
    pending_count: int
    filed_count: int
    paid_count: int
    reconciled_count: int
