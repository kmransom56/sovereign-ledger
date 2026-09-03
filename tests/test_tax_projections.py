"""Tests for tax liability projections and quarterly estimates (Step 13, Phase 5).

Tests core tax calculation logic: federal tax calculation across brackets,
self-employment tax, quarterly estimated tax safe harbor determination,
year-end projection, and multi-scenario tax savings analysis.
"""

from datetime import date

import pytest

from ledger.tax_projections import (
    FilingStatus,
    QuarterlyTaxEstimate,
    TaxBracket,
    TaxProjection,
    TaxProjectionError,
    TaxSavingsProjection,
    TaxSavingsScenario,
    calculate_federal_tax,
    calculate_quarterly_estimate,
    calculate_self_employment_tax,
    project_year_end_tax,
    simulate_tax_scenarios,
)


class TestCalculateFederalTax:
    """Test federal income tax calculation with brackets."""

    def test_single_bracket_no_qbi(self):
        """Calculate tax with single bracket, no QBI deduction."""
        # Simple 10% bracket
        brackets = [
            TaxBracket(
                filing_status=FilingStatus.SINGLE,
                min_income_cents=0,
                max_income_cents=11600 * 100,  # $11,600
                rate_percent=10.0,
                year=2024,
            ),
        ]

        taxable_cents = 10000 * 100  # $10,000
        tax_cents, marginal = calculate_federal_tax(
            taxable_cents, FilingStatus.SINGLE, brackets
        )

        expected_tax = int(10000 * 100 * 0.10)
        assert tax_cents == expected_tax
        assert marginal == 0.10

    def test_multiple_brackets_single_filer(self):
        """Calculate tax with multiple brackets for single filer."""
        brackets = [
            TaxBracket(
                filing_status=FilingStatus.SINGLE,
                min_income_cents=0,
                max_income_cents=11600 * 100,
                rate_percent=10.0,
                year=2024,
            ),
            TaxBracket(
                filing_status=FilingStatus.SINGLE,
                min_income_cents=11600 * 100,
                max_income_cents=47150 * 100,
                rate_percent=12.0,
                year=2024,
            ),
            TaxBracket(
                filing_status=FilingStatus.SINGLE,
                min_income_cents=47150 * 100,
                max_income_cents=0,  # Unlimited
                rate_percent=22.0,
                year=2024,
            ),
        ]

        # Income: $50,000 (covers 10%, 12%, and 22% brackets)
        taxable_cents = 50000 * 100
        tax_cents, marginal = calculate_federal_tax(
            taxable_cents, FilingStatus.SINGLE, brackets
        )

        # Expected: (11600 * 0.10) + (35550 * 0.12) + (2850 * 0.22)
        expected = int(
            (11600 * 0.10) + (35550 * 0.12) + (2850 * 0.22)
        ) * 100
        assert tax_cents == expected
        assert marginal == 0.22

    def test_married_filing_jointly(self):
        """Calculate tax for married filing jointly status."""
        brackets = [
            TaxBracket(
                filing_status=FilingStatus.MARRIED_FILING_JOINTLY,
                min_income_cents=0,
                max_income_cents=23200 * 100,
                rate_percent=10.0,
                year=2024,
            ),
            TaxBracket(
                filing_status=FilingStatus.MARRIED_FILING_JOINTLY,
                min_income_cents=23200 * 100,
                max_income_cents=0,
                rate_percent=12.0,
                year=2024,
            ),
        ]

        taxable_cents = 50000 * 100
        tax_cents, marginal = calculate_federal_tax(
            taxable_cents, FilingStatus.MARRIED_FILING_JOINTLY, brackets
        )

        # Expected: (23200 * 0.10) + (26800 * 0.12)
        expected = int((23200 * 0.10) + (26800 * 0.12)) * 100
        assert tax_cents == expected
        assert marginal == 0.12

    def test_with_qbi_deduction(self):
        """Calculate tax with qualified business income deduction."""
        brackets = [
            TaxBracket(
                filing_status=FilingStatus.SINGLE,
                min_income_cents=0,
                max_income_cents=0,
                rate_percent=12.0,
                year=2024,
            ),
        ]

        taxable_cents = 100000 * 100  # $100,000
        qbi_deduction = 20000 * 100  # 20% of $100,000
        tax_cents, _ = calculate_federal_tax(
            taxable_cents,
            FilingStatus.SINGLE,
            brackets,
            qualified_business_income_deduction_cents=qbi_deduction,
        )

        # Tax should be on 80,000 (100,000 - 20,000)
        expected = int(80000 * 100 * 0.12)
        assert tax_cents == expected

    def test_zero_income(self):
        """Calculate tax with zero income."""
        brackets = [
            TaxBracket(
                filing_status=FilingStatus.SINGLE,
                min_income_cents=0,
                max_income_cents=0,
                rate_percent=10.0,
                year=2024,
            ),
        ]

        tax_cents, marginal = calculate_federal_tax(
            0, FilingStatus.SINGLE, brackets
        )
        assert tax_cents == 0
        assert marginal == 0.0

    def test_negative_income_raises_error(self):
        """Negative taxable income raises error."""
        brackets = []
        with pytest.raises(TaxProjectionError):
            calculate_federal_tax(-1000 * 100, FilingStatus.SINGLE, brackets)


