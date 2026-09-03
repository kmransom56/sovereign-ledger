"""Tax management routes: jurisdictions, rates, exemptions, liability tracking (Step 11).

Provides REST API endpoints for:
  - Create and list tax jurisdictions
  - Set effective tax rates with date ranges
  - Manage customer tax exemptions (resale, nonprofit, etc.)
  - View tax liability by jurisdiction and period
  - Track tax filing and payment status
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.dependencies import current_user

if TYPE_CHECKING:
    import psycopg

router = APIRouter(prefix="/api/tax", tags=["tax"])


# ============================================================================
# PYDANTIC MODELS
# ============================================================================


class TaxJurisdictionIn(BaseModel):
    """Input for creating a tax jurisdiction."""

    code: str = Field(..., min_length=2, max_length=20, description="Jurisdiction code (CA, TX, etc.)")
    name: str = Field(..., min_length=1, max_length=255, description="Jurisdiction name")
    tax_type: str = Field(..., description="Type of tax (sales_tax, vat, gst, hst)")
    region_type: str | None = Field(None, description="Region type (state, country, local)")


class TaxJurisdictionOut(BaseModel):
    """Output for a tax jurisdiction."""

    id: int
    code: str
    name: str
    tax_type: str
    region_type: str | None
    active: bool


class TaxRateIn(BaseModel):
    """Input for setting a tax rate."""

    jurisdiction_code: str
    rate_percent: float = Field(..., ge=0, le=100, description="Tax rate as percentage")
    effective_from: date
    effective_until: date | None = None
    notes: str | None = None


class TaxRateOut(BaseModel):
    """Output for a tax rate."""

    id: int
    jurisdiction_code: str
    rate_percent: float
    effective_from: date
    effective_until: date | None


class CustomerTaxExemptionIn(BaseModel):
    """Input for creating a customer tax exemption."""

    customer_id: int
    jurisdiction_code: str
    exemption_type: str = Field(..., description="Type (resale, nonprofit, government, foreign)")
    exemption_number: str | None = Field(None, description="Cert/number reference")
    effective_from: date
    effective_until: date | None = None


class CustomerTaxExemptionOut(BaseModel):
    """Output for a customer tax exemption."""

    id: int
    customer_id: int
    jurisdiction_code: str
    exemption_type: str
    exemption_number: str | None
    effective_from: date
    effective_until: date | None
    active: bool


class TaxLiabilityOut(BaseModel):
    """Output for tax liability record."""

    id: int
    jurisdiction_code: str
    period_end: date
    collected_cents: int
    paid_cents: int
    status: str


# ============================================================================
# TAX JURISDICTIONS
# ============================================================================


@router.post("/jurisdictions", response_model=TaxJurisdictionOut, status_code=status.HTTP_201_CREATED)
def create_jurisdiction(
    req: TaxJurisdictionIn,
    request: Request,
    user: dict = Depends(current_user),
) -> TaxJurisdictionOut:
    """Create a new tax jurisdiction."""
    conn: psycopg.Connection = request.app.state.db

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO tax_jurisdictions (code, name, tax_type, region_type, active)
                VALUES (%s, %s, %s, %s, true)
                RETURNING id, code, name, tax_type, region_type, active
                """,
                (req.code, req.name, req.tax_type, req.region_type),
            )
            row = cur.fetchone()

        conn.commit()

        return TaxJurisdictionOut(
            id=row[0],
            code=row[1],
            name=row[2],
            tax_type=row[3],
            region_type=row[4],
            active=row[5],
        )

    except Exception as exc:
        conn.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to create jurisdiction: {exc}",
        ) from exc


@router.get("/jurisdictions", response_model=list[TaxJurisdictionOut])
def list_jurisdictions(
    request: Request,
    user: dict = Depends(current_user),
    active_only: bool = True,
) -> list[TaxJurisdictionOut]:
    """List tax jurisdictions."""
    conn: psycopg.Connection = request.app.state.db

    try:
        with conn.cursor() as cur:
            query = "SELECT id, code, name, tax_type, region_type, active FROM tax_jurisdictions"
            params = []

            if active_only:
                query += " WHERE active = true"

            query += " ORDER BY code"

            cur.execute(query, params)
            rows = cur.fetchall()

        return [
            TaxJurisdictionOut(
                id=row[0],
                code=row[1],
                name=row[2],
                tax_type=row[3],
                region_type=row[4],
                active=row[5],
            )
            for row in rows
        ]

    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list jurisdictions: {exc}",
        ) from exc


# ============================================================================
# TAX RATES
# ============================================================================


@router.post("/rates", response_model=TaxRateOut, status_code=status.HTTP_201_CREATED)
def set_tax_rate(
    req: TaxRateIn,
    request: Request,
    user: dict = Depends(current_user),
) -> TaxRateOut:
    """Set a tax rate for a jurisdiction effective on a date range."""
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

            # Insert rate
            cur.execute(
                """
                INSERT INTO tax_rates
                (jurisdiction_id, rate_percent, effective_from, effective_until, notes)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id, rate_percent, effective_from, effective_until
                """,
                (jurisdiction_id, req.rate_percent, req.effective_from, req.effective_until, req.notes),
            )
            rate_row = cur.fetchone()

        conn.commit()

        return TaxRateOut(
            id=rate_row[0],
            jurisdiction_code=req.jurisdiction_code,
            rate_percent=rate_row[1],
            effective_from=rate_row[2],
            effective_until=rate_row[3],
        )

    except HTTPException:
        raise
    except Exception as exc:
        conn.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to set tax rate: {exc}",
        ) from exc


