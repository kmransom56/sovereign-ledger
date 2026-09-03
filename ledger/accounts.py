"""Chart-of-accounts services for the Sovereign Ledger (CK-1, T-8 core half).

Everything the five top-level account classes and their fine-grained
``subtype`` groupings need outside persistence:

* :func:`create_account` / :func:`activate_account` /
  :func:`deactivate_account` — CoA lifecycle for the append-only
  ``accounts`` table.
* :data:`SUBTYPE_TAX_MAPPINGS` — the locked subtype → tax-mapping
  vocabulary consumed by ``tax/`` (P5: Schedule C, Form 1099).
* :func:`opening_balance_lines` / :func:`opening_balance_entry` — the
  opening-balance entry helper that loads Wave cutover balances so the
  opening trial balance nets to exactly $0.00 (CK-1, T-8).

Locked decisions honored here:

* D-3: money is signed integer USD cents (+ debit, − credit); never
  float, never ``money``.
* D-8: the ``accounts`` table is append-only — corrections are reversals;
  a status change is a NEW :class:`Account` value the caller records,
  never a mutation of a stored row.
* D-6 (trigger contract mirrored in core): ACTIVE is exactly what the
  ``is_active`` storage contract admits for posting — a non-active
  account is refused by :func:`assert_postable_account` just as the
  storage boundary refuses it.

Purity contract (hard rule 1): standard library only; no I/O of any kind;
no clock, no randomness. ``scripts/check_boundaries.py`` fails the build
if a forbidden I/O token ever appears under ``ledger/``.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from enum import Enum
from typing import Mapping

from ledger.types import AccountRef, AccountType, JournalEntry, JournalLine

__all__ = [
    "SUBTYPE_TAX_MAPPINGS",
    "OPENING_BALANCE_DESCRIPTION",
    "OPENING_BALANCE_PREFIX",
    "Account",
    "AccountError",
    "AccountInactiveError",
    "AccountStatus",
    "OpeningBalanceError",
    "account_ref",
    "activate_account",
    "assert_postable_account",
    "create_account",
    "deactivate_account",
    "known_subtypes",
    "opening_balance_entry",
    "opening_balance_lines",
    "tax_mapping_for",
    "tax_mappings_index",
]


class AccountError(ValueError):
    """Base class for chart-of-accounts domain errors."""


class AccountInactiveError(AccountError):
    """A posting touches an account that is not ACTIVE (D-6 core half)."""


class OpeningBalanceError(AccountError):
    """An opening-balance bundle cannot net to $0.00 as required (CK-1)."""


class AccountStatus(Enum):
    """Posting admission of an account — the ``is_active`` storage contract.

    ``PENDING`` exists so :func:`create_account` can hand back a value
    the caller may record first; only ACTIVE accounts accept postings.
    """

    PENDING = "pending"
    ACTIVE = "active"
    DEACTIVATED = "deactivated"


#: The locked subtype → tax-mapping vocabulary (mirrors
#: ``db/seed/chart_of_accounts.py`` and feeds ``tax/schedule_c.py``).
#: A subtype maps to a tuple of one or more return lines; an empty tuple
#: means the account class does not feed a tax-form line.
SUBTYPE_TAX_MAPPINGS: Mapping[str, tuple[str, ...]] = {
    "bank": (),
    "receivable": (),
    "payable": (),
    "credit_card": (),
    "fixed_asset": ("Form 4562",),
    "owner_equity": (),
    "owner_draws": (),
    "operating_revenue": ("Schedule C, Line 1",),
    "other_income": ("Schedule B, Part I",),
    "operating_expense": ("Schedule C, Line 18",),
    # Rent and utilities both sit in the occupancy grouping but land on
    # different Schedule C lines — hence the two-element tuple.
    "occupancy_expense": ("Schedule C, Line 20b", "Schedule C, Line 25"),
    "professional_expense": ("Schedule C, Line 17",),
}

#: Description stamped on every opening-balance entry so reports can
#: recognize the cutover load (CK-1).
OPENING_BALANCE_DESCRIPTION = "Opening balances (Wave cutover)"

#: Standard entry-id prefix for opening-balance entries (CK-1).
OPENING_BALANCE_PREFIX = "OB"


@dataclass(frozen=True, slots=True)
class Account:
    """One chart-of-accounts row — pure value object mirroring ``accounts``.

    Field mapping: ``name`` → ``name`` (UNIQUE, code-prefixed, e.g.
    ``'1000 Checking Account'``); ``type`` → ``account_type`` (the five
    CHECK classes — plural in storage, singular in the domain enum);
    ``subtype`` and ``tax_mapping`` → the like-named columns; ``status``
    → the ``is_active`` posting contract (D-6 mirrored). The frozen
    dataclass encodes the append-only model (D-8): a status or metadata
    change is a NEW value the caller records — the storage boundary
    refuses UPDATE/DELETE.

    ``__post_init__`` validates the subtype against
    :data:`SUBTYPE_TAX_MAPPINGS` and the tax mapping against the
    subtype's registered lines, so an account whose metadata points at a
    return line its grouping never feeds cannot exist.
    """

    name: str
    type: AccountType
    subtype: str
    tax_mapping: str | None = None
    status: AccountStatus = AccountStatus.PENDING

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("Account.name must be a non-empty string")
        if not isinstance(self.type, AccountType):
            raise TypeError("Account.type must be an AccountType")
        if not isinstance(self.subtype, str) or not self.subtype.strip():
            raise ValueError("Account.subtype must be a non-empty string")
        if self.tax_mapping is not None and not isinstance(self.tax_mapping, str):
            raise TypeError("Account.tax_mapping must be a str or None")
        if not isinstance(self.status, AccountStatus):
            raise TypeError("Account.status must be an AccountStatus")
        mappings = SUBTYPE_TAX_MAPPINGS.get(self.subtype)
        if mappings is None:
            raise ValueError(
                f"unknown account subtype {self.subtype!r}; known subtypes: {known_subtypes()}"
            )
        if self.tax_mapping is not None and self.tax_mapping not in mappings:
            raise ValueError(
                f"account {self.name!r}: tax_mapping {self.tax_mapping!r} is not a valid "
                f"mapping for subtype {self.subtype!r} (valid: {list(mappings)})"
            )


def known_subtypes() -> list[str]:
    """The registered subtypes, sorted — for error messages and UIs."""
    return sorted(SUBTYPE_TAX_MAPPINGS)


def account_ref(account: Account) -> AccountRef:
    """The engine-facing :class:`AccountRef` for an :class:`Account`.

    The code is the leading numeric prefix of ``name`` — the storage
    key convention (``accounts.name`` is code-prefixed and UNIQUE).
    """
    if not isinstance(account, Account):
        raise TypeError(f"account_ref expects an Account; got {type(account).__name__}")
    code = account.name.split(" ", 1)[0]
    if not code.isdigit():
        raise ValueError(
            f"account {account.name!r} has no numeric code prefix; names are code-prefixed "
            "(e.g. '1000 Checking Account')"
        )
    return AccountRef(code=code, name=account.name, type=account.type)


def create_account(
    name: str,
    account_type: AccountType,
    subtype: str,
    tax_mapping: str | None = None,
    status: AccountStatus = AccountStatus.PENDING,
) -> Account:
    """Build a NEW chart-of-accounts row value (append-only insert).

    The default PENDING status is deliberate (D-6 mirrored): an account
    becomes postable only when the caller records it as ACTIVE via
    :func:`activate_account` — the two-step storage contract.
    """
    return Account(
        name=name,
        type=account_type,
        subtype=subtype,
        tax_mapping=tax_mapping,
        status=status,
    )


def activate_account(account: Account) -> Account:
    """PENDING → ACTIVE: the account admits postings (D-6 core half)."""
    if not isinstance(account, Account):
        raise TypeError(f"activate_account expects an Account; got {type(account).__name__}")
    if account.status is not AccountStatus.PENDING:
        raise AccountError(
            f"account {account.name!r} is {account.status.value}; only a PENDING account "
            "can be activated"
        )
    return replace(account, status=AccountStatus.ACTIVE)


def deactivate_account(account: Account) -> Account:
    """ACTIVE → DEACTIVATED: future postings are refused (D-6 core half).

    Deactivation removes nothing: existing posted lines keep their
    history, mirroring the append-only storage model (D-8).
    """
    if not isinstance(account, Account):
        raise TypeError(f"deactivate_account expects an Account; got {type(account).__name__}")
    if account.status is not AccountStatus.ACTIVE:
        raise AccountError(
            f"account {account.name!r} is {account.status.value}; only an ACTIVE account "
            "can be deactivated"
        )
    return replace(account, status=AccountStatus.DEACTIVATED)


def assert_postable_account(account: Account) -> None:
    """REFUSE any posting touching a non-ACTIVE account — and NAME it.

    Raises:
        AccountInactiveError: the account is PENDING or DEACTIVATED.
    """
    if not isinstance(account, Account):
        raise TypeError(
            f"assert_postable_account expects an Account; got {type(account).__name__}"
        )
    if account.status is not AccountStatus.ACTIVE:
        raise AccountInactiveError(
            f"account {account.name!r} is {account.status.value}; posting is refused — "
            "only ACTIVE accounts admit postings"
        )


def tax_mapping_for(subtype: str) -> tuple[str, ...]:
    """The tax-form line(s) a subtype maps to (may be empty).

    Raises:
        ValueError: unknown subtype.
    """
    if not isinstance(subtype, str):
        raise TypeError(f"tax_mapping_for expects a str subtype; got {type(subtype).__name__}")
    mappings = SUBTYPE_TAX_MAPPINGS.get(subtype)
    if mappings is None:
        raise ValueError(
            f"unknown account subtype {subtype!r}; known subtypes: {known_subtypes()}"
        )
    return mappings


def tax_mappings_index() -> dict[str, tuple[str, ...]]:
    """Flattened subtype → tax lines, omitting non-tax groupings.

    Same content as :data:`SUBTYPE_TAX_MAPPINGS` minus the empty
    entries — a convenient shape for ``tax/`` to iterate.
    """
    return {subtype: mappings for subtype, mappings in SUBTYPE_TAX_MAPPINGS.items() if mappings}


# ---------------------------------------------------------------------------
# Opening-balance entry helper (CK-1 / T-8): Wave cutover balances load as
# ONE balanced entry so the opening trial balance nets to exactly $0.00.
# ---------------------------------------------------------------------------


def opening_balance_lines(
    debit_balances: Mapping[Account, int],
    credit_balances: Mapping[Account, int],
    opening_bank: Account,
) -> tuple[JournalLine, ...]:
    """Build opening-balance lines from per-account opening balances.

    ``debit_balances`` maps accounts that open with a DEBIT-normal
    balance (assets, expenses) to their opening balance in cents;
    ``credit_balances`` maps credit-normal accounts (liabilities,
    equity, income) likewise. ``opening_bank`` is the cash account that
    absorbs any residual so the bundle nets to exactly $0.00.

    Balance is by construction: Σ debits − Σ credits = residual, and a
    single cash line of −residual closes it. Balances of zero are
    skipped (a zero line is refused at the storage boundary —
    ``journal_lines_amount_domain``), and an account appearing in both
    maps is refused: its true opening balance is the signed difference,
    and silent netting would hide a data error.

    Returns:
        The balanced :class:`JournalLine` bundle (at least one line).

    Raises:
        OpeningBalanceError: the balances already net to $0.00 (nothing
            to load — an empty opening entry is refused).
    """
    if not isinstance(opening_bank, Account):
        raise TypeError(f"opening_bank must be an Account; got {type(opening_bank).__name__}")
    overlap = set(debit_balances) & set(credit_balances)
    if overlap:
        names = ", ".join(sorted(account.name for account in overlap))
        raise OpeningBalanceError(
            f"accounts appear in both debit and credit balances: {names} — "
            "net them into a single side first"
        )
    net = sum(debit_balances.values()) - sum(credit_balances.values())
    if net == 0:
        raise OpeningBalanceError(
            "opening balances already net to $0.00; there is nothing to load "
            "(an empty opening entry is refused)"
        )
    lines: list[JournalLine] = []
    for account, balance in sorted(debit_balances.items(), key=lambda item: item[0].name):
        if balance > 0:
            lines.append(JournalLine.debit(account_ref(account), balance))
    for account, balance in sorted(credit_balances.items(), key=lambda item: item[0].name):
        if balance > 0:
            lines.append(JournalLine.credit(account_ref(account), balance))
    # The cash line closes the gap; a negative residual means credits
    # outrun debits, so the cash account is DEBITED by the difference.
    residual = -net
    if residual > 0:
        lines.append(JournalLine.debit(account_ref(opening_bank), residual))
    else:
        lines.append(JournalLine.credit(account_ref(opening_bank), -residual))
    return tuple(lines)


def opening_balance_entry(
    debit_balances: Mapping[Account, int],
    credit_balances: Mapping[Account, int],
    opening_bank: Account,
    entry_date: date,
    entry_id: str | None = None,
) -> JournalEntry:
    """Construct THE opening-balance entry — guaranteed balanced (CK-1/T-8).

    The cash account absorbs the residual, so Σ amount_cents == 0 by
    construction and :class:`JournalEntry` accepts it. The description
    carries the standard cutover marker
    (:data:`OPENING_BALANCE_DESCRIPTION`); the default entry id is
    ``OB-<date>``.

    Raises:
        OpeningBalanceError: nothing to load (already nets to $0.00).
        BigIntOverflowError: a balance beyond the BIGINT ceiling.
    """
    if type(entry_date) is not date:
        raise TypeError(
            f"opening_balance_entry expects a datetime.date; got {type(entry_date).__name__}"
        )
    resolved_id = entry_id or f"{OPENING_BALANCE_PREFIX}-{entry_date.isoformat()}"
    lines = opening_balance_lines(debit_balances, credit_balances, opening_bank)
    return JournalEntry(resolved_id, entry_date, OPENING_BALANCE_DESCRIPTION, lines)