"""Integration tests for complete tax optimization workflows (Phase 6).

Tests end-to-end scenarios combining deductions, tax projections,
capital asset depreciation, and recommendation generation.
"""

from datetime import date

import pytest

from ledger.deductions import (
    DeductionCategory,
    DeductibleExpense,
    aggregate_deductions_by_period,
    detect_hobby_loss,
    identify_tax_breaks,
)
from ledger.tax_projections import (
    calculate_federal_tax,
    FilingStatus,
    TaxBracket,
)
from ledger.tax_recommendations import (
    generate_deduction_recommendations,
    generate_optimization_recommendations,
    prioritize_recommendations,
)


class TestSelfEmployeeWorkflow:
    """Test complete workflow for self-employed consultant."""

    def test_freelance_consultant_deduction_workflow(self):
        """End-to-end: freelancer deduction tracking and aggregation."""
        # Setup: Freelance consultant with various deductions
        expenses = [
            # Office supplies
            DeductibleExpense(
                bill_id=1,
                bill_number="SUPP-001",
                bill_date=date(2026, 1, 10),
                vendor_id=1,
                vendor_name="Office Depot",
                category=DeductionCategory.SUPPLIES,
                description="Office supplies",
                amount_cents=5000,
                business_use_percent=100,
                deductible_amount_cents=5000,
            ),
            # Home office utilities (50% business use)
            DeductibleExpense(
                bill_id=2,
                bill_number="UTIL-001",
                bill_date=date(2026, 1, 15),
                vendor_id=2,
                vendor_name="Electric Co",
                category=DeductionCategory.HOME_OFFICE,
                description="Home office utilities",
                amount_cents=10000,
                business_use_percent=50,
                deductible_amount_cents=5000,
            ),
            # Internet (75% business use)
            DeductibleExpense(
                bill_id=3,
                bill_number="INET-001",
                bill_date=date(2026, 2, 1),
                vendor_id=3,
                vendor_name="ISP",
                category=DeductionCategory.UTILITIES,
                description="Internet",
                amount_cents=8000,
                business_use_percent=75,
                deductible_amount_cents=6000,
            ),
            # Business meals
            DeductibleExpense(
                bill_id=4,
                bill_number="MEAL-001",
                bill_date=date(2026, 3, 15),
                vendor_id=4,
                vendor_name="Restaurant",
                category=DeductionCategory.MEALS,
                description="Client lunch",
                amount_cents=10000,
                business_use_percent=100,
                deductible_amount_cents=10000,
            ),
            # Professional services
            DeductibleExpense(
                bill_id=5,
                bill_number="PROF-001",
                bill_date=date(2026, 6, 1),
                vendor_id=5,
                vendor_name="Accountant",
                category=DeductionCategory.PROFESSIONAL_SERVICES,
                description="Tax consulting",
                amount_cents=50000,
                business_use_percent=100,
                deductible_amount_cents=50000,
            ),
            # Software subscriptions
            DeductibleExpense(
                bill_id=6,
                bill_number="SOFT-001",
                bill_date=date(2026, 1, 1),
                vendor_id=6,
                vendor_name="Adobe",
                category=DeductionCategory.SUBSCRIPTIONS,
                description="Adobe Creative Cloud",
                amount_cents=60000,
                business_use_percent=100,
                deductible_amount_cents=60000,
            ),
        ]

        # Aggregate deductions by period
        q1_summary = aggregate_deductions_by_period(
            expenses, date(2026, 1, 1), date(2026, 3, 31)
        )
        assert q1_summary.total_deductible_cents > 0

        # Verify aggregation includes multiple categories
        assert len(q1_summary.categories) > 1

        # Total deductions
        total_deductions = sum(e.deductible_amount_cents for e in expenses)
        assert total_deductions > 0


class TestTaxCalculationWithDeductions:
    """Test tax calculation with various deduction scenarios."""

    def test_federal_tax_with_deductions(self):
        """Calculate federal tax with business deductions."""
        business_income = 150000 * 100  # $150,000
        business_deductions = 40000 * 100  # $40,000

        # Create tax brackets for single filer
        brackets = [
            TaxBracket(
                filing_status=FilingStatus.SINGLE,
                min_income_cents=0,
                max_income_cents=11600 * 100,
                rate_percent=10.0,
                year=2026,
            ),
            TaxBracket(
                filing_status=FilingStatus.SINGLE,
                min_income_cents=11600 * 100,
                max_income_cents=47150 * 100,
                rate_percent=12.0,
                year=2026,
            ),
            TaxBracket(
                filing_status=FilingStatus.SINGLE,
                min_income_cents=47150 * 100,
                max_income_cents=100525 * 100,
                rate_percent=22.0,
                year=2026,
            ),
            TaxBracket(
                filing_status=FilingStatus.SINGLE,
                min_income_cents=100525 * 100,
                max_income_cents=191950 * 100,
                rate_percent=24.0,
                year=2026,
            ),
        ]
        
        # Calculate tax on business income
        taxable_income = business_income - business_deductions
        federal_tax, marginal_rate = calculate_federal_tax(
            taxable_income_cents=taxable_income,
            filing_status=FilingStatus.SINGLE,
            tax_brackets=brackets,
        )
        
        # Verify tax calculation
        assert federal_tax > 0
        effective_rate = federal_tax / business_income
        # With $40k deductions on $150k income, effective federal rate should be ~13%
        assert 0.10 < effective_rate < 0.25


