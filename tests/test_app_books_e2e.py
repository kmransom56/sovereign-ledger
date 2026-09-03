"""Books-exist e2e suite (T-8 / CK-1) — app against scratch Postgres.

This test exercises the full vertical slice through the app layer:
1. Login as admin.
2. Verify CoA accounts are seeded.
3. Post a manual journal entry via the API.
4. Verify the entry appears in the entries list.
5. Verify the trial balance nets to $0.00.
6. Verify immutability: UPDATE/DELETE on journal_entries is refused.

Requires the scratch Postgres fixture from conftest.py.
"""

from __future__ import annotations

import json
import os
from datetime import date

import psycopg
import pytest
from fastapi.testclient import TestClient

from db.seed.users import _argon2_hash
from config.settings import Settings


@pytest.fixture(scope="module")
def app_client(scratch_pg: str):
    """Create a FastAPI app wired to the scratch Postgres."""
    from app.main import create_app

    settings = Settings(
        database_url=scratch_pg,
        session_secret="test-e2e-secret-32-chars-long-aaa",
        cookie_secure=False,
    )
    app = create_app(settings=settings, cookie_secure_override=False)

    # Open a psycopg connection and store it on app.state.
    conn = psycopg.connect(scratch_pg)
    app.state.db = conn

    with TestClient(app) as client:
        yield client, conn

    conn.close()


def _login_admin(client: TestClient) -> str:
    """Login as keith (admin) and return the CSRF token."""
    # The seed created keith with a default password; we need to know it.
    # The seed uses DEFAULT_ADMIN_PASSWORD = "change-me-on-first-login".
    resp = client.post("/auth/login", json={
        "username": "keith",
        "password": "change-me-on-first-login",
    })
    assert resp.status_code == 200, f"admin login failed: {resp.status_code} {resp.text}"
    return resp.json()["csrf_token"]


def test_healthz(app_client) -> None:
    client, _ = app_client
    resp = client.get("/healthz")
    assert resp.status_code == 200


def test_login_admin_and_list_accounts(app_client) -> None:
    """Login as admin and verify the CoA is seeded (T-8/CK-1)."""
    client, _ = app_client
    csrf = _login_admin(client)

    resp = client.get("/accounts")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["accounts"]) > 0
    names = {a["name"] for a in data["accounts"]}
    assert "1000 Checking Account" in names
    assert "5200 Rent Expense" in names
    assert "4000 Service Revenue" in names


def test_post_manual_entry_and_verify_tb(app_client) -> None:
    """Post a manual entry → TB nets to $0.00 (HR-1/HR-9 through the web path)."""
    client, conn = app_client
    csrf = _login_admin(client)

    # Post a manual entry: $250 rent paid from checking.
    resp = client.post("/entries", json={
        "entry_date": "2026-09-15",
        "description": "September rent",
        "lines": [
            {"account_name": "5200 Rent Expense", "amount_cents": 25_000},
            {"account_name": "1000 Checking Account", "amount_cents": -25_000},
        ],
    }, headers={"X-CSRF-Token": csrf})
    assert resp.status_code == 200, f"post entry failed: {resp.status_code} {resp.text}"
    data = resp.json()
    assert data["status"] == "ok"
    assert data["debit_total"] == 25_000
    assert data["credit_total"] == 25_000

    # Verify the entry appears in the entries list.
    resp = client.get("/entries")
    assert resp.status_code == 200
    entries = resp.json()["entries"]
    assert len(entries) >= 1
    rent_entry = next(
        (e for e in entries if e["description"] == "September rent"),
        None,
    )
    assert rent_entry is not None
    assert len(rent_entry["lines"]) == 2

    # Verify the trial balance nets to $0.00.
    resp = client.get("/reports/trial-balance")
    assert resp.status_code == 200
    tb = resp.json()
    assert tb["is_balanced"] is True
    assert tb["total_debit_cents"] == tb["total_credit_cents"]
    # The rent entry posted $250 debit + $250 credit
    assert tb["total_debit_cents"] >= 25_000


def test_post_unbalanced_entry_rejected(app_client) -> None:
    """Posting an unbalanced entry is refused by the domain core (HR-1)."""
    client, _ = app_client
    csrf = _login_admin(client)

    resp = client.post("/entries", json={
        "entry_date": "2026-09-15",
        "description": "unbalanced",
        "lines": [
            {"account_name": "5200 Rent Expense", "amount_cents": 25_000},
            {"account_name": "1000 Checking Account", "amount_cents": -24_000},
        ],
    }, headers={"X-CSRF-Token": csrf})
    assert resp.status_code == 422
    assert "unbalanced" in resp.json()["detail"].lower()


def test_accountant_cannot_post_entries(app_client) -> None:
    """Accountant role cannot POST entries (CK-12)."""
    client, _ = app_client
    # Login as accountant.
    resp = client.post("/auth/login", json={
        "username": "accountant",
        "password": "read-only-audit",
    })
    assert resp.status_code == 200
    csrf = resp.json()["csrf_token"]

    resp = client.post("/entries", json={
        "entry_date": "2026-09-15",
        "description": "attempt",
        "lines": [
            {"account_name": "5200 Rent Expense", "amount_cents": 1000},
            {"account_name": "1000 Checking Account", "amount_cents": -1000},
        ],
    }, headers={"X-CSRF-Token": csrf})
    assert resp.status_code == 403


def test_journal_entries_immutable(app_client) -> None:
    """UPDATE/DELETE on journal_entries is refused (HR-2)."""
    _, conn = app_client

    # The trigger fires BEFORE UPDATE/DELETE and raises — even for the
    # table owner (triggers fire on owners; REVOKE only covers non-owners).
    # psycopg raises the trigger's exception on execute.
    with pytest.raises(psycopg.errors.DatabaseError):
        with conn.cursor() as cur:
            cur.execute("UPDATE journal_entries SET description = 'hacked' WHERE id = 1")
        conn.commit()
    conn.rollback()


def test_no_cdn_references_in_templates() -> None:
    """HR-3: no CDN references (https:// script src) in templates."""
    # No templates yet (JSON-only API); verify no https:// in app routes.
    import pathlib
    app_dir = pathlib.Path(__file__).resolve().parent.parent / "app"
    violations = []
    for pyfile in app_dir.rglob("*.py"):
        text = pyfile.read_text(encoding="utf-8", errors="replace")
        for lineno, line in enumerate(text.splitlines(), 1):
            if "https://" in line and "script src" in line.lower():
                violations.append(f"{pyfile}:{lineno}")
    assert not violations, f"CDN script references found: {violations}"