"""Sovereign Ledger pure domain core — hard rule 1: zero I/O.

Nothing under ``ledger/`` may import web frameworks, database drivers, or
HTTP clients; ``scripts/check_boundaries.py`` fails the build on any
violation under ``ledger/`` or ``reports/``. Persistence is the caller's
job (adapters in ``app/``, ``importers/``, ``scripts/``).

SIGN CONVENTION — locked decision D-3, load-bearing for every later step:

    amount_cents > 0   →  DEBIT   (+)
    amount_cents < 0   →  CREDIT  (−)

Money is signed integer USD cents, BIGINT-safe (see ``BIGINT_MAX_CENTS``).
The convention is encoded structurally: ``JournalLine.debit`` /
``JournalLine.credit`` construct lines from magnitudes, and
``AccountType.normal_balance_sign`` states each account class's normal
side. Property tests in ``tests/test_engine.py`` pin it.
"""

from ledger.engine import PostedEntry, post, post_lines, validate_balanced
from ledger.types import (
    BIGINT_MAX_CENTS,
    AccountRef,
    AccountType,
    BigIntOverflowError,
    JournalEntry,
    JournalLine,
    Money,
    UnbalancedEntryError,
    cents_from_decimal,
)

__all__ = [
    "BIGINT_MAX_CENTS",
    "AccountRef",
    "AccountType",
    "BigIntOverflowError",
    "JournalEntry",
    "JournalLine",
    "Money",
    "PostedEntry",
    "UnbalancedEntryError",
    "cents_from_decimal",
    "post",
    "post_lines",
    "validate_balanced",
]