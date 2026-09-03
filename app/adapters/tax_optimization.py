"""Adapter layer for tax optimization persistence (Step 13, Phase 3).

Bridges domain models (ledger/) to database schema (db/migrations/0007_tax_optimization.sql).
Handles CRUD operations for capital assets, depreciation schedules, deductions,
estimated tax payments, and tax break opportunities.

Locked: Follows CK-5/CK-6 validation before persistence; D-3 cents; HR-1 append-only.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from ledger.capital_assets import (
    CapitalAsset,
    DepreciationMethod,
    DepreciationSchedule,
    DepreciationYear,
    create_depreciation_schedule,
)
from ledger.deductions import (
    DeductionCategory,
    DeductibleExpense,
    DeductionSummary,
    TaxBreakOpportunity,
)
from ledger.tax_projections import QuarterlyTaxEstimate

__all__ = [
    "save_capital_asset",
    "load_capital_asset",
    "load_capital_assets_for_user",
    "calculate_and_save_depreciation_schedule",
    "load_depreciation_schedule",
    "save_deduction_aggregate",
    "load_deduction_aggregate",
    "load_deduction_aggregates_for_period",
    "save_estimated_tax_payment",
    "load_estimated_tax_payments_for_year",
    "load_tax_form_mappings",
    "save_tax_break_opportunity",
    "load_tax_break_opportunities",
    "save_deduction_audit_trail",
]


# ============================================================================
# Capital Assets
# ============================================================================


def save_capital_asset(
    conn: Any,
    user_id: int,
    asset: CapitalAsset,
) -> int:
    """Save a capital asset and return its ID.

    Creates a new capital asset record in capital_assets table.
    Returns the generated asset_id.
    """
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO capital_assets (
                user_id, description, asset_type, cost_basis_cents,
                salvage_value_cents, useful_life_years, depreciation_method,
                date_placed_in_service, vendor_name, invoice_date, invoice_number, notes
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                user_id,
                asset.description,
                asset.asset_type.value,
                asset.cost_basis_cents,
                asset.salvage_value_cents,
                asset.useful_life_years,
                asset.depreciation_method.value,
                asset.date_placed_in_service,
                asset.vendor_name,
                asset.invoice_date,
                asset.invoice_number,
                asset.notes,
            ),
        )
        result = cursor.fetchone()
        return result[0] if result else 0


def load_capital_asset(
    conn: Any,
    user_id: int,
    asset_id: int,
) -> CapitalAsset | None:
    """Load a capital asset by ID."""
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT id, description, asset_type, cost_basis_cents,
                   salvage_value_cents, useful_life_years, depreciation_method,
                   date_placed_in_service, vendor_name, invoice_date,
                   invoice_number, notes
            FROM capital_assets
            WHERE id = %s AND user_id = %s
            """,
            (asset_id, user_id),
        )
        row = cursor.fetchone()
        if not row:
            return None

        return CapitalAsset(
            asset_id=row[0],
            description=row[1],
            asset_type=row[2],
            cost_basis_cents=row[3],
            salvage_value_cents=row[4],
            useful_life_years=row[5],
            depreciation_method=DepreciationMethod(row[6]),
            date_placed_in_service=row[7],
            vendor_name=row[8],
            invoice_date=row[9],
            invoice_number=row[10],
            notes=row[11],
        )


def load_capital_assets_for_user(
    conn: Any,
    user_id: int,
    asset_type: str | None = None,
) -> list[dict[str, Any]]:
    """Load all capital assets for a user, optionally filtered by type."""
    with conn.cursor() as cursor:
        if asset_type:
            cursor.execute(
                """
                SELECT id, description, asset_type, cost_basis_cents,
                       salvage_value_cents, useful_life_years, depreciation_method,
                       date_placed_in_service, vendor_name
                FROM capital_assets
                WHERE user_id = %s AND asset_type = %s
                ORDER BY date_placed_in_service DESC
                """,
                (user_id, asset_type),
            )
        else:
            cursor.execute(
                """
                SELECT id, description, asset_type, cost_basis_cents,
                       salvage_value_cents, useful_life_years, depreciation_method,
                       date_placed_in_service, vendor_name
                FROM capital_assets
                WHERE user_id = %s
                ORDER BY date_placed_in_service DESC
                """,
                (user_id,),
            )

        rows = cursor.fetchall()
        return [
            {
                "id": row[0],
                "description": row[1],
                "asset_type": row[2],
                "cost_basis_cents": row[3],
                "salvage_value_cents": row[4],
                "useful_life_years": row[5],
                "depreciation_method": row[6],
                "date_placed_in_service": row[7],
                "vendor_name": row[8],
            }
            for row in rows
        ]


