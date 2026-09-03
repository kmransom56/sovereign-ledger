"""Version-stamped per-account import profiles (CK-2 / trap 12).

A profile maps column names to fields (date, amount, description) and
carries a date format and optional encoding hint.  Profiles are
version-stamped: editing a profile creates a new version_number so old
import batches retain the version that parsed them — a bank layout
change never silently re-maps old imports (trap 12, T-16).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "ImportProfile",
    "default_csv_profile",
    "profile_to_json",
    "profile_from_json",
]


@dataclass(frozen=True, slots=True)
class ImportProfile:
    """A versioned column-mapping profile for a bank account (CK-2/T-16).

    Fields:
        bank_account_id: the DB id of the bank account this profile maps.
        version_number: the version stamp (incremented on edit).
        column_map: {field_name: column_name_or_index} mapping.
            Required keys: "date", "amount", "description".
            Optional keys: "memo", "fitid" (OFX only).
        date_format: strptime format for the date column (default '%Y-%m-%d').
        encoding_hint: explicit encoding (e.g. 'cp1252') or None to auto-sniff.
    """

    bank_account_id: int
    version_number: int
    column_map: dict[str, str]
    date_format: str = "%Y-%m-%d"
    encoding_hint: str | None = None

    def __post_init__(self) -> None:
        required = {"date", "amount", "description"}
        missing = required - set(self.column_map)
        if missing:
            raise ValueError(
                f"ImportProfile.column_map is missing required keys: {sorted(missing)}"
            )
        if self.version_number < 1:
            raise ValueError("ImportProfile.version_number must be >= 1")


def default_csv_profile(bank_account_id: int) -> ImportProfile:
    """A sensible default profile for a generic bank CSV export."""
    return ImportProfile(
        bank_account_id=bank_account_id,
        version_number=1,
        column_map={
            "date": "Date",
            "amount": "Amount",
            "description": "Description",
        },
        date_format="%Y-%m-%d",
        encoding_hint=None,
    )


def profile_to_json(profile: ImportProfile) -> str:
    """Serialize a profile to JSON for DB storage."""
    return json.dumps({
        "bank_account_id": profile.bank_account_id,
        "version_number": profile.version_number,
        "column_map": profile.column_map,
        "date_format": profile.date_format,
        "encoding_hint": profile.encoding_hint,
    })


def profile_from_json(data: str) -> ImportProfile:
    """Deserialize a profile from JSON."""
    obj = json.loads(data)
    return ImportProfile(
        bank_account_id=obj["bank_account_id"],
        version_number=obj["version_number"],
        column_map=obj["column_map"],
        date_format=obj.get("date_format", "%Y-%m-%d"),
        encoding_hint=obj.get("encoding_hint"),
    )