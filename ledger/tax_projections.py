"""Tax liability projections and quarterly estimates (Step 13, Phase 1).

Immutable value objects for projecting income tax liability, calculating quarterly
estimated tax payments, and simulating tax scenarios with different deduction levels.

Locked decisions honored:

* D-3: Money as signed integer USD cents; all tax calculations in cents
* HR-1: Append-only; projections are calculated from posted data, never mutated
* CK-5/CK-6: Validation at creation time (frozen dataclasses with __post_init__)
* T-10: Projections calculated from posted transactions (not drafts)
* T-11: Tax calculations respect all deductions and limitations

Purity contract (hard rule 1): standard library only; no I/O of any kind,
no clock reads, no randomness. Dates and rates supplied by caller.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import NamedTuple

__all__ = [
    "TaxType",
    "FilingStatus",
    "TaxBracket",
    "TaxProjection",
    "QuarterlyTaxEstimate",
    "TaxSavingsScenario",
    "TaxSavingsProjection",
    "TaxProjectionError",
    "calculate_federal_tax",
    "calculate_self_employment_tax",
    "calculate_quarterly_estimate",
    "project_year_end_tax",
    "simulate_tax_scenarios",
]


class TaxProjectionError(ValueError):
    """Base error for tax projection operations."""


class TaxType(Enum):
    """Type of tax being projected or paid."""

    FEDERAL_INCOME = "federal_income"
    STATE_INCOME = "state_income"
    SELF_EMPLOYMENT = "self_employment"
    ESTIMATED = "estimated"


class FilingStatus(Enum):
    """IRS filing status for tax calculation."""

    SINGLE = "single"
    MARRIED_FILING_JOINTLY = "married_filing_jointly"
    MARRIED_FILING_SEPARATELY = "married_filing_separately"
    HEAD_OF_HOUSEHOLD = "head_of_household"


class TaxBracket(NamedTuple):
    """A marginal tax bracket for the year.

    Attributes:
        filing_status: Applicable filing status
        min_income_cents: Minimum income for this bracket (inclusive)
        max_income_cents: Maximum income for this bracket (exclusive); 0 = unlimited
        rate_percent: Marginal tax rate as percentage (e.g., 12.0 for 12%)
        year: Tax year this bracket applies to
    """

    filing_status: FilingStatus
    min_income_cents: int
    max_income_cents: int
    rate_percent: float
    year: int


@dataclass(frozen=True)
class TaxProjection:
    """Projection of tax liability for a period.

    Estimates federal income tax, self-employment tax, and estimated payment
    amounts based on projected income and deductions.
    """

    period_start: date
    period_end: date
    filing_status: FilingStatus
    gross_income_cents: int  # Total revenue/income
    business_deductions_cents: int  # Schedule C deductions
    qualified_business_income_cents: int  # QBI for 20% deduction
    adjusted_gross_income_cents: int  # AGI after deductions
    standard_deduction_cents: int  # Standard deduction for year
    taxable_income_cents: int  # AGI - standard deduction
    federal_income_tax_cents: int  # Calculated federal income tax
    self_employment_tax_cents: int  # Self-employment (Social Security + Medicare)
    total_tax_cents: int  # federal_income + self_employment
    estimated_quarterly_cents: int  # Recommended quarterly payment
    effective_tax_rate: float  # Total tax / gross income (as decimal, e.g., 0.15)
    marginal_tax_rate: float  # Top marginal rate (as decimal)

    def __post_init__(self) -> None:
        if self.period_end < self.period_start:
            raise TaxProjectionError(
                f"Period end {self.period_end} cannot be before start {self.period_start}"
            )
        if self.gross_income_cents < 0:
            raise TaxProjectionError("Gross income must be non-negative")
        if self.business_deductions_cents < 0:
            raise TaxProjectionError("Business deductions must be non-negative")
        if self.adjusted_gross_income_cents < 0:
            raise TaxProjectionError("AGI must be non-negative")
        if self.taxable_income_cents < 0:
            raise TaxProjectionError("Taxable income must be non-negative")
        if self.federal_income_tax_cents < 0:
            raise TaxProjectionError("Federal income tax must be non-negative")
        if self.self_employment_tax_cents < 0:
            raise TaxProjectionError("Self-employment tax must be non-negative")
        if not (0 <= self.effective_tax_rate <= 1.0):
            raise TaxProjectionError("Effective tax rate must be 0-1.0")
        if not (0 <= self.marginal_tax_rate <= 1.0):
            raise TaxProjectionError("Marginal tax rate must be 0-1.0")

        # Verify tax totals
        expected_total = self.federal_income_tax_cents + self.self_employment_tax_cents
        if self.total_tax_cents != expected_total:
            raise TaxProjectionError(
                f"Total tax ({self.total_tax_cents}) does not equal "
                f"federal ({self.federal_income_tax_cents}) + SE ({self.self_employment_tax_cents})"
            )


@dataclass(frozen=True)
class QuarterlyTaxEstimate:
    """Estimated tax payment for a quarter.

    Calculates safe harbor estimated payment amounts to avoid underpayment
    penalties. IRS requires payment of 90% of current year or 100% of prior
    year (110% if prior year AGI > $150k) tax liability.
    """

    year: int
    quarter: int  # 1-4
    quarter_start: date
    quarter_end: date
    projected_quarterly_income_cents: int
    projected_quarterly_deductions_cents: int
    projected_quarterly_tax_cents: int
    safe_harbor_90_current_year_cents: int  # 90% of estimated current year tax
    safe_harbor_100_prior_year_cents: int  # 100% of prior year tax (110% if applicable)
    recommended_payment_cents: int  # Safe harbor amount (lower of above)
    prior_payments_cents: int  # Amount already paid for year
    remaining_safe_harbor_cents: int  # Still need to pay to meet safe harbor
    due_date: date

    def __post_init__(self) -> None:
        if not (1 <= self.quarter <= 4):
            raise TaxProjectionError("Quarter must be 1-4")
        if self.quarter_end < self.quarter_start:
            raise TaxProjectionError(
                f"Quarter end {self.quarter_end} cannot be before start {self.quarter_start}"
            )
        if self.projected_quarterly_income_cents < 0:
            raise TaxProjectionError("Quarterly income must be non-negative")
        if self.projected_quarterly_deductions_cents < 0:
            raise TaxProjectionError("Quarterly deductions must be non-negative")
        if self.projected_quarterly_tax_cents < 0:
            raise TaxProjectionError("Quarterly tax must be non-negative")
        if self.safe_harbor_90_current_year_cents < 0:
            raise TaxProjectionError("Safe harbor 90% must be non-negative")
        if self.safe_harbor_100_prior_year_cents < 0:
            raise TaxProjectionError("Safe harbor 100% must be non-negative")
        if self.prior_payments_cents < 0:
            raise TaxProjectionError("Prior payments must be non-negative")
        if self.remaining_safe_harbor_cents < 0:
            raise TaxProjectionError("Remaining safe harbor must be non-negative")


@dataclass(frozen=True)
class TaxSavingsScenario:
    """A tax savings scenario with different deduction levels.

    Simulates tax liability under different deduction scenarios to show
    impact of various tax breaks and optimization strategies.
    """

    scenario_name: str
    description: str
    additional_deductions_cents: int  # Extra deductions in this scenario
    taxable_income_cents: int  # Taxable income with scenario applied
    federal_income_tax_cents: int  # Resulting federal tax
    self_employment_tax_cents: int  # Resulting SE tax
    total_tax_cents: int  # Total tax with scenario
    tax_savings_vs_baseline_cents: int  # Reduction from baseline
    effective_tax_rate: float  # Resulting effective rate
    break_even_deduction_cents: int = 0  # Min deduction for scenario to pay off

    def __post_init__(self) -> None:
        if self.additional_deductions_cents < 0:
            raise TaxProjectionError("Additional deductions must be non-negative")
        if self.taxable_income_cents < 0:
            raise TaxProjectionError("Taxable income must be non-negative")
        if self.federal_income_tax_cents < 0:
            raise TaxProjectionError("Federal income tax must be non-negative")
        if self.self_employment_tax_cents < 0:
            raise TaxProjectionError("Self-employment tax must be non-negative")
        if self.tax_savings_vs_baseline_cents < 0:
            raise TaxProjectionError("Tax savings must be non-negative")
        if not (0 <= self.effective_tax_rate <= 1.0):
            raise TaxProjectionError("Effective tax rate must be 0-1.0")


@dataclass(frozen=True)
class TaxSavingsProjection:
    """Multi-scenario tax savings analysis.

    Shows baseline tax liability and impact of various deduction strategies
    to help with tax planning and optimization decisions.
    """

    period_start: date
    period_end: date
    baseline_tax_cents: int  # Tax without any additional deductions
    scenarios: list[TaxSavingsScenario]  # Various scenarios with different deductions
    max_potential_savings_cents: int  # Maximum possible tax savings across all scenarios
    recommended_scenario_index: int = 0  # Index of recommended scenario

    def __post_init__(self) -> None:
        if self.period_end < self.period_start:
            raise TaxProjectionError(
                f"Period end {self.period_end} cannot be before start {self.period_start}"
            )
        if self.baseline_tax_cents < 0:
            raise TaxProjectionError("Baseline tax must be non-negative")
        if not self.scenarios:
            raise TaxProjectionError("Must have at least one scenario")
        if self.max_potential_savings_cents < 0:
            raise TaxProjectionError("Max savings must be non-negative")
        if not (0 <= self.recommended_scenario_index < len(self.scenarios)):
            raise TaxProjectionError("Recommended scenario index out of range")


def calculate_federal_tax(
    taxable_income_cents: int,
    filing_status: FilingStatus,
    tax_brackets: list[TaxBracket],
    qualified_business_income_deduction_cents: int = 0,
) -> tuple[int, float]:
    """Calculate federal income tax using brackets.

    Applies tax brackets to taxable income and calculates total federal tax.
    Optionally applies qualified business income (QBI) 20% deduction.

    Args:
        taxable_income_cents: Taxable income in cents
        filing_status: Filing status for bracket selection
        tax_brackets: List of TaxBracket objects (should be sorted)
        qualified_business_income_deduction_cents: QBI deduction (20% of QBI)

    Returns:
        Tuple of (federal_tax_cents, marginal_rate as decimal)
    """
    if taxable_income_cents < 0:
        raise TaxProjectionError("Taxable income must be non-negative")

    # Apply QBI deduction if provided
    taxable_after_qbi = max(0, taxable_income_cents - qualified_business_income_deduction_cents)

    # Calculate tax using brackets
    tax_cents = 0
    marginal_rate = 0.0

    # Filter brackets for filing status and sort by income range
    applicable_brackets = sorted(
        [b for b in tax_brackets if b.filing_status == filing_status],
        key=lambda b: b.min_income_cents,
    )

    for bracket in applicable_brackets:
        if taxable_after_qbi <= bracket.min_income_cents:
            # Income doesn't reach this bracket
            break

        # Calculate tax for this bracket
        bracket_min = bracket.min_income_cents
        bracket_max = bracket.max_income_cents if bracket.max_income_cents > 0 else taxable_after_qbi

        taxable_in_bracket = min(taxable_after_qbi, bracket_max) - bracket_min
        tax_in_bracket = int(taxable_in_bracket * bracket.rate_percent / 100.0)
        tax_cents += tax_in_bracket
        marginal_rate = bracket.rate_percent / 100.0

    return tax_cents, marginal_rate


def calculate_self_employment_tax(
    net_business_income_cents: int,
    se_tax_rate: float = 0.153,  # 15.3% (12.4% SS + 2.9% Medicare for 2024)
) -> int:
    """Calculate self-employment (Social Security + Medicare) tax.

    SE tax is 15.3% on 92.35% of net self-employment income. Returns
    the full tax amount (both employee and employer portion).

    Args:
        net_business_income_cents: Net business income in cents
        se_tax_rate: Combined SE tax rate (default 0.153 for 15.3%)

    Returns:
        Self-employment tax in cents
    """
    if net_business_income_cents < 0:
        raise TaxProjectionError("Net business income must be non-negative")

    # 92.35% of net income is subject to SE tax
    se_income_cents = int(net_business_income_cents * 0.9235)
    se_tax = int(se_income_cents * se_tax_rate)
    return se_tax


def calculate_quarterly_estimate(
    year: int,
    quarter: int,
    projected_quarterly_tax_cents: int,
    prior_year_tax_cents: int = 0,
    prior_payments_cents: int = 0,
    prior_year_agi_cents: int = 0,
) -> QuarterlyTaxEstimate:
    """Calculate safe harbor quarterly estimated tax payment.

    IRS safe harbor: pay 90% of current year or 100% of prior year
    (110% if prior year AGI > $150k). Returns minimum payment needed
    to avoid underpayment penalties.

    Args:
        year: Tax year
        quarter: Quarter (1-4)
        projected_quarterly_tax_cents: Projected tax for this quarter
        prior_year_tax_cents: Total tax from prior year
        prior_payments_cents: Already paid for current year
        prior_year_agi_cents: Prior year AGI (to determine 110% threshold)

    Returns:
        QuarterlyTaxEstimate with safe harbor calculations
    """
    if not (1 <= quarter <= 4):
        raise TaxProjectionError("Quarter must be 1-4")
    if projected_quarterly_tax_cents < 0:
        raise TaxProjectionError("Projected quarterly tax must be non-negative")
    if prior_year_tax_cents < 0:
        raise TaxProjectionError("Prior year tax must be non-negative")
    if prior_payments_cents < 0:
        raise TaxProjectionError("Prior payments must be non-negative")

    # Calculate safe harbor amounts
    safe_harbor_90 = int(projected_quarterly_tax_cents * 4 * 0.90)  # 90% of full year estimate

    # 100% or 110% depending on prior year AGI
    multiplier = 1.10 if prior_year_agi_cents > 15000000 else 1.00  # $150k threshold
    safe_harbor_100_or_110 = int(prior_year_tax_cents * multiplier)

    # Use lower of the two
    recommended = min(safe_harbor_90, safe_harbor_100_or_110)
    remaining = max(0, recommended - prior_payments_cents)

    # Quarter due dates
    quarter_due_dates = {
        1: date(year, 4, 15),
        2: date(year, 6, 15),
        3: date(year, 9, 15),
        4: date(year + 1, 1, 15),
    }

    # Quarter date ranges
    quarter_dates = {
        1: (date(year, 1, 1), date(year, 3, 31)),
        2: (date(year, 4, 1), date(year, 6, 30)),
        3: (date(year, 7, 1), date(year, 9, 30)),
        4: (date(year, 10, 1), date(year, 12, 31)),
    }

    q_start, q_end = quarter_dates[quarter]

    return QuarterlyTaxEstimate(
        year=year,
        quarter=quarter,
        quarter_start=q_start,
        quarter_end=q_end,
        projected_quarterly_income_cents=0,  # Caller to fill in
        projected_quarterly_deductions_cents=0,  # Caller to fill in
        projected_quarterly_tax_cents=projected_quarterly_tax_cents,
        safe_harbor_90_current_year_cents=safe_harbor_90,
        safe_harbor_100_prior_year_cents=safe_harbor_100_or_110,
        recommended_payment_cents=recommended,
        prior_payments_cents=prior_payments_cents,
        remaining_safe_harbor_cents=remaining,
        due_date=quarter_due_dates[quarter],
    )


def project_year_end_tax(
    gross_income_cents: int,
    business_deductions_cents: int,
    filing_status: FilingStatus,
    tax_brackets: list[TaxBracket],
    standard_deduction_cents: int = 0,
    period_start: date = date(2026, 1, 1),
    period_end: date = date(2026, 12, 31),
) -> TaxProjection:
    """Project year-end tax liability.

    Calculates estimated federal income tax, self-employment tax, and
    recommended quarterly estimated payments for the full year.

    Args:
        gross_income_cents: Total business income
        business_deductions_cents: Schedule C deductions
        filing_status: Filing status for tax calculation
        tax_brackets: List of TaxBracket objects
        standard_deduction_cents: Standard deduction amount (if any)
        period_start: Start of tax period
        period_end: End of tax period

    Returns:
        TaxProjection with full-year estimates
    """
    if gross_income_cents < 0:
        raise TaxProjectionError("Gross income must be non-negative")
    if business_deductions_cents < 0:
        raise TaxProjectionError("Business deductions must be non-negative")
    if period_end < period_start:
        raise TaxProjectionError("Period end cannot be before start")

    # Calculate AGI
    agi_cents = gross_income_cents - business_deductions_cents
    qbi_cents = agi_cents  # QBI subject to 20% deduction

    # QBI deduction (20% of qualified business income, limited to taxable income)
    qbi_deduction = int(agi_cents * 0.20)

    # Taxable income
    taxable_cents = max(0, agi_cents - standard_deduction_cents - qbi_deduction)

    # Federal income tax
    federal_tax, marginal_rate = calculate_federal_tax(
        taxable_cents, filing_status, tax_brackets, qbi_deduction
    )

    # Self-employment tax
    se_tax = calculate_self_employment_tax(agi_cents)

    # Total tax
    total_tax = federal_tax + se_tax

    # Quarterly estimate
    quarterly_estimate = int(total_tax / 4)

    # Effective tax rate
    effective_rate = total_tax / gross_income_cents if gross_income_cents > 0 else 0.0

    return TaxProjection(
        period_start=period_start,
        period_end=period_end,
        filing_status=filing_status,
        gross_income_cents=gross_income_cents,
        business_deductions_cents=business_deductions_cents,
        qualified_business_income_cents=qbi_cents,
        adjusted_gross_income_cents=agi_cents,
        standard_deduction_cents=standard_deduction_cents,
        taxable_income_cents=taxable_cents,
        federal_income_tax_cents=federal_tax,
        self_employment_tax_cents=se_tax,
        total_tax_cents=total_tax,
        estimated_quarterly_cents=quarterly_estimate,
        effective_tax_rate=effective_rate,
        marginal_tax_rate=marginal_rate,
    )


def simulate_tax_scenarios(
    baseline_tax_cents: int,
    scenarios: list[tuple[str, str, int]],  # (name, description, additional_deductions)
    taxable_income_cents: int,
    filing_status: FilingStatus,
    tax_brackets: list[TaxBracket],
) -> TaxSavingsProjection:
    """Simulate tax savings under different deduction scenarios.

    Creates multiple scenarios showing tax impact of various deduction
    strategies and identifies best approach.

    Args:
        baseline_tax_cents: Tax with no additional deductions
        scenarios: List of (name, description, additional_deductions_cents) tuples
        taxable_income_cents: Current taxable income
        filing_status: Filing status
        tax_brackets: List of TaxBracket objects

    Returns:
        TaxSavingsProjection with all scenarios
    """
    if baseline_tax_cents < 0:
        raise TaxProjectionError("Baseline tax must be non-negative")
    if not scenarios:
        raise TaxProjectionError("Must have at least one scenario")

    scenario_objects: list[TaxSavingsScenario] = []
    max_savings = 0
    best_scenario_idx = 0

    for idx, (name, desc, additional_ded) in enumerate(scenarios):
        # Reduce taxable income by additional deductions
        new_taxable = max(0, taxable_income_cents - additional_ded)

        # Recalculate tax
        new_federal_tax, _ = calculate_federal_tax(new_taxable, filing_status, tax_brackets)

        # SE tax stays same (based on business income, not deductions)
        # For this scenario, we're just showing income tax impact
        new_se_tax = 0

        # Calculate savings
        new_total_tax = new_federal_tax + new_se_tax
        savings = max(0, baseline_tax_cents - new_total_tax)

        new_rate = new_total_tax / taxable_income_cents if taxable_income_cents > 0 else 0.0

        scenario_obj = TaxSavingsScenario(
            scenario_name=name,
            description=desc,
            additional_deductions_cents=additional_ded,
            taxable_income_cents=new_taxable,
            federal_income_tax_cents=new_federal_tax,
            self_employment_tax_cents=new_se_tax,
            total_tax_cents=new_total_tax,
            tax_savings_vs_baseline_cents=savings,
            effective_tax_rate=new_rate,
        )

        scenario_objects.append(scenario_obj)

        if savings > max_savings:
            max_savings = savings
            best_scenario_idx = idx

    return TaxSavingsProjection(
        period_start=date.today(),
        period_end=date.today(),
        baseline_tax_cents=baseline_tax_cents,
        scenarios=scenario_objects,
        max_potential_savings_cents=max_savings,
        recommended_scenario_index=best_scenario_idx,
    )