def calculate_and_save_depreciation_schedule(
    conn: Any,
    user_id: int,
    asset_id: int,
    asset: CapitalAsset,
) -> DepreciationSchedule:
    """Calculate depreciation schedule and save year-by-year records."""
    # Calculate using domain logic
    schedule = create_depreciation_schedule(
        asset_id=asset_id,
        description=asset.description,
        cost_basis_cents=asset.cost_basis_cents,
        salvage_value_cents=asset.salvage_value_cents,
        depreciation_method=asset.depreciation_method,
        date_placed_in_service=asset.date_placed_in_service,
        recovery_period_years=asset.useful_life_years,
    )

    # Persist each year's depreciation
    with conn.cursor() as cursor:
        for year_record in schedule.years:
            cursor.execute(
                """
                INSERT INTO depreciation_schedules (
                    user_id, asset_id, depreciation_year,
                    depreciation_cents, accumulated_depreciation_cents,
                    book_value_cents
                ) VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (asset_id, depreciation_year) DO UPDATE
                SET depreciation_cents = EXCLUDED.depreciation_cents,
                    accumulated_depreciation_cents = EXCLUDED.accumulated_depreciation_cents,
                    book_value_cents = EXCLUDED.book_value_cents,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    user_id,
                    asset_id,
                    year_record.year,
                    year_record.depreciation_cents,
                    year_record.accumulated_depreciation_cents,
                    year_record.book_value_cents,
                ),
            )
        conn.commit()

    return schedule


def load_depreciation_schedule(
    conn: Any,
    user_id: int,
    asset_id: int,
) -> list[DepreciationYear]:
    """Load all depreciation years for an asset."""
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT depreciation_year, depreciation_cents,
                   accumulated_depreciation_cents, book_value_cents
            FROM depreciation_schedules
            WHERE user_id = %s AND asset_id = %s
            ORDER BY depreciation_year
            """,
            (user_id, asset_id),
        )
        rows = cursor.fetchall()

        return [
            DepreciationYear(
                year=row[0],
                depreciation_cents=row[1],
                accumulated_depreciation_cents=row[2],
                book_value_cents=row[3],
            )
            for row in rows
        ]


# ============================================================================
# Deduction Aggregates
# ============================================================================