class TestCalculateSelfEmploymentTax:
    """Test self-employment (Social Security + Medicare) tax calculation."""

    def test_basic_se_tax(self):
        """Calculate SE tax on net business income."""
        net_income_cents = 50000 * 100  # $50,000
        se_tax = calculate_self_employment_tax(net_income_cents)

        # SE tax = 50,000 * 0.9235 * 0.153
        expected = int(50000 * 0.9235 * 0.153 * 100)
        assert se_tax == expected

    def test_high_income_se_tax(self):
        """Calculate SE tax on high income."""
        net_income_cents = 150000 * 100  # $150,000
        se_tax = calculate_self_employment_tax(net_income_cents)

        expected = int(150000 * 0.9235 * 0.153 * 100)
        assert se_tax == expected

    def test_zero_income_se_tax(self):
        """SE tax on zero income is zero."""
        se_tax = calculate_self_employment_tax(0)
        assert se_tax == 0

    def test_custom_se_tax_rate(self):
        """Calculate SE tax with custom rate."""
        net_income_cents = 50000 * 100
        custom_rate = 0.92  # 92% rate
        se_tax = calculate_self_employment_tax(net_income_cents, se_tax_rate=custom_rate)

        expected = int(50000 * 0.9235 * 0.92 * 100)
        assert se_tax == expected

    def test_negative_income_raises_error(self):
        """Negative income raises error."""
        with pytest.raises(TaxProjectionError):
            calculate_self_employment_tax(-1000 * 100)


class TestCalculateQuarterlyEstimate:
    """Test safe harbor quarterly estimated tax calculation."""

    def test_q1_90_percent_safe_harbor(self):
        """Q1 90% safe harbor is lower."""
        estimate = calculate_quarterly_estimate(
            year=2024,
            quarter=1,
            projected_quarterly_tax_cents=10000 * 100,  # Quarterly
            prior_year_tax_cents=30000 * 100,  # Prior year total
            prior_payments_cents=0,
            prior_year_agi_cents=100000 * 100,
        )

        # 90% safe harbor: 10,000 * 4 * 0.90 = $36,000
        # 100% safe harbor: 30,000 (prior year, low AGI)
        # Min of two: $30,000
        assert estimate.quarter == 1
        assert estimate.year == 2024
        assert estimate.safe_harbor_90_current_year_cents == 36000 * 100
        assert estimate.safe_harbor_100_prior_year_cents == 30000 * 100
        assert estimate.recommended_payment_cents == 30000 * 100
        assert estimate.remaining_safe_harbor_cents == 30000 * 100
        assert estimate.due_date == date(2024, 4, 15)

    def test_q2_with_prior_payments(self):
        """Q2 with prior payments applied to remaining amount."""
        estimate = calculate_quarterly_estimate(
            year=2024,
            quarter=2,
            projected_quarterly_tax_cents=15000 * 100,
            prior_year_tax_cents=50000 * 100,
            prior_payments_cents=15000 * 100,  # Already paid Q1
            prior_year_agi_cents=100000 * 100,
        )

        # 90% safe harbor: 15,000 * 4 * 0.90 = $54,000
        # 100% safe harbor: 50,000
        # Recommended: $50,000
        # Remaining after $15,000 paid: $35,000
        assert estimate.quarter == 2
        assert estimate.recommended_payment_cents == 50000 * 100
        assert estimate.prior_payments_cents == 15000 * 100
        assert estimate.remaining_safe_harbor_cents == 35000 * 100
        assert estimate.due_date == date(2024, 6, 15)

    def test_q3_110_percent_high_agi(self):
        """Q3 uses 110% safe harbor for prior year when AGI > $150k."""
        estimate = calculate_quarterly_estimate(
            year=2024,
            quarter=3,
            projected_quarterly_tax_cents=12000 * 100,
            prior_year_tax_cents=40000 * 100,
            prior_payments_cents=30000 * 100,
            prior_year_agi_cents=160000 * 100,  # > $150k threshold
        )

        # 90% safe harbor: 12,000 * 4 * 0.90 = $43,200
        # 110% safe harbor: 40,000 * 1.10 = $44,000
        # Recommended: $43,200 (lower)
        assert estimate.safe_harbor_100_prior_year_cents == 44000 * 100
        assert estimate.recommended_payment_cents == 43200 * 100
        assert estimate.remaining_safe_harbor_cents == 13200 * 100
        assert estimate.due_date == date(2024, 9, 15)

    def test_q4_due_date_next_year(self):
        """Q4 due date is in next year (Jan 15)."""
        estimate = calculate_quarterly_estimate(
            year=2024,
            quarter=4,
            projected_quarterly_tax_cents=10000 * 100,
            prior_year_tax_cents=30000 * 100,
        )

        assert estimate.quarter == 4
        assert estimate.due_date == date(2025, 1, 15)

    def test_invalid_quarter_raises_error(self):
        """Invalid quarter (0 or 5) raises error."""
        with pytest.raises(TaxProjectionError):
            calculate_quarterly_estimate(
                year=2024,
                quarter=0,
                projected_quarterly_tax_cents=10000 * 100,
            )

        with pytest.raises(TaxProjectionError):
            calculate_quarterly_estimate(
                year=2024,
                quarter=5,
                projected_quarterly_tax_cents=10000 * 100,
            )

    def test_negative_tax_raises_error(self):
        """Negative projected tax raises error."""
        with pytest.raises(TaxProjectionError):
            calculate_quarterly_estimate(
                year=2024,
                quarter=1,
                projected_quarterly_tax_cents=-1000 * 100,
            )


