"""Customer domain service for Sovereign Ledger AR (Accounts Receivable).

Pure domain functions for customer lifecycle: registration, status tracking,
querying for payment readiness. No I/O; persistence is the caller's job.

All functions are deterministic and testable in isolation via property tests.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal

__all__ = [
    "Customer",
    "CustomerStatus",
    "new_customer",
]


CustomerStatus = Literal["active", "inactive", "archived"]


@dataclass(frozen=True, slots=True)
class Customer:
    """A billable customer record (AR domain).

    Attributes:
        id: Unique customer identifier (None for drafts, set by DB on persist).
        name: Customer's business name (unique).
        tax_id: SSN/EIN for 1099 tracking (optional).
        email: Contact email for statements.
        address: Mailing address.
        notes: Internal notes (e.g., payment terms, special instructions).
        status: Lifecycle state (active, inactive, archived).
        created_at: When the customer was registered (DB timestamp).
    """

    id: int | None
    name: str
    tax_id: str | None
    email: str | None
    address: str | None
    notes: str | None
    status: CustomerStatus
    created_at: date | None


class CustomerError(ValueError):
    """Base error for customer domain operations."""


class InvalidCustomerError(CustomerError):
    """Customer data failed validation."""


def new_customer(
    name: str,
    tax_id: str | None = None,
    email: str | None = None,
    address: str | None = None,
    notes: str | None = None,
) -> Customer:
    """Draft a new customer record.

    Args:
        name: Customer business name (required, unique at persist time).
        tax_id: SSN/EIN for 1099 tracking (optional).
        email: Contact email (optional).
        address: Mailing address (optional).
        notes: Internal notes (optional).

    Returns:
        A Customer draft (id=None, status='active', created_at=None).

    Raises:
        InvalidCustomerError: If name is empty.
    """
    if not name or not name.strip():
        raise InvalidCustomerError("Customer name is required and cannot be empty.")

    return Customer(
        id=None,
        name=name.strip(),
        tax_id=tax_id.strip() if tax_id else None,
        email=email.strip() if email else None,
        address=address.strip() if address else None,
        notes=notes.strip() if notes else None,
        status="active",
        created_at=None,
    )


def mark_inactive(customer: Customer) -> Customer:
    """Transition a customer to inactive status.

    Inactive customers receive no new invoices but retain history.

    Args:
        customer: The customer to mark inactive.

    Returns:
        A new Customer with status='inactive'.
    """
    return Customer(
        id=customer.id,
        name=customer.name,
        tax_id=customer.tax_id,
        email=customer.email,
        address=customer.address,
        notes=customer.notes,
        status="inactive",
        created_at=customer.created_at,
    )


def mark_active(customer: Customer) -> Customer:
    """Transition a customer to active status (reactivate).

    Args:
        customer: The customer to mark active.

    Returns:
        A new Customer with status='active'.
    """
    return Customer(
        id=customer.id,
        name=customer.name,
        tax_id=customer.tax_id,
        email=customer.email,
        address=customer.address,
        notes=customer.notes,
        status="active",
        created_at=customer.created_at,
    )


def is_billable(customer: Customer) -> bool:
    """Check if a customer can receive new invoices.

    Only active customers are billable.

    Args:
        customer: The customer to check.

    Returns:
        True if customer.status == 'active', False otherwise.
    """
    return customer.status == "active"
