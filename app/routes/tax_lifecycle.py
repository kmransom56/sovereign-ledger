"""Tax lifecycle routes: update status, mark as paid/filed, manage filings (Step 11).

Provides REST API endpoints for:
  - Mark tax liability as paid (reduces liability balance)
  - Track filing records (monthly, quarterly, annual)
  - Update filing status (draft → filed → paid → reconciled)
  - Reconcile filings against liability
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.dependencies import current_user

if TYPE_CHECKING:
    import psycopg

router = APIRouter(prefix="/api/tax/lifecycle", tags=["tax-lifecycle"])


# ============================================================================
# PYDANTIC MODELS
# ============================================================================


class MarkLiabilityPaidIn(BaseModel):
    """Mark tax liability as paid."""

    liability_id: int
    amount_paid_cents: int = Field(..., ge=0, description="Amount paid in cents")
    payment_date: date
    notes: str | None = None


class MarkLiabilityPaidOut(BaseModel):
    """Updated tax liability after payment."""

    id: int
    jurisdiction_id: int
    period_end: date
    collected_cents: int
    paid_cents: int
    remaining_cents: int
    status: str


class CreateFilingIn(BaseModel):
    """Create a tax filing record."""

    jurisdiction_code: str
    filing_period_start: date
    filing_period_end: date
    filing_type: str = Field(
        ..., description="Type of filing (monthly, quarterly, annual)"
    )
    total_sales_cents: int = Field(..., ge=0)
    tax_collected_cents: int = Field(..., ge=0)


class CreateFilingOut(BaseModel):
    """Created filing record."""

    id: int
    jurisdiction_code: str
    period_start: date
    period_end: date
    filing_type: str
    total_sales_cents: int
    tax_collected_cents: int
    tax_paid_cents: int
    status: str


class UpdateFilingStatusIn(BaseModel):
    """Update filing status."""

    filing_id: int
    status: str = Field(
        ..., description="New status (draft, filed, paid, reconciled)"
    )
    filing_date: date | None = None
    reference_number: str | None = None
    tax_paid_cents: int | None = None
    notes: str | None = None


class UpdateFilingStatusOut(BaseModel):
    """Updated filing record."""

    id: int
    jurisdiction_code: str
    filing_period_start: date
    filing_period_end: date
    filing_type: str
    status: str
    total_sales_cents: int
    tax_collected_cents: int
    tax_paid_cents: int
    filing_date: date | None
    reference_number: str | None


# ============================================================================
# TAX LIABILITY LIFECYCLE
# ============================================================================


@router.post("/liability/mark-paid", response_model=MarkLiabilityPaidOut)
def mark_liability_paid(
    req: MarkLiabilityPaidIn,
    request: Request,
    user: dict = Depends(current_user),
) -> MarkLiabilityPaidOut:
    """Mark portion of tax liability as paid.

    This updates the paid_cents column and recalculates status based on
    whether paid_cents >= collected_cents.
    """
    conn: psycopg.Connection = request.app.state.db

    try:
        with conn.cursor() as cur:
            # Get current liability
            cur.execute(
                "SELECT id, jurisdiction_id, period_end, collected_cents, paid_cents, status "
                "FROM tax_liability WHERE id = %s",
                (req.liability_id,),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Liability {req.liability_id} not found",
                )

            _, jur_id, period_end, collected, current_paid, current_status = row

            # Update paid amount
            new_paid = current_paid + req.amount_paid_cents
            if new_paid > collected:
                new_paid = collected  # Cap at collected amount

            # Determine new status
            if new_paid >= collected:
                new_status = "paid"
            else:
                new_status = "accrued"

            cur.execute(
                "UPDATE tax_liability SET paid_cents = %s, status = %s WHERE id = %s",
                (new_paid, new_status, req.liability_id),
            )

        conn.commit()

        return MarkLiabilityPaidOut(
            id=req.liability_id,
            jurisdiction_id=jur_id,
            period_end=period_end,
            collected_cents=collected,
            paid_cents=new_paid,
            remaining_cents=collected - new_paid,
            status=new_status,
        )

    except HTTPException:
        raise
    except Exception as exc:
        conn.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to mark liability paid: {exc}",
        ) from exc


# ============================================================================
# TAX FILING LIFECYCLE
# ============================================================================


@router.post("/filings", response_model=CreateFilingOut, status_code=status.HTTP_201_CREATED)
def create_filing(
    req: CreateFilingIn,
    request: Request,
    user: dict = Depends(current_user),
) -> CreateFilingOut:
    """Create a new tax filing record."""
    conn: psycopg.Connection = request.app.state.db

    try:
        with conn.cursor() as cur:
            # Get jurisdiction ID
            cur.execute(
                "SELECT id FROM tax_jurisdictions WHERE code = %s",
                (req.jurisdiction_code,),
            )
            jur_row = cur.fetchone()
            if not jur_row:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Jurisdiction {req.jurisdiction_code} not found",
                )
            jurisdiction_id = jur_row[0]

            # Create filing record
            cur.execute(
                """
                INSERT INTO tax_filings
                (jurisdiction_id, filing_period_start, filing_period_end, filing_type,
                 total_sales_cents, tax_collected_cents, tax_paid_cents, status)
                VALUES (%s, %s, %s, %s, %s, %s, 0, 'draft')
                RETURNING id, filing_period_start, filing_period_end, filing_type,
                          total_sales_cents, tax_collected_cents, tax_paid_cents, status
                """,
                (
                    jurisdiction_id,
                    req.filing_period_start,
                    req.filing_period_end,
                    req.filing_type,
                    req.total_sales_cents,
                    req.tax_collected_cents,
                ),
            )
            filing_row = cur.fetchone()

        conn.commit()

        return CreateFilingOut(
            id=filing_row[0],
            jurisdiction_code=req.jurisdiction_code,
            period_start=filing_row[1],
            period_end=filing_row[2],
            filing_type=filing_row[3],
            total_sales_cents=filing_row[4],
            tax_collected_cents=filing_row[5],
            tax_paid_cents=filing_row[6],
            status=filing_row[7],
        )

    except HTTPException:
        raise
    except Exception as exc:
        conn.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to create filing: {exc}",
        ) from exc


@router.patch("/filings/{filing_id}", response_model=UpdateFilingStatusOut)
def update_filing_status(
    filing_id: int,
    req: UpdateFilingStatusIn,
    request: Request,
    user: dict = Depends(current_user),
) -> UpdateFilingStatusOut:
    """Update filing status and details.

    Supports transitions:
      - draft → filed (set filing_date, reference_number)
      - filed → paid (set tax_paid_cents)
      - paid → reconciled
    """
    conn: psycopg.Connection = request.app.state.db

    try:
        with conn.cursor() as cur:
            # Get current filing
            cur.execute(
                """
                SELECT tf.id, tj.code, tf.filing_period_start, tf.filing_period_end,
                       tf.filing_type, tf.total_sales_cents, tf.tax_collected_cents,
                       tf.tax_paid_cents, tf.status
                FROM tax_filings tf
                JOIN tax_jurisdictions tj ON tf.jurisdiction_id = tj.id
                WHERE tf.id = %s
                """,
                (filing_id,),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Filing {filing_id} not found",
                )

            (
                fid,
                jur_code,
                period_start,
                period_end,
                filing_type,
                total_sales,
                tax_collected,
                tax_paid,
                current_status,
            ) = row

            # Update fields
            new_tax_paid = req.tax_paid_cents if req.tax_paid_cents is not None else tax_paid
            new_filing_date = req.filing_date
            new_reference = req.reference_number

            cur.execute(
                """
                UPDATE tax_filings
                SET status = %s, filing_date = %s, reference_number = %s, tax_paid_cents = %s
                WHERE id = %s
                """,
                (req.status, new_filing_date, new_reference, new_tax_paid, filing_id),
            )

        conn.commit()

        return UpdateFilingStatusOut(
            id=fid,
            jurisdiction_code=jur_code,
            filing_period_start=period_start,
            filing_period_end=period_end,
            filing_type=filing_type,
            status=req.status,
            total_sales_cents=total_sales,
            tax_collected_cents=tax_collected,
            tax_paid_cents=new_tax_paid,
            filing_date=new_filing_date,
            reference_number=new_reference,
        )

    except HTTPException:
        raise
    except Exception as exc:
        conn.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to update filing: {exc}",
        ) from exc
