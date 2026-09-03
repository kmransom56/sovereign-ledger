# Step 8 — AR Domain Services (Customers, Invoices, Payments, Recurring Logic)

**Task File:** .specs/tasks/draft/build-sovereign-ledger.feature.md
**Phase:** 3 — AR & Recurring
**Model:** opus
**Agent:** sdd:developer
**Depends on:** Step 3 (domain core), Step 2 (schema patterns)
**Parallel with:** Step 6 and Step 12 (starts in the Phase 2 window; phase gate remains Phase 3), then Step 7
**Note:** Locked decisions D-7 (serializable allocation), D-8 (overpayment → customer_credits liability, never income — HR-8), D-10 (gapless invoice numbers via locked counter row — never a sequence, F-5/trap 6). Migration `0002_ar.sql`. Pure modules; I/O stays in adapters.

**Goal:** The pure AR brain: customers, invoices that post on creation (Dr AR / Cr Income), all-or-nothing payment allocation across invoices with status flips in the same transaction, overpayment → customer credit, credit application to later invoices, and recurring-template generation logic (no scheduling here — Step 10 owns the timer).

Step 8 runs parallel to the Phase 2 importer work because it depends only on the Phase 1 domain core. Every function returns decisions/value objects; the routes step (9) persists them inside D-7 transactions.

#### Expected Output

- `db/migrations/0002_ar.sql`: `customers`, `invoices`, `invoice_lines`, `payments`, `customer_credits`, invoice-number counter table
- `ledger/customers.py`, `ledger/invoices.py` (official-post flow: counter row lock → gapless number → lines → JE Dr AR / Cr Income), `ledger/payments.py` (allocation: all-or-nothing across invoices, status flips, residual → customer_credits, JE Dr Bank / Cr AR; credit application), `ledger/recurring.py` (template → per-cycle invoice generation decision logic; pause semantics; price changes future-only)
- `tests/test_ar_domain.py` (invoice posting, sequential gapless numbers), `tests/test_payment_allocation.py` (T-5 core), `tests/test_recurring_logic.py`

#### Success Criteria

- [ ] `uv run pytest tests/test_ar_domain.py tests/test_payment_allocation.py tests/test_recurring_logic.py -q` passes
- [ ] T-5 core: $60 payment on a $49 invoice → invoice Paid + $11 customer_credit liability; income untouched; books balance; interrupted allocation leaves NO partial state (property test over allocation permutations)
- [ ] CK-8: $11 credit + $38 payment fully pay a later $49 invoice with $0 credit remaining
- [ ] Invoice posting produces exactly one balanced JE (Dr AR / Cr Income); Overdue derived from due date, never stored
- [ ] Gapless numbers: simulated rollback mid-creation does not burn a number (counter-row lock semantics) — property/loop test over N creations + failures
- [ ] Recurring logic: template active from Mar 1 → exactly 3 cycle invoices Mar/Apr/May; paused Apr 15 → no May invoice; price change affects future cycles only
- [ ] `grep` boundary gate still clean for `ledger/`

#### Subtasks

- [ ] Write `db/migrations/0002_ar.sql` (customers, invoices, invoice_lines, payments, customer_credits, counter table)
- [ ] Implement `ledger/customers.py` + `ledger/invoices.py` (official-post flow with counter-row lock, D-10)
- [ ] Implement `ledger/payments.py` (all-or-nothing allocation + residual credit, HR-8)
- [ ] Implement `ledger/recurring.py` (cycle computation, pause, future-only price changes)
- [ ] Write `tests/test_ar_domain.py` (balanced posting, gapless numbers under rollback)
- [ ] Write `tests/test_payment_allocation.py` (T-5 core scenarios + overpayment + credit application)
- [ ] Write `tests/test_recurring_logic.py` (CK-6 semantics, pause, tier change)

#### Blockers & Risks

| Item | Type | Impact | Likelihood | Resolution / Mitigation |
|------|------|--------|------------|-------------------------|
| Sequence-instead-of-counter regression burns invoice numbers on rollback | risk | High | Med | Mitigation: D-10 counter-row lock implemented and tested under simulated rollback; reviewer rejects any `CREATE SEQUENCE` for invoice numbers |
| Allocation partial-state on crash | risk | High | Med | Mitigation: allocation logic designed as one pure decision consumed inside a single serializable transaction in Step 9; property test asserts no intermediate states are representable |
| Overpayment booked as income | risk | High | Low | Mitigation: HR-8 hard rule; `customer_credits` is a liability account; T-5 asserts income unchanged |
| Recurring cycle edge cases (pause mid-cycle, 1st-of-month boundaries) | risk | Med | Med | Mitigation: cycle computation table-tested across pause/resume/price-change dates |
| Credit application double-counts | risk | High | Low | Mitigation: single apply path shared by payment allocation; tests assert $0 remaining |