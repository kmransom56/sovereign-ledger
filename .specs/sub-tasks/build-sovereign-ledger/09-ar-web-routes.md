# Step 9 — AR Web Routes (Invoices & Payments)

**Task File:** .specs/tasks/draft/build-sovereign-ledger.feature.md
**Phase:** 3 — AR & Recurring
**Model:** opus
**Agent:** sdd:developer
**Depends on:** Step 8 (AR domain), Step 4 (auth/role gate), Step 7 (shared UI conventions live)
**Parallel with:** Step 11 (AP domain, independent tables)
**Note:** Reuses D-7 (serializable+retry wrapper from `db/session.py`), D-11 (HTMX partials, no-store, `HX-Redirect`), CK-12 negative-test mandate.

**Goal:** Expose the Step 8 AR brain as the web screens: customer management, invoice creation/preview (gapless number, official-post on create), payment recording with allocation + overpayment-to-credit, credit application — every write role-gated, CSRF-checked, and serializable-retried.

Step 9 is the persistence/UI adapter for `ledger/` AR modules; it adds no new domain logic. The e2e flows it ships (T-5 via web, T-14 recurring UI consumption) are what the Phase 3 gate verifies.

#### Expected Output

- `app/routes/customers.py`, `app/routes/invoices.py` (create → preview → official post; PDF-ready preview data), `app/routes/payments.py` (allocate payment, apply credit) + templates
- Recurring-template CRUD screens (consume `ledger/recurring.py` decisions)
- Payment-allocation transaction: wrap `ledger/payments.py` decisions in the D-7 serializable+retry transaction (single call site per flow)
- `tests/test_ar_web_e2e.py` (T-5 via web: overpayment→credit, books balance), `tests/test_invoice_gapless_e2e.py` (T-11), `tests/test_recurring_e2e.py` (T-14 UI half)

#### Success Criteria

- [ ] `uv run pytest tests/test_ar_web_e2e.py tests/test_invoice_gapless_e2e.py tests/test_recurring_e2e.py -q` passes vs scratch Postgres
- [ ] T-5 web path: $60 payment on $49 invoice via the UI flow → invoice Paid + $11 credit + books balance (same assertions as core, now through routes + auth)
- [ ] T-11/CK-4: 50 invoices created (incl. simulated create+rollback) → numbers strictly sequential, no gaps/burns
- [ ] CK-12 negative set: accountant-role session attempting every POST/PUT/DELETE in these routers → 403, while GETs succeed
- [ ] Every mutating route requires CSRF header (403 without); partials send `Cache-Control: no-store`
- [ ] Overdue derived from due date at read time (no stored status); invoice preview renders exact amounts to the cent

#### Subtasks

- [ ] Implement `app/routes/customers.py` + screens
- [ ] Implement `app/routes/invoices.py` (create/preview/official-post, D-10 counter flow wired) + screens
- [ ] Implement `app/routes/payments.py` (allocation + credit application inside D-7 transaction) + screens
- [ ] Recurring-template CRUD screens consuming `ledger/recurring.py`
- [ ] Wire role gate + CSRF on all new routes (reuse Step 4 dependency choke point)
- [ ] Write `tests/test_ar_web_e2e.py` (T-5 web + CK-12 negative role matrix for AR routes)
- [ ] Write `tests/test_invoice_gapless_e2e.py` (T-11) and `tests/test_recurring_e2e.py` (T-14 UI half)

#### Blockers & Risks

| Item | Type | Impact | Likelihood | Resolution / Mitigation |
|------|------|--------|------------|-------------------------|
| Route drops CSRF or role dependency | risk | High | Med | Mitigation: Step 4 shared dependency + router-level dependency; negative-test matrix re-run per router (CK-12) |
| Preview vs official-post confusion (draft leak) | risk | Med | Med | Mitigation: preview renders from unsaved input; official post is a distinct action; tests assert preview never persists |
| Transaction wrapper bypass (direct psycopg calls in routes) | risk | High | Low | Mitigation: single wrapper call site per flow; reviewer traces; grep for raw connection usage in `app/routes/` |
| HTMX UX regression (double-submit on accept) | risk | Low | Med | Mitigation: `HX-Redirect` after POST (trap 9); test asserts idempotent handling of replayed submission |