"""REST API routes for tax optimization (Step 13, Phase 4).

Endpoints for capital asset management, deduction tracking, estimated tax
calculations, and tax break recommendations.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.adapters.tax_optimization import (
    calculate_and_save_depreciation_schedule,
    load_capital_asset,
    load_capital_assets_for_user,
    load_deduction_aggregate,
    load_deduction_aggregates_for_period,
    load_depreciation_schedule,
    load_estimated_tax_payments_for_year,
    load_tax_break_opportunities,
    load_tax_form_mappings,
    save_capital_asset,
    save_deduction_aggregate,
    save_deduction_audit_trail,
    save_estimated_tax_payment,
    save_tax_break_opportunity,
)
from ledger.capital_assets import (
    AssetType,
    CapitalAsset,
    DepreciationMethod,
    create_depreciation_schedule,
)
from ledger.deductions import (
    DeductionCategory,
    aggregate_deductions_by_period,
    identify_tax_breaks,
)
from ledger.tax_projections import (
    FilingStatus,
    calculate_quarterly_estimate,
    project_year_end_tax,
)
from ledger.tax_recommendations import (
    generate_compliance_recommendations,
    generate_deduction_recommendations,
    generate_optimization_recommendations,
    prioritize_recommendations,
)

router = APIRouter(prefix="/tax-optimization", tags=["Tax Optimization"])


# ============================================================================
# Request/Response Models
# ============================================================================


class CapitalAssetInput(BaseModel):
    """Input model for creating a capital asset."""

    description: str
    asset_type: str
    cost_basis_cents: int
    salvage_value_cents: int = 0
    useful_life_years: int
    depreciation_method: str = "macrs_200db"
    date_placed_in_service: date
    vendor_name: str | None = None
    invoice_date: date | None = None
    invoice_number: str | None = None
    notes: str | None = None


class CapitalAssetResponse(BaseModel):
    """Response model for capital asset."""

    id: int
    description: str
    asset_type: str
    cost_basis_cents: int
    salvage_value_cents: int
    useful_life_years: int
    depreciation_method: str
    date_placed_in_service: date
    vendor_name: str | None = None


class DepreciationYearResponse(BaseModel):
    """Response model for single year of depreciation."""

    year: int
    depreciation_cents: int
    accumulated_depreciation_cents: int
    book_value_cents: int


class DeductionSummaryResponse(BaseModel):
    """Response model for deduction summary."""

    start_date: date
    end_date: date
    total_amount_cents: int
    total_deductible_cents: int
    count: int
    deduction_rate_percent: float


class EstimatedTaxInput(BaseModel):
    """Input for quarterly estimated tax calculation."""

    year: int
    quarter: int
    projected_annual_income_cents: int
    projected_annual_deductions_cents: int
    prior_year_tax_cents: int = 0
    filing_status: str = "single"


class EstimatedTaxResponse(BaseModel):
    """Response for quarterly estimated tax."""

    year: int
    quarter: int
    safe_harbor_90_current_year_cents: int
    safe_harbor_100_prior_year_cents: int
    recommended_payment_cents: int
    due_date: date


class TaxBreakResponse(BaseModel):
    """Response model for tax break opportunity."""

    opportunity_type: str
    description: str
    current_deduction_cents: int
    potential_deduction_cents_cents: int
    tax_savings_cents: int
    estimated_marginal_rate: float
    status: str


class TaxRecommendationResponse(BaseModel):
    """Response model for tax recommendation."""

    recommendation_id: str
    recommendation_type: str
    priority: str
    title: str
    description: str
    estimated_tax_impact_cents: int
    estimated_compliance_risk_cents: int
    next_steps: list[str] | None = None


# ============================================================================
# Capital Assets Endpoints
# ============================================================================


@router.post("/capital-assets")
def create_capital_asset(
    request: Request,
    input_data: CapitalAssetInput,
    user: dict[str, Any] = Depends(lambda req: {"id": 1}),  # TODO: auth
) -> dict[str, Any]:
    """Create a new capital asset.

    POST /tax-optimization/capital-assets
    """
    try:
        # Validate input
        asset = CapitalAsset(
            asset_id=0,  # Will be set by database
            description=input_data.description,
            asset_type=AssetType(input_data.asset_type),
            cost_basis_cents=input_data.cost_basis_cents,
            salvage_value_cents=input_data.salvage_value_cents,
            useful_life_years=input_data.useful_life_years,
            depreciation_method=DepreciationMethod(input_data.depreciation_method),
            date_placed_in_service=input_data.date_placed_in_service,
            vendor_name=input_data.vendor_name,
            invoice_date=input_data.invoice_date,
            invoice_number=input_data.invoice_number,
            notes=input_data.notes,
        )

        # Save asset
        conn = request.app.state.db
        asset_id = save_capital_asset(conn, user["id"], asset)

        # Calculate and save depreciation schedule
        asset_with_id = CapitalAsset(
            asset_id=asset_id,
            description=asset.description,
            asset_type=asset.asset_type,
            cost_basis_cents=asset.cost_basis_cents,
            salvage_value_cents=asset.salvage_value_cents,
            useful_life_years=asset.useful_life_years,
            depreciation_method=asset.depreciation_method,
            date_placed_in_service=asset.date_placed_in_service,
            vendor_name=asset.vendor_name,
            invoice_date=asset.invoice_date,
            invoice_number=asset.invoice_number,
            notes=asset.notes,
        )

        calculate_and_save_depreciation_schedule(
            conn, user["id"], asset_id, asset_with_id
        )

        return {
            "id": asset_id,
            "description": asset.description,
            "asset_type": asset.asset_type.value,
            "cost_basis_cents": asset.cost_basis_cents,
            "useful_life_years": asset.useful_life_years,
            "date_placed_in_service": asset.date_placed_in_service.isoformat(),
        }

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/capital-assets")
def list_capital_assets(
    request: Request,
    asset_type: str | None = Query(None),
    user: dict[str, Any] = Depends(lambda req: {"id": 1}),
) -> dict[str, Any]:
    """List capital assets for the user.

    GET /tax-optimization/capital-assets?asset_type=computer_equipment
    """
    conn = request.app.state.db
    assets = load_capital_assets_for_user(conn, user["id"], asset_type)
    return {"assets": assets, "count": len(assets)}


@router.get("/capital-assets/{asset_id}")
def get_capital_asset(
    request: Request,
    asset_id: int,
    user: dict[str, Any] = Depends(lambda req: {"id": 1}),
) -> dict[str, Any]:
    """Get details for a specific capital asset.

    GET /tax-optimization/capital-assets/1
    """
    conn = request.app.state.db
    asset = load_capital_asset(conn, user["id"], asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    return {
        "id": asset.asset_id,
        "description": asset.description,
        "asset_type": asset.asset_type,
        "cost_basis_cents": asset.cost_basis_cents,
        "salvage_value_cents": asset.salvage_value_cents,
        "useful_life_years": asset.useful_life_years,
        "depreciation_method": asset.depreciation_method.value,
        "date_placed_in_service": asset.date_placed_in_service.isoformat(),
    }


@router.get("/capital-assets/{asset_id}/depreciation")
def get_depreciation_schedule(
    request: Request,
    asset_id: int,
    user: dict[str, Any] = Depends(lambda req: {"id": 1}),
) -> dict[str, Any]:
    """Get depreciation schedule for an asset.

    GET /tax-optimization/capital-assets/1/depreciation
    """
    conn = request.app.state.db
    asset = load_capital_asset(conn, user["id"], asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    years = load_depreciation_schedule(conn, user["id"], asset_id)
    return {
        "asset_id": asset_id,
        "description": asset.description,
        "cost_basis_cents": asset.cost_basis_cents,
        "years": [
            {
                "year": y.year,
                "depreciation_cents": y.depreciation_cents,
                "accumulated_depreciation_cents": y.accumulated_depreciation_cents,
                "book_value_cents": y.book_value_cents,
            }
            for y in years
        ],
    }


# ============================================================================
# Deductions Endpoints
# ============================================================================


@router.get("/deductions/summary")
def get_deduction_summary(
    request: Request,
    start_date: date = Query(...),
    end_date: date = Query(...),
    category: str | None = Query(None),
    user: dict[str, Any] = Depends(lambda req: {"id": 1}),
) -> dict[str, Any]:
    """Get deduction summary for a period.

    GET /tax-optimization/deductions/summary?start_date=2026-01-01&end_date=2026-12-31
    """
    conn = request.app.state.db
    aggregates = load_deduction_aggregate(conn, user["id"], start_date, end_date, category)

    total_amount = sum(a["total_amount_cents"] for a in aggregates)
    total_deductible = sum(a["total_deductible_cents"] for a in aggregates)
    deduction_rate = (total_deductible / total_amount * 100) if total_amount > 0 else 0

    return {
        "period_start": start_date.isoformat(),
        "period_end": end_date.isoformat(),
        "total_amount_cents": total_amount,
        "total_deductible_cents": total_deductible,
        "deduction_rate_percent": deduction_rate,
        "count": sum(a["expense_count"] for a in aggregates),
        "by_category": aggregates,
    }


@router.get("/deductions/breaks")
def get_tax_breaks(
    request: Request,
    start_date: date = Query(...),
    end_date: date = Query(...),
    user: dict[str, Any] = Depends(lambda req: {"id": 1}),
) -> dict[str, Any]:
    """Get identified tax break opportunities.

    GET /tax-optimization/deductions/breaks?start_date=2026-01-01&end_date=2026-12-31
    """
    conn = request.app.state.db
    opportunities = load_tax_break_opportunities(conn, user["id"], status="available")
    return {
        "period_start": start_date.isoformat(),
        "period_end": end_date.isoformat(),
        "opportunities": opportunities,
        "total_potential_savings_cents": sum(o["tax_savings_cents"] for o in opportunities),
    }


# ============================================================================
# Estimated Tax Endpoints
# ============================================================================


@router.post("/estimated-tax/quarterly")
def calculate_quarterly_estimate(
    request: Request,
    input_data: EstimatedTaxInput,
    user: dict[str, Any] = Depends(lambda req: {"id": 1}),
) -> dict[str, Any]:
    """Calculate quarterly estimated tax payment.

    POST /tax-optimization/estimated-tax/quarterly
    """
    try:
        # Calculate for full year first
        filing_status_enum = FilingStatus(input_data.filing_status.lower())

        # Use empty tax brackets for demo (caller should provide current year brackets)
        tax_brackets = []

        projection = project_year_end_tax(
            gross_income_cents=input_data.projected_annual_income_cents,
            business_deductions_cents=input_data.projected_annual_deductions_cents,
            filing_status=filing_status_enum,
            tax_brackets=tax_brackets,
            standard_deduction_cents=0,
        )

        # Calculate quarterly estimate
        quarterly_tax = int(projection.total_tax_cents / 4)
        estimate = calculate_quarterly_estimate(
            year=input_data.year,
            quarter=input_data.quarter,
            projected_quarterly_tax_cents=quarterly_tax,
            prior_year_tax_cents=input_data.prior_year_tax_cents,
        )

        # Save to database
        conn = request.app.state.db
        save_estimated_tax_payment(conn, user["id"], estimate)

        return {
            "year": estimate.year,
            "quarter": estimate.quarter,
            "safe_harbor_90_current_year_cents": estimate.safe_harbor_90_current_year_cents,
            "safe_harbor_100_prior_year_cents": estimate.safe_harbor_100_prior_year_cents,
            "recommended_payment_cents": estimate.recommended_payment_cents,
            "due_date": estimate.due_date.isoformat(),
        }

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/estimated-tax/payments")
def get_estimated_tax_payments(
    request: Request,
    year: int = Query(...),
    user: dict[str, Any] = Depends(lambda req: {"id": 1}),
) -> dict[str, Any]:
    """Get estimated tax payments for a year.

    GET /tax-optimization/estimated-tax/payments?year=2026
    """
    conn = request.app.state.db
    payments = load_estimated_tax_payments_for_year(conn, user["id"], year)
    total_paid = sum(p["amount_cents"] for p in payments)
    return {
        "year": year,
        "payments": payments,
        "total_paid_cents": total_paid,
        "count": len(payments),
    }


# ============================================================================
# Recommendations Endpoint
# ============================================================================


@router.get("/recommendations")
def get_tax_recommendations(
    request: Request,
    priority: str | None = Query(None),
    user: dict[str, Any] = Depends(lambda req: {"id": 1}),
) -> dict[str, Any]:
    """Get tax recommendations for the user.

    GET /tax-optimization/recommendations?priority=high
    """
    # Generate recommendations based on user activity
    deduction_recs = generate_deduction_recommendations(
        actual_deductions_cents=100000 * 100,  # TODO: Load from database
        potential_deductions_cents=125000 * 100,
        marginal_tax_rate=0.24,
    )

    compliance_recs = generate_compliance_recommendations(
        has_quarterly_payments=True,
        has_estimated_tax=True,
        has_self_employment_income=True,
        has_home_office=False,
        has_vehicle_expenses=False,
    )

    optimization_recs = generate_optimization_recommendations(
        business_income_cents=50000 * 100,
        current_deductions_cents=10000 * 100,
    )

    all_recs = deduction_recs + compliance_recs + optimization_recs
    sorted_recs = prioritize_recommendations(all_recs)

    # Filter by priority if specified
    if priority:
        sorted_recs = [r for r in sorted_recs if r.priority.value == priority.lower()]

    return {
        "recommendations": [
            {
                "id": r.recommendation_id,
                "type": r.recommendation_type.value,
                "priority": r.priority.value,
                "title": r.title,
                "description": r.description,
                "estimated_tax_impact_cents": r.estimated_tax_impact_cents,
                "next_steps": r.next_steps,
            }
            for r in sorted_recs
        ],
        "total_count": len(sorted_recs),
        "potential_tax_savings_cents": sum(
            r.estimated_tax_impact_cents for r in sorted_recs
        ),
    }


@router.get("/health")
def tax_optimization_health() -> dict[str, str]:
    """Health check for tax optimization module.

    GET /tax-optimization/health
    """
    return {
        "status": "healthy",
        "module": "tax-optimization",
        "version": "1.0.0",
    }
