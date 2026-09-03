"""Tax reporting adapter: load and compute tax liability summaries (Step 11).

Bridges domain tax summary types with database queries for tax reporting.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from reports.tax_summary import (
    TaxByJurisdictionRow,
    TaxByJurisdictionSummary,
    TaxFilingStatusRow,
    TaxFilingStatusSummary,
    TaxLiabilityRow,
    TaxLiabilitySummary,
)

if TYPE_CHECKING:
    import psycopg


def tax_liability_summary(
    conn: psycopg.Connection,
    jurisdiction_code: str | None = None,
    status_filter: str | None = None,
) -> TaxLiabilitySummary:
    """Load tax liability summary by period and jurisdiction.

    Args:
        conn: Database connection.
        jurisdiction_code: Filter to specific jurisdiction (None = all).
        status_filter: Filter to specific status (None = all).

    Returns:
        TaxLiabilitySummary with rows and aggregates.
    """
    with conn.cursor() as cur:
        query = """
            SELECT
                tj.code,
                tj.name,
                tl.period_end,
                tl.collected_cents,
                tl.paid_cents,
                tl.status
            FROM tax_liability tl
            JOIN tax_jurisdictions tj ON tl.jurisdiction_id = tj.id
            WHERE 1=1
        """
        params = []

        if jurisdiction_code:
            query += " AND tj.code = %s"
            params.append(jurisdiction_code)

        if status_filter:
            query += " AND tl.status = %s"
            params.append(status_filter)

        query += " ORDER BY tl.period_end DESC, tj.code"

        cur.execute(query, params)
        rows = cur.fetchall()

    liability_rows = []
    total_collected = 0
    total_paid = 0

    for row in rows:
        code, name, period_end, collected, paid, status = row
        balance = collected - paid
        liability_rows.append(
            TaxLiabilityRow(
                jurisdiction_code=code,
                jurisdiction_name=name,
                period_end=period_end,
                collected_cents=collected,
                paid_cents=paid,
                balance_cents=balance,
                status=status,
            )
        )
        total_collected += collected
        total_paid += paid

    return TaxLiabilitySummary(
        rows=tuple(liability_rows),
        total_collected_cents=total_collected,
        total_paid_cents=total_paid,
        total_balance_cents=total_collected - total_paid,
    )


def tax_by_jurisdiction_summary(
    conn: psycopg.Connection,
    active_only: bool = True,
) -> TaxByJurisdictionSummary:
    """Load tax summary aggregated by jurisdiction.

    Args:
        conn: Database connection.
        active_only: Only include active jurisdictions.

    Returns:
        TaxByJurisdictionSummary with jurisdiction breakdowns.
    """
    with conn.cursor() as cur:
        query = """
            SELECT
                tj.code,
                tj.name,
                tj.tax_type,
                tj.active,
                COALESCE(SUM(tl.collected_cents), 0) as total_collected,
                COALESCE(SUM(tl.paid_cents), 0) as total_paid,
                COUNT(DISTINCT tl.period_end) as period_count
            FROM tax_jurisdictions tj
            LEFT JOIN tax_liability tl ON tj.id = tl.jurisdiction_id
            WHERE 1=1
        """
        params = []

        if active_only:
            query += " AND tj.active = true"

        query += " GROUP BY tj.id, tj.code, tj.name, tj.tax_type, tj.active"
        query += " ORDER BY total_collected DESC, tj.code"

        cur.execute(query, params)
        rows = cur.fetchall()

    jur_rows = []
    total_collected = 0
    total_paid = 0

    for row in rows:
        code, name, tax_type, active, collected, paid, period_count = row
        outstanding = collected - paid
        jur_rows.append(
            TaxByJurisdictionRow(
                jurisdiction_code=code,
                jurisdiction_name=name,
                tax_type=tax_type,
                active=active,
                total_collected_cents=collected,
                total_paid_cents=paid,
                outstanding_cents=outstanding,
                period_count=period_count,
            )
        )
        total_collected += collected
        total_paid += paid

    return TaxByJurisdictionSummary(
        rows=tuple(jur_rows),
        total_collected_cents=total_collected,
        total_paid_cents=total_paid,
        total_outstanding_cents=total_collected - total_paid,
        jurisdiction_count=len([r for r in rows if r[3]]),  # count active
    )


def tax_filing_status_summary(
    conn: psycopg.Connection,
    status_filter: str | None = None,
) -> TaxFilingStatusSummary:
    """Load tax filing status summary.

    Args:
        conn: Database connection.
        status_filter: Filter to specific status (draft, filed, paid, reconciled).

    Returns:
        TaxFilingStatusSummary with filing details and counts.
    """
    with conn.cursor() as cur:
        query = """
            SELECT
                tj.code,
                tj.name,
                tf.filing_period_start,
                tf.filing_period_end,
                tf.filing_type,
                tf.status,
                tf.total_sales_cents,
                tf.tax_collected_cents,
                tf.tax_paid_cents,
                tf.filing_date,
                tf.reference_number
            FROM tax_filings tf
            JOIN tax_jurisdictions tj ON tf.jurisdiction_id = tj.id
            WHERE 1=1
        """
        params = []

        if status_filter:
            query += " AND tf.status = %s"
            params.append(status_filter)

        query += " ORDER BY tf.filing_period_end DESC, tj.code"

        cur.execute(query, params)
        rows = cur.fetchall()

    filing_rows = []
    status_counts = {
        "draft": 0,
        "filed": 0,
        "paid": 0,
        "reconciled": 0,
    }

    for row in rows:
        (
            code,
            name,
            period_start,
            period_end,
            filing_type,
            status,
            total_sales,
            tax_collected,
            tax_paid,
            filing_date,
            reference_number,
        ) = row

        filing_rows.append(
            TaxFilingStatusRow(
                jurisdiction_code=code,
                jurisdiction_name=name,
                period_start=period_start,
                period_end=period_end,
                filing_type=filing_type,
                status=status,
                total_sales_cents=total_sales,
                tax_collected_cents=tax_collected,
                tax_paid_cents=tax_paid,
                filing_date=filing_date,
                reference_number=reference_number,
            )
        )

        if status in status_counts:
            status_counts[status] += 1

    return TaxFilingStatusSummary(
        rows=tuple(filing_rows),
        pending_count=status_counts["draft"],
        filed_count=status_counts["filed"],
        paid_count=status_counts["paid"],
        reconciled_count=status_counts["reconciled"],
    )
