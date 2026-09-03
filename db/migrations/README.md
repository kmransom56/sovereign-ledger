# Sovereign Ledger — SQL migrations

## Numeric-order contract

Migrations are plain, ordered SQL files: `0001_core.sql`, `0002_ar.sql`, ...
No Alembic / SQLAlchemy (decision D-5). A migration file name MUST match
`NNNN_name.sql` (4-digit numeric prefix, lowercase snake_case name). Files are
applied strictly in ascending numeric order by `scripts/init_db.py`, which:

1. Asserts no numeric gaps in the present file set (a gap means a migration
   was lost — abort, never guess).
2. Refuses out-of-order application (e.g. `0003_...` cannot run before
   `0002_...` is applied; init_db aborts rather than skipping a missing file).
3. Tracks applied files in `schema_migrations` (name + applied_at), so re-runs
   are idempotent: applied files are skipped, new files append in order.

## Roadmap

| File | Priority | Scope | Depends on |
|---|---|---|---|
| `0001_core.sql` | P0 | Core append-only tables, deferred balance trigger, block-triggers, `ledger_app` role + grants/revocations, audit log | — |
| `0002_ar.sql` | P3 | Accounts receivable (customers, invoices, invoice lines) | 0001 |
| `0003_ap.sql` | P4 | Accounts payable (vendors, bills, bill lines) | 0001 |
| `0004_bank.sql` | P2 | Bank feeds / reconciliation (bank accounts, imported transactions, matches) | 0001 |
| `0005_access.sql` | P6 | User access control (users, roles, memberships) | 0001 |
| `0006_recurring.sql` | P3 | Recurring journal entry templates | 0001 |

## Refusal of gaps

If the set of migration files on disk is not a gap-free numeric sequence
`0001..N`, `scripts/init_db.py` refuses to run and exits non-zero. Never fill
a gap by renumbering an existing migration: append-only, immutable files.