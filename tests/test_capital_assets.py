"""Tests for capital asset depreciation calculations (Step 13, Phase 5).

Tests core depreciation logic: MACRS calculations with IRS tables,
straight-line depreciation, Section 179 expensing, bonus depreciation,
and complete depreciation schedule generation.
"""

from datetime import date

import pytest

from ledger.capital_assets import (
    AssetError,
    AssetType,
    CapitalAsset,
    DepreciationMethod,
    DepreciationSchedule,
    DepreciationYear,
    calculate_bonus_depreciation,
    calculate_macrs_depreciation,
    calculate_section_179_deduction,
    calculate_straight_line_depreciation,
    create_depreciation_schedule,
)


class TestCapitalAsset:
    """Test capital asset creation and validation."""

    def test_valid_asset_creation(self):
        """Create valid capital asset."""
        asset = CapitalAsset(
            asset_id=1,
            description="Dell Laptop",
            asset_type=AssetType.COMPUTER_EQUIPMENT,
            cost_basis_cents=150000,  # $1,500
            salvage_value_cents=0,
            date_placed_in_service=date(2024, 6, 1),
            useful_life_years=5,
            depreciation_method=DepreciationMethod.MACRS_200DB,
        )

        assert asset.asset_id == 1
        assert asset.description == "Dell Laptop"
        assert asset.asset_type == AssetType.COMPUTER_EQUIPMENT
        assert asset.cost_basis_cents == 150000
        assert asset.depreciable_basis() == 150000

    def test_asset_with_salvage_value(self):
        """Asset with salvage value calculates depreciable basis correctly."""
        asset = CapitalAsset(
            asset_id=2,
            description="Used Machine",
            asset_type=AssetType.MACHINERY_EQUIPMENT,
            cost_basis_cents=500000,  # $5,000
            salvage_value_cents=50000,  # $500
            useful_life_years=7,
            depreciation_method=DepreciationMethod.STRAIGHT_LINE,
        )

        assert asset.depreciable_basis() == 450000

    def test_empty_description_raises_error(self):
        """Empty description raises error."""
        with pytest.raises(AssetError):
            CapitalAsset(
                asset_id=1,
                description="",
                asset_type=AssetType.COMPUTER_EQUIPMENT,
                cost_basis_cents=100000,
            )

    def test_zero_cost_basis_raises_error(self):
        """Zero or negative cost basis raises error."""
        with pytest.raises(AssetError):
            CapitalAsset(
                asset_id=1,
                description="Asset",
                asset_type=AssetType.COMPUTER_EQUIPMENT,
                cost_basis_cents=0,
            )

    def test_negative_salvage_value_raises_error(self):
        """Negative salvage value raises error."""
        with pytest.raises(AssetError):
            CapitalAsset(
                asset_id=1,
                description="Asset",
                asset_type=AssetType.COMPUTER_EQUIPMENT,
                cost_basis_cents=100000,
                salvage_value_cents=-10000,
            )

    def test_salvage_exceeds_cost_raises_error(self):
        """Salvage value >= cost basis raises error."""
        with pytest.raises(AssetError):
            CapitalAsset(
                asset_id=1,
                description="Asset",
                asset_type=AssetType.COMPUTER_EQUIPMENT,
                cost_basis_cents=100000,
                salvage_value_cents=100000,
            )


