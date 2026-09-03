"""Auth dependencies: session, CSRF, role gate (Step 4, D-11/D-12/CK-12).

The single choke point every mutating route uses: ``require_admin``
verifies the session is authenticated, the CSRF token matches, and the
user holds the admin role.  Read-only routes use ``current_user`` (auth
without the admin requirement) so the accountant role can GET but not
POST/PUT/DELETE.

CSRF enforcement (trap 10): every POST/PUT/DELETE must carry the
``X-CSRF-Token`` header matching the per-session token stored in the
session.  SameSite=Strict alone is insufficient because two roles share
the browser.
"""

from __future__ import annotations

import secrets
from typing import TYPE_CHECKING

from fastapi import Depends, HTTPException, Request, status
from starlette.requests import HTTPConnection

from config.settings import ROLE_ACCOUNTANT, ROLE_ADMIN

if TYPE_CHECKING:  # pragma: no cover
    pass

#: The header name carrying the per-session CSRF token (trap 10).
CSRF_HEADER = "X-CSRF-Token"

#: Session key for the authenticated user id.
SESSION_USER_ID = "user_id"

#: Session key for the username (for display, not auth decisions).
SESSION_USERNAME = "username"

#: Session key for the user role.
SESSION_ROLE = "role"

#: Session key for the per-session CSRF token.
SESSION_CSRF_TOKEN = "csrf_token"


def _get_session_user(request: Request) -> dict[str, str] | None:
    """Extract the authenticated user from the session, or None."""
    if SESSION_USER_ID not in request.session:
        return None
    return {
        "user_id": request.session[SESSION_USER_ID],
        "username": request.session.get(SESSION_USERNAME, ""),
        "role": request.session.get(SESSION_ROLE, ""),
    }


def current_user(request: Request) -> dict[str, str]:
    """Require an authenticated session; return user info.

    Raises:
        HTTPException 401: no session or session expired.
    """
    user = _get_session_user(request)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated — log in first.",
        )
    return user


def _verify_csrf(request: Request) -> None:
    """Verify the per-session CSRF token header (trap 10).

    Raises:
        HTTPException 403: missing or mismatched CSRF token.
    """
    expected = request.session.get(SESSION_CSRF_TOKEN)
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No CSRF token in session — re-authenticate.",
        )
    provided = request.headers.get(CSRF_HEADER)
    if not provided:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Missing {CSRF_HEADER} header (CSRF protection — trap 10).",
        )
    if not secrets.compare_digest(expected, provided):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF token mismatch.",
        )


def require_admin(request: Request) -> dict[str, str]:
    """Require admin role + CSRF verification — the mutating-route choke point.

    This is the single dependency every POST/PUT/DELETE route wires so no
    mutating route can bypass auth, CSRF, or the role gate (CK-12).

    Raises:
        HTTPException 401: not authenticated.
        HTTPException 403: CSRF failure or non-admin role.
    """
    user = current_user(request)
    _verify_csrf(request)
    if user["role"] != ROLE_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Role '{user['role']}' is read-only — admin role required for this action (CK-12).",
        )
    return user


def require_authenticated(request: Request) -> dict[str, str]:
    """Require authentication + CSRF verification (but any role).

    Used by routes where both admin and accountant can POST (e.g. logout).
    """
    user = current_user(request)
    _verify_csrf(request)
    return user