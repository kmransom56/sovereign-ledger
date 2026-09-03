-- ============================================================================
-- 0001_core.sql — Sovereign Ledger core schema (PostgreSQL 16, D-2)
--
-- P0 foundation. Implements locked decisions:
--   D-2  PostgreSQL 16 sole system of record
--   D-3  signed BIGINT cents (+ debit / − credit), no floats, no `money`
--   D-6  per-entry DEFERRABLE INITIALLY DEFERRED balance trigger
--   D-8  append-only history; hash-chained audit_log
-- plus the privilege half of the defense in depth (SKILL.md layout
-- invariants): block-UPDATE/DELETE triggers AND `REVOKE UPDATE, DELETE`
-- from the `ledger_app` role on the four append-only tables.
--
-- COMMIT-TIME REJECTION SEMANTICS (read before debugging a failing COMMIT)
-- ---------------------------------------------------------------------------
-- `trg_entry_balanced` is a CONSTRAINT TRIGGER declared DEFERRABLE INITIALLY
-- DEFERRED (SKILL.md trap 4). It does NOT run while lines are being inserted:
-- it waits until COMMIT, then re-checks that every entry touched by a line
-- INSERT sums to exactly 0 signed cents. Consequences:
--   * An unbalanced entry raises its error at conn.commit() — NOT at INSERT
--     time. The failed COMMIT aborts the transaction; every row written by
--     that transaction (entries, lines, and anything else) is rolled back:
--     nothing is stored.
--   * Mid-transaction unbalanced states are legal and expected: you insert
--     the debit before the credit. Do NOT "fix" this into a plain row
--     trigger — a plain trigger fires per line and would reject the first
--     line of every two-line entry.
--   * Tests/tools that want eager checking can SET CONSTRAINTS
--     trg_entry_balanced IMMEDIATE (checks at the end of each statement).
--   * `trg_entry_has_lines` (below) rejects at COMMIT an entry that reached
--     COMMIT with zero lines — SUM of no rows is 0, so the balance trigger
--     alone would silently accept an empty entry.
--   * The pure posting core (ledger/, HR-1) must refuse unbalanced entries on
--     every path before storage; this trigger is the storage-boundary
--     backstop, not the primary defense.
--
-- APPEND-ONLY ENFORCEMENT (HR-2)
-- ---------------------------------------------------------------------------
-- The four append-only tables (accounts, journal_entries, journal_lines,
-- fiscal_periods) are protected twice:
--   1. BEFORE UPDATE OR DELETE row triggers raise an exception (covers the
--      table OWNER too — owners bypass privilege checks, not triggers);
--   2. `REVOKE UPDATE, DELETE ... FROM ledger_app` (covers every non-owner
--      role: permission denied before any trigger even fires).
-- audit_log gets the same treatment additively: its HR-10 hash chain is
-- meaningless if rows can be mutated. Corrections are reversing entries only
-- (D-8). TRUNCATE/DROP remain owner-level operations covered by backup
-- discipline (backup.sh, P6) — they are not grantable protections.
--
-- Role model: migrations run as the database OWNER (e.g. `ledger`). The app
-- runtime role `ledger_app` is NOLOGIN; the application connects as a LOGIN
-- role that is a member of `ledger_app` (or SET ROLEs into it). Step 5 wires
-- that LOGIN role up; this migration only creates the least-privilege role
-- and its grants.
-- ============================================================================

