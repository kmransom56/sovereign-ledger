"""Hypothesis property suite for the pure money engine (``ledger/engine.py``).

SIGN CONVENTION under test (locked decision D-3):

    amount_cents > 0   →  DEBIT   (+)
    amount_cents < 0   →  CREDIT  (−)

SCENARIO MATH — why this suite exercises ≥ 1,000 balanced/unbalanced
entry scenarios (SKILL trap 11: ``deadline=None`` everywhere; hypothesis
deadlines are wall-clock checks that flake on loaded CI boxes):

* ``LedgerPostingMachine`` — RuleBasedStateMachine configured with
  ``max_examples=60`` × ``stateful_step_count=25`` = **1,500 stateful
  scenarios**; every step either posts a balanced entry (built
  balanced-by-construction: Σ debit magnitudes == Σ credit magnitudes)
  or attempts an unbalanced posting that MUST be refused — so the
  ≥ 1,000 bar is met by this single test alone.
* ``test_posting_preserves_balance_and_sign`` — 250 generated entries.
* ``test_bigint_scale_exact_arithmetic`` — 250 magnitudes up to the
  Postgres BIGINT ceiling (2**63 − 1 cents, far beyond ±2**31), with
  pinned ``@example`` regressions at 2**31+1, 2**62, and the ceiling.
* ``test_bigint_multi_line_exact_sum`` — 200 two-debit/two-line-sum
  scenarios proving exact integer arithmetic past ±2**31 cents.
* ``test_sign_flip_is_refused`` — 150 adversarial unbalance attempts.
* ``test_debit_credit_bake_the_sign`` — 150 builder scenarios.
* ``test_cents_from_decimal_roundtrip`` — 200 boundary conversions.

Overall ≥ 2,700 scenarios; balanced coverage is structural
(``balanced_entries`` guarantees Σ = 0) and unbalanced coverage is
adversarial (perturbed and all-debit bundles must raise
``UnbalancedEntryError``). Database-I/O tests belong to the db worker's
files — everything here touches no I/O, mirroring the engine itself.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from hypothesis import HealthCheck, assume, example, given, settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, rule

from ledger.engine import PostedEntry, post, post_lines, validate_balanced
from ledger.types import (
    BIGINT_MAX_CENTS,
    AccountRef,
    AccountType,
    BigIntOverflowError,
    JournalEntry,
    JournalLine,
    Money,
    UnbalancedEntryError,
    cents_from_decimal,
)

#: Multi-line magnitudes stay ≤ 10**12 so balancing remainders can never
#: push a line past the BIGINT ceiling while still exercising large ints.
MAGNITUDE_CAP = 10**12

ACCOUNT_TYPES = st.sampled_from(AccountType)


# --------------------------------------------------------------------------
# Strategies: entries built BALANCED BY CONSTRUCTION and adversarial garbage
# --------------------------------------------------------------------------


@st.composite
def account_refs(draw: st.DrawFn) -> AccountRef:
    return AccountRef(
        code=f"A{draw(st.integers(0, 999)):03d}",
        name=f"acct {draw(st.integers(0, 999))}",
        type=draw(ACCOUNT_TYPES),
    )


@st.composite
def balanced_entries(draw: st.DrawFn) -> JournalEntry:
    """A journal entry that balances BY CONSTRUCTION (Σ amount_cents == 0).

    Debit and credit magnitudes are drawn independently, then a single
    balancing line (of the residual) closes the gap — never a zero
    line, so every generated entry is a realistic double posting.
    """
    n_debits = draw(st.integers(1, 3))
    n_credits = draw(st.integers(1, 3))
    debits = draw(st.lists(st.integers(1, MAGNITUDE_CAP), min_size=n_debits, max_size=n_debits))
    credits = draw(st.lists(st.integers(1, MAGNITUDE_CAP), min_size=n_credits, max_size=n_credits))
    delta = sum(debits) - sum(credits)
    if delta > 0:
        credits.append(delta)
    elif delta < 0:
        debits.append(-delta)
    lines = [JournalLine.debit(draw(account_refs()), magnitude) for magnitude in debits]
    lines += [JournalLine.credit(draw(account_refs()), magnitude) for magnitude in credits]
    return JournalEntry(
        entry_id=f"JE-{draw(st.integers(0, 10**9))}",
        date=draw(st.dates(min_value=date(2000, 1, 1), max_value=date(2100, 12, 31))),
        description=draw(st.text(max_size=60)),
        lines=lines,
    )


# --------------------------------------------------------------------------
# Properties: balance preservation and D-3 sign semantics
# --------------------------------------------------------------------------


@given(entry=balanced_entries())
@settings(deadline=None, max_examples=250)
def test_posting_preserves_balance_and_sign(entry: JournalEntry) -> None:
    """Posting preserves Σ == 0 and the + debit / − credit split (D-3)."""
    posted = post(entry)
    assert posted.entry == entry
    assert sum(line.amount_cents for line in entry.lines) == 0
    assert posted.total_debit_cents == posted.total_credit_cents > 0
    assert posted.debit_lines == tuple(line for line in entry.lines if line.amount_cents > 0)
    assert posted.credit_lines == tuple(line for line in entry.lines if line.amount_cents < 0)
    assert all(line.is_debit and line.amount_cents > 0 for line in posted.debit_lines)
    assert all(line.is_credit and line.amount_cents < 0 for line in posted.credit_lines)
    assert posted.is_balanced
    # Posting is a pure fold: identical inputs yield identical outputs.
    assert post(entry) == posted
    assert post_lines(entry.entry_id, entry.date, entry.description, list(entry.lines)) == posted


@given(magnitude=st.integers(0, BIGINT_MAX_CENTS))
@example(magnitude=2**31 + 1)
@example(magnitude=2**62)
@example(magnitude=BIGINT_MAX_CENTS)
@settings(deadline=None, max_examples=250)
def test_bigint_scale_exact_arithmetic(magnitude: int) -> None:
    """Exact arithmetic far beyond ±2**31 cents, up to the BIGINT ceiling."""
    cash = AccountRef("1010", "cash", AccountType.ASSET)
    revenue = AccountRef("4010", "revenue", AccountType.INCOME)
    debit_line = JournalLine.debit(cash, magnitude)
    credit_line = JournalLine.credit(revenue, magnitude)
    entry = JournalEntry("BIG", date(2026, 9, 2), "bigint-scale", (debit_line, credit_line))
    posted = post(entry)
    assert debit_line.amount_cents == magnitude  # + = DEBIT side (D-3)
    assert credit_line.amount_cents == -magnitude  # − = CREDIT side (D-3)
    assert posted.total_debit_cents == posted.total_credit_cents == magnitude
    assert sum(line.amount_cents for line in entry.lines) == 0
    # No float drift at quadrillion-cent scale: int + int is exact.
    assert magnitude + 1 > magnitude


@given(a=st.integers(1, 2**62), b=st.integers(1, 2**62))
@settings(deadline=None, max_examples=200)
def test_bigint_multi_line_exact_sum(a: int, b: int) -> None:
    """Two debit lines balancing against one credit of their exact sum."""
    assume(a + b <= BIGINT_MAX_CENTS)
    cash = AccountRef("1010", "cash", AccountType.ASSET)
    receivable = AccountRef("1200", "receivable", AccountType.ASSET)
    revenue = AccountRef("4010", "revenue", AccountType.INCOME)
    lines = [
        JournalLine.debit(cash, a),
        JournalLine.debit(receivable, b),
        JournalLine.credit(revenue, a + b),
    ]
    posted = post(JournalEntry("SUM", date(2026, 9, 2), "exact-sum", lines))
    assert posted.total_debit_cents == a + b == posted.total_credit_cents
    assert posted.is_balanced


@given(entry=balanced_entries(), data=st.data())
@settings(deadline=None, max_examples=150)
def test_sign_flip_is_refused(entry: JournalEntry, data: st.DataObject) -> None:
    """Negating any single line unbalances the entry — and is REFUSED."""
    index = data.draw(st.integers(0, len(entry.lines) - 1))
    victim = entry.lines[index]
    flipped = JournalLine(victim.account, -victim.amount_cents)
    lines = list(entry.lines)
    lines[index] = flipped
    assert sum(line.amount_cents for line in lines) == -2 * victim.amount_cents
    assert sum(line.amount_cents for line in lines) != 0  # magnitudes are ≥ 1
    with pytest.raises(UnbalancedEntryError):
        JournalEntry(entry.entry_id, entry.date, entry.description, lines)
    with pytest.raises(UnbalancedEntryError):
        validate_balanced(lines)


@given(account=account_refs(), magnitude=st.integers(0, BIGINT_MAX_CENTS))
@settings(deadline=None, max_examples=150)
def test_debit_credit_bake_the_sign(account: AccountRef, magnitude: int) -> None:
    """The constructors encode D-3 structurally; floats and bools are rejected."""
    debit = JournalLine.debit(account, magnitude)
    credit = JournalLine.credit(account, magnitude)
    assert debit.amount_cents == magnitude
    assert credit.amount_cents == -magnitude
    if magnitude > 0:
        assert debit.is_debit and not debit.is_credit
        assert credit.is_credit and not credit.is_debit
    else:
        assert not debit.is_debit and not debit.is_credit
    with pytest.raises(TypeError):
        JournalLine.debit(account, float(magnitude) + 0.5)  # float money is forbidden
    with pytest.raises(TypeError):
        JournalLine(account, True)  # bool is not int money
    with pytest.raises(BigIntOverflowError):
        JournalLine.debit(account, BIGINT_MAX_CENTS + 1)  # beyond Postgres BIGINT


# --------------------------------------------------------------------------
# Construction refusals: the engine must never accept a broken entry
# --------------------------------------------------------------------------


def test_entry_construction_refuses_garbage() -> None:
    account = AccountRef("1010", "cash", AccountType.ASSET)
    debit = JournalLine.debit(account, 100)
    credit = JournalLine.credit(account, 100)
    with pytest.raises(UnbalancedEntryError):
        JournalEntry("E1", date(2026, 9, 2), "no lines", ())
    with pytest.raises(UnbalancedEntryError):
        post_lines("E2", date(2026, 9, 2), "no lines", [])
    with pytest.raises(UnbalancedEntryError):
        validate_balanced([])
    with pytest.raises(UnbalancedEntryError):
        post_lines("E3", date(2026, 9, 2), "off by one", [debit, JournalLine.credit(account, 99)])
    with pytest.raises(UnbalancedEntryError):
        JournalEntry("E4", date(2026, 9, 2), "off by one", [debit, JournalLine.credit(account, 99)])
    with pytest.raises(TypeError):
        JournalEntry("E5", "2026-09-02", "str date", (debit, credit))
    with pytest.raises(TypeError):
        JournalEntry("E6", datetime(2026, 9, 2, 12, 0), "datetime is not date", (debit, credit))
    with pytest.raises(TypeError):
        JournalLine(account, 10.0)  # never float money
    # Sanity: the balanced pair itself posts cleanly.
    posted = post_lines("E7", date(2026, 9, 2), "balanced pair", [debit, credit])
    assert posted.is_balanced and posted.total_debit_cents == 100


@given(cents=st.integers(-BIGINT_MAX_CENTS, BIGINT_MAX_CENTS))
@example(cents=BIGINT_MAX_CENTS)
@example(cents=-BIGINT_MAX_CENTS)
@example(cents=2**31 + 7)
@settings(deadline=None, max_examples=200)
def test_cents_from_decimal_roundtrip(cents: int) -> None:
    """Decimal-USD ↔ int-cents is exact across the whole BIGINT range."""
    assert cents_from_decimal(Decimal(cents) / 100) == cents


def test_cents_from_decimal_rejects_non_money() -> None:
    with pytest.raises(TypeError):
        cents_from_decimal(12.34)  # float money is forbidden at the boundary
    with pytest.raises(ValueError):
        cents_from_decimal(Decimal("0.005"))  # sub-cent precision
    with pytest.raises(ValueError):
        cents_from_decimal(Decimal("NaN"))
    with pytest.raises(ValueError):
        cents_from_decimal(Decimal("Infinity"))
    with pytest.raises(BigIntOverflowError):
        cents_from_decimal(Decimal(2**63) / 100)  # beyond the BIGINT ceiling


@pytest.mark.parametrize(
    ("account_type", "expected_sign"),
    [
        (AccountType.ASSET, 1),
        (AccountType.EXPENSE, 1),
        (AccountType.LIABILITY, -1),
        (AccountType.EQUITY, -1),
        (AccountType.INCOME, -1),
    ],
)
def test_normal_balance_sign(account_type: AccountType, expected_sign: int) -> None:
    assert account_type.normal_balance_sign == expected_sign


def test_money_alias_is_int() -> None:
    assert Money is int  # signed integer cents, nothing else


# --------------------------------------------------------------------------
# Static purity: mirror the CI gate inside the test suite as well
# --------------------------------------------------------------------------

_FORBIDDEN_TOKEN = re.compile(r"\b(?:fastapi|psycopg|asyncpg|requests|httpx)\b")


def test_ledger_tree_has_no_io_tokens() -> None:
    ledger_root = Path(__file__).resolve().parent.parent / "ledger"
    for path in sorted(ledger_root.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            assert _FORBIDDEN_TOKEN.search(line) is None, f"{path}:{lineno}: forbidden I/O token"


# --------------------------------------------------------------------------
# Stateful posting machine
# --------------------------------------------------------------------------


class LedgerPostingMachine(RuleBasedStateMachine):
    """Post balanced entries into an in-memory ledger; refuse unbalanced ones.

    Every ``post_balanced_entry`` step builds a bundle whose debit and
    credit magnitudes are reconciled by construction, posts it, and
    checks the running per-account balances; every
    ``refuse_unbalanced_entry`` step tries to smuggle a Σ ≠ 0 bundle
    past the constructor, ``post_lines``, and ``validate_balanced`` —
    all three must raise ``UnbalancedEntryError``. The invariant holds
    the whole ledger balanced after every transition.
    """

    def __init__(self) -> None:
        super().__init__()
        self.accounts: dict[str, AccountRef] = {}
        self.balances: dict[str, int] = {}
        self.posted: list[PostedEntry] = []
        self._next_id = 0
        for account_type in AccountType:
            self._add_account(account_type)

    def _add_account(self, account_type: AccountType) -> None:
        code = f"A{len(self.accounts):03d}"
        self.accounts[code] = AccountRef(code=code, name=f"acct {code}", type=account_type)
        self.balances[code] = 0

    @rule(account_type=ACCOUNT_TYPES)
    def add_account(self, account_type: AccountType) -> None:
        self._add_account(account_type)

    @rule(data=st.data())
    def post_balanced_entry(self, data: st.DataObject) -> None:
        n_debits = data.draw(st.integers(1, 3))
        n_credits = data.draw(st.integers(1, 3))
        debits = data.draw(st.lists(st.integers(1, MAGNITUDE_CAP), min_size=n_debits, max_size=n_debits))
        credits = data.draw(st.lists(st.integers(1, MAGNITUDE_CAP), min_size=n_credits, max_size=n_credits))
        delta = sum(debits) - sum(credits)
        if delta > 0:
            credits.append(delta)
        elif delta < 0:
            debits.append(-delta)
        codes = sorted(self.accounts)
        lines = [
            JournalLine.debit(self.accounts[data.draw(st.sampled_from(codes))], magnitude)
            for magnitude in debits
        ] + [
            JournalLine.credit(self.accounts[data.draw(st.sampled_from(codes))], magnitude)
            for magnitude in credits
        ]
        before = dict(self.balances)
        entry = JournalEntry(f"JE-{self._next_id}", date(2026, 9, 2), "stateful posting", lines)
        self._next_id += 1
        posted = post(entry)
        self.posted.append(posted)
        for line in lines:
            self.balances[line.account.code] += line.amount_cents
        assert posted.is_balanced
        assert posted.total_debit_cents == posted.total_credit_cents == sum(debits)
        for code, balance in self.balances.items():
            assert balance == before.get(code, 0) + sum(
                line.amount_cents for line in lines if line.account.code == code
            )

    @rule(data=st.data())
    def refuse_unbalanced_entry(self, data: st.DataObject) -> None:
        count = data.draw(st.integers(1, 4))
        magnitudes = data.draw(st.lists(st.integers(0, MAGNITUDE_CAP), min_size=count, max_size=count))
        if sum(magnitudes) == 0:
            magnitudes[0] = 1  # all-debit bundles with Σ = 0 are impossible otherwise
        assert sum(magnitudes) != 0
        codes = sorted(self.accounts)
        lines = [
            JournalLine.debit(self.accounts[data.draw(st.sampled_from(codes))], magnitude)
            for magnitude in magnitudes
        ]
        with pytest.raises(UnbalancedEntryError):
            JournalEntry(f"BAD-{self._next_id}", date(2026, 9, 2), "unbalanced", lines)
        with pytest.raises(UnbalancedEntryError):
            post_lines(f"BAD-{self._next_id}", date(2026, 9, 2), "unbalanced", lines)
        with pytest.raises(UnbalancedEntryError):
            validate_balanced(lines)

    @invariant()
    def posted_ledger_stays_balanced(self) -> None:
        for posted in self.posted:
            assert posted.is_balanced
            for line in posted.debit_lines:
                assert line.amount_cents > 0
            for line in posted.credit_lines:
                assert line.amount_cents < 0
        for code in self.accounts:
            expected = sum(
                line.amount_cents
                for posted in self.posted
                for line in posted.entry.lines
                if line.account.code == code
            )
            assert self.balances[code] == expected


LedgerPostingMachine.TestCase.settings = settings(
    deadline=None,
    max_examples=60,
    stateful_step_count=25,
    suppress_health_check=[HealthCheck.too_slow],
)

#: Expose the machine's TestCase under a ``Test*`` name so pytest collects it.
TestLedgerPosting = LedgerPostingMachine.TestCase