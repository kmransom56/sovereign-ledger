"""Reports routes: trial balance (Step 5, extends through P5).

GET /reports/trial-balance — compute and return the trial balance.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.dependencies import current_user
from app.repository import load_journal_entries
from reports.trial_balance import trial_balance

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/trial-balance")
def get_trial_balance(request: Request, user: dict = Depends(current_user)) -> dict:
    """Compute the trial balance from all posted journal entries."""
    conn = request.app.state.db
    entries = load_journal_entries(conn)
    tb = trial_balance(entries)
    return {
        "is_balanced": tb.is_balanced,
        "total_debit_cents": tb.total_debit_cents,
        "total_credit_cents": tb.total_credit_cents,
        "rows": [
            {
                "account_code": row.account_code,
                "account_name": row.account_name,
                "debit_cents": row.debit_cents,
                "credit_cents": row.credit_cents,
            }
            for row in tb.rows
        ],
    }