@router.get("/rates/{jurisdiction_code}", response_model=list[TaxRateOut])
def get_tax_rates(
    jurisdiction_code: str,
    request: Request,
    user: dict = Depends(current_user),
) -> list[TaxRateOut]:
    """Get all tax rates for a jurisdiction."""
    conn: psycopg.Connection = request.app.state.db

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT tr.id, tj.code, tr.rate_percent, tr.effective_from, tr.effective_until
                FROM tax_rates tr
                JOIN tax_jurisdictions tj ON tr.jurisdiction_id = tj.id
                WHERE tj.code = %s
                ORDER BY tr.effective_from DESC
                """,
                (jurisdiction_code,),
            )
            rows = cur.fetchall()

        return [
            TaxRateOut(
                id=row[0],
                jurisdiction_code=row[1],
                rate_percent=row[2],
                effective_from=row[3],
                effective_until=row[4],
            )
            for row in rows
        ]

    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get tax rates: {exc}",
        ) from exc


# ============================================================================
# CUSTOMER TAX EXEMPTIONS
# ============================================================================


@router.post("/exemptions", response_model=CustomerTaxExemptionOut, status_code=status.HTTP_201_CREATED)
def create_exemption(
    req: CustomerTaxExemptionIn,
    request: Request,
    user: dict = Depends(current_user),
) -> CustomerTaxExemptionOut:
    """Create a tax exemption for a customer in a jurisdiction."""
    conn: psycopg.Connection = request.app.state.db

    try:
        with conn.cursor() as cur:
            # Verify customer exists
            cur.execute("SELECT id FROM customers WHERE id = %s", (req.customer_id,))
            if not cur.fetchone():
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Customer {req.customer_id} not found",
                )

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

            # Insert exemption
            cur.execute(
                """
                INSERT INTO customer_tax_exemptions
                (customer_id, jurisdiction_id, exemption_type, exemption_number,
                 effective_from, effective_until, active)
                VALUES (%s, %s, %s, %s, %s, %s, true)
                RETURNING id, customer_id, exemption_type, exemption_number,
                          effective_from, effective_until, active
                """,
                (
                    req.customer_id,
                    jurisdiction_id,
                    req.exemption_type,
                    req.exemption_number,
                    req.effective_from,
                    req.effective_until,
                ),
            )
            exemption_row = cur.fetchone()

        conn.commit()

        return CustomerTaxExemptionOut(
            id=exemption_row[0],
            customer_id=exemption_row[1],
            jurisdiction_code=req.jurisdiction_code,
            exemption_type=exemption_row[2],
            exemption_number=exemption_row[3],
            effective_from=exemption_row[4],
            effective_until=exemption_row[5],
            active=exemption_row[6],
        )

    except HTTPException:
        raise
    except Exception as exc:
        conn.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to create exemption: {exc}",
        ) from exc


@router.get("/exemptions/{customer_id}", response_model=list[CustomerTaxExemptionOut])
def get_customer_exemptions(
    customer_id: int,
    request: Request,
    user: dict = Depends(current_user),
    active_only: bool = True,
) -> list[CustomerTaxExemptionOut]:
    """Get tax exemptions for a customer."""
    conn: psycopg.Connection = request.app.state.db

    try:
        with conn.cursor() as cur:
            query = """
                SELECT cte.id, cte.customer_id, tj.code, cte.exemption_type,
                       cte.exemption_number, cte.effective_from, cte.effective_until, cte.active
                FROM customer_tax_exemptions cte
                JOIN tax_jurisdictions tj ON cte.jurisdiction_id = tj.id
                WHERE cte.customer_id = %s
            """
            params = [customer_id]

            if active_only:
                query += " AND cte.active = true"

            query += " ORDER BY tj.code, cte.effective_from DESC"

            cur.execute(query, params)
            rows = cur.fetchall()

        return [
            CustomerTaxExemptionOut(
                id=row[0],
                customer_id=row[1],
                jurisdiction_code=row[2],
                exemption_type=row[3],
                exemption_number=row[4],
                effective_from=row[5],
                effective_until=row[6],
                active=row[7],
            )
            for row in rows
        ]

    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get exemptions: {exc}",
        ) from exc


# ============================================================================
# TAX LIABILITY
# ============================================================================


@router.get("/liability", response_model=list[TaxLiabilityOut])
def get_tax_liability(
    request: Request,
    user: dict = Depends(current_user),
    jurisdiction_code: str | None = None,
    status_filter: str | None = None,
) -> list[TaxLiabilityOut]:
    """Get tax liability records."""
    conn: psycopg.Connection = request.app.state.db

    try:
        with conn.cursor() as cur:
            query = """
                SELECT tl.id, tj.code, tl.period_end, tl.collected_cents, tl.paid_cents, tl.status
                FROM tax_liability tl
                JOIN tax_jurisdictions tj ON tl.jurisdiction_id = tj.id
            """
            params = []

            if jurisdiction_code:
                query += " WHERE tj.code = %s"
                params.append(jurisdiction_code)

                if status_filter:
                    query += " AND tl.status = %s"
                    params.append(status_filter)
            elif status_filter:
                query += " WHERE tl.status = %s"
                params.append(status_filter)

            query += " ORDER BY tl.period_end DESC"

            cur.execute(query, params)
            rows = cur.fetchall()

        return [
            TaxLiabilityOut(
                id=row[0],
                jurisdiction_code=row[1],
                period_end=row[2],
                collected_cents=row[3],
                paid_cents=row[4],
                status=row[5],
            )
            for row in rows
        ]

    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get tax liability: {exc}",
        ) from exc
