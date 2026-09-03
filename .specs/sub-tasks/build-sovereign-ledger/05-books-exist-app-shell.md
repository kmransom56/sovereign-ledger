# Step 5 — Books-Exist App Shell: CoA/Entries Screens, Trial Balance, Deploy

**Task File:** .specs/tasks/draft/build-sovereign-ledger.feature.md
**Phase:** 1 — Foundation (books exist)
**Model:** opus
**Agent:** sdd:developer
**Depends on:** Step 4
**Parallel with:** — (Phase 1 exit step)
**Note:** Locked decisions D-11 (Jinja2 + vendored htmx.org 2.0.10 committed to `app/static/`, `jinja2-fragments` 1.12.0, `Cache-Control: no-store` partials), D-14 (rootless Podman quadlets, ports 11240/11241, `:Z` SELinux binds, pinned postgres:16.15). Phase 1 gate T-8 (CK-1) lands here.

**Goal:** Deliver Phase 1's independently-usable increment: CoA + manual journal entry screens, the trial-balance report and its route, DB init/seed wiring into the container, Wave opening-balance import, and the deployable quadlet stack — books exist and balance.

Step 5 is the first vertical slice (UI→domain→DB): an operator can create accounts, post a manual entry, see the TB net to $0.00, and run the stack via quadlets. The Wave cutover import script (`scripts/wave_cutover_import.py`) lands here because CK-1/T-8 opening balances are a Phase 1 gate.

#### Expected Output

- `app/routes/accounts.py`, `app/routes/entries.py` + `app/templates/` for CoA and journal-entry screens (HTMX, vendored `app/static/htmx.min.js` 2.0.10)
- `reports/trial_balance.py` (pure function) + `app/routes/reports.py` TB endpoint (extends through P5)
- `scripts/wave_cutover_import.py`: Wave CSV export → opening-balance entries via Step 3 helper
- `scripts/init_db.py` wired into container entrypoint; `Containerfile`; `deploy/sovereign-ledger-app.container`, `deploy/sovereign-ledger-db.container`, `deploy/sovereign-ledger-db.volume` (ports 11240/11241)
- `tests/test_tb_report.py`, `tests/test_app_books_e2e.py` (T-8), `tests/test_tb_golden.py` (first golden file)

#### Success Criteria

- [ ] `uv run pytest tests/test_tb_report.py tests/test_app_books_e2e.py -q` passes against scratch Postgres
- [ ] T-8/CK-1: seeded opening-balance entries via the Wave import path → opening TB nets to exactly $0.00; every balance-sheet account matches input to the cent
- [ ] Manual journal entry posted via UI flow is balanced, stored, immutable (UPDATE/DELETE refused), and visible in GL order (HR-1/HR-2 through the web path)
- [ ] Posting dated in a closed period via the app is refused with the period named (HR-6 through the web path)
- [ ] `app/static/htmx.min.js` is the vendored 2.0.10 file; no CDN reference anywhere in templates (HR-3)
- [ ] `podman build -f Containerfile` succeeds; quadlet files validate (`systemd-analyze verify` or dry-run); ports 11240/11241 only
- [ ] Coverage gate ≥95% holds on `ledger/` + `reports/`

#### Subtasks

- [ ] Vendor htmx 2.0.10 into `app/static/`; wire Jinja2 + jinja2-fragments partial rendering
- [ ] Implement `app/routes/accounts.py` + CoA screens (role-gated writes)
- [ ] Implement `app/routes/entries.py` (manual JE create/post + reversal-correction action) + screens
- [ ] Implement `reports/trial_balance.py` + `app/routes/reports.py` TB endpoint (HR-9 begins here)
- [ ] Write `scripts/wave_cutover_import.py` (Wave CSV → opening-balance entries) + golden TB test
- [ ] Write `Containerfile` + app/db quadlets + volume (D-14 style per analysis §2.2)
- [ ] Write `tests/test_tb_report.py`, `tests/test_tb_golden.py`, `tests/test_app_books_e2e.py` (T-8)

#### Blockers & Risks

| Item | Type | Impact | Likelihood | Resolution / Mitigation |
|------|------|--------|------------|-------------------------|
| Wave CSV export format undocumented/varying | risk | High | Med | Mitigation: profile-style column mapping in `wave_cutover_import.py`; fallback to manual opening-balance entry documented in operator runbook (Step 17) |
| Rootless Podman SELinux bind-mount denials (`:Z` omitted) | risk | Med | Med | Mitigation: D-14 style mandates `:Z`; deploy smoke test in this step |
| Port 11240/11241 conflict on host | blocker | High | Low | Resolution: analysis §2.3 verified free; deploy smoke asserts bind succeeds, else stop and re-verify |
| CDN temptation for htmx | risk | High | Low | Mitigation: HR-3 + grep test asserting no `https://` script src in templates |
| Step oversized (5 artifacts) | risk | Med | Med | Mitigation: screens are two routers only; TB report is one pure function; deploy files are template-following; reviewer verifies as one vertical slice |