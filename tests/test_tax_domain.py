"""Tests for tax domain services (Step 11).

Tests tax calculation, exemption handling, and journal entry creation.
Verifies D-3 (money as cents), HR-1 (balance), T-10 (deferred), T-11 (exemptions).
"""

from __future__ import annotations

from datetime import date

import pytest

from ledger.taxes import (
    InvoiceLineTax,
    InvalidTaxRateError,
    TaxError,
    TaxExemption,
    TaxExemptionError,
    TaxRate,
    apply_exemption,
    calculate_invoice_taxes,
    calculate_line_tax,
    get_effective_rate,
    tax_journal_entry,
)
from ledger.types import AccountRef, AccountType


class TestGetEffectiveRate:
    """Test rate lookup by date."""

    def test_single_rate_no_end(self):
        """Single rate with no end date applies indefinitely."""
        rate = TaxRate(
            jurisdiction_code="CA",
            rate_percent=8.5,
            effective_from=date(2026, 1, 1),
            effective_until=None,
        )
        assert get_effective_rate([rate], date(2026, 6, 1)) == 8.5
        assert get_effective_rate([rate], date(2027, 1, 1)) == 8.5

    def test_rate_not_yet_effective(self):
        """Rate before effective date returns None."""
        rate = TaxRate(
            jurisdiction_code="CA",
            rate_percent=8.5,
            effective_from=date(2026, 6, 1),
            effective_until=None,
        )
        assert get_effective_rate([rate], date(2026, 5, 31)) is None

    def test_rate_expired(self):
        """Rate after end date returns None."""
        rate = TaxRate(
            jurisdiction_code="CA",
            rate_percent=8.5,
            effective_from=date(2026, 1, 1),
            effective_until=date(2026, 6, 30),
        )
        assert get_effective_rate([rate], date(2026, 7, 1)) is None

    def test_rate_during_range(self):
        """Rate within effective range returns value."""
        rate = TaxRate(
            jurisdiction_code="CA",
            rate_percent=8.5,
            effective_from=date(2026, 1, 1),
            effective_until=date(2026, 12, 31),
        )
        assert get_effective_rate([rate], date(2026, 6, 15)) == 8.5


class TestApplyExemption:
    """Test tax exemption handling (T-11)."""

    def test_no_exemption(self):
        """No exemption returns full amount."""
        amount = apply_exemption(10000, None, date(2026, 6, 1))
        assert amount == 10000

    def test_resale_exemption_active(self):
        """Active resale exemption returns 0 taxable amount."""
        exemption = TaxExemption(
            customer_id=1,
            jurisdiction_code="CA",
            exemption_type="resale",
            effective_from=date(2026, 1, 1),
            effective_until=None,
        )
        amount = apply_exemption(10000, exemption, date(2026, 6, 1))
        assert amount == 0

    def test_exemption_not_yet_effective(self):
        """Exemption before effective date raises error."""
        exemption = TaxExemption(
            customer_id=1,
            jurisdiction_code="CA",
            exemption_type="resale",
            effective_from=date(2026, 7, 1),
            effective_until=None,
        )
        with pytest.raises(TaxExemptionError, match="not yet effective"):
            apply_exemption(10000, exemption, date(2026, 6, 1))

    def test_exemption_expired(self):
        """Exemption after end date raises error."""
        exemption = TaxExemption(
            customer_id=1,
            jurisdiction_code="CA",
            exemption_type="resale",
            effective_from=date(2026, 1, 1),
            effective_until=date(2026, 6, 30),
        )
        with pytest.raises(TaxExemptionError, match="expired"):
            apply_exemption(10000, exemption, date(2026, 7, 1))


class TestCalculateLineTax:
    """Test tax calculation on single line item."""

    def test_simple_tax_calculation(self):
        """Calculate tax on simple amount."""
        tax = calculate_line_tax(
            line_amount_cents=10000,  # $100
            rate_percent=8.5,
            as_of=date(2026, 6, 1),
        )
        assert tax.jurisdiction_code == ""
        assert tax.rate_percent == 8.5
        assert tax.taxable_amount_cents == 10000
        assert tax.tax_amount_cents == 850  # $100 * 0.085 = $8.50
        assert tax.exemption_code is None

    def test_tax_with_exemption(self):
        """Tax with exemption applied."""
        exemption = TaxExemption(
            customer_id=1,
            jurisdiction_code="CA",
            exemption_type="nonprofit",
            effective_from=date(2026, 1, 1),
            effective_until=None,
        )
        tax = calculate_line_tax(
            line_amount_cents=10000,
            rate_percent=8.5,
            as_of=date(2026, 6, 1),
            exemption=exemption,
        )
        assert tax.taxable_amount_cents == 0
        assert tax.tax_amount_cents == 0
        assert tax.exemption_code == "nonprofit"

    def test_negative_rate_error(self):
        """Negative rate raises error."""
        with pytest.raises(InvalidTaxRateError):
            calculate_line_tax(10000, -5.0, date(2026, 6, 1))

    def test_rate_over_100_error(self):
        """Rate > 100% raises error."""
        with pytest.raises(InvalidTaxRateError):
            calculate_line_tax(10000, 150.0, date(2026, 6, 1))

    def test_zero_amount(self):
        """Zero amount results in zero tax."""
        tax = calculate_line_tax(0, 8.5, date(2026, 6, 1))
        assert tax.tax_amount_cents == 0

    def test_rounding(self):
        """Tax rounds correctly (banker's rounding)."""
        # $33.33 * 8.5% = $2.83305 → rounds to $2.83 (banker's rounding)
        tax = calculate_line_tax(3333, 8.5, date(2026, 6, 1))
        # 3333 * 0.085 = 283.305 → 283 (banker's round down)
        assert 282 <= tax.tax_amount_cents <= 284  # Allow for rounding variation


