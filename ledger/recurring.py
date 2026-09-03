"""Recurring template domain service for Sovereign Ledger AR.

Recurring templates (e.g., "$49/mo subscription") generate invoices on a
fixed schedule (1st of month). This service is pure: it constructs invoice
drafts ready for the app layer to post.

Key concepts:
  - Template: configuration (customer, amount, schedule, active period).
  - Generation cycle: the date when an invoice should be generated (e.g., 2026-09-01).
  - Status tracking: success/failure for each cycle (for admin visibility, CK-14).
  - Price changes: affect only future cycles (BR-3); pausing stops generation (BR-3).

Locked decisions honored:
  - CK-6: template generates exactly one invoice per cycle (1st of month by default).
  - CK-14: generation failures are flagged on one admin screen.
  - BR-3: price changes and pause/resume don't touch history.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

from ledger.invoices import InvoiceDraft, add_line_to_draft, new_invoice_draft

__all__ = [
    "RecurringTemplate",
    "TemplateStatus",
    "GenerationResult",
    "new_template",
    "mark_template_paused",
    "mark_template_active",
    "mark_template_ended",
    "should_generate_for_cycle",
    "generate_invoice_for_cycle",
    "RecurringError",
]


TemplateStatus = Literal["active", "paused", "ended"]


class RecurringError(ValueError):
    """Base error for recurring template operations."""


class InvalidTemplateError(RecurringError):
    """Template configuration failed validation."""


@dataclass(frozen=True, slots=True)
class RecurringTemplate:
    """A recurring invoice template.

    Attributes:
        id: Unique template identifier (None for drafts).
        customer_id: Which customer receives invoices from this template.
        name: Human-readable name (e.g., "Privacy Dawg - Monthly Service").
        description: Customer-facing description.
        amount_cents: Invoice amount per cycle.
        due_days_offset: Days after issue date for due date (e.g., 30).
        status: Lifecycle (active, paused, ended).
        active_from: When generation starts.
        active_until: When generation stops (None = indefinite).
        line_account_id: Income account for the line item.
        created_at: When the template was created (DB timestamp).
    """

    id: int | None
    customer_id: int
    name: str
    description: str | None
    amount_cents: int
    due_days_offset: int
    status: TemplateStatus
    active_from: date
    active_until: date | None
    line_account_id: int
    created_at: date | None


@dataclass(frozen=True, slots=True)
class GenerationResult:
    """Result of a generation attempt for one cycle.

    Attributes:
        template_id: Which template was processed.
        cycle_date: The date the generation was for (e.g., 2026-09-01).
        invoice_draft: The generated invoice (None if failed).
        error: Error message if generation failed (None if successful).
    """

    template_id: int | None
    cycle_date: date
    invoice_draft: InvoiceDraft | None
    error: str | None


def new_template(
    customer_id: int,
    name: str,
    amount_cents: int,
    line_account_id: int,
    active_from: date,
    description: str | None = None,
    due_days_offset: int = 30,
    active_until: date | None = None,
) -> RecurringTemplate:
    """Draft a new recurring template.

    Args:
        customer_id: Customer to invoice.
        name: Template name.
        amount_cents: Invoice amount per cycle.
        line_account_id: Income account for the line.
        active_from: Generation start date.
        description: Optional customer-facing description.
        due_days_offset: Days after issue for due date (default 30).
        active_until: Optional end date (None = indefinite).

    Returns:
        A RecurringTemplate draft (id=None, created_at=None).

    Raises:
        InvalidTemplateError: If validation fails.
    """
    if amount_cents <= 0:
        raise InvalidTemplateError("Template amount must be > 0.")
    if due_days_offset < 0:
        raise InvalidTemplateError("Due days offset must be >= 0.")
    if active_until and active_until < active_from:
        raise InvalidTemplateError("Active until date must be >= active from date.")

    return RecurringTemplate(
        id=None,
        customer_id=customer_id,
        name=name.strip(),
        description=description.strip() if description else None,
        amount_cents=amount_cents,
        due_days_offset=due_days_offset,
        status="active",
        active_from=active_from,
        active_until=active_until,
        line_account_id=line_account_id,
        created_at=None,
    )


def mark_template_paused(template: RecurringTemplate) -> RecurringTemplate:
    """Pause a template (stops generation, preserves history).

    Args:
        template: The template to pause.

    Returns:
        A new RecurringTemplate with status='paused'.
    """
    return RecurringTemplate(
        id=template.id,
        customer_id=template.customer_id,
        name=template.name,
        description=template.description,
        amount_cents=template.amount_cents,
        due_days_offset=template.due_days_offset,
        status="paused",
        active_from=template.active_from,
        active_until=template.active_until,
        line_account_id=template.line_account_id,
        created_at=template.created_at,
    )


def mark_template_active(template: RecurringTemplate) -> RecurringTemplate:
    """Reactivate a paused template.

    Args:
        template: The template to reactivate.

    Returns:
        A new RecurringTemplate with status='active'.
    """
    return RecurringTemplate(
        id=template.id,
        customer_id=template.customer_id,
        name=template.name,
        description=template.description,
        amount_cents=template.amount_cents,
        due_days_offset=template.due_days_offset,
        status="active",
        active_from=template.active_from,
        active_until=template.active_until,
        line_account_id=template.line_account_id,
        created_at=template.created_at,
    )


def mark_template_ended(template: RecurringTemplate) -> RecurringTemplate:
    """End a template permanently (no more generations).

    Args:
        template: The template to end.

    Returns:
        A new RecurringTemplate with status='ended'.
    """
    return RecurringTemplate(
        id=template.id,
        customer_id=template.customer_id,
        name=template.name,
        description=template.description,
        amount_cents=template.amount_cents,
        due_days_offset=template.due_days_offset,
        status="ended",
        active_from=template.active_from,
        active_until=template.active_until,
        line_account_id=template.line_account_id,
        created_at=template.created_at,
    )


def should_generate_for_cycle(template: RecurringTemplate, cycle_date: date) -> bool:
    """Check if a template should generate an invoice for a given cycle date.

    Generation should occur iff:
      - Template status is 'active' (not paused or ended).
      - cycle_date >= active_from.
      - cycle_date <= active_until (if active_until is set).

    Args:
        template: The template to check.
        cycle_date: The cycle date (e.g., 2026-09-01).

    Returns:
        True if generation should proceed, False otherwise.
    """
    if template.status != "active":
        return False
    if cycle_date < template.active_from:
        return False
    if template.active_until and cycle_date > template.active_until:
        return False
    return True


def generate_invoice_for_cycle(
    template: RecurringTemplate,
    cycle_date: date,
) -> GenerationResult:
    """Generate an invoice for a recurring template in a given cycle.

    Constructs an InvoiceDraft ready to post. The draft is dated on the cycle date
    (e.g., 2026-09-01) with due date = cycle_date + due_days_offset.

    Args:
        template: The template to generate from.
        cycle_date: The cycle date (e.g., month boundary).

    Returns:
        A GenerationResult with either an invoice_draft (success) or error (failure).

    Raises:
        RecurringError: Should not be raised if should_generate_for_cycle() is checked first.
    """
    if not should_generate_for_cycle(template, cycle_date):
        return GenerationResult(
            template_id=template.id,
            cycle_date=cycle_date,
            invoice_draft=None,
            error="Template is not active for this cycle or dates are out of range.",
        )

    # Construct the invoice draft
    try:
        due_date = cycle_date + timedelta(days=template.due_days_offset)

        draft = new_invoice_draft(
            customer_id=template.customer_id,
            issue_date=cycle_date,
            due_date=due_date,
            memo=template.description or template.name,
        )

        # Add one line for the template amount
        draft = add_line_to_draft(
            draft,
            account_id=template.line_account_id,
            description=template.name,
            quantity=1,
            unit_price_cents=template.amount_cents,
        )

        return GenerationResult(
            template_id=template.id,
            cycle_date=cycle_date,
            invoice_draft=draft,
            error=None,
        )
    except Exception as e:
        return GenerationResult(
            template_id=template.id,
            cycle_date=cycle_date,
            invoice_draft=None,
            error=str(e),
        )
