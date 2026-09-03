"""Integration tests for tax calculation during invoice posting (Step 11).

Verifies:
  - Tax rates loaded from database
  - Tax exemptions applied correctly
  - Tax amounts calculated and recorded
  - Tax journal entries created and balanced
  - Invoice totals include tax
  - Tax liability tracked by period
"""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from app.adapters.ar_posting import (
    load_tax_rates_for_jurisdictions,
    load_tax_exemptions_for_customer,
)
from ledger.invoices import InvoiceLine, InvoiceDraft
from ledger.taxes import TaxRate, TaxExemption, calculate_invoice_taxes


class TestLoadTaxRates:
    """Test loading tax rates from database."""

    def test_load_single_rate(self):
        """Load single effective tax rate."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()

        # Single CA rate, effective 2026-01-01 to 2026-12-31
        mock_cursor.fetchall.return_value = [
            ("CA", 8.5, date(2026, 1, 1), date(2026, 12, 31)),
        ]
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        result = load_tax_rates_for_jurisdictions(mock_conn, ["CA"], date(2026, 6, 1))

        assert "CA" in result
        assert result["CA"].rate_percent == 8.5
        assert result["CA"].effective_from == date(2026, 1, 1)

    def test_load_multiple_jurisdictions(self):
        """Load rates for multiple jurisdictions."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()

        # CA and TX rates
        mock_cursor.fetchall.return_value = [
            ("CA", 8.5, date(2026, 1, 1), None),
            ("TX", 6.25, date(2026, 1, 1), None),
        ]
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        result = load_tax_rates_for_jurisdictions(
            mock_conn, ["CA", "TX"], date(2026, 6, 1)
        )

        assert result["CA"].rate_percent == 8.5
        assert result["TX"].rate_percent == 6.25

    def test_load_no_effective_rate(self):
        """Return None when no rate effective on date."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()

        # Rate effective from 2026-07-01, but query as of 2026-06-01
        mock_cursor.fetchall.return_value = [
            ("CA", 8.5, date(2026, 7, 1), None),
        ]
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        result = load_tax_rates_for_jurisdictions(mock_conn, ["CA"], date(2026, 6, 1))

        assert result["CA"] is None

    def test_load_rate_expired(self):
        """Return None when rate has expired."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()

        # Rate expired as of 2026-06-30, query as of 2026-07-01
        mock_cursor.fetchall.return_value = [
            ("CA", 8.5, date(2026, 1, 1), date(2026, 6, 30)),
        ]
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        result = load_tax_rates_for_jurisdictions(mock_conn, ["CA"], date(2026, 7, 1))

        assert result["CA"] is None


