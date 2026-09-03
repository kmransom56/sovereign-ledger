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
    """Create a test FastAPI app."""
    return create_app(
        settings=None,
        cookie_secure_override=False,
    )


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
    with patch("app.routes.portal.current_user") as mock_auth:
        mock_auth.return_value = auth_user

        with patch.object(client.app.state, "db", mock_db):
            mock_cursor = MagicMock()

            # Customer info
            mock_cursor.fetchone.side_effect = [
                (1, "Test Customer", "test@example.com"),  # customer
                (100000, 50000),  # invoice summary
                (10000,),  # credits
            ]

            # Recent invoices + payments
            mock_cursor.fetchall.side_effect = [
                [
                    (1, 1001, date(2026, 9, 1), date(2026, 10, 1), 100000, "posted", 5),
                ],
                [
                    (1, date(2026, 9, 15), 50000, "Check #1234"),
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
    with patch("app.routes.portal.current_user") as mock_auth:
        mock_auth.return_value = auth_user

        with patch.object(client.app.state, "db", mock_db):
            mock_cursor = MagicMock()
            mock_cursor.fetchall.return_value = [
                (1, 1001, date(2026, 9, 1), date(2026, 10, 1), 100000, "posted", 5),
                (2, 1002, date(2026, 8, 1), date(2026, 9, 1), 50000, "paid", -5),
            ]
            mock_db.cursor.return_value.__enter__.return_value = mock_cursor

            response = client.get("/portal/invoices")

            assert response.status_code == 200
            assert "#1001" in response.text
            assert "#1002" in response.text
            assert "Outstanding" in response.text or "Paid" in response.text


def test_invoice_detail(client, mock_db, auth_user):
    """Invoice detail view shows full details."""
    with patch("app.routes.portal.current_user") as mock_auth:
        mock_auth.return_value = auth_user

        with patch.object(client.app.state, "db", mock_db):
            mock_cursor = MagicMock()

            # Invoice header
            mock_cursor.fetchone.return_value = (
                1, 1001, date(2026, 9, 1), date(2026, 10, 1),
                100000, "posted", "Invoice for services", "Test Customer", "test@example.com"
            )

            # Line items
            mock_cursor.fetchall.return_value = [
                ("Consulting", 10, 10000, 100000),
            ]

            mock_db.cursor.return_value.__enter__.return_value = mock_cursor

            response = client.get("/portal/invoices/1")

            assert response.status_code == 200
            assert "#1001" in response.text
            assert "Consulting" in response.text
            assert "$1,000.00" in response.text or "100000" in response.text


def test_invoice_not_found(client, mock_db, auth_user):
    """Invoice detail returns 404 for missing invoice."""
    with patch("app.routes.portal.current_user") as mock_auth:
        mock_auth.return_value = auth_user

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
    with patch("app.routes.portal.current_user") as mock_auth:
        mock_auth.return_value = auth_user

        with patch.object(client.app.state, "db", mock_db):
            mock_cursor = MagicMock()
            mock_cursor.fetchall.return_value = [
                (1, 1001, date(2026, 9, 1), date(2026, 10, 1), 100000, "posted"),
                (2, 1002, date(2026, 8, 1), date(2026, 9, 1), 50000, "posted"),
            ]
            mock_db.cursor.return_value.__enter__.return_value = mock_cursor

            response = client.get("/portal/payments/new")

            assert response.status_code == 200
            assert "Record Payment" in response.text
            assert "#1001" in response.text
            assert "#1002" in response.text


def test_payment_history(client, mock_db, auth_user):
    """Payment history view lists payments."""
    with patch("app.routes.portal.current_user") as mock_auth:
        mock_auth.return_value = auth_user

        with patch.object(client.app.state, "db", mock_db):
            mock_cursor = MagicMock()

            # Payments
            mock_cursor.fetchall.side_effect = [
                [
                    (1, date(2026, 9, 15), 100000, "Check #1234"),
                ],
                # Allocations for payment 1
                [
                    (1, 1001),
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
    with patch("app.routes.portal.current_user") as mock_auth:
        mock_auth.return_value = auth_user

        with patch.object(client.app.state, "db", mock_db):
            # Setup mock data
            mock_cursor = MagicMock()
            mock_db.cursor.return_value.__enter__.return_value = mock_cursor

            # Dashboard
            mock_cursor.fetchone.side_effect = [
                (1, "Test Customer", "test@example.com"),
                (100000, 50000),
                (10000,),
            ]
            mock_cursor.fetchall.side_effect = [
                [(1, 1001, date(2026, 9, 1), date(2026, 10, 1), 100000, "posted", 5)],
                [(1, date(2026, 9, 15), 50000, None)],
            ]

            response = client.get("/portal/dashboard")
            assert response.status_code == 200

            # Reset mock
            mock_cursor.reset_mock()
            mock_cursor.fetchall.return_value = [
                (1, 1001, date(2026, 9, 1), date(2026, 10, 1), 100000, "posted", 5),
            ]

            # Invoices
            response = client.get("/portal/invoices")
            assert response.status_code == 200
            assert "#1001" in response.text

            # Invoice detail
            mock_cursor.fetchone.return_value = (
                1, 1001, date(2026, 9, 1), date(2026, 10, 1),
                100000, "posted", None, "Test Customer", "test@example.com"
            )
            mock_cursor.fetchall.return_value = [
                ("Service", 1, 100000, 100000),
            ]

            response = client.get("/portal/invoices/1")
            assert response.status_code == 200