def save_deduction_aggregate(
    conn: Any,
    user_id: int,
    summary: DeductionSummary,
) -> None:
    """Save deduction summary to deduction_aggregates table."""
    with conn.cursor() as cursor:
        for category, cat_summary in summary.categories.items():
            cursor.execute(
                """
                INSERT INTO deduction_aggregates (
                    user_id, period_start, period_end,
                    deduction_category, total_amount_cents,
                    total_deductible_cents, average_business_use_percent,
                    expense_count
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (user_id, period_start, period_end, deduction_category)
                DO UPDATE SET
                    total_amount_cents = EXCLUDED.total_amount_cents,
                    total_deductible_cents = EXCLUDED.total_deductible_cents,
                    average_business_use_percent = EXCLUDED.average_business_use_percent,
                    expense_count = EXCLUDED.expense_count,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    user_id,
                    summary.start_date,
                    summary.end_date,
                    category.value,
                    cat_summary.total_amount_cents,
                    cat_summary.total_deductible_cents,
                    cat_summary.average_business_use_percent,
                    cat_summary.count,
                ),
            )
        conn.commit()


def load_deduction_aggregate(
    conn: Any,
    user_id: int,
    period_start: date,
    period_end: date,
    category: str | None = None,
) -> list[dict[str, Any]]:
    """Load deduction aggregates for a period, optionally filtered by category."""
    with conn.cursor() as cursor:
        if category:
            cursor.execute(
                """
                SELECT deduction_category, total_amount_cents,
                       total_deductible_cents, average_business_use_percent,
                       expense_count
                FROM deduction_aggregates
                WHERE user_id = %s AND period_start = %s AND period_end = %s
                  AND deduction_category = %s
                """,
                (user_id, period_start, period_end, category),
            )
        else:
            cursor.execute(
                """
                SELECT deduction_category, total_amount_cents,
                       total_deductible_cents, average_business_use_percent,
                       expense_count
                FROM deduction_aggregates
                WHERE user_id = %s AND period_start = %s AND period_end = %s
                ORDER BY deduction_category
                """,
                (user_id, period_start, period_end),
            )

        rows = cursor.fetchall()
        return [
            {
                "category": row[0],
                "total_amount_cents": row[1],
                "total_deductible_cents": row[2],
                "average_business_use_percent": row[3],
                "expense_count": row[4],
            }
            for row in rows
        ]


def load_deduction_aggregates_for_period(
    conn: Any,
    user_id: int,
    period_start: date,
    period_end: date,
) -> dict[str, int]:
    """Load total deductible amounts by category for period."""
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT SUM(total_deductible_cents)
            FROM deduction_aggregates
            WHERE user_id = %s AND period_start <= %s AND period_end >= %s
            """,
            (user_id, period_end, period_start),
        )
        result = cursor.fetchone()
        return {"total_deductible_cents": result[0] or 0}


# ============================================================================
# Estimated Tax Payments
# ============================================================================


def save_estimated_tax_payment(
    conn: Any,
    user_id: int,
    estimate: QuarterlyTaxEstimate,
) -> int:
    """Save a quarterly estimated tax payment record."""
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO estimated_tax_payments (
                user_id, tax_year, quarter, payment_date, amount_cents,
                safe_harbor_method, notes
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                user_id,
                estimate.year,
                estimate.quarter,
                estimate.due_date,
                estimate.recommended_payment_cents,
                "90_current",  # Default safe harbor method
                f"Safe harbor: {estimate.safe_harbor_90_current_year_cents} (90%) vs "
                f"{estimate.safe_harbor_100_prior_year_cents} (100% prior)",
            ),
        )
        result = cursor.fetchone()
        conn.commit()
        return result[0] if result else 0


