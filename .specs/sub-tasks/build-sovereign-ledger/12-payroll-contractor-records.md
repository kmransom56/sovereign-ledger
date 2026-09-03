# Step 12 — Payroll & Contract Payments (Domain + Records Screens)

**Task File:** .specs/tasks/draft/build-sovereign-ledger.feature.md
**Phase:** 3 — AR & Recurring
**Model:** opus
**Agent:** sdd:developer
**Depends on:** Step 8 (payment patterns), Step 3 (domain), Step 5 (app shell)
**Parallel with:** Step 9, Step 10, Step 11 (all depend only on ≤Phase 2 outputs)
**Note:** Locked decisions D-8 (JE-first record-keeping; payroll is record-only — manual payroll stays outside the app per the Description's Option A, never a payroll engine). Migration `0006_payroll`.

**Goal:** Payroll and contractor-payment record-keeping: payroll runs as recorded JEs (Dr Expense / Cr Bank) with per-employee breakdown lines, contractor payments as simple recorded disbursements, plus the minimal record screens — a ledger, not a payroll engine.

Step 12 is deliberately the thinnest of the domain steps: Option A record-only means no tax computation, no withholding, no filings — just faithful JEs + audit-able records. Complexity here is correctness of the record structure, which is why it stays opus-tier under the criticality rule (payroll-adjacent data integrity), not breadth.

#### Expected Output

- `db/migrations/0006_payroll.sql`: `payroll_runs` (period, totals, JE link), `payroll_lines` (employee, gross, taxes withheld, net), `contractor_payments` (1099 flag, JE link)
- `ledger/payroll.py`: record-payroll-run logic (build JE from per-employee lines; totals must reconcile to JE lines before posting)
- `ledger/contractors.py`: record contractor disbursement logic
- `app/routes/payroll.py` + `app/routes/contractors.py`: record-entry screens (admin-gated), payroll-run history view, contractor 1099-ready listing
- `tests/test_payroll_records.py` (T-7), `tests/test_contractor_payments.py`

#### Success Criteria

- [ ] `uv run pytest tests/test_payroll_records.py tests/test_contractor_payments.py -q` passes
- [ ] T-7/HR-3: record a monthly payroll run with per-employee gross/net lines → one balanced JE (Dr Payroll Expense / Cr Bank) whose totals equal the line sums to the cent; run immutable after posting
- [ ] Tax-withheld lines stored per employee per run; 1099-ready contractor listing exports (id, TIN-masked, ytd total)
- [ ] No payroll computation exists: no withholding tables, no tax-rate logic (grep/gate test asserts absence)
- [ ] Screens: create-run form validates line sums == totals before posting; history view lists runs with JE links
- [ ] All writes admin-role-gated + CSRF-checked (CK-12 negative set for these routers)

#### Subtasks

- [ ] Write `db/migrations/0006_payroll.sql` (payroll_runs, payroll_lines, contractor_payments)
- [ ] Implement `ledger/payroll.py` (JE construction + totals reconciliation)
- [ ] Implement `ledger/contractors.py` (disbursement recording + 1099 data view)
- [ ] Implement `app/routes/payroll.py` + `app/routes/contractors.py` + screens (role-gated, CSRF)
- [ ] Write `tests/test_payroll_records.py` (T-7: balanced JE, immutability, totals==lines)
- [ ] Write `tests/test_contractor_payments.py` (disbursement + 1099 export data)

#### Blockers & Risks

| Item | Type | Impact | Likelihood | Resolution / Mitigation |
|------|------|--------|------------|-------------------------|
| Scope creep into payroll computation | risk | High | Med | Mitigation: HR-3 forbids it; negative gate test asserts no tax-table constructs; reviewer enforces record-only |
| Totals/lines mismatch slipping through | risk | High | Low | Mitigation: reconcile-before-post in `ledger/payroll.py` + T-7 negative test |
| Payroll data sensitivity (per-employee amounts) | risk | High | Med | Mitigation: admin-only routes (CK-12), no-export-by-default, audit log rows on access (HR-10) |
| 1099 TIN storage temptation (full TIN) | risk | Med | Low | Mitigation: masked-TIN display + export fields limited to CK-specified columns; reviewer verifies |