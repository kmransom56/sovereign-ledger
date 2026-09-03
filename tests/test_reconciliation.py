"""Reconciliation + suggestion unit tests (pure, no DB).

Tests:
* Reconciliation difference computation (HR-7).
* $0.00-only completion (HR-7 negative).
* Invoice-match suggestion (HR-5).
* Learned-category suggestion (HR-5).
"""

from __future__ import annotations

import pytest

from ledger.reconciliation import (
    reconciliation_difference,
    can_complete,
    complete_reconciliation,
    ReconciliationError,
)
from ledger.bank_suggestions import (
    suggest_invoice_match,
    suggest_learned_category,
    Suggestion,
)


# ---------------------------------------------------------------------------
# Reconciliation (HR-7)
# ---------------------------------------------------------------------------


def test_reconciliation_balanced_completes() -> None:
    """$0.00 difference → can complete."""
    result = reconciliation_difference(421_375, [400_000, 21_375])
    assert result.difference_cents == 0
    assert result.is_complete is True
    assert can_complete(result) is True
    complete_reconciliation(result)  # no raise


def test_reconciliation_unbalanced_refused() -> None:
    """T-4/HR-7: $13.75 gap → completion refused."""
    result = reconciliation_difference(421_375, [421_375 - 13_75])
    assert result.difference_cents == 13_75
    assert result.is_complete is False
    assert can_complete(result) is False
    with pytest.raises(ReconciliationError, match=r"\$13\.75"):
        complete_reconciliation(result)


def test_reconciliation_empty_cleared() -> None:
    """No cleared lines: difference = full statement balance."""
    result = reconciliation_difference(100_000, [])
    assert result.difference_cents == 100_000
    assert result.is_complete is False


def test_reconciliation_exact_match() -> None:
    """The classic T-4 scenario: $4,213.75 vs $4,200.00 → $13.75 gap."""
    result = reconciliation_difference(421_375, [420_000])
    assert result.difference_cents == 13_75
    assert result.is_complete is False
    # After adding the missing line, it completes.
    result2 = reconciliation_difference(421_375, [420_000, 1_375])
    assert result2.difference_cents == 0
    assert result2.is_complete is True


def test_reconciliation_negative_cleared_lines() -> None:
    """Cleared lines include withdrawals (negative amounts)."""
    # Statement: $1000, cleared: $1500 deposit + -$500 withdrawal = $1000.
    result = reconciliation_difference(1_000_00, [1_500_00, -500_00])
    assert result.cleared_total_cents == 1_000_00
    assert result.difference_cents == 0
    assert result.is_complete is True


# ---------------------------------------------------------------------------
# Suggestions (HR-5)
# ---------------------------------------------------------------------------


def test_invoice_match_exact() -> None:
    """A deposit matching an open invoice balance → high-confidence suggestion."""
    inv = {"invoice_id": "INV-001", "outstanding_cents": 49_00, "customer_name": "Acme"}
    suggestion = suggest_invoice_match(49_00, [inv])
    assert suggestion is not None
    assert suggestion.suggestion_type == "invoice_match"
    assert suggestion.confidence == "high"
    assert suggestion.ref_entity_id == "INV-001"


def test_invoice_match_no_match() -> None:
    """No matching invoice → None."""
    inv = {"invoice_id": "INV-001", "outstanding_cents": 49_00, "customer_name": "Acme"}
    assert suggest_invoice_match(50_00, [inv]) is None  # wrong amount


def test_invoice_match_withdrawal_ignored() -> None:
    """Withdrawals (negative) never match invoices."""
    inv = {"invoice_id": "INV-001", "outstanding_cents": 49_00, "customer_name": "Acme"}
    assert suggest_invoice_match(-49_00, [inv]) is None


def test_learned_category_match() -> None:
    """A repeat vendor → medium-confidence suggestion."""
    history = {"coffee shop": "5000 Office Supplies"}
    suggestion = suggest_learned_category("STARBUCKS COFFEE SHOP #123", history)
    assert suggestion is not None
    assert suggestion.suggestion_type == "learned_category"
    assert suggestion.confidence == "medium"
    assert suggestion.debit_account_name == "5000 Office Supplies"


def test_learned_category_no_match() -> None:
    """Unknown vendor → None."""
    history = {"coffee shop": "5000 Office Supplies"}
    assert suggest_learned_category("RENT PAYMENT TO LANDLORD", history) is None


def test_learned_category_case_insensitive() -> None:
    """Vendor matching is case-insensitive."""
    history = {"starbucks": "5000 Office Supplies"}
    suggestion = suggest_learned_category("STARBUCKS #42", history)
    assert suggestion is not None
    assert suggestion.debit_account_name == "5000 Office Supplies"