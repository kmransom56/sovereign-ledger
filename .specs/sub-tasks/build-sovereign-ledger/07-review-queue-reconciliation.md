# Step 7 — Import Review Queue + Reconciliation

**Task File:** .specs/tasks/draft/build-sovereign-ledger.feature.md
**Phase:** 2 — Daily Driver (import & review)
**Model:** opus
**Agent:** sdd:developer
**Depends on:** Step 6 (importers + bank schema)
**Parallel with:** Step 9 (independent AR routes), Step 11 (independent AP)
**Note:** Locked decisions D-7 (SERIALIZABLE + 40001 retry on accept-post), HR-5 (nothing auto-posts), HR-7 ($0.00-only reconciliation close). Reuses the D-7 retry wrapper from Step 2's `db/session.py`.

**Goal:** The human-gate posting path and the reconciliation close: review-queue screens where suggestions are accepted/edited/rejected (accept posts via serializable transaction), and the reconciliation flow that completes only at exactly $0.00 difference and locks its cleared lines.

Step 7 makes Phase 2 the daily driver: Keith's monthly bank cycle (import → review → accept → reconcile → lock) becomes operable end-to-end. This step carries three hard rules (HR-5, HR-7, and HR-1 via the D-7 posting transaction).

#### Expected Output

- `app/routes/import_review.py`: queue listing drafts, accept-as-suggested, edit-then-accept, reject; `Cache-Control: no-store` partials, `HX-Redirect` after POST
- `app/routes/bank.py`: upload endpoint → importer → batch/lines; "already imported" reporting
- `ledger/bank_accounts.py`, `ledger/reconciliation.py`: suggestion generation (auto-match to open invoice/bill, learned category), reconciliation decision logic (difference computation, completion at $0.00, line locking)
- `app/routes/reconcile.py`: statement-balance entry, cleared-line selection, complete-at-$0.00, locked-line display
- `tests/test_review_accept_e2e.py` (T-3), `tests/test_reconciliation.py` (T-4), suggestion unit tests

#### Success Criteria

- [ ] `uv run pytest tests/test_review_accept_e2e.py tests/test_reconciliation.py -q` passes vs scratch Postgres
- [ ] T-3/HR-5: 40-line seeded batch → accept 12 as suggested + edit 5 then accept → exactly 17 postings, 23 lines remain unposted; no path posts without explicit accept
- [ ] T-4/HR-7: statement $4,213.75 vs cleared $4,200.00 → completion refused, $13.75 displayed; after the missing line, completion succeeds and cleared lines are locked (subsequent altering posting refused)
- [ ] Auto-match: open-invoice suggestion produced for a matching deposit; learned category rule applied on repeat vendor
- [ ] Every posting path here runs inside the D-7 serializable+retry transaction (asserted by test with simulated 40001)
- [ ] Review queue works without JS via `hx-boost` fallback (D-11)

#### Subtasks

- [ ] Implement `ledger/bank_accounts.py` + `ledger/reconciliation.py` (suggestions, difference logic, lock semantics) — pure
- [ ] Write `app/routes/bank.py` (upload, batch status, "already imported" report)
- [ ] Write `app/routes/import_review.py` (queue + accept/edit/reject; posts via D-7 transaction)
- [ ] Write `app/routes/reconcile.py` (statement balance, cleared selection, $0.00 completion, lock)
- [ ] Templates: review queue + reconciliation screens (partials, no-store)
- [ ] Write `tests/test_review_accept_e2e.py` (T-3: 40-line batch, exact 17/23 counts)
- [ ] Write `tests/test_reconciliation.py` (T-4: $13.75 refusal → $0.00 completion → lock enforcement; simulated 40001 retry test)

#### Blockers & Risks

| Item | Type | Impact | Likelihood | Resolution / Mitigation |
|------|------|--------|------------|-------------------------|
| Accept path accidentally auto-posts on edit | risk | High | Low | Mitigation: single accept endpoint; T-3 exact-count assertion; reviewer traces every post call site |
| Reconciliation lock leaks (locked line altered via another path) | risk | High | Med | Mitigation: DB-level lock check in `0004_bank`/posting path + T-4 negative test through the web route |
| 40001 retry loops under contention on accept | risk | Med | Low | Mitigation: bounded retries from Step 2 wrapper; two-user scale makes contention rare; test injects 40001 |
| Suggestion quality (auto-match) too aggressive → wrong postings | risk | Med | Med | Mitigation: suggestions are drafts only (HR-5); confidence display; human accept is the gate by design |
| Queue usability without JS regresses | risk | Low | Low | Mitigation: `hx-boost` + full-page fallback templates per D-11; smoke test |