class TestProjectYearEndTax:
    """Test full-year tax projection."""

    def test_simple_projection(self):
        """Project year-end tax with basic income/deductions."""
        brackets = [
            TaxBracket(
                filing_status=FilingStatus.SINGLE,
                min_income_cents=0,
                max_income_cents=11600 * 100,
                rate_percent=10.0,
                year=2024,
            ),
            TaxBracket(
                filing_status=FilingStatus.SINGLE,
                min_income_cents=11600 * 100,
                max_income_cents=47150 * 100,
                rate_percent=12.0,
                year=2024,
            ),
        ]

        projection = project_year_end_tax(
            gross_income_cents=50000 * 100,
            business_deductions_cents=10000 * 100,
            filing_status=FilingStatus.SINGLE,
            tax_brackets=brackets,
            standard_deduction_cents=13850 * 100,
            period_start=date(2024, 1, 1),
            period_end=date(2024, 12, 31),
        )

        # AGI = 50,000 - 10,000 = 40,000
        # QBI deduction = 40,000 * 0.20 = 8,000
        # Taxable = 40,000 - 13,850 - 8,000 = 18,150
        assert projection.gross_income_cents == 50000 * 100
        assert projection.business_deductions_cents == 10000 * 100
        assert projection.adjusted_gross_income_cents == 40000 * 100
        assert projection.standard_deduction_cents == 13850 * 100
        assert projection.taxable_income_cents == 18150 * 100
        assert projection.federal_income_tax_cents > 0
        assert projection.self_employment_tax_cents > 0
        assert projection.total_tax_cents == (
            projection.federal_income_tax_cents + projection.self_employment_tax_cents
        )

    def test_projection_with_zero_deductions(self):
        """Project tax with zero deductions."""
        brackets = [
            TaxBracket(
                filing_status=FilingStatus.SINGLE,
                min_income_cents=0,
                max_income_cents=0,
                rate_percent=12.0,
                year=2024,
            ),
        ]

        projection = project_year_end_tax(
            gross_income_cents=60000 * 100,
            business_deductions_cents=0,
            filing_status=FilingStatus.SINGLE,
            tax_brackets=brackets,
            standard_deduction_cents=0,
        )

        assert projection.adjusted_gross_income_cents == 60000 * 100
        assert projection.business_deductions_cents == 0

    def test_projection_high_income(self):
        """Project tax for high income (QBI phase-out scenarios)."""
        brackets = [
            TaxBracket(
                filing_status=FilingStatus.SINGLE,
                min_income_cents=0,
                max_income_cents=0,
                rate_percent=24.0,
                year=2024,
            ),
        ]

        projection = project_year_end_tax(
            gross_income_cents=200000 * 100,
            business_deductions_cents=50000 * 100,
            filing_status=FilingStatus.SINGLE,
            tax_brackets=brackets,
            standard_deduction_cents=13850 * 100,
        )

        # AGI = 200,000 - 50,000 = 150,000
        # QBI = 150,000 * 0.20 = 30,000
        # Taxable = 150,000 - 13,850 - 30,000 = 106,150
        assert projection.adjusted_gross_income_cents == 150000 * 100
        assert projection.qualified_business_income_cents == 150000 * 100
        assert projection.taxable_income_cents == 106150 * 100

    def test_effective_and_marginal_rates(self):
        """Verify effective and marginal tax rate calculations."""
        brackets = [
            TaxBracket(
                filing_status=FilingStatus.SINGLE,
                min_income_cents=0,
                max_income_cents=11600 * 100,
                rate_percent=10.0,
                year=2024,
            ),
            TaxBracket(
                filing_status=FilingStatus.SINGLE,
                min_income_cents=11600 * 100,
                max_income_cents=0,
                rate_percent=12.0,
                year=2024,
            ),
        ]

        projection = project_year_end_tax(
            gross_income_cents=100000 * 100,
            business_deductions_cents=20000 * 100,
            filing_status=FilingStatus.SINGLE,
            tax_brackets=brackets,
            standard_deduction_cents=13850 * 100,
        )

        # Marginal rate should be 12% (top bracket hit)
        assert projection.marginal_tax_rate == 0.12
        # Effective rate is total tax / gross income
        effective = projection.total_tax_cents / (100000 * 100)
        assert abs(projection.effective_tax_rate - effective) < 0.0001

    def test_quarterly_estimate_calculation(self):
        """Verify quarterly estimate is 1/4 of total tax."""
        brackets = [
            TaxBracket(
                filing_status=FilingStatus.SINGLE,
                min_income_cents=0,
                max_income_cents=0,
                rate_percent=15.0,
                year=2024,
            ),
        ]

        projection = project_year_end_tax(
            gross_income_cents=60000 * 100,
            business_deductions_cents=10000 * 100,
            filing_status=FilingStatus.SINGLE,
            tax_brackets=brackets,
            standard_deduction_cents=13850 * 100,
        )

        expected_quarterly = projection.total_tax_cents // 4
        assert projection.estimated_quarterly_cents == expected_quarterly

    def test_period_dates_reflected(self):
        """Verify period start/end are captured."""
        brackets = []
        period_start = date(2024, 1, 1)
        period_end = date(2024, 12, 31)

        projection = project_year_end_tax(
            gross_income_cents=50000 * 100,
            business_deductions_cents=10000 * 100,
            filing_status=FilingStatus.SINGLE,
            tax_brackets=brackets,
            period_start=period_start,
            period_end=period_end,
        )

        assert projection.period_start == period_start
        assert projection.period_end == period_end

    def test_invalid_period_raises_error(self):
        """Period end before start raises error."""
        with pytest.raises(TaxProjectionError):
            project_year_end_tax(
                gross_income_cents=50000 * 100,
                business_deductions_cents=10000 * 100,
                filing_status=FilingStatus.SINGLE,
                tax_brackets=[],
                period_start=date(2024, 12, 31),
                period_end=date(2024, 1, 1),
            )


