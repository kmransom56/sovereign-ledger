"""Tests for AR routes: customers, invoices, payments, templates, reports (Step 9).

Tests the FastAPI route layer with mocked database. Each test:
  1. Sets up mock database state
  2. Calls the route via TestClient
  3. Verifies response and database interactions

Key coverage:
  - Customer CRUD (create, list, get, update status)
  - Invoice creation and posting (validates period, customer, gapless numbering)
  - Payment allocation and posting
  - Recurring template management
  - AR reports (aging, statements, overdue)
  - Error handling (validation, not found, server errors)
"""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import MagicMock, Mock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def app():
    """Create a test FastAPI app with auth overridden."""
    from app.dependencies import current_user
    a = create_app(
        settings=None,
        cookie_secure_override=False,  # Allow HTTP in tests
    )
    a.state.db = None
    a.dependency_overrides[current_user] = lambda: {"id": "test_user"}
    return a


@pytest.fixture
def client(app):
    """Create a TestClient for the app."""
    return TestClient(app)


@pytest.fixture
def mock_db():
    """Mock database connection."""
    db = MagicMock()
    db.transaction = MagicMock()
    db.cursor = MagicMock()
    db.commit = MagicMock()
    db.rollback = MagicMock()
    return db


@pytest.fixture
def setup_auth(client):
    """Setup fake auth session."""

    def _setup(user_id: str = "test_user"):
        # For tests, we'd mock the current_user dependency
        pass

    return _setup


# ============================================================================
# CUSTOMER TESTS
# ============================================================================


def test_create_customer_success(client, mock_db):
    """Create a new customer with valid data."""
    with patch.object(client.app.state, "db", mock_db):
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = (1,)  # customer_id
        mock_db.cursor.return_value.__enter__.return_value = mock_cursor

        response = client.post(
            "/ar/customers",
            json={
                "name": "Acme Corp",
                "tax_id": "12-3456789",
                "email": "contact@acme.com",
                "address": "123 Main St",
                "notes": "Premium customer",
            },
            headers={"Authorization": "Bearer test_token"},
        )

        assert response.status_code == 201
        assert response.json()["customer_id"] == 1
        assert response.json()["name"] == "Acme Corp"


def test_create_customer_missing_name(client, mock_db):
    """Reject customer creation without name."""
    with patch.object(client.app.state, "db", mock_db):
        response = client.post(
            "/ar/customers",
            json={"tax_id": "12-3456789"},
            headers={"Authorization": "Bearer test_token"},
        )

        assert response.status_code == 422
        assert "name is required" in response.json()["detail"]


def test_list_customers(client, mock_db):
    """List all customers."""
    with patch.object(client.app.state, "db", mock_db):
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            (1, "Acme Corp", "12-3456789", "active", "2026-01-01"),
            (2, "Beta Inc", "12-3456790", "active", "2026-02-01"),
        ]
        mock_db.cursor.return_value.__enter__.return_value = mock_cursor

        response = client.get(
            "/ar/customers",
            headers={"Authorization": "Bearer test_token"},
        )

        assert response.status_code == 200
        assert len(response.json()["customers"]) == 2
        assert response.json()["customers"][0]["name"] == "Acme Corp"


def test_update_customer_status(client, mock_db):
    """Update customer status (requires admin)."""
    with patch("app.routes.ar.require_admin") as mock_admin:
        mock_admin.return_value = {"id": "admin_user", "role": "admin"}

    with patch.object(client.app.state, "db", mock_db):
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = (1, "Acme Corp")
        mock_db.cursor.return_value.__enter__.return_value = mock_cursor

        response = client.patch(
            "/ar/customers/1/status",
            json={"status": "inactive"},
            headers={"Authorization": "Bearer admin_token"},
        )

        assert response.status_code == 200
        assert response.json()["new_status"] == "inactive"


# ============================================================================
# INVOICE TESTS
# ============================================================================