class TestCalculateMacrsDepreciation:
    """Test MACRS (Modified Accelerated Cost Recovery System) depreciation."""

    def test_5_year_property_year_1(self):
        """5-year property Year 1 depreciation (20% rate)."""
        # 5-year property uses 20% in year 1
        depreciation = calculate_macrs_depreciation(
            cost_basis_cents=100000,
            recovery_period_years=5,
            year_number=1,
        )

        expected = int(100000 * 0.20)
        assert depreciation == expected

    def test_5_year_property_year_2(self):
        """5-year property Year 2 depreciation (32% rate)."""
        depreciation = calculate_macrs_depreciation(
            cost_basis_cents=100000,
            recovery_period_years=5,
            year_number=2,
        )

        expected = int(100000 * 0.32)
        assert depreciation == expected

    def test_7_year_property_full_schedule(self):
        """7-year property year-by-year depreciation rates."""
        # Expected rates for 7-year property: 14.29%, 24.49%, 17.49%, 12.49%, 8.93%, 8.92%, 8.93%, 4.46%
        expected_rates = [0.1429, 0.2449, 0.1749, 0.1249, 0.0893, 0.0892, 0.0893, 0.0446]

        for year_num, expected_rate in enumerate(expected_rates, start=1):
            depreciation = calculate_macrs_depreciation(
                cost_basis_cents=100000,
                recovery_period_years=7,
                year_number=year_num,
            )

            expected = int(100000 * expected_rate)
            assert depreciation == expected

    def test_27_5_year_residential_property(self):
        """27.5-year residential property (straight-line equivalent)."""
        # Straight-line rate for residential: 1/27.5 per year
        depreciation = calculate_macrs_depreciation(
            cost_basis_cents=1000000,
            recovery_period_years=27.5,  # Residential property recovery period
            year_number=1,
        )

        # Should be roughly 1000000 / 27.5 / 2 = 18,182 (half-year convention)
        assert depreciation > 17000
        assert depreciation < 19000

    def test_year_beyond_recovery_period(self):
        """Year beyond recovery period returns 0."""
        depreciation = calculate_macrs_depreciation(
            cost_basis_cents=100000,
            recovery_period_years=5,
            year_number=10,  # Beyond 5-year period
        )

        assert depreciation == 0

    def test_invalid_recovery_period_defaults_to_7(self):
        """Invalid recovery period defaults to 7-year rates."""
        depreciation = calculate_macrs_depreciation(
            cost_basis_cents=100000,
            recovery_period_years=8,  # Not standard
            year_number=1,
        )

        # Should use 7-year rates (first year = 14.29%)
        expected = int(100000 * 0.1429)
        assert depreciation == expected

    def test_zero_cost_raises_error(self):
        """Zero cost basis raises error."""
        with pytest.raises(AssetError):
            calculate_macrs_depreciation(
                cost_basis_cents=0,
                recovery_period_years=5,
                year_number=1,
            )

    def test_negative_year_number_raises_error(self):
        """Negative year number raises error."""
        with pytest.raises(AssetError):
            calculate_macrs_depreciation(
                cost_basis_cents=100000,
                recovery_period_years=5,
                year_number=0,
            )


class TestCalculateStraightLineDepreciation:
    """Test straight-line depreciation calculation."""

    def test_basic_straight_line(self):
        """Basic straight-line: (cost - salvage) / useful life."""
        # Cost $10,000, salvage $1,000, life 5 years = $1,800/year
        depreciation = calculate_straight_line_depreciation(
            cost_basis_cents=1000000,  # $10,000
            salvage_value_cents=100000,  # $1,000
            useful_life_years=5,
            year_number=1,
            half_year_convention=False,  # Disable half-year for basic test
        )

        expected = (1000000 - 100000) // 5
        assert depreciation == expected

    def test_half_year_convention_year_1(self):
        """Half-year convention: first year gets half depreciation."""
        annual_depreciation = (1000000 - 100000) // 5
        half_depreciation = annual_depreciation // 2

        depreciation = calculate_straight_line_depreciation(
            cost_basis_cents=1000000,
            salvage_value_cents=100000,
            useful_life_years=5,
            year_number=1,
            half_year_convention=True,
        )

        assert depreciation == half_depreciation

    def test_half_year_convention_middle_years(self):
        """Middle years get full depreciation."""
        annual_depreciation = (1000000 - 100000) // 5

        depreciation = calculate_straight_line_depreciation(
            cost_basis_cents=1000000,
            salvage_value_cents=100000,
            useful_life_years=5,
            year_number=3,
            half_year_convention=True,
        )

        assert depreciation == annual_depreciation

    def test_no_salvage_value(self):
        """Depreciation with zero salvage value."""
        depreciation = calculate_straight_line_depreciation(
            cost_basis_cents=500000,
            salvage_value_cents=0,
            useful_life_years=5,
            year_number=2,
        )

        expected = 500000 // 5
        assert depreciation == expected

    def test_year_beyond_useful_life(self):
        """Year beyond useful life returns 0."""
        depreciation = calculate_straight_line_depreciation(
            cost_basis_cents=500000,
            salvage_value_cents=0,
            useful_life_years=5,
            year_number=10,
        )

        assert depreciation == 0

    def test_negative_cost_raises_error(self):
        """Negative cost basis raises error."""
        with pytest.raises(AssetError):
            calculate_straight_line_depreciation(
                cost_basis_cents=-100000,
                salvage_value_cents=0,
                useful_life_years=5,
                year_number=1,
            )

    def test_zero_useful_life_raises_error(self):
        """Zero useful life raises error."""
        with pytest.raises(AssetError):
            calculate_straight_line_depreciation(
                cost_basis_cents=100000,
                salvage_value_cents=0,
                useful_life_years=0,
                year_number=1,
            )


