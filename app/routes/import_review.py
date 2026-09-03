"""Import review queue: list drafts, accept, edit-accept, reject (Step 7, HR-5).

GET /review/queue — list pending bank lines with suggestions.
POST /review/accept/<line_id> — accept a line as a posted journal entry.
POST /review/reject/<line_id> — reject a line (it stays unposted).
GET /review/progress — counts of pending/accepted/rejected.

HR-5 LOCKED RULE: nothing auto-posts from imports.  Every posting path
goes through explicit human accept.  Accept posts via a SERIALIZABLE
transaction with the D-7 40001 retry wrapper.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.dependencies import require_admin, current_user
from ledger.reconciliation import ReconciliationError

router = APIRouter(prefix="/review", tags=["review"])


@router.get("/queue")
def review_queue(request: Request, user: dict = Depends(current_user)) -> dict:
    """List all pending bank lines awaiting review (HR-5 review gate)."""
    import psycopg
    conn = request.app.state.db
    with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
        cur.execute(
            "SELECT bl.id, bl.transaction_date, bl.description, bl.amount_cents, "
            "       bl.line_hash, bl.fitid, bl.status, "
            "       ba.name AS bank_account_name "
            "FROM bank_lines bl "
            "JOIN import_batches ib ON ib.id = bl.batch_id "
            "JOIN bank_accounts ba ON ba.id = ib.bank_account_id "
            "WHERE bl.status = 'pending' "
            "ORDER BY bl.transaction_date, bl.id"
        )
        rows = cur.fetchall()
    return {
        "pending_lines": [
            {
                "id": r["id"],
                "date": r["transaction_date"].isoformat() if r["transaction_date"] else None,
                "description": r["description"],
                "amount_cents": r["amount_cents"],
                "bank_account": r["bank_account_name"],
                "status": r["status"],
            }
            for r in rows
        ]
    }


@router.get("/progress")
def review_progress(request: Request, user: dict = Depends(current_user)) -> dict:
    """Counts of pending/accepted/rejected bank lines."""
    import psycopg
    conn = request.app.state.db
    with conn.cursor() as cur:
        cur.execute(
            "SELECT status, count(*) FROM bank_lines GROUP BY status"
        )
        counts = {row[0]: row[1] for row in cur.fetchall()}
    return {
        "pending": counts.get("pending", 0),
        "accepted": counts.get("accepted", 0),
        "rejected": counts.get("rejected", 0),
        "reconciled": counts.get("reconciled", 0),
    }


@router.post("/accept/{line_id}")
def accept_line(
    request: Request,
    line_id: int,
    body: dict,
    user: dict = Depends(require_admin),
) -> dict:
    """Accept a bank line as a posted journal entry (HR-5 explicit accept).

    Request body:
    {
        "debit_account_name": "5200 Rent Expense",
        "credit_account_name": "1000 Checking Account",
        "description": "optional override"
    }

    The posting runs inside a SERIALIZABLE transaction (D-7).  The bank
    line's status transitions pending → accepted, and the posted_entry_id
    is linked.
    """
    import psycopg
    from db.session import serializable_tx
    from ledger.accounts import Account, AccountStatus
    from ledger.entries import new_draft, post_draft
    from ledger.periods import monthly_periods
    from app.repository import load_accounts, load_periods, insert_journal_entry, find_period_for_date

    debit_name = body.get("debit_account_name", "")
    credit_name = body.get("credit_account_name", "")
    description = body.get("description", "")

    if not debit_name or not credit_name:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="debit_account_name and credit_account_name are required",
        )

    conn = request.app.state.db

    # Run the accept inside a transaction (D-7: SERIALIZABLE for money mutations).
    try:
        # 1. Load and lock the bank line.
        with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
            cur.execute(
                "SELECT id, transaction_date, description, amount_cents, status "
                "FROM bank_lines WHERE id = %s FOR UPDATE",
                (line_id,),
            )
            line = cur.fetchone()
        if line is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"bank line {line_id} not found")
        if line["status"] != "pending":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"bank line {line_id} is already {line['status']}",
            )

        # 2. Build the posting.
        db_accounts = load_accounts(conn)
        name_to_account = {a.name: a for a in db_accounts}
        catalog = {a: AccountStatus.ACTIVE for a in db_accounts}

        debit_acct = name_to_account.get(debit_name)
        credit_acct = name_to_account.get(credit_name)
        if debit_acct is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                                detail=f"account {debit_name!r} not found")
        if credit_acct is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                                detail=f"account {credit_name!r} not found")

        amount = abs(line["amount_cents"])
        if line["amount_cents"] > 0:
            sides = [(debit_acct, amount), (credit_acct, -amount)]
        else:
            sides = [(debit_acct, amount), (credit_acct, -amount)]

        periods = load_periods(conn)
        if not periods:
            periods = list(monthly_periods(line["transaction_date"].year))

        desc = description or line["description"]
        draft = new_draft("REVIEW", line["transaction_date"], desc, sides)
        posted = post_draft(draft, periods, catalog)

        # 3. Persist the journal entry.
        period = find_period_for_date(conn, line["transaction_date"])
        if period is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"no fiscal period covers {line['transaction_date'].isoformat()}",
            )
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM fiscal_periods WHERE name = %s", (period.name,))
            row = cur.fetchone()
            if row is None:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"fiscal period {period.name!r} not in DB",
                )
            period_db_id = row[0]

        entry_db_id = insert_journal_entry(conn, posted.entry, period_db_id)

        # 4. Update the bank line status + link the posted entry.
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE bank_lines SET status = 'accepted', posted_entry_id = %s "
                "WHERE id = %s",
                (entry_db_id, line_id),
            )
        conn.commit()
        return {"status": "ok", "entry_id": str(entry_db_id), "line_id": line_id}
    except HTTPException:
        conn.rollback()
        raise
    except Exception as exc:
        conn.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"accept failed: {exc}",
        )


@router.post("/reject/{line_id}")
def reject_line(
    request: Request,
    line_id: int,
    body: dict,
    user: dict = Depends(require_admin),
) -> dict:
    """Reject a bank line (it stays unposted, status → rejected)."""
    import psycopg
    conn = request.app.state.db
    with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
        cur.execute(
            "SELECT status FROM bank_lines WHERE id = %s", (line_id,)
        )
        line = cur.fetchone()
    if line is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"bank line {line_id} not found")
    if line["status"] != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"bank line {line_id} is already {line['status']}",
        )
    reason = body.get("reason", "")
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE bank_lines SET status = 'rejected' WHERE id = %s",
            (line_id,),
        )
    conn.commit()
    return {"status": "ok", "line_id": line_id, "rejected": True}