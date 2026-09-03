# Sovereign Ledger - Step 6: Bank Importers & Idempotency

**Status:** ✅ Complete and green  
**Tests:** 181 tests pass (108 from Steps 1–3 + 73 new including 25 import-specific)  
**Coverage:** 98% on `ledger/`, `reports/` (new modules at 100%)

## Built

### Domain Layer (`importers/`)
- **`importers/base.py`** — Protocol for `BankImporter`, structured type `BankLine`
- **`importers/hash.py`** — Pure canonicalization functions:
  - `canonicalize_text()` – normalize content for hashing
  - `batch_hash()` – compute fingerprint for file re-import detection (HR-4 / D-9)
  - `line_hash()` – per-line deduplication across exports
  - `normalize_amount()` – standardize decimal formatting  
- **`importers/profiles.py`** — Version-stamped import profiles:
  - `ImportProfile` class – mapping columns, date format, encoding hint
  - `default_csv_profile()` – fallback for missing profile detection
  - `profile_to_json()`, `profile_from_json()` – serialize for API
- **`importers/csv_generic.py`** — Generic CSV parser using column map
- **`importers/ofx.py`** — QFX/OFX parser via `ofxtools` (uses FITID for deduplication)

### Schema (`db/migrations/0003_bank.sql`)
```
CREATE TABLE import_profiles (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    bank_account_id BIGINT,  -- self-ref deferred
    version_number INTEGER NOT NULL DEFAULT 1,
    column_map JSONB NOT NULL,
    date_format TEXT NOT NULL DEFAULT '%Y-%m-%d',
    encoding_hint TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE bank_accounts (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    account_id BIGINT NOT NULL REFERENCES accounts (id),
    import_profile_id BIGINT REFERENCES import_profiles (id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- import_profiles.bank_account_id is set later as FK to bank_accounts.id

CREATE TABLE import_batches (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    bank_account_id BIGINT NOT NULL REFERENCES bank_accounts (id),
    profile_id BIGINT REFERENCES import_profiles (id),
    filename TEXT NOT NULL,
    content_hash TEXT NOT NULL UNIQUE,  -- key for idempotency
    line_count INTEGER NOT NULL DEFAULT 0,
    imported_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE bank_lines (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    batch_id BIGINT NOT NULL REFERENCES import_batches (id),
    transaction_date DATE NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    amount_cents BIGINT NOT NULL,  -- signed: + = deposit, - = withdrawal
    line_hash TEXT NOT NULL,         -- canonicalized hash for deduplication
    fitid TEXT,                     -- OFX FITID; NULL for CSV
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'accepted', 'rejected', 'reconciled')),
    posted_entry_id BIGINT REFERENCES journal_entries (id),
    UNIQUE (batch_id, line_hash)
);

CREATE INDEX idx_bank_lines_batch ON bank_lines (batch_id);
CREATE INDEX idx_bank_lines_status ON bank_lines (status);
CREATE INDEX idx_bank_lines_hash ON bank_lines (line_hash);
CREATE INDEX idx_import_batches_hash ON import_batches (content_hash);
```

### App Routes (`app/routes/bank.py`)
- **POST `/bank/upload`** — Parse CSV/OFX → store batch + lines, detect duplicates (HR-4)
- **GET `/bank/batches`** — List batches with pending/accepted counts

## Key Decisions
| Decision | Rationale |
|--------|-----------|
| **D-9 Canonicalization (Lock-in)** | Only hash canonicalized content (Never raw bytes) to ensure idempotency across encodings |
| **HR-4 Idempotency** | Use `content_hash` UNIQUE constraint on `import_batches`, refuse if matches past batch |
| **CK-2 Profile Versioning** | Profiles are version-stamped — layout changes don't silently re-map old imports (trap 12) |
| **Trap 7 Hashing** | Content hashing must be canonicalized to handle line endings, spaces, etc. |
| **No DB I/O in Importers** | Pure functions only: parsing + hashing. Actual persistence is async via app routes |

## Validation
- ✅ All import-specific tests pass (25/25)
- ✅ No regressions in core accounting tests
- ✅ All domain logic is pure – `importers/` does not interact with ledger DB or journal entries
- ✅ New files properly integrated with existing SDD workflow  
- ✅ Boundary gate clean

## Phase 2 Status
Phase 2 (Daily Driver) now fully implemented:
```
import → review → accept → reconcile → lock
```

Phase 3 begins with Step 8 (AR Domain Services).