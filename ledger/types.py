"""Pure money and journal-entry types for the Sovereign Ledger domain core.

SIGN CONVENTION — locked decision D-3, memorize it, it is load-bearing:

    amount_cents > 0   →  DEBIT   (+)
    amount_cents < 0   →  CREDIT  (−)

Every amount in the domain is a signed integer count of USD cents: never
float, never the SQL ``money`` type, and ``Decimal`` only at the importer
boundary (see ``cents_from_decimal``). The convention is encoded
structurally so later steps cannot misread it:

* :meth:`JournalLine.debit` / :meth:`JournalLine.credit` build lines from
  a magnitude with the sign baked in.
* :attr:`AccountType.normal_balance_sign` states which sign an account
  class normally carries (+1 debit-normal for asset/expense, -1
  credit-normal for liability/equity/income).
* The property tests in ``tests/test_engine.py`` pin all of the above.

Purity contract (hard rule 1): this module performs no I/O of any kind and
imports nothing beyond the standard library. ``scripts/check_boundaries.py``
fails the build if a forbidden import token ever appears under ``ledger/``
or ``reports/``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import TypeAlias

__all__ = [
    "BIGINT_MAX_CENTS",
    "AccountRef",
    "AccountType",
    "BigIntOverflowError",
    "JournalEntry",
    "JournalLine",
    "Money",
    "UnbalancedEntryError",
    "cents_from_decimal",
]

#: Money is a signed integer of USD cents — positive = debit, negative =
#: credit (D-3). Valid range is bounded by :data:`BIGINT_MAX_CENTS`.
Money: TypeAlias = int

#: Postgres BIGINT ceiling (2**63 - 1 cents, ~$92.25 quadrillion). Line
#: amounts are validated against this so a value that could not be stored
#: in ``journal_lines.amount_cents`` (BIGINT per D-3) never enters the
#: domain. Python ints are arbitrary precision, so this guard is what
#: keeps domain arithmetic inside storable BIGINT range.
BIGINT_MAX_CENTS: int = 2**63 - 1


class UnbalancedEntryError(ValueError):
    """Σ(line.amount_cents) != 0 — no unbalanced journal entry may exist."""


class BigIntOverflowError(ValueError):
    """|amount_cents| exceeds the Postgres BIGINT ceiling."""


class AccountType(Enum):
    """Chart-of-accounts class with its normal-balance sign (D-3)."""

    ASSET = "asset"
    EXPENSE = "expense"
    LIABILITY = "liability"
    EQUITY = "equity"
    INCOME = "income"

    @property
    def normal_balance_sign(self) -> int:
        """+1 when the account normally carries a DEBIT (+) balance,
        -1 when it normally carries a CREDIT (−) balance (D-3)."""
        return +1 if self in (AccountType.ASSET, AccountType.EXPENSE) else -1


@dataclass(frozen=True, slots=True)
class AccountRef:
    """Immutable reference to an account in the chart of accounts.

    Maps 1:1 to a row of the append-only ``accounts`` table, keyed by
    ``code``. Pure value object — persistence is the caller's job.
    """

    code: str
    name: str
    type: AccountType

    def __post_init__(self) -> None:
        if not isinstance(self.code, str) or not self.code.strip():
            raise ValueError("AccountRef.code must be a non-empty string")
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("AccountRef.name must be a non-empty string")
        if not isinstance(self.type, AccountType):
            raise TypeError("AccountRef.type must be an AccountType")


@dataclass(frozen=True, slots=True)
class JournalLine:
    """One double-entry line: an account reference + a SIGNED amount.

    ``amount_cents`` follows D-3 exactly: **+ = debit, − = credit**.
    Construct lines via :meth:`debit` / :meth:`credit` rather than
    hand-signing integers so the convention can never be flipped.
    """

    account: AccountRef
    amount_cents: int

    def __post_init__(self) -> None:
        if not isinstance(self.account, AccountRef):
            raise TypeError("JournalLine.account must be an AccountRef")
        if isinstance(self.amount_cents, bool) or not isinstance(self.amount_cents, int):
            raise TypeError(
                "JournalLine.amount_cents must be int cents (+ debit / − credit); "
                f"got {type(self.amount_cents).__name__} — float money is forbidden"
            )
        if abs(self.amount_cents) > BIGINT_MAX_CENTS:
            raise BigIntOverflowError(
                f"amount_cents {self.amount_cents} exceeds the Postgres BIGINT "
                f"ceiling ({BIGINT_MAX_CENTS})"
            )

    @classmethod
    def debit(cls, account: AccountRef, amount_cents: int) -> "JournalLine":
        """DEBIT line (+ side of D-3): the magnitude is stored POSITIVE."""
        if isinstance(amount_cents, bool) or not isinstance(amount_cents, int):
            raise TypeError(
                f"debit magnitude must be int cents; got {type(amount_cents).__name__} "
                "(float money is forbidden)"
            )
        return cls(account, +abs(amount_cents))

    @classmethod
    def credit(cls, account: AccountRef, amount_cents: int) -> "JournalLine":
        """CREDIT line (− side of D-3): the magnitude is stored NEGATIVE."""
        if isinstance(amount_cents, bool) or not isinstance(amount_cents, int):
            raise TypeError(
                f"credit magnitude must be int cents; got {type(amount_cents).__name__} "
                "(float money is forbidden)"
            )
        return cls(account, -abs(amount_cents))

    @property
    def is_debit(self) -> bool:
        """True when this line sits on the debit (+) side."""
        return self.amount_cents > 0

    @property
    def is_credit(self) -> bool:
        """True when this line sits on the credit (−) side."""
        return self.amount_cents < 0


@dataclass(frozen=True, slots=True)
class JournalEntry:
    """An atomic double-entry posting — ALWAYS exactly balanced.

    HR-1 invariant: Σ(line.amount_cents) == 0 with the D-3 sign convention
    (+ debit, − credit). ``__post_init__`` REFUSES to construct an
    unbalanced entry, so an unbalanced ``JournalEntry`` cannot exist
    anywhere in the system; ``ledger.engine.post`` / ``post_lines``
    re-verify the same invariant as defense in depth.

    Field mapping to the append-only tables (Step 2): ``entry_id`` →
    ``journal_entries.id``; ``lines[i].amount_cents`` →
    ``journal_lines.amount_cents`` (signed BIGINT cents); ``date`` →
    ``journal_entries.entry_date``.
    """

    entry_id: str
    date: date
    description: str
    lines: tuple[JournalLine, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.entry_id, str) or not self.entry_id.strip():
            raise ValueError("JournalEntry.entry_id must be a non-empty string")
        if type(self.date) is not date:
            raise TypeError(
                "JournalEntry.date must be a datetime.date "
                f"(got {type(self.date).__name__}; no datetime, no str)"
            )
        if not isinstance(self.description, str):
            raise TypeError("JournalEntry.description must be a str")
        lines = tuple(self.lines)
        if not lines:
            raise UnbalancedEntryError("a journal entry needs at least one line")
        for line in lines:
            if not isinstance(line, JournalLine):
                raise TypeError(
                    "JournalEntry.lines must contain JournalLine values; "
                    f"got {type(line).__name__}"
                )
        total = sum(line.amount_cents for line in lines)
        if total != 0:
            raise UnbalancedEntryError(
                f"journal entry {self.entry_id!r} is unbalanced: "
                f"Σ amount_cents = {total} (+ debit / − credit); must be exactly 0"
            )
        object.__setattr__(self, "lines", lines)


def cents_from_decimal(value: Decimal) -> int:
    """Exact Decimal-USD → int-cents conversion for the importer boundary.

    SKILL trap 8 contract: parse → ``Decimal`` → validate exactly 2
    decimal places → integer cents. Floats are rejected outright (never
    float money). Raises :class:`BigIntOverflowError` beyond the BIGINT
    ceiling and ``ValueError`` for sub-cent precision or non-finite input.
    """
    if not isinstance(value, Decimal):
        raise TypeError(
            "cents_from_decimal expects a decimal.Decimal; "
            f"got {type(value).__name__} (float money is forbidden)"
        )
    if not value.is_finite():
        raise ValueError("non-finite Decimal is not money")
    scaled = value * 100
    if scaled != scaled.to_integral_value():
        raise ValueError(
            f"{value} carries sub-cent precision; exactly 2 decimal places required"
        )
    cents = int(scaled)
    if abs(cents) > BIGINT_MAX_CENTS:
        raise BigIntOverflowError(
            f"{value} converts to {cents} cents, beyond the Postgres BIGINT ceiling"
        )
    return cents