"""Sovereign Ledger pure domain core — hard rule 1: zero I/O.

Nothing under ``ledger/`` may import web frameworks, database drivers, or
HTTP clients; ``scripts/check_boundaries.py`` fails the build on any
violation under ``ledger/`` or ``reports/``. Persistence is the caller's
job (adapters in ``app/``, ``importers/``, ``scripts/``).

SIGN CONVENTION — locked decision D-3, load-bearing for every later step:

    amount_cents > 0   →  DEBIT   (+)
    amount_cents < 0   →  CREDIT  (−)

Money is signed integer USD cents, BIGINT-safe (see ``BIGINT_MAX_CENTS``).
The convention is encoded structurally: ``JournalLine.debit`` /
``JournalLine.credit`` construct lines from magnitudes, and
``AccountType.normal_balance_sign`` states each account class's normal
side. Property tests in ``tests/test_engine.py`` pin it.
"""

from ledger.capital_assets import (
    AssetPool,
    AssetType,
    CapitalAsset,
    DepreciationMethod,
    DepreciationSchedule,
    create_depreciation_schedule,
)
from ledger.customers import Customer, CustomerStatus, new_customer
from ledger.deductions import (
    DeductibleExpense,
    DeductionCategory,
    DeductionSummary,
    HobbyLossAnalysis,
    TaxBreakOpportunity,
    aggregate_deductions_by_category,
    aggregate_deductions_by_period,
    detect_hobby_loss,
    identify_tax_breaks,
)
from ledger.engine import PostedEntry, post, post_lines, validate_balanced
from ledger.invoices import (
    Invoice,
    InvoiceDraft,
    InvoiceLine,
    add_line_to_draft,
    invoice_journal_entry,
    mark_paid,
    mark_void,
    new_invoice_draft,
)
from ledger.payments import (
    Payment,
    PaymentAllocationLine,
    allocate_payment,
    payment_journal_entry,
)
from ledger.recurring import (
    GenerationResult,
    RecurringTemplate,
    generate_invoice_for_cycle,
    mark_template_active,
    mark_template_ended,
    mark_template_paused,
    new_template,
    should_generate_for_cycle,
)
from ledger.tax_projections import (
    FilingStatus,
    QuarterlyTaxEstimate,
    TaxProjection,
    TaxSavingsProjection,
    calculate_federal_tax,
    calculate_quarterly_estimate,
    calculate_self_employment_tax,
    project_year_end_tax,
)
from ledger.tax_recommendations import (
    RecommendationPriority,
    RecommendationType,
    TaxRecommendation,
    TaxRecommendationSet,
    generate_compliance_recommendations,
    generate_deduction_recommendations,
    generate_optimization_recommendations,
    prioritize_recommendations,
)
from ledger.types import (
    BIGINT_MAX_CENTS,
    AccountRef,
    AccountType,
    BigIntOverflowError,
    JournalEntry,
    JournalLine,
    Money,
    UnbalancedEntryError,
    cents_from_decimal,
)

__all__ = [
    # Core
    "BIGINT_MAX_CENTS",
    "AccountRef",
    "AccountType",
    "BigIntOverflowError",
    "JournalEntry",
    "JournalLine",
    "Money",
    "PostedEntry",
    "UnbalancedEntryError",
    "cents_from_decimal",
    "post",
    "post_lines",
    "validate_balanced",
    # Capital Assets (Step 13, Phase 1)
    "AssetPool",
    "AssetType",
    "CapitalAsset",
    "DepreciationMethod",
    "DepreciationSchedule",
    "create_depreciation_schedule",
    # Customers
    "Customer",
    "CustomerStatus",
    "new_customer",
    # Deductions (Step 13, Phase 1)
    "DeductibleExpense",
    "DeductionCategory",
    "DeductionSummary",
    "HobbyLossAnalysis",
    "TaxBreakOpportunity",
    "aggregate_deductions_by_category",
    "aggregate_deductions_by_period",
    "detect_hobby_loss",
    "identify_tax_breaks",
    # Invoices
    "Invoice",
    "InvoiceDraft",
    "InvoiceLine",
    "add_line_to_draft",
    "invoice_journal_entry",
    "mark_paid",
    "mark_void",
    "new_invoice_draft",
    # Payments
    "Payment",
    "PaymentAllocationLine",
    "allocate_payment",
    "payment_journal_entry",
    # Recurring
    "GenerationResult",
    "RecurringTemplate",
    "generate_invoice_for_cycle",
    "mark_template_active",
    "mark_template_ended",
    "mark_template_paused",
    "new_template",
    "should_generate_for_cycle",
    # Tax Projections (Step 13, Phase 1)
    "FilingStatus",
    "QuarterlyTaxEstimate",
    "TaxProjection",
    "TaxSavingsProjection",
    "calculate_federal_tax",
    "calculate_quarterly_estimate",
    "calculate_self_employment_tax",
    "project_year_end_tax",
    # Tax Recommendations (Step 13, Phase 1)
    "RecommendationPriority",
    "RecommendationType",
    "TaxRecommendation",
    "TaxRecommendationSet",
    "generate_compliance_recommendations",
    "generate_deduction_recommendations",
    "generate_optimization_recommendations",
    "prioritize_recommendations",
]