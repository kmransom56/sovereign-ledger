"""Tests for Accounts Payable: vendors, bills, payments (Step 12).

Tests vendor management, bill creation/posting, payment recording, and AP aging.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

import pytest


class TestVendorCRUD:
    """Test vendor create/read operations."""

    def test_create_vendor(self):
        """Create a new vendor."""
        from app.routes.ap import create_vendor
        from pydantic import BaseModel

        class Input(BaseModel):
            name: str
            tax_id: str | None = None
            contact_name: str | None = None
            email: str | None = None
            phone: str | None = None
            address: str | None = None
            city: str | None = None
            state: str | None = None
            zip_code: str | None = None
            payment_terms: str | None = None
            notes: str | None = None

        mock_request = MagicMock()
        mock_conn = MagicMock()
        mock_cursor = MagicMock()

        mock_cursor.fetchone.return_value = (1, True)  # vendor_id, is_active
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_request.app.state.db = mock_conn

        req = Input(
            name="Google LLC",
            tax_id="12-3456789",
            email="billing@google.com",
            payment_terms="net30",
        )

        user = {"id": 1}

        result = create_vendor(req, mock_request, user)

        assert result.id == 1
        assert result.name == "Google LLC"
        assert result.tax_id == "12-3456789"
        assert result.payment_terms == "net30"
        assert result.is_active is True

    def test_get_vendor(self):
        """Retrieve vendor details."""
        from app.routes.ap import get_vendor

        mock_request = MagicMock()
        mock_conn = MagicMock()
        mock_cursor = MagicMock()

        mock_cursor.fetchone.return_value = (
            1,
            "Google LLC",
            "12-3456789",
            "Billing",
            "billing@google.com",
            "1-800-555-1234",
            "1600 Amphitheatre Parkway",
            "Mountain View",
            "CA",
            "94043",
            "net30",
            True,
            "Production vendor",
        )
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_request.app.state.db = mock_conn

        user = {"id": 1}

        result = get_vendor(1, mock_request, user)

        assert result.id == 1
        assert result.name == "Google LLC"
        assert result.city == "Mountain View"
        assert result.state == "CA"


class TestBillPosting:
    """Test bill creation and posting."""

    def test_post_bill_single_category(self):
        """Post a bill with single expense category."""
        from app.adapters.ap_posting import post_bill

        mock_conn = MagicMock()
        mock_cursor = MagicMock()

        # Mock query sequence (new order after refactoring):
        # 1. fetchall() from load_accounts_catalog - returns list of accounts
        # 2. fetchone() from load_ap_liability_account - returns AP account (2100)
        # 3. fetchall() from load_fiscal_periods
        # 4. fetchone() from load_vendor - returns vendor
        # 5. fetchone() from load_expense_category - returns expense category
        # 6. fetchone() from INSERT bill - returns bill_id
        # 7. fetchone() from INSERT journal_entries - returns entry_id

        # Set up fetchone for individual queries (in order of execution)
        # load_vendor is called FIRST
        mock_cursor.fetchone.side_effect = [
            (1, "Google LLC", None, "billing@google.com", "net30", True),  # load_vendor (called FIRST)
            ("2100 Accounts Payable", "Liabilities", "payable", None),  # load_ap_liability_account
            (1, "SW", "Software", 5000, True),  # load_expense_category
            (1,),  # INSERT bill - bill_id
            (101,),  # INSERT journal_entries - entry_id
        ]

        # Set up fetchall for accounts (for load_accounts_catalog and fiscal_periods)
        mock_cursor.fetchall.side_effect = [
            [  # Accounts
                (1000, "1000 Checking Account", "Assets", "bank", None),
                (2100, "2100 Accounts Payable", "Liabilities", "payable", None),
                (5000, "5000 Software Expense", "Expenses", "operating_expense", None),
            ],
            [  # Fiscal periods
                ("2026-09", 2026, date(2026, 9, 1), date(2026, 9, 30), "open"),
            ],
        ]

        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_conn.commit = MagicMock()

        bill_items = [
            {
                "expense_category_id": 1,
                "description": "Google Workspace (12 users)",
                "quantity": 1,
                "unit_price_cents": 14400,  # $144/month
                "business_use_percent": 100.0,
            }
        ]

        result = post_bill(
            conn=mock_conn,
            bill_number="GOOG-001",
            vendor_id=1,
            bill_date=date(2026, 9, 1),
            due_date=date(2026, 10, 1),
            memo="Google Workspace",
            period_end=None,
            bill_items=bill_items,
            fiscal_period_id=1,
        )

        assert result["bill_id"] == 1
        assert result["bill_number"] == "GOOG-001"
        assert result["total_amount_cents"] == 14400
        assert result["deductible_amount_cents"] == 14400

    def test_post_bill_mixed_use_expense(self):
        """Post a bill with mixed-use expense (80% business, 20% personal)."""
        from app.adapters.ap_posting import post_bill

        mock_conn = MagicMock()
        mock_cursor = MagicMock()

        # Mock query sequence
        mock_cursor.fetchall.side_effect = [
            [  # Accounts
                (1000, "1000 Checking Account", "Assets", "bank", None),
                (2100, "2100 Accounts Payable", "Liabilities", "payable", None),
                (5100, "5100 Utilities Expense", "Expenses", "operating_expense", None),
            ],
            [  # Fiscal periods
                ("2026-09", 2026, date(2026, 9, 1), date(2026, 9, 30), "open"),
            ],
        ]

        mock_cursor.fetchone.side_effect = [
            (1, "Comcast", None, "billing@comcast.com", "net30", True),  # vendor (FIRST)
            ("2100 Accounts Payable", "Liabilities", "payable", None),  # AP account
            (2, "UTIL", "Utilities", 5100, True),  # expense category
            (2,),  # bill_id
            (102,),  # entry_id
        ]

        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_conn.commit = MagicMock()

        bill_items = [
            {
                "expense_category_id": 2,
                "description": "Internet (home office + personal use)",
                "quantity": 1,
                "unit_price_cents": 9999,  # $99.99/month
                "business_use_percent": 80.0,  # 80% business deductible
            }
        ]

        result = post_bill(
            conn=mock_conn,
            bill_number="COMCAST-001",
            vendor_id=1,
            bill_date=date(2026, 9, 1),
            due_date=date(2026, 10, 1),
            memo="Internet",
            period_end=None,
            bill_items=bill_items,
            fiscal_period_id=1,
        )

        assert result["total_amount_cents"] == 9999
        # 80% of 9999 = 7999.2 → 7999 cents (banker's rounding)
        assert result["deductible_amount_cents"] == 7999

    def test_post_bill_multiple_categories(self):
        """Post a bill with multiple expense categories."""
        from app.adapters.ap_posting import post_bill

        mock_conn = MagicMock()
        mock_cursor = MagicMock()

        # Mock query sequence
        mock_cursor.fetchall.side_effect = [
            [  # Accounts
                (1000, "1000 Checking Account", "Assets", "bank", None),
                (2100, "2100 Accounts Payable", "Liabilities", "payable", None),
                (5000, "5000 Software Expense", "Expenses", "operating_expense", None),
                (5001, "5001 AI Services Expense", "Expenses", "operating_expense", None),
            ],
            [  # Fiscal periods
                ("2026-09", 2026, date(2026, 9, 1), date(2026, 9, 30), "open"),
            ],
        ]

        mock_cursor.fetchone.side_effect = [
            (3, "OpenAI", None, "billing@openai.com", "net30", True),  # vendor (FIRST)
            ("2100 Accounts Payable", "Liabilities", "payable", None),  # AP account
            (1, "SW", "Software", 5000, True),  # category 1
            (3, "AI", "AI Services", 5001, True),  # category 3
            (3,),  # bill_id
            (103,),  # entry_id
        ]

        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_conn.commit = MagicMock()

        bill_items = [
            {
                "expense_category_id": 1,
                "description": "ChatGPT Plus",
                "quantity": 1,
                "unit_price_cents": 2000,  # $20
                "business_use_percent": 100.0,
            },
            {
                "expense_category_id": 3,
                "description": "OpenAI API Credits",
                "quantity": 1,
                "unit_price_cents": 10000,  # $100
                "business_use_percent": 100.0,
            },
        ]

        result = post_bill(
            conn=mock_conn,
            bill_number="OPENAI-001",
            vendor_id=3,
            bill_date=date(2026, 9, 1),
            due_date=date(2026, 10, 1),
            memo="AI subscriptions",
            period_end=None,
            bill_items=bill_items,
            fiscal_period_id=1,
        )

        assert result["bill_id"] == 3
        assert result["total_amount_cents"] == 12000  # 2000 + 10000
        assert result["deductible_amount_cents"] == 12000


class TestPaymentRecording:
    """Test payment recording against bills."""

    def test_record_payment_partial(self):
        """Record partial payment against a bill."""
        from app.adapters.ap_posting import record_payment

        mock_conn = MagicMock()
        mock_cursor = MagicMock()

        # Mock query sequence
        mock_cursor.fetchone.side_effect = [
            (1, "GOOG-001", 1, 14400, 0),  # bill details (FIRST)
            (1, "Google LLC", None, "billing@google.com", "net30", True),  # vendor
            ("2100 Accounts Payable", "Liabilities", "payable", None),  # AP account
            (201,),  # entry_id from INSERT journal_entries
            (501,),  # payment_id from INSERT bill_payments
        ]

        mock_cursor.fetchall.side_effect = [
            [  # Accounts
                (1000, "1000 Checking Account", "Assets", "bank", None),
                (2100, "2100 Accounts Payable", "Liabilities", "payable", None),
            ],
            [  # Fiscal periods
                ("2026-09", 2026, date(2026, 9, 1), date(2026, 9, 30), "open"),
            ],
        ]

        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_conn.commit = MagicMock()

        result = record_payment(
            conn=mock_conn,
            bill_id=1,
            payment_date=date(2026, 9, 15),
            amount_cents=7200,  # Pay half ($72)
            payment_method="ach",
            reference_number="ACH-20260915-001",
            fiscal_period_id=1,
            bank_account_id=1000,
        )

        assert result["payment_id"] == 501
        assert result["bill_id"] == 1
        assert result["amount_cents"] == 7200
        assert result["new_paid_total"] == 7200
        assert result["outstanding_cents"] == 7200  # 14400 - 7200

    def test_record_payment_full(self):
        """Record full payment to complete bill."""
        from app.adapters.ap_posting import record_payment

        mock_conn = MagicMock()
        mock_cursor = MagicMock()

        # Mock query sequence
        # Bill with $100 already paid, $50 remaining
        mock_cursor.fetchone.side_effect = [
            (1, "UTIL-001", 2, 15000, 10000),  # bill: $150, paid $100 (FIRST)
            (2, "Comcast", None, "billing@comcast.com", "net30", True),  # vendor
            ("2100 Accounts Payable", "Liabilities", "payable", None),  # AP account
            (202,),  # entry_id from INSERT journal_entries
            (502,),  # payment_id from INSERT bill_payments
        ]

        mock_cursor.fetchall.side_effect = [
            [  # Accounts
                (1000, "1000 Checking Account", "Assets", "bank", None),
                (2100, "2100 Accounts Payable", "Liabilities", "payable", None),
            ],
            [  # Fiscal periods
                ("2026-09", 2026, date(2026, 9, 1), date(2026, 9, 30), "open"),
            ],
        ]

        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_conn.commit = MagicMock()

        result = record_payment(
            conn=mock_conn,
            bill_id=1,
            payment_date=date(2026, 9, 30),
            amount_cents=5000,  # Pay remaining $50
            payment_method="check",
            reference_number="CHK-1001",
            fiscal_period_id=1,
            bank_account_id=1000,
        )

        assert result["payment_id"] == 502
        assert result["new_paid_total"] == 15000  # Fully paid
        assert result["outstanding_cents"] == 0


class TestAPAging:
    """Test AP aging report."""

    def test_ap_aging_multiple_bills(self):
        """AP aging shows unpaid bills by due date."""
        from app.routes.ap import ap_aging_report

        mock_request = MagicMock()
        mock_conn = MagicMock()
        mock_cursor = MagicMock()

        # Three bills: one overdue, one current, one paid
        mock_cursor.fetchall.return_value = [
            (1, "GOOG-001", "Google LLC", date(2026, 8, 1), date(2026, 8, 31), 14400, 0, 14400, "Overdue", 3),
            (2, "UTIL-001", "Comcast", date(2026, 9, 1), date(2026, 10, 1), 15000, 0, 15000, "Current", None),
            (3, "OPENAI-001", "OpenAI", date(2026, 8, 15), date(2026, 9, 15), 12000, 12000, 0, "Paid", None),
        ]

        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_request.app.state.db = mock_conn

        user = {"id": 1}

        result = ap_aging_report(mock_request, user)

        # Should include 2 unpaid bills (overdue and current)
        assert len(result["rows"]) == 3
        assert result["total_outstanding_cents"] == 29400
        assert result["overdue_count"] == 1
        assert result["current_count"] == 1


class TestExpenseSummary:
    """Test expense summary for tax reporting."""

    def test_expense_summary_by_category(self):
        """Expense summary aggregates by category for deduction reporting."""
        from app.routes.ap import expense_summary

        mock_request = MagicMock()
        mock_conn = MagicMock()
        mock_cursor = MagicMock()

        # Summary by category
        mock_cursor.fetchall.return_value = [
            ("AI", "AI Services", True, 22000, 22000, 2),  # OpenAI + ChatGPT
            ("SW", "Software", True, 14400, 14400, 1),  # Google Workspace
            ("UTIL", "Utilities", True, 15000, 12000, 1),  # Comcast (80% business)
        ]

        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_request.app.state.db = mock_conn

        user = {"id": 1}

        result = expense_summary(mock_request, user)

        assert len(result["categories"]) == 3
        assert result["total_amount_cents"] == 51400
        assert result["total_deductible_cents"] == 48400  # Respects business-use %

        # Find the utilities category
        util = next(c for c in result["categories"] if c["category_code"] == "UTIL")
        assert util["total_cents"] == 15000
        assert util["deductible_cents"] == 12000  # 80% of 15000
