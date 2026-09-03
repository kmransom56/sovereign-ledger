"""Tests for deduction aggregation and tax-break identification (Step 13, Phase 5).

Tests core deduction logic: filtering, aggregation, tax-break identification,
and hobby-loss detection.
"""

from datetime import date

import pytest

from ledger.deductions import (
    DeductionCategory,
    DeductibleExpense,
    HobbyLossAnalysis,
    TaxBreakOpportunity,
    aggregate_deductions_by_category,
    aggregate_deductions_by_period,
    detect_hobby_loss,
    filter_deductible_expenses,
    identify_tax_breaks,
)


class TestFilterDeductibleExpenses:
    """Test filtering deductible expenses by category and date."""

    def test_filter_by_category(self):
        """Filter expenses by deduction category."""
        expenses = [
            DeductibleExpense(
                bill_id=1,
                bill_number="BILL-001",
                bill_date=date(2026, 1, 15),
                vendor_id=1,
                vendor_name="Office Depot",
                category=DeductionCategory.SUPPLIES,
                description="Office supplies",
                amount_cents=5000,
                business_use_percent=100,
                deductible_amount_cents=5000,
            ),
            DeductibleExpense(
                bill_id=2,
                bill_number="BILL-002",
                bill_date=date(2026, 1, 20),
                vendor_id=2,
                vendor_name="Comcast",
                category=DeductionCategory.UTILITIES,
                description="Internet",
                amount_cents=10000,
                business_use_percent=80,
                deductible_amount_cents=8000,
            ),
        ]

        filtered = filter_deductible_expenses(expenses, category=DeductionCategory.SUPPLIES)
        assert len(filtered) == 1
        assert filtered[0].category == DeductionCategory.SUPPLIES

    def test_filter_by_date_range(self):
        """Filter expenses by date range."""
        expenses = [
            DeductibleExpense(
                bill_id=1,
                bill_number="BILL-001",
                bill_date=date(2026, 1, 15),
                vendor_id=1,
                vendor_name="Vendor A",
                category=DeductionCategory.SUPPLIES,
                description="Expense",
                amount_cents=1000,
                business_use_percent=100,
                deductible_amount_cents=1000,
            ),
            DeductibleExpense(
                bill_id=2,
                bill_number="BILL-002",
                bill_date=date(2026, 6, 15),
                vendor_id=2,
                vendor_name="Vendor B",
                category=DeductionCategory.SUPPLIES,
                description="Expense",
                amount_cents=2000,
                business_use_percent=100,
                deductible_amount_cents=2000,
            ),
        ]

        filtered = filter_deductible_expenses(
            expenses, min_date=date(2026, 1, 1), max_date=date(2026, 3, 31)
        )
        assert len(filtered) == 1
        assert filtered[0].bill_date == date(2026, 1, 15)


