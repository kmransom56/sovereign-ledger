# Step 15 — Tax-Ready Exports, CPA Bundle, Period Close

**Task File:** .specs/tasks/draft/build-sovereign-ledger.feature.md
**Phase:** 4 — AP & Money UI Completion
**Model:** opus
**Agent:** sdd:developer
**Depends on:** Step 12 (contractor 1099 data), Step 14 (report suite for Schedule C inputs)
**Parallel with:** Step 17 (deploy hardening — no shared files)
**Note:** Locked decisions D-2 (accrual basis), Expected Changes tree `tax/ (schedule_c, form_1099) [P5]`, `scripts/cpa_export [P5]`, `app/routes/close.py [P5]`. Rubric criterion "Reporting & Tax-Export Fidelity" (0.15) is decided here.

**Goal:** The tax-ready layer: Schedule C summary and 1099-NEC tracking built from ledger data, the one-export CPA bundle (GL CSV, report PDFs, Schedule C summary, 1099-NEC tracking), and the period-close flow (books-closed snapshot that locks periods and freezes report snapshots).

Step 15 turns the report suite into a filing handoff and gives the year a hard boundary: the close flow produces immutable snapshots and refuses further postings into closed periods (T-10/CK-9), while `cpa_export.py` answers CK-11 with one command.

#### Expected Output

- `tax/schedule_c.py`: expense category → Schedule C line mapping over committed entries (pure)
- `tax/form_1099.py`: 1099-NEC tracking from contractor payments (thresholds, ytd totals, masked TIN)
- `scripts/cpa_export.py`: one command → GL CSV + report PDFs + Schedule C summary + 1099-NEC tracking into a dated bundle directory
- `app/routes/close.py` + screens: period/year close wizard — pre-close checklist (TB $0.00, reconciliation complete), snapshot generation, lock
- `tests/test_tax_exports.py`, `tests/test_cpa_bundle.py` (CK-11 bundle completeness), `tests/test_close_flow.py` (T-10/CK-9)

#### Success Criteria

- [ ] `uv run pytest tests/test_tax_exports.py tests/test_cpa_bundle.py tests/test_close_flow.py -q` passes
- [ ] CK-11: `uv run python scripts/cpa_export.py --year 2026` produces a bundle containing GL CSV, P&L/BS/TB PDFs, Schedule C summary, and 1099-NEC tracking — all four components present and internally consistent (bundle totals == ledger to the cent)
- [ ] Schedule C mapping: every CoA expense subtype maps to exactly one Schedule C line; unmapped subtype fails loudly (no silent omission)
- [ ] T-10/CK-9: books-open→books-closed flow: close requires $0.00 TB + reconciled bank accounts; after close, postings into the period are refused (HR-6) and P&L/BS snapshots render from frozen data
- [ ] 1099-NEC tracking lists contractors meeting the threshold with ytd totals matching `contractor_payments` exactly
- [ ] `grep` purity gate: `tax/` imports nothing from `app/`

#### Subtasks

- [ ] Implement `tax/schedule_c.py` (category mapping + totals) + `tests/test_tax_exports.py` unit tests
- [ ] Implement `tax/form_1099.py` (thresholds, ytd, masked TIN) + tests
- [ ] Implement `scripts/cpa_export.py` + `tests/test_cpa_bundle.py` (four-component completeness, cent-exact consistency)
- [ ] Implement `app/routes/close.py` + close wizard screens (checklist, snapshot, lock)
- [ ] Write `tests/test_close_flow.py` (T-10: pre-close gates, snapshot freeze, closed-period refusal)
- [ ] Verify CPA bundle against the seeded scenario and record bundle listing as evidence

#### Blockers & Risks

| Item | Type | Impact | Likelihood | Resolution / Mitigation |
|------|------|--------|------------|-------------------------|
| Schedule C line mapping ambiguous for some CoA subtypes | risk | High | Med | Mitigation: explicit mapping table reviewed against IRS line names; unmapped → loud failure, never silent omission; Keith confirms mapping before close |
| CPA bundle incomplete at real filing time | risk | High | Med | Mitigation: `test_cpa_bundle.py` asserts all four components + cross-consistency; bundle contents pinned in golden manifest |
| Close flow locks periods irreversibly with a defect inside | risk | High | Low | Mitigation: pre-close checklist gates (TB $0.00, reconciliations complete) + dry-run mode that reports without locking; restore drill (Step 17) as backstop |
| Snapshot drift vs live queries | risk | Med | Med | Mitigation: snapshots stored as committed data (hash-stamped); close tests compare snapshot vs live report at close instant |
| Tax advice creep (rates, deductions logic) | risk | Med | Low | Mitigation: record-only mapping of existing entries; no rate computation; reviewer enforces scope |