"""Bank importer unit tests (Step 6 — parsing, charset, canonicalization).

Tests the pure parsing functions: CSV column mapping, date/amount
parsing, charset sniffing, canonicalization, and the BankLine draft type.
No I/O, no DB.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from importers.base import BankLine, ImportResult
from importers.csv_generic import parse_csv, CSVImporter
from importers.hash import canonicalize_text, batch_hash, line_hash, normalize_amount
from importers.profiles import ImportProfile, default_csv_profile, profile_to_json, profile_from_json


# ---------------------------------------------------------------------------
# Canonicalization + hashing (D-9)
# ---------------------------------------------------------------------------


def test_normalize_amount() -> None:
    assert normalize_amount("100") == "100.00"
    assert normalize_amount("100.0") == "100.00"
    assert normalize_amount("100.00") == "100.00"
    assert normalize_amount("-50.5") == "-50.50"
    assert normalize_amount("1,234.50") == "1234.50"  # thousands sep stripped


def test_canonicalize_text_crlf_to_lf() -> None:
    raw = "line1\r\nline2\r\n"
    assert canonicalize_text(raw) == "line1\nline2\n"


def test_canonicalize_strips_trailing_ws() -> None:
    raw = "line1   \nline2\t\n"
    assert canonicalize_text(raw) == "line1\nline2\n"


def test_canonicalize_removes_blank_lines() -> None:
    raw = "a\n\n\nb\n"
    assert canonicalize_text(raw) == "a\nb\n"


def test_batch_hash_same_under_renaming() -> None:
    """The same content produces the same hash regardless of filename."""
    content = "Date,Amount,Description\n2026-01-15,100.00,Test\n"
    h1 = batch_hash(content)
    h2 = batch_hash(content)
    assert h1 == h2
    assert len(h1) == 64  # SHA-256 hex


def test_batch_hash_different_under_content_change() -> None:
    content1 = "Date,Amount,Description\n2026-01-15,100.00,Test\n"
    content2 = "Date,Amount,Description\n2026-01-15,200.00,Test\n"
    assert batch_hash(content1) != batch_hash(content2)


def test_batch_hash_crlf_vs_lf_same() -> None:
    """CRLF and LF versions of the same content hash identically (D-9)."""
    crlf = "line1\r\nline2\r\n"
    lf = "line1\nline2\n"
    assert batch_hash(crlf) == batch_hash(lf)


def test_line_hash_same_under_amount_normalization() -> None:
    """100, 100.0, and 100.00 produce the same line hash (D-9)."""
    h1 = line_hash("2026-01-15", "Test", "100")
    h2 = line_hash("2026-01-15", "Test", "100.0")
    h3 = line_hash("2026-01-15", "Test", "100.00")
    assert h1 == h2 == h3


def test_line_hash_distinguishes_different_descriptions() -> None:
    h1 = line_hash("2026-01-15", "Coffee", "5.00")
    h2 = line_hash("2026-01-15", "Tea", "5.00")
    assert h1 != h2


def test_line_hash_with_fitid() -> None:
    h1 = line_hash("2026-01-15", "Test", "100.00", fitid="ABC123")
    h2 = line_hash("2026-01-15", "Test", "100.00", fitid="ABC123")
    h3 = line_hash("2026-01-15", "Test", "100.00", fitid=None)
    assert h1 == h2
    assert h1 != h3  # FITID changes the hash


# ---------------------------------------------------------------------------
# CSV parsing
# ---------------------------------------------------------------------------

PROFILE = ImportProfile(
    bank_account_id=1,
    version_number=1,
    column_map={"date": "Date", "amount": "Amount", "description": "Description"},
    date_format="%Y-%m-%d",
)


def test_csv_parse_basic() -> None:
    content = "Date,Amount,Description\n2026-01-15,100.00,Deposit\n2026-01-16,-50.00,Coffee\n"
    result = parse_csv(content, PROFILE)
    assert result.line_count == 2
    assert len(result.lines) == 2
    assert result.lines[0].transaction_date == date(2026, 1, 15)
    assert result.lines[0].amount_cents == 10000
    assert result.lines[0].description == "Deposit"
    assert result.lines[1].amount_cents == -5000
    assert result.lines[1].description == "Coffee"


def test_csv_parse_strips_dollar_signs() -> None:
    content = 'Date,Amount,Description\n2026-01-15,"$1,234.50",Test\n'
    result = parse_csv(content, PROFILE)
    assert result.lines[0].amount_cents == 123450


def test_csv_parse_sub_cent_rejected() -> None:
    content = "Date,Amount,Description\n2026-01-15,100.999,Test\n"
    with pytest.raises(ValueError, match="sub-cent"):
        parse_csv(content, PROFILE)


def test_csv_parse_bad_date() -> None:
    content = "Date,Amount,Description\n15/01/2026,100.00,Test\n"
    with pytest.raises(ValueError, match="date"):
        parse_csv(content, PROFILE)


def test_csv_parse_missing_column() -> None:
    content = "Date,Desc,Amount\n2026-01-15,Test,100.00\n"
    with pytest.raises(ValueError, match="not in the CSV header"):
        parse_csv(content, PROFILE)


def test_csv_parse_skips_blank_rows() -> None:
    content = "Date,Amount,Description\n2026-01-15,100.00,Test\n,,\n2026-01-16,-50.00,Coffee\n"
    result = parse_csv(content, PROFILE)
    assert result.line_count == 2


def test_csv_parse_empty_file() -> None:
    content = "Date,Amount,Description\n"
    result = parse_csv(content, PROFILE)
    assert result.line_count == 0
    assert result.lines == ()


def test_csv_importer_detect_protocol() -> None:
    importer = CSVImporter(PROFILE)
    assert importer.detect("Date,Amount\n", "test.csv") is True
    assert importer.detect("<OFX>", "test.ofx") is False


def test_csv_parse_line_hashes_unique() -> None:
    content = "Date,Amount,Description\n2026-01-15,100.00,Test\n2026-01-16,-50.00,Coffee\n"
    result = parse_csv(content, PROFILE)
    hashes = [line.line_hash for line in result.lines]
    assert len(set(hashes)) == 2  # all unique


def test_csv_parse_amount_variations_same_hash() -> None:
    """100, 100.0, and 100.00 in the amount column hash the same line."""
    p = ImportProfile(
        bank_account_id=1, version_number=1,
        column_map={"date": "D", "amount": "A", "description": "X"},
    )
    content1 = "D,A,X\n2026-01-15,100,Test\n"
    content2 = "D,A,X\n2026-01-15,100.00,Test\n"
    r1 = parse_csv(content1, p)
    r2 = parse_csv(content2, p)
    assert r1.lines[0].line_hash == r2.lines[0].line_hash


# ---------------------------------------------------------------------------
# Profiles (CK-2 / T-16)
# ---------------------------------------------------------------------------


def test_profile_default() -> None:
    p = default_csv_profile(42)
    assert p.bank_account_id == 42
    assert p.version_number == 1
    assert "date" in p.column_map


def test_profile_requires_required_keys() -> None:
    with pytest.raises(ValueError, match="missing required keys"):
        ImportProfile(
            bank_account_id=1, version_number=1,
            column_map={"date": "D", "amount": "A"},  # missing description
        )


def test_profile_version_must_be_positive() -> None:
    with pytest.raises(ValueError, match="version_number"):
        ImportProfile(
            bank_account_id=1, version_number=0,
            column_map={"date": "D", "amount": "A", "description": "X"},
        )


def test_profile_json_roundtrip() -> None:
    p = default_csv_profile(1)
    json_str = profile_to_json(p)
    p2 = profile_from_json(json_str)
    assert p2.bank_account_id == p.bank_account_id
    assert p2.version_number == p.version_number
    assert p2.column_map == p.column_map
    assert p2.date_format == p.date_format


def test_profile_new_version_preserves_old() -> None:
    """Editing a profile creates a new version; old is preserved (T-16)."""
    v1 = default_csv_profile(1)
    v2 = ImportProfile(
        bank_account_id=1,
        version_number=2,
        column_map={"date": "Transaction Date", "amount": "Amount", "description": "Memo"},
        date_format="%m/%d/%Y",
    )
    assert v1.version_number == 1
    assert v2.version_number == 2
    # The old profile's column map is untouched.
    assert v1.column_map["date"] == "Date"
    assert v2.column_map["date"] == "Transaction Date"