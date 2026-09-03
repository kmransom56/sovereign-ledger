"""Auth router: login, logout, session info (Step 4, D-11/D-12).

Login flow:
1. POST /login with JSON {username, password}.
2. Verify password against argon2 hash in the DB.
3. On success: check_needs_rehash() — if the hash is outdated, rehash and
   update the DB row (D-12).
4. Issue a signed-cookie session with user_id, username, role, and a
   fresh per-session CSRF token (trap 10).
5. Return the CSRF token in the response body (the client sends it in the
   X-CSRF-Token header on every subsequent POST).

Logout:
1. POST /logout with the X-CSRF-Token header.
2. Clear the session.

The router uses a raw psycopg connection (not the pool — Step 5 wires
the pool into the app).  For tests, a connection is injected via app.state.
"""

from __future__ import annotations

import logging
import secrets
from typing import Any

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.dependencies import (
    CSRF_HEADER,
    SESSION_CSRF_TOKEN,
    SESSION_ROLE,
    SESSION_USER_ID,
    SESSION_USERNAME,
    current_user,
    require_admin,
    require_authenticated,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

# Argon2id hasher at OWASP floor (D-12: direct argon2-cffi, never passlib).
_argon2: Any = None


def _get_hasher() -> Any:
    """Lazy-init the argon2 PasswordHasher (OWASP floor m=19456/t=2/p=1)."""
    global _argon2
    if _argon2 is None:
        from argon2 import PasswordHasher

        _argon2 = PasswordHasher(
            time_cost=2,
            memory_cost=19456,
            parallelism=1,
        )
    return _argon2


def _get_db(request: Request) -> psycopg.Connection:
    """Get the DB connection from app state (set by the test/app factory)."""
    if not hasattr(request.app.state, "db") or request.app.state.db is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database not configured — set app.state.db before using auth routes.",
        )
    return request.app.state.db


def _fetch_user(conn, username: str) -> dict | None:
    """Fetch a user row by username; return None if not found."""
    with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
        cur.execute(
            "SELECT id, username, password_hash, role, is_active "
            "FROM users WHERE username = %s",
            (username,),
        )
        row = cur.fetchone()
    return dict(row) if row else None


def _update_password_hash(conn, user_id: int, new_hash: str) -> None:
    """Update a user's password hash (rehash on login, D-12)."""
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE users SET password_hash = %s WHERE id = %s",
            (new_hash, user_id),
        )


@router.post("/login")
def login(request: Request, body: dict) -> dict:
    """Authenticate and issue a signed-cookie session with CSRF token.

    Request body: {"username": str, "password": str}

    Returns: {"status": "ok", "csrf_token": str, "role": str, "username": str}

    Raises:
        401: invalid credentials or inactive account.
    """
    username = body.get("username", "")
    password = body.get("password", "")
    if not username or not password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Username and password are required.",
        )

    conn = _get_db(request)
    user = _fetch_user(conn, username)
    if user is None or not user["is_active"]:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials.",
        )

    hasher = _get_hasher()
    try:
        hasher.verify(user["password_hash"], password)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials.",
        )

    # D-12: check_needs_rehash on successful login.
    if hasher.check_needs_rehash(user["password_hash"]):
        new_hash = hasher.hash(password)
        _update_password_hash(conn, user["id"], new_hash)
        log.info("rehashed password for user %s on login", username)

    # Issue the session with a fresh per-session CSRF token (trap 10).
    csrf_token = secrets.token_urlsafe(32)
    request.session.clear()
    request.session[SESSION_USER_ID] = str(user["id"])
    request.session[SESSION_USERNAME] = user["username"]
    request.session[SESSION_ROLE] = user["role"]
    request.session[SESSION_CSRF_TOKEN] = csrf_token

    return {
        "status": "ok",
        "csrf_token": csrf_token,
        "role": user["role"],
        "username": user["username"],
    }


@router.post("/logout")
def logout(request: Request, user: dict = Depends(require_authenticated)) -> dict:
    """Clear the session (requires auth + CSRF)."""
    request.session.clear()
    return {"status": "ok"}


@router.get("/me")
def me(user: dict = Depends(current_user)) -> dict:
    """Return the current session user (requires auth, no CSRF needed — GET)."""
    return {
        "user_id": user["user_id"],
        "username": user["username"],
        "role": user["role"],
    }


# --- Representative mutating route for negative tests ---
@router.post("/admin-only")
def admin_only(user: dict = Depends(require_admin)) -> dict:
    """A representative admin-only mutating route for negative tests.

    Steps 5+ add real mutating routes (entries, accounts, etc.), each
    wiring ``require_admin`` the same way.  This stub exists so the
    Step 4 test suite can prove the role gate and CSRF work end-to-end.
    """
    return {"status": "ok", "actor": user["username"]}