class TestSimulateTaxScenarios:
    """Test multi-scenario tax savings analysis."""

    def test_single_scenario(self):
        """Simulate tax with single scenario."""
        brackets = [
            TaxBracket(
                filing_status=FilingStatus.SINGLE,
                min_income_cents=0,
                max_income_cents=0,
                rate_percent=24.0,
                year=2024,
            ),
        ]

        baseline_tax = 24000 * 100  # $24,000
        scenarios = [
            ("Home Office", "Add $5,000 home office deduction", 5000 * 100),
        ]

        projection = simulate_tax_scenarios(
            baseline_tax_cents=baseline_tax,
            scenarios=scenarios,
            taxable_income_cents=100000 * 100,
            filing_status=FilingStatus.SINGLE,
            tax_brackets=brackets,
        )

        assert len(projection.scenarios) == 1
        assert projection.baseline_tax_cents == baseline_tax
        scenario = projection.scenarios[0]
        assert scenario.scenario_name == "Home Office"
        assert scenario.additional_deductions_cents == 5000 * 100
        assert scenario.taxable_income_cents == 95000 * 100
        # Tax on $95,000 at 24% = $22,800
        assert scenario.federal_income_tax_cents == 22800 * 100
        # Savings = 24,000 - 22,800 = 1,200
        assert scenario.tax_savings_vs_baseline_cents == 1200 * 100

    def test_multiple_scenarios_comparison(self):
        """Simulate tax with multiple scenarios and identify best."""
        brackets = [
            TaxBracket(
                filing_status=FilingStatus.SINGLE,
                min_income_cents=0,
                max_income_cents=0,
                rate_percent=22.0,
                year=2024,
            ),
        ]

        baseline_tax = 22000 * 100
        scenarios = [
            ("Small Deduction", "Add $5,000 deduction", 5000 * 100),
            ("Large Deduction", "Add $20,000 deduction", 20000 * 100),
            ("Medium Deduction", "Add $10,000 deduction", 10000 * 100),
        ]

        projection = simulate_tax_scenarios(
            baseline_tax_cents=baseline_tax,
            scenarios=scenarios,
            taxable_income_cents=100000 * 100,
            filing_status=FilingStatus.SINGLE,
            tax_brackets=brackets,
        )

        assert len(projection.scenarios) == 3
        # Best scenario should be Large Deduction (highest savings)
        assert projection.recommended_scenario_index == 1
        assert projection.scenarios[1].tax_savings_vs_baseline_cents == max(
            s.tax_savings_vs_baseline_cents for s in projection.scenarios
        )
        # Max savings should equal best scenario's savings
        assert (
            projection.max_potential_savings_cents
            == projection.scenarios[1].tax_savings_vs_baseline_cents
        )

    def test_scenario_with_zero_additional_deductions(self):
        """Scenario with zero additional deductions shows no savings."""
        brackets = [
            TaxBracket(
                filing_status=FilingStatus.SINGLE,
                min_income_cents=0,
                max_income_cents=0,
                rate_percent=12.0,
                year=2024,
            ),
        ]

        baseline_tax = 12000 * 100
        scenarios = [
            ("No Change", "No additional deductions", 0),
        ]

        projection = simulate_tax_scenarios(
            baseline_tax_cents=baseline_tax,
            scenarios=scenarios,
            taxable_income_cents=100000 * 100,
            filing_status=FilingStatus.SINGLE,
            tax_brackets=brackets,
        )

        scenario = projection.scenarios[0]
        assert scenario.additional_deductions_cents == 0
        assert scenario.tax_savings_vs_baseline_cents == 0
        assert scenario.taxable_income_cents == 100000 * 100

    def test_deduction_exceeds_taxable_income(self):
        """Deduction that exceeds taxable income results in zero taxable."""
        brackets = [
            TaxBracket(
                filing_status=FilingStatus.SINGLE,
                min_income_cents=0,
                max_income_cents=0,
                rate_percent=24.0,
                year=2024,
            ),
        ]

        baseline_tax = 24000 * 100
        scenarios = [
            ("Excess Deduction", "Add $150,000 deduction", 150000 * 100),
        ]

        projection = simulate_tax_scenarios(
            baseline_tax_cents=baseline_tax,
            scenarios=scenarios,
            taxable_income_cents=100000 * 100,
            filing_status=FilingStatus.SINGLE,
            tax_brackets=brackets,
        )

        scenario = projection.scenarios[0]
        # Taxable income can't go below zero
        assert scenario.taxable_income_cents == 0
        assert scenario.federal_income_tax_cents == 0
        # Full tax is saved
        assert scenario.tax_savings_vs_baseline_cents == baseline_tax

    def test_empty_scenarios_raises_error(self):
        """Empty scenarios list raises error."""
        with pytest.raises(TaxProjectionError):
            simulate_tax_scenarios(
                baseline_tax_cents=10000 * 100,
                scenarios=[],
                taxable_income_cents=100000 * 100,
                filing_status=FilingStatus.SINGLE,
                tax_brackets=[],
            )

    def test_negative_baseline_raises_error(self):
        """Negative baseline tax raises error."""
        with pytest.raises(TaxProjectionError):
            simulate_tax_scenarios(
                baseline_tax_cents=-1000 * 100,
                scenarios=[("Test", "Test", 0)],
                taxable_income_cents=100000 * 100,
                filing_status=FilingStatus.SINGLE,
                tax_brackets=[],
            )
