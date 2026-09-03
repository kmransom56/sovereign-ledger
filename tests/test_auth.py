"""Auth + session + CSRF + role-gate test suite (Step 4, D-11/D-12/CK-12).

Covers:
* Login with correct password sets a signed cookie (SameSite=Strict).
* Tampered cookie is rejected.
* Every POST without the per-session CSRF header returns 403 (trap 10).
* Accountant role: write attempts refused with 403, GET succeeds.
* check_needs_rehash() is invoked on successful login (asserted via test double).
* Argon2id parameters match OWASP floor m=19456 KiB, t=2, p=1.

The auth tests use a lightweight in-memory DB substitute (sqlite-style
mock) to avoid requiring the full Postgres container — the argon2 hashing,
session signing, CSRF, and role-gate logic are all pure app-layer concerns
that don't need PG.  The conftest.py scratch_pg fixture exists for Step 2
DB tests; auth tests run without it.
"""

from __future__ import annotations

import importlib
import sys
from datetime import datetime, timezone

import psycopg
import pytest
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Test fixtures: lightweight app with a real argon2 hasher and a mock DB
# ---------------------------------------------------------------------------

# OWASP floor hasher (D-12) — matches the app hasher.
_HASHER = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)

# Pre-computed hashes for the test users (fast — no hash in the hot path).
_ADMIN_HASH = _HASHER.hash("admin-pass-123")
_ACCOUNTANT_HASH = _HASHER.hash("read-only-456")


class MockDB:
    """Minimal in-memory mock of the psycopg connection for auth tests.

    Implements just enough: dict_row cursor for SELECT, plain cursor for
    UPDATE, and a row factory pattern matching psycopg 3.
    """

    def __init__(self) -> None:
        self._users = {
            "keith": {
                "id": 1,
                "username": "keith",
                "password_hash": _ADMIN_HASH,
                "role": "admin",
                "is_active": True,
            },
            "accountant": {
                "id": 2,
                "username": "accountant",
                "password_hash": _ACCOUNTANT_HASH,
                "role": "accountant",
                "is_active": True,
            },
        }

    def cursor(self, row_factory=None):
        return MockCursor(self, row_factory)

    def commit(self):
        pass

    def close(self):
        pass


class MockCursor:
    def __init__(self, db: MockDB, row_factory=None):
        self._db = db
        self._row_factory = row_factory
        self._result = None
        self.rowcount = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, query: str, params: tuple = ()) -> None:
        q = query.strip().upper()
        if q.startswith("SELECT"):
            username = params[0] if params else ""
            user = self._db._users.get(username)
            if user:
                self._result = [dict(user)]
            else:
                self._result = []
        elif q.startswith("UPDATE"):
            # Extract the new hash and user id from params
            new_hash, user_id = params[0], params[1]
            for u in self._db._users.values():
                if u["id"] == user_id:
                    u["password_hash"] = new_hash
                    self.rowcount = 1
                    return
            self.rowcount = 0
        else:
            self._result = []

    def fetchone(self):
        if self._row_factory is None:
            return self._result[0] if self._result else None
        return self._result[0] if self._result else None


@pytest.fixture()
def app_with_mock_db():
    """Create a FastAPI app with a mock DB and test session settings."""
    # Import here so each test gets a fresh app.
    from app.main import create_app
    from config.settings import Settings

    settings = Settings(
        session_secret="test-secret-for-signed-cookies-32+chars-long",
        cookie_secure=False,
    )
    app = create_app(settings=settings, cookie_secure_override=False)
    mock_db = MockDB()
    app.state.db = mock_db

    # Reset the argon2 hasher cache so the test hasher matches.
    import app.routes.auth as auth_mod
    auth_mod._argon2 = _HASHER

    return app, mock_db


@pytest.fixture()
def client(app_with_mock_db):
    app, _ = app_with_mock_db
    with TestClient(app) as c:
        yield c


