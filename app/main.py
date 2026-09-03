"""Sovereign Ledger FastAPI app factory + session middleware wiring (Step 4).

Creates the FastAPI app, mounts itsdangerous signed-cookie session
middleware (SameSite=Strict, Secure, HttpOnly — D-11/trap 10), and
registers the auth router.  Later steps (5+) add more routers here.

The app factory pattern keeps tests flexible: each TestClient can spin
up an app with test-specific settings (session secret, cookie_secure=False
for HTTP) without mutating global state.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware

from config.settings import Settings, get_settings

if TYPE_CHECKING:  # pragma: no cover
    from app.routes.auth import AuthRouter


def create_app(
    *,
    settings: Settings | None = None,
    cookie_secure_override: bool | None = None,
) -> FastAPI:
    """Build the FastAPI app with session middleware + auth router.

    Args:
        settings: inject settings (tests); defaults to the lru_cache singleton.
        cookie_secure_override: force the cookie Secure flag regardless of
            settings (tests use False to inspect cookies over HTTP).
    """
    s = settings or get_settings()

    app = FastAPI(
        title="Sovereign Ledger",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    # D-11 / trap 10: signed cookies, SameSite=Strict, HttpOnly.
    app.add_middleware(
        SessionMiddleware,
        secret_key=s.session_secret,
        same_site="strict",
        https_only=cookie_secure_override if cookie_secure_override is not None else s.cookie_secure,
        session_cookie="ledger_session",
        max_age=s.session_ttl_hours * 3600,
    )

    # Register routers (Step 4: auth; Step 5: accounts, entries, reports;
    # Step 7: bank upload, import review, reconciliation; Step 9: AR posting;
    # Step 10: customer portal; Step 11: tax management & reporting).
    from app.routes.auth import router as auth_router
    from app.routes.accounts import router as accounts_router
    from app.routes.entries import router as entries_router
    from app.routes.reports import router as reports_router
    from app.routes.bank import router as bank_router
    from app.routes.import_review import router as review_router
    from app.routes.reconcile import router as reconcile_router
    from app.routes.ar import router as ar_router
    from app.routes.portal import router as portal_router
    from app.routes.tax_management import router as tax_router
    from app.routes.tax_reports import router as tax_reports_router
    from app.routes.tax_lifecycle import router as tax_lifecycle_router

    app.include_router(auth_router)
    app.include_router(accounts_router)
    app.include_router(entries_router)
    app.include_router(reports_router)
    app.include_router(bank_router)
    app.include_router(review_router)
    app.include_router(reconcile_router)
    app.include_router(ar_router)
    app.include_router(portal_router)
    app.include_router(tax_router)
    app.include_router(tax_reports_router)
    app.include_router(tax_lifecycle_router)

    @app.get("/healthz", tags=["meta"])
    def healthz() -> dict[str, str]:
        """Liveness probe — no auth required."""
        return {"status": "ok"}

    return app