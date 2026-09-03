"""Reconciliation route: statement balance, cleared lines, $0.00 completion (Step 7, HR-7).

POST /reconcile/start — start a reconciliation with a statement balance.
GET /reconcile/{bank_account_name} — get current reconciliation state.
POST /reconcile/{bank_account_name}/complete — complete if difference == $0.00.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.dependencies import require_admin, current_user
from ledger.reconciliation import (
    reconciliation_difference,
    complete_reconciliation,
    ReconciliationError,
)

router = APIRouter(prefix="/reconcile", tags=["reconcile"])


@router.post("/{bank_account_name}/start")
def start_reconciliation(
    request: Request,
    bank_account_name: str,
    body: dict,
    user: dict = Depends(require_admin),
) -> dict:
    """Start a reconciliation with a statement ending balance.

    Request body: {"statement_balance_cents": 421375}

    Returns the current difference between the statement and cleared lines.
    """
    import psycopg
    conn = request.app.state.db

    statement_balance = body.get("statement_balance_cents")
    if not isinstance(statement_balance, int):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="statement_balance_cents (int) is required",
        )

    # Look up the bank account.
    with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
        cur.execute(
            "SELECT id FROM bank_accounts WHERE name = %s", (bank_account_name,)
        )
        bank_acct = cur.fetchone()
    if bank_acct is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"bank account {bank_account_name!r} not found")

    # Get all accepted (cleared) bank lines for this account.
    with conn.cursor() as cur:
        cur.execute(
            "SELECT bl.amount_cents FROM bank_lines bl "
            "JOIN import_batches ib ON ib.id = bl.batch_id "
            "WHERE ib.bank_account_id = %s AND bl.status = 'accepted' "
            "ORDER BY bl.transaction_date",
            (bank_acct["id"],),
        )
        cleared_amounts = [row[0] for row in cur.fetchall()]

    result = reconciliation_difference(statement_balance, cleared_amounts)
    return {
        "bank_account": bank_account_name,
        "statement_balance_cents": result.statement_balance_cents,
        "cleared_total_cents": result.cleared_total_cents,
        "difference_cents": result.difference_cents,
        "is_complete": result.is_complete,
    }


@router.post("/{bank_account_name}/complete")
def complete(
    request: Request,
    bank_account_name: str,
    body: dict,
    user: dict = Depends(require_admin),
) -> dict:
    """Complete the reconciliation — refuses if difference != $0.00 (HR-7).

    Request body: {"statement_balance_cents": 421375}
    """
    import psycopg
    conn = request.app.state.db

    statement_balance = body.get("statement_balance_cents")
    if not isinstance(statement_balance, int):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="statement_balance_cents (int) is required",
        )

    with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
        cur.execute(
            "SELECT id FROM bank_accounts WHERE name = %s", (bank_account_name,)
        )
        bank_acct = cur.fetchone()
    if bank_acct is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"bank account {bank_account_name!r} not found")

    with conn.cursor() as cur:
        cur.execute(
            "SELECT bl.id, bl.amount_cents FROM bank_lines bl "
            "JOIN import_batches ib ON ib.id = bl.batch_id "
            "WHERE ib.bank_account_id = %s AND bl.status = 'accepted'",
            (bank_acct["id"],),
        )
        cleared = cur.fetchall()

    cleared_amounts = [row[1] for row in cleared]
    result = reconciliation_difference(statement_balance, cleared_amounts)

    try:
        complete_reconciliation(result)
    except ReconciliationError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        )

    # Lock the cleared lines: status → reconciled.
    with conn.cursor() as cur:
        for line_id, _ in cleared:
            cur.execute(
                "UPDATE bank_lines SET status = 'reconciled' WHERE id = %s AND status = 'accepted'",
                (line_id,),
            )
    conn.commit()

    return {
        "status": "complete",
        "bank_account": bank_account_name,
        "cleared_line_count": len(cleared),
        "statement_balance_cents": result.statement_balance_cents,
        "cleared_total_cents": result.cleared_total_cents,
    }