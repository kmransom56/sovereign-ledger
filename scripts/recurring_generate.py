#!/usr/bin/env python3
"""Generate and post invoices for recurring templates (Step 9 automation).

This script is meant to run nightly via systemd timer. It:
  1. Connects to the database
  2. Finds all active recurring templates
  3. For each template, determines if it's due for generation based on last cycle
  4. Calls generate_and_post_recurring() for each due template
  5. Logs results and skipped templates

Locked decisions honored:
  - D-10: Gapless invoice numbering (handled by ar_posting.post_invoice)
  - D-7: Serializable allocation retry (handled by ar_posting.post_payment)
  - HR-8: Overpayment → customer_credits liability
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

# Add repo root to path
repo_root = Path(__file__).parent.parent
sys.path.insert(0, str(repo_root))

import psycopg

from app.adapters.ar_posting import generate_and_post_recurring
from config.settings import get_settings

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def get_next_cycle_date(
    template_id: int,
    template_status: str,
    last_generated: date | None,
    active_from: date,
    active_until: date | None,
) -> date | None:
    """Determine the next cycle date for a template.

    Rules:
      - Template must be active
      - Must be within active_from/active_until range
      - Default cycle is 1st of month (can be overridden)
      - If this month's 1st has passed and no generation yet, generate now
      - If last generated was before this month, generate this month

    Args:
        template_id: Template ID (for logging)
        template_status: Template status (active/paused/ended)
        last_generated: Last successful generation date
        active_from: Template becomes active on this date
        active_until: Template ends on this date (or None for ongoing)

    Returns:
        The date to generate for, or None if not due.
    """
    if template_status != "active":
        logger.debug(f"Template {template_id}: status is {template_status}, skipping")
        return None

    today = date.today()

    # Check if we're within the active range
    if today < active_from:
        logger.debug(f"Template {template_id}: not yet active (starts {active_from})")
        return None

    if active_until and today > active_until:
        logger.debug(f"Template {template_id}: ended (was until {active_until})")
        return None

    # Default cycle: 1st of month
    cycle_date = date(today.year, today.month, 1)

    # If last_generated is this month or later, not due yet
    if last_generated and last_generated.year == today.year and last_generated.month == today.month:
        logger.debug(f"Template {template_id}: already generated this month ({last_generated})")
        return None

    # Due for this month's cycle
    return cycle_date


def main(
    dry_run: bool = False,
    specific_template_id: int | None = None,
    specific_cycle_date: date | None = None,
) -> int:
    """Main entry point for recurring generation.

    Args:
        dry_run: If True, log but don't actually insert anything.
        specific_template_id: If provided, only process this template (for testing/retry).
        specific_cycle_date: If provided with template_id, use this cycle date.

    Returns:
        Exit code (0 = success, 1 = error).
    """
    settings = get_settings()

    logger.info(
        f"Starting recurring invoice generation "
        f"(dry_run={dry_run}, as_of={date.today()})"
    )

    try:
        conn = psycopg.connect(
            host=settings.db_host,
            port=settings.db_port,
            user=settings.db_user,
            password=settings.db_password,
            dbname=settings.db_name,
        )
    except Exception as exc:
        logger.error(f"Failed to connect to database: {exc}")
        return 1

    try:
        # Determine which templates to process
        if specific_template_id:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, status, active_from, active_until "
                    "FROM recurring_templates WHERE id = %s",
                    (specific_template_id,),
                )
                row = cur.fetchone()
                if not row:
                    logger.error(f"Template {specific_template_id} not found")
                    return 1
            templates_to_process = [row]
        else:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, status, active_from, active_until "
                    "FROM recurring_templates ORDER BY id"
                )
                templates_to_process = cur.fetchall()

        logger.info(f"Found {len(templates_to_process)} template(s) to check")

        success_count = 0
        skip_count = 0
        error_count = 0

        for template_id, template_status, active_from, active_until in templates_to_process:
            # Determine last generation for this template
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT MAX(cycle_date) FROM recurring_generations WHERE template_id = %s AND success = true",
                    (template_id,),
                )
                row = cur.fetchone()
                last_generated = row[0] if row else None

            # Determine if this template is due
            if specific_cycle_date:
                # Override with specific date (for testing)
                cycle_date = specific_cycle_date
            else:
                cycle_date = get_next_cycle_date(
                    template_id, template_status, last_generated, active_from, active_until
                )

            if not cycle_date:
                skip_count += 1
                continue

            logger.info(f"Template {template_id}: due for cycle {cycle_date}")

            if dry_run:
                logger.info(f"[DRY RUN] Would generate invoice for template {template_id}")
                success_count += 1
                continue

            # Generate and post
            try:
                invoice_id, error_msg = generate_and_post_recurring(conn, template_id, cycle_date)
                if error_msg:
                    logger.error(f"Template {template_id}: {error_msg}")
                    error_count += 1
                else:
                    logger.info(f"Template {template_id}: generated invoice {invoice_id}")
                    success_count += 1
            except Exception as exc:
                logger.error(f"Template {template_id}: unexpected error: {exc}")
                error_count += 1

        conn.close()

        logger.info(
            f"Recurring generation complete: "
            f"{success_count} succeeded, {skip_count} skipped, {error_count} failed"
        )

        return 0 if error_count == 0 else 1

    except Exception as exc:
        logger.error(f"Unexpected error: {exc}")
        return 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Generate and post invoices for active recurring templates."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Log what would be generated without actually inserting records",
    )
    parser.add_argument(
        "--template-id",
        type=int,
        help="Only process this specific template (for testing/retry)",
    )
    parser.add_argument(
        "--cycle-date",
        type=lambda s: date.fromisoformat(s),
        help="Override cycle date (ISO format: YYYY-MM-DD, use with --template-id)",
    )

    args = parser.parse_args()

    exit_code = main(
        dry_run=args.dry_run,
        specific_template_id=args.template_id,
        specific_cycle_date=args.cycle_date,
    )
    sys.exit(exit_code)
