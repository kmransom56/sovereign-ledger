# Step 2 — Schema, Append-Only Triggers, Persistence Bootstrap

**Task File:** .specs/tasks/draft/build-sovereign-ledger.feature.md
**Phase:** 1 — Foundation (books exist)
**Model:** opus
**Agent:** sdd:developer
**Depends on:** — (none at code level; consumes locked decisions D-2/D-3/D-5/D-6 only)
**Parallel with:** Step 1
**Note:** Locked decisions D-5 (plain ordered SQL, NO Alembic/SQLAlchemy), D-6 (per-entry DEFERRABLE INITIALLY DEFERRED balance trigger + REVOKE UPDATE/DELETE), D-4 (psycopg 3.3.5 sync, `dict_row`). Install psycopg 3.3.5 HERE (first consumer). Conventions from SKILL.md traps 4/5.

**Goal:** Stand up the PostgreSQL 16 data foundation — migration `0001_core.sql` (four append-only tables + trigger machinery), `db/session.py` pool factory, CoA seed — plus the scratch-Postgres pytest fixture every e2e test reuses.

Step 2 is the other Level-0 node: it needs no code from Step 1, only the locked D-decisions, so the two run in parallel. The deferred trigger (fires at COMMIT, not per-row) and the privilege revocations are the DB-level half of HR-1/HR-2 defense in depth.

#### Expected Output

- `db/migrations/0001_core.sql`: `accounts`, `journal_entries`, `journal_lines` (BIGINT signed cents), `fiscal_periods`, `audit_log`; per-entry balance constraint trigger DEFERRABLE INITIALLY DEFERRED; block-UPDATE/DELETE triggers on the four append-only tables; `REVOKE UPDATE, DELETE` from the app role
- `db/migrations/0002…0006` placeholder naming convention documented in a `db/migrations/README.md` (numeric-order contract, D-5)
- `db/session.py`: psycopg 3.3.5 sync pool factory, server-side binding, `dict_row`, serializable-retry helper for SQLSTATE 40001 (bounded backoff wrapper, D-7)
- `db/seed/chart_of_accounts.py`: starter CoA with tax-mapping subtypes
- `scripts/init_db.py`: applies migrations in numeric order, then seeds
- `tests/conftest.py`: scratch-Postgres fixture (create DB per session, run `scripts/init_db.py`, teardown), used by all later e2e tests

#### Success Criteria

- [ ] `uv run python scripts/init_db.py` against a scratch Postgres creates all five tables; `\d journal_lines` shows BIGINT amount_cents with CHECK for sign domain
- [ ] Property-style DB test: inserting an unbalanced entry's lines commits-fails at COMMIT (deferred trigger), error raised, nothing stored (HR-1 at storage boundary)
- [ ] DB test: `UPDATE`/`DELETE` on `journal_entries`, `journal_lines`, `accounts`, `fiscal_periods` raise permission-denied as app role (HR-2)
- [ ] `uv run pytest tests/test_db_core.py -q` passes (new file: trigger + revocation + retry-wrapper tests)
- [ ] 40001 retry wrapper test: simulated serialization failure retried ≤N times with backoff, then surfaces
- [ ] Seed loads starter CoA; `SELECT count(*) FROM accounts` > 0 after init

#### Subtasks

- [ ] Install psycopg 3.3.5 pin into pyproject (folded; first consumer) and write `db/session.py` pool + 40001 retry wrapper (D-4/D-7)
- [ ] Write `db/migrations/0001_core.sql` with the four append-only tables + deferred balance trigger + anti-UPDATE/DELETE triggers + REVOKEs (D-6)
- [ ] Write `db/migrations/README.md` documenting the ordered-SQL contract (0001…0006 roadmap per Expected Changes tree)
- [ ] Write `db/seed/chart_of_accounts.py` with subtype→tax-mapping fields
- [ ] Write `scripts/init_db.py` (apply in numeric order, then seed)
- [ ] Write `tests/conftest.py` scratch-PG fixture
- [ ] Write `tests/test_db_core.py`: unbalanced-entry COMMIT rejection, mutation refusal, retry-wrapper behavior (T-1 storage half, T-6 trigger foundations)

#### Blockers & Risks

| Item | Type | Impact | Likelihood | Resolution / Mitigation |
|------|------|--------|------------|-------------------------|
| Scratch Postgres unavailable in test env | blocker | High | Med | Resolution: Step 2 provisions a disposable PG16 container on 11241 (or ephemeral port) as part of conftest; quadlet from Step 5 is not a test dependency |
| Deferred trigger fires only at COMMIT — devs expect per-row rejection | risk | Med | High | Mitigation: document in migration header + tests assert COMMIT-time behavior; pure core already rejects pre-storage (HR-1 on every path) |
| Missing REVOKE leaves an UPDATE path | risk | High | Low | Mitigation: revocations in same migration as tables; dedicated negative test in `tests/test_db_core.py` |
| 40001 retry wrapper masking real bugs | risk | Med | Med | Mitigation: bounded attempts, only on SQLSTATE 40001, logged; unit test proves non-40001 errors surface immediately |
| Migration ordering drift as 0002–0006 land later | risk | Med | Med | Mitigation: README contract now; `init_db.py` asserts numeric order and refuses gaps |