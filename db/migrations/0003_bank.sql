-- ============================================================================
-- 0003_bank.sql — Bank import schema (Step 6, D-9/HR-4/CK-2)
--
-- Implements:
--   D-9   canonicalized content hash (NEVER raw bytes) — batch + per-line
--   HR-4  import idempotency: same statement re-imported → zero duplicates
--   CK-2  versioned per-account import profiles
--   trap 7 import idempotency hashes canonicalized content
--   trap 12 per-account profile versioning
--
-- Tables (creation order respects FK dependencies):
--   import_profiles  — per-account column-mapping profiles, version-stamped
--   bank_accounts    — 1:1 mapping to ledger accounts, FK to import_profiles
--   import_batches   — one per import file, content_hash UNIQUE (idempotency key)
--   bank_lines       — individual parsed lines from a batch, per-line hash
--
-- bank_lines are DRAFTS (HR-5): they are never auto-posted.  Step 7 adds
-- the review/accept/reconcile flow; this migration only stores the parsed
-- identity and content hash.
-- ============================================================================

-- import_profiles FIRST (no FK dependencies, referenced by bank_accounts)
CREATE TABLE import_profiles (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    bank_account_id BIGINT,                           -- self-ref deferred; set after bank_accounts exists
    version_number  INTEGER NOT NULL DEFAULT 1,
    column_map      JSONB NOT NULL,                   -- {date_col, amount_col, desc_col, ...}
    date_format     TEXT NOT NULL DEFAULT '%Y-%m-%d',
    encoding_hint   TEXT,                             -- e.g. 'cp1252', or NULL to auto-sniff
    is_active        BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- bank_accounts SECOND (FK to accounts + import_profiles)
CREATE TABLE bank_accounts (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name            TEXT NOT NULL UNIQUE,             -- e.g. 'Checking'
    account_id      BIGINT NOT NULL REFERENCES accounts (id),
    import_profile_id BIGINT REFERENCES import_profiles (id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Now link import_profiles.bank_account_id back to bank_accounts (can't FK
-- in the CREATE because bank_accounts doesn't exist yet).  We add the FK
-- constraint here.
ALTER TABLE import_profiles
    ADD CONSTRAINT import_profiles_bank_account_fk
    FOREIGN KEY (bank_account_id) REFERENCES bank_accounts (id);

-- import_batches: one per file import.  content_hash is the CANONICALIZED
-- file hash (D-9) — the same statement re-imported under a different
-- filename produces the same hash and is refused (HR-4/T-2).
CREATE TABLE import_batches (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    bank_account_id BIGINT NOT NULL REFERENCES bank_accounts (id),
    profile_id      BIGINT REFERENCES import_profiles (id),
    filename        TEXT NOT NULL,                    -- original filename (informational)
    content_hash    TEXT NOT NULL UNIQUE,             -- canonicalized content hash (D-9)
    line_count      INTEGER NOT NULL DEFAULT 0,
    imported_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Individual parsed bank lines.  Per-line hash (D-9) dedupes across
-- overlapping statements (same transaction in two exports).
CREATE TABLE bank_lines (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    batch_id        BIGINT NOT NULL REFERENCES import_batches (id),
    transaction_date DATE NOT NULL,
    description     TEXT NOT NULL DEFAULT '',
    amount_cents    BIGINT NOT NULL,                  -- signed: + = deposit, - = withdrawal
    line_hash       TEXT NOT NULL,                    -- canonicalized per-line hash (D-9)
    fitid           TEXT,                              -- OFX FITID (NULL for CSV)
    status          TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'accepted', 'rejected', 'reconciled')),
    posted_entry_id BIGINT REFERENCES journal_entries (id),
    UNIQUE (batch_id, line_hash)
);

CREATE INDEX idx_bank_lines_batch   ON bank_lines (batch_id);
CREATE INDEX idx_bank_lines_status  ON bank_lines (status);
CREATE INDEX idx_bank_lines_hash    ON bank_lines (line_hash);
CREATE INDEX idx_import_batches_hash ON import_batches (content_hash);

-- Grant the app role access.
GRANT SELECT, INSERT ON bank_accounts, import_profiles, import_batches, bank_lines TO ledger_app;
GRANT UPDATE ON bank_lines TO ledger_app;  -- status transitions (pending→accepted etc.)
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO ledger_app;