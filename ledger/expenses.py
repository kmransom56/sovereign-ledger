"""Domain models for Accounts Payable: vendors, bills, expense categories, payments (Step 12).

Immutable value objects for vendor management, bill lifecycle, and expense categorization.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class ExpenseCategory:
    """Expense category for bill line items (maps to Chart of Accounts)."""

    id: int
    code: str  # "SW", "UTIL", "PROF", etc.
    name: str
    description: str | None
    account_id: int | None  # Reference to chart of accounts
    tax_deductible: bool
    is_active: bool

    def __post_init__(self) -> None:
        if not self.code or not self.code.strip():
            raise ValueError("Expense category code is required")
        if not self.name or not self.name.strip():
            raise ValueError("Expense category name is required")


@dataclass(frozen=True)
class Vendor:
    """Vendor/supplier entity."""

    id: int
    name: str
    tax_id: str | None
    contact_name: str | None
    email: str | None
    phone: str | None
    address: str | None
    city: str | None
    state: str | None
    zip_code: str | None
    payment_terms: str | None  # "net30", "net60", "due_on_receipt"
    is_active: bool
    notes: str | None

    def __post_init__(self) -> None:
        if not self.name or not self.name.strip():
            raise ValueError("Vendor name is required")


@dataclass(frozen=True)
class BillLineItem:
    """Line item on a bill."""

    id: int | None
    expense_category_id: int
    description: str
    quantity: Decimal
    unit_price_cents: int
    amount_cents: int
    business_use_percent: Decimal  # 0-100, for mixed-use expenses
    deductible_amount_cents: int  # amount_cents * business_use_percent / 100

    def __post_init__(self) -> None:
        if not self.description or not self.description.strip():
            raise ValueError("Bill line description is required")
        if self.quantity < 0:
            raise ValueError("Quantity must be non-negative")
        if self.unit_price_cents < 0:
            raise ValueError("Unit price must be non-negative")
        if self.amount_cents < 0:
            raise ValueError("Line amount must be non-negative")
        if not (0 <= self.business_use_percent <= 100):
            raise ValueError("Business use percent must be 0-100")

        # Verify deductible amount matches calculation
        expected_deductible = int(
            self.amount_cents * self.business_use_percent / Decimal(100)
        )
        if self.deductible_amount_cents != expected_deductible:
            raise ValueError(
                f"Deductible amount ({self.deductible_amount_cents}) does not match "
                f"calculation ({expected_deductible})"
            )


@dataclass(frozen=True)
class BillDraft:
    """Draft bill before posting."""

    bill_number: str
    vendor_id: int
    bill_date: date
    due_date: date
    memo: str | None
    period_end: date | None  # For recurring expenses
    lines: list[BillLineItem]

    def __post_init__(self) -> None:
        if not self.bill_number or not self.bill_number.strip():
            raise ValueError("Bill number is required")
        if self.vendor_id <= 0:
            raise ValueError("Vendor ID must be positive")
        if self.bill_date > self.due_date:
            raise ValueError("Due date must be on or after bill date")
        if not self.lines:
            raise ValueError("Bill must have at least one line item")

    def total_amount_cents(self) -> int:
        """Sum of all line amounts."""
        return sum(line.amount_cents for line in self.lines)

    def total_deductible_cents(self) -> int:
        """Sum of all deductible amounts (respecting business-use %)."""
        return sum(line.deductible_amount_cents for line in self.lines)


@dataclass(frozen=True)
class BillPosted:
    """Bill after posting to ledger."""

    id: int
    bill_number: str
    vendor_id: int
    bill_date: date
    due_date: date
    period_end: date | None
    total_amount_cents: int
    paid_amount_cents: int
    status: str  # "posted", "paid", etc.
    memo: str | None
    lines: list[BillLineItem]

    @property
    def outstanding_cents(self) -> int:
        """Unpaid balance."""
        return self.total_amount_cents - self.paid_amount_cents

    @property
    def is_fully_paid(self) -> bool:
        """True if all paid."""
        return self.paid_amount_cents >= self.total_amount_cents

    @property
    def is_overdue(self, as_of: date | None = None) -> bool:
        """True if due date has passed."""
        check_date = as_of or date.today()
        return check_date > self.due_date and not self.is_fully_paid


@dataclass(frozen=True)
class BillPayment:
    """Payment allocation against a bill."""

    id: int | None
    bill_id: int
    payment_date: date
    amount_cents: int
    payment_method: str  # "check", "ach", "credit_card", "cash"
    reference_number: str | None  # Check#, ACH ref, etc.
    memo: str | None

    def __post_init__(self) -> None:
        if self.bill_id <= 0:
            raise ValueError("Bill ID must be positive")
        if self.amount_cents <= 0:
            raise ValueError("Payment amount must be positive")
        if not self.payment_method or not self.payment_method.strip():
            raise ValueError("Payment method is required")
