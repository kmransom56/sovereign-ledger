---
name: sovereign-ledger-stack
description: Use when building or extending the Sovereign Ledger stack (Postgres/FastAPI/HTMX quadlet accounting app) — pins, traps, and patterns.
topics: postgres,fastapi,htmx,quadlet,double-entry,ofx,hypothesis
created: 2026-09-02
updated: 2026-09-02
updated-by: judge-2a fix loop (researcher remediation)
scratchpad: .specs/scratchpad/8268ddb9.md
---

# Sovereign Ledger Stack

Verified 2026-09-02 against PyPI/GitHub/jsDelivr/endoflife.date and canonical docs.
Full evidence: `.specs/analysis/research-report.md` (same repo).

## Pinned stack

| Component | Pin | Why |
|---|---|---|
| postgres image | 16.15 | EOL 2028-11-09; nothing in 17/18 is required |
| psycopg | 3.3.5 | server-side binding, dict_row, transaction blocks; NOT psycopg2 |
| fastapi | 0.141.1 | Jinja2Templates (Starlette) is the documented pattern |
| uvicorn | 0.52.4 | sync psycopg + plain `def` endpoints (threadpool) |
| pydantic | 2.13.5 | DTO validation |
| jinja2 | 3.1.6 | |
| jinja2-fragments | 1.12.0 | HTMX partials share full-page templates (repo: **sponsfreixes**) |
| htmx.org | 2.0.10 | **vendor htmx.min.js** — no CDN (HR-3 blocks external net) |
| itsdangerous | 2.2.0 | signed-cookie sessions, same_site=strict, https_only |
| argon2-cffi | 25.1.0 | Argon2id; call directly — **never passlib** (dead since 2020) |
| ofxtools | 1.1.1 | OFX 1.x/2.x + FITID; **never ofxparse** (0.21/2021, GitHub 404) |
| hypothesis | 6.167.1 | `RuleBasedStateMachine` + `@invariant` for ledger properties |
| pytest / pytest-cov | 9.1.1 / 7.1.0 | `--cov-fail-under=95` on `ledger/` + `reports/` |
| dbmate | active (7.3k★) | plain ordered SQL migrations; Alembic only if raw-op discipline kept |

## References

Canonical documentation, last verified 2026-09-02 (full list: research-report.md §10).

| Resource | What it covers | URL |
|---|---|---|
| PostgreSQL 16: transaction isolation | SERIALIZABLE semantics + 40001 retry caveat | https://www.postgresql.org/docs/16/transaction-iso.html |
| PostgreSQL 16: deferred constraints | `DEFERRABLE`/`INITIALLY DEFERRED` mechanics | https://www.postgresql.org/docs/16/constraints.html#CONSTRAINTS-DEFERRED-CONSTRAINTS |
| PostgreSQL 16: numeric types | `NUMERIC` precision for money | https://www.postgresql.org/docs/16/datatype-numeric.html |
| PostgreSQL 16: backup / pg_dump | MVCC-consistent dumps | https://www.postgresql.org/docs/16/backup.html |
| FastAPI: templates | Jinja2Templates (Starlette) — the documented pattern | https://fastapi.tiangolo.com/advanced/templates/ |
| FastAPI: async | sync `def` endpoints + threadpool vs `async def` | https://fastapi.tiangolo.com/async/ |
| Psycopg 3 docs | server-side binding, dict_row, transaction blocks | https://www.psycopg.org/psycopg3/docs/ |
| htmx docs | attributes, `hx-boost`, events, extensions | https://htmx.org/docs/ |
| jinja2-fragments | HTMX partials sharing full-page templates | https://jinja2-fragments.readthedocs.io/ |
| Podman quadlet units | `.container`/`.kube`, `Type=notify`, PublishPort | https://docs.podman.io/en/latest/markdown/podman-systemd.unit.5.html |
| Hypothesis | `RuleBasedStateMachine`, `@invariant`, stateful testing | https://hypothesis.readthedocs.io/en/latest/stateful.html |
| argon2-cffi API | `PasswordHasher` defaults, `check_needs_rehash` | https://argon2-cffi.readthedocs.io/en/stable/api.html |
| OWASP password storage | Argon2id m=19456 KiB / t=2 / p=1 floor | https://owasp.org/www-project-cheat-sheets/cheatsheets/Password_Storage_Cheat_Sheet.html |
| OFX spec body | OFX 1.x/2.x; QFX = Intuit OFX 1.x variant | https://www.ofx.net/ |
| endoflife.date: PostgreSQL | EOL dates backing the 16.x pin | https://endoflife.date/postgresql |

Install (PyPI pins verified 2026-09-02):

```bash
pip install \
  "psycopg[binary]==3.3.5" \
  "fastapi==0.141.1" \
  "uvicorn==0.52.4" \
  "pydantic==2.13.5" \
  "jinja2==3.1.6" \
  "jinja2-fragments==1.12.0" \
  "itsdangerous==2.2.0" \
  "argon2-cffi==25.1.0" \
  "ofxtools==1.1.1" \
  "python-dateutil==2.9.0.post0" \
  "charset-normalizer==3.5.1" \
  "hypothesis==6.167.1" \
  "pytest==9.1.1" \
  "pytest-cov==7.1.0"
```

