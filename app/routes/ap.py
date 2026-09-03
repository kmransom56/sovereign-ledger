"""AP routes: vendors, bills, payments, expense tracking (Step 12).

REST API endpoints for Accounts Payable operations:
  - Vendor CRUD
  - Bill creation, posting, detail
  - Payment recording
  - AP aging and expense reports
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.adapters.ap_posting import (
    APPostingError,
    InvalidPaymentError,
    post_bill,
    record_payment,
)
from app.dependencies import current_user

if TYPE_CHECKING:
    import psycopg

router = APIRouter(prefix="/ap", tags=["ap"])


# ============================================================================
# PYDANTIC MODELS
# ============================================================================


class VendorIn(BaseModel):
    """Create or update vendor."""

    name: str
    tax_id: str | None = None
    contact_name: str | None = None
    email: str | None = None
    phone: str | None = None
    address: str | None = None
    city: str | None = None
    state: str | None = None
    zip_code: str | None = None
    payment_terms: str | None = None
    notes: str | None = None


class VendorOut(BaseModel):
    """Vendor response."""

    id: int
    name: str
    tax_id: str | None
    contact_name: str | None
    email: str | None
    phone: str | None
    address: str | None
    city: str | None
    state: str | None
    zip_code: str | None
    payment_terms: str | None
    is_active: bool
    notes: str | None


class ExpenseCategoryOut(BaseModel):
    """Expense category for dropdown/selection."""

    id: int
    code: str
    name: str
    account_id: int | None
    tax_deductible: bool


class BillLineIn(BaseModel):
    """Line item for bill."""

    expense_category_id: int
    description: str
    quantity: float = Field(default=1.0, ge=0)
    unit_price_cents: int = Field(..., ge=0)
    business_use_percent: float = Field(default=100.0, ge=0, le=100)


class CreateBillIn(BaseModel):
    """Create and post a bill."""

    vendor_id: int
    bill_number: str
    bill_date: date
    due_date: date
    period_end: date | None = None
    memo: str | None = None
    lines: list[BillLineIn]
    fiscal_period_id: int


class BillLineOut(BaseModel):
    """Posted bill line item."""

    id: int
    expense_category_id: int
    description: str
    quantity: float
    unit_price_cents: int
    amount_cents: int
    business_use_percent: float
    deductible_amount_cents: int


class BillOut(BaseModel):
    """Posted bill response."""

    id: int
    bill_number: str
    vendor_id: int
    bill_date: date
    due_date: date
    period_end: date | None
    total_amount_cents: int
    paid_amount_cents: int
    outstanding_cents: int
    status: str
    memo: str | None
    lines: list[BillLineOut]


class RecordPaymentIn(BaseModel):
    """Record a payment against a bill."""

    bill_id: int
    payment_date: date
    amount_cents: int = Field(..., gt=0)
    payment_method: str = Field(...)
    reference_number: str | None = None
    memo: str | None = None
    fiscal_period_id: int | None = None
    bank_account_id: int | None = None


class PaymentOut(BaseModel):
    """Payment response."""

    payment_id: int
    bill_id: int
    payment_date: date
    amount_cents: int
    payment_method: str
    reference_number: str | None
    memo: str | None


class BillAgingRow(BaseModel):
    """AP aging report row."""

    bill_id: int
    bill_number: str
    vendor_name: str
    bill_date: date
    due_date: date
    total_amount_cents: int
    paid_amount_cents: int
    outstanding_cents: int
    aging_status: str  # "Paid", "Current", "Overdue"
    days_overdue: int | None


# ============================================================================
# VENDORS
# ============================================================================


@router.post("/vendors", response_model=VendorOut, status_code=status.HTTP_201_CREATED)
def create_vendor(
    req: VendorIn,
    request: Request,
    user: dict = Depends(current_user),
) -> VendorOut:
    """Create a new vendor."""
    conn: psycopg.Connection = request.app.state.db

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO vendors
                (name, tax_id, contact_name, email, phone, address, city, state,
                 zip_code, payment_terms, notes)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id, is_active
                """,
                (
                    req.name,
                    req.tax_id,
                    req.contact_name,
                    req.email,
                    req.phone,
                    req.address,
                    req.city,
                    req.state,
                    req.zip_code,
                    req.payment_terms,
                    req.notes,
                ),
            )
            vendor_id, is_active = cur.fetchone()
        conn.commit()

        return VendorOut(
            id=vendor_id,
            name=req.name,
            tax_id=req.tax_id,
            contact_name=req.contact_name,
            email=req.email,
            phone=req.phone,
            address=req.address,
            city=req.city,
            state=req.state,
            zip_code=req.zip_code,
            payment_terms=req.payment_terms,
            is_active=is_active,
            notes=req.notes,
        )

    except Exception as exc:
        conn.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to create vendor: {exc}",
        ) from exc


