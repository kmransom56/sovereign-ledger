"""Import idempotency tests (T-2 / HR-4) — same file twice → zero duplicates.

Tests the content-hash idempotency mechanism: the same statement file
re-imported under a different filename must produce the same batch_hash
and be detected as a duplicate.  This is the core HR-4 test.

These tests use the pure parsing functions (no DB) to verify the
hash-level idempotency; the DB-level idempotency (import_batches
content_hash UNIQUE constraint) is tested via the e2e suite in Step 7.
"""

from __future__ import annotations

import pytest

from importers.csv_generic import parse_csv
from importers.hash import batch_hash, line_hash, normalize_amount
from importers.profiles import ImportProfile, default_csv_profile

PROFILE = default_csv_profile(1)


STATEMENT_1 = """Date,Amount,Description
2026-01-15,1000.00,Deposit
2026-01-16,-50.00,Coffee Shop
2026-01-17,-125.00,Grocery Store
2026-01-18,500.00,Transfer
"""

STATEMENT_1_RENAMED = STATEMENT_1  # same content, different filename

STATEMENT_1_CRLF = STATEMENT_1.replace("\n", "\r\n")

STATEMENT_1_DIFFERENT = """Date,Amount,Description
2026-01-15,1000.00,Deposit
2026-01-16,-50.00,Coffee Shop
2026-01-17,-125.00,Grocery Store
2026-01-18,600.00,Transfer
"""


def test_same_content_same_hash_different_filename() -> None:
    """T-2/HR-4: same statement under different filename → same hash."""
    h1 = batch_hash(STATEMENT_1)
    h2 = batch_hash(STATEMENT_1_RENAMED)
    assert h1 == h2


def test_crlf_vs_lf_same_hash() -> None:
    """CRLF and LF versions hash identically (D-9 canonicalization)."""
    h_lf = batch_hash(STATEMENT_1)
    h_crlf = batch_hash(STATEMENT_1_CRLF)
    assert h_lf == h_crlf


def test_different_content_different_hash() -> None:
    """A changed amount produces a different hash."""
    h1 = batch_hash(STATEMENT_1)
    h2 = batch_hash(STATEMENT_1_DIFFERENT)
    assert h1 != h2


def test_parsed_lines_same_under_crlf() -> None:
    """Parsing CRLF vs LF content produces the same BankLines."""
    r1 = parse_csv(STATEMENT_1, PROFILE)
    r2 = parse_csv(STATEMENT_1_CRLF, PROFILE)
    assert r1.line_count == r2.line_count
    for l1, l2 in zip(r1.lines, r2.lines):
        assert l1.line_hash == l2.line_hash
        assert l1.amount_cents == l2.amount_cents


def test_parsed_lines_same_batch_hash_under_crlf() -> None:
    """The batch_hash is the same for CRLF and LF content."""
    r1 = parse_csv(STATEMENT_1, PROFILE)
    r2 = parse_csv(STATEMENT_1_CRLF, PROFILE)
    assert r1.batch_hash == r2.batch_hash


def test_per_line_hashes_dedupe_across_statements() -> None:
    """The same transaction in two overlapping exports has the same line hash."""
    stmt_a = """Date,Amount,Description
2026-01-15,1000.00,Deposit
2026-01-16,-50.00,Coffee Shop
"""
    stmt_b = """Date,Amount,Description
2026-01-16,-50.00,Coffee Shop
2026-01-17,-125.00,Grocery Store
"""
    r_a = parse_csv(stmt_a, PROFILE)
    r_b = parse_csv(stmt_b, PROFILE)

    # The "Coffee Shop" line appears in both statements.
    coffee_a = next(l for l in r_a.lines if "Coffee" in l.description)
    coffee_b = next(l for l in r_b.lines if "Coffee" in l.description)

    # Same line hash → cross-statement deduplication key (D-9).
    assert coffee_a.line_hash == coffee_b.line_hash


def test_amount_variations_same_line_hash() -> None:
    """100, 100.0, 100.00 all normalize to the same line hash."""
    h1 = line_hash("2026-01-15", "Test", "100")
    h2 = line_hash("2026-01-15", "Test", "100.0")
    h3 = line_hash("2026-01-15", "Test", "100.00")
    assert h1 == h2 == h3


def test_reimport_produces_zero_new_lines() -> None:
    """T-2 core: re-importing the same content produces the same batch_hash.

    The DB-level idempotency (import_batches UNIQUE on content_hash) is
    tested in the e2e suite; here we verify the hash-level mechanism
    that the DB constraint relies on.
    """
    r1 = parse_csv(STATEMENT_1, PROFILE)
    r2 = parse_csv(STATEMENT_1, PROFILE)  # re-import
    assert r1.batch_hash == r2.batch_hash
    assert r1.line_count == r2.line_count
    # All line hashes match.
    for l1, l2 in zip(r1.lines, r2.lines):
        assert l1.line_hash == l2.line_hash