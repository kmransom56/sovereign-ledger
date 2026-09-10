"""Tests for AR invoice detail with tax breakdown (Step 11).

Tests displaying tax line items and tax summary on invoice detail.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

import pytest


class TestInvoiceDetailWithTax:
    """Test invoice detail endpoint includes tax information."""

    def test_invoice_detail_no_tax(self):
        """Invoice with no taxes shows basic details."""
        from app.routes.ar import get_invoice

        mock_request = MagicMock()
        mock_conn = MagicMock()
        mock_cursor = MagicMock()

        # Invoice header
        mock_cursor.fetchone.return_value = {
            "id": 1, "invoice_number": "INV-001", "customer_id": 2,
            "issue_date": date(2026, 9, 1), "due_date": date(2026, 10, 1),
            "memo": "Services rendered", "total_amount_cents": 5000, "status": "posted",
        }

        # Line items
        mock_cursor.fetchall.side_effect = [
            [
                {"id": 101, "account_id": 1000, "description": "Service A", "quantity": 1, "unit_price_cents": 5000, "amount_cents": 5000},
            ],
            [],  # No taxes
        ]

        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_request.app.state.db = mock_conn

        user = {"id": 1}
        result = get_invoice(1, mock_request, user)

        assert result["invoice"]["id"] == 1
        assert result["invoice"]["invoice_number"] == "INV-001"
        assert result["invoice"]["subtotal_cents"] == 5000
        assert result["invoice"]["total_tax_cents"] == 0
        assert result["invoice"]["total_cents"] == 5000
        assert len(result["invoice"]["lines"]) == 1
        assert result["invoice"]["lines"][0]["taxes"] == []
        assert result["invoice"]["lines"][0]["tax_total_cents"] == 0
        assert result["invoice"]["lines"][0]["total_with_tax_cents"] == 5000

    def test_invoice_detail_single_tax_jurisdiction(self):
        """Invoice with tax from one jurisdiction."""
        from app.routes.ar import get_invoice

        mock_request = MagicMock()
        mock_conn = MagicMock()
        mock_cursor = MagicMock()

        # Invoice header: $50.00 total
        mock_cursor.fetchone.return_value = {
            "id": 1, "invoice_number": "INV-001", "customer_id": 2,
            "issue_date": date(2026, 9, 1), "due_date": date(2026, 10, 1),
            "memo": "Services", "total_amount_cents": 5425, "status": "posted",
        }

        # Line items: $50.00 subtotal
        mock_cursor.fetchall.side_effect = [
            [
                {"id": 101, "account_id": 1000, "description": "Service A", "quantity": 1, "unit_price_cents": 5000, "amount_cents": 5000},
            ],
            [
                # Tax: CA 8.5%, $50 * 0.085 = $4.25 (425 cents)
                {"invoice_line_id": 101, "code": "CA", "name": "California", "rate_percent": 8.500, "taxable_amount_cents": 5000, "tax_amount_cents": 425},
            ],
        ]

        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_request.app.state.db = mock_conn

        user = {"id": 1}
        result = get_invoice(1, mock_request, user)

        assert result["invoice"]["subtotal_cents"] == 5000
        assert result["invoice"]["total_tax_cents"] == 425
        assert result["invoice"]["total_cents"] == 5425

        line = result["invoice"]["lines"][0]
        assert len(line["taxes"]) == 1
        assert line["taxes"][0]["jurisdiction"] == "CA"
        assert line["taxes"][0]["rate_percent"] == 8.5
        assert line["taxes"][0]["tax_amount_cents"] == 425
        assert line["tax_total_cents"] == 425
        assert line["total_with_tax_cents"] == 5425

    def test_invoice_detail_multiple_tax_jurisdictions(self):
        """Invoice with taxes from multiple jurisdictions."""
        from app.routes.ar import get_invoice

        mock_request = MagicMock()
        mock_conn = MagicMock()
        mock_cursor = MagicMock()

        # Invoice: $100.00 + $8.50 (CA sales) + $2.50 (local) = $111.00
        mock_cursor.fetchone.return_value = {
            "id": 1, "invoice_number": "INV-001", "customer_id": 2,
            "issue_date": date(2026, 9, 1), "due_date": date(2026, 10, 1),
            "memo": "Services", "total_amount_cents": 11100, "status": "posted",
        }

        # Line items
        mock_cursor.fetchall.side_effect = [
            [
                {"id": 101, "account_id": 1000, "description": "Service", "quantity": 1, "unit_price_cents": 10000, "amount_cents": 10000},
            ],
            [
                # CA sales tax: 8.5%
                {"invoice_line_id": 101, "code": "CA", "name": "California", "rate_percent": 8.500, "taxable_amount_cents": 10000, "tax_amount_cents": 850},
                # Local tax: 2.5%
                {"invoice_line_id": 101, "code": "LOCAL", "name": "Local Tax", "rate_percent": 2.500, "taxable_amount_cents": 10000, "tax_amount_cents": 250},
            ],
        ]

        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_request.app.state.db = mock_conn

        user = {"id": 1}
        result = get_invoice(1, mock_request, user)

        assert result["invoice"]["subtotal_cents"] == 10000
        assert result["invoice"]["total_tax_cents"] == 1100  # 850 + 250
        assert result["invoice"]["total_cents"] == 11100

        line = result["invoice"]["lines"][0]
        assert len(line["taxes"]) == 2
        assert line["tax_total_cents"] == 1100
        assert line["total_with_tax_cents"] == 11100

    def test_invoice_detail_multiple_lines_different_taxes(self):
        """Invoice with multiple lines, each with different taxes."""
        from app.routes.ar import get_invoice

        mock_request = MagicMock()
        mock_conn = MagicMock()
        mock_cursor = MagicMock()

        # Two lines: $30 + $20 = $50 subtotal
        # Line 1 (taxable): $30 + $2.55 CA tax
        # Line 2 (exempt): $20 + $0 tax
        # Total: $52.55
        mock_cursor.fetchone.return_value = {
            "id": 1, "invoice_number": "INV-002", "customer_id": 2,
            "issue_date": date(2026, 9, 1), "due_date": date(2026, 10, 1),
            "memo": "Mixed items", "total_amount_cents": 5255, "status": "posted",
        }

        # Line items
        mock_cursor.fetchall.side_effect = [
            [
                {"id": 101, "account_id": 1000, "description": "Taxable Service", "quantity": 1, "unit_price_cents": 3000, "amount_cents": 3000},
                {"id": 102, "account_id": 1000, "description": "Exempt Service", "quantity": 1, "unit_price_cents": 2000, "amount_cents": 2000},
            ],
            [
                # Only line 101 has tax
                {"invoice_line_id": 101, "code": "CA", "name": "California", "rate_percent": 8.500, "taxable_amount_cents": 3000, "tax_amount_cents": 255},
            ],
        ]

        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_request.app.state.db = mock_conn

        user = {"id": 1}
        result = get_invoice(1, mock_request, user)

        assert result["invoice"]["subtotal_cents"] == 5000
        assert result["invoice"]["total_tax_cents"] == 255
        assert result["invoice"]["total_cents"] == 5255

        # Line 1 has tax
        line1 = result["invoice"]["lines"][0]
        assert line1["amount_cents"] == 3000
        assert len(line1["taxes"]) == 1
        assert line1["tax_total_cents"] == 255
        assert line1["total_with_tax_cents"] == 3255

        # Line 2 is exempt (no tax)
        line2 = result["invoice"]["lines"][1]
        assert line2["amount_cents"] == 2000
        assert len(line2["taxes"]) == 0
        assert line2["tax_total_cents"] == 0
        assert line2["total_with_tax_cents"] == 2000

    def test_invoice_detail_tax_with_exemption(self):
        """Invoice shows tax details including exemption indicator."""
        from app.routes.ar import get_invoice

        mock_request = MagicMock()
        mock_conn = MagicMock()
        mock_cursor = MagicMock()

        mock_cursor.fetchone.return_value = {
            "id": 1, "invoice_number": "INV-001", "customer_id": 2,
            "issue_date": date(2026, 9, 1), "due_date": date(2026, 10, 1),
            "memo": "Resale", "total_amount_cents": 5000, "status": "posted",
        }

        # Line items
        mock_cursor.fetchall.side_effect = [
            [
                {"id": 101, "account_id": 1000, "description": "Merchandise", "quantity": 1, "unit_price_cents": 5000, "amount_cents": 5000},
            ],
            [
                # Tax amount is 0 but details show it was evaluated
                {"invoice_line_id": 101, "code": "CA", "name": "California", "rate_percent": 8.500, "taxable_amount_cents": 5000, "tax_amount_cents": 0},
            ],
        ]

        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_request.app.state.db = mock_conn

        user = {"id": 1}
        result = get_invoice(1, mock_request, user)

        assert result["invoice"]["total_tax_cents"] == 0
        line = result["invoice"]["lines"][0]
        # Even though tax is 0, the jurisdiction was checked
        assert len(line["taxes"]) == 1
        assert line["taxes"][0]["tax_amount_cents"] == 0
        assert line["taxes"][0]["jurisdiction"] == "CA"

