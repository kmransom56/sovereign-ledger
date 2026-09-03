# Step 11 — AP Domain Services (Vendors, Bills, Bill Payments, Checks)

**Task File:** .specs/tasks/draft/build-sovereign-ledger.feature.md
**Phase:** 3 — AR & Recurring
**Model:** opus
**Agent:** sdd:developer
**Depends on:** Step 8 (payment/allocation patterns), Step 3 (domain core)
**Parallel with:** Step 9 (AR web), Step 10 (scheduler — independent artifacts)
**Note:** Locked decisions D-8 (bill-payment JE), CK-9 (vendors, bills, bill payments with partial payments in AP aging; check register), D-7 (serializable payment application). Migration `0005_ap.sql`. Mirrors Step 8's discipline: pure logic, decisions not I/O.

**Goal:** The AP brain: vendors, bills (expense posting Dr Expense / Cr AP), vendor-credit memos, check-run payments that settle bills and write the check register, and duplicate-bill guard (same vendor+number+amount refused) — with property-tested invariants mirroring AR's.

Step 11 completes the payables half of the money flows (F-3). It reuses Step 8's allocation transaction patterns so review/accept of AP bills later (Step 13) slots into the same posting machinery.

#### Expected Output

- `db/migrations/0005_ap.sql`: `vendors`, `bills`, `bill_lines`, `bill_payments`, `checks` (register), vendor credits
- `ledger/vendors.py`, `ledger/bills.py` (enter/post flow, duplicate guard), `ledger/bill_payments.py` (settle bills, JE Dr AP / Cr Bank, check-number assignment, register entries), `ledger/vendor_credits.py` (memo + application)
- `tests/test_ap_domain.py` (bills, duplicate guard), `tests/test_bill_payments.py` (T-12 core), `tests/test_check_register.py` (register integrity)

#### Success Criteria

- [ ] `uv run pytest tests/test_ap_domain.py tests/test_bill_payments.py tests/test_check_register.py -q` passes
- [ ] T-12 core: $800 bill entered → posted Dr Expense / Cr AP; payment → Dr AP / Cr Bank; bill Paid; books balance; register row written with check number
- [ ] Duplicate bill refused: same vendor + bill number + amount → explicit error naming the existing bill
- [ ] Vendor credit: memo reduces a later bill payment; books balance after application
- [ ] Check numbers strictly sequential per register; gaps only from voided checks (void preserved, never deleted — HR-2)
- [ ] Partial bill payment supported; status derived from remaining balance (not stored)

#### Subtasks

- [ ] Write `db/migrations/0005_ap.sql` (vendors, bills, bill_lines, bill_payments, checks, vendor credits)
- [ ] Implement `ledger/vendors.py` + `ledger/bills.py` (post flow + duplicate guard)
- [ ] Implement `ledger/bill_payments.py` (settlement + check-number assignment + register)
- [ ] Implement `ledger/vendor_credits.py` (memo creation + application)
- [ ] Write `tests/test_ap_domain.py` (bill posting, duplicate refusal)
- [ ] Write `tests/test_bill_payments.py` (T-12 core + partial payments)
- [ ] Write `tests/test_check_register.py` (sequence integrity, void handling)

#### Blockers & Risks

| Item | Type | Impact | Likelihood | Resolution / Mitigation |
|------|------|--------|------------|-------------------------|
| Duplicate-bill guard too strict (legitimate re-bills) | risk | Med | Med | Mitigation: guard keys on vendor+number+amount exactly per T-12; override path documented in runbook, requires admin role |
| Check-number race under concurrent check runs | risk | Med | Low | Mitigation: single-user reality + counter-row lock pattern reused from D-10; test simulates interleaving |
| Register vs JE divergence (void not reflected) | risk | High | Low | Mitigation: void creates reversing JE + register status update in one transaction; tests assert both sides |
| AP/AR allocation logic drift (copy-paste forks) | risk | Med | Med | Mitigation: shared allocation helper extracted in Step 8; Step 11 consumes it; reviewer checks for forked copies |