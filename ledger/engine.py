"""Pure posting engine for the Sovereign Ledger.

This module is the construction/posting path for journal entries. It is
pure by hard rule 1: no web framework, database driver, or HTTP client
imports; no clock, no filesystem, no network, no randomness.
``scripts/check_boundaries.py`` fails CI if a forbidden I/O token ever
appears under ``ledger/``.

HR-1 / D-3 invariant: an entry is postable if and only if

    Σ(line.amount_cents) == 0        (+ = DEBIT, − = CREDIT)

``JournalEntry`` already refuses unbalanced construction, and this engine
re-verifies the same invariant as defense in depth (``validate_balanced``)
before freezing the accepted posting into a :class:`PostedEntry` value
object. Posting is an atomic, side-effect-free fold:

    JournalEntry (validated) → validate_balanced (Σ == 0) → PostedEntry (frozen)

Money semantics: every amount is a signed integer count of USD cents —
positive is a DEBIT (+), negative is a CREDIT (−). Nothing here rounds,
converts to float, or touches a database; persistence is the caller's job.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Iterable

from ledger.types import JournalEntry, JournalLine, UnbalancedEntryError

__all__ = ["PostedEntry", "post", "post_lines", "validate_balanced"]


def validate_balanced(lines: Iterable[JournalLine]) -> int:
    """Return Σ amount_cents and REFUSE anything but exactly 0.

    Defense in depth: ``JournalEntry`` enforces balance at construction;
    the engine re-checks before accepting a posting. Also refuses the
    empty bundle — an entry with no lines is not an entry.

    Raises:
        UnbalancedEntryError: Σ != 0 (or no lines at all).
    """
    lines = tuple(lines)
    if not lines:
        raise UnbalancedEntryError("a journal entry needs at least one line")
    total = sum(line.amount_cents for line in lines)
    if total != 0:
        raise UnbalancedEntryError(
            f"unbalanced posting refused: Σ amount_cents = {total} "
            "(+ debit / − credit, D-3); must be exactly 0"
        )
    return total


@dataclass(frozen=True, slots=True)
class PostedEntry:
    """Immutable record of an ACCEPTED posting — the atomic engine output.

    Wraps the already-balanced :class:`JournalEntry` plus the totals of
    each side under D-3: debits are the positive lines, credits the
    negative ones. ``total_debit_cents == total_credit_cents`` always.
    """

    entry: JournalEntry
    total_debit_cents: int
    total_credit_cents: int

    @property
    def is_balanced(self) -> bool:
        """Σ lines == 0 and both side totals agree — always True for a posted entry."""
        return (
            sum(line.amount_cents for line in self.entry.lines) == 0
            and self.total_debit_cents == self.total_credit_cents
        )

    @property
    def debit_lines(self) -> tuple[JournalLine, ...]:
        """The (+) DEBIT side of the posting (D-3)."""
        return tuple(line for line in self.entry.lines if line.amount_cents > 0)

    @property
    def credit_lines(self) -> tuple[JournalLine, ...]:
        """The (−) CREDIT side of the posting (D-3)."""
        return tuple(line for line in self.entry.lines if line.amount_cents < 0)


def post(entry: JournalEntry) -> PostedEntry:
    """Post a validated :class:`JournalEntry` — pure, atomic, side-effect-free.

    Re-verifies HR-1 (Σ amount_cents == 0) even though the constructor
    already enforced it, then freezes the posting into a PostedEntry.
    Re-posting the same entry yields an equal PostedEntry every time.
    """
    validate_balanced(entry.lines)
    debit_total = sum(line.amount_cents for line in entry.lines if line.amount_cents > 0)
    credit_total = -sum(line.amount_cents for line in entry.lines if line.amount_cents < 0)
    return PostedEntry(entry=entry, total_debit_cents=debit_total, total_credit_cents=credit_total)


def post_lines(
    entry_id: str,
    entry_date: date,
    description: str,
    lines: Iterable[JournalLine],
) -> PostedEntry:
    """Construct and post an entry from raw lines in one atomic step.

    REFUSES any bundle whose Σ(amount_cents) != 0 (D-3: + debit, − credit)
    by validating BEFORE the JournalEntry is constructed — an unbalanced
    entry never exists, not even transiently; the only observable outcome
    is :class:`UnbalancedEntryError`.
    """
    validate_balanced(lines)
    return post(JournalEntry(entry_id, entry_date, description, tuple(lines)))