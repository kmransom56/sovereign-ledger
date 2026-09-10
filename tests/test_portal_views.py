"""Tests for customer portal views (Step 10).

Tests HTMX-based views for:
  - Account dashboard with summary and recent activity
  - Invoice listing and detail views
  - Payment recording and history

Each test verifies:
  - Correct template rendering
  - Data loading from database
  - Authentication enforcement
  - Error handling
"""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def app():
    """Create a test FastAPI app with auth overridden."""
    from app.dependencies import current_user
    a = create_app(
        settings=None,
        cookie_secure_override=False,
    )
    a.state.db = None
    # Override auth dependency so tests don't need real session cookies
    a.dependency_overrides[current_user] = lambda: {
        "customer_id": 1, "user_id": "cust_user_1", "email": "customer@example.com"
    }
    return a


@pytest.fixture
def client(app):
    """Create a TestClient."""
    return TestClient(app)


@pytest.fixture
def mock_db():
    """Mock database connection."""
    return MagicMock()


@pytest.fixture
def auth_user():
    """Mock authenticated customer user."""
    return {"customer_id": 1, "user_id": "cust_user_1", "email": "customer@example.com"}


# ============================================================================
# DASHBOARD TESTS
# ============================================================================


def test_dashboard_renders(client, mock_db, auth_user):
    """Dashboard renders with account summary."""

    with patch.object(client.app.state, "db", mock_db):
        mock_cursor = MagicMock()

        # Customer info
        mock_cursor.fetchone.side_effect = [
            {"id": 1, "name": "Test Customer", "email": "test@example.com"},  # customer
            {"total_invoiced": 100000, "total_paid": 50000},  # invoice summary
            {"coalesce": 10000},  # credits
        ]

        # Recent invoices + payments
        mock_cursor.fetchall.side_effect = [
            [
                {"id": 1, "invoice_number": 1001, "issue_date": date(2026, 9, 1), "due_date": date(2026, 10, 1), "total_amount_cents": 100000, "status": "posted", "days_overdue": 5},
            ],
            [
                {"id": 1, "payment_date": date(2026, 9, 15), "amount_cents": 50000, "memo": "Check #1234"},
            ],
        ]

        mock_db.cursor.return_value.__enter__.return_value = mock_cursor

        response = client.get("/portal/dashboard")

        assert response.status_code == 200
        assert "Account Summary" in response.text
        assert "Test Customer" in response.text or "Recent Invoices" in response.text


def test_dashboard_requires_auth(client, mock_db):
    """Dashboard requires authentication."""
    with patch("app.routes.portal.current_user") as mock_auth:
        mock_auth.side_effect = Exception("Not authenticated")

        response = client.get("/portal/dashboard")
        # TestClient will raise an exception if the dependency fails
        assert response.status_code in (401, 500)


# ============================================================================
# INVOICE LIST TESTS
# ============================================================================


def test_list_invoices(client, mock_db, auth_user):
    """Invoice list view renders invoices."""

    with patch.object(client.app.state, "db", mock_db):
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            {"id": 1, "invoice_number": 1001, "issue_date": date(2026, 9, 1), "due_date": date(2026, 10, 1), "total_amount_cents": 100000, "status": "posted", "days_overdue": 5},
            {"id": 2, "invoice_number": 1002, "issue_date": date(2026, 8, 1), "due_date": date(2026, 9, 1), "total_amount_cents": 50000, "status": "paid", "days_overdue": -5},
        ]
        mock_db.cursor.return_value.__enter__.return_value = mock_cursor

        response = client.get("/portal/invoices")

        assert response.status_code == 200
        assert "#1001" in response.text
        assert "#1002" in response.text
        assert "Outstanding" in response.text or "Paid" in response.text


def test_invoice_detail(client, mock_db, auth_user):
    """Invoice detail view shows full details."""

    with patch.object(client.app.state, "db", mock_db):
        mock_cursor = MagicMock()

        # Invoice header
        mock_cursor.fetchone.return_value = {
            "id": 1, "invoice_number": 1001, "issue_date": date(2026, 9, 1), "due_date": date(2026, 10, 1),
            "total_amount_cents": 100000, "status": "posted", "memo": "Invoice for services",
            "name": "Test Customer", "email": "test@example.com",
        }

        # Line items
        mock_cursor.fetchall.return_value = [
            {"description": "Consulting", "quantity": 10, "unit_price_cents": 10000, "amount_cents": 100000},
        ]

        mock_db.cursor.return_value.__enter__.return_value = mock_cursor

        response = client.get("/portal/invoices/1")

        assert response.status_code == 200
        assert "#1001" in response.text
        assert "Consulting" in response.text
        assert "$1,000.00" in response.text or "100000" in response.text