class TestCalculateSection179Deduction:
    """Test Section 179 expensing deduction."""

    def test_full_deduction_under_limit(self):
        """Full cost deductible when under annual limit."""
        deduction = calculate_section_179_deduction(
            cost_basis_cents=500000,  # $5,000
            cumulative_179_cents=0,
            annual_limit_cents=1160000 * 100,  # 2024 limit
        )

        assert deduction == 500000

    def test_deduction_limited_by_annual_limit(self):
        """Deduction limited by annual $1.16M limit."""
        deduction = calculate_section_179_deduction(
            cost_basis_cents=1500000 * 100,  # Asset costs $1.5M
            cumulative_179_cents=0,
            annual_limit_cents=1160000 * 100,
        )

        # Capped at $1.16M limit
        assert deduction == 1160000 * 100

    def test_deduction_limited_by_cumulative(self):
        """Deduction reduced by prior 179 deductions."""
        deduction = calculate_section_179_deduction(
            cost_basis_cents=700000 * 100,  # $700k asset
            cumulative_179_cents=500000 * 100,  # $500k already taken
            annual_limit_cents=1160000 * 100,
        )

        # Only $660k available ($1.16M - $500k)
        assert deduction == 660000 * 100

    def test_no_deduction_when_limit_exceeded(self):
        """Zero deduction when cumulative already equals limit."""
        deduction = calculate_section_179_deduction(
            cost_basis_cents=500000 * 100,
            cumulative_179_cents=1160000 * 100,  # Already at limit
            annual_limit_cents=1160000 * 100,
        )

        assert deduction == 0

    def test_deduction_limited_by_taxable_income(self):
        """Deduction limited by taxable income if provided."""
        deduction = calculate_section_179_deduction(
            cost_basis_cents=500000 * 100,
            cumulative_179_cents=0,
            annual_limit_cents=1160000 * 100,
            taxable_income_cents=300000 * 100,  # Limited by income
        )

        # Limited to taxable income
        assert deduction == 300000 * 100

    def test_zero_cost_raises_error(self):
        """Zero cost basis raises error."""
        with pytest.raises(AssetError):
            calculate_section_179_deduction(
                cost_basis_cents=0,
                cumulative_179_cents=0,
            )


class TestCalculateBonusDepreciation:
    """Test bonus depreciation (100% or percentage)."""

    def test_full_bonus_depreciation(self):
        """100% bonus depreciation (qualified asset)."""
        deduction = calculate_bonus_depreciation(
            cost_basis_cents=500000,
            percentage=1.0,
            qualified=True,
        )

        assert deduction == 500000

    def test_partial_bonus_depreciation(self):
        """80% bonus depreciation (phasing percentage)."""
        deduction = calculate_bonus_depreciation(
            cost_basis_cents=500000,
            percentage=0.80,
            qualified=True,
        )

        expected = int(500000 * 0.80)
        assert deduction == expected

    def test_non_qualified_asset_no_bonus(self):
        """Non-qualified asset gets no bonus."""
        deduction = calculate_bonus_depreciation(
            cost_basis_cents=500000,
            percentage=1.0,
            qualified=False,
        )

        assert deduction == 0

    def test_zero_percentage(self):
        """Zero bonus percentage gives zero deduction."""
        deduction = calculate_bonus_depreciation(
            cost_basis_cents=500000,
            percentage=0.0,
            qualified=True,
        )

        assert deduction == 0

    def test_invalid_percentage_raises_error(self):
        """Percentage > 1.0 raises error."""
        with pytest.raises(AssetError):
            calculate_bonus_depreciation(
                cost_basis_cents=500000,
                percentage=1.5,
                qualified=True,
            )


