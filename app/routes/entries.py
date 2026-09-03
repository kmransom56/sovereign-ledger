"""Journal entry routes: list entries, post a manual entry (Step 5).

GET /entries — list all journal entries (any authenticated user).
POST /entries — post a balanced journal entry (admin only, CSRF-gated).
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.dependencies import require_admin, current_user
from app.repository import load_journal_entries, insert_journal_entry, find_period_for_date

router = APIRouter(prefix="/entries", tags=["entries"])


@router.get("")
def list_entries(request: Request, user: dict = Depends(current_user)) -> dict:
    """List all journal entries with their lines."""
    conn = request.app.state.db
    entries = load_journal_entries(conn)
    return {
        "entries": [
            {
                "entry_id": e.entry_id,
                "date": e.date.isoformat(),
                "description": e.description,
                "lines": [
                    {
                        "account": line.account.name,
                        "code": line.account.code,
                        "amount_cents": line.amount_cents,
                        "side": "debit" if line.amount_cents > 0 else "credit",
                    }
                    for line in e.lines
                ],
            }
            for e in entries
        ]
    }


@router.post("")
def post_entry(
    request: Request,
    body: dict,
    user: dict = Depends(require_admin),
) -> dict:
    """Post a balanced journal entry (admin only, CSRF-gated).

    Request body:
    {
        "entry_date": "2026-09-15",
        "description": "Office supplies",
        "lines": [
            {"account_name": "5000 Office Supplies", "amount_cents": 5000},
            {"account_name": "1000 Checking Account", "amount_cents": -5000}
        ]
    }
    """
    from ledger.accounts import Account, AccountStatus
    from ledger.entries import new_draft, post_draft
    from ledger.periods import monthly_periods, PeriodClosedError, UnmappedDateError
    from app.repository import load_accounts, load_periods
    import psycopg

    entry_date_str = body.get("entry_date", "")
    description = body.get("description", "")
    raw_lines = body.get("lines", [])

    if not entry_date_str or not description or not raw_lines:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="entry_date, description, and lines are required",
        )

    try:
        entry_date = date.fromisoformat(entry_date_str)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"invalid date format {entry_date_str!r}; use YYYY-MM-DD",
        )

    conn = request.app.state.db

    # Build the account catalog from DB accounts.
    db_accounts = load_accounts(conn)
    catalog = {a: AccountStatus.ACTIVE for a in db_accounts}
    name_to_account = {a.name: a for a in db_accounts}

    # Build sides for the draft.
    sides = []
    for raw in raw_lines:
        acct_name = raw.get("account_name", "")
        amount = raw.get("amount_cents", 0)
        if not acct_name or not isinstance(amount, int):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="each line needs account_name (str) and amount_cents (int)",
            )
        acct = name_to_account.get(acct_name)
        if acct is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"account {acct_name!r} not found in chart of accounts",
            )
        sides.append((acct, amount))

    # Load fiscal periods from DB.
    periods = load_periods(conn)
    if not periods:
        # No periods in DB — generate monthly for the entry's year.
        periods = list(monthly_periods(entry_date.year))

    try:
        draft = new_draft("DRAFT", entry_date, description, sides)
        posted = post_draft(draft, periods, catalog)
    except PeriodClosedError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        )
    except UnmappedDateError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )

    # Persist to DB.
    period = find_period_for_date(conn, entry_date)
    if period is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"no fiscal period covers {entry_date.isoformat()}",
        )

    # Look up the period's DB id.
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM fiscal_periods WHERE name = %s", (period.name,))
        row = cur.fetchone()
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"fiscal period {period.name!r} exists in core but not in DB",
            )
        period_db_id = row[0]

    try:
        entry_db_id = insert_journal_entry(conn, posted.entry, period_db_id)
    except Exception as exc:
        conn.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"failed to persist entry: {exc}",
        )
    conn.commit()

    return {
        "status": "ok",
        "entry_id": str(entry_db_id),
        "debit_total": posted.total_debit_cents,
        "credit_total": posted.total_credit_cents,
    }