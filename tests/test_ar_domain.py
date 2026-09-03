"""Test suite for AR domain services (Step 8).

Test matrix (from build spec):
  - T-5: Payment allocation with overpayment → customer_credits (HR-8, CK-7, CK-8)
  - T-6: Recurring template generation (CK-6, CK-14)
  - T-8: Invoice creation posting balanced entry (HR-1, CK-5)

Property tests (hypothesis) on pure domain logic.
E2E tests against scratch Postgres fixture (conftest.py).
"""

from datetime import date, timedelta

import pytest
from hypothesis import given, strategies as st

from ledger.customers import (
    Customer,
    InvalidCustomerError,
    is_billable,
    mark_active,
    mark_inactive,
    new_customer,
)
from ledger.invoices import (
    DraftInvoiceError,
    Invoice,
    InvoiceDraft,
    InvoiceLine,
    add_line_to_draft,
    invoice_journal_entry,
    mark_paid,
    mark_void,
    new_invoice_draft,
)
from ledger.payments import (
    InvalidAllocationError,
    Payment,
    PaymentAllocationLine,
    PaymentError,
    allocate_payment,
    payment_journal_entry,
)
from ledger.recurring import (
    GenerationResult,
    InvalidTemplateError,
    RecurringTemplate,
    generate_invoice_for_cycle,
    mark_template_active,
    mark_template_ended,
    mark_template_paused,
    new_template,
    should_generate_for_cycle,
)
from ledger.types import AccountRef


# ============================================================================
# CUSTOMER DOMAIN TESTS
# ============================================================================


class TestCustomerDomain:
    """Property and unit tests for customer domain service."""

    def test_new_customer_valid(self) -> None:
        """T-8a: Create a valid customer draft."""
        c = new_customer(
            name="Acme Corp",
            tax_id="12-3456789",
            email="invoice@acme.com",
            address="123 Main St",
            notes="Net 30 terms",
        )
        assert c.id is None
        assert c.name == "Acme Corp"
        assert c.tax_id == "12-3456789"
        assert c.status == "active"
        assert c.created_at is None
        assert is_billable(c)

    def test_new_customer_name_required(self) -> None:
        """Customer name is required."""
        with pytest.raises(InvalidCustomerError):
            new_customer(name="")
        with pytest.raises(InvalidCustomerError):
            new_customer(name="   ")

    def test_customer_status_transitions(self) -> None:
        """T-8b: Customer status transitions."""
        c = new_customer(name="Test Corp")
        assert c.status == "active"
        assert is_billable(c)

        inactive = mark_inactive(c)
        assert inactive.status == "inactive"
        assert not is_billable(inactive)

        active_again = mark_active(inactive)
        assert active_again.status == "active"
        assert is_billable(active_again)

    @given(st.text(min_size=1))
    def test_customer_whitespace_stripped(self, name: str) -> None:
        """Customer names are stripped of leading/trailing whitespace."""
        padded = f"  {name}  "
        c = new_customer(name=padded)
        assert c.name == name.strip()


# ============================================================================
# INVOICE DOMAIN TESTS (T-8: Invoice Creation + Posting)
# ============================================================================


