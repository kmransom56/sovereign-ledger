"""Integration test for Sovereign Ledger SurrealDB Tax Optimization Adapter."""

from datetime import date
from db.surreal_session import get_surreal_client
from ledger.capital_assets import AssetType, CapitalAsset, DepreciationMethod
from app.adapters.tax_optimization_surreal import (
    save_capital_asset,
    load_capital_asset,
    calculate_and_save_depreciation_schedule,
    load_depreciation_schedule,
    save_tax_break_opportunity,
    load_tax_break_opportunities,
)
from ledger.deductions import TaxBreakOpportunity


def test_surreal_tax_optimization():
    client = get_surreal_client()
    assert client.ping() is True
    user_id = 1

    # 1. Capital Asset
    asset = CapitalAsset(
        asset_id=1,
        description="MacBook Pro M3 Max for Sovereign Development",
        asset_type=AssetType.COMPUTER_EQUIPMENT,
        cost_basis_cents=399900,
        useful_life_years=5,
        date_placed_in_service=date(2026, 1, 15),
        depreciation_method=DepreciationMethod.MACRS_200DB,
    )
    asset_id = save_capital_asset(client, user_id, asset)
    assert asset_id is not None

    loaded = load_capital_asset(client, user_id, asset_id)
    assert loaded is not None
    assert loaded.description == "MacBook Pro M3 Max for Sovereign Development"
    assert loaded.cost_basis_cents == 399900

    # 2. Depreciation Schedule
    sched = calculate_and_save_depreciation_schedule(client, user_id, asset_id)
    assert len(sched.years) > 0

    loaded_sched_years = load_depreciation_schedule(client, user_id, asset_id)
    assert len(loaded_sched_years) == len(sched.years)

    # 3. Tax Break Opportunities
    opp = TaxBreakOpportunity(
        opportunity_type="home_office",
        description="Home Office Simplified Deduction for Sovereign Edge Datacenter",
        current_deduction_cents=0,
        potential_deduction_cents=150000,
        tax_savings_cents=36000,
        estimated_marginal_rate=0.24,
        applicable_periods=[date(2026, 1, 1), date(2026, 12, 31)],
        status="available",
    )
    save_tax_break_opportunity(client, user_id, opp)
    opps = load_tax_break_opportunities(client, user_id)
    assert len(opps) >= 1
    found = any(o.get("opportunity_type") == "home_office" for o in opps)
    assert found is True
    print("✅ All SurrealDB tax optimization tests passed successfully!")


if __name__ == "__main__":
    test_surreal_tax_optimization()