class TestHobbyLossDetectionWorkflow:
    """Test hobby loss detection in multi-year scenario."""

    def test_activity_with_profitable_history(self):
        """End-to-end: verify profit motive with 3+ profitable years."""
        # Activity with all profitable years
        income_by_year = {
            2021: 50000 * 100,
            2022: 75000 * 100,
            2023: 100000 * 100,
            2024: 85000 * 100,
            2025: 120000 * 100,
        }
        expenses_by_year = {
            2021: 30000 * 100,
            2022: 40000 * 100,
            2023: 50000 * 100,
            2024: 60000 * 100,
            2025: 50000 * 100,
        }

        analysis = detect_hobby_loss(
            activity_description="Consulting",
            income_by_year=income_by_year,
            expenses_by_year=expenses_by_year,
        )

        # Should NOT be hobby (all profitable)
        assert not analysis.is_hobby
        assert analysis.profit_count == 5
        assert analysis.loss_count == 0

    def test_activity_with_consecutive_losses(self):
        """End-to-end: detect hobby status with consecutive losses."""
        # Activity with consecutive losses
        income_by_year = {
            2021: 100000 * 100,
            2022: 10000 * 100,
            2023: 5000 * 100,
            2024: 8000 * 100,
            2025: 3000 * 100,
        }
        expenses_by_year = {
            2021: 50000 * 100,
            2022: 60000 * 100,
            2023: 70000 * 100,  # 2+ consecutive losses
            2024: 80000 * 100,
            2025: 90000 * 100,
        }

        analysis = detect_hobby_loss(
            activity_description="Crafts",
            income_by_year=income_by_year,
            expenses_by_year=expenses_by_year,
        )

        # Should be hobby (2+ consecutive losses)
        assert analysis.is_hobby
        # Losses limited to income
        total_income = sum(income_by_year.values())
        total_expenses = sum(expenses_by_year.values())
        expected_nondeductible = total_expenses - total_income
        assert analysis.nondeductible_loss_cents == expected_nondeductible


class TestTaxBreakIdentification:
    """Test identification of tax break opportunities."""

    def test_identify_home_office_opportunity(self):
        """End-to-end: identify home office deduction opportunity."""
        expenses = [
            DeductibleExpense(
                bill_id=1,
                bill_number="UTIL-001",
                bill_date=date(2026, 1, 1),
                vendor_id=1,
                vendor_name="Landlord",
                category=DeductionCategory.HOME_OFFICE,
                description="Home office rent",
                amount_cents=50000,  # $500/month equivalent
                business_use_percent=100,
                deductible_amount_cents=50000,
            ),
        ]

        income = 100000 * 100  # $100,000

        # Identify tax breaks
        breaks = identify_tax_breaks(expenses, income_cents=income)

        # Should find home office opportunity
        home_office_breaks = [
            b for b in breaks if b.opportunity_type == "home_office"
        ]
        assert len(home_office_breaks) > 0
        assert home_office_breaks[0].tax_savings_cents > 0

    def test_identify_vehicle_opportunity(self):
        """End-to-end: identify vehicle deduction opportunity."""
        expenses = [
            DeductibleExpense(
                bill_id=1,
                bill_number="FUEL-001",
                bill_date=date(2026, 1, 15),
                vendor_id=1,
                vendor_name="Shell",
                category=DeductionCategory.VEHICLE,
                description="Vehicle fuel",
                amount_cents=15000,
                business_use_percent=100,
                deductible_amount_cents=15000,
            ),
        ]

        income = 100000 * 100

        # Identify opportunities
        breaks = identify_tax_breaks(expenses, income_cents=income)

        # Should find vehicle opportunity
        vehicle_breaks = [
            b for b in breaks if b.opportunity_type == "vehicle_mileage"
        ]
        assert len(vehicle_breaks) > 0


class TestRecommendationWorkflow:
    """Test recommendation generation and prioritization."""

    def test_deduction_recommendations(self):
        """Generate deduction recommendations for identified gaps."""
        current_deductions = 40000 * 100
        potential_deductions = 70000 * 100  # $30k gap

        # Generate recommendations
        recs = generate_deduction_recommendations(
            actual_deductions_cents=current_deductions,
            potential_deductions_cents=potential_deductions,
            marginal_tax_rate=0.24,
        )

        # Should identify deduction gap
        assert len(recs) > 0

    def test_optimization_recommendations(self):
        """Generate tax optimization recommendations."""
        business_income = 150000 * 100
        current_deductions = 40000 * 100

        # Generate optimization recommendations
        recs = generate_optimization_recommendations(
            business_income_cents=business_income,
            current_deductions_cents=current_deductions,
        )

        # Should have recommendations
        assert len(recs) > 0
        
        # Entity structure should be included
        entity_recs = [r for r in recs if "entity" in r.recommendation_id.lower()]
        assert len(entity_recs) > 0

    def test_recommendation_prioritization(self):
        """Prioritize mixed recommendations."""
        current_deductions = 40000 * 100
        potential_deductions = 70000 * 100

        # Generate deduction and optimization recs
        deduction_recs = generate_deduction_recommendations(
            actual_deductions_cents=current_deductions,
            potential_deductions_cents=potential_deductions,
        )

        optimization_recs = generate_optimization_recommendations(
            business_income_cents=150000 * 100,
            current_deductions_cents=current_deductions,
        )

        # Combine and prioritize
        all_recs = deduction_recs + optimization_recs
        if len(all_recs) > 0:
            prioritized = prioritize_recommendations(all_recs)

            # Should be sorted by priority
            assert len(prioritized) > 0
            
            # Verify priority order (lower priority value = higher priority)
            for i in range(len(prioritized) - 1):
                current_priority = {
                    "critical": 0,
                    "high": 1,
                    "medium": 2,
                    "low": 3,
                }[prioritized[i].priority.value]
                next_priority = {
                    "critical": 0,
                    "high": 1,
                    "medium": 2,
                    "low": 3,
                }[prioritized[i + 1].priority.value]
                assert current_priority <= next_priority
