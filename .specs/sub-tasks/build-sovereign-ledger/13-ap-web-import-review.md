# Step 13 — AP Web + AP Import Review (Bills into the Queue)

**Task File:** .specs/tasks/draft/build-sovereign-ledger.feature.md
**Phase:** 4 — AP & Money UI Completion
**Model:** sonnet
**Agent:** sdd:developer
**Depends on:** Step 11 (AP domain), Step 7 (review-queue machinery)
**Parallel with:** Step 15 (independent routers/reports; no shared files — Step 14 depends on this step)
**Note:** Reuses Step 7's queue/accept mechanics for AP; D-7 posting; CK-12 negative set.

**Goal:** Vendor/bill/check screens plus AP-side import review: vendor-entered bills can flow through the same review queue as bank drafts (imported bill batches accepted into AP), and check-run + vendor payment screens land.

Step 13 completes the payables UX by reusing the Step 7 human-gate pattern — no new posting semantics, only new routes/templates consuming Step 11 decisions and Step 7 machinery.

#### Expected Output

- `app/routes/vendors.py`, `app/routes/bills.py` (enter + review-accept into AP + pay), `app/routes/checks.py` (check-run + register view) + templates
- AP import path: vendor bill batches (CSV) routed through `import_batches`/review queue with AP-type drafts
- `tests/test_ap_web_e2e.py` (T-12 via web: enter bill → pay by check → register view; duplicate-bill refusal through UI)

#### Success Criteria

- [ ] `uv run pytest tests/test_ap_web_e2e.py -q` passes vs scratch Postgres
- [ ] T-12 web path: bill entered → paid by check → register shows entry; duplicate bill attempt through UI refused with the existing bill named
- [ ] AP-type drafts: imported bill batch accepted → AP bills created, nothing auto-posted (HR-5), queue counts exact
- [ ] CK-12 negative set for all new routers (accountant 403 on writes, admin succeeds)
- [ ] CSRF + no-store + `HX-Redirect` conventions hold on every new route
- [ ] Coverage gates unchanged (ledger/reports ≥95%, app ≥90%)

#### Subtasks

- [ ] Implement `app/routes/vendors.py` + screens
- [ ] Implement `app/routes/bills.py` (enter + review-accept + pay) + screens
- [ ] Implement `app/routes/checks.py` (check-run creation + register view) + screens
- [ ] Extend Step 7 queue to carry AP-type drafts (bill batches)
- [ ] Write `tests/test_ap_web_e2e.py` (T-12 web + duplicate refusal + role/CSRF negative matrix)

#### Blockers & Risks

| Item | Type | Impact | Likelihood | Resolution / Mitigation |
|------|------|--------|------------|-------------------------|
| AP acceptance bypasses review gate | risk | High | Low | Mitigation: same accept endpoint family as Step 7; T-12 + queue-count assertions |
| Queue extension forks Step 7 logic | risk | Med | Med | Mitigation: generalize the existing queue module rather than fork; reviewer diffs for divergence |
| Check-run UX double-submits | risk | Low | Low | Mitigation: `HX-Redirect` pattern; idempotent replay test |