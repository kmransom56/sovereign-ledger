"""Bank-account suggestion generation (Step 7, HR-5).

Pure functions that produce *suggestions* (drafts) for imported bank
lines — never auto-postings.  Two suggestion types:

1. **Auto-match**: a deposit whose amount matches an open invoice's
   outstanding balance → suggest posting the payment (Dr Bank / Cr AR).
2. **Learned category**: a repeat vendor whose previous import was
   posted to a specific expense account → suggest the same account.

Suggestions carry a confidence level so the review UI can display it;
the human accept is always the gate (HR-5).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

__all__ = [
    "Suggestion",
    "SuggestionType",
    "SuggestionConfidence",
    "suggest_invoice_match",
    "suggest_learned_category",
]


SuggestionType = str  # "invoice_match" | "learned_category" | "manual"
SuggestionConfidence = str  # "high" | "medium" | "low"


@dataclass(frozen=True, slots=True)
class Suggestion:
    """A review-queue suggestion for a bank line (HR-5: draft only).

    Fields:
        suggestion_type: "invoice_match", "learned_category", or "manual".
        confidence: "high", "medium", or "low".
        debit_account_name: suggested debit account name (or None).
        credit_account_name: suggested credit account name (or None).
        description: human-readable reason for the suggestion.
        ref_entity_id: optional reference (e.g. invoice id for auto-match).
    """

    suggestion_type: SuggestionType
    confidence: SuggestionConfidence
    debit_account_name: str | None = None
    credit_account_name: str | None = None
    description: str = ""
    ref_entity_id: str | None = None


def suggest_invoice_match(
    bank_amount_cents: int,
    open_invoices: list[dict],
) -> Suggestion | None:
    """Suggest an invoice-payment posting when a deposit matches an open invoice.

    Args:
        bank_amount_cents: the bank line's amount (+ = deposit).
        open_invoices: list of {"invoice_id": str, "outstanding_cents": int,
            "customer_name": str}.

    Returns:
        A Suggestion with type "invoice_match" and confidence "high" when
        an exact match is found, or None.
    """
    if bank_amount_cents <= 0:
        return None  # deposits only

    for inv in open_invoices:
        if inv["outstanding_cents"] == bank_amount_cents:
            return Suggestion(
                suggestion_type="invoice_match",
                confidence="high",
                debit_account_name="1200 Accounts Receivable",
                credit_account_name="1200 Accounts Receivable",  # payment reduces AR
                description=(
                    f"Matches open invoice {inv['invoice_id']} "
                    f"from {inv['customer_name']} (${bank_amount_cents / 100:.2f})"
                ),
                ref_entity_id=inv["invoice_id"],
            )
    return None


def suggest_learned_category(
    bank_description: str,
    vendor_history: Mapping[str, str],
) -> Suggestion | None:
    """Suggest the same expense account a repeat vendor was previously posted to.

    Args:
        bank_description: the bank line's description (vendor name).
        vendor_history: {vendor_substring: account_name} learned from
            previous accepted imports.

    Returns:
        A Suggestion with type "learned_category" and confidence "medium",
        or None if no vendor match.
    """
    desc_lower = bank_description.lower()
    for vendor_fragment, account_name in vendor_history.items():
        if vendor_fragment.lower() in desc_lower:
            return Suggestion(
                suggestion_type="learned_category",
                confidence="medium",
                debit_account_name=account_name,
                credit_account_name="1000 Checking Account",
                description=f"Repeat vendor: previously posted to {account_name}",
            )
    return None