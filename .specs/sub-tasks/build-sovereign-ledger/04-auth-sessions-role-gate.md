# Step 4 — Auth, Sessions, CSRF, Role Gate

**Task File:** .specs/tasks/draft/build-sovereign-ledger.feature.md
**Phase:** 1 — Foundation (books exist)
**Model:** opus
**Agent:** sdd:developer
**Depends on:** Step 3 (needs entries domain for the negative-test mutating route)
**Parallel with:** — (serial; Step 5 waits on this)
**Note:** Locked decisions D-12 (argon2-cffi 25.1.0 called directly, never passlib; OWASP-floor Argon2id m=19456/t=2/p=1 + `check_needs_rehash()`), D-11 (itsdangerous signed cookies `SameSite=Strict`, `https_only` + per-session CSRF header on every POST — trap 10). Installs argon2-cffi + itsdangerous here (first consumer).

**Goal:** The security foundation of `app/`: password hashing, signed-cookie sessions, per-session CSRF enforcement, and the two-role dependency (admin vs accountant-read) applied to every mutating route — negatively tested per CK-12/BR-17.

Step 4 builds only the security layer, no screens: FastAPI app factory, auth router, dependencies, and the role-gate that later route steps (5, 7, 9, 13–15) consume. Auth is critical domain; it gets its own step so its verification (negative tests on every mutating path) is meaningful rather than buried.

#### Expected Output

- `app/main.py`: FastAPI app factory, session middleware wiring, dependency registration, `/healthz`
- `app/routes/auth.py`: login/logout, argon2 verify + `check_needs_rehash()` on login, signed-cookie session issue
- `app/dependencies.py`: `require_admin` / `current_user` / CSRF-verify dependency; single choke point used by all future mutating routes
- `config/settings.py` extension: session secret, cookie flags, role constants
- `tests/test_auth.py`: unit + FastAPI TestClient tests incl. negative role tests
- Users seed: Keith = admin (argon2 hash); accountant = read-only role constant

#### Success Criteria

- [ ] `uv run pytest tests/test_auth.py -q` passes
- [ ] Login with correct password sets a signed cookie with `SameSite=Strict`; tampered cookie rejected
- [ ] Every POST without the per-session CSRF header returns 403 (trap 10) — test covers a representative mutating route
- [ ] Accountant role: every write attempt (representative POST/PUT/DELETE) refused with 403 while GET succeeds (CK-12 negative core)
- [ ] `check_needs_rehash()` invoked on successful login (asserted via test double)
- [ ] Argon2id parameters match OWASP floor m=19456 KiB, t=2, p=1 (verified in test)

#### Subtasks

- [ ] Install argon2-cffi 25.1.0 + itsdangerous pins (folded; first consumer)
- [ ] Write `app/main.py` factory + `/healthz`
- [ ] Write `app/routes/auth.py` (login/logout, rehash check)
- [ ] Write `app/dependencies.py` (session auth, CSRF verify, `require_admin` role gate as the single choke point)
- [ ] Extend `config/settings.py` (session secret via env, cookie flags, roles)
- [ ] Seed users table rows (Keith admin; accountant read-only) with argon2 hashes
- [ ] Write `tests/test_auth.py`: login flow, cookie flags, CSRF refusal, role negative tests, rehash assertion

#### Blockers & Risks

| Item | Type | Impact | Likelihood | Resolution / Mitigation |
|------|------|--------|------------|-------------------------|
| CSRF token not enforced on a later route added in Steps 5–15 | risk | High | Med | Mitigation: enforcement lives in the shared dependency + a router-level dependency so adding a route without it fails tests; Step 7/9/13 wire it and their tests re-verify |
| Session secret committed to repo | risk | High | Low | Mitigation: env-driven via `config/settings.py`; test asserts absence of default secret |
| Role gate bypass via missing dependency on a new route | risk | High | Med | Mitigation: negative tests template shipped in `tests/test_auth.py` and reused per route step; reviewer checks each new router wires `require_admin` |
| passlib temptation (research F-4) | risk | Low | Low | Mitigation: D-12 forbids passlib; reviewer enforces direct argon2-cffi usage |