@router.get("/vendors", response_model=dict)
def list_vendors(
    request: Request,
    active_only: bool = True,
    user: dict = Depends(current_user),
) -> dict:
    """List vendors."""
    conn: psycopg.Connection = request.app.state.db

    try:
        with conn.cursor() as cur:
            if active_only:
                cur.execute("SELECT id, name, email, payment_terms FROM vendors WHERE is_active = true ORDER BY name")
            else:
                cur.execute("SELECT id, name, email, payment_terms FROM vendors ORDER BY name")

            rows = cur.fetchall()

        vendors = [
            {
                "id": row[0],
                "name": row[1],
                "email": row[2],
                "payment_terms": row[3],
            }
            for row in rows
        ]

        return {"vendors": vendors}

    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list vendors: {exc}",
        ) from exc


@router.get("/vendors/{vendor_id}", response_model=VendorOut)
def get_vendor(
    vendor_id: int,
    request: Request,
    user: dict = Depends(current_user),
) -> VendorOut:
    """Get vendor detail."""
    conn: psycopg.Connection = request.app.state.db

    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, name, tax_id, contact_name, email, phone, address, city, state, zip_code, payment_terms, is_active, notes FROM vendors WHERE id = %s",
                (vendor_id,),
            )
            row = cur.fetchone()

            if not row:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Vendor {vendor_id} not found",
                )

        return VendorOut(
            id=row[0],
            name=row[1],
            tax_id=row[2],
            contact_name=row[3],
            email=row[4],
            phone=row[5],
            address=row[6],
            city=row[7],
            state=row[8],
            zip_code=row[9],
            payment_terms=row[10],
            is_active=row[11],
            notes=row[12],
        )

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get vendor: {exc}",
        ) from exc


# ============================================================================
# BILLS
# ============================================================================


@router.post("/bills", response_model=BillOut, status_code=status.HTTP_201_CREATED)
def create_and_post_bill(
    req: CreateBillIn,
    request: Request,
    user: dict = Depends(current_user),
) -> BillOut:
    """Create and post a bill."""
    if not req.lines:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Bill must have at least one line item",
        )

    conn: psycopg.Connection = request.app.state.db

    try:
        # Prepare bill items for posting
        bill_items = []
        for line in req.lines:
            bill_items.append(
                {
                    "expense_category_id": line.expense_category_id,
                    "description": line.description,
                    "quantity": line.quantity,
                    "unit_price_cents": line.unit_price_cents,
                    "business_use_percent": line.business_use_percent,
                }
            )

        # Post bill
        result = post_bill(
            conn=conn,
            bill_number=req.bill_number,
            vendor_id=req.vendor_id,
            bill_date=req.bill_date,
            due_date=req.due_date,
            memo=req.memo,
            period_end=req.period_end,
            bill_items=bill_items,
            fiscal_period_id=req.fiscal_period_id,
        )

        # Fetch full bill details
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, bill_number, vendor_id, bill_date, due_date, period_end, total_amount_cents, paid_amount_cents, status, memo FROM bills WHERE id = %s",
                (result["bill_id"],),
            )
            bill_row = cur.fetchone()

            cur.execute(
                "SELECT id, expense_category_id, description, quantity, unit_price_cents, amount_cents, business_use_percent, deductible_amount_cents FROM bill_items WHERE bill_id = %s ORDER BY id",
                (result["bill_id"],),
            )
            line_rows = cur.fetchall()

        lines = [
            BillLineOut(
                id=lr[0],
                expense_category_id=lr[1],
                description=lr[2],
                quantity=lr[3],
                unit_price_cents=lr[4],
                amount_cents=lr[5],
                business_use_percent=lr[6],
                deductible_amount_cents=lr[7],
            )
            for lr in line_rows
        ]

        return BillOut(
            id=bill_row[0],
            bill_number=bill_row[1],
            vendor_id=bill_row[2],
            bill_date=bill_row[3],
            due_date=bill_row[4],
            period_end=bill_row[5],
            total_amount_cents=bill_row[6],
            paid_amount_cents=bill_row[7],
            outstanding_cents=bill_row[6] - bill_row[7],
            status=bill_row[8],
            memo=bill_row[9],
            lines=lines,
        )

    except APPostingError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        conn.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to create bill: {exc}",
        ) from exc


@router.get("/bills/{bill_id}", response_model=BillOut)
def get_bill(
    bill_id: int,
    request: Request,
    user: dict = Depends(current_user),
) -> BillOut:
    """Get bill detail with line items."""
    conn: psycopg.Connection = request.app.state.db

    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, bill_number, vendor_id, bill_date, due_date, period_end, total_amount_cents, paid_amount_cents, status, memo FROM bills WHERE id = %s",
                (bill_id,),
            )
            bill_row = cur.fetchone()

            if not bill_row:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Bill {bill_id} not found",
                )

            cur.execute(
                "SELECT id, expense_category_id, description, quantity, unit_price_cents, amount_cents, business_use_percent, deductible_amount_cents FROM bill_items WHERE bill_id = %s ORDER BY id",
                (bill_id,),
            )
            line_rows = cur.fetchall()

        lines = [
            BillLineOut(
                id=lr[0],
                expense_category_id=lr[1],
                description=lr[2],
                quantity=lr[3],
                unit_price_cents=lr[4],
                amount_cents=lr[5],
                business_use_percent=lr[6],
                deductible_amount_cents=lr[7],
            )
            for lr in line_rows
        ]

        return BillOut(
            id=bill_row[0],
            bill_number=bill_row[1],
            vendor_id=bill_row[2],
            bill_date=bill_row[3],
            due_date=bill_row[4],
            period_end=bill_row[5],
            total_amount_cents=bill_row[6],
            paid_amount_cents=bill_row[7],
            outstanding_cents=bill_row[6] - bill_row[7],
            status=bill_row[8],
            memo=bill_row[9],
            lines=lines,
        )

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get bill: {exc}",
        ) from exc


