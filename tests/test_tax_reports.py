"""Tests for tax reporting (Step 11).

Tests tax liability summaries, jurisdiction breakdowns, and filing status.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

import pytest

from app.adapters.tax_reports import (
    tax_by_jurisdiction_summary,
    tax_filing_status_summary,
    tax_liability_summary,
)


class TestTaxLiabilitySummary:
    """Test tax liability reporting."""

    def test_single_liability_record(self):
        """Load single tax liability record."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()

        # CA, June period, $100 collected, $0 paid
        mock_cursor.fetchall.return_value = [
            ("CA", "California", date(2026, 6, 30), 850, 0, "accrued"),
        ]
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        summary = tax_liability_summary(mock_conn)

        assert len(summary.rows) == 1
        assert summary.rows[0].jurisdiction_code == "CA"
        assert summary.rows[0].collected_cents == 850
        assert summary.rows[0].paid_cents == 0
        assert summary.rows[0].balance_cents == 850
        assert summary.total_collected_cents == 850
        assert summary.total_balance_cents == 850

    def test_multiple_periods_same_jurisdiction(self):
        """Load multiple periods for one jurisdiction."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()

        # CA May and June
        mock_cursor.fetchall.return_value = [
            ("CA", "California", date(2026, 6, 30), 850, 0, "accrued"),
            ("CA", "California", date(2026, 5, 31), 800, 800, "paid"),
        ]
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        summary = tax_liability_summary(mock_conn)

        assert len(summary.rows) == 2
        assert summary.total_collected_cents == 1650
        assert summary.total_paid_cents == 800
        assert summary.total_balance_cents == 850

    def test_multiple_jurisdictions(self):
        """Load data across multiple jurisdictions."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()

        # CA and TX, June
        mock_cursor.fetchall.return_value = [
            ("CA", "California", date(2026, 6, 30), 850, 0, "accrued"),
            ("TX", "Texas", date(2026, 6, 30), 625, 625, "paid"),
        ]
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        summary = tax_liability_summary(mock_conn)

        assert len(summary.rows) == 2
        assert summary.total_collected_cents == 1475
        assert summary.total_paid_cents == 625
        assert summary.total_balance_cents == 850

    def test_filter_by_jurisdiction(self):
        """Filter liability to specific jurisdiction."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()

        # Only CA should be queried
        mock_cursor.fetchall.return_value = [
            ("CA", "California", date(2026, 6, 30), 850, 0, "accrued"),
        ]
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        summary = tax_liability_summary(mock_conn, jurisdiction_code="CA")

        # Verify CA was passed to query
        call_args = mock_cursor.execute.call_args
        assert "CA" in call_args[0][1] or "CA" in str(call_args[0][1])
        assert len(summary.rows) == 1

    def test_filter_by_status(self):
        """Filter liability by status."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()

        # Only paid status
        mock_cursor.fetchall.return_value = [
            ("TX", "Texas", date(2026, 6, 30), 625, 625, "paid"),
        ]
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        summary = tax_liability_summary(mock_conn, status_filter="paid")

        assert len(summary.rows) == 1
        assert summary.rows[0].status == "paid"
        assert summary.rows[0].balance_cents == 0


class TestTaxByJurisdictionSummary:
    """Test tax aggregation by jurisdiction."""

    def test_single_jurisdiction(self):
        """Load aggregated tax for one jurisdiction."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()

        # CA with 2 periods of activity
        mock_cursor.fetchall.return_value = [
            ("CA", "California", "sales_tax", True, 1650, 800, 2),
        ]
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        summary = tax_by_jurisdiction_summary(mock_conn)

        assert len(summary.rows) == 1
        assert summary.rows[0].jurisdiction_code == "CA"
        assert summary.rows[0].total_collected_cents == 1650
        assert summary.rows[0].total_paid_cents == 800
        assert summary.rows[0].outstanding_cents == 850
        assert summary.rows[0].period_count == 2

    def test_multiple_jurisdictions_aggregated(self):
        """Load aggregated data for multiple jurisdictions."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()

        # CA and TX with different amounts
        mock_cursor.fetchall.return_value = [
            ("CA", "California", "sales_tax", True, 2500, 1000, 3),
            ("TX", "Texas", "sales_tax", True, 1875, 1875, 2),
        ]
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        summary = tax_by_jurisdiction_summary(mock_conn)

        assert len(summary.rows) == 2
        assert summary.total_collected_cents == 4375
        assert summary.total_paid_cents == 2875
        assert summary.total_outstanding_cents == 1500
        assert summary.jurisdiction_count == 2

    def test_active_only_filter(self):
        """Filter to only active jurisdictions."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()

        # Only active jurisdictions returned
        mock_cursor.fetchall.return_value = [
            ("CA", "California", "sales_tax", True, 1650, 800, 2),
        ]
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        summary = tax_by_jurisdiction_summary(mock_conn, active_only=True)

        assert all(row.active for row in summary.rows)
        call_args = mock_cursor.execute.call_args
        assert "active = true" in call_args[0][0]


class TestTaxFilingStatusSummary:
    """Test tax filing status reporting."""

    def test_single_filing(self):
        """Load single filing record."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()

        # CA June filing, filed
        mock_cursor.fetchall.return_value = [
            (
                "CA",
                "California",
                date(2026, 6, 1),
                date(2026, 6, 30),
                "monthly",
                "filed",
                10000,
                850,
                850,
                date(2026, 7, 15),
                "REF-001",
            ),
        ]
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        summary = tax_filing_status_summary(mock_conn)

        assert len(summary.rows) == 1
        assert summary.rows[0].jurisdiction_code == "CA"
        assert summary.rows[0].status == "filed"
        assert summary.rows[0].filing_date == date(2026, 7, 15)
        assert summary.rows[0].reference_number == "REF-001"
        assert summary.filed_count == 1
        assert summary.pending_count == 0

    def test_multiple_statuses(self):
        """Load filings with different statuses."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()

        # CA draft, TX filed, NY paid
        mock_cursor.fetchall.return_value = [
            (
                "CA",
                "California",
                date(2026, 6, 1),
                date(2026, 6, 30),
                "monthly",
                "draft",
                10000,
                850,
                0,
                None,
                None,
            ),
            (
                "TX",
                "Texas",
                date(2026, 6, 1),
                date(2026, 6, 30),
                "monthly",
                "filed",
                8000,
                500,
                500,
                date(2026, 7, 15),
                "REF-002",
            ),
            (
                "NY",
                "New York",
                date(2026, 5, 1),
                date(2026, 5, 31),
                "monthly",
                "paid",
                12000,
                900,
                900,
                date(2026, 6, 15),
                "REF-003",
            ),
        ]
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        summary = tax_filing_status_summary(mock_conn)

        assert len(summary.rows) == 3
        assert summary.pending_count == 1
        assert summary.filed_count == 1
        assert summary.paid_count == 1
        assert summary.reconciled_count == 0

    def test_filter_by_status(self):
        """Filter filings by status."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()

        # Only draft status
        mock_cursor.fetchall.return_value = [
            (
                "CA",
                "California",
                date(2026, 6, 1),
                date(2026, 6, 30),
                "monthly",
                "draft",
                10000,
                850,
                0,
                None,
                None,
            ),
        ]
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        summary = tax_filing_status_summary(mock_conn, status_filter="draft")

        assert len(summary.rows) == 1
        assert summary.rows[0].status == "draft"
        assert summary.pending_count == 1
