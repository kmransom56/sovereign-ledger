# Step 17 — Deploy Hardening + Operations Runbook

**Task File:** .specs/tasks/draft/build-sovereign-ledger.feature.md
**Phase:** 4 — AP & Money UI Completion
**Model:** sonnet
**Agent:** sdd:developer
**Depends on:** Step 5 (quadlets), Step 10 (timers/backup)
**Parallel with:** Steps 15, 16 (ops artifacts — no shared files)
**Note:** Locked decisions D-14 (rootless quadlets, 11240/11241), CK-13 (backup verify + restore drill), CK-1 (cutover opening balances). This step finalizes the operational story; actual cutover is an operator action (P6).

**Goal:** Production-grade deployment hardening and the operator runbook: quadlet stack finalization on 11240/11241 with healthchecks, restore-drill integration, log hygiene, and a written runbook covering deploy, backup/restore drill, period close, cutover from Wave, and failure recovery.

Step 17 turns "works on scratch" into "operable on the host": the same artifacts Keith will run daily, with the runbook that makes Keith the operator. The cutover dry-run against a restored scratch backup proves the documented cutover procedure without touching real data.

#### Expected Output

- Final `Containerfile` + `deploy/*.container/*.volume/*.timer` (healthchecks, `:Z` labels, restart policy, `Persistent=true`)
- `scripts/healthcheck.py` (app `/healthz` + DB reachability); systemd `ConditionPathExists` guards where applicable
- `docs/runbook.md`: deploy, upgrade, backup, restore drill, period close, Wave cutover, common failures (port conflicts, SELinux, timer lingering)
- `scripts/cutover_dryrun.py`: restore latest backup → run T-8/T-10 flows against it → report
- `tests/test_deploy_smoke.py` (build + unit-validate + smoke on scratch), `tests/test_runbook_cutover.py` (T-10 procedure assertions)

#### Success Criteria

- [ ] `uv run pytest tests/test_deploy_smoke.py tests/test_runbook_cutover.py -q` passes
- [ ] `podman build` succeeds; quadlet units `systemd-analyze verify` clean; app answers `/healthz` on 11240, DB on 11241, nothing else bound
- [ ] Restore drill: latest backup restored to scratch → `scripts/cutover_dryrun.py` passes books-exist + books-closed checks (T-10)
- [ ] Backup tile in dashboard shows current manifest generation (ties to Step 10/13)
- [ ] Runbook covers all six listed procedures with real commands; commands in runbook executed once during this step and verified (no untested commands)
- [ ] Timers enabled in a scratch user session: recurring + backup fire (log evidence), `Persistent=true` honored

#### Subtasks

- [ ] Finalize Containerfile + all deploy units (healthchecks, `:Z`, restart policies)
- [ ] Implement `scripts/healthcheck.py` + guards
- [ ] Implement `scripts/cutover_dryrun.py` (restore → T-8/T-10 assertions → report)
- [ ] Write `docs/runbook.md` (six procedures) and execute each command once to verify
- [ ] Write `tests/test_deploy_smoke.py` + `tests/test_runbook_cutover.py`

#### Blockers & Risks

| Item | Type | Impact | Likelihood | Resolution / Mitigation |
|------|------|--------|------------|-------------------------|
| Host-specific SELinux/port issues surface only at deploy | risk | Med | Med | Mitigation: smoke tests run on this host (analysis §2.3 verified ports); runbook documents the two known failure modes and fixes |
| Runbook rot (commands drift from scripts) | risk | Med | Med | Mitigation: T-10 procedure test asserts runbook commands match script names/flags; reviewer re-executes during phase review |
| Quadlet unit drift from Step 5/10 drafts | risk | Med | Med | Mitigation: single source of truth under `deploy/`; Step 5/10 units were drafts, this step finalizes and both smoke-test |
| Cutover dry-run accidentally touches real Wave data | risk | High | Low | Mitigation: dry-run operates only on scratch restore; script refuses real-DB targets (mirrors Step 10 restore guard) |