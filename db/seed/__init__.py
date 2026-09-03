"""Sovereign Ledger seed data package.

Seed modules load reference data (chart of accounts, fiscal periods) into a
migrated database. Seeding is idempotent: re-running a seed never duplicates
or mutates existing rows.
"""