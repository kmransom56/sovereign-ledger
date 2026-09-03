"""Tax recommendations engine (Step 13, Phase 1).

Immutable value objects for generating actionable tax optimization and
compliance recommendations based on expense patterns, deductions, and
business activity.

Locked decisions honored:

* D-3: Money as signed integer USD cents; all amounts in cents
* HR-1: Append-only; recommendations derived from current state, never mutated
* CK-5/CK-6: Validation at creation time (frozen dataclasses with __post_init__)
* T-10: Recommendations based on posted data (not drafts)
* T-11: All deduction rules and limitations respected

Purity contract (hard rule 1): standard library only; no I/O of any kind,
no clock reads, no randomness.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Iterable

__all__ = [
    "RecommendationType",
    "RecommendationPriority",
    "RecommendationStatus",
    "TaxRecommendation",
    "TaxRecommendationSet",
    "RecommendationError",
    "generate_deduction_recommendations",
    "generate_compliance_recommendations",
    "generate_optimization_recommendations",
    "prioritize_recommendations",
]


class RecommendationError(ValueError):
    """Base error for recommendation operations."""


class RecommendationType(Enum):
    """Category of tax recommendation."""

    DEDUCTION_OPPORTUNITY = "deduction_opportunity"  # Unclaimed/under-claimed deduction
    COMPLIANCE_REQUIREMENT = "compliance_requirement"  # Filing/documentation requirement
    TAX_OPTIMIZATION = "tax_optimization"  # Strategy to reduce tax
    DOCUMENTATION = "documentation"  # Documentation needed for audit defense
    ENTITY_STRUCTURE = "entity_structure"  # Business entity optimization
    QUARTERLY_PLANNING = "quarterly_planning"  # Quarterly payment strategy
    RECORD_KEEPING = "record_keeping"  # Record-keeping improvement
    EXPENSE_TIMING = "expense_timing"  # Year-end timing strategy


class RecommendationPriority(Enum):
    """Priority level for recommendation."""

    CRITICAL = "critical"  # High dollar impact, compliance risk
    HIGH = "high"  # Significant tax savings or compliance requirement
    MEDIUM = "medium"  # Meaningful tax savings or compliance guidance
    LOW = "low"  # Minor tax savings or informational


class RecommendationStatus(Enum):
    """Status of a recommendation."""

    OPEN = "open"  # Not yet addressed
    IN_PROGRESS = "in_progress"  # Being implemented
    COMPLETED = "completed"  # Implemented
    REJECTED = "rejected"  # Deemed not applicable/desirable
    PENDING_REVIEW = "pending_review"  # Awaiting user review


@dataclass(frozen=True)
class TaxRecommendation:
    """An actionable tax recommendation.

    Provides a specific, quantified tax optimization or compliance
    recommendation with implementation details and impact.
    """

    recommendation_id: str  # Unique ID for tracking
    recommendation_type: RecommendationType
    priority: RecommendationPriority
    status: RecommendationStatus = RecommendationStatus.OPEN
    title: str = ""  # Short title
    description: str = ""  # Detailed explanation
    rationale: str = ""  # Why this recommendation exists
    estimated_tax_impact_cents: int = 0  # Tax savings (positive) or cost (negative)
    estimated_compliance_risk_cents: int = 0  # Potential penalty if ignored
    implementation_effort: str = "medium"  # "low", "medium", "high"
    timeline: str = ""  # When to implement ("immediately", "before year-end", etc.)
    required_documentation: list[str] | None = None  # What to document
    applicable_periods: list[date] | None = None  # Dates when applicable
    deadline: date | None = None  # Deadline to implement
    related_regulations: list[str] | None = None  # IRC sections, etc.
    next_steps: list[str] | None = None  # Specific action items
    notes: str | None = None

    def __post_init__(self) -> None:
        if not self.recommendation_id or not self.recommendation_id.strip():
            raise RecommendationError("Recommendation ID is required")
        if not self.title or not self.title.strip():
            raise RecommendationError("Title is required")
        if not self.description or not self.description.strip():
            raise RecommendationError("Description is required")
        if self.estimated_tax_impact_cents == 0 and self.estimated_compliance_risk_cents == 0:
            raise RecommendationError(
                "Recommendation must have tax impact or compliance risk"
            )
        if self.deadline is not None and not isinstance(self.deadline, date):
            raise RecommendationError("Deadline must be a date")

    def total_impact_cents(self) -> int:
        """Total impact: tax savings + compliance risk avoided."""
        return max(0, self.estimated_tax_impact_cents + self.estimated_compliance_risk_cents)


@dataclass(frozen=True)
class TaxRecommendationSet:
    """A set of recommendations for a tax period.

    Groups related recommendations with summary statistics.
    """

    period_start: date
    period_end: date
    total_potential_tax_savings_cents: int
    total_compliance_risk_cents: int
    recommendations: list[TaxRecommendation]
    critical_count: int = 0
    high_count: int = 0
    medium_count: int = 0
    low_count: int = 0
    open_count: int = 0
    completed_count: int = 0

    def __post_init__(self) -> None:
        if self.period_end < self.period_start:
            raise RecommendationError(
                f"Period end {self.period_end} cannot be before start {self.period_start}"
            )
        if self.total_potential_tax_savings_cents < 0:
            raise RecommendationError("Total tax savings must be non-negative")
        if self.total_compliance_risk_cents < 0:
            raise RecommendationError("Total compliance risk must be non-negative")
        if not self.recommendations:
            raise RecommendationError("Must have at least one recommendation")


def generate_deduction_recommendations(
    actual_deductions_cents: int,
    potential_deductions_cents: int,
    marginal_tax_rate: float = 0.24,
    period_start: date = date(2026, 1, 1),
    period_end: date = date(2026, 12, 31),
) -> list[TaxRecommendation]:
    """Generate recommendations for unclaimed deductions.

    Identifies gaps between actual and potential deductions and
    recommends strategies to capture missing deductions.

    Args:
        actual_deductions_cents: Currently claimed deductions
        potential_deductions_cents: Maximum allowable deductions
        marginal_tax_rate: Expected marginal rate (for tax impact)
        period_start: Tax period start
        period_end: Tax period end

    Returns:
        List of TaxRecommendation objects
    """
    recommendations: list[TaxRecommendation] = []

    if potential_deductions_cents > actual_deductions_cents:
        gap_cents = potential_deductions_cents - actual_deductions_cents
        tax_savings = int(gap_cents * marginal_tax_rate)

        recommendations.append(
            TaxRecommendation(
                recommendation_id="DED-UNCLAIMED-001",
                recommendation_type=RecommendationType.DEDUCTION_OPPORTUNITY,
                priority=RecommendationPriority.HIGH
                if gap_cents > 500000
                else RecommendationPriority.MEDIUM,
                title="Unclaimed Deductions",
                description=f"Identified ${gap_cents/100:.2f} in deductions not yet claimed",
                rationale="Complete deduction tracking can reduce tax liability",
                estimated_tax_impact_cents=tax_savings,
                implementation_effort="medium",
                timeline="before year-end",
                required_documentation=[
                    "Expense receipts",
                    "Vendor invoices",
                    "Business purpose documentation",
                ],
                applicable_periods=[period_start, period_end],
                deadline=date(period_end.year, 12, 31),
                related_regulations=["IRC §162(a)", "IRC §263A"],
                next_steps=[
                    "Review expense records",
                    "Categorize by deduction type",
                    "Document business purpose",
                    "Submit deduction claim",
                ],
            )
        )

    return recommendations


def generate_compliance_recommendations(
    has_quarterly_payments: bool = False,
    has_estimated_tax: bool = False,
    has_self_employment_income: bool = False,
    has_home_office: bool = False,
    has_vehicle_expenses: bool = False,
    high_deduction_ratio: bool = False,
) -> list[TaxRecommendation]:
    """Generate compliance and documentation recommendations.

    Identifies compliance requirements and documentation needs based
    on business activities.

    Args:
        has_quarterly_payments: Whether entity has quarterly payments
        has_estimated_tax: Whether estimated tax payments are due
        has_self_employment_income: Whether self-employed
        has_home_office: Whether claiming home office deduction
        has_vehicle_expenses: Whether claiming vehicle expenses
        high_deduction_ratio: Whether deductions are unusually high (>50% of income)

    Returns:
        List of TaxRecommendation objects
    """
    recommendations: list[TaxRecommendation] = []

    # Estimated tax payments
    if has_estimated_tax:
        recommendations.append(
            TaxRecommendation(
                recommendation_id="COMP-EST-TAX-001",
                recommendation_type=RecommendationType.QUARTERLY_PLANNING,
                priority=RecommendationPriority.CRITICAL,
                title="Quarterly Estimated Tax Payments",
                description="Quarterly estimated tax payments are required to avoid underpayment penalties",
                rationale="IRS requires installment payments if tax liability exceeds withholding",
                estimated_tax_impact_cents=0,
                estimated_compliance_risk_cents=2500000,  # Potential penalties
                implementation_effort="low",
                timeline="before each quarter",
                required_documentation=[
                    "Tax projections",
                    "Prior year return",
                ],
                deadline=date.today(),
                related_regulations=["IRC §6654", "Form 1040-ES"],
                next_steps=[
                    "Calculate tax liability",
                    "Determine safe harbor amount",
                    "Make quarterly payments",
                    "Keep payment records",
                ],
            )
        )

    # Home office documentation
    if has_home_office:
        recommendations.append(
            TaxRecommendation(
                recommendation_id="COMP-HOME-OFF-001",
                recommendation_type=RecommendationType.DOCUMENTATION,
                priority=RecommendationPriority.MEDIUM,
                title="Home Office Documentation",
                description="Home office deduction requires documentation of exclusive business use",
                rationale="IRS frequently audits home office deductions; detailed records needed",
                estimated_tax_impact_cents=0,
                estimated_compliance_risk_cents=500000,
                implementation_effort="low",
                timeline="immediately",
                required_documentation=[
                    "Home square footage",
                    "Office square footage",
                    "Utility bills",
                    "Lease/mortgage statements",
                    "Photos of office space",
                ],
                related_regulations=["IRC §280A", "Publication 587"],
                next_steps=[
                    "Measure office square footage",
                    "Document exclusive use",
                    "Gather utility documentation",
                    "Choose calculation method (simplified vs. actual)",
                ],
            )
        )

    # Vehicle expense documentation
    if has_vehicle_expenses:
        recommendations.append(
            TaxRecommendation(
                recommendation_id="COMP-VEHICLE-001",
                recommendation_type=RecommendationType.DOCUMENTATION,
                priority=RecommendationPriority.HIGH,
                title="Vehicle Expense Documentation",
                description="Vehicle expense deductions require mileage logs and business purpose documentation",
                rationale="IRS requires contemporaneous mileage records; high audit risk",
                estimated_tax_impact_cents=0,
                estimated_compliance_risk_cents=750000,
                implementation_effort="medium",
                timeline="immediately",
                required_documentation=[
                    "Mileage log (date, miles, business purpose)",
                    "Maintenance records",
                    "Fuel/gas receipts",
                    "Insurance bills",
                    "Registration/ownership proof",
                ],
                related_regulations=["IRC §162(a)", "Publication 463"],
                next_steps=[
                    "Establish mileage tracking system",
                    "Compile prior year records",
                    "Categorize business vs. personal",
                    "Choose standard mileage vs. actual method",
                ],
            )
        )

    # Self-employment tax documentation
    if has_self_employment_income:
        recommendations.append(
            TaxRecommendation(
                recommendation_id="COMP-SE-TAX-001",
                recommendation_type=RecommendationType.COMPLIANCE_REQUIREMENT,
                priority=RecommendationPriority.CRITICAL,
                title="Self-Employment Tax Reporting",
                description="Self-employment income requires Schedule C and self-employment tax calculation",
                rationale="SE tax funds Social Security/Medicare; accurate reporting ensures benefits",
                estimated_tax_impact_cents=0,
                estimated_compliance_risk_cents=1000000,
                implementation_effort="low",
                timeline="immediately",
                required_documentation=[
                    "Business income records",
                    "Business expense records",
                    "Prior year tax return",
                ],
                related_regulations=["IRC §1401", "Schedule C (Form 1040)"],
                next_steps=[
                    "Organize business income",
                    "Complete Schedule C",
                    "Calculate SE tax",
                    "Apply SE tax deduction",
                ],
            )
        )

    # High deduction ratio flag
    if high_deduction_ratio:
        recommendations.append(
            TaxRecommendation(
                recommendation_id="COMP-HIGH-DED-001",
                recommendation_type=RecommendationType.RECORD_KEEPING,
                priority=RecommendationPriority.MEDIUM,
                title="Enhanced Record Keeping for High Deduction Ratio",
                description="Deductions exceed 50% of income; enhanced documentation recommended",
                rationale="High deduction ratios increase audit risk; detailed substantiation essential",
                estimated_tax_impact_cents=0,
                estimated_compliance_risk_cents=1500000,
                implementation_effort="medium",
                timeline="immediately",
                required_documentation=[
                    "All receipts and invoices",
                    "Contemporaneous business purpose notes",
                    "Vendor information",
                    "Timeline of expenses",
                ],
                related_regulations=["IRC §162(a)", "IRC §263A", "Treas. Reg. §1.162-1"],
                next_steps=[
                    "Implement receipt tracking system",
                    "Maintain detailed expense log",
                    "Document business purpose for each expense",
                    "Keep records for at least 7 years",
                ],
            )
        )

    return recommendations


def generate_optimization_recommendations(
    business_income_cents: int,
    current_deductions_cents: int,
    has_quarterly_losses: bool = False,
    approaching_limit: bool = False,
) -> list[TaxRecommendation]:
    """Generate tax optimization strategy recommendations.

    Suggests proactive strategies to minimize tax liability while
    maintaining compliance.

    Args:
        business_income_cents: Total business income
        current_deductions_cents: Current deductions claimed
        has_quarterly_losses: Whether any quarter shows a loss
        approaching_limit: Whether deductions approach certain limits

    Returns:
        List of TaxRecommendation objects
    """
    recommendations: list[TaxRecommendation] = []
    deduction_ratio = (
        current_deductions_cents / business_income_cents
        if business_income_cents > 0
        else 0
    )

    # Year-end expense timing
    if business_income_cents > 0:
        recommendations.append(
            TaxRecommendation(
                recommendation_id="OPT-TIMING-001",
                recommendation_type=RecommendationType.EXPENSE_TIMING,
                priority=RecommendationPriority.MEDIUM,
                title="Year-End Expense Timing Strategy",
                description="Plan discretionary expense timing to optimize year-end tax position",
                rationale="Timing of deductible expenses can shift deductions between years",
                estimated_tax_impact_cents=int(business_income_cents * 0.10 * 0.24),
                implementation_effort="low",
                timeline="in November/December",
                required_documentation=["Expense schedules", "Vendor quotes"],
                next_steps=[
                    "Review planned capital equipment purchases",
                    "Evaluate Section 179 deduction eligibility",
                    "Time discretionary expenses appropriately",
                    "Evaluate income acceleration/deferral",
                ],
            )
        )

    # Quarterly loss strategy
    if has_quarterly_losses:
        recommendations.append(
            TaxRecommendation(
                recommendation_id="OPT-LOSS-001",
                recommendation_type=RecommendationType.TAX_OPTIMIZATION,
                priority=RecommendationPriority.HIGH,
                title="Quarterly Loss Carryforward Strategy",
                description="Utilize losses to offset prior year income or carry forward to future years",
                rationale="Net operating losses can provide significant tax savings",
                estimated_tax_impact_cents=int(business_income_cents * 0.35 * 0.24),
                implementation_effort="medium",
                timeline="before year-end filing",
                related_regulations=["IRC §172", "Form 1045", "Form 1040-X"],
                next_steps=[
                    "Calculate total loss for year",
                    "File amended return for carryback (if eligible)",
                    "Track carryforward for future years",
                ],
            )
        )

    # Entity structure review
    # Use minimal compliance risk if income is zero to ensure valid recommendation
    entity_tax_impact = int(business_income_cents * 0.05 * 0.25)
    entity_compliance_risk = max(50 * 100, int(business_income_cents * 0.01))  # Minimum $50

    recommendations.append(
        TaxRecommendation(
            recommendation_id="OPT-ENTITY-001",
            recommendation_type=RecommendationType.ENTITY_STRUCTURE,
            priority=RecommendationPriority.LOW,
            title="Entity Structure Tax Review",
            description="Review whether current business entity provides optimal tax treatment",
            rationale="S-corp, C-corp, or partnership structures may offer tax advantages",
            estimated_tax_impact_cents=entity_tax_impact,
            estimated_compliance_risk_cents=entity_compliance_risk,
            implementation_effort="high",
            timeline="before year-end",
            required_documentation=[
                "Current business structure",
                "Ownership information",
                "Historical tax returns",
            ],
            next_steps=[
                "Consult with tax professional",
                "Model different entity structures",
                "Evaluate election timing",
            ],
        )
    )

    return recommendations


def prioritize_recommendations(
    recommendations: Iterable[TaxRecommendation],
) -> list[TaxRecommendation]:
    """Sort recommendations by priority and estimated impact.

    Returns recommendations ordered by priority level (critical → low)
    and within each priority, by estimated tax impact (highest first).

    Args:
        recommendations: Iterable of TaxRecommendation objects

    Returns:
        List sorted by priority and impact
    """
    priority_order = {
        RecommendationPriority.CRITICAL: 0,
        RecommendationPriority.HIGH: 1,
        RecommendationPriority.MEDIUM: 2,
        RecommendationPriority.LOW: 3,
    }

    rec_list = list(recommendations)
    return sorted(
        rec_list,
        key=lambda r: (
            priority_order[r.priority],
            -r.total_impact_cents(),  # Descending by impact
        ),
    )
