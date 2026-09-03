# Step 6 — Bank Importers + Content-Hash Idempotency

**Task File:** .specs/tasks/draft/build-sovereign-ledger.feature.md
**Phase:** 2 — Daily Driver (import & review)
**Model:** opus
**Agent:** sdd:developer
**Depends on:** Step 3 (pure core), Step 5 (app shell + bank schema consumers)
**Parallel with:** Step 8, Step 12 (all three depend only on Phase 1 outputs)
**Note:** Locked decisions D-9 (canonicalized content hash — NEVER raw bytes; batch + per-line hashing; FITID via ofxtools 1.1.1, never ofxparse per F-1), migration `0004_bank`. Installs ofxtools 1.1.1 + charset-normalizer 3.5.1 here (first consumer). SKILL traps 7, 8, 12.

**Goal:** `importers/` producing drafts only: CSV/QFX/OFX parsing with versioned per-account profiles, charset sniffing, canonicalized file+line hashing against `import_batches` so the same statement re-imported under any filename creates zero duplicates (HR-4/T-2/T-16).

Step 6 is the pure parsing/identity layer — it does not post anything and has no review UI (that is Step 7). Profiles are version-stamped so a bank layout change cannot silently re-map old imports (trap 12, CK-2).

#### Expected Output

- `importers/base.py`: `BankImporter` protocol (`detect`/`parse` → `BankLine` drafts)
- `importers/csv_generic.py`: CSV parser driven by saved profile (column mapping, date format, decimal normalization → Decimal → validate 2dp → integer cents, trap 8)
- `importers/ofx.py`: QFX/OFX via ofxtools 1.1.1, keyed on bank `FITID`
- `importers/profiles.py`: version-stamped per-account profiles (persisted in `0004_bank` tables)
- `db/migrations/0004_bank.sql`: `bank_accounts` (1:1 ledger accounts), `import_batches` (content_hash unique), `bank_lines`, profile storage
- `importers/hash.py` (or within base): canonicalization + batch/line hashing
- `tests/test_importers.py` (unit: parsing, charset, canonicalization), `tests/test_import_idempotency.py` (T-2), `tests/test_import_profile.py` (T-16)

#### Success Criteria

- [ ] `uv run pytest tests/test_importers.py tests/test_import_idempotency.py tests/test_import_profile.py -q` passes
- [ ] T-2/HR-4: same statement file imported twice under different filenames → second run reports "already imported", `import_batches` unchanged, zero new `bank_lines`
- [ ] Canonicalization test: CRLF→LF, trailing-whitespace, and `100.00` vs `100.0` vs `100` normalizations hash identically; raw-byte difference (re-encode cp1252) does not defeat the match
- [ ] cp1252/latin-1 sample files parse correctly via charset-normalizer sniffing
- [ ] OFX fixture lines key on FITID; duplicate FITID within overlapping statements dedupes per-line
- [ ] Profile version stamp: editing a profile creates a new version; old batches retain the version that parsed them (T-16)
- [ ] `importers/` imports nothing from `app/`; drafts carry no posted state

#### Subtasks

- [ ] Install ofxtools 1.1.1 + charset-normalizer 3.5.1 pins (folded; first consumer)
- [ ] Write `db/migrations/0004_bank.sql` (bank_accounts, import_batches w/ unique content_hash, bank_lines, profiles)
- [ ] Implement `importers/base.py` protocol + `BankLine` draft type
- [ ] Implement `importers/csv_generic.py` + profile-driven column/date/decimal mapping
- [ ] Implement `importers/ofx.py` (FITID keying via ofxtools)
- [ ] Implement `importers/profiles.py` (version-stamped save/load) + canonical hash functions (D-9)
- [ ] Write unit tests (parsers, charset, Decimal→cents boundary), T-2 idempotency e2e, T-16 profile persistence tests

#### Blockers & Risks

| Item | Type | Impact | Likelihood | Resolution / Mitigation |
|------|------|--------|------------|-------------------------|
| ofxtools 1.1.1 struggles with bank-specific OFX dialects | risk | High | Med | Mitigation: test with Keith's real bank exports early (sample fixtures in `tests/fixtures/`); fallback documented: manual journal entry keeps books current (error flow) |
| Canonicalization gap (e.g. timezone-ish date formats, thousands separators) defeats idempotency | risk | High | Med | Mitigation: property tests over canonicalization matrix; per-line hash as second net across overlapping statements |
| CSV column shift silently mis-maps amounts | risk | High | Low | Mitigation: profile version stamps + 2dp validation + sign heuristic test; drift handled by profile edit or manual entry (T-16) |
| Raw-byte hash temptation (simpler) | risk | High | Med | Mitigation: D-9 explicitly forbids; reviewer checks canonicalization precedes hashing |
| ofxparse confusion (research F-1) | risk | Med | Low | Mitigation: pin ofxtools 1.1.1; reviewer verifies import source |