class TestInvoiceDomain:
    """Property and unit tests for invoice domain service."""

    def test_invoice_draft_creation(self) -> None:
        """T-8a: Create a valid invoice draft."""
        issue = date(2026, 9, 1)
        due = date(2026, 10, 1)
        draft = new_invoice_draft(
            customer_id=1,
            issue_date=issue,
            due_date=due,
            memo="Monthly service",
        )
        assert draft.customer_id == 1
        assert draft.issue_date == issue
        assert draft.due_date == due
        assert draft.total_amount_cents == 0
        assert len(draft.lines) == 0

    def test_invoice_draft_due_date_must_follow_issue(self) -> None:
        """Due date must be >= issue date."""
        issue = date(2026, 9, 1)
        due = date(2026, 8, 31)
        with pytest.raises(DraftInvoiceError):
            new_invoice_draft(
                customer_id=1,
                issue_date=issue,
                due_date=due,
            )

    def test_invoice_add_line_to_draft(self) -> None:
        """T-8b: Add line items to a draft."""
        draft = new_invoice_draft(
            customer_id=1,
            issue_date=date(2026, 9, 1),
            due_date=date(2026, 10, 1),
        )

        # Add first line: 2 units @ $2400 cents ($24.00) = $4800 cents
        draft1 = add_line_to_draft(
            draft,
            account_id=100,  # income account
            description="Privacy Dawg - Monthly",
            quantity=2,
            unit_price_cents=2400,
        )
        assert len(draft1.lines) == 1
        assert draft1.total_amount_cents == 4800

        # Add second line: 1 unit @ $1000 cents ($10.00) = $1000 cents
        draft2 = add_line_to_draft(
            draft1,
            account_id=101,
            description="Setup fee",
            quantity=1,
            unit_price_cents=1000,
        )
        assert len(draft2.lines) == 2
        assert draft2.total_amount_cents == 5800

    def test_invoice_line_quantity_must_be_positive(self) -> None:
        """Line quantity must be > 0."""
        draft = new_invoice_draft(
            customer_id=1,
            issue_date=date(2026, 9, 1),
            due_date=date(2026, 10, 1),
        )
        with pytest.raises(DraftInvoiceError):
            add_line_to_draft(draft, account_id=100, description="Test", quantity=0, unit_price_cents=1000)

    def test_invoice_journal_entry_construction(self) -> None:
        """T-8c: Construct balanced journal entry for invoice (HR-1, CK-5)."""
        draft = new_invoice_draft(
            customer_id=1,
            issue_date=date(2026, 9, 1),
            due_date=date(2026, 10, 1),
            memo="Invoice",
        )
        draft = add_line_to_draft(
            draft,
            account_id=100,
            description="Service",
            quantity=1,
            unit_price_cents=4900,  # $49.00
        )

        ar_account_id = 1  # AR asset account
        fiscal_period_id = 1
        entry, total = invoice_journal_entry(draft, ar_account_id, fiscal_period_id)

        # Check balanced (HR-1)
        assert len(entry.lines) == 2
        assert entry.lines[0].amount_cents == 4900  # debit AR
        assert entry.lines[1].amount_cents == -4900  # credit income
        assert sum(l.amount_cents for l in entry.lines) == 0

        # Check total
        assert total == 4900

    def test_invoice_journal_entry_multiple_lines(self) -> None:
        """Invoice posting with multiple lines still balances."""
        draft = new_invoice_draft(
            customer_id=1,
            issue_date=date(2026, 9, 1),
            due_date=date(2026, 10, 1),
        )
        draft = add_line_to_draft(draft, account_id=100, description="Service A", quantity=1, unit_price_cents=2000)
        draft = add_line_to_draft(draft, account_id=101, description="Service B", quantity=1, unit_price_cents=3000)

        entry, total = invoice_journal_entry(draft, ar_account_id=1, fiscal_period_id=1)

        # DR AR 5000, CR acc100 2000, CR acc101 3000 = balanced
        assert total == 5000
        assert sum(l.amount_cents for l in entry.lines) == 0

    def test_invoice_status_transitions(self) -> None:
        """Invoice can transition to paid or void."""
        invoice = Invoice(
            id=1,
            invoice_number=1001,
            customer_id=1,
            issue_date=date(2026, 9, 1),
            due_date=date(2026, 10, 1),
            memo="Test",
            total_amount_cents=4900,
            status="posted",
            posted_entry_id=100,
        )
        assert invoice.status == "posted"

        paid = mark_paid(invoice)
        assert paid.status == "paid"
        assert paid.id == invoice.id  # identity preserved

        voided = mark_void(invoice)
        assert voided.status == "void"


# ============================================================================
# PAYMENT DOMAIN TESTS (T-5: Overpayment + Allocation)
# ============================================================================


