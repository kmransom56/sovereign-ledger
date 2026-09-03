"""Tests for tax lifecycle management (Step 11).

Tests marking tax as paid and managing filing records.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

import pytest


class TestMarkLiabilityPaid:
    """Test marking tax liability as paid."""

    def test_mark_liability_partial_paid(self):
        """Mark portion of liability as paid."""
        from app.routes.tax_lifecycle import mark_liability_paid
        from pydantic import BaseModel

        # Create input model
        class Input(BaseModel):
            liability_id: int
            amount_paid_cents: int
            payment_date: date
            notes: str | None

        mock_request = MagicMock()
        mock_conn = MagicMock()
        mock_cursor = MagicMock()

        # Liability: CA, June, $850 collected, $0 paid
        mock_cursor.fetchone.side_effect = [
            (1, 1, date(2026, 6, 30), 850, 0, "accrued"),
        ]
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_request.app.state.db = mock_conn

        req = Input(
            liability_id=1,
            amount_paid_cents=500,
            payment_date=date(2026, 7, 15),
            notes="Partial payment",
        )

        # Mock user
        user = {"id": 1}

        result = mark_liability_paid(req, mock_request, user)

        assert result.id == 1
        assert result.collected_cents == 850
        assert result.paid_cents == 500
        assert result.remaining_cents == 350
        assert result.status == "accrued"  # Not fully paid yet

    def test_mark_liability_fully_paid(self):
        """Mark full liability as paid (status changes to paid)."""
        from app.routes.tax_lifecycle import mark_liability_paid
        from pydantic import BaseModel

        class Input(BaseModel):
            liability_id: int
            amount_paid_cents: int
            payment_date: date
            notes: str | None

        mock_request = MagicMock()
        mock_conn = MagicMock()
        mock_cursor = MagicMock()

        # Liability: CA, June, $850 collected, $500 already paid
        mock_cursor.fetchone.side_effect = [
            (1, 1, date(2026, 6, 30), 850, 500, "accrued"),
        ]
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_request.app.state.db = mock_conn

        req = Input(
            liability_id=1,
            amount_paid_cents=350,  # Complete the payment
            payment_date=date(2026, 7, 15),
            notes="Final payment",
        )

        user = {"id": 1}

        result = mark_liability_paid(req, mock_request, user)

        assert result.paid_cents == 850
        assert result.remaining_cents == 0
        assert result.status == "paid"  # Fully paid

    def test_mark_liability_overpaid_capped(self):
        """Overpayment is capped at collected amount."""
        from app.routes.tax_lifecycle import mark_liability_paid
        from pydantic import BaseModel

        class Input(BaseModel):
            liability_id: int
            amount_paid_cents: int
            payment_date: date
            notes: str | None

        mock_request = MagicMock()
        mock_conn = MagicMock()
        mock_cursor = MagicMock()

        # Liability: CA, June, $850 collected, $0 paid
        mock_cursor.fetchone.side_effect = [
            (1, 1, date(2026, 6, 30), 850, 0, "accrued"),
        ]
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_request.app.state.db = mock_conn

        req = Input(
            liability_id=1,
            amount_paid_cents=1000,  # More than owed
            payment_date=date(2026, 7, 15),
            notes="Overpayment",
        )

        user = {"id": 1}

        result = mark_liability_paid(req, mock_request, user)

        assert result.paid_cents == 850  # Capped
        assert result.remaining_cents == 0


class TestCreateFiling:
    """Test creating tax filing records."""

    def test_create_monthly_filing(self):
        """Create a monthly tax filing."""
        from app.routes.tax_lifecycle import create_filing
        from pydantic import BaseModel

        class Input(BaseModel):
            jurisdiction_code: str
            filing_period_start: date
            filing_period_end: date
            filing_type: str
            total_sales_cents: int
            tax_collected_cents: int

        mock_request = MagicMock()
        mock_conn = MagicMock()
        mock_cursor = MagicMock()

        # Get jurisdiction ID, then create filing
        mock_cursor.fetchone.side_effect = [
            (1,),  # jurisdiction_id
            (1, date(2026, 6, 1), date(2026, 6, 30), "monthly", 10000, 850, 0, "draft"),
        ]
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_request.app.state.db = mock_conn

        req = Input(
            jurisdiction_code="CA",
            filing_period_start=date(2026, 6, 1),
            filing_period_end=date(2026, 6, 30),
            filing_type="monthly",
            total_sales_cents=10000,
            tax_collected_cents=850,
        )

        user = {"id": 1}

        result = create_filing(req, mock_request, user)

        assert result.jurisdiction_code == "CA"
        assert result.filing_type == "monthly"
        assert result.total_sales_cents == 10000
        assert result.tax_collected_cents == 850
        assert result.status == "draft"
        assert result.tax_paid_cents == 0

    def test_create_quarterly_filing(self):
        """Create a quarterly filing."""
        from app.routes.tax_lifecycle import create_filing
        from pydantic import BaseModel

        class Input(BaseModel):
            jurisdiction_code: str
            filing_period_start: date
            filing_period_end: date
            filing_type: str
            total_sales_cents: int
            tax_collected_cents: int

        mock_request = MagicMock()
        mock_conn = MagicMock()
        mock_cursor = MagicMock()

        mock_cursor.fetchone.side_effect = [
            (2,),  # jurisdiction_id
            (2, date(2026, 4, 1), date(2026, 6, 30), "quarterly", 30000, 2550, 0, "draft"),
        ]
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_request.app.state.db = mock_conn

        req = Input(
            jurisdiction_code="TX",
            filing_period_start=date(2026, 4, 1),
            filing_period_end=date(2026, 6, 30),
            filing_type="quarterly",
            total_sales_cents=30000,
            tax_collected_cents=2550,
        )

        user = {"id": 1}

        result = create_filing(req, mock_request, user)

        assert result.jurisdiction_code == "TX"
        assert result.filing_type == "quarterly"
        assert result.period_start == date(2026, 4, 1)
        assert result.period_end == date(2026, 6, 30)


class TestUpdateFilingStatus:
    """Test updating filing status."""

    def test_update_filing_draft_to_filed(self):
        """Mark filing as filed."""
        from app.routes.tax_lifecycle import update_filing_status
        from pydantic import BaseModel

        class Input(BaseModel):
            filing_id: int
            status: str
            filing_date: date | None
            reference_number: str | None
            tax_paid_cents: int | None
            notes: str | None

        mock_request = MagicMock()
        mock_conn = MagicMock()
        mock_cursor = MagicMock()

        # Get filing details
        mock_cursor.fetchone.side_effect = [
            (
                1,  # filing_id
                "CA",
                date(2026, 6, 1),
                date(2026, 6, 30),
                "monthly",
                10000,
                850,
                0,
                "draft",
            ),
        ]
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_request.app.state.db = mock_conn

        req = Input(
            filing_id=1,
            status="filed",
            filing_date=date(2026, 7, 15),
            reference_number="CA-2026-06-001",
            tax_paid_cents=None,
            notes="Filed with CA Dept of Revenue",
        )

        user = {"id": 1}

        result = update_filing_status(1, req, mock_request, user)

        assert result.status == "filed"
        assert result.filing_date == date(2026, 7, 15)
        assert result.reference_number == "CA-2026-06-001"

    def test_update_filing_filed_to_paid(self):
        """Mark filing as paid."""
        from app.routes.tax_lifecycle import update_filing_status
        from pydantic import BaseModel

        class Input(BaseModel):
            filing_id: int
            status: str
            filing_date: date | None
            reference_number: str | None
            tax_paid_cents: int | None
            notes: str | None

        mock_request = MagicMock()
        mock_conn = MagicMock()
        mock_cursor = MagicMock()

        mock_cursor.fetchone.side_effect = [
            (
                1,
                "CA",
                date(2026, 6, 1),
                date(2026, 6, 30),
                "monthly",
                10000,
                850,
                0,
                "filed",
            ),
        ]
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_request.app.state.db = mock_conn

        req = Input(
            filing_id=1,
            status="paid",
            filing_date=None,
            reference_number=None,
            tax_paid_cents=850,  # Payment amount
            notes="Paid via ACH transfer",
        )

        user = {"id": 1}

        result = update_filing_status(1, req, mock_request, user)

        assert result.status == "paid"
        assert result.tax_paid_cents == 850

    def test_update_filing_paid_to_reconciled(self):
        """Mark filing as reconciled."""
        from app.routes.tax_lifecycle import update_filing_status
        from pydantic import BaseModel

        class Input(BaseModel):
            filing_id: int
            status: str
            filing_date: date | None
            reference_number: str | None
            tax_paid_cents: int | None
            notes: str | None

        mock_request = MagicMock()
        mock_conn = MagicMock()
        mock_cursor = MagicMock()

        mock_cursor.fetchone.side_effect = [
            (
                1,
                "CA",
                date(2026, 6, 1),
                date(2026, 6, 30),
                "monthly",
                10000,
                850,
                850,
                "paid",
            ),
        ]
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_request.app.state.db = mock_conn

        req = Input(
            filing_id=1,
            status="reconciled",
            filing_date=None,
            reference_number=None,
            tax_paid_cents=None,
            notes="Matched against bank statement",
        )

        user = {"id": 1}

        result = update_filing_status(1, req, mock_request, user)

        assert result.status == "reconciled"