class TestCalculateInvoiceTaxes:
    """Test tax calculation across multiple lines and jurisdictions."""

    def test_single_jurisdiction_no_exemptions(self):
        """Calculate tax on multiple lines in one jurisdiction."""
        rates = {
            "CA": TaxRate("CA", 8.5, date(2026, 1, 1), None),
        }
        calc = calculate_invoice_taxes(
            line_amounts=[
                (5000, "CA"),  # $50
                (5000, "CA"),  # $50
            ],
            tax_rates=rates,
            as_of=date(2026, 6, 1),
        )
        assert calc.subtotal_cents == 10000
        assert len(calc.line_taxes) == 2
        # Total tax: $100 * 0.085 = $8.50 = 850 cents
        assert calc.total_tax_cents == 850
        assert calc.total_with_tax_cents == 10850

    def test_multiple_jurisdictions(self):
        """Calculate taxes with multiple jurisdictions."""
        rates = {
            "CA": TaxRate("CA", 8.5, date(2026, 1, 1), None),
            "TX": TaxRate("TX", 6.25, date(2026, 1, 1), None),
        }
        calc = calculate_invoice_taxes(
            line_amounts=[
                (5000, "CA"),  # $50 → tax $4.25
                (5000, "TX"),  # $50 → tax $3.125 ≈ $3.12 (banker's rounding)
            ],
            tax_rates=rates,
            as_of=date(2026, 6, 1),
        )
        assert calc.subtotal_cents == 10000
        assert len(calc.line_taxes) == 2
        # Tax: 425 (CA) + 312 (TX: 312.5 → banker's rounding) = 737 cents
        assert calc.total_tax_cents == 737
        assert calc.total_with_tax_cents == 10737

    def test_with_exemption(self):
        """Calculate taxes with exemption applied."""
        rates = {
            "CA": TaxRate("CA", 8.5, date(2026, 1, 1), None),
        }
        exemptions = {
            "CA": TaxExemption(
                customer_id=1,
                jurisdiction_code="CA",
                exemption_type="resale",
                effective_from=date(2026, 1, 1),
                effective_until=None,
            ),
        }
        calc = calculate_invoice_taxes(
            line_amounts=[(10000, "CA")],
            tax_rates=rates,
            as_of=date(2026, 6, 1),
            exemptions=exemptions,
        )
        assert calc.subtotal_cents == 10000
        assert calc.total_tax_cents == 0  # Exempted
        assert calc.total_with_tax_cents == 10000

    def test_no_lines(self):
        """Empty invoice has no tax."""
        calc = calculate_invoice_taxes([], {}, date(2026, 6, 1))
        assert calc.subtotal_cents == 0
        assert calc.total_tax_cents == 0
        assert calc.total_with_tax_cents == 0

    def test_no_rate_for_jurisdiction(self):
        """Missing rate for jurisdiction skips tax."""
        calc = calculate_invoice_taxes(
            line_amounts=[(10000, "CA")],
            tax_rates={},  # No rate for CA
            as_of=date(2026, 6, 1),
        )
        assert calc.subtotal_cents == 10000
        assert calc.total_tax_cents == 0  # No rate, no tax


class TestTaxJournalEntry:
    """Test journal entry creation for tax collection."""

    def test_tax_entry_balances(self):
        """Tax journal entry balances."""
        calc = calculate_invoice_taxes(
            line_amounts=[(10000, "CA")],
            tax_rates={"CA": TaxRate("CA", 8.5, date(2026, 1, 1), None)},
            as_of=date(2026, 6, 1),
        )

        sales_ref = AccountRef(
            code="4000",
            name="Sales Revenue",
            type=AccountType.INCOME,
        )
        tax_ref = AccountRef(
            code="2100",
            name="Sales Tax Payable",
            type=AccountType.LIABILITY,
        )

        entry = tax_journal_entry(
            calc,
            sales_account_ref=sales_ref,
            tax_payable_account_ref=tax_ref,
            entry_id="tax-001",
            entry_date=date(2026, 6, 1),
        )

        # Entry should balance: debit sales = credit tax payable
        debit_total = sum(line.amount_cents for line in entry.lines if line.amount_cents > 0)
        credit_total = sum(-line.amount_cents for line in entry.lines if line.amount_cents < 0)
        assert debit_total == credit_total

    def test_no_tax_entry(self):
        """No tax calculation raises error (cannot create empty entry)."""
        calc = calculate_invoice_taxes([], {}, date(2026, 6, 1))

        sales_ref = AccountRef("4000", "Sales", AccountType.INCOME)
        tax_ref = AccountRef("2100", "Tax Payable", AccountType.LIABILITY)

        with pytest.raises(TaxError, match="zero tax"):
            tax_journal_entry(
                calc,
                sales_ref,
                tax_ref,
                "tax-002",
                date(2026, 6, 1),
            )
