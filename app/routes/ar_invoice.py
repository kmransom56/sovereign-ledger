"""AR Invoice routes (Step 8, CK-17).

REST endpoints for managing invoices:
* POST /ar/invoice — create a new invoice
* GET /ar/invoice/{invoice_id} — get an invoice
* PUT /ar/invoice/{invoice_id}/status — update invoice status
* GET /ar/invoices — list all invoices

The accountant role is allowed to edit AR invoice details (HR-13).
"""

from datetime import date
from typing import Optional

from app.main import router  # the main FastAPI instance
from fastapi import Depends, HTTPException, Request, status
from pydantic import BaseModel

from ledger.ar_invoice import (
    Invoice,
    InvoiceStatus,
    InvalidInvoiceError,
    validate_invoice,
    update_invoice_status
)
from ledger.auth import require_admin, current_user
from ledger.repository import get_ar_accounts, create_ar_invoice, get_ar_invoice


# DTOs: data transfer objects for input/output
class InvoiceCreateRequest(BaseModel):
    """Input DTO for creating a new invoice."""
    customer_name: str
    due_date: date
    amount_cents: int  # validated on creation
    status: Optional[InvoiceStatus] = InvoiceStatus.DRAFT


class InvoiceUpdateStatusRequest(BaseModel):
    """Input DTO for updating an invoice's status."""
    new_status: InvoiceStatus


@router.post("/ar/invoice")
def create_invoice(request: Request, payload: InvoiceCreateRequest,
                user: dict = Depends(require_admin)) -> Invoice:
    """Create a new AR invoice (CK-17, HR-13).

    POST /ar/invoice JSON: customer_name, due_date, amount_cents
    """
    # D-29: No validation needed — amount field is typed and pydantic validates it.
    try:
        invoice = create_ar_invoice(
            customer_name=payload.customer_name,
            due_date=payload.due_date,
            amount_cents=payload.amount_cents,
            status=payload.status,
        )
        validate_invoice(invoice)
        # D-31: Return created invoice to the client.
        return invoice
    except (InvalidInvoiceError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )


@router.get("/ar/invoice/{invoice_id}")
def get_invoice(request: Request, invoice_id: str,
                 user: dict = Depends(current_user)) -> Invoice:
    """Get an AR invoice by ID (CK-17).

    GET /ar/invoice/<uuid>
    """
    try:
        return get_ar_invoice(invoice_id)
    except KeyError:
        # D-59: 404 for non-existent invoices
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Invoice not found: {invoice_id}"
        )


@router.put("/ar/invoice/{invoice_id}/status")
def update_invoice_status_endpoint(request: Request, invoice_id: str,
                              payload: InvoiceUpdateStatusRequest,
                              user: dict = Depends(require_admin)) -> Invoice:
    """Update an AR invoice's status (CK-17, HR-13).

    PUT /ar/invoice/<uuid>/status JSON: new_status
    """
    try:
        # D-35: Get the current invoice.
        invoice = get_ar_invoice(invoice_id)
        # D-36: Update and revalidate.
        updated = update_invoice_status(invoice, payload.new_status)
        # D-37: Save the updated invoice.
        return create_ar_invoice(  # Re-save with new status
            customer_name=invoice.customer_name,
            due_date=invoice.due_date,
            amount_cents=invoice.amount_cents,
            status=payload.new_status,
        )
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Invoice not found: {invoice_id}"
        )
    except (InvalidInvoiceError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc)
        )


@router.get("/ar/invoices")
def list_invoices(request: Request,
                 user: dict = Depends(current_user)) -> list[Invoice]:
    """List all AR invoices.

    GET /ar/invoices
    """
    # D-38: List without filtering for now (may add query params later).
    # This is a pure function, just returns whatever repository returns.
    return get_ar_invoice(invoice_id=None)  # Return all invoices