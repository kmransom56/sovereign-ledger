"""Chart-of-accounts suite (CK-1 / T-8 core half).

Covers the CoA lifecycle (create PENDING → activate → deactivate),
subtype → tax-mapping metadata (the locked seed vocabulary, incl. the
two-line occupancy grouping), and the opening-balance entry helper whose
whole point is an opening trial balance netting to exactly $0.00.

The account-status posting gate mirrors D-6: only ACTIVE accounts admit
postings, and the refusal names the account.

Purity (hard rule 1): no I/O — every account and balance is constructed.
"""

from __future__ import annotations

from datetime import date

import pytest

from ledger.accounts import (
    OPENING_BALANCE_DESCRIPTION,
    OPENING_BALANCE_PREFIX,
    SUBTYPE_TAX_MAPPINGS,
    Account,
    AccountError,
    AccountInactiveError,
    AccountStatus,
    OpeningBalanceError,
    account_ref,
    activate_account,
    assert_postable_account,
    create_account,
    deactivate_account,
    known_subtypes,
    opening_balance_entry,
    opening_balance_lines,
    tax_mapping_for,
    tax_mappings_index,
)
from ledger.engine import post
from ledger.types import AccountType, BigIntOverflowError

OB_DATE = date(2026, 1, 1)


def checking(tax_mapping: str | None = None, status: AccountStatus = AccountStatus.PENDING) -> Account:
    return Account("1000 Checking Account", AccountType.ASSET, "bank", tax_mapping, status)


def rent(status: AccountStatus = AccountStatus.PENDING) -> Account:
    return Account("5200 Rent Expense", AccountType.EXPENSE, "occupancy_expense",
                   "Schedule C, Line 20b", status)


# ---------------------------------------------------------------------------
# Account value object + subtype → tax-mapping metadata
# ---------------------------------------------------------------------------


def test_account_defaults_and_status_lifecycle() -> None:
    account = create_account("1000 Checking Account", AccountType.ASSET, "bank")
    assert account.status is AccountStatus.PENDING  # two-step storage contract
    assert account.tax_mapping is None
    active = activate_account(account)
    assert active.status is AccountStatus.ACTIVE
    assert account.status is AccountStatus.PENDING  # original untouched (frozen)
    inactive = deactivate_account(active)
    assert inactive.status is AccountStatus.DEACTIVATED
    assert active.status is AccountStatus.ACTIVE


def test_account_validation() -> None:
    with pytest.raises(ValueError):
        Account("", AccountType.ASSET, "bank")
    with pytest.raises(ValueError):
        Account("   ", AccountType.ASSET, "bank")
    with pytest.raises(TypeError):
        Account("1000 X", "Assets", "bank")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        Account("1000 X", AccountType.ASSET, "")  # empty subtype
    with pytest.raises(TypeError):
        Account("1000 X", AccountType.ASSET, "bank", tax_mapping=7)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        Account("1000 X", AccountType.ASSET, "bank", status="active")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        Account("1000 X", AccountType.ASSET, "not-a-subtype")
    # tax mapping must be valid FOR THE SUBTYPE:
    with pytest.raises(ValueError, match="not a valid mapping"):
        Account("5200 Rent Expense", AccountType.EXPENSE, "occupancy_expense",
                "Schedule C, Line 1")  # revenue line, not occupancy
    with pytest.raises(ValueError, match="not a valid mapping"):
        Account("1000 X", AccountType.ASSET, "bank", "Form 4562")  # bank feeds no form


def test_subtype_tax_mapping_vocabulary() -> None:
    """The locked seed vocabulary is mirrored exactly (12 subtypes)."""
    assert len(SUBTYPE_TAX_MAPPINGS) == 12
    assert tax_mapping_for("operating_revenue") == ("Schedule C, Line 1",)
    assert tax_mapping_for("other_income") == ("Schedule B, Part I",)
    # Rent → Line 20b, utilities → Line 25 — one grouping, two lines:
    assert tax_mapping_for("occupancy_expense") == ("Schedule C, Line 20b", "Schedule C, Line 25")
    assert tax_mapping_for("professional_expense") == ("Schedule C, Line 17",)
    assert tax_mapping_for("operating_expense") == ("Schedule C, Line 18",)
    assert tax_mapping_for("fixed_asset") == ("Form 4562",)
    assert tax_mapping_for("bank") == ()  # bank accounts feed no tax line
    with pytest.raises(ValueError, match="known subtypes"):
        tax_mapping_for("not-a-subtype")
    with pytest.raises(TypeError):
        tax_mapping_for(1)  # type: ignore[arg-type]
    index = tax_mappings_index()
    assert set(index) == {s for s, m in SUBTYPE_TAX_MAPPINGS.items() if m}
    assert "bank" not in index and "occupancy_expense" in index
    assert known_subtypes() == sorted(SUBTYPE_TAX_MAPPINGS)


