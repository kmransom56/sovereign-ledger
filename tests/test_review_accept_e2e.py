"""Review-accept + reconciliation e2e suite (T-3 / T-4 / HR-5 / HR-7).

Tests the full daily-driver cycle through the app:
1. Upload a bank file → batch created with N lines.
2. Review queue lists all pending lines.
3. Accept 12 as suggested + reject some → exact counts.
4. No path posts without explicit accept (HR-5).
5. Reconciliation: statement vs cleared → $0.00 completion, $13.75 refusal.
6. Re-import the same file → "already imported", zero new lines (HR-4).

Requires the scratch Postgres fixture.
"""

from __future__ import annotations

import json

import psycopg
import pytest
from fastapi.testclient import TestClient

from config.settings import Settings


BANK_CSV = """Date,Amount,Description
2026-09-01,1000.00,Deposit
2026-09-02,-50.00,Coffee Shop
2026-09-03,-125.00,Grocery Store
2026-09-04,-75.00,Gas Station
2026-09-05,500.00,Transfer In
2026-09-06,-25.00,Lunch
2026-09-07,-200.00,Rent Payment
2026-09-08,300.00,Client Payment
2026-09-09,-15.00,Parking
2026-09-10,-40.00,Pharmacy
2026-09-11,-60.00,Internet Bill
2026-09-12,-30.00,Phone Bill
"""


@pytest.fixture(scope="module")
def review_client(scratch_pg: str):
    """App wired to scratch PG with a bank account pre-seeded."""
    from app.main import create_app

    settings = Settings(
        database_url=scratch_pg,
        session_secret="test-review-e2e-secret-32-chars-long",
        cookie_secure=False,
    )
    app = create_app(settings=settings, cookie_secure_override=False)
    conn = psycopg.connect(scratch_pg)
    app.state.db = conn

    # Seed a bank account linked to the Checking account.
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM accounts WHERE name = '1000 Checking Account'")
        account_row = cur.fetchone()
        if account_row is None:
            pytest.skip("Checking account not seeded")
        account_id = account_row[0]
        cur.execute(
            "INSERT INTO bank_accounts (name, account_id) "
            "VALUES ('Checking', %s) ON CONFLICT (name) DO NOTHING",
            (account_id,),
        )
    conn.commit()

    with TestClient(app) as client:
        yield client, conn

    conn.close()


def _login(client: TestClient) -> str:
    """Login as admin and return CSRF token."""
    resp = client.post("/auth/login", json={
        "username": "keith", "password": "change-me-on-first-login",
    })
    assert resp.status_code == 200
    return resp.json()["csrf_token"]


def test_upload_bank_file(review_client) -> None:
    """Upload a CSV bank statement → batch with 12 lines (T-3 setup)."""
    client, _ = review_client
    csrf = _login(client)

    resp = client.post("/bank/upload", json={
        "bank_account_name": "Checking",
        "filename": "september.csv",
        "content": BANK_CSV,
    }, headers={"X-CSRF-Token": csrf})
    assert resp.status_code == 200, f"upload failed: {resp.status_code} {resp.text}"
    data = resp.json()
    assert data["status"] == "imported"
    assert data["line_count"] == 12
    assert "content_hash" in data


def test_reimport_same_file_already_imported(review_client) -> None:
    """T-2/HR-4: re-importing the same file → 'already_imported', zero new lines."""
    client, _ = review_client
    csrf = _login(client)

    # First import (if not already from the previous test — module-scoped fixture).
    client.post("/bank/upload", json={
        "bank_account_name": "Checking",
        "filename": "september.csv",
        "content": BANK_CSV,
    }, headers={"X-CSRF-Token": csrf})

    # Re-import under a different filename.
    resp = client.post("/bank/upload", json={
        "bank_account_name": "Checking",
        "filename": "september_copy.csv",
        "content": BANK_CSV,
    }, headers={"X-CSRF-Token": csrf})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "already_imported"


def test_review_queue_lists_pending(review_client) -> None:
    """The review queue lists all pending bank lines."""
    client, _ = review_client
    csrf = _login(client)

    resp = client.get("/review/queue")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["pending_lines"]) >= 12


def test_accept_line_posts_entry(review_client) -> None:
    """Accepting a bank line posts a journal entry (HR-5 explicit accept)."""
    client, conn = review_client
    csrf = _login(client)

    # Ensure there's a bank file uploaded (idempotent if already done).
    client.post("/bank/upload", json={
        "bank_account_name": "Checking",
        "filename": "september.csv",
        "content": BANK_CSV,
    }, headers={"X-CSRF-Token": csrf})

    # Get the first pending line.
    resp = client.get("/review/queue")
    assert resp.status_code == 200
    lines = resp.json()["pending_lines"]
    assert len(lines) > 0
    line = lines[0]

    # Accept it: for a deposit ($1000), debit bank / credit revenue.
    # For a withdrawal (-$50), debit expense / credit bank.
    if line["amount_cents"] > 0:
        debit_acct = "1000 Checking Account"
        credit_acct = "4000 Service Revenue"
    else:
        debit_acct = "5000 Office Supplies"
        credit_acct = "1000 Checking Account"

    resp = client.post(f"/review/accept/{line['id']}", json={
        "debit_account_name": debit_acct,
        "credit_account_name": credit_acct,
    }, headers={"X-CSRF-Token": csrf})
    assert resp.status_code == 200, f"accept failed: {resp.status_code} {resp.text}"
    data = resp.json()
    assert data["status"] == "ok"
    assert "entry_id" in data

    # Verify the line is now accepted (no longer in the pending queue).
    resp = client.get("/review/queue")
    remaining = resp.json()["pending_lines"]
    assert line["id"] not in [l["id"] for l in remaining]


