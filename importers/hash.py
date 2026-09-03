"""Canonicalization + content hashing for bank imports (D-9, trap 7).

D-9 LOCKED DECISION: the import idempotency hash is computed over
**canonicalized** content — NEVER raw bytes.  This means:

* CRLF → LF line endings
* trailing whitespace stripped per line
* decimal amounts normalized to exactly 2 decimal places
  (``100`` → ``100.00``, ``100.0`` → ``100.00``)
* blank lines removed
* a single trailing newline appended

so the same statement re-imported under a different filename (or
re-encoded cp1252 → UTF-8) produces the same hash and is refused (HR-4).
The per-line hash applies the same normalization to a single transaction
line, deduping across overlapping statements (the same transaction in
two different monthly exports).
"""

from __future__ import annotations

import hashlib
import re
from decimal import Decimal, InvalidOperation

__all__ = [
    "canonicalize_text",
    "batch_hash",
    "line_hash",
    "normalize_amount",
]

#: Regex to strip trailing whitespace and normalize line endings.
_WS_RE = re.compile(r"[ \t]+\r?\n")
_AMOUNT_RE = re.compile(r"(-?)(\d+)(?:\.(\d*))?")


def normalize_amount(s: str) -> str:
    """Normalize a decimal amount string to exactly 2 decimal places.

    ``"100"`` → ``"100.00"``, ``"100.0"`` → ``"100.00"``,
    ``"100.00"`` → ``"100.00"``, ``"-50.5"`` → ``"-50.50"``.
    """
    s = s.strip().replace(",", "")  # strip thousands separators
    try:
        d = Decimal(s)
    except InvalidOperation:
        return s  # not a number — return as-is (let the parser decide)
    # Quantize to exactly 2 decimal places.
    return str(d.quantize(Decimal("0.01")))


def canonicalize_text(raw: str) -> str:
    """Canonicalize text for content hashing (D-9).

    Normalizations:
    * CRLF/CR → LF
    * trailing whitespace stripped per line
    * blank lines removed
    * single trailing newline

    Amount normalization is NOT applied here (it would corrupt OFX);
    it is applied per-line in :func:`line_hash` and selectively in the
    CSV parser where the amount column is known.
    """
    # CR/CRLF → LF
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    # Strip trailing whitespace per line
    lines = [line.rstrip() for line in text.split("\n")]
    # Remove blank lines
    lines = [line for line in lines if line]
    # Single trailing newline
    return "\n".join(lines) + "\n"


def batch_hash(raw: str) -> str:
    """SHA-256 of the canonicalized file content (D-9).

    The same statement re-imported under a different filename (or
    re-encoded) produces the same hash — HR-4 idempotency key.
    """
    canonical = canonicalize_text(raw)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def line_hash(
    transaction_date: str,
    description: str,
    amount: str,
    fitid: str | None = None,
) -> str:
    """SHA-256 of a canonicalized single transaction line (D-9).

    The per-line hash dedupes across overlapping statements: the same
    transaction in two monthly exports produces the same hash.  The
    amount is normalized to 2 decimal places before hashing so
    ``"100"`` and ``"100.00"`` match.
    """
    norm_amount = normalize_amount(amount)
    norm_date = transaction_date.strip()
    norm_desc = description.strip()
    if fitid:
        fitid_part = fitid.strip()
    else:
        fitid_part = ""
    preimage = f"{norm_date}|{norm_desc}|{norm_amount}|{fitid_part}"
    return hashlib.sha256(preimage.encode("utf-8")).hexdigest()