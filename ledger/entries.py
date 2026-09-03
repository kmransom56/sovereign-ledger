"""Journal-entry lifecycle for the Sovereign Ledger (HR-1/HR-2 core half).

The draft→post domain path every money flow calls:

* :func:`new_draft` — construct a reviewable draft from raw sides.
* :func:`post_draft` — THE posting gate: an entry is accepted iff it is
  balanced (HR-1), dated inside an OPEN fiscal period (HR-6) and every
  touched account is ACTIVE (D-6 mirrored).
* :func:`reversal_for` — the reversing-entry constructor (HR-2/CK-15):
  the ONLY correction mechanism, referencing the original entry id.

Locked decisions honored here:

* D-3: money is signed integer USD cents (+ debit, − credit); never
  float, never ``money``.
* D-6 (trigger contract mirrored in core): the pure core refuses what
  the storage boundary refuses — an unbalanced entry (the deferred
  trigger's rejection), an empty entry (``trg_entry_has_lines``), a zero
  line (``journal_lines_amount_domain``), a posting into a closed or
  locked period and a posting through a non-active account. Neither side
  allows what the other forbids.
* D-8: posted entries are immutable; :func:`reversal_for` produces a NEW
  entry whose lines are the exact negation of the original's, referencing
  the original entry id. The original entry value is returned untouched.
* CK-15: a reversal is dated in the OPEN correction period — which may
  differ from the original's (the May-closed/July-open scenario) — the
  original entry itself is never touched.

Purity contract (hard rule 1): standard library only; no I/O of any kind;
no clock, no randomness. ``scripts/check_boundaries.py`` fails the build
if a forbidden I/O token ever appears under ``ledger/``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Iterable, Mapping

from ledger.accounts import Account, AccountStatus, account_ref
from ledger.engine import PostedEntry, post
from ledger.periods import assert_postable
from ledger.types import JournalEntry, JournalLine

__all__ = [
    "DraftEntry",
    "EntryPostError",
    "ReversalError",
    "new_draft",
    "post_draft",
    "posted_index",
    "reversal_for",
    "reversals_index",
    "reversal_meta",
]

#: The standard description marker a reversal carries so linkage can be
#: resolved from stored entries (audit trail aid, CK-15/T-7).
REVERSAL_MARKER = "Reversal of entry "


class EntryPostError(ValueError):
    """A draft failed a posting precondition (balance, period, or account)."""


class ReversalError(ValueError):
    """A reversing entry was requested for a non-posted original."""


@dataclass(frozen=True, slots=True)
class DraftEntry:
    """A reviewable, NOT-yet-accepted journal bundle — drafts only (HR-5).

    Deliberately NOT a :class:`~ledger.types.JournalEntry`: a draft may
    be unbalanced while under construction (the debit is typed before
    the credit — legal mid-draft exactly as it is legal mid-transaction
    under the DEFERRABLE INITIALLY DEFERRED trigger, D-6). Only
    :func:`post_draft` accepts a draft, and only as a balanced whole.

    ``sides`` is a sequence of ``(account, magnitude)`` pairs; the sign
    convention is applied at construction time — magnitude ≥ 0 becomes a
    DEBIT line (+), magnitude < 0 a CREDIT line (−) of |magnitude|.

    The reversal/correction linkage (HR-2/CK-15) rides on plain fields:
    ``reverses_entry_id`` references the original entry id when this
    draft IS a reversal, ``corrects_reversal_id`` the reversal id when
    it IS the corrected re-posting — no mutable state, no metadata
    escape hatch.
    """

    draft_id: str
    entry_date: date
    description: str
    sides: tuple[tuple[Account, int], ...]
    reverses_entry_id: str | None = None
    corrects_reversal_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.draft_id, str) or not self.draft_id.strip():
            raise ValueError("DraftEntry.draft_id must be a non-empty string")
        if type(self.entry_date) is not date:
            raise TypeError(
                f"DraftEntry.entry_date must be a datetime.date; got {type(self.entry_date).__name__}"
            )
        if not isinstance(self.description, str):
            raise TypeError("DraftEntry.description must be a str")
        if self.reverses_entry_id is not None and (
            not isinstance(self.reverses_entry_id, str) or not self.reverses_entry_id.strip()
        ):
            raise ValueError("DraftEntry.reverses_entry_id must be a non-empty string or None")
        if self.corrects_reversal_id is not None and (
            not isinstance(self.corrects_reversal_id, str) or not self.corrects_reversal_id.strip()
        ):
            raise ValueError("DraftEntry.corrects_reversal_id must be a non-empty string or None")
        sides = tuple(self.sides)
        for account, magnitude in sides:
            if not isinstance(account, Account):
                raise TypeError(
                    f"DraftEntry sides must be (Account, int) pairs; got account "
                    f"{type(account).__name__}"
                )
            if isinstance(magnitude, bool) or not isinstance(magnitude, int):
                raise TypeError(
                    f"DraftEntry magnitudes must be int cents (+ debit / − credit); got "
                    f"{type(magnitude).__name__} (float money is forbidden)"
                )
        object.__setattr__(self, "sides", sides)

    def to_lines(self) -> tuple[JournalLine, ...]:
        """The engine-facing lines, zero magnitudes skipped.

        A zero side carries no information and is refused at the storage
        boundary (``journal_lines_amount_domain``) — the draft layer
        mirrors that contract by dropping it rather than passing it on.
        """
        lines: list[JournalLine] = []
        for account, magnitude in self.sides:
            if magnitude > 0:
                lines.append(JournalLine.debit(account_ref(account), magnitude))
            elif magnitude < 0:
                lines.append(JournalLine.credit(account_ref(account), -magnitude))
            # magnitude == 0: dropped, never stored
        return tuple(lines)

    @property
    def net_cents(self) -> int:
        """Σ of the raw side magnitudes — 0 means the draft is balanced."""
        return sum(magnitude for _, magnitude in self.sides)

    @property
    def is_balanced(self) -> bool:
        """True when the raw sides already net to exactly $0.00."""
        return self.net_cents == 0


def new_draft(
    draft_id: str,
    entry_date: date,
    description: str,
    sides: Iterable[tuple[Account, int]],
    *,
    reverses_entry_id: str | None = None,
    corrects_reversal_id: str | None = None,
) -> DraftEntry:
    """Construct a reviewable draft — no posting precondition checked yet.

    Accepting an unbalanced bundle is the POINT of a draft (HR-5: a
    draft is a suggestion until a human accepts); balance, period and
    account status are all enforced by :func:`post_draft`.
    """
    return DraftEntry(
        draft_id,
        entry_date,
        description,
        tuple(sides),
        reverses_entry_id,
        corrects_reversal_id,
    )


def post_draft(
    draft: DraftEntry,
    periods: Iterable[FiscalPeriod],
    accounts: Mapping[Account, AccountStatus],
    entry_id: str | None = None,
) -> PostedEntry:
    """Accept a draft as a posting — all-or-nothing, side-effect-free (HR-1).

    The acceptance gate, in order:

    1. HR-1 / D-6: the bundle must balance. An unbalanced draft is
       refused and never becomes a :class:`JournalEntry` — the entry
       does not even transiently exist, mirroring the deferred trigger's
       commit-time rollback.
    2. HR-6: the draft's date must fall inside an OPEN fiscal period;
       the refusal names the period (see
       :func:`ledger.periods.assert_postable`).
    3. D-6 mirrored: every touched account must be ACTIVE; the refusal
       names the account (see
       :func:`ledger.accounts.assert_postable_account`).
    4. The balanced entry is constructed and frozen via
       :func:`ledger.engine.post` — the atomic engine fold.

    Args:
        draft: the accepted draft.
        periods: the fiscal calendar to check the date against.
        accounts: the account catalog mapping every side's account to
            its current status (the caller persists this map).
        entry_id: override the posting id; defaults to the draft id.

    Returns:
        The frozen :class:`PostedEntry`.

    Raises:
        EntryPostError: the draft is unbalanced or has no non-zero lines.
        PeriodClosedError / UnmappedDateError: the date is not postable.
    """
    from ledger.periods import FiscalPeriod  # local import keeps the type out of __all__

    if not isinstance(draft, DraftEntry):
        raise TypeError(f"post_draft expects a DraftEntry; got {type(draft).__name__}")
    lines = draft.to_lines()
    if not lines:
        raise EntryPostError(
            f"draft {draft.draft_id!r} has no non-zero lines; nothing to post"
        )
    # HR-1 before anything else: an unbalanced draft never becomes a
    # JournalEntry — the only observable outcome is this error.
    net = sum(line.amount_cents for line in lines)
    if net != 0:
        raise EntryPostError(
            f"draft {draft.draft_id!r} is unbalanced: Σ amount_cents = {net} "
            "(+ debit / − credit, D-3); must be exactly 0"
        )
    # HR-6 before the account gate: a closed/locked-period refusal must
    # name the PERIOD even when an account would also fail — the date
    # problem is the operator-facing one.
    assert_postable(draft.entry_date, periods)
    for account in sorted({account for account, _ in draft.sides}, key=lambda a: a.name):
        status = accounts.get(account)
        if status is None:
            raise EntryPostError(
                f"account {account.name!r} is not in the posting catalog — refusing to post "
                "against an unknown account"
            )
        if status is not AccountStatus.ACTIVE:
            raise EntryPostError(
                f"account {account.name!r} is {status.value}; posting is refused — "
                "only ACTIVE accounts admit postings"
            )
    resolved_id = entry_id or draft.draft_id
    return post(JournalEntry(resolved_id, draft.entry_date, draft.description, lines))


def reversal_for(
    original: JournalEntry,
    reversal_id: str,
    reversal_date: date,
    periods: Iterable["FiscalPeriod"],
) -> JournalEntry:
    """Construct the reversing entry for a POSTED entry (HR-2 / CK-15).

    The ONLY correction mechanism: the reversal's lines are the exact
    negation of the original's (every debit becomes a credit and vice
    versa, same accounts, same magnitudes — Σ still 0), the original
    entry id is referenced in the description (resolvable by
    :func:`reversals_index`), and the original entry value is returned
    untouched — stored history is immutable (HR-2).

    CK-15 (reversals post into the OPEN period): the reversal date may
    be in a different period than the original — the classic May-closed /
    July-open correction — but THAT period must be OPEN; a reversal
    dated into a closed or locked period is refused with the period
    named (HR-6).

    Args:
        original: the posted entry being reversed.
        reversal_id: the reversal's own entry id.
        reversal_date: the OPEN-period date the reversal posts into.
        periods: the fiscal calendar.

    Returns:
        The NEW reversing :class:`JournalEntry`.

    Raises:
        ReversalError: ``original`` is not a balanced (posted) entry.
        PeriodClosedError / UnmappedDateError: the reversal date is not
            in an OPEN period.
    """
    if not isinstance(original, JournalEntry):
        raise TypeError(f"reversal_for expects a JournalEntry; got {type(original).__name__}")
    if not isinstance(reversal_id, str) or not reversal_id.strip():
        raise ValueError("reversal_id must be a non-empty string")
    if type(reversal_date) is not date:
        raise TypeError(
            f"reversal_date must be a datetime.date; got {type(reversal_date).__name__}"
        )
    # A posted entry is balanced by construction; a non-balanced value
    # cannot have been posted, so refusing here mirrors HR-2 exactly.
    original_net = sum(line.amount_cents for line in original.lines)
    if original_net != 0:
        raise ReversalError(
            f"entry {original.entry_id!r} is not balanced (Σ = {original_net}); "
            "only a posted entry can be reversed"
        )
    assert_postable(reversal_date, periods)  # HR-6: names the period
    description = f"{REVERSAL_MARKER}{original.entry_id}: {original.description}"
    lines = tuple(JournalLine(line.account, -line.amount_cents) for line in original.lines)
    return JournalEntry(reversal_id, reversal_date, description, lines)


def reversal_meta(entry: JournalEntry) -> dict[str, str]:
    """The reversal linkage metadata for an entry (audit trail aid).

    A reversal (description carrying the standard marker) yields
    ``{"reverses": <original id>, "entry_id": <this id>}``; any other
    entry yields just ``{"entry_id": <id>}``.
    """
    if not isinstance(entry, JournalEntry):
        raise TypeError(f"reversal_meta expects a JournalEntry; got {type(entry).__name__}")
    if entry.description.startswith(REVERSAL_MARKER):
        original_id = entry.description.split(":", 1)[0].removeprefix(REVERSAL_MARKER).strip()
        return {"reverses": original_id, "entry_id": entry.entry_id}
    return {"entry_id": entry.entry_id}


def posted_index(entries: Iterable[JournalEntry]) -> dict[str, JournalEntry]:
    """Entries keyed by entry id — the reference map reversal links point at."""
    index: dict[str, JournalEntry] = {}
    for entry in entries:
        if not isinstance(entry, JournalEntry):
            raise TypeError(
                f"posted_index expects JournalEntry values; got {type(entry).__name__}"
            )
        if entry.entry_id in index:
            raise EntryPostError(
                f"duplicate entry id {entry.entry_id!r}; entry ids must be unique"
            )
        index[entry.entry_id] = entry
    return index


def reversals_index(entries: Iterable[JournalEntry]) -> dict[str, str]:
    """Map every reversal entry id → the original entry id it references.

    Entries whose description carries the standard reversal marker
    (see :func:`reversal_for`) are included; everything else is skipped.
    """
    index: dict[str, str] = {}
    for entry in entries:
        if not isinstance(entry, JournalEntry):
            raise TypeError(
                f"reversals_index expects JournalEntry values; got {type(entry).__name__}"
            )
        if entry.description.startswith(REVERSAL_MARKER):
            original_id = entry.description.split(":", 1)[0].removeprefix(REVERSAL_MARKER).strip()
            index[entry.entry_id] = original_id
    return index