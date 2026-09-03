"""Bank upload route: receive a bank file, parse, store batch (Step 7).

POST /bank/upload — upload a CSV/OFX bank statement, parse it via the
appropriate importer, store the batch and lines in the DB, and report
"already imported" if the content hash matches a previous batch (HR-4).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.dependencies import require_admin, current_user

router = APIRouter(prefix="/bank", tags=["bank"])


@router.post("/upload")
def upload_bank_file(
    request: Request,
    body: dict,
    user: dict = Depends(require_admin),
) -> dict:
    """Upload and parse a bank statement file.

    Request body:
    {
        "bank_account_name": "Checking",
        "filename": "september.csv",
        "content": "Date,Amount,Description\\n...",
        "profile_column_map": {"date": "Date", "amount": "Amount", ...},
        "date_format": "%Y-%m-%d"
    }

    Returns:
    {
        "status": "imported" | "already_imported",
        "batch_id": int | null,
        "line_count": int,
        "content_hash": str
    }
    """
    import psycopg
    from importers.csv_generic import parse_csv
    from importers.ofx import OFXImporter
    from importers.profiles import ImportProfile
    from importers.hash import batch_hash

    bank_account_name = body.get("bank_account_name", "")
    filename = body.get("filename", "")
    content = body.get("content", "")

    if not bank_account_name or not filename or not content:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="bank_account_name, filename, and content are required",
        )

    conn = request.app.state.db

    # Look up the bank account in the DB.
    with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
        cur.execute(
            "SELECT id, account_id FROM bank_accounts WHERE name = %s",
            (bank_account_name,),
        )
        bank_acct = cur.fetchone()
    if bank_acct is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"bank account {bank_account_name!r} not found — create it first",
        )

    # Compute the content hash and check for existing import (HR-4).
    content_hash = batch_hash(content)
    with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
        cur.execute(
            "SELECT id, line_count FROM import_batches WHERE content_hash = %s",
            (content_hash,),
        )
        existing = cur.fetchone()
    if existing is not None:
        return {
            "status": "already_imported",
            "batch_id": existing["id"],
            "line_count": existing["line_count"],
            "content_hash": content_hash,
        }

    # Determine parser: OFX if the file looks like OFX, else CSV.
    ofx_importer = OFXImporter()
    if ofx_importer.detect(content, filename):
        from importers.ofx import parse_ofx
        result = parse_ofx(content)
    else:
        # Build profile from request or use defaults.
        col_map = body.get("profile_column_map", {
            "date": "Date", "amount": "Amount", "description": "Description",
        })
        date_fmt = body.get("date_format", "%Y-%m-%d")
        profile = ImportProfile(
            bank_account_id=bank_acct["id"],
            version_number=1,
            column_map=col_map,
            date_format=date_fmt,
        )
        result = parse_csv(content, profile)

    # Persist the batch and lines.
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO import_batches (bank_account_id, filename, content_hash, line_count) "
            "VALUES (%s, %s, %s, %s) RETURNING id",
            (bank_acct["id"], filename, content_hash, result.line_count),
        )
        batch_id = cur.fetchone()[0]
        for line in result.lines:
            cur.execute(
                "INSERT INTO bank_lines "
                "(batch_id, transaction_date, description, amount_cents, line_hash, fitid) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (batch_id, line.transaction_date, line.description,
                 line.amount_cents, line.line_hash, line.fitid),
            )
    conn.commit()

    return {
        "status": "imported",
        "batch_id": batch_id,
        "line_count": result.line_count,
        "content_hash": content_hash,
    }


@router.get("/batches")
def list_batches(request: Request, user: dict = Depends(current_user)) -> dict:
    """List all import batches with their status."""
    import psycopg
    conn = request.app.state.db
    with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
        cur.execute(
            "SELECT b.id, b.filename, b.content_hash, b.line_count, b.imported_at, "
            "       ba.name AS bank_account_name, "
            "       (SELECT count(*) FROM bank_lines WHERE batch_id = b.id AND status = 'pending') AS pending_count, "
            "       (SELECT count(*) FROM bank_lines WHERE batch_id = b.id AND status = 'accepted') AS accepted_count "
            "FROM import_batches b "
            "JOIN bank_accounts ba ON ba.id = b.bank_account_id "
            "ORDER BY b.imported_at DESC"
        )
        rows = cur.fetchall()
    return {
        "batches": [
            {
                "id": r["id"],
                "filename": r["filename"],
                "line_count": r["line_count"],
                "imported_at": r["imported_at"].isoformat() if r["imported_at"] else None,
                "bank_account": r["bank_account_name"],
                "pending": r["pending_count"],
                "accepted": r["accepted_count"],
            }
            for r in rows
        ]
    }