def load_estimated_tax_payments_for_year(
    conn: Any,
    user_id: int,
    tax_year: int,
) -> list[dict[str, Any]]:
    """Load all estimated tax payments for a tax year."""
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT id, quarter, payment_date, amount_cents, safe_harbor_method
            FROM estimated_tax_payments
            WHERE user_id = %s AND tax_year = %s
            ORDER BY quarter
            """,
            (user_id, tax_year),
        )

        rows = cursor.fetchall()
        return [
            {
                "id": row[0],
                "quarter": row[1],
                "payment_date": row[2],
                "amount_cents": row[3],
                "safe_harbor_method": row[4],
            }
            for row in rows
        ]


# ============================================================================
# Tax Form Mappings
# ============================================================================


def load_tax_form_mappings(
    conn: Any,
    user_id: int,
    tax_form: str | None = None,
) -> list[dict[str, Any]]:
    """Load tax form mappings for user, optionally filtered by form."""
    with conn.cursor() as cursor:
        if tax_form:
            cursor.execute(
                """
                SELECT tax_form, form_line, form_line_description,
                       deduction_category, account_id, percentage_allocation
                FROM tax_form_mappings
                WHERE user_id = %s AND tax_form = %s
                ORDER BY form_line
                """,
                (user_id, tax_form),
            )
        else:
            cursor.execute(
                """
                SELECT tax_form, form_line, form_line_description,
                       deduction_category, account_id, percentage_allocation
                FROM tax_form_mappings
                WHERE user_id = %s
                ORDER BY tax_form, form_line
                """,
                (user_id,),
            )

        rows = cursor.fetchall()
        return [
            {
                "tax_form": row[0],
                "form_line": row[1],
                "form_line_description": row[2],
                "deduction_category": row[3],
                "account_id": row[4],
                "percentage_allocation": row[5],
            }
            for row in rows
        ]


# ============================================================================
# Tax Break Opportunities
# ============================================================================


def save_tax_break_opportunity(
    conn: Any,
    user_id: int,
    opportunity: TaxBreakOpportunity,
) -> int:
    """Save a tax break opportunity."""
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO tax_break_opportunities (
                user_id, opportunity_type, description,
                current_deduction_cents, potential_deduction_cents,
                tax_savings_cents, estimated_marginal_rate, status,
                applicable_from, applicable_until, implementation_difficulty,
                requirements, notes
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                user_id,
                opportunity.opportunity_type,
                opportunity.description,
                opportunity.current_deduction_cents,
                opportunity.potential_deduction_cents,
                opportunity.tax_savings_cents,
                opportunity.estimated_marginal_rate,
                opportunity.status,
                opportunity.applicable_periods[0] if opportunity.applicable_periods else None,
                opportunity.applicable_periods[-1] if opportunity.applicable_periods else None,
                opportunity.opportunity_type,
                ",".join(opportunity.requirements) if opportunity.requirements else None,
                opportunity.notes,
            ),
        )
        result = cursor.fetchone()
        conn.commit()
        return result[0] if result else 0


def load_tax_break_opportunities(
    conn: Any,
    user_id: int,
    status: str | None = None,
) -> list[dict[str, Any]]:
    """Load tax break opportunities for user, optionally filtered by status."""
    with conn.cursor() as cursor:
        if status:
            cursor.execute(
                """
                SELECT id, opportunity_type, description,
                       current_deduction_cents, potential_deduction_cents,
                       tax_savings_cents, estimated_marginal_rate, status,
                       applicable_from, applicable_until
                FROM tax_break_opportunities
                WHERE user_id = %s AND status = %s
                ORDER BY tax_savings_cents DESC
                """,
                (user_id, status),
            )
        else:
            cursor.execute(
                """
                SELECT id, opportunity_type, description,
                       current_deduction_cents, potential_deduction_cents,
                       tax_savings_cents, estimated_marginal_rate, status,
                       applicable_from, applicable_until
                FROM tax_break_opportunities
                WHERE user_id = %s
                ORDER BY status, tax_savings_cents DESC
                """,
                (user_id,),
            )

        rows = cursor.fetchall()
        return [
            {
                "id": row[0],
                "opportunity_type": row[1],
                "description": row[2],
                "current_deduction_cents": row[3],
                "potential_deduction_cents": row[4],
                "tax_savings_cents": row[5],
                "estimated_marginal_rate": row[6],
                "status": row[7],
                "applicable_from": row[8],
                "applicable_until": row[9],
            }
            for row in rows
        ]


# ============================================================================
# Deduction Audit Trail
# ============================================================================


def save_deduction_audit_trail(
    conn: Any,
    user_id: int,
    bill_id: int,
    category: str,
    transaction_date: date,
    amount_cents: int,
    deductible_amount_cents: int,
    business_use_percent: int,
    deduction_type: str = "ordinary",
    limitation_type: str = "none",
    notes: str | None = None,
) -> None:
    """Save a deduction to the immutable audit trail."""
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO deduction_audit_trail (
                user_id, bill_id, deduction_category, transaction_date,
                amount_cents, deductible_amount_cents, business_use_percent,
                deduction_type, limitation_type, notes
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                user_id,
                bill_id,
                category,
                transaction_date,
                amount_cents,
                deductible_amount_cents,
                business_use_percent,
                deduction_type,
                limitation_type,
                notes,
            ),
        )
        conn.commit()
