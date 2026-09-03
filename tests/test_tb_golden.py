"""Golden-file trial-balance test (T-8 / CK-1).

Pins the opening-balance entry: the exact set of accounts and amounts
that produce a trial balance netting to exactly $0.00, verified byte-
for-byte against a stored golden JSON snapshot.

The golden file is regenerated when the expected values change — the
test asserts equality, not "close enough."
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from ledger.accounts import Account, AccountStatus, AccountType
from ledger.accounts import opening_balance_entry
from ledger.types import JournalLine
from reports.trial_balance import trial_balance

GOLDEN_DIR = Path(__file__).resolve().parent / "golden"
GOLDEN_FILE = GOLDEN_DIR / "opening_tb.json"


def test_opening_balance_tb_nets_zero_golden() -> None:
    """The opening-balance entry → trial balance nets $0.00 (T-8/CK-1)."""
    cash = Account("1000 Checking Account", AccountType.ASSET, "bank", status=AccountStatus.ACTIVE)
    ar = Account("1200 Accounts Receivable", AccountType.ASSET, "receivable", status=AccountStatus.ACTIVE)
    ap = Account("2000 Accounts Payable", AccountType.LIABILITY, "payable", status=AccountStatus.ACTIVE)
    capital = Account("3000 Owner's Capital", AccountType.EQUITY, "owner_equity", status=AccountStatus.ACTIVE)
    equipment = Account("1500 Business Equipment", AccountType.ASSET, "fixed_asset", "Form 4562", status=AccountStatus.ACTIVE)

    entry = opening_balance_entry(
        debit_balances={cash: 150_000, ar: 30_000, equipment: 50_000},
        credit_balances={ap: 45_000, capital: 175_000},
        opening_bank=cash,
        entry_date=date(2026, 1, 1),
    )

    tb = trial_balance([entry])
    assert tb.is_balanced
    assert tb.total_debit_cents == tb.total_credit_cents
    assert tb.net_cents == 0

    # Build the golden snapshot.
    snapshot = {
        "is_balanced": tb.is_balanced,
        "total_debit_cents": tb.total_debit_cents,
        "total_credit_cents": tb.total_credit_cents,
        "rows": [
            {
                "account_code": r.account_code,
                "account_name": r.account_name,
                "debit_cents": r.debit_cents,
                "credit_cents": r.credit_cents,
            }
            for r in tb.rows
        ],
    }

    # Compare against the golden file if it exists, else write it.
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    if GOLDEN_FILE.exists():
        expected = json.loads(GOLDEN_FILE.read_text())
        assert snapshot == expected, (
            f"Trial balance changed from golden file!\n"
            f"Expected: {json.dumps(expected, indent=2)}\n"
            f"Got:      {json.dumps(snapshot, indent=2)}\n"
            f"If this change is intentional, delete {GOLDEN_FILE} and re-run."
        )
    else:
        GOLDEN_FILE.write_text(json.dumps(snapshot, indent=2))
        # On first write, just verify it's balanced.
        assert tb.is_balanced