# ============================================================================
# PAYMENTS
# ============================================================================


@router.post("/payments", response_model=PaymentOut, status_code=status.HTTP_201_CREATED)
def record_bill_payment(
    req: RecordPaymentIn,
    request: Request,
    user: dict = Depends(current_user),
) -> PaymentOut:
    """Record a payment against a bill."""
    conn: psycopg.Connection = request.app.state.db

    try:
        result = record_payment(
            conn=conn,
            bill_id=req.bill_id,
            payment_date=req.payment_date,
            amount_cents=req.amount_cents,
            payment_method=req.payment_method,
            reference_number=req.reference_number,
            memo=req.memo,
            fiscal_period_id=req.fiscal_period_id,
            bank_account_id=req.bank_account_id,
        )

        # Fetch payment details
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, bill_id, payment_date, amount_cents, payment_method, reference_number, memo FROM bill_payments WHERE id = %s",
                (result["payment_id"],),
            )
            payment_row = cur.fetchone()

        return PaymentOut(
            payment_id=payment_row[0],
            bill_id=payment_row[1],
            payment_date=payment_row[2],
            amount_cents=payment_row[3],
            payment_method=payment_row[4],
            reference_number=payment_row[5],
            memo=payment_row[6],
        )

    except (APPostingError, InvalidPaymentError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        conn.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to record payment: {exc}",
        ) from exc


# ============================================================================
# REPORTS
# ============================================================================


@router.get("/aging", response_model=dict)
def ap_aging_report(
    request: Request,
    user: dict = Depends(current_user),
) -> dict:
    """AP aging report - unpaid bills by due date."""
    conn: psycopg.Connection = request.app.state.db

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, bill_number, vendor_name, bill_date, due_date,
                       total_amount_cents, paid_amount_cents, outstanding_cents,
                       aging_status, days_overdue
                FROM ap_aging
                ORDER BY due_date ASC
                """
            )
            rows = cur.fetchall()

        aging_rows = [
            BillAgingRow(
                bill_id=row[0],
                bill_number=row[1],
                vendor_name=row[2],
                bill_date=row[3],
                due_date=row[4],
                total_amount_cents=row[5],
                paid_amount_cents=row[6],
                outstanding_cents=row[7],
                aging_status=row[8],
                days_overdue=row[9],
            )
            for row in rows
        ]

        # Calculate totals
        total_outstanding = sum(row.outstanding_cents for row in aging_rows)
        overdue_count = sum(1 for row in aging_rows if row.aging_status == "Overdue")
        current_count = sum(1 for row in aging_rows if row.aging_status == "Current")

        return {
            "rows": [row.dict() for row in aging_rows],
            "total_outstanding_cents": total_outstanding,
            "overdue_count": overdue_count,
            "current_count": current_count,
            "bill_count": len(aging_rows),
        }

    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load aging report: {exc}",
        ) from exc


@router.get("/expenses", response_model=dict)
def expense_summary(
    request: Request,
    user: dict = Depends(current_user),
) -> dict:
    """Expense summary by category for tax reporting."""
    conn: psycopg.Connection = request.app.state.db

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT ec.code, ec.name, ec.tax_deductible,
                       SUM(bi.amount_cents) as total_cents,
                       SUM(bi.deductible_amount_cents) as deductible_cents,
                       COUNT(DISTINCT b.id) as bill_count
                FROM bill_items bi
                JOIN bills b ON bi.bill_id = b.id
                JOIN expense_categories ec ON bi.expense_category_id = ec.id
                WHERE b.status != 'voided'
                GROUP BY ec.id, ec.code, ec.name, ec.tax_deductible
                ORDER BY ec.name
                """
            )
            rows = cur.fetchall()

        summary = [
            {
                "category_code": row[0],
                "category_name": row[1],
                "tax_deductible": row[2],
                "total_cents": row[3] or 0,
                "deductible_cents": row[4] or 0,
                "bill_count": row[5],
            }
            for row in rows
        ]

        total_all = sum(row["total_cents"] for row in summary)
        total_deductible = sum(row["deductible_cents"] for row in summary)

        return {
            "categories": summary,
            "total_amount_cents": total_all,
            "total_deductible_cents": total_deductible,
        }

    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load expense summary: {exc}",
        ) from exc
