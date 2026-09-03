"""Accounts routes: list chart of accounts (Step 5).

GET /accounts — list all accounts (any authenticated user).
POST /accounts — create a new account (admin only, CSRF-gated).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.dependencies import require_admin, current_user
from app.repository import load_accounts, load_account_by_name

router = APIRouter(prefix="/accounts", tags=["accounts"])

#: Map the domain enum value back to the DB's capitalized plural CHECK value.
_DB_TYPE_VALUES = {
    "asset": "Assets",
    "liability": "Liabilities",
    "equity": "Equity",
    "income": "Income",
    "expense": "Expenses",
}


@router.get("")
def list_accounts(request: Request, user: dict = Depends(current_user)) -> dict:
    """List all chart-of-accounts rows."""
    conn = request.app.state.db
    accounts = load_accounts(conn)
    return {
        "accounts": [
            {
                "name": a.name,
                "type": a.type.value,
                "subtype": a.subtype,
                "tax_mapping": a.tax_mapping,
                "status": a.status.value,
            }
            for a in accounts
        ]
    }


@router.post("")
def create_account(
    request: Request,
    body: dict,
    user: dict = Depends(require_admin),
) -> dict:
    """Create a new account (admin only)."""
    from ledger.accounts import create_account as do_create, activate_account
    from ledger.types import AccountType

    name = body.get("name", "")
    account_type_str = body.get("type", "")
    subtype = body.get("subtype", "")
    tax_mapping = body.get("tax_mapping")

    if not name or not account_type_str or not subtype:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="name, type, and subtype are required",
        )

    try:
        atype = AccountType(account_type_str.lower())
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"invalid account type {account_type_str!r}",
        )

    conn = request.app.state.db

    existing = load_account_by_name(conn, name)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"account {name!r} already exists",
        )

    try:
        account = activate_account(do_create(name, atype, subtype, tax_mapping))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )

    db_type = _DB_TYPE_VALUES.get(atype.value, atype.value.capitalize())
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO accounts (name, account_type, subtype, tax_mapping) "
            "VALUES (%s, %s, %s, %s)",
            (account.name, db_type, account.subtype, account.tax_mapping),
        )
    conn.commit()

    return {"status": "ok", "account": {"name": account.name, "type": account.type.value}}