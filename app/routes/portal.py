"""Customer portal routes: invoice viewing, payment recording, account summary (Step 10).

Provides HTMX-based web interface for customers to:
  - View account dashboard with summary and recent activity
  - List and view invoice details
  - Record payments with automatic allocation
  - View payment history

All views are server-rendered with Jinja2 templates and HTMX for dynamic interactions.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.dependencies import current_user
from ledger.payments import allocate_payment

if TYPE_CHECKING:
    import psycopg

# Setup Jinja2 environment
from pathlib import Path

template_dir = Path(__file__).parent.parent / "templates"
jinja_env = Environment(
    loader=FileSystemLoader(str(template_dir)),
    autoescape=select_autoescape(["html", "xml"]),
    enable_async=False,
)

# Register custom filters
def format_date(d: date | None) -> str:
    """Format date as human-readable string."""
    if not d:
        return "-"
    return d.strftime("%b %d, %Y")

def format_currency(value: float) -> str:
    """Format value as USD currency."""
    return f"{value:,.2f}"

jinja_env.filters["format_date"] = format_date
jinja_env.filters["format_currency"] = format_currency

router = APIRouter(prefix="/portal", tags=["portal"])


# ============================================================================
# DASHBOARD
# ============================================================================


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(
    request: Request,
    user: dict = Depends(current_user),
) -> str:
    """Display account dashboard with summary and recent activity."""
    conn: psycopg.Connection = request.app.state.db

    try:
        # Get customer ID from session
        customer_id = user.get("customer_id")
        if not customer_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Not authenticated as customer",
            )

        with conn.cursor() as cur:
            # Get customer info
            cur.execute(
                "SELECT id, name, email FROM customers WHERE id = %s",
                (customer_id,),
            )
            customer_row = cur.fetchone()
            if not customer_row:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Customer not found",
                )

            # Get account summary
            cur.execute(
                """
                SELECT
                    COALESCE(SUM(CASE WHEN status IN ('posted', 'partial') THEN total_amount_cents ELSE 0 END), 0) as total_invoiced,
                    COALESCE(SUM(CASE WHEN status = 'paid' THEN total_amount_cents ELSE 0 END), 0) as total_paid
                FROM invoices
                WHERE customer_id = %s
                """
                , (customer_id,)
            )
            invoice_row = cur.fetchone()
            total_invoiced, total_paid = invoice_row or (0, 0)
            balance = total_invoiced - total_paid

            # Get credits
            cur.execute(
                "SELECT COALESCE(SUM(amount_cents), 0) FROM customer_credits WHERE customer_id = %s",
                (customer_id,),
            )
            credits_row = cur.fetchone()
            credits = credits_row[0] if credits_row else 0

            # Get recent invoices
            cur.execute(
                """
                SELECT id, invoice_number, issue_date, due_date, total_amount_cents, status,
                       CAST((CURRENT_DATE - due_date) AS INTEGER) as days_overdue
                FROM invoices
                WHERE customer_id = %s
                ORDER BY issue_date DESC
                LIMIT 5
                """,
                (customer_id,),
            )
            invoices = [
                {
                    "id": row[0],
                    "invoice_number": row[1],
                    "issue_date": row[2],
                    "due_date": row[3],
                    "amount_cents": row[4],
                    "status": row[5],
                    "days_overdue": row[6],
                }
                for row in cur.fetchall()
            ]

            # Get recent payments
            cur.execute(
                """
                SELECT id, payment_date, amount_cents, memo
                FROM payments
                WHERE customer_id = %s
                ORDER BY payment_date DESC
                LIMIT 5
                """,
                (customer_id,),
            )
            payments = [
                {
                    "id": row[0],
                    "payment_date": row[1],
                    "amount_cents": row[2],
                    "memo": row[3],
                }
                for row in cur.fetchall()
            ]

        # Render template
        template = jinja_env.get_template("ar/dashboard.html")
        return template.render(
            active_page="dashboard",
            as_of_date=date.today(),
            summary={
                "total_invoiced_cents": total_invoiced,
                "total_paid_cents": total_paid,
                "balance_cents": balance,
                "credits_cents": credits,
            },
            recent_invoices=invoices,
            recent_payments=payments,
        )

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load dashboard: {exc}",
        )


# ============================================================================
# INVOICES
# ============================================================================


@router.get("/invoices", response_class=HTMLResponse)
def list_invoices(
    request: Request,
    status_filter: str | None = None,
    user: dict = Depends(current_user),
) -> str:
    """List all invoices for the customer."""
    conn: psycopg.Connection = request.app.state.db

    try:
        customer_id = user.get("customer_id")
        if not customer_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Not authenticated as customer",
            )

        with conn.cursor() as cur:
            query = (
                "SELECT id, invoice_number, issue_date, due_date, total_amount_cents, status, "
                "CAST((CURRENT_DATE - due_date) AS INTEGER) as days_overdue "
                "FROM invoices WHERE customer_id = %s"
            )
            params = [customer_id]

            if status_filter:
                query += " AND status = %s"
                params.append(status_filter)

            query += " ORDER BY issue_date DESC"

            cur.execute(query, params)
            invoices = [
                {
                    "id": row[0],
                    "invoice_number": row[1],
                    "issue_date": row[2],
                    "due_date": row[3],
                    "amount_cents": row[4],
                    "status": row[5],
                    "days_overdue": row[6],
                }
                for row in cur.fetchall()
            ]

        template = jinja_env.get_template("ar/invoices.html")
        return template.render(active_page="invoices", invoices=invoices)

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load invoices: {exc}",
        )


@router.get("/invoices/{invoice_id}", response_class=HTMLResponse)
def get_invoice_detail(
    invoice_id: int,
    request: Request,
    user: dict = Depends(current_user),
) -> str:
    """Display invoice detail with line items."""
    conn: psycopg.Connection = request.app.state.db

    try:
        customer_id = user.get("customer_id")
        if not customer_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Not authenticated as customer",
            )

        with conn.cursor() as cur:
            # Get invoice
            cur.execute(
                "SELECT i.id, i.invoice_number, i.issue_date, i.due_date, i.total_amount_cents, "
                "i.status, i.memo, c.name, c.email "
                "FROM invoices i JOIN customers c ON i.customer_id = c.id "
                "WHERE i.id = %s AND i.customer_id = %s",
                (invoice_id, customer_id),
            )
            invoice_row = cur.fetchone()
            if not invoice_row:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Invoice not found",
                )

            invoice = {
                "id": invoice_row[0],
                "invoice_number": invoice_row[1],
                "issue_date": invoice_row[2],
                "due_date": invoice_row[3],
                "amount_cents": invoice_row[4],
                "status": invoice_row[5],
                "memo": invoice_row[6],
                "customer_name": invoice_row[7],
                "customer_email": invoice_row[8],
            }

            # Get line items
            cur.execute(
                "SELECT description, quantity, unit_price_cents, amount_cents "
                "FROM invoice_lines WHERE invoice_id = %s",
                (invoice_id,),
            )
            lines = [
                {
                    "description": row[0],
                    "quantity": row[1],
                    "unit_price_cents": row[2],
                    "amount_cents": row[3],
                }
                for row in cur.fetchall()
            ]

        template = jinja_env.get_template("ar/invoice_detail.html")
        return template.render(
            active_page="invoices",
            invoice=invoice,
            invoice_lines=lines,
            company_name="Outset Solutions LLC",  # TODO: Make configurable
        )

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load invoice: {exc}",
        )


# ============================================================================
# PAYMENTS
# ============================================================================


@router.get("/payments", response_class=HTMLResponse)
def list_payments(
    request: Request,
    user: dict = Depends(current_user),
) -> str:
    """List payment history."""
    conn: psycopg.Connection = request.app.state.db

    try:
        customer_id = user.get("customer_id")
        if not customer_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Not authenticated as customer",
            )

        with conn.cursor() as cur:
            # Get payments
            cur.execute(
                "SELECT id, payment_date, amount_cents, memo FROM payments "
                "WHERE customer_id = %s ORDER BY payment_date DESC",
                (customer_id,),
            )
            payments = [
                {
                    "id": row[0],
                    "payment_date": row[1],
                    "amount_cents": row[2],
                    "memo": row[3],
                }
                for row in cur.fetchall()
            ]

            # Get allocations for each payment
            for payment in payments:
                cur.execute(
                    "SELECT i.id, i.invoice_number FROM payment_allocations pa "
                    "JOIN invoices i ON pa.invoice_id = i.id "
                    "WHERE pa.payment_id = %s",
                    (payment["id"],),
                )
                payment["allocations"] = [
                    {"invoice_id": row[0], "invoice_number": row[1]}
                    for row in cur.fetchall()
                ]

        template = jinja_env.get_template("ar/payments.html")
        return template.render(active_page="payments", payments=payments)

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load payments: {exc}",
        )


@router.get("/payments/new", response_class=HTMLResponse)
def payment_form(
    request: Request,
    invoice_id: int | None = None,
    user: dict = Depends(current_user),
) -> str:
    """Display payment recording form."""
    conn: psycopg.Connection = request.app.state.db

    try:
        customer_id = user.get("customer_id")
        if not customer_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Not authenticated as customer",
            )

        with conn.cursor() as cur:
            # Get outstanding invoices
            cur.execute(
                "SELECT id, invoice_number, issue_date, due_date, total_amount_cents, status "
                "FROM invoices WHERE customer_id = %s AND status IN ('posted', 'partial') "
                "ORDER BY due_date ASC",
                (customer_id,),
            )
            invoices = [
                {
                    "id": row[0],
                    "invoice_number": row[1],
                    "issue_date": row[2],
                    "due_date": row[3],
                    "amount_cents": row[4],
                    "status": row[5],
                }
                for row in cur.fetchall()
            ]

        template = jinja_env.get_template("ar/payment_form.html")
        return template.render(
            active_page="payments",
            outstanding_invoices=invoices,
            today=date.today(),
        )

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load payment form: {exc}",
        )


@router.post("/payments", response_class=HTMLResponse)
async def record_payment(
    request: Request,
    user: dict = Depends(current_user),
) -> str:
    """Record a payment and allocate across invoices."""
    conn: psycopg.Connection = request.app.state.db

    try:
        customer_id = user.get("customer_id")
        if not customer_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Not authenticated as customer",
            )

        # Parse form data
        form_data = await request.form()  # pragma: no cover
        payment_date = date.fromisoformat(form_data.get("payment_date", ""))
        amount_cents = int(float(form_data.get("amount_cents", 0)) * 100)
        memo = form_data.get("memo", "").strip() or None

        if amount_cents <= 0:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Payment amount must be greater than 0",
            )

        # Get invoice allocations from form
        invoices = []
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, total_amount_cents FROM invoices "
                "WHERE customer_id = %s AND status IN ('posted', 'partial') "
                "ORDER BY due_date ASC",
                (customer_id,),
            )
            for row in cur.fetchall():
                invoice_id, total_cents = row
                allocate_key = f"allocate_{invoice_id}"
                if allocate_key in form_data:
                    allocate_amount = int(float(form_data[allocate_key]) * 100)
                    if allocate_amount > 0:
                        invoices.append((invoice_id, allocate_amount))

        if not invoices:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Must allocate payment to at least one invoice",
            )

        # Allocate payment
        allocations, overpayment = allocate_payment(amount_cents, invoices)

        # Record payment (simplified - would call post_payment in production)
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO payments (customer_id, payment_date, amount_cents, memo) "
                "VALUES (%s, %s, %s, %s) RETURNING id",
                (customer_id, payment_date, amount_cents, memo),
            )
            payment_id = cur.fetchone()[0]

            # Record allocations
            for alloc in allocations:
                cur.execute(
                    "INSERT INTO payment_allocations (payment_id, invoice_id, amount_cents) "
                    "VALUES (%s, %s, %s)",
                    (payment_id, alloc.invoice_id, alloc.amount_cents),
                )

        conn.commit()

        # Redirect to payment history
        template = jinja_env.get_template("ar/payments.html")
        return template.render(
            active_page="payments",
            payments=[],
            message="Payment recorded successfully!",
        )

    except HTTPException:
        raise
    except Exception as exc:
        conn.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to record payment: {exc}",
        )
