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
        mock_cursor.fetchone.return_value = (
            1, "INV-001", 2, date(2026, 9, 1), date(2026, 10, 1),
            "Services rendered", 5000, "posted"
        )

        # Line items
        mock_cursor.fetchall.side_effect = [
            [
                (101, 1000, "Service A", 1, 5000, 5000),
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
        mock_cursor.fetchone.return_value = (
            1, "INV-001", 2, date(2026, 9, 1), date(2026, 10, 1),
            "Services", 5425, "posted"
        )

        # Line items: $50.00 subtotal
        mock_cursor.fetchall.side_effect = [
            [
                (101, 1000, "Service A", 1, 5000, 5000),
            ],
            [
                # Tax: CA 8.5%, $50 * 0.085 = $4.25 (425 cents)
                (101, "CA", "California", 8.500, 5000, 425),
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
        mock_cursor.fetchone.return_value = (
            1, "INV-001", 2, date(2026, 9, 1), date(2026, 10, 1),
            "Services", 11100, "posted"
        )

        # Line items
        mock_cursor.fetchall.side_effect = [
            [
                (101, 1000, "Service", 1, 10000, 10000),
            ],
            [
                # CA sales tax: 8.5%
                (101, "CA", "California", 8.500, 10000, 850),
                # Local tax: 2.5%
                (101, "LOCAL", "Local Tax", 2.500, 10000, 250),
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
        mock_cursor.fetchone.return_value = (
            1, "INV-002", 2, date(2026, 9, 1), date(2026, 10, 1),
            "Mixed items", 5255, "posted"
        )

        # Line items
        mock_cursor.fetchall.side_effect = [
            [
                (101, 1000, "Taxable Service", 1, 3000, 3000),
                (102, 1000, "Exempt Service", 1, 2000, 2000),
            ],
            [
                # Only line 101 has tax
                (101, "CA", "California", 8.500, 3000, 255),
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

        mock_cursor.fetchone.return_value = (
            1, "INV-001", 2, date(2026, 9, 1), date(2026, 10, 1),
            "Resale", 5000, "posted"
        )

        # Line items
        mock_cursor.fetchall.side_effect = [
            [
                (101, 1000, "Merchandise", 1, 5000, 5000),
            ],
            [
                # Tax amount is 0 but details show it was evaluated
                (101, "CA", "California", 8.500, 5000, 0),
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

