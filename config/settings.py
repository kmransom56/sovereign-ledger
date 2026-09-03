"""Env-driven application settings (pydantic-settings).

No secrets live in the repository: the values below are local-development
defaults only; real deployments override them via the environment:

    LEDGER_DATABASE_URL      PostgreSQL DSN (default points at the loopback
                             quadlet DB on port 11241)
    LEDGER_HOST              uvicorn bind host (default 0.0.0.0)
    LEDGER_PORT              uvicorn bind port (default 11240)
    LEDGER_LOG_LEVEL         or bare LOG_LEVEL — logging verbosity (INFO)
    LEDGER_SESSION_SECRET    signed-cookie secret (REQUIRED in production;
                             no insecure default — tests set it explicitly)
    LEDGER_SESSION_TTL_HOURS session lifetime in hours (default 12)
    LEDGER_COOKIE_SECURE     set-cookie Secure flag (default true; set to
                             'false' for local HTTP dev)

Anything under the ``LEDGER_`` prefix that this schema does not declare is
ignored (``extra="ignore"``) so the environment can carry unrelated vars.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

#: Two-role model (CK-12): admin writes, accountant reads.
ROLE_ADMIN = "admin"
ROLE_ACCOUNTANT = "accountant"


class Settings(BaseSettings):
    """Process configuration; every value is overridable by environment."""

    model_config = SettingsConfigDict(env_prefix="LEDGER_", extra="ignore")

    database_url: str = Field(
        default="postgresql://ledger:ledger@127.0.0.1:11241/ledger",
        description="PostgreSQL DSN for the ledger database (DB lives in db/session.py, never here).",
    )
    host: str = Field(
        default="0.0.0.0",
        description="uvicorn bind host for the app container (rootless podman, port >=1024).",
    )
    port: int = Field(
        default=11240,
        ge=1,
        le=65535,
        description="uvicorn bind port for the app (loopback-only per D-14).",
    )
    log_level: LogLevel = Field(
        default="INFO",
        validation_alias=AliasChoices("LEDGER_LOG_LEVEL", "LOG_LEVEL"),
        description="Root logging level; accepts LEDGER_LOG_LEVEL or bare LOG_LEVEL.",
    )

    # --- Session / auth (D-11, D-12) ---
    session_secret: str = Field(
        default="dev-only-do-not-use-in-production-change-this-now",
        description="itsdangerous signed-cookie secret. MUST be overridden in production.",
    )
    session_ttl_hours: int = Field(
        default=12,
        ge=1,
        le=168,
        description="Session lifetime in hours (default 12).",
    )
    cookie_secure: bool = Field(
        default=True,
        description="Set-cookie Secure flag (true in production; false for local HTTP).",
    )


@lru_cache
def get_settings() -> Settings:
    """Cached accessor so every adapter reads one parsed Settings instance."""
    return Settings()