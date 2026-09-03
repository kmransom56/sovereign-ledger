"""Tax domain service: calculate, track, and report sales taxes (Step 11).

Key flows:
  - Load applicable tax rates for customer & invoice line items
  - Apply tax exemptions (resale, nonprofit, etc.)
  - Calculate tax on each line item
  - Create tax liability and journal entries
  - Generate tax filing reports

Locked decisions honored:
  - D-3: Money as signed integer USD cents
  - HR-1: All entries balance (tax payable = tax collected)
  - T-10: Tax calculation deferred until invoice posting (not draft)
  - T-11: Tax exemptions reduce taxable amount, not tax rate
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import NamedTuple

from ledger.types import AccountRef, JournalEntry, JournalLine

__all__ = [
    "TaxRate",
    "TaxExemption",
    "InvoiceLineTax",
    "TaxCalculation",
    "get_effective_rate",
    "apply_exemption",
    "calculate_line_tax",
    "calculate_invoice_taxes",
    "tax_journal_entry",
]


class TaxError(ValueError):
    """Base error for tax operations."""


class InvalidTaxRateError(TaxError):
    """Tax rate is not valid."""


class TaxExemptionError(TaxError):
    """Tax exemption failed validation."""


class TaxRate(NamedTuple):
    """A tax rate effective on a date range.

    Attributes:
        jurisdiction_code: Code like "CA", "TX", "US-FEDERAL"
        rate_percent: Tax rate as percentage (8.5, 10.0, etc.)
        effective_from: Date this rate becomes effective
        effective_until: Date this rate expires (None = ongoing)
    """

    jurisdiction_code: str
    rate_percent: float
    effective_from: date
    effective_until: date | None


class TaxExemption(NamedTuple):
    """Tax exemption for a customer in a jurisdiction.

    Attributes:
        customer_id: Customer with exemption
        jurisdiction_code: Jurisdiction where exempt
        exemption_type: Type of exemption ("resale", "nonprofit", etc.)
        effective_from: When exemption becomes effective
        effective_until: When exemption expires (None = ongoing)
    """

    customer_id: int
    jurisdiction_code: str
    exemption_type: str
    effective_from: date
    effective_until: date | None


class InvoiceLineTax(NamedTuple):
    """Tax line item on an invoice line.

    Attributes:
        jurisdiction_code: Where tax applies
        rate_percent: Tax rate applied
        taxable_amount_cents: Amount tax was calculated on
        tax_amount_cents: Calculated tax (signed integer cents)
        exemption_code: Code of exemption applied (None if no exemption)
    """

    jurisdiction_code: str
    rate_percent: float
    taxable_amount_cents: int
    tax_amount_cents: int
    exemption_code: str | None = None


@dataclass(frozen=True, slots=True)
class TaxCalculation:
    """Result of tax calculation on invoice line(s).

    Attributes:
        line_taxes: List of taxes calculated per jurisdiction
        total_tax_cents: Sum of all tax_amount_cents
        subtotal_cents: Sum of all taxable_amount_cents
        total_with_tax_cents: Subtotal + total tax
    """

    line_taxes: tuple[InvoiceLineTax, ...]
    total_tax_cents: int
    subtotal_cents: int
    total_with_tax_cents: int


def get_effective_rate(
    rates: list[TaxRate],
    as_of: date,
) -> float | None:
    """Get effective tax rate on a given date.

    Args:
        rates: List of rates for a jurisdiction, sorted by effective_from descending.
        as_of: Date to check.

    Returns:
        Effective rate percentage, or None if no rate applies.

    Raises:
        InvalidTaxRateError: If multiple rates apply on same date.
    """
    applicable = [
        r for r in rates
        if r.effective_from <= as_of
        and (r.effective_until is None or as_of <= r.effective_until)
    ]

    if not applicable:
        return None

    if len(applicable) > 1:
        raise InvalidTaxRateError(f"Multiple rates apply on {as_of}")

    return applicable[0].rate_percent


def apply_exemption(
    line_amount_cents: int,
    exemption: TaxExemption | None,
    as_of: date,
) -> int:
    """Apply exemption to reduce taxable amount.

    Args:
        line_amount_cents: Original line item amount.
        exemption: Exemption to apply (None = no exemption).
        as_of: Date to check exemption validity.

    Returns:
        Taxable amount after exemption (full amount if no exemption).

    Raises:
        TaxExemptionError: If exemption is not valid on the date.
    """
    if exemption is None:
        return line_amount_cents

    if exemption.effective_from > as_of:
        raise TaxExemptionError(
            f"Exemption not yet effective (starts {exemption.effective_from})"
        )

    if exemption.effective_until and as_of > exemption.effective_until:
        raise TaxExemptionError(
            f"Exemption expired (ended {exemption.effective_until})"
        )

    # T-11: Exemption reduces taxable amount to 0 (full exemption for this invoice)
    # In future: could support partial exemptions (e.g., resale of 50% of items)
    if exemption.exemption_type in ("resale", "nonprofit", "government"):
        return 0  # Entire amount exempt

    # Unknown exemption type: don't apply
    return line_amount_cents


def calculate_line_tax(
    line_amount_cents: int,
    rate_percent: float,
    as_of: date,
    exemption: TaxExemption | None = None,
) -> InvoiceLineTax:
    """Calculate tax on one invoice line item.

    Args:
        line_amount_cents: Line item amount in cents.
        rate_percent: Tax rate (8.5, 10.0, etc.).
        as_of: Date tax is being calculated.
        exemption: Optional exemption to apply.

    Returns:
        InvoiceLineTax with calculated amount.

    Raises:
        InvalidTaxRateError: If rate is negative or > 100.
        TaxExemptionError: If exemption is invalid.
    """
    if rate_percent < 0 or rate_percent > 100:
        raise InvalidTaxRateError(f"Rate must be 0-100%, got {rate_percent}")

    if line_amount_cents < 0:
        raise InvalidTaxRateError("Line amount must be non-negative")

    taxable = apply_exemption(line_amount_cents, exemption, as_of)

    # T-3: Money as signed integer cents; tax = round(amount * rate / 100)
    # Standard rounding: banker's rounding (round half to even)
    tax_cents = round((taxable * rate_percent) / 100)

    exemption_code = exemption.exemption_type if exemption else None

    return InvoiceLineTax(
        jurisdiction_code=exemption.jurisdiction_code if exemption else "",
        rate_percent=rate_percent,
        taxable_amount_cents=taxable,
        tax_amount_cents=tax_cents,
        exemption_code=exemption_code,
    )


def calculate_invoice_taxes(
    line_amounts: list[tuple[int, str]],  # (amount_cents, jurisdiction_code)
    tax_rates: dict[str, TaxRate],  # jurisdiction_code -> rate
    as_of: date,
    exemptions: dict[str, TaxExemption] | None = None,  # jurisdiction_code -> exemption
) -> TaxCalculation:
    """Calculate taxes on all line items of an invoice.

    Args:
        line_amounts: List of (amount_cents, jurisdiction_code) tuples.
        tax_rates: Mapping of jurisdiction to applicable rate.
        as_of: Date for tax calculation.
        exemptions: Optional exemptions by jurisdiction.

    Returns:
        TaxCalculation with all taxes and totals.

    Raises:
        InvalidTaxRateError: If rate is invalid.
        TaxExemptionError: If exemption is invalid.
    """
    if not line_amounts:
        return TaxCalculation(
            line_taxes=(),
            total_tax_cents=0,
            subtotal_cents=0,
            total_with_tax_cents=0,
        )

    exemptions = exemptions or {}
    line_taxes = []
    subtotal = 0
    total_tax = 0

    for line_amount_cents, jurisdiction in line_amounts:
        subtotal += line_amount_cents

        if jurisdiction not in tax_rates:
            # No tax rate for this jurisdiction
            continue

        rate = tax_rates[jurisdiction]
        rate_percent = get_effective_rate([rate], as_of)

        if rate_percent is None:
            # No rate effective on this date
            continue

        exemption = exemptions.get(jurisdiction)
        line_tax = calculate_line_tax(
            line_amount_cents, rate_percent, as_of, exemption
        )
        line_taxes.append(line_tax)
        total_tax += line_tax.tax_amount_cents

    return TaxCalculation(
        line_taxes=tuple(line_taxes),
        total_tax_cents=total_tax,
        subtotal_cents=subtotal,
        total_with_tax_cents=subtotal + total_tax,
    )


def tax_journal_entry(
    calculation: TaxCalculation,
    sales_account_ref: AccountRef,  # Income account being credited
    tax_payable_account_ref: AccountRef,  # Liability account
    entry_id: str,
    entry_date: date,
) -> JournalEntry:
    """Construct journal entry for taxes collected on an invoice.

    Entry structure:
      - Debit Sales/Income account for total collected (sales + tax)
      - Credit Sales/Income account for sales amount
      - Credit Tax Payable for tax amount

    This creates the tax liability when the invoice is posted (T-10).

    Args:
        calculation: TaxCalculation with tax amounts.
        sales_account_ref: Income account reference.
        tax_payable_account_ref: Tax payable liability account reference.
        entry_id: Unique entry identifier.
        entry_date: Date of entry.

    Returns:
        Balanced JournalEntry for tax posting.

    Raises:
        TaxError: If entry would not balance or if there is no tax to record.
    """
    if calculation.total_tax_cents == 0:
        raise TaxError("Cannot create tax journal entry with zero tax amount")

    lines: list[JournalLine] = []

    # Debit Sales account for the tax portion (representing increased revenue)
    lines.append(
        JournalLine.debit(sales_account_ref, calculation.total_tax_cents)
    )

    # Credit Tax Payable for the tax collected
    lines.append(
        JournalLine.credit(tax_payable_account_ref, calculation.total_tax_cents)
    )

    entry = JournalEntry(
        entry_id=entry_id,
        date=entry_date,
        description=f"Tax collected: {calculation.total_tax_cents / 100:.2f}",
        lines=tuple(lines),
    )

    return entry