def test_create_invoice_success(client, mock_db):
    """Create and post an invoice."""
    with patch("app.routes.ar.post_invoice") as mock_post:
            mock_post.return_value = 123  # invoice_id

            with patch.object(client.app.state, "db", mock_db):
                mock_cursor = MagicMock()
                mock_db.cursor.return_value.__enter__.return_value = mock_cursor

                response = client.post(
                    "/ar/invoices",
                    json={
                        "customer_id": 1,
                        "issue_date": "2026-09-01",
                        "due_date": "2026-10-01",
                        "fiscal_period_id": 1,
                        "ar_account_id": 100,
                        "memo": "Invoice for services",
                        "lines": [
                            {
                                "account_id": 200,
                                "description": "Consulting",
                                "quantity": 10,
                                "unit_price_cents": 10000,
                            }
                        ],
                    },
                    headers={"Authorization": "Bearer test_token"},
                )

                assert response.status_code == 201
                assert response.json()["invoice_id"] == 123


def test_create_invoice_invalid_date(client, mock_db):
    """Reject invoice with invalid date format."""
    with patch.object(client.app.state, "db", mock_db):
        response = client.post(
            "/ar/invoices",
            json={
                "customer_id": 1,
                "issue_date": "not-a-date",
                "due_date": "2026-10-01",
                "fiscal_period_id": 1,
                "ar_account_id": 100,
                "lines": [],
            },
            headers={"Authorization": "Bearer test_token"},
        )

        assert response.status_code == 422
        assert "Invalid date format" in response.json()["detail"]


def test_update_invoice_status(client, mock_db):
    """Update invoice status (mark paid/void)."""
    with patch("app.routes.ar.require_admin") as mock_admin:
        mock_admin.return_value = {"id": "admin_user"}

    with patch.object(client.app.state, "db", mock_db):
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = ("posted",)  # old status
        mock_db.cursor.return_value.__enter__.return_value = mock_cursor

        response = client.patch(
            "/ar/invoices/123/status",
            json={"status": "paid"},
            headers={"Authorization": "Bearer admin_token"},
        )

        assert response.status_code == 200
        assert response.json()["new_status"] == "paid"


# ============================================================================
# PAYMENT TESTS
# ============================================================================


def test_record_payment_success(client, mock_db):
    """Record and allocate a payment."""
    with patch("app.routes.ar.post_payment") as mock_post:
            mock_post.return_value = 456  # payment_id

            with patch.object(client.app.state, "db", mock_db):
                mock_cursor = MagicMock()
                mock_db.cursor.return_value.__enter__.return_value = mock_cursor

                response = client.post(
                    "/ar/payments",
                    json={
                        "customer_id": 1,
                        "payment_date": "2026-09-15",
                        "amount_cents": 50000,
                        "memo": "Check #1234",
                        "invoices": [(1, 30000), (2, 20000)],
                        "bank_account_id": 300,
                        "ar_account_id": 100,
                        "customer_credits_account_id": 400,
                        "fiscal_period_id": 1,
                    },
                    headers={"Authorization": "Bearer test_token"},
                )

                assert response.status_code == 201
                assert response.json()["payment_id"] == 456


def test_record_payment_overpayment(client, mock_db):
    """Payment exceeding invoice due creates customer credits."""
    with patch("app.routes.ar.post_payment") as mock_post:
            mock_post.return_value = 456

            with patch.object(client.app.state, "db", mock_db):
                mock_cursor = MagicMock()
                mock_db.cursor.return_value.__enter__.return_value = mock_cursor

                response = client.post(
                    "/ar/payments",
                    json={
                        "customer_id": 1,
                        "payment_date": "2026-09-15",
                        "amount_cents": 60000,  # More than invoices owe
                        "invoices": [(1, 50000)],  # Only owes 50000
                        "bank_account_id": 300,
                        "ar_account_id": 100,
                        "customer_credits_account_id": 400,
                        "fiscal_period_id": 1,
                    },
                    headers={"Authorization": "Bearer test_token"},
                )

                assert response.status_code == 201


# ============================================================================
# RECURRING TEMPLATE TESTS
# ============================================================================


def test_create_recurring_template(client, mock_db):
    """Create a new recurring template."""
    with patch.object(client.app.state, "db", mock_db):
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = (789,)  # template_id
        mock_db.cursor.return_value.__enter__.return_value = mock_cursor

        response = client.post(
            "/ar/recurring-templates",
            json={
                "customer_id": 1,
                "name": "Monthly SaaS",
                "description": "Monthly subscription",
                "amount_cents": 25000,
                "due_days_offset": 30,
                "line_account_id": 200,
                "active_from": "2026-09-01",
            },
            headers={"Authorization": "Bearer test_token"},
        )

        assert response.status_code == 201
        assert response.json()["template_id"] == 789