def test_error_hierarchy() -> None:
    assert issubclass(AccountInactiveError, AccountError)
    assert issubclass(OpeningBalanceError, AccountError)
    assert issubclass(AccountError, ValueError)


# ---------------------------------------------------------------------------
# CoA operations: create / activate / deactivate (D-6 mirrored)
# ---------------------------------------------------------------------------


def test_activate_only_pending() -> None:
    active = activate_account(checking())
    with pytest.raises(AccountError, match="only a PENDING account"):
        activate_account(active)
    deactivated = deactivate_account(active)
    with pytest.raises(AccountError, match="only a PENDING account"):
        activate_account(deactivated)


def test_deactivate_only_active() -> None:
    with pytest.raises(AccountError, match="only an ACTIVE account"):
        deactivate_account(checking())  # PENDING cannot deactivate
    locked = activate_account(checking())
    deactivated = deactivate_account(locked)
    with pytest.raises(AccountError, match="only an ACTIVE account"):
        deactivate_account(deactivated)  # already deactivated


def test_activate_deactivate_reject_garbage() -> None:
    with pytest.raises(TypeError):
        activate_account("1000")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        deactivate_account(1)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        assert_postable_account(None)  # type: ignore[arg-type]


def test_assert_postable_account_names_it() -> None:
    active = activate_account(checking())
    assert_postable_account(active)  # ACTIVE: no error
    with pytest.raises(AccountInactiveError, match="'1000 Checking Account' is pending"):
        assert_postable_account(checking())
    with pytest.raises(AccountInactiveError, match="is deactivated"):
        assert_postable_account(deactivate_account(active))


def test_account_ref_resolves_code_prefix() -> None:
    ref = account_ref(activate_account(checking()))
    assert ref.code == "1000"
    assert ref.name == "1000 Checking Account"
    assert ref.type is AccountType.ASSET
    with pytest.raises(ValueError, match="no numeric code prefix"):
        account_ref(Account("Checking Account", AccountType.ASSET, "bank"))
    with pytest.raises(TypeError):
        account_ref("1000")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Opening-balance entry helper (CK-1 / T-8): opening TB nets to $0.00
# ---------------------------------------------------------------------------


def bank(name: str, status: AccountStatus = AccountStatus.PENDING) -> Account:
    return Account(name, AccountType.ASSET, "bank", None, status)


def payable(name: str, status: AccountStatus = AccountStatus.PENDING) -> Account:
    return Account(name, AccountType.LIABILITY, "payable", None, status)


def capital(status: AccountStatus = AccountStatus.PENDING) -> Account:
    return Account("3000 Owner's Capital", AccountType.EQUITY, "owner_equity", None, status)


def test_opening_balance_lines_balanced_by_construction() -> None:
    cash, card, equity = bank("1000 Checking Account"), payable("2000 Accounts Payable"), capital()
    lines = opening_balance_lines(
        debit_balances={cash: 150_000},                            # debits
        credit_balances={card: 45_000, equity: 80_000},            # credits
        opening_bank=cash,
    )
    assert sum(line.amount_cents for line in lines) == 0  # HR-1 by construction
    assert len(lines) == 4  # debit cash + credit AP + credit equity + cash residual
    # Debits (150000) outran credits (125000) → cash CREDITED by 25000, so
    # the cash account ends up with TWO lines (its opening debit + residual
    # credit) and ends flat at 0.
    cash_lines = [line for line in lines if line.account.code == "1000"]
    assert len(cash_lines) == 2
    assert sum(line.amount_cents for line in cash_lines) == 125_000  # 150k debit - 25k residual credit


def test_opening_balance_lines_refuses_zero_net() -> None:
    cash = bank("1000 Checking Account")
    with pytest.raises(OpeningBalanceError, match="already net to"):
        opening_balance_lines(
            debit_balances={bank("1000 A"): 100_000},
            credit_balances={payable("2000 A"): 40_000, capital(): 60_000},
            opening_bank=cash,
        )