class TestCreateDepreciationSchedule:
    """Test complete depreciation schedule generation."""

    def test_5_year_macrs_schedule(self):
        """Create full 5-year MACRS depreciation schedule."""
        schedule = create_depreciation_schedule(
            asset_id=1,
            description="Computer Equipment",
            cost_basis_cents=100000,
            salvage_value_cents=0,
            depreciation_method=DepreciationMethod.MACRS_200DB,
            date_placed_in_service=date(2024, 6, 1),
            recovery_period_years=5,
        )

        assert schedule.asset_id == 1
        assert schedule.description == "Computer Equipment"
        assert schedule.cost_basis_cents == 100000
        assert schedule.depreciable_basis_cents == 100000
        # 5-year MACRS with half-year convention = 6 years
        assert schedule.total_depreciation_years == 6
        # Total depreciation should equal depreciable basis
        assert schedule.total_depreciation_cents == 100000
        # Years should be sequential
        for i, year in enumerate(schedule.years):
            if i > 0:
                assert year.year == schedule.years[i - 1].year + 1

    def test_straight_line_schedule(self):
        """Create straight-line depreciation schedule."""
        schedule = create_depreciation_schedule(
            asset_id=2,
            description="Furniture",
            cost_basis_cents=700000,  # $7,000
            salvage_value_cents=0,
            depreciation_method=DepreciationMethod.STRAIGHT_LINE,
            date_placed_in_service=date(2024, 1, 1),
            recovery_period_years=5,
        )

        # Straight-line with half-year convention = 6 years
        assert schedule.total_depreciation_years == 6
        # Total should still equal depreciable basis
        assert schedule.total_depreciation_cents == 700000

        # Check that middle years have equal depreciation
        annual_depr = 700000 // 5
        for i in range(1, 5):  # Years 2-5 (middle years)
            assert schedule.years[i].depreciation_cents == annual_depr

    def test_section_179_schedule(self):
        """Section 179 deduction takes 100% in year 1."""
        schedule = create_depreciation_schedule(
            asset_id=3,
            description="Equipment",
            cost_basis_cents=500000,
            salvage_value_cents=0,
            depreciation_method=DepreciationMethod.SECTION_179,
            date_placed_in_service=date(2024, 3, 15),
            recovery_period_years=5,
        )

        # Year 1 should have full cost basis
        assert schedule.years[0].depreciation_cents == 500000
        assert schedule.years[0].accumulated_depreciation_cents == 500000
        # Subsequent years should have zero
        for year in schedule.years[1:]:
            assert year.depreciation_cents == 0

    def test_bonus_depreciation_schedule(self):
        """Bonus depreciation takes 100% in year 1."""
        schedule = create_depreciation_schedule(
            asset_id=4,
            description="Qualified Property",
            cost_basis_cents=300000,
            salvage_value_cents=0,
            depreciation_method=DepreciationMethod.BONUS_DEPRECIATION,
            date_placed_in_service=date(2024, 1, 1),
            recovery_period_years=5,
        )

        # Year 1 should have full deduction
        assert schedule.years[0].depreciation_cents == 300000
        # Asset should be fully depreciated after year 1
        assert schedule.years[0].book_value_cents == 0

    def test_accumulated_depreciation_tracking(self):
        """Accumulated depreciation increases monotonically."""
        schedule = create_depreciation_schedule(
            asset_id=5,
            description="Asset",
            cost_basis_cents=100000,
            salvage_value_cents=0,
            depreciation_method=DepreciationMethod.STRAIGHT_LINE,
            date_placed_in_service=date(2024, 1, 1),
            recovery_period_years=5,
        )

        previous_accumulated = 0
        for year in schedule.years:
            assert year.accumulated_depreciation_cents >= previous_accumulated
            previous_accumulated = year.accumulated_depreciation_cents

    def test_book_value_calculation(self):
        """Book value = cost basis - accumulated depreciation."""
        schedule = create_depreciation_schedule(
            asset_id=6,
            description="Asset",
            cost_basis_cents=100000,
            salvage_value_cents=0,
            depreciation_method=DepreciationMethod.MACRS_200DB,
            date_placed_in_service=date(2024, 1, 1),
            recovery_period_years=5,
        )

        for year in schedule.years:
            expected_book_value = schedule.cost_basis_cents - year.accumulated_depreciation_cents
            assert year.book_value_cents == expected_book_value

    def test_salvage_value_limits_depreciation(self):
        """Accumulated depreciation cannot exceed depreciable basis."""
        schedule = create_depreciation_schedule(
            asset_id=7,
            description="Asset with Salvage",
            cost_basis_cents=1000000,
            salvage_value_cents=200000,  # $2,000 salvage
            depreciation_method=DepreciationMethod.STRAIGHT_LINE,
            date_placed_in_service=date(2024, 1, 1),
            recovery_period_years=5,
        )

        # Depreciable basis = 1,000,000 - 200,000 = 800,000
        final_year = schedule.years[-1]
        assert final_year.accumulated_depreciation_cents == 800000
        # Book value should be cost basis minus accumulated (minimum is salvage)
        assert final_year.book_value_cents == 200000

    def test_zero_cost_raises_error(self):
        """Zero cost basis raises error."""
        with pytest.raises(AssetError):
            create_depreciation_schedule(
                asset_id=1,
                description="Asset",
                cost_basis_cents=0,
                salvage_value_cents=0,
                depreciation_method=DepreciationMethod.STRAIGHT_LINE,
                date_placed_in_service=date(2024, 1, 1),
                recovery_period_years=5,
            )

    def test_zero_recovery_period_raises_error(self):
        """Zero recovery period raises error."""
        with pytest.raises(AssetError):
            create_depreciation_schedule(
                asset_id=1,
                description="Asset",
                cost_basis_cents=100000,
                salvage_value_cents=0,
                depreciation_method=DepreciationMethod.STRAIGHT_LINE,
                date_placed_in_service=date(2024, 1, 1),
                recovery_period_years=0,
            )