Not pip-installed: **htmx.org 2.0.10** is vendored (`htmx.min.js` committed to the repo — HR-3); **dbmate** installs as a standalone binary (see its GitHub releases).

## Known traps

1. **npm `htmx` is a 0.0.2 squat** — the package is `htmx.org`. Moot when vendored (always vendor).
2. **ofxparse is abandoned** (PyPI frozen 2021, repo 404). Reflexively reaching for it is the #1 import-path mistake.
3. **passlib is unmaintained** (1.7.4, 2020). Use `argon2.PasswordHasher` directly; OWASP floor m=19456 KiB, t=2, p=1; keep `check_needs_rehash()` on login.
4. **Balance trigger must be deferred**: `CREATE CONSTRAINT TRIGGER ... DEFERRABLE INITIALLY DEFERRED` for the per-entry SUM=0 check — a plain row trigger fires per-line insert and rejects mid-transaction states.
5. **SERIALIZABLE aborts must be retried**: SQLSTATE 40001 → bounded retry/backoff wrapper. Scope serializable to money-mutation transactions only; reads stay READ COMMITTED.
6. **Gapless invoice numbers**: sequences burn numbers on rollback → locked counter row inside the posting transaction.
7. **Import idempotency hashes canonicalized content**, not raw bytes: normalize newlines/whitespace/decimals; hash whole file + per line; OFX lines keyed by bank `FITID`.
8. **Never float money**: parse → Decimal → validate 2dp → integer cents at the importer boundary. Ledger stores signed BIGINT cents (+ debit, − credit). No `money` type.
9. **Quadlet rootless**: ports ≥1024 only; `:Z` on SELinux bind mounts; `Type=notify` auto-set for `.container`; systemd `.timer` runs recurring-invoice CLI; `pg_advisory_lock` guards against double-generation.
10. **HTMX partials**: `Cache-Control: no-store`; use `HX-Redirect`/`HX-Trigger` headers; `hx-boost` for progressive enhancement. **CSRF**: `SameSite=Strict` cookies plus a per-session token sent in a custom header on every POST — two roles share the browser, so don't rely on SameSite alone.
11. **Hypothesis on DB tests**: `deadline=None` for Postgres-backed stateful tests; generate balanced entries by construction, then separately assert unbalanced ones are refused.
12. **Bank-file encoding + profile versioning**: QFX/OFX/CSV statements frequently arrive cp1252/latin-1, not UTF-8 — sniff with `charset-normalizer` (pinned above) or decode explicitly per-account; never assume UTF-8. Version-stamp each per-account import profile so a bank layout change cannot silently re-map old imports.

## Pattern examples

Deferred balance check (trap 4) — per-entry, not per-line:

```sql
CREATE OR REPLACE FUNCTION assert_entry_sum_zero() RETURNS trigger AS $$
BEGIN
  IF (SELECT COALESCE(SUM(amount_cents), 0) FROM journal_lines
      WHERE entry_id = NEW.entry_id) <> 0 THEN
    RAISE EXCEPTION 'journal entry % is not balanced', NEW.entry_id;
  END IF;
  RETURN NULL;
END $$ LANGUAGE plpgsql;

CREATE CONSTRAINT TRIGGER trg_entry_balanced
  AFTER INSERT ON journal_lines
  DEFERRABLE INITIALLY DEFERRED
  FOR EACH ROW EXECUTE FUNCTION assert_entry_sum_zero();
```

SERIALIZABLE retry (trap 5) — money mutations only; reads stay READ COMMITTED:

```python
import time
from psycopg.errors import SerializationFailure  # SQLSTATE 40001

def post_with_retry(conn, work, attempts=5):
    for i in range(attempts):
        try:
            with conn.transaction(isolation_level="SERIALIZABLE"):
                work(conn)  # all money mutations inside one tx
            return
        except SerializationFailure:
            if i == attempts - 1:
                raise
            time.sleep(0.05 * 2**i)  # bounded exponential backoff
```

## Layout invariants

- `ledger/` + `reports/` are pure (zero I/O); DB/network only in `app/`, `importers/`, CLI.
- Four append-only tables (`accounts`, `journal_entries`, `journal_lines`, `fiscal_periods`) protected by triggers **and** `REVOKE UPDATE, DELETE` from the app role.
- Corrections = reversing entries only; nothing auto-posts from imports (human accept required); reconciliation completes only at exactly $0.00 difference.
- Full app must function with external network blocked — no CDN assets, no outbound calls, ever.

## Changelog

| Date | Change |
|---|---|
| 2026-09-02 | Initial verified skill (pins, traps, invariants) from research-report.md. |
| 2026-09-02 | Judge 2a remediation: added References + pinned install block, encoding/profile-versioning + CSRF traps, frontmatter metadata, pattern examples. |