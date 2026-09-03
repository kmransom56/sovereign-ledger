# Step 1 — Project Scaffold + Pure Money Engine

**Task File:** .specs/tasks/draft/build-sovereign-ledger.feature.md
**Phase:** 1 — Foundation (books exist)
**Model:** opus
**Agent:** sdd:developer
**Depends on:** — (none; Level 0)
**Parallel with:** Step 2
**Note:** Locked decisions D-1, D-3 apply verbatim: signed BIGINT integer cents (+ = debit, − = credit), USD only, `ledger/` is pure zero-I/O. Install everything this step consumes (uv project init, hypothesis 6.167.1, pytest) HERE — no standalone install step exists.

**Goal:** Create the repository skeleton (uv, Python 3.12, config) and the pure domain core — `ledger/types.py` and `ledger/engine.py` — that every later step builds on, proven by hypothesis property tests (T-1 core invariants).

Step 1 is the leaf of the dependency tree: money types, `JournalLine`, `JournalEntry`, and the balance/posting engine with the Σ=0 invariant. It deliberately contains no DB, HTTP, or filesystem code — hard rule 1 starts here, and the CI grep gate that enforces it is created in this step so it can never regress.

#### Expected Output

- `pyproject.toml`, `uv.lock`, `.python-version` (3.12) at repo root, with pinned deps: hypothesis, pytest, pytest-cov
- `config/settings.py` (pydantic-settings, env-driven), `config/logging.py`
- `ledger/__init__.py`, `ledger/types.py` (Money-as-int-cents helpers, `JournalLine`, `JournalEntry`, account type enums), `ledger/engine.py` (balance invariant, `post()` construction that refuses unbalanced entries)
- `tests/test_engine.py` — hypothesis `RuleBasedStateMachine` property tests (deadline=None)
- CI boundary gate: grep check failing the build if `fastapi|psycopg|asyncpg|requests|httpx` appears under `ledger/` or `reports/`
- `README.md` stub with stack pins pointer to `.claude/skills/sovereign-ledger-stack/SKILL.md`

#### Success Criteria

- [ ] `uv run pytest tests/test_engine.py -q` passes; the state machine drives ≥1,000 balanced/unbalanced entry scenarios
- [ ] `ledger/engine.py` raises on any entry whose `sum(line.amount_cents) != 0` — property test proves no unbalanced `JournalEntry` can be constructed
- [ ] `grep -rEn "fastapi|psycopg|asyncpg|requests|httpx" ledger/` returns nothing; the gate script exits non-zero when a violation is injected
- [ ] `uv run python -c "from ledger.types import JournalEntry"` succeeds
- [ ] BIGINT-safe arithmetic demonstrated: amounts beyond ±2^31 cents handled exactly in tests

#### Subtasks

- [ ] Initialize uv project (pyproject.toml, .python-version, uv.lock) with pinned test deps — folded install, no standalone step
- [ ] Write `config/settings.py` + `config/logging.py` (env-driven, no secrets in repo)
- [ ] Implement `ledger/types.py`: int-cent primitives, `JournalLine`, `JournalEntry` dataclasses, account-type enums per D-3
- [ ] Implement `ledger/engine.py`: construction-time Σ=0 invariant, atomic posting value objects (HR-1 core)
- [ ] Write `tests/test_engine.py`: hypothesis RuleBasedStateMachine covering balance, sign semantics (+debit/−credit), overflow-scale amounts (T-1 foundations)
- [ ] Add boundary grep gate script + wire into pyproject as a check target
- [ ] Write README stub linking SKILL.md pins

#### Blockers & Risks

| Item | Type | Impact | Likelihood | Resolution / Mitigation |
|------|------|--------|------------|-------------------------|
| uv not present on host | blocker | Med | Low | Resolution: install uv per estate baseline before Step 1 starts; verify `uv --version` |
| hypothesis deadline flakiness on CI-style runs | risk | Low | Med | Mitigation: set `deadline=None` per SKILL trap 11; keep state machine steps bounded |
| Sign-convention confusion (+debit/−credit) leaking into later steps | risk | High | Med | Mitigation: encode sign semantics in type names + docstring + property tests now; Step 2 trigger asserts same convention |
| Accidental future import of I/O libs into `ledger/` | risk | High | Low | Mitigation: grep gate shipped in this step, run in every later step's test command |