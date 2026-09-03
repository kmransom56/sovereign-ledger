"""Bank importer protocol + BankLine draft type (Step 6).

``BankLine`` is a DRAFT — it carries parsed identity (date, description,
amount, line hash) but has NO posted state.  Nothing here posts to the
ledger; that is Step 7's job (HR-5: nothing auto-posts from imports).

The ``BankImporter`` protocol defines the two-method contract every
format parser implements: ``detect`` (can this parser handle this file?)
and ``parse`` (return ``BankLine`` drafts).

Purity: the parsers are pure I/O-free functions over strings/bytes —
the caller reads the file and passes the content in.  No DB, no network.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol

__all__ = [
    "BankLine",
    "BankImporter",
    "ImportResult",
]


@dataclass(frozen=True, slots=True)
class BankLine:
    """One parsed bank transaction line — a DRAFT, never posted (HR-5).

    Fields:
        transaction_date: the posting date from the bank file.
        description: the memo/description from the bank file.
        amount_cents: signed integer cents (+ = deposit, − = withdrawal).
        line_hash: canonicalized per-line content hash (D-9).
        fitid: OFX FITID (None for CSV imports).
    """

    transaction_date: date
    description: str
    amount_cents: int
    line_hash: str
    fitid: str | None = None


@dataclass(frozen=True, slots=True)
class ImportResult:
    """The output of a successful import parse.

    Fields:
        lines: the parsed ``BankLine`` drafts.
        batch_hash: the canonicalized file content hash (D-9, HR-4).
        line_count: number of lines parsed.
    """

    lines: tuple[BankLine, ...]
    batch_hash: str
    line_count: int


class BankImporter(Protocol):
    """The two-method contract every format parser implements."""

    def detect(self, content: str, filename: str) -> bool:
        """Return True if this parser can handle this file."""
        ...

    def parse(self, content: str, filename: str) -> ImportResult:
        """Parse the file and return ``BankLine`` drafts."""
        ...