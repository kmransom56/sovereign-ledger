# Step 3 — Ledger Domain Services (Entries, Accounts, Periods, Audit)

**Task File:** .specs/tasks/draft/build-sovereign-ledger.feature.md
**Phase:** 1 — Foundation (books exist)
**Model:** opus
**Agent:** sdd:developer
**Depends on:** Step 1, Step 2
**Parallel with:** — (joins the Step 1 ∥ Step 2 pair; blocks Step 4)
**Note:** Locked decisions D-6 (trigger contract mirrored in core), D-8 (append-only + reversing entries + hash-chained audit). Modules stay pure — persistence remains the caller's job.

**Goal:** Complete the L1/L2 domain core: draft→post entry lifecycle, chart-of-accounts with tax subtypes, fiscal-period open/close/lock state machine, and the hash-chained audit append — the logic every money flow (Steps 6–14) calls.

Step 3 turns the Step 1 engine primitives into the posting domain and adds the three governing services. The hash chain (`audit.py`) is where HR-10 lives; the period state machine is where HR-6 is decided in the core before the DB trigger re-verifies it.

#### Expected Output

- `ledger/entries.py`: draft construction, `post()` validation (balanced, period open, accounts active), reversing-entry constructor that references the original entry id
- `ledger/accounts.py`: CoA operations (create/activate/deactivate), subtype → tax-mapping metadata, opening-balance entry helper
- `ledger/periods.py`: fiscal period open/closed/locked transitions, in-order enforcement, `assert_postable(date)`
- `ledger/audit.py`: append-only hash-chained event records (prev-hash linkage)
- `tests/test_accounts.py`, `tests/test_periods.py`, `tests/test_audit.py`, extended `tests/test_engine.py` state machine (post + reversal transitions)

#### Success Criteria

- [ ] `uv run pytest tests/test_engine.py tests/test_accounts.py tests/test_periods.py tests/test_audit.py -q` all pass
- [ ] Property test: no path constructs a stored-state posting into a closed/locked period — `assert_postable` refuses with the named period (HR-6 core half)
- [ ] Reversing entry: constructed only for an existing posted entry; reversal + correction link by original id (HR-2/CK-15 core half)
- [ ] Hash chain: appending N events yields verifiable chain; mutating any event's payload breaks verification (HR-10, T-15 core)
- [ ] `grep -rEn "fastapi|psycopg|asyncpg|requests|httpx" ledger/` empty — modules remain pure
- [ ] Coverage on `ledger/` ≥95% in this step's pytest-cov run (gate asserted early, not retrofitted)

#### Subtasks

- [ ] Implement `ledger/entries.py` (draft→post lifecycle + reversal constructor)
- [ ] Implement `ledger/accounts.py` (CoA + subtypes + opening-balance helper)
- [ ] Implement `ledger/periods.py` (state machine + in-order close + postability)
- [ ] Implement `ledger/audit.py` (hash-chained append + chain verification)
- [ ] Write `tests/test_periods.py` + `tests/test_accounts.py` incl. closed-period refusal and reversal cases
- [ ] Write `tests/test_audit.py`: chain verification + tamper detection (T-15 core half)
- [ ] Extend `tests/test_engine.py` state machine with post/reverse transitions (T-1 full)
- [ ] Add pytest-cov ≥95% gate config for `ledger/`

#### Blockers & Risks

| Item | Type | Impact | Likelihood | Resolution / Mitigation |
|------|------|--------|------------|-------------------------|
| Core/DB invariant drift (core allows what trigger forbids or vice versa) | risk | High | Med | Mitigation: Step 2's trigger contract documented in SKILL trap 4 terms; both tested in this step and Step 2's `tests/test_db_core.py` |
| Hash-chain design weak (recomputation ambiguity) | risk | High | Low | Mitigation: canonical serialization (sorted keys, explicit separators) fixed in this step and pinned by golden test vector in `tests/test_audit.py` |
| Period state machine too strict for corrections | risk | Med | Med | Mitigation: reversals post into the OPEN period per CK-15; tests assert May-closed/July-open scenario |
| Scope creep into use-case territory (invoices etc.) | risk | Low | Med | Mitigation: AR/AP modules are explicitly Steps 8/11; this step only ships entries/accounts/periods/audit |