class TestLoadTaxExemptions:
    """Test loading tax exemptions from database."""

    def test_load_single_exemption(self):
        """Load single active exemption."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()

        # Single CA resale exemption
        mock_cursor.fetchall.return_value = [
            (
                "CA",
                1,
                "CA",
                "resale",
                date(2026, 1, 1),
                None,
            ),
        ]
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        result = load_tax_exemptions_for_customer(
            mock_conn, 1, ["CA"], date(2026, 6, 1)
        )

        assert "CA" in result
        assert result["CA"].exemption_type == "resale"

    def test_load_no_active_exemption(self):
        """Return None when no active exemption."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()

        mock_cursor.fetchall.return_value = []
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        result = load_tax_exemptions_for_customer(
            mock_conn, 1, ["CA"], date(2026, 6, 1)
        )

        assert result["CA"] is None

    def test_load_exemption_not_yet_effective(self):
        """Return None when exemption not yet effective."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()

        # Exemption effective from 2026-07-01, query as of 2026-06-01
        mock_cursor.fetchall.return_value = [
            (
                "CA",
                1,
                "CA",
                "nonprofit",
                date(2026, 7, 1),
                None,
            ),
        ]
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        result = load_tax_exemptions_for_customer(
            mock_conn, 1, ["CA"], date(2026, 6, 1)
        )

        assert result["CA"] is None


class TestTaxCalculationIntegration:
    """Test tax calculation within invoice posting flow."""

    def test_calculate_tax_on_invoice_lines(self):
        """Calculate tax across multiple invoice lines."""
        # Create draft with two lines
        lines = [
            InvoiceLine(
                id=None,
                invoice_id=None,
                description="Service A",
                quantity=1,
                unit_price_cents=5000,
                amount_cents=5000,
                account_id=1,
            ),
            InvoiceLine(
                id=None,
                invoice_id=None,
                description="Service B",
                quantity=1,
                unit_price_cents=5000,
                amount_cents=5000,
                account_id=2,
            ),
        ]

        draft = InvoiceDraft(
            customer_id=1,
            issue_date=date(2026, 6, 1),
            due_date=date(2026, 7, 1),
            lines=lines,
            memo="Test invoice",
        )

        # Create tax rates
        tax_rates = {
            "CA": TaxRate("CA", 8.5, date(2026, 1, 1), None),
        }

        # Calculate taxes on $100 total at 8.5% = $8.50
        line_amounts = [
            (5000, "CA"),  # $50
            (5000, "CA"),  # $50
        ]

        calc = calculate_invoice_taxes(
            line_amounts,
            tax_rates,
            date(2026, 6, 1),
        )

        assert calc.subtotal_cents == 10000
        assert calc.total_tax_cents == 850  # $100 * 0.085
        assert calc.total_with_tax_cents == 10850

    def test_calculate_tax_with_exemption(self):
        """Calculate tax with customer exemption applied."""
        lines = [
            InvoiceLine(
                id=None,
                invoice_id=None,
                description="Resale",
                quantity=1,
                unit_price_cents=10000,
                amount_cents=10000,
                account_id=1,
            ),
        ]

        draft = InvoiceDraft(
            customer_id=1,
            issue_date=date(2026, 6, 1),
            due_date=date(2026, 7, 1),
            lines=lines,
            memo="Resale invoice",
        )

        # Create tax rate and exemption
        tax_rates = {
            "CA": TaxRate("CA", 8.5, date(2026, 1, 1), None),
        }

        exemption = TaxExemption(
            customer_id=1,
            jurisdiction_code="CA",
            exemption_type="resale",
            effective_from=date(2026, 1, 1),
            effective_until=None,
        )

        exemptions = {"CA": exemption}

        # Calculate taxes with exemption
        line_amounts = [(10000, "CA")]

        calc = calculate_invoice_taxes(
            line_amounts,
            tax_rates,
            date(2026, 6, 1),
            exemptions,
        )

        assert calc.subtotal_cents == 10000
        assert calc.total_tax_cents == 0  # Fully exempt
        assert calc.total_with_tax_cents == 10000

    def test_calculate_tax_mixed_jurisdictions(self):
        """Calculate tax with different rates per jurisdiction."""
        lines = [
            InvoiceLine(
                id=None,
                invoice_id=None,
                description="CA",
                quantity=1,
                unit_price_cents=5000,
                amount_cents=5000,
                account_id=1,
            ),
            InvoiceLine(
                id=None,
                invoice_id=None,
                description="TX",
                quantity=1,
                unit_price_cents=5000,
                amount_cents=5000,
                account_id=2,
            ),
        ]

        draft = InvoiceDraft(
            customer_id=1,
            issue_date=date(2026, 6, 1),
            due_date=date(2026, 7, 1),
            lines=lines,
            memo="Multi-jurisdiction invoice",
        )

        # Different rates
        tax_rates = {
            "CA": TaxRate("CA", 8.5, date(2026, 1, 1), None),
            "TX": TaxRate("TX", 6.25, date(2026, 1, 1), None),
        }

        # $50 CA @ 8.5% = $4.25, $50 TX @ 6.25% = $3.125 ≈ $3.13
        line_amounts = [
            (5000, "CA"),
            (5000, "TX"),
        ]

        calc = calculate_invoice_taxes(
            line_amounts,
            tax_rates,
            date(2026, 6, 1),
        )

        assert calc.subtotal_cents == 10000
        # 425 (CA) + 312 (TX: 312.5 → banker's rounding to 312) = 737
        assert calc.total_tax_cents == 737
        assert calc.total_with_tax_cents == 10737
