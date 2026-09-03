"""Generic CSV bank statement importer (Step 6, trap 8).

Parses a bank CSV export using a versioned profile's column mapping.
The profile maps field names (date, amount, description) to column
headers in the CSV.  Amounts are parsed via Decimal → validate 2dp →
integer cents (trap 8: never float money).

The parser is pure: it takes the file content (str) and a profile, and
returns ``BankLine`` drafts.  No I/O, no DB, no posting (HR-5).
"""

from __future__ import annotations

import csv
import io
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from importers.base import BankLine, ImportResult
from importers.hash import batch_hash, line_hash, normalize_amount
from importers.profiles import ImportProfile

__all__ = ["CSVImporter", "parse_csv"]


def _detect_encoding(raw_bytes: bytes, hint: str | None = None) -> str:
    """Detect encoding via charset-normalizer (trap 12) or use the hint."""
    if hint:
        return hint
    try:
        from charset_normalizer import from_bytes
        result = from_bytes(raw_bytes)
        if result.best():
            return result.best().encoding
    except ImportError:
        pass
    return "utf-8"


def parse_csv(content: str, profile: ImportProfile) -> ImportResult:
    """Parse a CSV bank export into ``BankLine`` drafts.

    Args:
        content: the file content as a string (already decoded).
        profile: the versioned column-mapping profile.

    Returns:
        An :class:`ImportResult` with parsed lines + batch hash.

    Raises:
        ValueError: a required column is missing, a date/amount is
            unparseable, or the amount has sub-cent precision.
    """
    reader = csv.DictReader(io.StringIO(content))

    # Validate required columns exist in the CSV header.
    headers = {h.strip() for h in (reader.fieldnames or [])}
    col = profile.column_map
    for field in ("date", "amount", "description"):
        col_name = col[field]
        if col_name not in headers and str(col_name) not in headers:
            raise ValueError(
                f"profile column map expects {field!r} column {col_name!r} "
                f"but it is not in the CSV header: {sorted(headers)}"
            )

    lines: list[BankLine] = []
    for i, row in enumerate(reader, start=2):
        # Skip blank rows.
        if not any(v and v.strip() for v in row.values()):
            continue

        date_str = (row.get(col["date"]) or "").strip()
        amount_str = (row.get(col["amount"]) or "").strip()
        desc_str = (row.get(col["description"]) or "").strip()

        if not date_str or not amount_str:
            continue  # skip incomplete rows

        # Parse date.
        try:
            txn_date = datetime.strptime(date_str, profile.date_format).date()
        except ValueError:
            raise ValueError(
                f"row {i}: date {date_str!r} does not match format {profile.date_format!r}"
            )

        # Parse amount: Decimal → validate 2dp → integer cents (trap 8).
        try:
            amount_clean = amount_str.replace(",", "").replace("$", "").strip()
            if not amount_clean:
                continue
            d = Decimal(amount_clean)
        except InvalidOperation:
            raise ValueError(f"row {i}: invalid amount {amount_str!r}")

        scaled = d * 100
        if scaled != scaled.to_integral_value():
            raise ValueError(
                f"row {i}: amount {amount_str!r} has sub-cent precision "
                "(exactly 2 decimal places required — trap 8)"
            )
        amount_cents = int(scaled)

        # Compute per-line hash (D-9).
        lh = line_hash(
            transaction_date=date_str,
            description=desc_str,
            amount=amount_str,
        )

        lines.append(BankLine(
            transaction_date=txn_date,
            description=desc_str,
            amount_cents=amount_cents,
            line_hash=lh,
            fitid=None,
        ))

    bh = batch_hash(content)
    return ImportResult(
        lines=tuple(lines),
        batch_hash=bh,
        line_count=len(lines),
    )


class CSVImporter:
    """CSV bank importer — the ``BankImporter`` protocol implementation."""

    def __init__(self, profile: ImportProfile) -> None:
        self.profile = profile

    def detect(self, content: str, filename: str) -> bool:
        """CSV files are detected by extension or comma-separated content."""
        return filename.lower().endswith(".csv") or (
            "," in content.split("\n", 1)[0] if content else False
        )

    def parse(self, content: str, filename: str) -> ImportResult:
        """Parse the CSV content using the profile."""
        return parse_csv(content, self.profile)