def test_opening_balance_entry_trial_balance_zero() -> None:
    """THE T-8 core check: opening TB nets to exactly $0.00."""
    cash, card, equity = bank("1000 Checking Account"), payable("2000 Accounts Payable"), capital()
    entry = opening_balance_entry(
        debit_balances={cash: 125_000},                    # debits
        credit_balances={card: 45_000, equity: 92_300},    # credits
        opening_bank=cash,
        entry_date=OB_DATE,
    )
    assert entry.description == OPENING_BALANCE_DESCRIPTION
    assert entry.entry_id.startswith(OPENING_BALANCE_PREFIX)
    assert sum(line.amount_cents for line in entry.lines) == 0
    # Opening trial balance: every debit-normal balance minus credit-normal
    # balance — with the residual absorbed by cash — nets to exactly zero.
    debit_total = sum(line.amount_cents for line in entry.lines if line.amount_cents > 0)
    credit_total = -sum(line.amount_cents for line in entry.lines if line.amount_cents < 0)
    assert debit_total == credit_total > 0
    posted = post(entry)
    assert posted.total_debit_cents == posted.total_credit_cents


def test_opening_balance_entry_cash_residual_direction() -> None:
    """Credits outrunning debits DEBIT the cash account (and vice versa)."""
    cash = bank("1000 Checking Account")
    # Case 1: credits outrun debits → cash DEBITED by the gap.
    entry = opening_balance_entry(
        debit_balances={bank("1200 A"): 10_000},
        credit_balances={capital(): 40_000},
        opening_bank=cash,
        entry_date=OB_DATE,
    )
    net = sum(line.amount_cents for line in entry.lines)
    assert net == 0
    cash_line = next(line for line in entry.lines if line.account.code == "1000")
    assert cash_line.amount_cents == 30_000  # debited by the gap
    # Case 2: debits outrun credits → cash CREDITED.
    entry2 = opening_balance_entry(
        debit_balances={bank("1200 B"): 50_000},
        credit_balances={capital(): 20_000},
        opening_bank=cash,
        entry_date=OB_DATE,
    )
    cash_line2 = next(line for line in entry2.lines if line.account.code == "1000")
    assert cash_line2.amount_cents == -30_000  # credited by the gap


def test_opening_balance_custom_id_and_date_validation() -> None:
    cash = bank("1000 Checking Account")
    entry = opening_balance_entry(
        debit_balances={bank("1200 C"): 5_000},
        credit_balances={capital(): 3_000},
        opening_bank=cash,
        entry_date=OB_DATE,
        entry_id="OB-CUSTOM",
    )
    assert entry.entry_id == "OB-CUSTOM"
    assert entry.date is OB_DATE
    with pytest.raises(TypeError):
        opening_balance_entry(
            debit_balances={bank("1200 D"): 5_000},
            credit_balances={capital(): 3_000},
            opening_bank=cash,
            entry_date="2026-01-01",  # type: ignore[arg-type]
        )
    with pytest.raises(BigIntOverflowError):
        opening_balance_entry(
            debit_balances={bank("1200 E"): 2**63},
            credit_balances={capital(): 1},
            opening_bank=cash,
            entry_date=OB_DATE,
        )


def test_opening_balance_overlap_and_bank_validation() -> None:
    cash = bank("1000 Checking Account")
    same = bank("1200 A")
    with pytest.raises(OpeningBalanceError, match="both debit and credit"):
        opening_balance_lines(
            debit_balances={same: 100}, credit_balances={same: 100}, opening_bank=cash
        )
    with pytest.raises(TypeError, match="opening_bank"):
        opening_balance_lines(
            debit_balances={bank("1200 B"): 100},
            credit_balances={capital(): 50},
            opening_bank="1000",  # type: ignore[arg-type]
        )


def test_opening_balance_zero_balances_skipped() -> None:
    """A zero balance carries no information and is skipped (not stored)."""
    cash = bank("1000 Checking Account")
    zero_asset = bank("1300 Empty")
    entry = opening_balance_entry(
        debit_balances={zero_asset: 0, bank("1200 C2"): 4_000},
        credit_balances={capital(): 2_000},
        opening_bank=cash,
        entry_date=OB_DATE,
    )
    codes = {line.account.code for line in entry.lines}
    assert "1300" not in codes  # zero-balance account skipped
    assert sum(line.amount_cents for line in entry.lines) == 0


def test_opening_balance_lines_returns_at_least_one_line() -> None:
    """The balanced bundle always has lines (an empty entry is refused)."""
    cash = bank("1000 Checking Account")
    lines = opening_balance_lines(
        debit_balances={bank("1200 D"): 3_000},
        credit_balances={},
        opening_bank=cash,
    )
    assert len(lines) >= 1
    assert sum(line.amount_cents for line in lines) == 0