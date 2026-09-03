# Sovereign Ledger

An append-only, double-entry ledger service. Every journal entry balances
exactly (Σ signed cents = 0) under the locked sign convention **+ = debit,
− = credit** (decision D-3); money is always a signed Postgres `BIGINT`
count of integer cents — never floats, never the `money` type. The domain
core (`ledger/`, later `reports/`) is pure — zero I/O imports — and CI
enforces that with the boundary gate.

* Stack pins, traps, and conventions: `.claude/skills/sovereign-ledger-stack/SKILL.md`
* Architecture & specification: `.specs/tasks/in-progress/build-sovereign-ledger.feature.md`

Verify locally:

```bash
uv run python scripts/check_boundaries.py   # boundary gate — exit 0 = clean
uv run pytest                               # hypothesis property tests
```