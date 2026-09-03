"""Deduction aggregation and tax-break identification (Step 13, Phase 1).

Immutable value objects for deductible expense tracking, deduction summarization,
tax-break opportunity identification, and hobby-loss analysis.

Locked decisions honored:

* D-3: Money as signed integer USD cents; all amounts stored as int
* HR-1: Append-only; deductions are derived from posted bills, never mutated
* CK-5/CK-6: Validation at creation time (frozen dataclasses with __post_init__)
* T-11: Deductibility respects business-use percentage (0-100%) from expense posting
* Tax break identification follows IRS rules (home office, vehicle, etc.)
* Hobby loss detection: income < expenses = hobby loss (IRC §183)

Purity contract (hard rule 1): standard library only; no I/O of any kind,
no clock reads, no randomness.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Iterable, NamedTuple

__all__ = [
    "DeductionCategory",
    "DeductionType",
    "DeductibleExpense",
    "DeductionSummary",
    "CategorySummary",
    "TaxBreakOpportunity",
    "HobbyLossAnalysis",
    "DeductionError",
    "DeductionValidationError",
    "aggregate_deductions_by_period",
    "aggregate_deductions_by_category",
    "identify_tax_breaks",
    "detect_hobby_loss",
    "filter_deductible_expenses",
]


class DeductionError(ValueError):
    """Base error for deduction operations."""


class DeductionValidationError(DeductionError):
    """Deduction validation failed."""


class DeductionCategory(Enum):
    """IRS-aligned expense categories eligible for Schedule C or self-employment deductions."""

    SUPPLIES = "supplies"  # Office/operating supplies
    UTILITIES = "utilities"  # Electric, water, gas
    RENT = "rent"  # Office space rent
    EQUIPMENT = "equipment"  # Machinery, tools (depreciable)
    REPAIRS = "repairs"  # Repairs & maintenance
    INSURANCE = "insurance"  # Business insurance
    VEHICLE = "vehicle"  # Vehicle expenses (gas, maintenance)
    MEALS = "meals"  # Business meals (50% deductible)
    TRAVEL = "travel"  # Travel expenses
    PROFESSIONAL_SERVICES = "professional_services"  # Legal, accounting, consulting
    ADVERTISING = "advertising"  # Marketing, advertising
    SUBSCRIPTIONS = "subscriptions"  # Software, publications
    EDUCATION = "education"  # Business education & training
    PHONE = "phone"  # Business phone & internet
    HOME_OFFICE = "home_office"  # Home office deduction
    OTHER = "other"  # Miscellaneous business expense


class DeductionType(Enum):
    """Type of deduction recognized by IRS."""

    ORDINARY = "ordinary"  # Ordinary and necessary for trade/business
    REASONABLE_SALARY = "reasonable_salary"  # Reasonable salary to owner
    HOME_OFFICE = "home_office"  # Home office (simplified or actual)
    VEHICLE_MILEAGE = "vehicle_mileage"  # Standard mileage rate
    MEAL_ENTERTAINMENT = "meal_entertainment"  # 50% or 100% depending on type
    EDUCATION = "education"  # Legitimate business education
    CHARITABLE = "charitable"  # Charitable contributions (limited)
    CASUALTY_LOSS = "casualty_loss"  # Casualty/disaster loss
    HOBBY_RELATED = "hobby_related"  # Only if hobby generates income
    NONDEDUCTIBLE = "nondeductible"  # Not deductible


class DeductionLimitationType(Enum):
    """Type of limitation applied to deduction."""

    NONE = "none"  # No limitation
    PERCENTAGE = "percentage"  # Limited to percentage (e.g., 50% of meals)
    PASSIVE_ACTIVITY = "passive_activity"  # Passive activity loss limit
    HOBBY_LOSS = "hobby_loss"  # Hobby loss limitation (IRC 183)
    AMT_EXCLUSION = "amt_exclusion"  # AMT adjustment


class DeductibleExpense(NamedTuple):
    """A single deductible expense from a posted bill line item.

    Attributes:
        bill_id: Bill containing this expense
        bill_number: Bill number for reference
        bill_date: Date expense was incurred
        vendor_id: Vendor who provided goods/services
        vendor_name: Vendor name for reference
        category: IRS-aligned expense category
        description: Expense description
        amount_cents: Full expense amount (signed int cents)
        business_use_percent: Business-use percentage (0-100)
        deductible_amount_cents: Calculated deductible amount
        deduction_type: Type of deduction (ordinary, home_office, etc.)
        limitation_type: Any limitation applied
    """

    bill_id: int
    bill_number: str
    bill_date: date
    vendor_id: int
    vendor_name: str
    category: DeductionCategory
    description: str
    amount_cents: int
    business_use_percent: int  # 0-100
    deductible_amount_cents: int
    deduction_type: DeductionType = DeductionType.ORDINARY
    limitation_type: DeductionLimitationType = DeductionLimitationType.NONE


@dataclass(frozen=True)
class CategorySummary:
    """Summary of deductions in a single category."""

    category: DeductionCategory
    total_amount_cents: int
    total_deductible_cents: int
    count: int
    average_business_use_percent: int

    def __post_init__(self) -> None:
        if self.total_amount_cents < 0:
            raise DeductionValidationError("Total amount must be non-negative")
        if self.total_deductible_cents < 0:
            raise DeductionValidationError("Total deductible must be non-negative")
        if self.count < 0:
            raise DeductionValidationError("Count must be non-negative")
        if not (0 <= self.average_business_use_percent <= 100):
            raise DeductionValidationError("Average business-use percent must be 0-100")


@dataclass(frozen=True)
class DeductionSummary:
    """Summary of all deductions for a period or entity.

    Aggregates deductible expenses by category, providing totals and statistics
    for tax planning and reporting.
    """

    start_date: date
    end_date: date
    total_amount_cents: int  # Sum of all expenses (full amount)
    total_deductible_cents: int  # Sum of all deductible portions
    count: int  # Total number of expenses
    categories: dict[DeductionCategory, CategorySummary]
    nondeductible_cents: int  # Amount that is not deductible

    def __post_init__(self) -> None:
        if self.end_date < self.start_date:
            raise DeductionValidationError(
                f"End date {self.end_date} cannot be before start date {self.start_date}"
            )
        if self.total_amount_cents < 0:
            raise DeductionValidationError("Total amount must be non-negative")
        if self.total_deductible_cents < 0:
            raise DeductionValidationError("Total deductible must be non-negative")
        if self.count < 0:
            raise DeductionValidationError("Count must be non-negative")
        if self.nondeductible_cents < 0:
            raise DeductionValidationError("Nondeductible amount must be non-negative")

        # Verify total consistency
        expected_total = self.total_deductible_cents + self.nondeductible_cents
        if self.total_amount_cents != expected_total:
            raise DeductionValidationError(
                f"Total amount ({self.total_amount_cents}) does not equal "
                f"deductible ({self.total_deductible_cents}) + nondeductible ({self.nondeductible_cents})"
            )

    def deduction_rate(self) -> float:
        """Percentage of total expenses that are deductible (0-100)."""
        if self.total_amount_cents == 0:
            return 0.0
        return (self.total_deductible_cents / self.total_amount_cents) * 100


@dataclass(frozen=True)
class TaxBreakOpportunity:
    """Identified tax break or optimization opportunity.

    Represents a deduction opportunity or tax optimization strategy
    that can reduce tax liability.
    """

    opportunity_type: str  # "home_office", "vehicle_mileage", "quarterly_payments", etc.
    description: str
    current_deduction_cents: int  # Amount currently claimed
    potential_deduction_cents: int  # Amount that could be claimed
    tax_savings_cents: int  # Estimated tax savings (at marginal rate)
    estimated_marginal_rate: float  # Estimated tax rate (as decimal, e.g., 0.24)
    applicable_periods: list[date]  # Fiscal periods where applicable
    status: str  # "available", "in_progress", "claimed", "ineligible"
    notes: str | None = None
    requirements: list[str] | None = None  # What's needed to claim

    def __post_init__(self) -> None:
        if self.current_deduction_cents < 0:
            raise DeductionValidationError("Current deduction must be non-negative")
        if self.potential_deduction_cents < 0:
            raise DeductionValidationError("Potential deduction must be non-negative")
        if self.tax_savings_cents < 0:
            raise DeductionValidationError("Tax savings must be non-negative")
        if not (0 <= self.estimated_marginal_rate <= 1.0):
            raise DeductionValidationError("Marginal rate must be 0-1.0")
        if self.potential_deduction_cents < self.current_deduction_cents:
            raise DeductionValidationError(
                "Potential deduction cannot be less than current deduction"
            )


@dataclass(frozen=True)
class HobbyLossAnalysis:
    """Analysis for hobby-loss determination (IRC Section 183).

    The IRS presumes an activity is engaged in for profit if it has a
    profit in 3 or more of the last 5 years. Conversely, if expenses
    exceed income for 2+ consecutive years, the activity is presumed
    to be a hobby, and losses are not deductible.
    """

    activity_description: str
    years_analyzed: list[int]
    income_by_year: dict[int, int]  # {year: income_cents}
    expenses_by_year: dict[int, int]  # {year: expense_cents}
    profit_count: int  # Years with profit
    loss_count: int  # Years with loss
    consecutive_losses: int  # Longest streak of consecutive losses
    is_hobby: bool  # True if presumed hobby under IRC 183
    deductible_loss_cents: int  # Loss amount that can be deducted
    nondeductible_loss_cents: int  # Loss amount that cannot be deducted
    notes: str | None = None

    def __post_init__(self) -> None:
        if not self.activity_description or not self.activity_description.strip():
            raise DeductionValidationError("Activity description is required")
        if not self.years_analyzed:
            raise DeductionValidationError("At least one year must be analyzed")
        if self.profit_count < 0 or self.loss_count < 0:
            raise DeductionValidationError("Profit and loss counts must be non-negative")
        if self.consecutive_losses < 0:
            raise DeductionValidationError("Consecutive loss count must be non-negative")

        # Verify income/expenses dictionaries match years
        for year in self.years_analyzed:
            if year not in self.income_by_year:
                raise DeductionValidationError(f"Missing income data for year {year}")
            if year not in self.expenses_by_year:
                raise DeductionValidationError(f"Missing expense data for year {year}")

        if self.deductible_loss_cents < 0 or self.nondeductible_loss_cents < 0:
            raise DeductionValidationError("Loss amounts must be non-negative")


def filter_deductible_expenses(
    expenses: Iterable[DeductibleExpense],
    category: DeductionCategory | None = None,
    min_date: date | None = None,
    max_date: date | None = None,
) -> list[DeductibleExpense]:
    """Filter deductible expenses by category and/or date range.

    Args:
        expenses: Iterable of DeductibleExpense objects
        category: Optional category to filter by (None = all categories)
        min_date: Optional earliest date (inclusive)
        max_date: Optional latest date (inclusive)

    Returns:
        List of DeductibleExpense objects matching filters
    """
    result: list[DeductibleExpense] = []
    for expense in expenses:
        if category is not None and expense.category != category:
            continue
        if min_date is not None and expense.bill_date < min_date:
            continue
        if max_date is not None and expense.bill_date > max_date:
            continue
        result.append(expense)
    return result


def aggregate_deductions_by_period(
    expenses: Iterable[DeductibleExpense],
    start_date: date,
    end_date: date,
) -> DeductionSummary:
    """Aggregate deductible expenses into a period summary.

    Creates a DeductionSummary for all expenses within a date range,
    broken down by category.

    Args:
        expenses: Iterable of DeductibleExpense objects
        start_date: Period start date (inclusive)
        end_date: Period end date (inclusive)

    Returns:
        DeductionSummary for the period
    """
    filtered = filter_deductible_expenses(
        expenses, min_date=start_date, max_date=end_date
    )

    total_amount = 0
    total_deductible = 0
    category_totals: dict[DeductionCategory, dict[str, int]] = {}

    for expense in filtered:
        total_amount += expense.amount_cents
        total_deductible += expense.deductible_amount_cents

        if expense.category not in category_totals:
            category_totals[expense.category] = {
                "amount": 0,
                "deductible": 0,
                "count": 0,
                "business_use_sum": 0,
            }

        cat_data = category_totals[expense.category]
        cat_data["amount"] += expense.amount_cents
        cat_data["deductible"] += expense.deductible_amount_cents
        cat_data["count"] += 1
        cat_data["business_use_sum"] += expense.business_use_percent

    # Build category summaries
    categories: dict[DeductionCategory, CategorySummary] = {}
    for category, data in category_totals.items():
        avg_business_use = (
            data["business_use_sum"] // data["count"] if data["count"] > 0 else 0
        )
        categories[category] = CategorySummary(
            category=category,
            total_amount_cents=data["amount"],
            total_deductible_cents=data["deductible"],
            count=data["count"],
            average_business_use_percent=avg_business_use,
        )

    nondeductible = total_amount - total_deductible

    return DeductionSummary(
        start_date=start_date,
        end_date=end_date,
        total_amount_cents=total_amount,
        total_deductible_cents=total_deductible,
        count=len(filtered),
        categories=categories,
        nondeductible_cents=nondeductible,
    )


def aggregate_deductions_by_category(
    expenses: Iterable[DeductibleExpense],
) -> dict[DeductionCategory, CategorySummary]:
    """Aggregate deductible expenses by category only (no date filtering).

    Returns a dictionary mapping DeductionCategory to CategorySummary.

    Args:
        expenses: Iterable of DeductibleExpense objects

    Returns:
        Dictionary of DeductionCategory -> CategorySummary
    """
    category_totals: dict[DeductionCategory, dict[str, int]] = {}

    for expense in expenses:
        if expense.category not in category_totals:
            category_totals[expense.category] = {
                "amount": 0,
                "deductible": 0,
                "count": 0,
                "business_use_sum": 0,
            }

        cat_data = category_totals[expense.category]
        cat_data["amount"] += expense.amount_cents
        cat_data["deductible"] += expense.deductible_amount_cents
        cat_data["count"] += 1
        cat_data["business_use_sum"] += expense.business_use_percent

    # Build category summaries
    result: dict[DeductionCategory, CategorySummary] = {}
    for category, data in category_totals.items():
        avg_business_use = (
            data["business_use_sum"] // data["count"] if data["count"] > 0 else 0
        )
        result[category] = CategorySummary(
            category=category,
            total_amount_cents=data["amount"],
            total_deductible_cents=data["deductible"],
            count=data["count"],
            average_business_use_percent=avg_business_use,
        )

    return result


def identify_tax_breaks(
    expenses: Iterable[DeductibleExpense],
    income_cents: int = 0,
    estimated_marginal_rate: float = 0.24,
) -> list[TaxBreakOpportunity]:
    """Identify potential tax-break opportunities based on expense patterns.

    Analyzes deductions to identify unclaimed or under-claimed opportunities:
    - Home office deduction (if home office expenses exist)
    - Vehicle mileage (if vehicle category expenses exist)
    - Meal and entertainment optimization (50% vs 100% categorization)
    - Quarterly estimated payment timing
    - Education and training deductions
    - Equipment depreciation/Section 179

    Args:
        expenses: Iterable of DeductibleExpense objects
        income_cents: Estimated income for the period (for qualified business income)
        estimated_marginal_rate: Expected marginal tax rate (default 0.24 = 24%)

    Returns:
        List of TaxBreakOpportunity objects
    """
    opportunities: list[TaxBreakOpportunity] = []
    exp_list = list(expenses)

    # Check for home office expenses
    home_office_exps = [e for e in exp_list if e.category == DeductionCategory.HOME_OFFICE]
    if home_office_exps:
        total_home_office = sum(e.deductible_amount_cents for e in home_office_exps)
        tax_savings = int(total_home_office * estimated_marginal_rate)
        opportunities.append(
            TaxBreakOpportunity(
                opportunity_type="home_office",
                description="Home office deduction opportunity",
                current_deduction_cents=total_home_office,
                potential_deduction_cents=total_home_office,
                tax_savings_cents=tax_savings,
                estimated_marginal_rate=estimated_marginal_rate,
                applicable_periods=[e.bill_date for e in home_office_exps],
                status="available",
                requirements=["Dedicated office space", "Business exclusive use"],
            )
        )

    # Check for vehicle expenses (could use mileage method instead)
    vehicle_exps = [e for e in exp_list if e.category == DeductionCategory.VEHICLE]
    if vehicle_exps:
        total_vehicle = sum(e.deductible_amount_cents for e in vehicle_exps)
        # Suggest reviewing mileage method as alternative
        opportunities.append(
            TaxBreakOpportunity(
                opportunity_type="vehicle_mileage",
                description="Consider standard mileage rate vs. actual expense method",
                current_deduction_cents=total_vehicle,
                potential_deduction_cents=total_vehicle,  # May vary
                tax_savings_cents=0,  # Requires calculation
                estimated_marginal_rate=estimated_marginal_rate,
                applicable_periods=[e.bill_date for e in vehicle_exps],
                status="in_progress",
                notes="Compare standard mileage rate ($0.67/mile for 2024) to actual expenses",
            )
        )

    # Check for meal expenses (50% deductibility)
    meal_exps = [e for e in exp_list if e.category == DeductionCategory.MEALS]
    if meal_exps:
        total_meals = sum(e.deductible_amount_cents for e in meal_exps)
        # Note: Some meals may be 100% (employer provided, etc.)
        opportunities.append(
            TaxBreakOpportunity(
                opportunity_type="meal_optimization",
                description="Verify 50% vs. 100% deductibility of meal expenses",
                current_deduction_cents=total_meals,
                potential_deduction_cents=total_meals,
                tax_savings_cents=0,
                estimated_marginal_rate=estimated_marginal_rate,
                applicable_periods=[e.bill_date for e in meal_exps],
                status="available",
                requirements=["Documentation of business purpose", "Attendee information"],
            )
        )

    # Check for education expenses
    education_exps = [e for e in exp_list if e.category == DeductionCategory.EDUCATION]
    if education_exps:
        total_education = sum(e.deductible_amount_cents for e in education_exps)
        tax_savings = int(total_education * estimated_marginal_rate)
        opportunities.append(
            TaxBreakOpportunity(
                opportunity_type="education",
                description="Business education and training deduction",
                current_deduction_cents=total_education,
                potential_deduction_cents=total_education,
                tax_savings_cents=tax_savings,
                estimated_marginal_rate=estimated_marginal_rate,
                applicable_periods=[e.bill_date for e in education_exps],
                status="claimed",
                requirements=[
                    "Course related to current trade/business",
                    "Does not lead to new trade",
                ],
            )
        )

    return opportunities


def detect_hobby_loss(
    activity_description: str,
    income_by_year: dict[int, int],
    expenses_by_year: dict[int, int],
) -> HobbyLossAnalysis:
    """Detect hobby-loss status under IRC Section 183.

    The IRS presumes profit motive if activity has profit in 3+ of last 5 years.
    Presumes hobby if no profit in 2+ consecutive years.

    Args:
        activity_description: Description of the activity (e.g., "Consulting", "Crafts")
        income_by_year: Dictionary of {year: income_cents}
        expenses_by_year: Dictionary of {year: expense_cents}

    Returns:
        HobbyLossAnalysis with hobby status and deductible loss calculation
    """
    if not income_by_year or not expenses_by_year:
        raise DeductionValidationError("Must provide income and expense data")

    all_years = sorted(set(income_by_year.keys()) | set(expenses_by_year.keys()))
    if not all_years:
        raise DeductionValidationError("No year data provided")

    profit_count = 0
    loss_count = 0
    consecutive_losses = 0
    max_consecutive = 0
    current_streak = 0
    total_loss = 0

    for year in all_years:
        income = income_by_year.get(year, 0)
        expenses = expenses_by_year.get(year, 0)
        net = income - expenses

        if net > 0:
            profit_count += 1
            current_streak = 0
        else:
            loss_count += 1
            current_streak += 1
            if current_streak > max_consecutive:
                max_consecutive = current_streak
            total_loss += abs(net)

    consecutive_losses = max_consecutive

    # IRC 183 hobby loss: presumed hobby if no profit in 2+ consecutive years
    # or less than 3 profitable years in last 5 years
    is_hobby = consecutive_losses >= 2 or (len(all_years) >= 3 and profit_count < 3)

    # If hobby, only deductible to extent of income
    total_income = sum(income_by_year.values())
    total_expenses = sum(expenses_by_year.values())
    net_total = total_income - total_expenses

    if is_hobby and net_total < 0:
        # Only income-generating portion of expenses is deductible
        deductible_loss = 0
        nondeductible_loss = total_expenses - total_income
    else:
        # All expenses deductible
        deductible_loss = abs(net_total) if net_total < 0 else 0
        nondeductible_loss = 0

    return HobbyLossAnalysis(
        activity_description=activity_description,
        years_analyzed=all_years,
        income_by_year=income_by_year,
        expenses_by_year=expenses_by_year,
        profit_count=profit_count,
        loss_count=loss_count,
        consecutive_losses=consecutive_losses,
        is_hobby=is_hobby,
        deductible_loss_cents=deductible_loss,
        nondeductible_loss_cents=nondeductible_loss,
    )
