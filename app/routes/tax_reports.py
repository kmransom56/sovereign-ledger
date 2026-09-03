"""Tax reports routes: liability summaries, jurisdiction breakdowns, filing status (Step 11).

Provides REST API endpoints for:
  - Tax liability by period (accrued, paid, outstanding)
  - Tax summary by jurisdiction
  - Tax filing status tracking
  - Filtering by jurisdiction and status
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel

from app.adapters.tax_reports import (
    tax_by_jurisdiction_summary,
    tax_filing_status_summary,
    tax_liability_summary,
)
from app.dependencies import current_user

if TYPE_CHECKING:
    import psycopg

router = APIRouter(prefix="/api/tax/reports", tags=["tax-reports"])


# ============================================================================
# PYDANTIC OUTPUT MODELS
# ============================================================================


class TaxLiabilityRowOut(BaseModel):
    """One tax liability row."""

    jurisdiction_code: str
    jurisdiction_name: str
    period_end: str  # ISO date
    collected_cents: int
    paid_cents: int
    balance_cents: int
    status: str


class TaxLiabilitySummaryOut(BaseModel):
    """Tax liability summary response."""

    rows: list[TaxLiabilityRowOut]
    total_collected_cents: int
    total_paid_cents: int
    total_balance_cents: int


class TaxByJurisdictionRowOut(BaseModel):
    """One jurisdiction tax row."""

    jurisdiction_code: str
    jurisdiction_name: str
    tax_type: str
    active: bool
    total_collected_cents: int
    total_paid_cents: int
    outstanding_cents: int
    period_count: int


class TaxByJurisdictionSummaryOut(BaseModel):
    """Tax by jurisdiction summary response."""

    rows: list[TaxByJurisdictionRowOut]
    total_collected_cents: int
    total_paid_cents: int
    total_outstanding_cents: int
    jurisdiction_count: int


class TaxFilingStatusRowOut(BaseModel):
    """One tax filing status row."""

    jurisdiction_code: str
    jurisdiction_name: str
    period_start: str  # ISO date
    period_end: str  # ISO date
    filing_type: str
    status: str
    total_sales_cents: int
    tax_collected_cents: int
    tax_paid_cents: int
    filing_date: str | None  # ISO date
    reference_number: str | None


class TaxFilingStatusSummaryOut(BaseModel):
    """Tax filing status summary response."""

    rows: list[TaxFilingStatusRowOut]
    pending_count: int
    filed_count: int
    paid_count: int
    reconciled_count: int


# ============================================================================
# TAX LIABILITY REPORTS
# ============================================================================


@router.get("/liability", response_model=TaxLiabilitySummaryOut)
def get_liability_summary(
    request: Request,
    user: dict = Depends(current_user),
    jurisdiction_code: str | None = None,
    status: str | None = None,
) -> TaxLiabilitySummaryOut:
    """Get tax liability summary by period.

    Filters:
        jurisdiction_code: Optional jurisdiction filter (e.g., "CA")
        status: Optional status filter (accrued, paid, settled, filed)

    Returns:
        Liability rows with totals.
    """
    conn: psycopg.Connection = request.app.state.db

    summary = tax_liability_summary(conn, jurisdiction_code, status)

    return TaxLiabilitySummaryOut(
        rows=[
            TaxLiabilityRowOut(
                jurisdiction_code=row.jurisdiction_code,
                jurisdiction_name=row.jurisdiction_name,
                period_end=row.period_end.isoformat(),
                collected_cents=row.collected_cents,
                paid_cents=row.paid_cents,
                balance_cents=row.balance_cents,
                status=row.status,
            )
            for row in summary.rows
        ],
        total_collected_cents=summary.total_collected_cents,
        total_paid_cents=summary.total_paid_cents,
        total_balance_cents=summary.total_balance_cents,
    )


# ============================================================================
# TAX BY JURISDICTION REPORTS
# ============================================================================


@router.get("/by-jurisdiction", response_model=TaxByJurisdictionSummaryOut)
def get_by_jurisdiction_summary(
    request: Request,
    user: dict = Depends(current_user),
    active_only: bool = True,
) -> TaxByJurisdictionSummaryOut:
    """Get tax summary aggregated by jurisdiction.

    Filters:
        active_only: Only include active jurisdictions (default: true)

    Returns:
        Jurisdiction rows with aggregated tax data.
    """
    conn: psycopg.Connection = request.app.state.db

    summary = tax_by_jurisdiction_summary(conn, active_only)

    return TaxByJurisdictionSummaryOut(
        rows=[
            TaxByJurisdictionRowOut(
                jurisdiction_code=row.jurisdiction_code,
                jurisdiction_name=row.jurisdiction_name,
                tax_type=row.tax_type,
                active=row.active,
                total_collected_cents=row.total_collected_cents,
                total_paid_cents=row.total_paid_cents,
                outstanding_cents=row.outstanding_cents,
                period_count=row.period_count,
            )
            for row in summary.rows
        ],
        total_collected_cents=summary.total_collected_cents,
        total_paid_cents=summary.total_paid_cents,
        total_outstanding_cents=summary.total_outstanding_cents,
        jurisdiction_count=summary.jurisdiction_count,
    )


# ============================================================================
# TAX FILING STATUS REPORTS
# ============================================================================


@router.get("/filing-status", response_model=TaxFilingStatusSummaryOut)
def get_filing_status_summary(
    request: Request,
    user: dict = Depends(current_user),
    status: str | None = None,
) -> TaxFilingStatusSummaryOut:
    """Get tax filing status summary.

    Shows filing status across all jurisdictions and periods, useful for
    tracking which filings are pending, filed, paid, or reconciled.

    Filters:
        status: Optional status filter (draft, filed, paid, reconciled)

    Returns:
        Filing status rows with counts by status.
    """
    conn: psycopg.Connection = request.app.state.db

    summary = tax_filing_status_summary(conn, status)

    return TaxFilingStatusSummaryOut(
        rows=[
            TaxFilingStatusRowOut(
                jurisdiction_code=row.jurisdiction_code,
                jurisdiction_name=row.jurisdiction_name,
                period_start=row.period_start.isoformat(),
                period_end=row.period_end.isoformat(),
                filing_type=row.filing_type,
                status=row.status,
                total_sales_cents=row.total_sales_cents,
                tax_collected_cents=row.tax_collected_cents,
                tax_paid_cents=row.tax_paid_cents,
                filing_date=row.filing_date.isoformat() if row.filing_date else None,
                reference_number=row.reference_number,
            )
            for row in summary.rows
        ],
        pending_count=summary.pending_count,
        filed_count=summary.filed_count,
        paid_count=summary.paid_count,
        reconciled_count=summary.reconciled_count,
    )