def test_update_template_status(client, mock_db):
    """Update template status (pause/resume/end)."""
    with patch("app.routes.ar.require_admin") as mock_admin:
        mock_admin.return_value = {"id": "admin_user"}

    with patch.object(client.app.state, "db", mock_db):
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = (789,)
        mock_db.cursor.return_value.__enter__.return_value = mock_cursor

        response = client.patch(
            "/ar/recurring-templates/789/status",
            json={"status": "paused"},
            headers={"Authorization": "Bearer admin_token"},
        )

        assert response.status_code == 200
        assert response.json()["new_status"] == "paused"


def test_update_template_price(client, mock_db):
    """Update template amount (cents)."""
    with patch("app.routes.ar.require_admin") as mock_admin:
        mock_admin.return_value = {"id": "admin_user"}

    with patch.object(client.app.state, "db", mock_db):
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = (789,)
        mock_db.cursor.return_value.__enter__.return_value = mock_cursor

        response = client.patch(
            "/ar/recurring-templates/789/price",
            json={"amount_cents": 30000},
            headers={"Authorization": "Bearer admin_token"},
        )

        assert response.status_code == 200
        assert response.json()["new_amount_cents"] == 30000


def test_preview_recurring_generation(client, mock_db):
    """Preview what invoice would be generated."""
    with patch.object(client.app.state, "db", mock_db):
        from ledger.recurring import GenerationResult, RecurringTemplate
        from ledger.invoices import InvoiceDraft, InvoiceLine

        mock_cursor = MagicMock()
        mock_template_row = (
            789, 1, "Monthly", "Description", 25000, 30, "active",
            date(2026, 9, 1), None, 200, date(2026, 9, 1)
        )
        mock_cursor.fetchone.return_value = mock_template_row
        mock_db.cursor.return_value.__enter__.return_value = mock_cursor

        with patch("app.routes.ar.generate_invoice_for_cycle") as mock_gen:
            draft = InvoiceDraft(
                customer_id=1,
                issue_date=date(2026, 9, 1),
                due_date=date(2026, 10, 1),
                total_amount_cents=25000,
                memo="Monthly",
                lines=(
                    InvoiceLine(
                        account_id=200,
                        description="Service",
                        quantity=1,
                        unit_price_cents=25000,
                        amount_cents=25000,
                    ),
                ),
            )
            mock_gen.return_value = GenerationResult(invoice_draft=draft, error=None)

            response = client.post(
                "/ar/recurring-templates/789/preview",
                json={"cycle_date": "2026-09-01"},
                headers={"Authorization": "Bearer test_token"},
            )

            assert response.status_code == 200
            preview = response.json()["would_generate"]
            assert preview["customer_id"] == 1
            assert preview["total_amount_cents"] == 25000


# ============================================================================
# REPORT TESTS
# ============================================================================


def test_ar_aging_report(client, mock_db):
    """Generate AR aging report (invoices grouped by days overdue)."""
    with patch.object(client.app.state, "db", mock_db):
        mock_cursor = MagicMock()
        today = date.today()
        mock_cursor.fetchall.return_value = [
            (1, 1001, "Acme Corp", today, today + timedelta(days=10), 50000, "posted", -10),  # current
            (2, 1002, "Beta Inc", today - timedelta(days=40), today - timedelta(days=10), 30000, "posted", 10),  # 30 days
            (3, 1003, "Gamma Ltd", today - timedelta(days=90), today - timedelta(days=60), 70000, "posted", 60),  # 90+ days
        ]
        mock_db.cursor.return_value.__enter__.return_value = mock_cursor

        response = client.get(
            "/ar/reports/aging",
            headers={"Authorization": "Bearer test_token"},
        )

        assert response.status_code == 200
        aging = response.json()["aging_buckets"]
        assert aging["current"]["count"] == 1
        assert aging["30_days"]["count"] == 1
        assert aging["90_plus_days"]["count"] == 1