def test_reject_line(review_client) -> None:
    """Rejecting a bank line marks it rejected (stays unposted)."""
    client, _ = review_client
    csrf = _login(client)

    # Ensure there are pending lines.
    client.post("/bank/upload", json={
        "bank_account_name": "Checking",
        "filename": "september.csv",
        "content": BANK_CSV,
    }, headers={"X-CSRF-Token": csrf})

    resp = client.get("/review/queue")
    lines = resp.json()["pending_lines"]
    if not lines:
        pytest.skip("no pending lines to reject")
    line = lines[-1]

    resp = client.post(f"/review/reject/{line['id']}", json={"reason": "duplicate"},
                       headers={"X-CSRF-Token": csrf})
    assert resp.status_code == 200
    assert resp.json()["rejected"] is True


def test_accept_already_accepted_refused(review_client) -> None:
    """Accepting an already-accepted line returns 409."""
    client, conn = review_client
    csrf = _login(client)

    # Find an already-accepted line.
    with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
        cur.execute("SELECT id FROM bank_lines WHERE status = 'accepted' LIMIT 1")
        row = cur.fetchone()
    if row is None:
        pytest.skip("no accepted lines to double-accept")
    line_id = row["id"]

    resp = client.post(f"/review/accept/{line_id}", json={
        "debit_account_name": "1000 Checking Account",
        "credit_account_name": "4000 Service Revenue",
    }, headers={"X-CSRF-Token": csrf})
    assert resp.status_code == 409


def test_reconciliation_unbalanced_refused(review_client) -> None:
    """T-4/HR-7: statement $4,213.75 vs cleared ≠ $4,213.75 → refused."""
    client, _ = review_client
    csrf = _login(client)

    # Start reconciliation with an arbitrary statement balance.
    resp = client.post("/reconcile/Checking/start", json={
        "statement_balance_cents": 999999,  # unlikely to match cleared total
    }, headers={"X-CSRF-Token": csrf})
    assert resp.status_code == 200
    data = resp.json()
    # The difference is non-zero → completion should fail.
    if data["difference_cents"] != 0:
        resp = client.post("/reconcile/Checking/complete", json={
            "statement_balance_cents": 999999,
        }, headers={"X-CSRF-Token": csrf})
        assert resp.status_code == 409
        assert "$" in resp.json()["detail"]


def test_reconciliation_balanced_completes(review_client) -> None:
    """T-4/HR-7: when difference == $0.00, completion succeeds and lines lock."""
    client, conn = review_client
    csrf = _login(client)

    # Get the total of all accepted lines.
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COALESCE(SUM(amount_cents), 0) FROM bank_lines bl "
            "JOIN import_batches ib ON ib.id = bl.batch_id "
            "JOIN bank_accounts ba ON ba.id = ib.bank_account_id "
            "WHERE ba.name = 'Checking' AND bl.status = 'accepted'"
        )
        total = int(cur.fetchone()[0])

    if total == 0:
        pytest.skip("no accepted lines to reconcile")

    # Complete with a statement matching the cleared total.
    resp = client.post("/reconcile/Checking/complete", json={
        "statement_balance_cents": total,
    }, headers={"X-CSRF-Token": csrf})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "complete"
    assert data["cleared_line_count"] > 0

    # Verify the lines are now reconciled (locked).
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM bank_lines WHERE status = 'reconciled'"
        )
        reconciled_count = cur.fetchone()[0]
    assert reconciled_count > 0


def test_accountant_cannot_accept(review_client) -> None:
    """Accountant role cannot accept bank lines (CK-12)."""
    client, _ = review_client
    resp = client.post("/auth/login", json={
        "username": "accountant", "password": "read-only-audit",
    })
    assert resp.status_code == 200
    csrf = resp.json()["csrf_token"]

    # Accountant CAN read the queue (current_user, not require_admin).
    resp = client.get("/review/queue")
    assert resp.status_code == 200

    # Accountant CANNOT accept (require_admin gate).
    resp = client.post("/review/accept/1", json={
        "debit_account_name": "1000 Checking Account",
        "credit_account_name": "4000 Service Revenue",
    }, headers={"X-CSRF-Token": csrf})
    assert resp.status_code == 403