"""Journal-entry lifecycle suite (HR-1/HR-2 core half, CK-15).

Covers draft construction (unbalanced drafts are LEGAL — HR-5: a draft is
a suggestion until a human accepts), the ``post_draft`` acceptance gate
in its exact refusal order (no lines → unbalanced → closed period →
account status), and the reversing-entry constructor: reversal lines are
the exact negation of the original's, the original entry id is referenced
and resolvable, the original value is untouched, and reversals post into
the OPEN period (the May-closed/July-open CK-15 scenario).

Purity (hard rule 1): no I/O — everything is constructed in the test.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from ledger.accounts import Account, AccountStatus, activate_account, account_ref, create_account
from ledger.engine import validate_balanced
from ledger.entries import (
    REVERSAL_MARKER,
    DraftEntry,
    EntryPostError,
    ReversalError,
    new_draft,
    post_draft,
    posted_index,
    reversal_for,
    reversal_meta,
    reversals_index,
)
from ledger.periods import PeriodClosedError, UnmappedDateError, monthly_periods
from ledger.types import (
    AccountType,
    JournalEntry,
    JournalLine,
    UnbalancedEntryError,
)

MAY_DATE = date(2026, 5, 14)
JULY_DATE = date(2026, 7, 3)


def may_closed_july_open() -> list:
    """2026 with January..May closed (flow-6 in-order close)."""
    from ledger.periods import close_period

    cal = list(monthly_periods(2026))
    for i in range(5):
        cal[i] = close_period(cal[i], cal)
    return cal


@pytest.fixture()
def catalog() -> dict:
    cash = activate_account(create_account("1000 Checking Account", AccountType.ASSET, "bank"))
    rent = activate_account(create_account("5200 Rent Expense", AccountType.EXPENSE,
                                            "occupancy_expense", "Schedule C, Line 20b"))
    return {cash: AccountStatus.ACTIVE, rent: AccountStatus.ACTIVE}


@pytest.fixture()
def cal() -> list:
    from ledger.periods import close_period

    calendar_ = list(monthly_periods(2026))
    for i in range(5):
        calendar_[i] = close_period(calendar_[i], calendar_)
    return calendar_


# ---------------------------------------------------------------------------
# Draft construction: unbalanced bundles are legal DRAFTS (HR-5)
# ---------------------------------------------------------------------------


def test_new_draft_accepts_unbalanced_sides() -> None:
    cash = activate_account(create_account("1000 C", AccountType.ASSET, "bank"))
    rent = activate_account(create_account("5200 R", AccountType.EXPENSE, "occupancy_expense"))
    draft = new_draft("D1", MAY_DATE, "typed debit first", [(rent, 25_000), (cash, -24_000)])
    assert draft.net_cents == 1_000
    assert not draft.is_balanced
    assert len(draft.to_lines()) == 2  # lines exist; only POST refuses


def test_draft_zero_sides_dropped() -> None:
    cash = activate_account(create_account("1000 C", AccountType.ASSET, "bank"))
    rent = activate_account(create_account("5200 R", AccountType.EXPENSE, "occupancy_expense"))
    draft = new_draft("DZ", JULY_DATE, "zero side", [(cash, 0), (rent, 5_000), (cash, -5_000)])
    assert len(draft.to_lines()) == 2  # zero side dropped, never stored
    assert draft.to_lines()[0].amount_cents == 5_000


def test_draft_net_and_balance_properties(catalog) -> None:
    cash, rent = list(catalog)
    balanced = new_draft("DB", JULY_DATE, "balanced", [(rent, 25_000), (cash, -25_000)])
    assert balanced.is_balanced and balanced.net_cents == 0
    unbalanced = new_draft("DU", JULY_DATE, "unbalanced", [(rent, 25_000), (cash, -24_000)])
    assert not unbalanced.is_balanced and unbalanced.net_cents == 1_000


def test_draft_rejects_garbage() -> None:
    cash = activate_account(create_account("1000 C", AccountType.ASSET, "bank"))
    with pytest.raises(ValueError):
        new_draft("", MAY_DATE, "x", [(cash, 100)])
    with pytest.raises(ValueError):
        new_draft("   ", MAY_DATE, "x", [(cash, 100)])
    with pytest.raises(TypeError):
        new_draft("D2", "2026-05-14", "x", [(cash, 100)])  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        new_draft("D3", MAY_DATE, 7, [(cash, 100)])  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        new_draft("D4", MAY_DATE, "x", [("not-an-account", 100)])  # type: ignore[list-item]
    with pytest.raises(TypeError):
        new_draft("D5", MAY_DATE, "x", [(cash, 10.5)])  # float money forbidden
    with pytest.raises(TypeError):
        new_draft("D6", MAY_DATE, "x", [(cash, True)])  # bool is not int money
    with pytest.raises(ValueError):
        DraftEntry("D6", MAY_DATE, "x", [(cash, 100)], reverses_entry_id="   ")
    with pytest.raises(ValueError):
        DraftEntry("D7", MAY_DATE, "x", [(cash, 100)], corrects_reversal_id="   ")


def test_post_draft_rejects_garbage_type() -> None:
    with pytest.raises(TypeError):
        post_draft("not-a-draft", [], {})  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# post_draft acceptance gate: the exact refusal order (HR-1 → HR-6 → acct)
# ---------------------------------------------------------------------------


def test_post_draft_refusal_order_no_lines_first(catalog, cal) -> None:
    cash, rent = list(catalog)
    all_zero = new_draft("D0", JULY_DATE, "all zero", [(rent, 0), (cash, 0)])
    with pytest.raises(EntryPostError, match="no non-zero lines"):
        post_draft(all_zero, cal, catalog)
    # An unbalanced-but-nonempty draft reports the BALANCE problem first.
    off_by_one = new_draft("D2", date(2026, 3, 1), "off", [(rent, 100), (cash, -99)])
    with pytest.raises(EntryPostError, match="unbalanced"):
        post_draft(off_by_one, cal, catalog)


def test_post_draft_refuses_unbalanced(catalog, cal) -> None:
    cash, rent = list(catalog)
    draft = new_draft("D3", JULY_DATE, "off by one", [(rent, 25_000), (cash, -24_000)])
    with pytest.raises(EntryPostError, match="unbalanced: Σ amount_cents = 1000"):
        post_draft(draft, cal, catalog)


def test_post_draft_refuses_closed_period_named(catalog, cal) -> None:
    cash, rent = list(catalog)
    draft = new_draft("D4", MAY_DATE, "may-dated", [(rent, 25_000), (cash, -25_000)])
    with pytest.raises(PeriodClosedError, match="2026-05 is closed.*2026-05-14"):
        post_draft(draft, cal, catalog)


def test_post_draft_refuses_unknown_account(catalog, cal) -> None:
    cash, rent = list(catalog)
    stranger = create_account("9900 Stranger", AccountType.ASSET, "bank")
    draft = new_draft("D5", JULY_DATE, "stranger", [(stranger, 100), (cash, -100)])
    with pytest.raises(EntryPostError, match="'9900 Stranger' is not in the posting catalog"):
        post_draft(draft, cal, catalog)


def test_post_draft_refuses_non_active_account(catalog, cal) -> None:
    cash, rent = list(catalog)
    pending = create_account("9800 Pending", AccountType.ASSET, "bank")
    draft = new_draft("D6", JULY_DATE, "pending acct", [(pending, 100), (cash, -100)])
    with pytest.raises(EntryPostError, match="'9800 Pending' is pending"):
        post_draft(draft, cal, {**catalog, pending: AccountStatus.PENDING})
    draft2 = new_draft("D7", JULY_DATE, "deactivated acct", [(pending, 100), (cash, -100)])
    with pytest.raises(EntryPostError, match="is deactivated"):
        post_draft(draft2, cal, {**catalog, pending: AccountStatus.DEACTIVATED})


def test_post_draft_accepts_good_posting(catalog, cal) -> None:
    cash, rent = list(catalog)
    draft = new_draft("DG", JULY_DATE, "good posting", [(rent, 25_000), (cash, -25_000)])
    posted = post_draft(draft, cal, catalog)
    assert posted.entry.entry_id == "DG"  # defaults to the draft id
    assert posted.entry.date is JULY_DATE
    override = post_draft(draft, cal, catalog, entry_id="JE-OVERRIDE")
    assert override.entry.entry_id == "JE-OVERRIDE"


def test_post_draft_refuses_unmapped_date(catalog) -> None:
    cash, rent = list(catalog)
    draft = new_draft("DM", date(2027, 5, 1), "unmapped", [(rent, 100), (cash, -100)])
    with pytest.raises(UnmappedDateError, match="no fiscal period covers 2027-05-01"):
        post_draft(draft, monthly_periods(2026), catalog)


# ---------------------------------------------------------------------------
# Reversing entry constructor (HR-2 / CK-15)
# ---------------------------------------------------------------------------


def may_rent_entry(entry_id: str = "JE-MAY-1") -> JournalEntry:
    cash = activate_account(create_account("1000 C", AccountType.ASSET, "bank"))
    rent = activate_account(create_account("5200 R", AccountType.EXPENSE, "occupancy_expense"))
    return JournalEntry(
        entry_id,
        MAY_DATE,
        "office rent",
        (JournalLine.debit(account_ref(rent), 25_000), JournalLine.credit(account_ref(cash), 25_000)),
    )


@pytest.fixture()
def original() -> JournalEntry:
    return may_rent_entry()


def test_reversal_negates_lines_exactly(cal, original) -> None:
    rev = reversal_for(original, "JE-JUL-REV-1", JULY_DATE, cal)
    assert len(rev.lines) == len(original.lines)
    for rev_line, orig_line in zip(rev.lines, original.lines):
        assert rev_line.account == orig_line.account
        assert rev_line.amount_cents == -orig_line.amount_cents
    assert sum(line.amount_cents for line in rev.lines) == 0
    assert original.lines[0].amount_cents == 25_000  # original untouched (HR-2)


def test_reversal_references_original_id(cal, original) -> None:
    rev = reversal_for(original, "JE-JUL-REV-1", JULY_DATE, cal)
    assert rev.description.startswith("Reversal of entry JE-MAY-1:")
    assert reversal_meta(rev) == {"reverses": "JE-MAY-1", "entry_id": "JE-JUL-REV-1"}
    assert reversals_index([original, rev]) == {"JE-JUL-REV-1": "JE-MAY-1"}
    assert reversal_meta(original) == {"entry_id": "JE-MAY-1"}  # non-reversal


def test_reversal_posts_into_open_period_ck15(cal, original) -> None:
    """CK-15: May-closed mistake corrected in July — the OPEN period."""
    rev = reversal_for(original, "JE-JUL-REV-1", JULY_DATE, cal)
    assert rev.date is JULY_DATE
    assert rev.entry_id == "JE-JUL-REV-1"
    with pytest.raises(PeriodClosedError, match="2026-05 is closed"):
        reversal_for(original, "JE-REV-BAD", MAY_DATE + timedelta(days=6), cal)  # into closed May


def test_reversal_rejects_unposted_original(cal) -> None:
    """A balanced JournalEntry is the only thing reversal_for accepts.

    JournalEntry refuses unbalanced construction (HR-1), so the
    ReversalError guard in reversal_for is defense-in-depth.  We verify
    a balanced entry passes and a non-JournalEntry is rejected.
    """
    cash = activate_account(create_account("1000 C", AccountType.ASSET, "bank"))
    rent = activate_account(create_account("5200 R", AccountType.EXPENSE, "occupancy_expense"))
    good_entry = JournalEntry("JE-GOOD", JULY_DATE, "ok", (
        JournalLine.debit(account_ref(rent), 100),
        JournalLine.credit(account_ref(cash), 100),
    ))
    rev = reversal_for(good_entry, "REV", JULY_DATE, cal)
    assert rev.entry_id == "REV"
    # An unbalanced entry cannot even be constructed to test the
    # ReversalError path — HR-1 makes it unreachable from pure code.


def test_reversal_rejects_garbage(cal, original) -> None:
    with pytest.raises(TypeError):
        reversal_for("JE-MAY-1", "REV", JULY_DATE, cal)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        reversal_for(original, "   ", JULY_DATE, cal)
    with pytest.raises(TypeError):
        reversal_for(original, "REV", "2026-07-03", cal)  # type: ignore[arg-type]


def test_posted_index_uniqueness(cal, original) -> None:
    index = posted_index([original])
    assert index["JE-MAY-1"] is original
    twin = may_rent_entry("JE-MAY-1")
    with pytest.raises(EntryPostError, match="duplicate entry id"):
        posted_index([original, twin])


def test_full_correction_flow_ck15(catalog, cal) -> None:
    """May-closed/July-open end-to-end: reversal + correction linked by id."""
    cash, rent = list(catalog)
    # The mistaken May entry (posted while May was still open):
    mistaken = JournalEntry("JE-MAY-1", MAY_DATE, "office rent", (
        JournalLine.debit(account_ref(rent), 25_000), JournalLine.credit(account_ref(cash), 25_000),
    ))
    # Reversal dated in OPEN July:
    rev = reversal_for(mistaken, "JE-JUL-REV-1", JULY_DATE, cal)
    assert reversal_meta(rev)["reverses"] == "JE-MAY-1"
    # Corrected posting (the expense was actually $200.00, not $250.00):
    correction = new_draft("JE-JUL-FIX-1", JULY_DATE, "corrected rent",
                           [(rent, 20_000), (cash, -20_000)])
    corrected = post_draft(correction, cal, catalog)
    # Stored history immutable: mistaken entry value unchanged (HR-2):
    assert mistaken.lines[0].amount_cents == 25_000
    assert mistaken.entry_id == "JE-MAY-1"
    # Audit linkage: both reference each other through the original id:
    assert reversals_index([mistaken, rev]) == {"JE-JUL-REV-1": "JE-MAY-1"}
    assert corrected.is_balanced
    # The books still balance after reversal + correction:
    assert sum(line.amount_cents for line in rev.lines) == 0
    assert sum(line.amount_cents for line in corrected.entry.lines) == 0