-- ----------------------------------------------------------- fiscal_periods --
CREATE TABLE fiscal_periods (
    id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name       TEXT NOT NULL UNIQUE,          -- e.g. '2026-09'
    year       INTEGER NOT NULL,
    start_date DATE NOT NULL,
    end_date   DATE NOT NULL,
    status     TEXT NOT NULL DEFAULT 'open'
               CHECK (status IN ('open', 'closed', 'locked')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fiscal_periods_date_order CHECK (end_date >= start_date)
);

-- ----------------------------------------------------------------- accounts --
CREATE TABLE accounts (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name         TEXT NOT NULL UNIQUE,        -- human-readable, code-prefixed
    account_type TEXT NOT NULL
                 CHECK (account_type IN
                        ('Assets', 'Liabilities', 'Equity', 'Income', 'Expenses')),
    subtype      TEXT NOT NULL,               -- fine-grained grouping for reports
    tax_mapping  TEXT,                        -- e.g. 'Schedule C, Line 1' (tax/, P5)
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ----------------------------------------------------------- journal_entries --
CREATE TABLE journal_entries (
    id               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    entry_date       DATE NOT NULL,
    description      TEXT NOT NULL,
    fiscal_period_id BIGINT NOT NULL REFERENCES fiscal_periods (id),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ------------------------------------------------------------- journal_lines --
CREATE TABLE journal_lines (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    entry_id     BIGINT NOT NULL REFERENCES journal_entries (id),
    account_id   BIGINT NOT NULL REFERENCES accounts (id),
    amount_cents BIGINT NOT NULL
                 CONSTRAINT journal_lines_amount_domain CHECK (amount_cents <> 0),
                 -- signed domain per D-3: + = debit, − = credit; zero carries
                 -- no information and is refused at the storage boundary.
    memo         TEXT
);

-- ---------------------------------------------------------------- audit_log --
-- Hash-chained audit trail (HR-10 / D-8): each row commits to `prev_hash`
-- (the `hash` of the previous row) and its own `hash`. Rows are append-only;
-- chain verification belongs to the audit modules (ledger/audit.py, P0).
CREATE TABLE audit_log (
    id        BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ts        TIMESTAMPTZ NOT NULL DEFAULT now(),
    actor     TEXT NOT NULL,
    action    TEXT NOT NULL,
    entity    TEXT NOT NULL,
    entity_id TEXT,                           -- polymorphic target id
    prev_hash TEXT,                           -- NULL only for the genesis row
    hash      TEXT NOT NULL
);

-- ------------------------------------------------------------------ indexes --
CREATE INDEX idx_journal_lines_entry   ON journal_lines (entry_id);
CREATE INDEX idx_journal_lines_account ON journal_lines (account_id);
CREATE INDEX idx_journal_entries_date  ON journal_entries (entry_date);
CREATE INDEX idx_audit_log_entity      ON audit_log (entity, entity_id);

-- ============================================================
-- Per-entry balance invariant (SKILL.md trap 4 pattern, D-6)
-- ============================================================

CREATE OR REPLACE FUNCTION assert_entry_sum_zero() RETURNS trigger AS $$
BEGIN
  IF (SELECT COALESCE(SUM(amount_cents), 0) FROM journal_lines
      WHERE entry_id = NEW.entry_id) <> 0 THEN
    RAISE EXCEPTION 'journal entry % is not balanced', NEW.entry_id;
  END IF;
  RETURN NULL;
END $$ LANGUAGE plpgsql;

CREATE CONSTRAINT TRIGGER trg_entry_balanced
  AFTER INSERT ON journal_lines
  DEFERRABLE INITIALLY DEFERRED
  FOR EACH ROW EXECUTE FUNCTION assert_entry_sum_zero();

-- Defense in depth (D-6): an entry reaching COMMIT with zero lines passes the
-- sum-zero check vacuously (SUM of no rows = 0). Reject it at COMMIT too.
CREATE OR REPLACE FUNCTION assert_entry_has_lines() RETURNS trigger AS $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM journal_lines WHERE entry_id = NEW.id) THEN
    RAISE EXCEPTION 'journal entry % has no lines', NEW.id;
  END IF;
  RETURN NULL;
END $$ LANGUAGE plpgsql;

CREATE CONSTRAINT TRIGGER trg_entry_has_lines
  AFTER INSERT ON journal_entries
  DEFERRABLE INITIALLY DEFERRED
  FOR EACH ROW EXECUTE FUNCTION assert_entry_has_lines();

-- ============================================================
-- Append-only enforcement (HR-2): triggers first...
-- ============================================================

CREATE OR REPLACE FUNCTION forbid_append_only_mutation() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION '% is append-only: % is forbidden (corrections are reversing entries — D-8)',
                 TG_TABLE_NAME, TG_OP;
END $$ LANGUAGE plpgsql;

CREATE TRIGGER trg_accounts_append_only
  BEFORE UPDATE OR DELETE ON accounts
  FOR EACH ROW EXECUTE FUNCTION forbid_append_only_mutation();

CREATE TRIGGER trg_journal_entries_append_only
  BEFORE UPDATE OR DELETE ON journal_entries
  FOR EACH ROW EXECUTE FUNCTION forbid_append_only_mutation();

CREATE TRIGGER trg_journal_lines_append_only
  BEFORE UPDATE OR DELETE ON journal_lines
  FOR EACH ROW EXECUTE FUNCTION forbid_append_only_mutation();

CREATE TRIGGER trg_fiscal_periods_append_only
  BEFORE UPDATE OR DELETE ON fiscal_periods
  FOR EACH ROW EXECUTE FUNCTION forbid_append_only_mutation();

-- audit_log is not one of the four ledger tables but its hash chain (HR-10)
-- is equally worthless if rows can be edited — protect it the same way.
CREATE TRIGGER trg_audit_log_append_only
  BEFORE UPDATE OR DELETE ON audit_log
  FOR EACH ROW EXECUTE FUNCTION forbid_append_only_mutation();

-- ============================================================
-- ... and privilege revocations (SKILL.md layout invariants)
-- ============================================================

DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'ledger_app') THEN
    CREATE ROLE ledger_app NOLOGIN;
  END IF;
END $$;

-- Hardened default (PG15+ already does this; made explicit here): no ad-hoc
-- object creation in the ledger schema.
REVOKE CREATE ON SCHEMA public FROM PUBLIC;

GRANT USAGE ON SCHEMA public TO ledger_app;
GRANT SELECT, INSERT ON accounts, journal_entries, journal_lines,
                         fiscal_periods, audit_log TO ledger_app;
-- Identity columns draw from sequences: INSERT needs sequence USAGE.
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO ledger_app;

-- The heart of HR-2: even if a future migration forgets a block trigger, the
-- app role has no UPDATE/DELETE path on the append-only tables. (The owner
-- bypasses REVOKE — that is what the triggers above are for.)
REVOKE UPDATE, DELETE ON accounts, journal_entries, journal_lines,
                         fiscal_periods, audit_log FROM ledger_app;