class TestPaymentDomain:
    """Property and unit tests for payment allocation (HR-8, CK-7)."""

    def test_allocate_payment_exact_match(self) -> None:
        """T-5a: Payment exactly matches invoice due."""
        payment_cents = 4900
        invoices = [(1, 4900)]  # invoice_id, amount_due_cents

        allocations, overpayment = allocate_payment(payment_cents, invoices)

        assert len(allocations) == 1
        assert allocations[0].invoice_id == 1
        assert allocations[0].amount_cents == 4900
        assert overpayment == 0

    def test_allocate_payment_across_multiple_invoices(self) -> None:
        """T-5b: Payment split across multiple invoices."""
        payment_cents = 7000
        invoices = [
            (1, 4900),
            (2, 3000),
        ]

        allocations, overpayment = allocate_payment(payment_cents, invoices)

        assert len(allocations) == 2
        assert allocations[0].amount_cents == 4900  # invoice 1 gets 4900
        assert allocations[1].amount_cents == 2100  # invoice 2 gets remaining 2100
        assert overpayment == 0

    def test_allocate_payment_overpayment(self) -> None:
        """T-5c: Payment exceeds total due → overpayment → customer_credits (HR-8)."""
        payment_cents = 6000  # paying $60.00
        invoices = [(1, 4900)]  # invoice is $49.00

        allocations, overpayment = allocate_payment(payment_cents, invoices)

        # Entire invoice is allocated, $11 is overpayment
        assert len(allocations) == 1
        assert allocations[0].amount_cents == 4900
        assert overpayment == 1100  # $11 overpayment
        # Overpayment becomes a customer_credits liability row

    def test_allocate_payment_invalid_amount(self) -> None:
        """Payment amount must be > 0."""
        with pytest.raises(InvalidAllocationError):
            allocate_payment(0, [(1, 1000)])
        with pytest.raises(InvalidAllocationError):
            allocate_payment(-500, [(1, 1000)])

    def test_allocate_payment_invalid_invoice_due(self) -> None:
        """Invoice due amounts must be >= 0."""
        with pytest.raises(InvalidAllocationError):
            allocate_payment(1000, [(1, -500)])

    def test_payment_journal_entry_no_overpayment(self) -> None:
        """T-5d: Payment entry balances (Dr Bank / Cr AR)."""
        payment = Payment(
            id=None,
            customer_id=1,
            payment_date=date(2026, 9, 15),
            amount_cents=4900,
            memo="Check #123",
            bank_line_id=None,
            allocations=(PaymentAllocationLine(invoice_id=1, amount_cents=4900),),
            overpayment_cents=0,
        )

        entry = payment_journal_entry(
            payment,
            bank_account_id=2,  # checking account
            ar_account_id=1,  # AR asset
            customer_credits_account_id=50,  # liability (not used here)
            fiscal_period_id=1,
        )

        # Check balanced (HR-1)
        assert len(entry.lines) == 2
        assert entry.lines[0].amount_cents == 4900  # debit bank
        assert entry.lines[1].amount_cents == -4900  # credit AR
        assert sum(l.amount_cents for l in entry.lines) == 0

    def test_payment_journal_entry_with_overpayment(self) -> None:
        """T-5e: Overpayment creates additional credit to customer_credits (HR-8)."""
        payment = Payment(
            id=None,
            customer_id=1,
            payment_date=date(2026, 9, 15),
            amount_cents=6000,  # $60 payment
            memo="Overpayment",
            bank_line_id=None,
            allocations=(PaymentAllocationLine(invoice_id=1, amount_cents=4900),),
            overpayment_cents=1100,  # $11 overpayment
        )

        entry = payment_journal_entry(
            payment,
            bank_account_id=2,
            ar_account_id=1,
            customer_credits_account_id=50,  # customer_credits liability
            fiscal_period_id=1,
        )

        # Check balanced (HR-1): Dr Bank 6000 / Cr AR 4900 / Cr customer_credits 1100
        assert len(entry.lines) == 3
        assert entry.lines[0].amount_cents == 6000  # debit bank (full payment)
        assert entry.lines[1].amount_cents == -4900  # credit AR (allocated portion)
        assert entry.lines[2].amount_cents == -1100  # credit customer_credits (overpayment liability)
        assert sum(l.amount_cents for l in entry.lines) == 0

    def test_payment_overpayment_requires_credits_account(self) -> None:
        """Overpayment without customer_credits_account_id raises error."""
        payment = Payment(
            id=None,
            customer_id=1,
            payment_date=date(2026, 9, 15),
            amount_cents=6000,
            memo="Overpayment",
            bank_line_id=None,
            allocations=(PaymentAllocationLine(invoice_id=1, amount_cents=4900),),
            overpayment_cents=1100,
        )

        with pytest.raises(PaymentError):
            payment_journal_entry(
                payment,
                bank_account_id=2,
                ar_account_id=1,
                customer_credits_account_id=None,  # missing required account
                fiscal_period_id=1,
            )


# ============================================================================
# RECURRING DOMAIN TESTS (T-6: Generation)
# ============================================================================


