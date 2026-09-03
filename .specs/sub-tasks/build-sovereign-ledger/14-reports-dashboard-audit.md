# Step 14 — Financial Reports + Dashboard + Audit Viewer

**Task File:** .specs/tasks/draft/build-sovereign-ledger.feature.md
**Phase:** 4 — AP & Money UI Completion
**Model:** opus
**Agent:** sdd:developer
**Depends on:** Step 5 (TB foundation), Step 13 (GL source completeness: AR/AP/payroll flows all post by now)
**Parallel with:** Step 15 (no shared files)
**Note:** Locked decisions D-2 (accrual basis), CK-10 (P&L cash/accrual, balance sheet, cash flow + drill-down for any past period), HR-9 (every report regenerates a trial balance netting $0.00), HR-10 (append-only audit log — the viewer surfaces and verifies the chain), HR-7/HR-6 already enforced upstream. `reports/` stays pure (D-1 hard rule 1).

**Goal:** The full financial reporting layer: P&L (month + YTD), Balance Sheet, Cash Flow, General Ledger, plus the operator dashboard tiles and the audit-log viewer — all backed by pure `reports/` functions with golden-file tests.

Step 14 is the last pure-domain step and the one that makes the system decision-usable: Keith can see P&L monthly, drill GL to journal entries, and inspect the tamper-evident audit chain. Reports consume only committed ledger state.

#### Expected Output

- `reports/pnl.py` (month + YTD with month columns), `reports/balance_sheet.py`, `reports/cash_flow.py` (indirect method), `reports/general_ledger.py` (drill-down data), `reports/dashboard.py` (tile aggregates)
- `app/routes/reports.py` extended: P&L/BS/CF/GL endpoints + drill-down; `app/routes/audit.py` (hash-chain verification view); `app/routes/dashboard.py` (tiles incl. backup status)
- `app/templates/reports/` screens; period-parameter pickers; CSV export endpoints (admin-gated)
- `tests/test_reports.py` (unit), `tests/test_reports_golden.py` (T-9 golden files), `tests/test_dashboard.py`, `tests/test_audit_viewer.py` (T-15 UI half)

#### Success Criteria

- [ ] `uv run pytest tests/test_reports.py tests/test_reports_golden.py tests/test_dashboard.py tests/test_audit_viewer.py -q` passes
- [ ] T-9: P&L, BS, CF golden files match to the cent for the seeded scenario; BS balances (A=L+E) exactly; P&L month + YTD columns agree with TB
- [ ] CFS reconciles: cash at end == BS cash line to the cent (indirect method over committed entries only)
- [ ] GL drill-down: account → period → journal entries → lines, in entry order; every link resolves (T-9)
- [ ] Audit viewer verifies the full chain and pinpoints the first broken link on injected tamper (HR-10/T-15)
- [ ] Dashboard tiles render from `reports/dashboard.py` (AR aging, AP due, backup status); backup tile reflects Step 10 manifest
- [ ] `grep` boundary gate: `reports/` imports no `app`/DB modules

#### Subtasks

- [ ] Implement `reports/pnl.py`, `reports/balance_sheet.py`, `reports/cash_flow.py`, `reports/general_ledger.py`, `reports/dashboard.py`
- [ ] Extend `app/routes/reports.py` + write `app/routes/audit.py` + `app/routes/dashboard.py` with screens
- [ ] CSV export endpoints (admin-gated) + period pickers
- [ ] Write `tests/test_reports.py` unit tests (classification, zero-amount handling)
- [ ] Write `tests/test_reports_golden.py` (T-9: golden files committed under `tests/golden/`)
- [ ] Write `tests/test_dashboard.py` + `tests/test_audit_viewer.py` (T-15 chain-verify + tamper pinpoint)

#### Blockers & Risks

| Item | Type | Impact | Likelihood | Resolution / Mitigation |
|------|------|--------|------------|-------------------------|
| Classification errors (asset vs expense) corrupt BS/CFS | risk | High | Med | Mitigation: CoA subtype → report-class mapping table tested against T-9 goldens; golden diffs reviewed by reviewer |
| CFS indirect-method edge cases (no explicit cash account) | risk | High | Med | Mitigation: CFS derived from committed JEs against designated cash accounts; test with the seeded scenario incl. credit application + bill payment |
| Golden files mask future regressions via sloppy update culture | risk | Med | Med | Mitigation: golden-update script + reviewer must approve any golden change with recomputed rationale |
| Report queries slow at single-user scale | risk | Low | Low | Mitigation: single-digit-years data volume; indexes from Step 2 sufficient; measured in Phase 5 perf check (T-16) |
| Drill-down N+1 queries | risk | Low | Med | Mitigation: batched queries in `reports/general_ledger.py`; T-9 asserts order, not perf |