class TestAggregateDeductionsByPeriod:
    """Test period-based deduction aggregation."""

    def test_aggregate_single_category(self):
        """Aggregate deductions in a single category for period."""
        expenses = [
            DeductibleExpense(
                bill_id=1,
                bill_number="BILL-001",
                bill_date=date(2026, 1, 15),
                vendor_id=1,
                vendor_name="Vendor A",
                category=DeductionCategory.SUPPLIES,
                description="Supplies",
                amount_cents=5000,
                business_use_percent=100,
                deductible_amount_cents=5000,
            ),
            DeductibleExpense(
                bill_id=2,
                bill_number="BILL-002",
                bill_date=date(2026, 1, 20),
                vendor_id=1,
                vendor_name="Vendor A",
                category=DeductionCategory.SUPPLIES,
                description="More supplies",
                amount_cents=3000,
                business_use_percent=100,
                deductible_amount_cents=3000,
            ),
        ]

        summary = aggregate_deductions_by_period(
            expenses, date(2026, 1, 1), date(2026, 1, 31)
        )

        assert summary.total_amount_cents == 8000
        assert summary.total_deductible_cents == 8000
        assert summary.count == 2
        assert summary.nondeductible_cents == 0
        assert DeductionCategory.SUPPLIES in summary.categories
        cat_summary = summary.categories[DeductionCategory.SUPPLIES]
        assert cat_summary.total_amount_cents == 8000
        assert cat_summary.count == 2

    def test_aggregate_multiple_categories(self):
        """Aggregate deductions across multiple categories."""
        expenses = [
            DeductibleExpense(
                bill_id=1,
                bill_number="BILL-001",
                bill_date=date(2026, 1, 15),
                vendor_id=1,
                vendor_name="Vendor A",
                category=DeductionCategory.SUPPLIES,
                description="Supplies",
                amount_cents=5000,
                business_use_percent=100,
                deductible_amount_cents=5000,
            ),
            DeductibleExpense(
                bill_id=2,
                bill_number="BILL-002",
                bill_date=date(2026, 1, 20),
                vendor_id=2,
                vendor_name="Vendor B",
                category=DeductionCategory.UTILITIES,
                description="Internet",
                amount_cents=10000,
                business_use_percent=80,
                deductible_amount_cents=8000,
            ),
        ]

        summary = aggregate_deductions_by_period(
            expenses, date(2026, 1, 1), date(2026, 1, 31)
        )

        assert summary.total_amount_cents == 15000
        assert summary.total_deductible_cents == 13000
        assert summary.count == 2
        assert len(summary.categories) == 2

    def test_mixed_use_percentage(self):
        """Aggregate with mixed-use business percentage."""
        expenses = [
            DeductibleExpense(
                bill_id=1,
                bill_number="BILL-001",
                bill_date=date(2026, 1, 15),
                vendor_id=1,
                vendor_name="ISP",
                category=DeductionCategory.UTILITIES,
                description="Internet",
                amount_cents=10000,  # $100
                business_use_percent=75,
                deductible_amount_cents=7500,  # 75% of $100
            ),
            DeductibleExpense(
                bill_id=2,
                bill_number="BILL-002",
                bill_date=date(2026, 1, 20),
                vendor_id=1,
                vendor_name="ISP",
                category=DeductionCategory.UTILITIES,
                description="Internet",
                amount_cents=10000,  # $100
                business_use_percent=75,
                deductible_amount_cents=7500,  # 75% of $100
            ),
        ]

        summary = aggregate_deductions_by_period(
            expenses, date(2026, 1, 1), date(2026, 1, 31)
        )

        assert summary.total_amount_cents == 20000
        assert summary.total_deductible_cents == 15000
        assert summary.nondeductible_cents == 5000
        cat_summary = summary.categories[DeductionCategory.UTILITIES]
        assert cat_summary.average_business_use_percent == 75


class TestAggregateDeductionsByCategory:
    """Test category-based aggregation without date filtering."""

    def test_aggregate_all_categories(self):
        """Aggregate deductions by category across all dates."""
        expenses = [
            DeductibleExpense(
                bill_id=1,
                bill_number="BILL-001",
                bill_date=date(2026, 1, 15),
                vendor_id=1,
                vendor_name="Vendor A",
                category=DeductionCategory.SUPPLIES,
                description="Supplies",
                amount_cents=5000,
                business_use_percent=100,
                deductible_amount_cents=5000,
            ),
            DeductibleExpense(
                bill_id=2,
                bill_number="BILL-002",
                bill_date=date(2026, 6, 20),
                vendor_id=2,
                vendor_name="ISP",
                category=DeductionCategory.UTILITIES,
                description="Internet",
                amount_cents=10000,
                business_use_percent=80,
                deductible_amount_cents=8000,
            ),
        ]

        by_category = aggregate_deductions_by_category(expenses)

        assert len(by_category) == 2
        assert by_category[DeductionCategory.SUPPLIES].total_amount_cents == 5000
        assert by_category[DeductionCategory.UTILITIES].total_amount_cents == 10000


