"""QFX/OFX bank statement importer via ofxtools 1.1.1 (Step 6, F-1).

Parses OFX/QFX statements using ofxtools (NOT ofxparse — F-1: ofxparse
is abandoned, repo 404).  Transactions are keyed on the bank's FITID
for per-line deduplication across overlapping statements (D-9).

The parser is pure: it takes file content (str) and returns ``BankLine``
drafts.  No I/O, no DB, no posting (HR-5).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from importers.base import BankLine, ImportResult
from importers.hash import batch_hash, line_hash

__all__ = ["OFXImporter", "parse_ofx"]


def parse_ofx(content: str) -> ImportResult:
    """Parse an OFX/QFX statement into ``BankLine`` drafts.

    Uses ofxtools 1.1.1 for robust OFX 1.x/2.x parsing.  Transactions
    are keyed on FITID for cross-statement deduplication (D-9).

    Args:
        content: the OFX file content as a string.

    Returns:
        An :class:`ImportResult` with parsed lines + batch hash.

    Raises:
        ValueError: the OFX content is unparseable or a transaction
            has sub-cent precision.
    """
    from ofxtools import OFXTree

    tree = OFXTree()
    try:
        tree.parse(io_source(content))
    except Exception as exc:
        raise ValueError(f"OFX parse failed: {exc}") from exc

    ofx = tree.convert()

    lines: list[BankLine] = []
    for stmt in ofx.statements:
        for txn in getattr(stmt, "transactions", []) or []:
            txn_date = getattr(txn, "dtpost", None)
            if txn_date is None:
                continue
            if hasattr(txn_date, "date"):
                txn_date = txn_date.date()

            amount = getattr(txn, "trnamt", Decimal("0"))
            if not isinstance(amount, Decimal):
                amount = Decimal(str(amount))

            scaled = amount * 100
            if scaled != scaled.to_integral_value():
                raise ValueError(
                    f"OFX transaction on {txn_date}: amount {amount} has "
                    "sub-cent precision (exactly 2 decimal places required — trap 8)"
                )
            amount_cents = int(scaled)

            description = (
                getattr(txn, "name", "")
                or getattr(txn, "memo", "")
                or ""
            ).strip()

            fitid = getattr(txn, "fitid", None)
            if fitid is not None:
                fitid = str(fitid).strip()

            date_str = txn_date.isoformat() if hasattr(txn_date, "isoformat") else str(txn_date)

            lh = line_hash(
                transaction_date=date_str,
                description=description,
                amount=str(amount),
                fitid=fitid,
            )

            lines.append(BankLine(
                transaction_date=txn_date if isinstance(txn_date, date) else date.today(),
                description=description,
                amount_cents=amount_cents,
                line_hash=lh,
                fitid=fitid,
            ))

    bh = batch_hash(content)
    return ImportResult(
        lines=tuple(lines),
        batch_hash=bh,
        line_count=len(lines),
    )


class _StringSource:
    """Adapter so ofxtools' OFXTree.parse can read from a string."""

    def __init__(self, content: str) -> None:
        self._buf = content.encode("utf-8")

    def read(self, size: int = -1) -> bytes:
        if size == -1:
            data = self._buf
            self._buf = b""
            return data
        data = self._buf[:size]
        self._buf = self._buf[size:]
        return data


def io_source(content: str) -> _StringSource:
    """Create a file-like object from a string for ofxtools."""
    return _StringSource(content)


class OFXImporter:
    """OFX/QFX bank importer — the ``BankImporter`` protocol implementation."""

    def detect(self, content: str, filename: str) -> bool:
        """OFX files are detected by extension or OFX header content."""
        fname = filename.lower()
        if fname.endswith((".ofx", ".qfx")):
            return True
        # Check for OFX header: "OFXHEADER:" appears early in the file.
        return "OFXHEADER:" in content[:200] if content else False

    def parse(self, content: str, filename: str) -> ImportResult:
        """Parse the OFX content."""
        return parse_ofx(content)