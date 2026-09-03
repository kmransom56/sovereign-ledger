"""SurrealDB Adapter for Tax Optimization (Step 13, Phase 7).

Persists domain models (ledger/) to SurrealDB (sovereign.ledger).
Replaces legacy PostgreSQL psycopg calls with native SurrealDB queries.

Zero external dependencies; uses db.surreal_session.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Optional

from db.surreal_session import SurrealDBClient, get_surreal_client
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
    "load_deduction_aggregates_for_period",
    "save_estimated_tax_payment",
    "load_estimated_tax_payments_for_year",
    "save_tax_break_opportunity",
    "load_tax_break_opportunities",
    "save_deduction_audit_trail",
]


def _ensure_client(client: Any) -> SurrealDBClient:
    if isinstance(client, SurrealDBClient):
        return client
    return get_surreal_client()


def _format_dt(d: Any) -> str:
    if isinstance(d, datetime):
        return d.isoformat()
    if isinstance(d, date):
        return f"{d.isoformat()}T00:00:00Z"
    return str(d)


# ============================================================================
# Capital Assets
# ============================================================================


def save_capital_asset(
    client: Any,
    user_id: int,
    asset: CapitalAsset,
) -> int:
    """Save a capital asset to SurrealDB and return its integer ID."""
    c = _ensure_client(client)
    data = {
        "user_id": f"users:{user_id}",
        "description": asset.description,
        "asset_type": asset.asset_type,
        "cost_basis_cents": asset.cost_basis_cents,
        "salvage_value_cents": asset.salvage_value_cents,
        "useful_life_years": asset.useful_life_years,
        "depreciation_method": asset.depreciation_method.value,
        "date_placed_in_service": _format_dt(asset.date_placed_in_service),
        "vendor_name": asset.vendor_name,
        "invoice_date": _format_dt(asset.invoice_date) if asset.invoice_date else None,
        "invoice_number": asset.invoice_number,
        "notes": asset.notes,
        "created_at": datetime.utcnow().isoformat() + "Z",
        "updated_at": datetime.utcnow().isoformat() + "Z",
    }
    rec = c.create("capital_assets", None, data)
    rec_id = rec.get("id", "")
    # SurrealDB IDs are formatted table:key; extract numeric key or hash
    raw_id = rec_id.split(":")[-1] if ":" in str(rec_id) else str(rec_id)
    try:
        return int(raw_id)
    except ValueError:
        return abs(hash(raw_id)) % (10**9)


def load_capital_asset(
    client: Any,
    user_id: int,
    asset_id: Any,
) -> Optional[CapitalAsset]:
    """Load a capital asset from SurrealDB."""
    c = _ensure_client(client)
    target = f"capital_assets:{asset_id}" if ":" not in str(asset_id) else str(asset_id)
    sql = f"SELECT * FROM {target} WHERE user_id = users:{user_id};"
    res = c.query(sql)
    rows = res[0].get("result", [])
    if not rows:
        return None
    r = rows[0]
    p_date = r["date_placed_in_service"]
    if isinstance(p_date, str):
        placed_date = datetime.fromisoformat(p_date.replace("Z", "+00:00")).date()
    else:
        placed_date = p_date

    inv_date = None
    if r.get("invoice_date"):
        if isinstance(r["invoice_date"], str):
            inv_date = datetime.fromisoformat(r["invoice_date"].replace("Z", "+00:00")).date()
        else:
            inv_date = r["invoice_date"]

    return CapitalAsset(
        description=r["description"],
        asset_type=r["asset_type"],
        cost_basis_cents=r["cost_basis_cents"],
        useful_life_years=r["useful_life_years"],
        date_placed_in_service=placed_date,
        salvage_value_cents=r.get("salvage_value_cents", 0),
        depreciation_method=DepreciationMethod(r["depreciation_method"]),
        vendor_name=r.get("vendor_name"),
        invoice_date=inv_date,
        invoice_number=r.get("invoice_number"),
        notes=r.get("notes"),
    )


def load_capital_assets_for_user(
    client: Any,
    user_id: int,
) -> List[CapitalAsset]:
    """Load all capital assets for a user."""
    c = _ensure_client(client)
    sql = f"SELECT * FROM capital_assets WHERE user_id = users:{user_id};"
    res = c.query(sql)
    rows = res[0].get("result", [])
    assets = []
    for r in rows:
        p_date = r["date_placed_in_service"]
        placed_date = datetime.fromisoformat(p_date.replace("Z", "+00:00")).date() if isinstance(p_date, str) else p_date
        inv_date = None
        if r.get("invoice_date"):
            inv_date = datetime.fromisoformat(r["invoice_date"].replace("Z", "+00:00")).date() if isinstance(r["invoice_date"], str) else r["invoice_date"]
        assets.append(
            CapitalAsset(
                description=r["description"],
                asset_type=r["asset_type"],
                cost_basis_cents=r["cost_basis_cents"],
                useful_life_years=r["useful_life_years"],
                date_placed_in_service=placed_date,
                salvage_value_cents=r.get("salvage_value_cents", 0),
                depreciation_method=DepreciationMethod(r["depreciation_method"]),
                vendor_name=r.get("vendor_name"),
                invoice_date=inv_date,
                invoice_number=r.get("invoice_number"),
                notes=r.get("notes"),
            )
        )
    return assets


# ============================================================================
# Depreciation Schedules
# ============================================================================


def calculate_and_save_depreciation_schedule(
    client: Any,
    user_id: int,
    asset_id: Any,
) -> DepreciationSchedule:
    """Calculate and persist depreciation schedule in SurrealDB."""
    c = _ensure_client(client)
    asset = load_capital_asset(c, user_id, asset_id)
    if not asset:
        raise ValueError(f"Asset {asset_id} not found for user {user_id}")

    schedule = create_depreciation_schedule(asset)
    target_asset = f"capital_assets:{asset_id}" if ":" not in str(asset_id) else str(asset_id)

    # Delete existing schedule for this asset
    c.query(f"DELETE depreciation_schedules WHERE asset_id = {target_asset} AND user_id = users:{user_id};")

    for year in schedule.years:
        c.create(
            "depreciation_schedules",
            None,
            {
                "user_id": f"users:{user_id}",
                "asset_id": target_asset,
                "depreciation_year": year.year,
                "depreciation_cents": year.depreciation_cents,
                "accumulated_depreciation_cents": year.accumulated_depreciation_cents,
                "book_value_cents": year.book_value_cents,
                "created_at": datetime.utcnow().isoformat() + "Z",
            },
        )
    return schedule


def load_depreciation_schedule(
    client: Any,
    user_id: int,
    asset_id: Any,
) -> Optional[DepreciationSchedule]:
    """Load depreciation schedule for an asset from SurrealDB."""
    c = _ensure_client(client)
    asset = load_capital_asset(c, user_id, asset_id)
    if not asset:
        return None

    target_asset = f"capital_assets:{asset_id}" if ":" not in str(asset_id) else str(asset_id)
    sql = f"SELECT * FROM depreciation_schedules WHERE asset_id = {target_asset} AND user_id = users:{user_id} ORDER BY depreciation_year ASC;"
    res = c.query(sql)
    rows = res[0].get("result", [])
    if not rows:
        return None

    years = [
        DepreciationYear(
            year=r["depreciation_year"],
            depreciation_cents=r["depreciation_cents"],
            accumulated_depreciation_cents=r["accumulated_depreciation_cents"],
            book_value_cents=r["book_value_cents"],
        )
        for r in rows
    ]
    return DepreciationSchedule(asset=asset, years=years)


# ============================================================================
# Deductions & Aggregates
# ============================================================================


def save_deduction_aggregate(
    client: Any,
    user_id: int,
    summary: DeductionSummary,
) -> int:
    """Save or update a deduction summary aggregate in SurrealDB."""
    c = _ensure_client(client)
    p_start = _format_dt(summary.period_start)
    p_end = _format_dt(summary.period_end)
    cat = summary.category.value if hasattr(summary.category, "value") else str(summary.category)

    sql = f"""
    UPSERT deduction_aggregates SET
        user_id = users:{user_id},
        period_start = '{p_start}',
        period_end = '{p_end}',
        deduction_category = '{cat}',
        total_amount_cents = {summary.total_cents},
        total_deductible_cents = {summary.deductible_cents},
        average_business_use_percent = {summary.business_use_percentage},
        expense_count = {summary.transaction_count},
        updated_at = time::now()
    WHERE user_id = users:{user_id} AND period_start = '{p_start}' AND period_end = '{p_end}' AND deduction_category = '{cat}';
    """
    res = c.query(sql)
    return 1


def load_deduction_aggregates_for_period(
    client: Any,
    user_id: int,
    period_start: date,
    period_end: date,
) -> List[DeductionSummary]:
    """Load deduction aggregates for a user and period range."""
    c = _ensure_client(client)
    p_start = _format_dt(period_start)
    p_end = _format_dt(period_end)
    sql = f"""
    SELECT * FROM deduction_aggregates
    WHERE user_id = users:{user_id} AND period_start >= '{p_start}' AND period_end <= '{p_end}';
    """
    res = c.query(sql)
    rows = res[0].get("result", [])
    summaries = []
    for r in rows:
        ps = datetime.fromisoformat(r["period_start"].replace("Z", "+00:00")).date() if isinstance(r["period_start"], str) else r["period_start"]
        pe = datetime.fromisoformat(r["period_end"].replace("Z", "+00:00")).date() if isinstance(r["period_end"], str) else r["period_end"]
        summaries.append(
            DeductionSummary(
                category=DeductionCategory(r["deduction_category"]),
                period_start=ps,
                period_end=pe,
                total_cents=r["total_amount_cents"],
                deductible_cents=r["total_deductible_cents"],
                business_use_percentage=r["average_business_use_percent"],
                transaction_count=r["expense_count"],
            )
        )
    return summaries


# ============================================================================
# Estimated Tax Payments
# ============================================================================


def save_estimated_tax_payment(
    client: Any,
    user_id: int,
    estimate: QuarterlyTaxEstimate,
) -> int:
    """Save estimated quarterly tax payment in SurrealDB."""
    c = _ensure_client(client)
    p_date = _format_dt(estimate.due_date)
    method = estimate.safe_harbor_method if hasattr(estimate, "safe_harbor_method") else None
    data = {
        "user_id": f"users:{user_id}",
        "tax_year": estimate.tax_year,
        "quarter": estimate.quarter,
        "payment_date": p_date,
        "amount_cents": estimate.total_estimated_tax_cents,
        "safe_harbor_method": method,
        "created_at": datetime.utcnow().isoformat() + "Z",
    }
    c.create("estimated_tax_payments", None, data)
    return 1


def load_estimated_tax_payments_for_year(
    client: Any,
    user_id: int,
    tax_year: int,
) -> List[Dict[str, Any]]:
    """Load estimated tax payments for a tax year from SurrealDB."""
    c = _ensure_client(client)
    sql = f"SELECT * FROM estimated_tax_payments WHERE user_id = users:{user_id} AND tax_year = {tax_year} ORDER BY quarter ASC;"
    res = c.query(sql)
    return res[0].get("result", [])


# ============================================================================
# Tax Break Opportunities & Audit Trail
# ============================================================================


def save_tax_break_opportunity(
    client: Any,
    user_id: int,
    opp: TaxBreakOpportunity,
) -> int:
    """Save identified tax break opportunity in SurrealDB."""
    c = _ensure_client(client)
    data = {
        "user_id": f"users:{user_id}",
        "opportunity_type": opp.opportunity_type,
        "description": opp.description,
        "current_deduction_cents": opp.current_deduction_cents,
        "potential_deduction_cents": opp.potential_deduction_cents,
        "tax_savings_cents": opp.tax_savings_cents,
        "estimated_marginal_rate": opp.estimated_marginal_rate,
        "status": opp.status,
        "implementation_difficulty": getattr(opp, "implementation_difficulty", "medium"),
        "created_at": datetime.utcnow().isoformat() + "Z",
        "updated_at": datetime.utcnow().isoformat() + "Z",
    }
    c.create("tax_break_opportunities", None, data)
    return 1


def load_tax_break_opportunities(
    client: Any,
    user_id: int,
    status: Optional[str] = None,
) -> List[TaxBreakOpportunity]:
    """Load tax break opportunities from SurrealDB."""
    c = _ensure_client(client)
    where_status = f"AND status = '{status}'" if status else ""
    sql = f"SELECT * FROM tax_break_opportunities WHERE user_id = users:{user_id} {where_status};"
    res = c.query(sql)
    rows = res[0].get("result", [])
    return [
        TaxBreakOpportunity(
            opportunity_type=r["opportunity_type"],
            description=r["description"],
            current_deduction_cents=r["current_deduction_cents"],
            potential_deduction_cents=r["potential_deduction_cents"],
            tax_savings_cents=r["tax_savings_cents"],
            estimated_marginal_rate=r.get("estimated_marginal_rate", 0.24),
            status=r.get("status", "available"),
        )
        for r in rows
    ]


def save_deduction_audit_trail(
    client: Any,
    user_id: int,
    bill_id: Optional[int],
    deduction_category: str,
    transaction_date: date,
    amount_cents: int,
    deductible_amount_cents: int,
    business_use_percent: int,
    deduction_type: str = "ordinary",
    limitation_type: str = "none",
    notes: Optional[str] = None,
) -> int:
    """Record immutable deduction calculation in audit trail."""
    c = _ensure_client(client)
    data = {
        "user_id": f"users:{user_id}",
        "bill_id": f"bills:{bill_id}" if bill_id else None,
        "deduction_category": deduction_category,
        "transaction_date": _format_dt(transaction_date),
        "amount_cents": amount_cents,
        "deductible_amount_cents": deductible_amount_cents,
        "business_use_percent": business_use_percent,
        "deduction_type": deduction_type,
        "limitation_type": limitation_type,
        "notes": notes,
        "created_at": datetime.utcnow().isoformat() + "Z",
    }
    c.create("deduction_audit_trail", None, data)
    return 1
