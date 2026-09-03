"""Reconciliation decision logic (Step 7, HR-7).

Pure functions for the reconciliation flow:

* :func:`reconciliation_difference` — statement vs cleared lines difference.
* :func:`can_complete` — True iff difference is exactly $0.00 (HR-7).
* :func:`complete_reconciliation` — the reconciliation record when complete.

HR-7 LOCKED RULE: a reconciliation completes ONLY when the difference
between the statement balance and the sum of cleared lines is exactly
$0.00.  No rounding, no tolerance — a $13.75 gap is refused.

This module is pure: no I/O, no DB.  The caller (app route) persists.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "ReconciliationResult",
    "ReconciliationError",
    "reconciliation_difference",
    "can_complete",
    "complete_reconciliation",
]


class ReconciliationError(ValueError):
    """Reconciliation cannot complete — difference is not $0.00 (HR-7)."""


@dataclass(frozen=True, slots=True)
class ReconciliationResult:
    """The outcome of a reconciliation attempt.

    Fields:
        statement_balance_cents: the bank statement's ending balance.
        cleared_total_cents: sum of all cleared bank lines.
        difference_cents: statement - cleared (must be 0 to complete).
        is_complete: True iff difference == 0 (HR-7).
    """

    statement_balance_cents: int
    cleared_total_cents: int
    difference_cents: int
    is_complete: bool


def reconciliation_difference(
    statement_balance_cents: int,
    cleared_line_amounts: list[int],
) -> ReconciliationResult:
    """Compute the reconciliation difference (HR-7).

    Args:
        statement_balance_cents: the bank statement's ending balance.
        cleared_line_amounts: the amounts of all cleared bank lines
            (signed: + deposit, − withdrawal).

    Returns:
        A :class:`ReconciliationResult` with the difference and completion flag.
    """
    cleared_total = sum(cleared_line_amounts)
    diff = statement_balance_cents - cleared_total
    return ReconciliationResult(
        statement_balance_cents=statement_balance_cents,
        cleared_total_cents=cleared_total,
        difference_cents=diff,
        is_complete=(diff == 0),
    )


def can_complete(result: ReconciliationResult) -> bool:
    """True iff the reconciliation can complete (HR-7: difference == $0.00)."""
    return result.is_complete


def complete_reconciliation(result: ReconciliationResult) -> ReconciliationResult:
    """Complete the reconciliation — refuses if difference != $0.00 (HR-7).

    Returns:
        The same :class:`ReconciliationResult` (now confirmed complete).

    Raises:
        ReconciliationError: the difference is not zero.
    """
    if not result.is_complete:
        raise ReconciliationError(
            f"reconciliation cannot complete: statement "
            f"${result.statement_balance_cents / 100:.2f} vs cleared "
            f"${result.cleared_total_cents / 100:.2f} — difference "
            f"${result.difference_cents / 100:.2f} is not $0.00 (HR-7)"
        )
    return result