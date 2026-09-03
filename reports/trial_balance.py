"""Trial-balance report — pure derivation over journal entries (HR-9 / T-8).

A trial balance lists every account that has posted lines, grouped by
account, with its debit and credit totals.  The defining invariant: the
grand total of all debits equals the grand total of all credits (Σ = 0
under the D-3 sign convention), so the trial balance MUST net to exactly
$0.00.  If it doesn't, a posting path is broken — the function raises
rather than returning an unbalanced report.

Input: a sequence of ``JournalEntry`` values (the pure domain objects
from ``ledger.types``).  No I/O of any kind — the caller loads entries from
storage and passes them in.

Output: a ``TrialBalance`` value object with per-account rows and the
grand totals.  The rows are sorted by account code for deterministic output.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Mapping
from collections import defaultdict

from ledger.types import JournalEntry, JournalLine

__all__ = [
    "TrialBalanceRow",
    "TrialBalance",
    "trial_balance",
]


@dataclass(frozen=True, slots=True)
class TrialBalanceRow:
    """One account line in the trial balance."""

    account_code: str
    account_name: str
    debit_cents: int   # 0 when the account is credit-normal or has no debit side
    credit_cents: int  # 0 when the account is debit-normal or has no credit side

    @property
    def net_cents(self) -> int:
        """Signed net balance (debit positive, credit negative, D-3)."""
        return self.debit_cents - self.credit_cents


@dataclass(frozen=True, slots=True)
class TrialBalance:
    """The complete trial balance — all accounts + grand totals.

    The ``is_balanced`` property is always True for a report returned by
    :func:`trial_balance` — the function raises on an unbalanced set.  It
    exists for defense-in-depth assertions by callers.
    """

    rows: tuple[TrialBalanceRow, ...]
    total_debit_cents: int
    total_credit_cents: int

    @property
    def is_balanced(self) -> bool:
        """True iff grand debits == grand credits (HR-9 invariant)."""
        return self.total_debit_cents == self.total_credit_cents

    @property
    def net_cents(self) -> int:
        """Grand total net — always 0 for a balanced trial balance."""
        return self.total_debit_cents - self.total_credit_cents


def trial_balance(entries: Iterable[JournalEntry]) -> TrialBalance:
    """Compute the trial balance from posted journal entries (HR-9/T-8).

    Aggregates every line across all entries by account, sums the debit
    (positive) and credit (negative) sides separately, and returns the
    per-account rows plus grand totals.  Raises if the books don't balance.

    Args:
        entries: the posted ``JournalEntry`` values to aggregate.

    Returns:
        A balanced :class:`TrialBalance` (rows sorted by account code).

    Raises:
        ValueError: the entries do not net to zero (a broken posting path).
    """
    debit_by_account: dict[str, int] = defaultdict(int)
    credit_by_account: dict[str, int] = defaultdict(int)
    name_by_code: dict[str, str] = {}

    for entry in entries:
        if not isinstance(entry, JournalEntry):
            raise TypeError(
                f"trial_balance expects JournalEntry values; got {type(entry).__name__}"
            )
        for line in entry.lines:
            code = line.account.code
            name = line.account.name
            name_by_code.setdefault(code, name)
            if line.amount_cents > 0:
                debit_by_account[code] += line.amount_cents
            elif line.amount_cents < 0:
                credit_by_account[code] += -line.amount_cents

    all_codes = sorted(set(debit_by_account) | set(credit_by_account))
    rows: list[TrialBalanceRow] = []
    total_debit = 0
    total_credit = 0
    for code in all_codes:
        d = debit_by_account.get(code, 0)
        c = credit_by_account.get(code, 0)
        rows.append(TrialBalanceRow(
            account_code=code,
            account_name=name_by_code[code],
            debit_cents=d,
            credit_cents=c,
        ))
        total_debit += d
        total_credit += c

    if total_debit != total_credit:
        raise ValueError(
            f"trial balance is unbalanced: total debits {total_debit} cents != "
            f"total credits {total_credit} cents (difference {total_debit - total_credit} cents); "
            "a posting path is broken — entries should net to zero under D-3"
        )

    return TrialBalance(
        rows=tuple(rows),
        total_debit_cents=total_debit,
        total_credit_cents=total_credit,
    )