def test_customer_statement(client, mock_db):
    """Generate customer statement (invoices and payments for date range)."""
    with patch.object(client.app.state, "db", mock_db):
        mock_cursor = MagicMock()
        mock_cursor.fetchone.side_effect = [
            (1, "Acme Corp", "12-3456789", "contact@acme.com", "active"),  # customer
        ]
        mock_cursor.fetchall.side_effect = [
            [(1, 1001, date(2026, 9, 1), date(2026, 10, 1), 50000, "posted")],  # invoices
            [(1, date(2026, 9, 15), 50000, "Check #1234", "recorded")],  # payments
        ]
        mock_db.cursor.return_value.__enter__.return_value = mock_cursor

        response = client.get(
            "/ar/reports/statements/1",
            params={"start_date": "2026-09-01", "end_date": "2026-09-30"},
            headers={"Authorization": "Bearer test_token"},
        )

        assert response.status_code == 200
        statement = response.json()
        assert statement["customer"]["name"] == "Acme Corp"
        assert len(statement["invoices"]) == 1
        assert len(statement["payments"]) == 1
        assert statement["summary"]["balance_cents"] == 0


def test_overdue_invoices_report(client, mock_db):
    """Generate overdue invoices report."""
    with patch.object(client.app.state, "db", mock_db):
        mock_cursor = MagicMock()
        today = date.today()
        mock_cursor.fetchall.return_value = [
            (1, 1001, "Acme Corp", today - timedelta(days=30), 50000, "posted", 30),
            (2, 1002, "Beta Inc", today - timedelta(days=60), 30000, "posted", 60),
        ]
        mock_db.cursor.return_value.__enter__.return_value = mock_cursor

        response = client.get(
            "/ar/reports/overdue",
            headers={"Authorization": "Bearer test_token"},
        )

        assert response.status_code == 200
        report = response.json()
        assert report["count"] == 2
        assert report["total_cents"] == 80000


# ============================================================================
# ERROR HANDLING
# ============================================================================


def test_fiscal_period_closed_error(client, mock_db):
    """Handle FiscalPeriodClosedError when posting invoice."""
    with patch("app.routes.ar.post_invoice") as mock_post:
            from app.adapters.ar_posting import FiscalPeriodClosedError

            mock_post.side_effect = FiscalPeriodClosedError("Period is closed")

            with patch.object(client.app.state, "db", mock_db):
                mock_cursor = MagicMock()
                mock_db.cursor.return_value.__enter__.return_value = mock_cursor

                response = client.post(
                    "/ar/invoices",
                    json={
                        "customer_id": 1,
                        "issue_date": "2026-09-01",
                        "due_date": "2026-10-01",
                        "fiscal_period_id": 1,
                        "ar_account_id": 100,
                        "lines": [],
                    },
                    headers={"Authorization": "Bearer test_token"},
                )

                assert response.status_code == 400


def test_customer_inactive_error(client, mock_db):
    """Handle CustomerInactiveError when posting invoice."""
    with patch("app.routes.ar.post_invoice") as mock_post:
            from app.adapters.ar_posting import CustomerInactiveError

            mock_post.side_effect = CustomerInactiveError("Customer is inactive")

            with patch.object(client.app.state, "db", mock_db):
                mock_cursor = MagicMock()
                mock_db.cursor.return_value.__enter__.return_value = mock_cursor

                response = client.post(
                    "/ar/invoices",
                    json={
                        "customer_id": 1,
                        "issue_date": "2026-09-01",
                        "due_date": "2026-10-01",
                        "fiscal_period_id": 1,
                        "ar_account_id": 100,
                        "lines": [],
                    },
                    headers={"Authorization": "Bearer test_token"},
                )

                assert response.status_code == 400


def test_account_not_found_error(client, mock_db):
    """Handle AccountNotFoundError when posting invoice."""
    with patch("app.routes.ar.post_invoice") as mock_post:
            from app.adapters.ar_posting import AccountNotFoundError

            mock_post.side_effect = AccountNotFoundError("Account 999 not found")

            with patch.object(client.app.state, "db", mock_db):
                mock_cursor = MagicMock()
                mock_db.cursor.return_value.__enter__.return_value = mock_cursor

                response = client.post(
                    "/ar/invoices",
                    json={
                        "customer_id": 1,
                        "issue_date": "2026-09-01",
                        "due_date": "2026-10-01",
                        "fiscal_period_id": 1,
                        "ar_account_id": 100,
                        "lines": [],
                    },
                    headers={"Authorization": "Bearer test_token"},
                )

                assert response.status_code == 400