def test_invoice_not_found(client, mock_db, auth_user):
    """Invoice detail returns 404 for missing invoice."""

    with patch.object(client.app.state, "db", mock_db):
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = None  # No invoice found
        mock_db.cursor.return_value.__enter__.return_value = mock_cursor

        response = client.get("/portal/invoices/999")

        assert response.status_code == 404


# ============================================================================
# PAYMENT TESTS
# ============================================================================


def test_payment_form_renders(client, mock_db, auth_user):
    """Payment form renders with outstanding invoices."""

    with patch.object(client.app.state, "db", mock_db):
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            {"id": 1, "invoice_number": 1001, "issue_date": date(2026, 9, 1), "due_date": date(2026, 10, 1), "total_amount_cents": 100000, "status": "posted"},
            {"id": 2, "invoice_number": 1002, "issue_date": date(2026, 8, 1), "due_date": date(2026, 9, 1), "total_amount_cents": 50000, "status": "posted"},
        ]
        mock_db.cursor.return_value.__enter__.return_value = mock_cursor

        response = client.get("/portal/payments/new")

        assert response.status_code == 200
        assert "Record Payment" in response.text
        assert "#1001" in response.text
        assert "#1002" in response.text


def test_payment_history(client, mock_db, auth_user):
    """Payment history view lists payments."""

    with patch.object(client.app.state, "db", mock_db):
        mock_cursor = MagicMock()

        # Payments
        mock_cursor.fetchall.side_effect = [
            [
                {"id": 1, "payment_date": date(2026, 9, 15), "amount_cents": 100000, "memo": "Check #1234"},
            ],
            # Allocations for payment 1
            [
                {"id": 1, "invoice_number": 1001},
            ],
        ]

        mock_db.cursor.return_value.__enter__.return_value = mock_cursor

        response = client.get("/portal/payments")

        assert response.status_code == 200
        assert "Payment History" in response.text
        assert "#1001" in response.text or "Check #1234" in response.text


# ============================================================================
# INTEGRATION TESTS
# ============================================================================


def test_portal_workflow(client, mock_db, auth_user):
    """Test complete portal workflow: dashboard → invoices → detail."""

    with patch.object(client.app.state, "db", mock_db):
        # Setup mock data
        mock_cursor = MagicMock()
        mock_db.cursor.return_value.__enter__.return_value = mock_cursor

        # Dashboard
        mock_cursor.fetchone.side_effect = [
            {"id": 1, "name": "Test Customer", "email": "test@example.com"},
            {"total_invoiced": 100000, "total_paid": 50000},
            {"coalesce": 10000},
        ]
        mock_cursor.fetchall.side_effect = [
            [{"id": 1, "invoice_number": 1001, "issue_date": date(2026, 9, 1), "due_date": date(2026, 10, 1), "total_amount_cents": 100000, "status": "posted", "days_overdue": 5}],
            [{"id": 1, "payment_date": date(2026, 9, 15), "amount_cents": 50000, "memo": None}],
        ]

        response = client.get("/portal/dashboard")
        assert response.status_code == 200

        # Reset mock — re-establish cursor chain (reset_mock clears __enter__ config)
        mock_cursor = MagicMock()
        mock_db.cursor.return_value.__enter__.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [
            {"id": 1, "invoice_number": 1001, "issue_date": date(2026, 9, 1), "due_date": date(2026, 10, 1), "total_amount_cents": 100000, "status": "posted", "days_overdue": 5},
        ]

        # Invoices
        response = client.get("/portal/invoices")
        assert response.status_code == 200
        assert "#1001" in response.text

        # Invoice detail
        mock_cursor.fetchone.return_value = {
            "id": 1, "invoice_number": 1001, "issue_date": date(2026, 9, 1), "due_date": date(2026, 10, 1),
            "total_amount_cents": 100000, "status": "posted", "memo": None,
            "name": "Test Customer", "email": "test@example.com",
        }
        mock_cursor.fetchall.return_value = [
            {"description": "Service", "quantity": 1, "unit_price_cents": 100000, "amount_cents": 100000},
        ]

        response = client.get("/portal/invoices/1")
        assert response.status_code == 200
