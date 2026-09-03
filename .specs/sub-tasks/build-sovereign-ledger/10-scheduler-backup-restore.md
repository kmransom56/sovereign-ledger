# Step 10 — Scheduler + Backup/Restore Orchestration

**Task File:** .specs/tasks/draft/build-sovereign-ledger.feature.md
**Phase:** 3 — AR & Recurring
**Model:** sonnet
**Agent:** sdd:developer
**Depends on:** Step 8 (recurring logic), Step 4 (app/auth wiring), Step 5 (quadlet patterns)
**Parallel with:** Step 11 (AP domain — independent), Step 9 (AR routes, different artifacts)
**Note:** Locked decisions D-13 (systemd user timers, `Persistent=true`, no cron/apscheduler — SKILL trap 13), D-14 (quadlet deployment), CK-13 (nightly `pg_dump` on self-owned storage with 7-generation rotation + monthly restore drill). Migration `0003` (recurring templates persistence).

**Goal:** Recurring invoice generation driven by a systemd user timer (idempotent, pause-respecting), nightly `pg_dump` with 7-generation rotation on the same timer family, a restore drill script, and backup/restore smoke tests — the unattended-operations layer.

Step 10 wraps Step 8's pure recurring logic in a CLI (`jobs/run_recurring.py`) and mounts it on user timers; the same pattern hosts the backup job. No scheduling logic is invented here — timers only trigger idempotent runs.

#### Expected Output

- `db/migrations/0003_recurring.sql` (templates + run log for idempotency)
- `jobs/run_recurring.py` CLI (calls `ledger/recurring.py`; idempotent per cycle via run-log; never posts to closed periods)
- `jobs/backup.py` (`pg_dump` custom format, 7-generation rotation, checksum manifest)
- `jobs/restore.py` (restore + verification pass)
- `deploy/sovereign-ledger-recurring.timer/.service`, `deploy/sovereign-ledger-backup.timer/.service` (user units, `Persistent=true`)
- `tests/test_recurring_jobs.py` (T-14 job half), `tests/test_backup_restore.py`

#### Success Criteria

- [ ] `uv run pytest tests/test_recurring_jobs.py tests/test_backup_restore.py -q` passes
- [ ] T-14: timer-simulated runs (invoke `jobs/run_recurring.py` twice for the same cycle) → exactly one invoice per cycle; paused template generates nothing; closed-period cycle deferred with log line
- [ ] Backup: dump + rotation test → exactly 7 generations retained, oldest deleted; checksum manifest written
- [ ] Restore drill: restore into scratch DB → row counts + TB net-to-$0.00 verified by `jobs/restore.py` verification pass
- [ ] Timer units validate (`systemd-analyze verify`); `Persistent=true` set; no cron/apscheduler anywhere (`grep` test)
- [ ] Run-log prevents duplicate generation across concurrent invocations

#### Subtasks

- [ ] Write `db/migrations/0003_recurring.sql` (templates + idempotency run-log)
- [ ] Implement `jobs/run_recurring.py` (idempotent cycle generation, closed-period deferral logging)
- [ ] Implement `jobs/backup.py` (pg_dump custom format + 7-gen rotation + manifest)
- [ ] Implement `jobs/restore.py` (restore + TB/row-count verification)
- [ ] Write quadlet timer/service units for recurring + backup (`Persistent=true`, D-13/D-14 style)
- [ ] Write `tests/test_recurring_jobs.py` (T-14 job half: idempotency, pause, closed-period)
- [ ] Write `tests/test_backup_restore.py` (rotation count, restore verification, TB balance after restore)

#### Blockers & Risks

| Item | Type | Impact | Likelihood | Resolution / Mitigation |
|------|------|--------|------------|-------------------------|
| Timer fires while previous run still executing (overlap) | risk | Med | Med | Mitigation: run-log idempotency key + advisory lock in job; test simulates concurrent invocations |
| systemd user timers not enabled in rootless context | blocker | High | Low | Resolution: `systemctl --user enable --now` verified during deploy smoke (Step 17); lingering enabled for the user |
| Backup job failing silently for months | risk | High | Med | Mitigation: checksum manifest + dashboard Step 13 backup tile + restore drill in operator runbook (Step 17) |
| pg_dump version mismatch vs PG16 container | risk | Med | Low | Mitigation: run pg_dump inside the db container image; version pinned in Containerfile |
| Restore into wrong DB (footgun) | risk | High | Low | Mitigation: `jobs/restore.py` requires explicit `--target` and refuses non-empty non-scratch DBs |