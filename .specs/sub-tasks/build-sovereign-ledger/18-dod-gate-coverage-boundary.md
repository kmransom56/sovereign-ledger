# Step 18 — Full DoD Gate: Coverage Audit, Boundary Sweep, Regression Suite

**Task File:** .specs/tasks/draft/build-sovereign-ledger.feature.md
**Phase:** 5 — DoD Gate
**Model:** opus
**Agent:** sdd:qa-engineer
**Depends on:** Step 16 (suite baseline), Step 17 (deploy/runbook final)
**Parallel with:** — (final gate; blocks Phase 5 sign-off)
**Note:** DoD lives in `## Acceptance Criteria`; this step verifies every item with evidence, runs the boundary sweep, and produces the DoD sign-off report. Defects route back to owning steps; this step only signs off when green.

**Goal:** The final quality gate: run the complete suite on a clean checkout, audit coverage against thresholds, sweep the two boundary greps, verify every acceptance-criterion checklist item (HR-1…HR-10, CK-1…CK-15) with recorded evidence, and issue the DoD sign-off report (or a defect list routed to owners).

Step 18 is deliberately separate from Step 16: Step 16 built the gates during Phase 4; Step 18 executes the gate cold, on a clean tree, as the release decision. It owns no features.

#### Expected Output

- `.specs/scratchpad/<id>-dod-report.md` (sign-off): per-checklist-item evidence (command + output excerpt + verdict) covering HR-1…HR-10, CK-1…CK-15
- Coverage audit: `pytest --cov` full run with per-package table vs thresholds (ledger/reports/tax ≥95%, app ≥90%)
- Boundary sweep results: CK-13/CK-14 greps + import-graph check (`ledger/`, `reports/`, `tax/` free of `app`/DB imports)
- Clean-checkout reproducibility: `uv sync --frozen` + full suite from fresh clone directory
- Defect list (if any) routed to owning steps with repro commands; gate re-run after fixes

#### Success Criteria

- [ ] Fresh clone + `uv sync --frozen` + `uv run pytest tests/ -q` — full suite green, zero skips without linked defect
- [ ] Coverage report meets thresholds per package; table recorded in the report
- [ ] Boundary greps clean (CK-13: no CDN/external URLs in templates; CK-14: no SQLAlchemy/Alembic anywhere; ledger/reports/tax purity)
- [ ] Every HR-n and CK-n item has a recorded verdict with command evidence in the DoD report
- [ ] T-1…T-16 matrix: every gate tagged and green in the final run summary
- [ ] No open defects owned by this step at sign-off; all routed defects confirmed fixed and re-tested

#### Subtasks

- [ ] Clean-checkout reproducibility run (`uv sync --frozen`, full suite)
- [ ] Coverage audit + per-package threshold table
- [ ] Boundary sweep (CK-13/CK-14 greps + import-graph purity check)
- [ ] DoD evidence report: HR-1…HR-10, CK-1…CK-15 item-by-item verdicts
- [ ] T-1…T-16 gate-tag summary from the final run
- [ ] Defect routing + re-run loop until green

#### Blockers & Risks

| Item | Type | Impact | Likelihood | Resolution / Mitigation |
|------|------|--------|------------|-------------------------|
| Late defect forces re-opening a "done" step | risk | High | Med | Mitigation: gate runs cold on clean tree; defect routing with repro makes owner-step fixes fast; re-run loop is cheap |
| Coverage measured against stale cache | risk | Low | Low | Mitigation: `pytest --cov` with `--cov-fail-under` and cleared caches in clean tree |
| Evidence report becomes theater (green checks without commands) | risk | High | Med | Mitigation: every verdict line must cite command + output excerpt; reviewer (opus) rejects command-less verdicts |
| uv.lock drift discovered at clean sync | risk | Med | Low | Mitigation: `--frozen` surfaces it immediately; lock fix routes to Step 1 owner |
| Gate pressure to weaken a threshold at the end | risk | High | Low | Mitigation: thresholds are DoD constants; only the task owner may change them; reviewer flags any attempt |