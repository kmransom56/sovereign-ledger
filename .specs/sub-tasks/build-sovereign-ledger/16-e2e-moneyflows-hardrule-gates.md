# Step 16 — End-to-End Money-Flow Suite + Hard-Rule Gate Tests

**Task File:** .specs/tasks/draft/build-sovereign-ledger.feature.md
**Phase:** 4 — AP & Money UI Completion
**Model:** opus
**Agent:** sdd:qa-engineer
**Depends on:** Steps 6, 7, 9, 12, 13, 14, 15 (all money flows + tax/close must exist)
**Parallel with:** Step 17 (hardening ops, different artifacts)
**Note:** This is the T-1…T-16 acceptance suite; CK-13/CK-14 hard-rule greps; CK-12 negative matrix. The suite is the Phase 4 exit evidence and Phase 5's regression baseline.

**Goal:** Assemble the six money flows end-to-end against a seeded scratch instance, encode every hard rule as an automated gate test (HR-1…HR-10), and wire the full pytest suite + coverage thresholds as the DoD gate.

Step 16 does not build features — it proves the system against the Test Matrix (T-1…T-16) and turns hard rules into CI-enforced assertions. Where a flow test exposes a defect, the fix belongs to the step that owns the flow; this step records and routes the defect.

#### Expected Output

- `tests/e2e/test_money_flows.py`: six parameterized flows (T-3 review→accept, T-4 reconcile, T-5 AR payment, T-12 bill→check, T-7 payroll record, T-2 re-import) against seeded scratch PG + running app
- `tests/test_hard_rules.py`: HR-1 (unbalanced refused on every path), HR-2 (mutations refused everywhere), HR-3 (no payroll computation + no CDN), HR-4 (duplicate import), HR-5 (no auto-post), HR-6 (closed-period refusal incl. web), HR-7 ($0.00-only reconcile), HR-8 (overpayment→credit), HR-9 (register/backup/report existence + integrity), HR-10 (audit chain tamper detection)
- `tests/test_permissions_matrix.py`: CK-12 negative matrix over every mutating route × accountant role
- `pytest.ini`/pyproject gate config: full suite + coverage thresholds (ledger/reports/tax ≥95%, app ≥90%) + boundary greps (CK-13/CK-14) as test-collected checks
- `tests/test_import_profile.py` consolidated final (T-16)

#### Success Criteria

- [ ] `uv run pytest tests/ -q` — entire suite green including the six e2e flows and hard-rule gates
- [ ] T-10/CK-9: books-open→books-closed e2e (period lock + snapshot freeze from Step 15) passes; CK-14 boundary greps enforced in-suite
- [ ] Coverage thresholds enforced by CI config (fail below 95% ledger+reports+tax, 90% app)
- [ ] Every HR-1…HR-10 has at least one automated gate test that fails on violation (spot-check: inject violation → test red)
- [ ] CK-12: permissions matrix covers every mutating route across all routers (route table introspected in test, not hand-listed)
- [ ] Any defects found are filed back to owner steps with repro in this suite (scratchpad log)

#### Subtasks

- [ ] Build seeded scratch-instance fixture (CoA, customers, vendors, bank lines, periods)
- [ ] Write `tests/e2e/test_money_flows.py` (six flows, T-matrix tagged)
- [ ] Write `tests/test_hard_rules.py` (HR-1…HR-10 gates)
- [ ] Write `tests/test_permissions_matrix.py` (CK-12 introspected route matrix)
- [ ] Wire pytest gate config: coverage thresholds + boundary greps (CK-13/CK-14) as collected checks
- [ ] Defect triage log in scratchpad; route each to owning step; re-run suite after fixes

#### Blockers & Risks

| Item | Type | Impact | Likelihood | Resolution / Mitigation |
|------|------|--------|------------|-------------------------|
| Flow defects surfaced late (Phase 4) force cross-step fixes | risk | High | Med | Mitigation: this step's tests route defects to owning steps; earlier steps already carry per-flow tests; qa-engineer has explicit fix-routing authority |
| Flaky e2e (app + scratch PG timing) | risk | Med | Med | Mitigation: deterministic seeds, readiness probes, retries only on known-infra errors; deadline=None hypothesis |
| Hard-rule gates rot (skip markers creep in) | risk | High | Low | Mitigation: skip/reason lint in gate config; reviewer rejects skips without linked defect |
| Route introspection misses non-standard routers | risk | Med | Low | Mitigation: introspect FastAPI app route table + explicit smoke list cross-check |
| Scope creep: rebuilding fixes here instead of routing | risk | Med | Med | Mitigation: charter is prove+gate; fixes route to owner steps; reviewer enforces |