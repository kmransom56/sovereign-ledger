"""Fiscal period seed for the sovereign ledger.

Seeds twelve monthly fiscal periods for a given year (default 2026).
Idempotent: ON CONFLICT (name) DO NOTHING.
"""

from __future__ import annotations

import calendar
import logging
from datetime import date

import psycopg

log = logging.getLogger("seed.periods")

DEFAULT_YEAR = 2026


def seed(conn: psycopg.Connection, *, year: int = DEFAULT_YEAR) -> int:
    """Insert twelve monthly fiscal periods for ``year``.

    Returns:
        Number of rows actually inserted this run (0 on re-run).
    """
    inserted = 0
    with conn.cursor() as cur:
        for month in range(1, 13):
            last_day = calendar.monthrange(year, month)[1]
            name = f"{year:04d}-{month:02d}"
            cur.execute(
                """
                INSERT INTO fiscal_periods (name, year, start_date, end_date, status)
                VALUES (%s, %s, %s, %s, 'open')
                ON CONFLICT (name) DO NOTHING
                """,
                (name, year, date(year, month, 1), date(year, month, last_day)),
            )
            inserted += cur.rowcount
    return inserted