class TestRecurringDomain:
    """Property and unit tests for recurring template generation (CK-6)."""

    def test_new_template_valid(self) -> None:
        """T-6a: Create a valid recurring template."""
        active_from = date(2026, 9, 1)
        template = new_template(
            customer_id=1,
            name="Privacy Dawg - Monthly",
            amount_cents=4900,
            line_account_id=100,
            active_from=active_from,
            description="$49/mo subscription",
        )
        assert template.customer_id == 1
        assert template.status == "active"
        assert template.active_from == active_from
        assert template.active_until is None  # indefinite

    def test_new_template_amount_must_be_positive(self) -> None:
        """Template amount must be > 0."""
        with pytest.raises(InvalidTemplateError):
            new_template(
                customer_id=1,
                name="Test",
                amount_cents=0,
                line_account_id=100,
                active_from=date(2026, 9, 1),
            )

    def test_new_template_with_end_date(self) -> None:
        """T-6b: Template can have an end date."""
        active_from = date(2026, 9, 1)
        active_until = date(2026, 12, 31)
        template = new_template(
            customer_id=1,
            name="Seasonal",
            amount_cents=1000,
            line_account_id=100,
            active_from=active_from,
            active_until=active_until,
        )
        assert template.active_until == active_until

    def test_template_status_transitions(self) -> None:
        """T-6c: Template lifecycle (active → paused → active → ended)."""
        template = new_template(
            customer_id=1,
            name="Test",
            amount_cents=1000,
            line_account_id=100,
            active_from=date(2026, 9, 1),
        )
        assert template.status == "active"

        paused = mark_template_paused(template)
        assert paused.status == "paused"

        active_again = mark_template_active(paused)
        assert active_again.status == "active"

        ended = mark_template_ended(template)
        assert ended.status == "ended"

    def test_should_generate_for_cycle_active(self) -> None:
        """T-6d: Active template generates for cycles within range."""
        template = new_template(
            customer_id=1,
            name="Test",
            amount_cents=1000,
            line_account_id=100,
            active_from=date(2026, 9, 1),
            active_until=date(2026, 12, 31),
        )
        assert should_generate_for_cycle(template, date(2026, 9, 1))  # start date
        assert should_generate_for_cycle(template, date(2026, 10, 1))  # mid-range
        assert should_generate_for_cycle(template, date(2026, 12, 1))  # before end
        assert not should_generate_for_cycle(template, date(2026, 8, 31))  # before start
        assert not should_generate_for_cycle(template, date(2027, 1, 1))  # after end

    def test_should_generate_for_cycle_paused(self) -> None:
        """Paused template does not generate."""
        template = new_template(
            customer_id=1,
            name="Test",
            amount_cents=1000,
            line_account_id=100,
            active_from=date(2026, 9, 1),
        )
        paused = mark_template_paused(template)
        assert not should_generate_for_cycle(paused, date(2026, 9, 1))

    def test_generate_invoice_for_cycle_success(self) -> None:
        """T-6e: Generate invoice for a cycle (CK-6)."""
        template = new_template(
            customer_id=1,
            name="Privacy Dawg - Monthly",
            amount_cents=4900,
            line_account_id=100,
            active_from=date(2026, 9, 1),
            description="$49/mo subscription",
        )

        result = generate_invoice_for_cycle(template, date(2026, 9, 1))

        assert result.error is None
        assert result.invoice_draft is not None
        draft = result.invoice_draft
        assert draft.customer_id == 1
        assert draft.issue_date == date(2026, 9, 1)
        assert draft.due_date == date(2026, 10, 1)  # issue_date + 30 days
        assert draft.total_amount_cents == 4900
        assert len(draft.lines) == 1
        assert draft.lines[0].amount_cents == 4900

    def test_generate_invoice_for_cycle_out_of_range(self) -> None:
        """Generation fails for out-of-range cycles."""
        template = new_template(
            customer_id=1,
            name="Test",
            amount_cents=1000,
            line_account_id=100,
            active_from=date(2026, 9, 1),
            active_until=date(2026, 12, 31),
        )

        result = generate_invoice_for_cycle(template, date(2026, 8, 1))
        assert result.error is not None
        assert result.invoice_draft is None

    def test_generate_invoice_multiple_cycles(self) -> None:
        """T-6f: Same template generates one invoice per cycle (CK-6)."""
        template = new_template(
            customer_id=1,
            name="Privacy Dawg",
            amount_cents=4900,
            line_account_id=100,
            active_from=date(2026, 9, 1),
        )

        sep_result = generate_invoice_for_cycle(template, date(2026, 9, 1))
        oct_result = generate_invoice_for_cycle(template, date(2026, 10, 1))
        nov_result = generate_invoice_for_cycle(template, date(2026, 11, 1))

        # All three should succeed and have the same amount
        assert sep_result.invoice_draft is not None
        assert oct_result.invoice_draft is not None
        assert nov_result.invoice_draft is not None

        assert sep_result.invoice_draft.total_amount_cents == 4900
        assert oct_result.invoice_draft.total_amount_cents == 4900
        assert nov_result.invoice_draft.total_amount_cents == 4900

        # But different issue dates
        assert sep_result.invoice_draft.issue_date == date(2026, 9, 1)
        assert oct_result.invoice_draft.issue_date == date(2026, 10, 1)
        assert nov_result.invoice_draft.issue_date == date(2026, 11, 1)