class TestIdentifyTaxBreaks:
    """Test tax break identification from expense patterns."""

    def test_identify_home_office(self):
        """Identify home office deduction opportunity."""
        expenses = [
            DeductibleExpense(
                bill_id=1,
                bill_number="BILL-001",
                bill_date=date(2026, 1, 15),
                vendor_id=1,
                vendor_name="Landlord",
                category=DeductionCategory.HOME_OFFICE,
                description="Home office utilities",
                amount_cents=20000,  # $200/month
                business_use_percent=100,
                deductible_amount_cents=20000,
            ),
        ]

        breaks = identify_tax_breaks(expenses, income_cents=100000 * 100)

        home_office_breaks = [b for b in breaks if b.opportunity_type == "home_office"]
        assert len(home_office_breaks) > 0
        assert home_office_breaks[0].current_deduction_cents == 20000

    def test_identify_vehicle_deduction(self):
        """Identify vehicle mileage deduction opportunity."""
        expenses = [
            DeductibleExpense(
                bill_id=1,
                bill_number="BILL-001",
                bill_date=date(2026, 1, 15),
                vendor_id=1,
                vendor_name="Shell",
                category=DeductionCategory.VEHICLE,
                description="Fuel",
                amount_cents=10000,
                business_use_percent=100,
                deductible_amount_cents=10000,
            ),
        ]

        breaks = identify_tax_breaks(expenses, income_cents=100000 * 100)

        vehicle_breaks = [b for b in breaks if b.opportunity_type == "vehicle_mileage"]
        assert len(vehicle_breaks) > 0

    def test_identify_meal_deduction(self):
        """Identify meal expense deduction (50% limitation)."""
        expenses = [
            DeductibleExpense(
                bill_id=1,
                bill_number="BILL-001",
                bill_date=date(2026, 1, 15),
                vendor_id=1,
                vendor_name="Restaurant",
                category=DeductionCategory.MEALS,
                description="Business meal",
                amount_cents=5000,
                business_use_percent=100,
                deductible_amount_cents=5000,
            ),
        ]

        breaks = identify_tax_breaks(expenses, income_cents=100000 * 100)

        meal_breaks = [b for b in breaks if b.opportunity_type == "meal_optimization"]
        assert len(meal_breaks) > 0


class TestDetectHobbyLoss:
    """Test hobby-loss analysis (IRC Section 183)."""

    def test_presumed_profit_motive(self):
        """Activity presumed for-profit if 3+ years of profit."""
        analysis = detect_hobby_loss(
            activity_description="Consulting",
            income_by_year={2021: 100000 * 100, 2022: 80000 * 100, 2023: 120000 * 100, 2024: 50000 * 100, 2025: 200000 * 100},
            expenses_by_year={2021: 30000 * 100, 2022: 25000 * 100, 2023: 40000 * 100, 2024: 60000 * 100, 2025: 20000 * 100},
        )

        assert not analysis.is_hobby  # 4 years of profit = presumed for-profit (3+ required)
        assert analysis.profit_count == 4
        assert analysis.loss_count == 1

    def test_presumed_hobby_2_consecutive_losses(self):
        """Activity presumed hobby if 2+ consecutive years of loss."""
        analysis = detect_hobby_loss(
            activity_description="Crafts",
            income_by_year={2021: 10000 * 100, 2022: 20000 * 100, 2023: 5000 * 100, 2024: 8000 * 100, 2025: 3000 * 100},
            expenses_by_year={2021: 50000 * 100, 2022: 60000 * 100, 2023: 70000 * 100, 2024: 50000 * 100, 2025: 40000 * 100},
        )

        assert analysis.is_hobby
        assert analysis.consecutive_losses >= 2

    def test_hobby_deduction_limitation(self):
        """Losses deductible only to extent of income when hobby."""
        analysis = detect_hobby_loss(
            activity_description="Hobby",
            income_by_year={2021: 10000 * 100, 2022: 15000 * 100},
            expenses_by_year={2021: 50000 * 100, 2022: 60000 * 100},
        )

        assert analysis.is_hobby  # 2 consecutive loss years triggers hobby status
        # Only income-generating portion deductible
        assert analysis.nondeductible_loss_cents == ((50000 - 10000) + (60000 - 15000)) * 100
        assert analysis.deductible_loss_cents == 0

    def test_hobby_income_exceeds_expenses(self):
        """Hobby with profit allows full deduction."""
        analysis = detect_hobby_loss(
            activity_description="Profitable Hobby",
            income_by_year={2021: 100000 * 100},
            expenses_by_year={2021: 50000 * 100},
        )

        assert not analysis.is_hobby  # One profitable year
        assert analysis.deductible_loss_cents == 0
