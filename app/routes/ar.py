"""AR routes: customers, invoices, payments, recurring templates (Step 9).

Routes for Accounts Receivable operations:
  - Customer CRUD
  - Invoice creation, posting, PDF rendering
  - Payment allocation and posting
  - Recurring template management
  - AR aging reports
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.adapters.ar_posting import (
    ARPostingError,
    AccountNotFoundError,
    CustomerInactiveError,
    FiscalPeriodClosedError,
    generate_and_post_recurring,
    post_invoice,
    post_payment,
)
from app.dependencies import current_user, require_admin
from ledger.customers import (
    CustomerStatus,
    is_billable,
    mark_active,
    mark_inactive,
    new_customer,
)
from ledger.invoices import (
    InvoiceDraft,
    add_line_to_draft,
    mark_paid,
    mark_void,
    new_invoice_draft,
)
from ledger.payments import Payment, PaymentAllocationLine, allocate_payment

if TYPE_CHECKING:
    import psycopg

router = APIRouter(prefix="/ar", tags=["ar"])


# ============================================================================
# CUSTOMERS
# ============================================================================


@router.post("/customers", status_code=status.HTTP_201_CREATED)
def create_customer(
    request: Request,
    body: dict,
    user: dict = Depends(current_user),
) -> dict:
    """Create a new customer."""
    name = body.get("name", "").strip()
    tax_id = body.get("tax_id", "").strip() or None
    email = body.get("email", "").strip() or None
    address = body.get("address", "").strip() or None
    notes = body.get("notes", "").strip() or None

    if not name:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Customer name is required",
        )

    try:
        customer = new_customer(
            name=name,
            tax_id=tax_id,
            email=email,
            address=address,
            notes=notes,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )

    conn: psycopg.Connection = request.app.state.db
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO customers (name, tax_id, email, address, notes, status) "
                "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                (name, tax_id, email, address, notes, customer.status),
            )
            customer_id = cur.fetchone()[0]
        conn.commit()
    except Exception as exc:
        conn.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create customer: {exc}",
        )

    return {
        "status": "created",
        "customer_id": customer_id,
        "name": name,
    }


@router.get("/customers")
def list_customers(
    request: Request,
    user: dict = Depends(current_user),
) -> dict:
    """List all customers."""
    conn: psycopg.Connection = request.app.state.db
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, name, tax_id, email, status FROM customers ORDER BY created_at DESC"
            )
            rows = cur.fetchall()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list customers: {exc}",
        )

    return {
        "customers": [
            {
                "id": row[0],
                "name": row[1],
                "tax_id": row[2],
                "email": row[3],
                "status": row[4],
            }
            for row in rows
        ]
    }


@router.get("/customers/{customer_id}")
def get_customer(
    customer_id: int,
    request: Request,
    user: dict = Depends(current_user),
) -> dict:
    """Get customer detail."""
    conn: psycopg.Connection = request.app.state.db
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, name, tax_id, email, address, notes, status, created_at "
                "FROM customers WHERE id = %s",
                (customer_id,),
            )
            row = cur.fetchone()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load customer: {exc}",
        )

    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Customer {customer_id} not found",
        )

    return {
        "customer": {
            "id": row[0],
            "name": row[1],
            "tax_id": row[2],
            "email": row[3],
            "address": row[4],
            "notes": row[5],
            "status": row[6],
            "created_at": row[7].isoformat() if row[7] else None,
        }
    }


@router.patch("/customers/{customer_id}/status")
def update_customer_status(
    customer_id: int,
    request: Request,
    body: dict,
    user: dict = Depends(require_admin),
) -> dict:
    """Update customer status (active/inactive/archived)."""
    new_status = body.get("status", "").strip().lower()

    if new_status not in ("active", "inactive", "archived"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Status must be active, inactive, or archived",
        )

    conn: psycopg.Connection = request.app.state.db
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE customers SET status = %s WHERE id = %s",
                (new_status, customer_id),
            )
            if cur.rowcount == 0:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Customer {customer_id} not found",
                )
        conn.commit()
    except HTTPException:
        raise
    except Exception as exc:
        conn.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update customer status: {exc}",
        )

    return {
        "status": "updated",
        "customer_id": customer_id,
        "new_status": new_status,
    }


# ============================================================================
# INVOICES
# ============================================================================


@router.post("/invoices", status_code=status.HTTP_201_CREATED)
def create_and_post_invoice(
    request: Request,
    body: dict,
    user: dict = Depends(current_user),
) -> dict:
    """Create and immediately post an invoice (CK-5).

    Request body:
      {
        "customer_id": 1,
        "issue_date": "2026-09-01",
        "due_date": "2026-10-01",
        "memo": "Invoice for services",
        "lines": [
          {
            "account_id": 100,
            "description": "Service A",
            "quantity": 1,
            "unit_price_cents": 4900
          }
        ],
        "fiscal_period_id": 1,
        "ar_account_id": 1
      }
    """
    customer_id = body.get("customer_id")
    issue_date_str = body.get("issue_date")
    due_date_str = body.get("due_date")
    memo = body.get("memo")
    lines = body.get("lines", [])
    fiscal_period_id = body.get("fiscal_period_id")
    ar_account_id = body.get("ar_account_id")

    # Validate required fields
    if not all([customer_id, issue_date_str, due_date_str, fiscal_period_id, ar_account_id]):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Missing required fields: customer_id, issue_date, due_date, fiscal_period_id, ar_account_id",
        )

    if not lines:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invoice must have at least one line item",
        )

    # Parse dates
    try:
        issue_date = date.fromisoformat(issue_date_str)
        due_date = date.fromisoformat(due_date_str)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid date format: {exc}",
        )

    # Build invoice draft
    try:
        draft = new_invoice_draft(
            customer_id=customer_id,
            issue_date=issue_date,
            due_date=due_date,
            memo=memo,
        )

        for line in lines:
            draft = add_line_to_draft(
                draft,
                account_id=line["account_id"],
                description=line.get("description", ""),
                quantity=line.get("quantity", 1),
                unit_price_cents=line.get("unit_price_cents", 0),
            )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )

    # Post invoice
    conn: psycopg.Connection = request.app.state.db
    try:
        invoice_id = post_invoice(
            conn,
            draft,
            ar_account_id=ar_account_id,
            fiscal_period_id=fiscal_period_id,
        )
    except FiscalPeriodClosedError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )
    except CustomerInactiveError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )
    except AccountNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )
    except ARPostingError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        )

    return {
        "status": "posted",
        "invoice_id": invoice_id,
        "customer_id": customer_id,
        "total_cents": draft.total_amount_cents,
    }


@router.get("/invoices")
def list_invoices(
    request: Request,
    status_filter: str | None = None,
    customer_id: int | None = None,
    user: dict = Depends(current_user),
) -> dict:
    """List invoices with optional filters."""
    conn: psycopg.Connection = request.app.state.db
    query = "SELECT id, invoice_number, customer_id, issue_date, due_date, total_amount_cents, status FROM invoices"
    params = []

    if status_filter:
        query += " WHERE status = %s"
        params.append(status_filter)

    if customer_id:
        if params:
            query += " AND customer_id = %s"
        else:
            query += " WHERE customer_id = %s"
        params.append(customer_id)

    query += " ORDER BY issue_date DESC"

    try:
        with conn.cursor() as cur:
            cur.execute(query, params)
            rows = cur.fetchall()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list invoices: {exc}",
        )

    return {
        "invoices": [
            {
                "id": row[0],
                "invoice_number": row[1],
                "customer_id": row[2],
                "issue_date": row[3].isoformat(),
                "due_date": row[4].isoformat(),
                "total_cents": row[5],
                "status": row[6],
            }
            for row in rows
        ]
    }


@router.get("/invoices/{invoice_id}")
def get_invoice(
    invoice_id: int,
    request: Request,
    user: dict = Depends(current_user),
) -> dict:
    """Get invoice detail with line items and tax breakdown."""
    conn: psycopg.Connection = request.app.state.db
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, invoice_number, customer_id, issue_date, due_date, memo, "
                "total_amount_cents, status FROM invoices WHERE id = %s",
                (invoice_id,),
            )
            row = cur.fetchone()

            if not row:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Invoice {invoice_id} not found",
                )

            cur.execute(
                "SELECT id, account_id, description, quantity, unit_price_cents, amount_cents "
                "FROM invoice_lines WHERE invoice_id = %s ORDER BY id",
                (invoice_id,),
            )
            line_rows = cur.fetchall()

            # Fetch tax details for each line
            cur.execute(
                """
                SELECT ilt.invoice_line_id, tj.code, tj.name, tr.rate_percent,
                       ilt.taxable_amount_cents, ilt.tax_amount_cents
                FROM invoice_line_taxes ilt
                JOIN tax_jurisdictions tj ON ilt.jurisdiction_id = tj.id
                JOIN tax_rates tr ON ilt.tax_rate_id = tr.id
                WHERE ilt.invoice_id = %s
                ORDER BY ilt.invoice_line_id, tj.code
                """,
                (invoice_id,),
            )
            tax_rows = cur.fetchall()

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load invoice: {exc}",
        )

    # Group taxes by line ID
    taxes_by_line = {}
    total_tax_cents = 0
    for tax_row in tax_rows:
        line_id = tax_row[0]
        if line_id not in taxes_by_line:
            taxes_by_line[line_id] = []
        taxes_by_line[line_id].append({
            "jurisdiction": tax_row[1],
            "jurisdiction_name": tax_row[2],
            "rate_percent": float(tax_row[3]),
            "taxable_amount_cents": tax_row[4],
            "tax_amount_cents": tax_row[5],
        })
        total_tax_cents += tax_row[5]

    # Build line items with tax details
    lines = []
    for lr in line_rows:
        line_id = lr[0]
        line_taxes = taxes_by_line.get(line_id, [])
        line_tax_total = sum(t["tax_amount_cents"] for t in line_taxes)

        lines.append({
            "id": line_id,
            "account_id": lr[1],
            "description": lr[2],
            "quantity": lr[3],
            "unit_price_cents": lr[4],
            "amount_cents": lr[5],
            "taxes": line_taxes,
            "tax_total_cents": line_tax_total,
            "total_with_tax_cents": lr[5] + line_tax_total,
        })

    return {
        "invoice": {
            "id": row[0],
            "invoice_number": row[1],
            "customer_id": row[2],
            "issue_date": row[3].isoformat(),
            "due_date": row[4].isoformat(),
            "memo": row[5],
            "subtotal_cents": row[6] - total_tax_cents,
            "total_tax_cents": total_tax_cents,
            "total_cents": row[6],
            "status": row[7],
            "lines": lines,
        }
    }


# ============================================================================
# PAYMENTS
# ============================================================================


@router.post("/payments", status_code=status.HTTP_201_CREATED)
def record_payment(
    request: Request,
    body: dict,
    user: dict = Depends(current_user),
) -> dict:
    """Record and post a payment with allocation.

    Request body:
      {
        "customer_id": 1,
        "payment_date": "2026-09-15",
        "amount_cents": 6000,
        "memo": "Check #123",
        "invoices": [
          {"invoice_id": 1, "amount_due_cents": 4900}
        ],
        "bank_account_id": 2,
        "ar_account_id": 1,
        "customer_credits_account_id": 50,
        "fiscal_period_id": 1
      }
    """
    customer_id = body.get("customer_id")
    payment_date_str = body.get("payment_date")
    amount_cents = body.get("amount_cents")
    memo = body.get("memo")
    invoices = body.get("invoices", [])
    bank_account_id = body.get("bank_account_id")
    ar_account_id = body.get("ar_account_id")
    customer_credits_account_id = body.get("customer_credits_account_id")
    fiscal_period_id = body.get("fiscal_period_id")

    # Validate required fields
    if not all([customer_id, payment_date_str, amount_cents, bank_account_id, ar_account_id, fiscal_period_id]):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Missing required fields",
        )

    # Parse date
    try:
        payment_date = date.fromisoformat(payment_date_str)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid date format: {exc}",
        )

    # Allocate payment across invoices
    invoice_list = [(inv["invoice_id"], inv["amount_due_cents"]) for inv in invoices]
    try:
        allocations, overpayment_cents = allocate_payment(amount_cents, invoice_list)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )

    # Create payment object
    payment = Payment(
        id=None,
        customer_id=customer_id,
        payment_date=payment_date,
        amount_cents=amount_cents,
        memo=memo,
        bank_line_id=None,
        allocations=tuple(
            PaymentAllocationLine(invoice_id=alloc[0], amount_cents=alloc[1])
            for alloc in allocations
        ),
        overpayment_cents=overpayment_cents,
    )

    # Post payment with serializable retry
    conn: psycopg.Connection = request.app.state.db
    try:
        payment_id = post_payment(
            conn,
            payment,
            bank_account_id=bank_account_id,
            ar_account_id=ar_account_id,
            customer_credits_account_id=customer_credits_account_id,
            fiscal_period_id=fiscal_period_id,
        )
    except FiscalPeriodClosedError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )
    except AccountNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )
    except ARPostingError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        )

    return {
        "status": "posted",
        "payment_id": payment_id,
        "customer_id": customer_id,
        "amount_cents": amount_cents,
        "allocations": len(allocations),
        "overpayment_cents": overpayment_cents,
    }


@router.get("/payments")
def list_payments(
    request: Request,
    customer_id: int | None = None,
    user: dict = Depends(current_user),
) -> dict:
    """List payments with optional filters."""
    conn: psycopg.Connection = request.app.state.db
    query = "SELECT id, customer_id, payment_date, amount_cents, memo FROM payments"
    params = []

    if customer_id:
        query += " WHERE customer_id = %s"
        params.append(customer_id)

    query += " ORDER BY payment_date DESC"

    try:
        with conn.cursor() as cur:
            cur.execute(query, params)
            rows = cur.fetchall()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list payments: {exc}",
        )

    return {
        "payments": [
            {
                "id": row[0],
                "customer_id": row[1],
                "payment_date": row[2].isoformat(),
                "amount_cents": row[3],
                "memo": row[4],
            }
            for row in rows
        ]
    }


# ============================================================================
# RECURRING TEMPLATES
# ============================================================================


@router.post("/recurring-templates", status_code=status.HTTP_201_CREATED)
def create_recurring_template(
    request: Request,
    body: dict,
    user: dict = Depends(require_admin),
) -> dict:
    """Create a recurring invoice template."""
    customer_id = body.get("customer_id")
    name = body.get("name", "").strip()
    amount_cents = body.get("amount_cents")
    line_account_id = body.get("line_account_id")
    active_from_str = body.get("active_from")

    if not all([customer_id, name, amount_cents, line_account_id, active_from_str]):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Missing required fields",
        )

    try:
        active_from = date.fromisoformat(active_from_str)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid date format: {exc}",
        )

    conn: psycopg.Connection = request.app.state.db
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO recurring_templates "
                "(customer_id, name, description, amount_cents, due_days_offset, "
                "status, active_from, active_until, line_account_id) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
                (
                    customer_id,
                    name,
                    body.get("description"),
                    amount_cents,
                    body.get("due_days_offset", 30),
                    "active",
                    active_from,
                    body.get("active_until"),
                    line_account_id,
                ),
            )
            template_id = cur.fetchone()[0]
        conn.commit()
    except Exception as exc:
        conn.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create template: {exc}",
        )

    return {
        "status": "created",
        "template_id": template_id,
        "name": name,
    }


@router.get("/recurring-templates")
def list_recurring_templates(
    request: Request,
    status_filter: str | None = None,
    user: dict = Depends(current_user),
) -> dict:
    """List recurring templates."""
    conn: psycopg.Connection = request.app.state.db
    query = "SELECT id, customer_id, name, amount_cents, status, active_from FROM recurring_templates"
    params = []

    if status_filter:
        query += " WHERE status = %s"
        params.append(status_filter)

    query += " ORDER BY created_at DESC"

    try:
        with conn.cursor() as cur:
            cur.execute(query, params)
            rows = cur.fetchall()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list templates: {exc}",
        )

    return {
        "templates": [
            {
                "id": row[0],
                "customer_id": row[1],
                "name": row[2],
                "amount_cents": row[3],
                "status": row[4],
                "active_from": row[5].isoformat() if row[5] else None,
            }
            for row in rows
        ]
    }


@router.patch("/recurring-templates/{template_id}/status")
def update_recurring_template_status(
    template_id: int,
    request: Request,
    body: dict,
    user: dict = Depends(require_admin),
) -> dict:
    """Update recurring template status (active/paused/ended)."""
    new_status = body.get("status", "").strip()
    valid_statuses = {"active", "paused", "ended"}

    if new_status not in valid_statuses:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Status must be one of {valid_statuses}",
        )

    conn: psycopg.Connection = request.app.state.db
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE recurring_templates SET status = %s WHERE id = %s RETURNING id",
                (new_status, template_id),
            )
            result = cur.fetchone()
            if not result:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Template {template_id} not found",
                )
        conn.commit()
    except HTTPException:
        raise
    except Exception as exc:
        conn.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update template status: {exc}",
        )

    return {"status": "updated", "template_id": template_id, "new_status": new_status}


@router.patch("/recurring-templates/{template_id}/price")
def update_recurring_template_price(
    template_id: int,
    request: Request,
    body: dict,
    user: dict = Depends(require_admin),
) -> dict:
    """Update recurring template amount (cents)."""
    amount_cents = body.get("amount_cents")

    if not isinstance(amount_cents, int) or amount_cents <= 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="amount_cents must be a positive integer",
        )

    conn: psycopg.Connection = request.app.state.db
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE recurring_templates SET amount_cents = %s WHERE id = %s RETURNING id",
                (amount_cents, template_id),
            )
            result = cur.fetchone()
            if not result:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Template {template_id} not found",
                )
        conn.commit()
    except HTTPException:
        raise
    except Exception as exc:
        conn.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update template price: {exc}",
        )

    return {
        "status": "updated",
        "template_id": template_id,
        "new_amount_cents": amount_cents,
    }


@router.post("/recurring-templates/{template_id}/preview")
def preview_recurring_generation(
    template_id: int,
    request: Request,
    body: dict,
    user: dict = Depends(current_user),
) -> dict:
    """Preview what invoice would be generated for a given cycle date."""
    cycle_date_str = body.get("cycle_date")
    if not cycle_date_str:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="cycle_date is required (ISO format: YYYY-MM-DD)",
        )

    try:
        cycle_date = date.fromisoformat(cycle_date_str)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid date format: {exc}",
        )

    from ledger.recurring import generate_invoice_for_cycle, RecurringTemplate

    conn: psycopg.Connection = request.app.state.db
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, customer_id, name, description, amount_cents, due_days_offset, "
                "status, active_from, active_until, line_account_id, created_at "
                "FROM recurring_templates WHERE id = %s",
                (template_id,),
            )
            row = cur.fetchone()

        if not row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Template {template_id} not found",
            )

        template = RecurringTemplate(
            id=row[0],
            customer_id=row[1],
            name=row[2],
            description=row[3],
            amount_cents=row[4],
            due_days_offset=row[5],
            status=row[6],
            active_from=row[7],
            active_until=row[8],
            line_account_id=row[9],
            created_at=row[10],
        )

        # Generate draft
        result = generate_invoice_for_cycle(template, cycle_date)
        if result.error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=result.error,
            )

        draft = result.invoice_draft
        return {
            "cycle_date": cycle_date.isoformat(),
            "would_generate": {
                "customer_id": draft.customer_id,
                "issue_date": draft.issue_date.isoformat(),
                "due_date": draft.due_date.isoformat(),
                "total_amount_cents": draft.total_amount_cents,
                "memo": draft.memo,
                "lines": [
                    {
                        "account_id": line.account_id,
                        "description": line.description,
                        "quantity": line.quantity,
                        "unit_price_cents": line.unit_price_cents,
                        "amount_cents": line.amount_cents,
                    }
                    for line in draft.lines
                ],
            },
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to preview generation: {exc}",
        )


# ============================================================================
# INVOICE STATUS UPDATES
# ============================================================================


@router.patch("/invoices/{invoice_id}/status")
def update_invoice_status(
    invoice_id: int,
    request: Request,
    body: dict,
    user: dict = Depends(require_admin),
) -> dict:
    """Update invoice status (mark paid or void)."""
    new_status = body.get("status", "").strip()
    valid_statuses = {"posted", "paid", "void"}

    if new_status not in valid_statuses:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Status must be one of {valid_statuses}",
        )

    conn: psycopg.Connection = request.app.state.db
    try:
        with conn.cursor() as cur:
            # Verify invoice exists
            cur.execute("SELECT status FROM invoices WHERE id = %s", (invoice_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Invoice {invoice_id} not found",
                )

            old_status = row[0]

            # Update status
            cur.execute(
                "UPDATE invoices SET status = %s WHERE id = %s",
                (new_status, invoice_id),
            )

        conn.commit()
    except HTTPException:
        raise
    except Exception as exc:
        conn.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update invoice status: {exc}",
        )

    return {
        "status": "updated",
        "invoice_id": invoice_id,
        "old_status": old_status,
        "new_status": new_status,
    }


# ============================================================================
# REPORTS
# ============================================================================


@router.get("/reports/aging")
def report_ar_aging(
    request: Request,
    user: dict = Depends(current_user),
) -> dict:
    """AR aging report: invoices grouped by days overdue."""
    conn: psycopg.Connection = request.app.state.db
    try:
        with conn.cursor() as cur:
            # Fetch all open invoices with customer names and days overdue
            cur.execute(
                """
                SELECT
                    i.id,
                    i.invoice_number,
                    c.name as customer_name,
                    i.issue_date,
                    i.due_date,
                    i.total_amount_cents,
                    i.status,
                    CAST((CURRENT_DATE - i.due_date) AS INTEGER) as days_overdue
                FROM invoices i
                JOIN customers c ON i.customer_id = c.id
                WHERE i.status IN ('posted', 'partial')
                ORDER BY i.due_date ASC
                """
            )
            rows = cur.fetchall()

        # Group by aging buckets
        current = []
        thirty_days = []
        sixty_days = []
        ninety_plus = []

        for row in rows:
            inv_id, inv_num, cust_name, issue_date, due_date, amount_cents, inv_status, days_over = row
            entry = {
                "invoice_id": inv_id,
                "invoice_number": inv_num,
                "customer_name": cust_name,
                "issue_date": issue_date.isoformat() if issue_date else None,
                "due_date": due_date.isoformat() if due_date else None,
                "amount_cents": amount_cents,
                "status": inv_status,
                "days_overdue": days_over or 0,
            }

            if days_over is None or days_over <= 0:
                current.append(entry)
            elif days_over <= 30:
                thirty_days.append(entry)
            elif days_over <= 60:
                sixty_days.append(entry)
            else:
                ninety_plus.append(entry)

        return {
            "as_of_date": date.today().isoformat(),
            "aging_buckets": {
                "current": {
                    "count": len(current),
                    "total_cents": sum(e["amount_cents"] for e in current),
                    "invoices": current,
                },
                "30_days": {
                    "count": len(thirty_days),
                    "total_cents": sum(e["amount_cents"] for e in thirty_days),
                    "invoices": thirty_days,
                },
                "60_days": {
                    "count": len(sixty_days),
                    "total_cents": sum(e["amount_cents"] for e in sixty_days),
                    "invoices": sixty_days,
                },
                "90_plus_days": {
                    "count": len(ninety_plus),
                    "total_cents": sum(e["amount_cents"] for e in ninety_plus),
                    "invoices": ninety_plus,
                },
            },
        }

    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate aging report: {exc}",
        )


@router.get("/reports/statements/{customer_id}")
def report_customer_statement(
    customer_id: int,
    request: Request,
    start_date: str | None = None,
    end_date: str | None = None,
    user: dict = Depends(current_user),
) -> dict:
    """Customer statement: all invoices and payments for a date range."""
    # Parse dates
    try:
        start = date.fromisoformat(start_date) if start_date else None
        end = date.fromisoformat(end_date) if end_date else date.today()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid date format: {exc}",
        )

    conn: psycopg.Connection = request.app.state.db
    try:
        with conn.cursor() as cur:
            # Fetch customer
            cur.execute(
                "SELECT id, name, tax_id, email, status FROM customers WHERE id = %s",
                (customer_id,),
            )
            customer_row = cur.fetchone()
            if not customer_row:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Customer {customer_id} not found",
                )

            cust_id, cust_name, cust_tax_id, cust_email, cust_status = customer_row

            # Fetch invoices
            query = (
                "SELECT id, invoice_number, issue_date, due_date, total_amount_cents, status "
                "FROM invoices WHERE customer_id = %s"
            )
            params = [customer_id]
            if start:
                query += " AND issue_date >= %s"
                params.append(start)
            if end:
                query += " AND issue_date <= %s"
                params.append(end)
            query += " ORDER BY issue_date DESC"

            cur.execute(query, params)
            invoice_rows = cur.fetchall()

            # Fetch payments
            query = (
                "SELECT id, payment_date, amount_cents, memo, status "
                "FROM payments WHERE customer_id = %s"
            )
            params = [customer_id]
            if start:
                query += " AND payment_date >= %s"
                params.append(start)
            if end:
                query += " AND payment_date <= %s"
                params.append(end)
            query += " ORDER BY payment_date DESC"

            cur.execute(query, params)
            payment_rows = cur.fetchall()

        # Assemble response
        invoices = [
            {
                "id": row[0],
                "invoice_number": row[1],
                "issue_date": row[2].isoformat() if row[2] else None,
                "due_date": row[3].isoformat() if row[3] else None,
                "amount_cents": row[4],
                "status": row[5],
            }
            for row in invoice_rows
        ]

        payments = [
            {
                "id": row[0],
                "payment_date": row[1].isoformat() if row[1] else None,
                "amount_cents": row[2],
                "memo": row[3],
                "status": row[4],
            }
            for row in payment_rows
        ]

        total_invoiced = sum(inv["amount_cents"] for inv in invoices)
        total_paid = sum(pmt["amount_cents"] for pmt in payments)

        return {
            "customer": {
                "id": cust_id,
                "name": cust_name,
                "tax_id": cust_tax_id,
                "email": cust_email,
                "status": cust_status,
            },
            "date_range": {
                "start": start.isoformat() if start else None,
                "end": end.isoformat() if end else None,
            },
            "summary": {
                "total_invoiced_cents": total_invoiced,
                "total_paid_cents": total_paid,
                "balance_cents": total_invoiced - total_paid,
            },
            "invoices": invoices,
            "payments": payments,
        }

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate statement: {exc}",
        )


@router.get("/reports/overdue")
def report_overdue_invoices(
    request: Request,
    days_overdue: int = 0,
    user: dict = Depends(current_user),
) -> dict:
    """Overdue invoices report: invoices past due date."""
    conn: psycopg.Connection = request.app.state.db
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    i.id,
                    i.invoice_number,
                    c.name as customer_name,
                    i.due_date,
                    i.total_amount_cents,
                    i.status,
                    CAST((CURRENT_DATE - i.due_date) AS INTEGER) as days_overdue
                FROM invoices i
                JOIN customers c ON i.customer_id = c.id
                WHERE i.status IN ('posted', 'partial')
                  AND i.due_date < CURRENT_DATE
                ORDER BY i.due_date ASC
                """
            )
            rows = cur.fetchall()

        overdue_invoices = [
            {
                "invoice_id": row[0],
                "invoice_number": row[1],
                "customer_name": row[2],
                "due_date": row[3].isoformat() if row[3] else None,
                "amount_cents": row[4],
                "status": row[5],
                "days_overdue": row[6] or 0,
            }
            for row in rows
        ]

        total_overdue_cents = sum(inv["amount_cents"] for inv in overdue_invoices)

        return {
            "as_of_date": date.today().isoformat(),
            "count": len(overdue_invoices),
            "total_cents": total_overdue_cents,
            "invoices": overdue_invoices,
        }

    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate overdue report: {exc}",
        )