def _login(client: TestClient, username: str, password: str) -> dict:
    """Helper: login and return the response JSON."""
    resp = client.post("/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, f"login failed: {resp.status_code} {resp.text}"
    return resp.json()


def _get_csrf(client: TestClient) -> str:
    """Login as admin and return the CSRF token."""
    data = _login(client, "keith", "admin-pass-123")
    return data["csrf_token"]


# ---------------------------------------------------------------------------
# /healthz — no auth required
# ---------------------------------------------------------------------------


def test_healthz_no_auth(client: TestClient) -> None:
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# Login flow (D-11/D-12)
# ---------------------------------------------------------------------------


def test_login_success_sets_cookie(client: TestClient) -> None:
    resp = client.post("/auth/login", json={"username": "keith", "password": "admin-pass-123"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["role"] == "admin"
    assert data["username"] == "keith"
    assert "csrf_token" in data

    # The signed cookie must be set with SameSite=Strict.
    cookies = resp.headers.get("set-cookie", "")
    assert "ledger_session=" in cookies
    assert "samesite=strict" in cookies.lower()
    assert "httponly" in cookies.lower()


def test_login_wrong_password_rejected(client: TestClient) -> None:
    resp = client.post("/auth/login", json={"username": "keith", "password": "wrong"})
    assert resp.status_code == 401
    assert "Invalid credentials" in resp.json()["detail"]


def test_login_unknown_user_rejected(client: TestClient) -> None:
    resp = client.post("/auth/login", json={"username": "nobody", "password": "x"})
    assert resp.status_code == 401
    assert "Invalid credentials" in resp.json()["detail"]


def test_login_missing_fields_rejected(client: TestClient) -> None:
    resp = client.post("/auth/login", json={"username": "", "password": ""})
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Tampered cookie rejected (D-11)
# ---------------------------------------------------------------------------


def test_tampered_cookie_rejected(client: TestClient) -> None:
    _login(client, "keith", "admin-pass-123")
    # Tamper with the session cookie.
    original = client.cookies.get("ledger_session", "")
    if original:
        tampered = original[:-4] + ("0000" if original[-4:] != "0000" else "1111")
        client.cookies.set("ledger_session", tampered)
    resp = client.get("/auth/me")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# CSRF enforcement (trap 10)
# ---------------------------------------------------------------------------


def test_post_without_csrf_token_returns_403(client: TestClient) -> None:
    _login(client, "keith", "admin-pass-123")
    resp = client.post("/auth/admin-only")
    assert resp.status_code == 403
    assert "CSRF" in resp.json()["detail"] or "X-CSRF-Token" in resp.json()["detail"]


def test_post_with_wrong_csrf_token_returns_403(client: TestClient) -> None:
    _login(client, "keith", "admin-pass-123")
    resp = client.post("/auth/admin-only", headers={"X-CSRF-Token": "wrong-token"})
    assert resp.status_code == 403
    assert "CSRF token mismatch" in resp.json()["detail"]


def test_post_with_correct_csrf_token_succeeds(client: TestClient) -> None:
    csrf = _get_csrf(client)
    resp = client.post("/auth/admin-only", headers={"X-CSRF-Token": csrf})
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


# ---------------------------------------------------------------------------
# Role gate (CK-12 negative core)
# ---------------------------------------------------------------------------


def test_accountant_get_succeeds(client: TestClient) -> None:
    """Accountant role can GET (read-only access)."""
    _login(client, "accountant", "read-only-456")
    resp = client.get("/auth/me")
    assert resp.status_code == 200
    assert resp.json()["role"] == "accountant"


def test_accountant_post_refused_403(client: TestClient) -> None:
    """Accountant role: every write attempt refused with 403 (CK-12)."""
    _login(client, "accountant", "read-only-456")
    csrf = _login(client, "accountant", "read-only-456")["csrf_token"]
    resp = client.post("/auth/admin-only", headers={"X-CSRF-Token": csrf})
    assert resp.status_code == 403
    assert "read-only" in resp.json()["detail"] or "admin" in resp.json()["detail"]


def test_admin_post_succeeds(client: TestClient) -> None:
    """Admin role with correct CSRF can POST."""
    csrf = _get_csrf(client)
    resp = client.post("/auth/admin-only", headers={"X-CSRF-Token": csrf})
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Unauthenticated requests
# ---------------------------------------------------------------------------


def test_unauthenticated_post_rejected(client: TestClient) -> None:
    resp = client.post("/auth/admin-only", headers={"X-CSRF-Token": "x"})
    assert resp.status_code == 401


def test_unauthenticated_me_rejected(client: TestClient) -> None:
    resp = client.get("/auth/me")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------


def test_logout_clears_session(client: TestClient) -> None:
    csrf = _get_csrf(client)
    resp = client.post("/auth/logout", headers={"X-CSRF-Token": csrf})
    assert resp.status_code == 200
    # After logout, /me should reject.
    resp = client.get("/auth/me")
    assert resp.status_code == 401


def test_logout_requires_csrf(client: TestClient) -> None:
    _get_csrf(client)
    resp = client.post("/auth/logout")
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# check_needs_rehash invoked on successful login (D-12)
# ---------------------------------------------------------------------------


def test_check_needs_rehash_invoked_on_login(app_with_mock_db) -> None:
    """check_needs_rehash() is called on every successful login.

    We verify by asserting that a hash with outdated parameters gets
    rehashed (the DB row is updated).  We plant a hash with different
    parameters (lower memory cost) and verify the DB row changes.
    """
    app, mock_db = app_with_mock_db

    # Plant a hash with outdated parameters (low memory_cost).
    weak_hasher = PasswordHasher(time_cost=1, memory_cost=8192, parallelism=1)
    mock_db._users["keith"]["password_hash"] = weak_hasher.hash("admin-pass-123")

    with TestClient(app) as c:
        resp = c.post("/auth/login", json={"username": "keith", "password": "admin-pass-123"})
        assert resp.status_code == 200

    # The password_hash in the mock DB should have been updated (rehashed
    # with the app's OWASP-floor parameters).
    new_hash = mock_db._users["keith"]["password_hash"]
    # Verify the new hash works with the app hasher.
    _HASHER.verify(new_hash, "admin-pass-123")
    # check_needs_rehash should return False for the new hash (it's at floor).
    assert not _HASHER.check_needs_rehash(new_hash)


# ---------------------------------------------------------------------------
# Argon2id parameters match OWASP floor (D-12)
# ---------------------------------------------------------------------------


def test_argon2_parameters_match_owasp_floor() -> None:
    """The app hasher uses OWASP floor: m=19456 KiB, t=2, p=1."""
    from app.routes.auth import _get_hasher

    hasher = _get_hasher()
    # argon2-cffi stores the parameters in the hash string itself.
    test_hash = hasher.hash("test")
    # Parse the argon2id hash parameters: $argon2id$v=19$m=19456,t=2,p=1$...
    assert "m=19456" in test_hash
    assert "t=2" in test_hash
    assert "p=1" in test_hash


# ---------------------------------------------------------------------------
# No default session secret in production config (security check)
# ---------------------------------------------------------------------------


def test_no_insecure_default_secret_in_production() -> None:
    """The default session_secret is a dev-only marker, not a real secret.

    This test asserts the default value is NOT a production-grade secret —
    it's a clearly-marked development placeholder that must be overridden.
    """
    from config.settings import Settings

    s = Settings()
    assert "dev-only" in s.session_secret or "change" in s.session_secret.lower()
    # The cookie_secure default is True (Secure flag on).
    assert s.cookie_secure is True