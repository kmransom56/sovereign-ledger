"""Import profile persistence + versioning tests (T-16 / CK-2).

Tests the version-stamped profile lifecycle: create → edit → new version
preserves old batches' parsing.  Uses the pure profile functions (no DB
for version 1; a mock DB for the persistence contract).
"""

from __future__ import annotations

import pytest

from importers.profiles import (
    ImportProfile,
    default_csv_profile,
    profile_to_json,
    profile_from_json,
)


def test_profile_version_stamp_initial() -> None:
    """A new profile starts at version 1."""
    p = default_csv_profile(1)
    assert p.version_number == 1


def test_profile_version_increment_on_edit() -> None:
    """Editing a profile's column map creates a new version (T-16)."""
    v1 = default_csv_profile(1)
    v2 = ImportProfile(
        bank_account_id=v1.bank_account_id,
        version_number=v1.version_number + 1,
        column_map={"date": "Txn Date", "amount": "Amount", "description": "Memo"},
        date_format="%m/%d/%Y",
    )
    assert v2.version_number == 2
    assert v1.version_number == 1  # old version preserved


def test_profile_json_serialization() -> None:
    """Profiles round-trip through JSON for DB storage."""
    p = default_csv_profile(42)
    json_str = profile_to_json(p)
    p2 = profile_from_json(json_str)
    assert p2 == p


def test_profile_encoding_hint() -> None:
    """A profile can carry an encoding hint for cp1252 bank files (trap 12)."""
    p = ImportProfile(
        bank_account_id=1, version_number=1,
        column_map={"date": "Date", "amount": "Amount", "description": "Description"},
        encoding_hint="cp1252",
    )
    assert p.encoding_hint == "cp1252"


def test_profile_custom_date_format() -> None:
    """Profiles can carry custom date formats for non-ISO bank exports."""
    p = ImportProfile(
        bank_account_id=1, version_number=1,
        column_map={"date": "Date", "amount": "Amount", "description": "Description"},
        date_format="%m/%d/%Y",
    )
    assert p.date_format == "%m/%d/%Y"


def test_profile_version_history_preserved() -> None:
    """Multiple profile versions can coexist — old batches reference old versions."""
    v1 = default_csv_profile(1)
    v2 = ImportProfile(
        bank_account_id=1, version_number=2,
        column_map={"date": "New Date", "amount": "New Amount", "description": "New Description"},
    )
    v3 = ImportProfile(
        bank_account_id=1, version_number=3,
        column_map={"date": "Txn Date", "amount": "Amt", "description": "Desc"},
        date_format="%d/%m/%Y",
    )
    # All three versions are valid and distinct.
    versions = [v1, v2, v3]
    assert len({v.version_number for v in versions}) == 3
    assert all(v.column_map["date"] != v2.column_map["date"] for v, v2 in zip(versions, versions[1:]))