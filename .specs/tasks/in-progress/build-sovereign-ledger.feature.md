---
title: Build Sovereign Ledger, a self-hosted double-entry accounting system
depends_on: []
skill: .claude/skills/sovereign-ledger-stack/SKILL.md
---

## Skill Reference

**Required skill:** `.claude/skills/sovereign-ledger-stack/SKILL.md` — the reusable
research skill created for this task. Load it before any implementation phase. It
carries the live-verified stack pins (PostgreSQL 16, FastAPI, ofxtools 1.1.1,
argon2-cffi, charset-normalizer 3.5.1, htmx.org 2.0.10 vendored, dbmate), a
References table of canonical doc URLs, and the Known-traps list (DEFERRABLE
balance trigger, 40001 serialization retry, cp1252 bank-file decoding, per-session
CSRF). Implementation agents must consult its pinned install block for exact
versions and its References table before adding dependencies.

## Initial User Prompt

> I was connected to WAVE for accounting for my business, I want to build my own
> accounting system instead of paying for one, We just need to know what all is
> required for an accounting system that handles money

### Requirements

**Decisions locked during brainstorm (2026-09-02)**

- **Scope**: full Wave replacement for Outset Solutions LLC bookkeeping — ledger,
  AR (invoicing + recurring $49/mo tiers), AP, bank import + reconciliation,
  reports, tax-prep export. Payment *recording* only; card processing stays
  external (see Option A).
- **Option A — record-only money path**: the system never touches card rails or
  payment processors. It books payments after they land in the bank (CSV/QFX/OFX
  import). Zero external dependencies in the money path; fully sovereign.
- **Approach (0.85 fit)**: custom double-entry core — PostgreSQL 16 + FastAPI +
  Jinja2/HTMX server-rendered UI. Deliberate deviation from estate-wide
  SurrealDB: deferred constraints, serializable isolation, and 30 years of
  ledger-proven patterns for the one money-critical system. Rejected
  alternatives: Next.js SPA (0.83, no v1 benefit), ERPNext/Akaunting self-host
  (0.81, off-stack maintenance), TigerBeetle (0.08), Beancount+Fava (0.07),
  event-sourced SurrealDB (0.05).
- **Repo**: `gitea.netintegrate.net/soverigndataadmin/sovereign-ledger`,
  working dir `/media/keith/NVMe/sovereign-ledger/`.

**Architecture**

```
ledger/        pure domain core (journal, postings, money math) — zero I/O
app/           FastAPI + Jinja2 + HTMX routes, no SPA build
importers/     CSV/QFX/OFX parsers, per-account column profiles
reports/       pure functions over the ledger
db/migrations/ hand-written ordered SQL, reviewed like code
tests/         property tests + golden-file report tests + flow tests
deploy/        Containerfile + Podman quadlets (app + postgres), loopback only
```

Hard rules: (1) domain core never touches network or DB; (2) migrations are
plain SQL; (3) no outbound calls from app code — PDFs render for manual sending.

**Data model (15 tables)** — four sacred, append-only:
`accounts` (type + subtype driving tax mapping), `journal_entries`, `journal_lines`
(signed integer cents: + = debit, − = credit; DB trigger enforces per-entry
SUM=0 and blocks UPDATE/DELETE), `fiscal_periods` (open/closed/locked by
trigger). Plus: customers, invoices, invoice_lines, payments (allocation in
serializable transactions; overpayment → customer_credits liability), vendors,
bills, bill_lines, bank_accounts (1:1 to ledger accounts), import_batches
(idempotent by content hash), bank_lines, reconciliations (closing locks
cleared lines), audit_log (hash-chained), users (admin + accountant-read),
attachments (content-addressed on NVMe). Single currency (USD cents), single
entity for v1.

**Money flows (all end in a balanced journal entry)**
1. Invoice: post on creation (Dr AR / Cr Income); payment: Dr Bank / Cr AR,
   status flip in same transaction
2. Bills: Dr Expense / Cr AP; payment: Dr AP / Cr Bank; recurring templates
3. Bank import: parse → suggest (auto-match or learned category rule) → review
   → accept; suggestions are drafts, never auto-posted
4. Reconciliation: statement balance + cleared lines → difference zero → close
   → lines locked
5. Corrections: reversing entries only, never edit/delete
6. Period close: lock period, snapshot reports, CPA bundle export
Scheduling (recurring invoices/bills) = systemd timer invoking CLI in container.

**Reports & tax** — all pure derivations, nothing cached: trial balance (must
net to zero), P&L (cash/accrual toggle — ledger stores accrual), balance sheet
(retained earnings derived, never stored), cash flow, AR/AP aging, GL detail,
customer statements. Tax layer: account subtype → Schedule C line mapping;
annual CPA bundle (GL CSV + report PDFs + Schedule C summary + 1099-NEC vendor
tracking). No automated filing.

**Trust & testing**
- argon2 local auth, signed-cookie sessions, LAN/Tailscale binding
- hash-chained audit log; fail-closed money paths (rollback on incomplete entry)
- nightly pg_dump + tested monthly restore drill; 7-year retention
- tests: hypothesis property tests on invariants, golden-file report tests,
  six-flow e2e vs scratch Postgres, import idempotency (same file twice → zero
  duplicates); ≥95% coverage gate on `ledger/` and `reports/`

**Build phases (each independently usable)**
0. Core: ledger module + schema + triggers + property tests
1. Books exist: CoA setup, manual journal entry, trial balance; post Wave
   opening balances via Opening Balance Equity
2. Daily driver: CSV import, review/accept, reconciliation — replaces Wave's
   tracking half
3. AR: customers, invoices, PDFs, payments, recurring tiers, aging, statements
4. AP: vendors, bills, recurring, aging
5. Tax-ready: report suite, Schedule C mapping, CPA bundle, period close
6. Polish: accountant role, audit viewer, backup drill automation

**Cutover**: export Wave CSVs → import at phases 2–3 → go-live at a fiscal
boundary → one month parallel run → reconcile → Wave read-only.

**v1 exclusions**: payroll (single-member LLC = draws), multi-currency,
inventory, sales-tax filing automation, payment processing (Option A).

## Description

Sovereign Ledger is a self-hosted, double-entry accounting system that fully replaces Wave as the books of record for Outset Solutions LLC. **Why**: the business pays indefinitely for bookkeeping software it does not control, keeps its complete financial history in someone else's cloud, and still faces manual rework every tax season. **What it delivers**: permanent, trustworthy, tax-ready books the business owns end-to-end — with zero third parties in the money path (payments are *recorded* after they land in the bank, never *processed*) and exports an outside CPA can consume without system access.

### Scope Included

- **Ledger foundation**: chart of accounts (with tax-mapping subtypes), manual journal entries, Wave opening balances, append-only history (corrections only via reversing entries), tamper-evident audit trail.
- **Invoicing / AR**: customers, line-item invoices posting on creation, send-ready PDFs, payments with all-or-nothing allocation, overpayment → customer credit, recurring $49/mo subscription tiers generating per-cycle invoices with no manual entry, AR aging, customer statements.
- **Bills / AP**: vendors, bills, recurring bill templates, partial payments, AP aging.
- **Bank import + reconciliation**: CSV/QFX/OFX statement import with saved per-account profiles, content-based idempotency (re-import of the same file creates nothing), suggestion → human review → accept (nothing auto-posts), statement reconciliation that completes only at exactly $0.00 difference and locks cleared lines.
- **Financial reporting**: trial balance (always nets to $0.00), P&L with cash/accrual toggle, balance sheet, cash flow, AR/AP aging, GL detail, customer statements — all regenerable for any past period.
- **Tax-prep export**: account subtype → Schedule C line mapping, annual CPA bundle (GL CSV, report PDFs, Schedule C summary, 1099-NEC vendor tracking with configurable threshold), no automated filing.
- **Period close**: in-order locking of fiscal periods, report snapshots at close, late corrections via reversing entries only.
- **Trust**: two roles (Keith = admin; outside accountant = read-only), private-network-only access, nightly backups with monthly *verified* restore drills, 7-year retention.
- **Cutover**: Wave data imported at a fiscal boundary, one full month parallel run, month-end difference must be $0.00 before Wave is demoted to read-only.

### Scope Excluded

- **Payment/card processing** — Option A: record-only money path; cards charged externally, books updated after bank import.
- **Payroll** — single-member LLC takes draws, not payroll.
- **Multi-currency, multi-entity** — single USD currency, single legal entity.
- **Inventory tracking and COGS-per-unit valuation.**
- **Sales-tax computation/filing automation; automated tax filing** — the system prepares, humans file.
- **Outbound transmission** — invoices/statements render as PDFs for manual sending; no email, no bank connectivity, no external API calls in the money path.
- **Derived non-goals** (analyst defaults, see `.specs/analysis/business-analysis.md` §5.2): budgeting/forecasting, estimates/quotes/purchase orders, late fees and dunning, time tracking, customer portal, mobile or public-internet access, more than two roles.

### User Scenarios

**Primary flows**

1. **Monthly bank cycle (Keith)**: download statement → import (idempotent, saved profile) → review each suggested match/category → accept → reconcile against the statement balance → difference $0.00 → close reconciliation → cleared lines lock.
2. **Recurring subscription invoicing**: on the 1st, each active $49/mo Privacy Dawg template auto-generates its invoice → Keith renders the PDF and sends it himself → customer pays externally → after the deposit appears in the bank import, Keith records the payment → invoice flips to Paid, AR falls, bank rises, all-or-nothing.
3. **Period close and CPA handoff**: reconcile all bank activity → close the month (locked, reports snapshotted) → at year end export the CPA bundle by Feb 15 → CPA prepares the return from the bundle; questions ≤ 2.

**Alternative flows**

- **Overpayment**: customer pays $60 on a $49 invoice → invoice Paid, $11 recorded as customer credit (liability), later applied to a future invoice exactly like a payment.
- **Partial bill payment**: $200 of a $500 vendor bill paid → bill shows $300 outstanding in AP aging until cleared.
- **Recurring tier change**: price change affects future cycles only; paused templates stop generating without touching history.
- **Correction of a mistaken entry**: a May misclassification discovered in July is fixed by a reversing entry plus corrected posting in July; May's closed books are untouched; the audit trail links both entries.
- **Import format drift**: bank changes its CSV layout → Keith adjusts the per-account profile, or falls back to manual journal entry so bookkeeping never blocks.

**Error flows**

1. **Bank import mismatch (duplicate guard)**: Keith re-imports a statement already processed (new filename, same content) → the system recognizes it by content and creates **zero** duplicates, reporting "already imported"; ledger totals unchanged.
2. **Overpayment with no open invoice**: payment recorded for a customer with nothing due → the full amount lands as customer credit, never as income; books balance.
3. **Failed reconciliation**: statement balance $4,213.75 vs cleared lines $4,200.00 → completion refused with the $13.75 difference displayed; after the missing line is imported and accepted, the reconciliation completes and locks its lines.
4. **Reversal of a mistaken entry**: any attempt to edit or delete a posted entry is impossible; the only correction path is a reversing entry that references the original, with both visible in the audit trail.
5. **Posting into a closed period**: an entry dated in a closed month is refused, with an explanation naming the closed period.
6. **Unbalanced entry attempt**: any posting path that would store a non-zero-sum entry is rejected outright — nothing is half-stored.

## Acceptance Criteria

**Checklist:**

| ID | Question | Category | Importance |
|-----|----------|----------|------------|
| HR-1 | Does every journal entry balance exactly (debits = credits), with unbalanced entries never stored on any posting path? | hard_rule | Critical |
| HR-2 | Are recorded entries immutable — no update or delete — with corrections made only via reversing entries? | hard_rule | Critical |
| HR-3 | Does the system make zero outbound calls (no payment processing, no bank connectivity, no transmissions) and function fully with external network blocked? | hard_rule | Critical |
| HR-4 | Is bank import idempotent by file content — the same statement re-imported under any filename creates zero duplicates? | hard_rule | Critical |
| HR-5 | Does no imported line ever post without an explicit human accept (nothing auto-posts)? | hard_rule | Critical |
| HR-6 | Is posting into a closed or locked fiscal period always refused? | hard_rule | Critical |
| HR-7 | Can a reconciliation complete only when the statement balance minus cleared lines equals exactly $0.00? | hard_rule | Critical |
| HR-8 | Is an overpayment recorded as customer credit (liability), never as income? | hard_rule | Critical |
| HR-9 | Does the trial balance net to $0.00 for every period, regenerable identically at any later date? | hard_rule | Critical |
| HR-10 | Is the audit log append-only and tamper-evident? | hard_rule | Critical |
| CK-1 | Can Wave opening balances be entered via opening-balance entries so the opening trial balance nets to $0.00 at cutover? | principle | Critical |
| CK-2 | Can a saved per-account import profile be reused without re-mapping columns or date formats? | principle | High |
| CK-3 | Does every imported line arrive as a reviewable draft suggestion (match or category) that can be accepted, edited, or rejected? | principle | Critical |
| CK-4 | Can a reconciliation be completed at $0.00 difference, locking reconciled lines against change? | principle | Critical |
| CK-5 | Can an invoice with line items be created, post on creation (AR up / income up), and render as a send-ready PDF? | principle | Critical |
| CK-6 | Does each active recurring tier generate exactly one invoice per cycle with zero manual entry? | principle | Critical |
| CK-7 | Can a payment be allocated across invoices with invoice status flipping in the same all-or-nothing action? | principle | Critical |
| CK-8 | Does standing customer credit apply to a later invoice exactly like a payment? | principle | High |
| CK-9 | Can vendors, bills, and bill payments be recorded with partial payments visible in AP aging? | principle | High |
| CK-10 | Do all reports (trial balance, P&L cash/accrual, balance sheet, cash flow, AR/AP aging, GL detail, customer statements) render for any past period? | principle | High |
| CK-11 | Does one export produce the complete CPA bundle (GL CSV, report PDFs, Schedule C summary, 1099-NEC tracking)? | principle | High |
| CK-12 | Does the accountant role see all reports/exports while every write attempt is refused? | principle | High |
| CK-13 | Does each monthly restore drill record the restored point-in-time and verification results (books open, TB $0.00, a report regenerates)? | principle | High |
| CK-14 | Are recurring-generation failures (a month's missing invoices) visible to the administrator within one screen? | principle | Medium |
| CK-15 | Is a mistaken entry corrected by a reversing entry in the open period, with the audit trail linking reversal and correction? | principle | Critical |

**Regular Checks:**

- [ ] Weekly: bank statements imported and review queue emptied — no imported line unreviewed for more than 5 business days (books current within days, not weeks)
- [ ] After every import batch: trial balance re-run and confirmed at $0.00
- [ ] Monthly: recurring-generation results reviewed — invoices generated equals active templates; any failure flagged (CK-14)
- [ ] Monthly: AR and AP aging reviewed; overdue receivables actioned
- [ ] Monthly: restore drill executed with recorded verification results (CK-13); nightly backup confirmed on self-owned storage
- [ ] At each period close: reports snapshotted and CPA-bundle exportability confirmed
- [ ] At cutover: one-month parallel run completed with month-end difference $0.00 before Wave is demoted (after one full month running both systems in parallel, month-end differences for every tracked category are $0.00 before Wave goes read-only)

**Rubric:**

| Criterion | Weight |
|-----------|--------|
| Ledger & Posting Correctness | 0.25 |
| Money-Flow Completeness | 0.25 |
| Sovereignty & Access Compliance | 0.15 |
| Reporting & Tax-Export Fidelity | 0.15 |
| Test Rigor & Invariant Coverage | 0.15 |
| Phased Usability & Documentation | 0.05 |
| **Total** | **1.00** |

**Rubric Score Definitions:**

### Ledger & Posting Correctness (Weight: 0.25)

How completely the implementation enforces the double-entry core: balance at every posting path, append-only history, reversing-entry corrections, closed-period refusal, tamper-evident audit.

**Anchors:**
- score_2:
  ```
  Does the app validate that entries balance before saving?
  ```
- score_4:
  ```
  Does every journal entry balance exactly (debits = credits), with unbalanced entries never stored on any posting path?
  ```
- contrast: Same debits-equal-credits question; only the enforcement locus differs — a UI save-time check vs a store-nothing rule on every posting path.

### Money-Flow Completeness (Weight: 0.25)

All six money flows (invoice, bill, import, reconciliation, correction, close) work end-to-end per the scenarios above, including the alternative and error flows.

**Anchors:**
- score_2:
  ```
  - Given statement balance $4,213.75 and cleared lines $4,200.00, when reconciliation is completed with difference $13.75, then the period closes with the difference noted.
  ```
- score_4:
  ```
  - Given statement balance $4,213.75 and cleared lines $4,200.00, when reconciliation is attempted at difference $13.75, then completion is refused and the $13.75 difference is displayed until it is $0.00.
  ```
- contrast: Same $13.75-gap scenario; only the completion behavior differs — the reconciliation closes anyway vs completion is refused until the difference is $0.00.

### Sovereignty & Access Compliance (Weight: 0.15)

Zero external dependencies in the money path; full function with external network blocked; two-role access enforced; private-network-only reachability.

**Anchors:**
- score_2:
  ```
  - [ ] Sovereignty demonstrated: full-cycle test passes; no third-party service in the money path; accountant role enforced read-only
  ```
- score_4:
  ```
  - [ ] Sovereignty demonstrated: full-cycle test passes with external network blocked; no third-party service in the money path; accountant role enforced read-only
  ```
- contrast: Identical clauses except one — the full-cycle test runs with external network blocked (present) vs without that condition (absent).

### Reporting & Tax-Export Fidelity (Weight: 0.15)

Report suite correctness (trial balance zero, accrual/cash toggle, derived retained earnings) and CPA-bundle completeness for a real filing handoff.

**Anchors:**
- score_2:
  ```
  Does one export produce the complete CPA bundle (GL CSV, report PDFs, 1099-NEC tracking)?
  ```
- score_4:
  ```
  Does one export produce the complete CPA bundle (GL CSV, report PDFs, Schedule C summary, 1099-NEC tracking)?
  ```
- contrast: Same one-export bundle question; only the component list differs — the Schedule C summary is included vs omitted.

### Test Rigor & Invariant Coverage (Weight: 0.15)

Property tests on invariants, import idempotency proof, six-flow end-to-end coverage, golden-file report tests, and the ≥95% coverage gate on the domain core and reports.

**Anchors:**
- score_2:
  ```
  - [ ] Import idempotency checked: re-importing a processed statement shows the duplicate warning before posting
  ```
- score_4:
  ```
  - [ ] Import idempotency proven: same content under a different filename creates zero duplicates
  ```
- contrast: Same re-import scenario; only the guarantee differs — a duplicate warning before posting vs a content-hash proof of zero duplicates under a different filename.

### Phased Usability & Documentation (Weight: 0.05)

Each delivered phase is independently usable for real bookkeeping, and a non-accountant operator can run the daily cycle from the documentation alone.

**Anchors:**
- score_2:
  ```
  - [ ] Every delivered phase (0–6) is usable once all phases are complete, with the full scope operable from the operator documentation
  ```
- score_4:
  ```
  - [ ] Every delivered phase (0–6) is independently usable, with the phase's scope operable from the operator documentation alone
  ```
- contrast: Same DoD item otherwise; only the usability timing differs — usable once all phases complete vs each phase independently usable on delivery.

**Test Strategy:**

**Criticality note.** This is money-critical software: a defect that corrupts, duplicates, or loses ledger data is business-unrecoverable and may misstate a tax filing. Therefore the test strategy is invariant-first — the hard rules (HR-1…HR-10) are verified continuously by property-based tests, not spot-checked — and every error flow in the User Scenarios has an explicit test case. A green suite that never exercises the error paths is treated as a failure, not a pass.

**Test Matrix:**

| Type | Size | Framework | Dependencies | Gate |
|------|------|-----------|--------------|------|
| property | small | hypothesis | T-1 covers HR-1, HR-2: pure ledger core with per-entry balance trigger in place | Unbalanced-entry and modification attempts on every posting path store nothing — any stored or altered entry fails the suite (release blocker) |
| e2e | medium | pytest | T-2 covers HR-4, CK-2, CK-3: importer + import_batches content-hash idempotency live | Same statement imported twice under a different filename → zero duplicates and all lines queue as drafts — any duplicate fails (release blocker) |
| e2e | medium | pytest | T-3 covers HR-5, CK-3: 40-line import batch seeded in scratch Postgres | 12 accepted as suggested + 5 edited then accepted → exactly 17 postings, 23 unposted — any other count fails (release blocker) |
| e2e | medium | pytest | T-4 covers HR-7, CK-4: reconciliation with lockable cleared lines | $13.75 gap refuses completion and displays the difference; after fix it completes and locks lines — completing unbalanced or failing to lock fails (release blocker) |
| e2e | medium | pytest | T-5 covers HR-8, CK-7, CK-8: payment allocation in serializable transaction | $60 payment on $49 invoice → Paid + $11 customer credit, books balance; credit later applied to a new invoice — any partial state fails (release blocker) |
| e2e | medium | pytest | T-6 covers HR-6: fiscal_periods open/closed/locked triggers in place | Posting dated in a closed period refused with named-period explanation — any stored closed-period entry fails (release blocker) |
| e2e | medium | pytest | T-7 covers HR-2, CK-15: append-only journal + audit trail live | Mistaken May entry corrected in July via reversal; May unchanged; audit trail links both — any altered history fails (release blocker) |
| e2e | medium | pytest | T-8 covers CK-1: chart of accounts + opening-balance entries available | Opening balances via opening-balance entries → opening trial balance $0.00 — any non-zero opening TB fails (release blocker) |
| e2e | large | pytest | T-9 covers CK-6, CK-14: recurring templates + systemd-timer CLI in container | 3 cycles → 3 invoices; pause stops generation; injected failure flagged in one screen — a silent failure fails (phase-exit blocker) |
| flow | small | pytest | T-10 covers CK-9: vendor bills + AP aging report functions | $200 partial payment on $500 bill → $300 outstanding in AP aging — any mismatch fails (phase-exit blocker) |
| golden | medium | pytest | T-11 covers HR-9, CK-10: closed quarter + at-close report snapshots | Golden-file regeneration of a past quarter's reports; TB nets $0.00 — any drift from the snapshot fails (phase-exit blocker) |
| flow | medium | pytest | T-12 covers CK-11: CPA bundle export + Schedule C mapping | Bundle contains all four components; Schedule C summary reconciles to year P&L — any missing component or mismatch fails (phase-exit blocker) |
| e2e | large | pytest | T-13 covers HR-3, CK-12: full-cycle environment with external network blocked + accountant role | Full cycle succeeds with network blocked; accountant role read-only on every write — any network-attributable error or successful write fails (phase-exit blocker) |
| e2e | large | pytest | T-14 covers CK-13: nightly backup + restore-drill record | Restore from backup: books open, TB $0.00, report regenerates; results recorded — an unverified restore fails (phase-exit blocker) |
| unit | small | pytest | T-15 covers HR-10: hash-chained audit log | Audit-log tamper attempt is detected by chain verification — an undetected tamper fails (phase-exit blocker) |
| e2e | medium | pytest | T-16 covers CK-2: saved per-account import profile | Saved import profile reused; bank layout change handled by profile edit or manual-entry fallback — any data loss fails (fix before next release) |

#### CK-1: Cutover opening balances

- Given Wave-exported account balances as of the cutover date, when Keith posts opening balances via opening-balance entries, then the opening trial balance nets to $0.00 and every balance-sheet account matches Wave to the cent.
- Given the parallel-run month, when both systems are compared at month end, then the difference for every tracked category is $0.00 (G10) before Wave is demoted.

#### CK-2: Import profile persistence

- Given an account profile saved with column mapping and date format, when a new statement from the same bank is imported, then no re-mapping is requested and lines parse with correct dates and amounts.
- Given the bank changes its CSV layout (error flow), when the profile is updated or a manual journal entry is used, then bookkeeping continues without data loss.

#### CK-3: Review-before-post (incl. bank import mismatch)

- Given 40 imported lines of which 12 match open invoices, when Keith accepts the 12 and edits 5 categories then accepts, then exactly 17 postings exist and 23 lines remain pending/rejected with no postings (HR-5).
- Given a statement file whose content was already imported (renamed copy, error flow), when it is imported again, then the system reports "already imported", creates zero duplicates, and ledger totals are unchanged (HR-4).

#### CK-4: Reconciliation (incl. failed reconciliation)

- Given a statement balance of $4,213.75 and cleared lines of $4,200.00 (error flow), when Keith attempts completion, then it is refused and the $13.75 difference is displayed (HR-7).
- Given the missing $13.75 line imported and accepted, when the reconciliation is retried, then it completes and its cleared lines become locked against any altering posting.

#### CK-5: Invoice creation and PDF

- Given a customer and line items totaling $49, when the invoice is made official, then AR rises $49 and income rises $49 in one balanced entry (HR-1) and a send-ready PDF renders without any transmission (HR-3).
- Given ten invoices generated in a month, when listed, their numbers are sequential with no gaps or duplicates.

#### CK-6: Recurring tier generation

- Given a $49/mo template active from Mar 1, when Mar 1, Apr 1, May 1 pass, then exactly three $49 invoices exist with no manual entry.
- Given the template paused Apr 15, when May 1 arrives, then no May invoice is generated and April's history is untouched.
- Given an injected generation failure, when Keith opens the recurring view, then the failed template and affected customer are flagged within one screen (CK-14).

#### CK-7: Payment allocation

- Given a $49 invoice and a $49 bank deposit, when the payment is recorded against the invoice, then bank +49 / AR −49 post and the invoice flips to Paid in the same all-or-nothing action; an interrupted allocation leaves no partial state.

#### CK-8: Overpayment → credit → application (error flow)

- Given a customer with a $49 due invoice and no credit, when a $60 payment is recorded, then the invoice is Paid, $11 appears as customer credit (liability), the bank reflects $60, and the books balance (HR-8).
- Given that customer's next $49 invoice, when the $11 credit plus a $38 payment are applied, then the invoice is Paid with $0 credit remaining.

#### CK-9: Bills and AP aging

- Given a $500 vendor bill, when a $200 payment is recorded, then the bill shows $300 outstanding and appears at $300 in AP aging; after a further $300 payment it shows Paid.

#### CK-10: Report suite over past periods

- [golden] Given a closed quarter with report snapshots taken at close, when the trial balance is regenerated for that quarter, then it nets to $0.00 and matches the at-close snapshot (HR-9).
- [golden] Given the same closed quarter, when the P&L is regenerated in cash mode and in accrual mode, then each view equals its at-close snapshot.
- [golden] Given the same closed quarter, when the balance sheet is regenerated, then it matches the at-close snapshot with retained earnings derived from history.
- [golden] Given the same closed quarter, when the cash flow statement is regenerated, then it matches the at-close snapshot.
- [golden] Given the same closed quarter, when AR aging and AP aging are regenerated, then each matches its at-close snapshot.
- [golden] Given the same closed quarter, when the GL detail is regenerated, then every posted transaction in the quarter appears and account totals match the at-close snapshot.
- [golden] Given the same closed quarter, when a customer statement is regenerated, then its invoice and payment history matches the at-close snapshot.

#### CK-11: CPA bundle

- Given a completed fiscal year, when the CPA bundle is exported in one operation, then it contains the GL CSV (every posted transaction), report PDFs, a Schedule C summary, and 1099-NEC tracking, and the Schedule C totals reconcile to the year's P&L.
- Given three 1099-eligible vendors paid $450 / $620 / $1,200 with the default threshold, when the tracking list is generated, then exactly the two vendors ≥ $600 appear with ledger-matching totals.

#### CK-12: Role separation and sovereignty (error flow)

- Given the accountant role, when any write is attempted (post, import, edit, reconcile, close, configure), then every attempt is refused while all reports and exports remain available (CK-12).
- Given all external network access blocked, when a full cycle is executed (import → review → accept → post → invoice → payment → reconcile → report → export), then every step succeeds with no error attributable to network absence (HR-3).

#### CK-13: Restore drill

- Given last night's backup, when the monthly restore drill runs, then the restored copy opens, its trial balance nets to $0.00, a recent report regenerates, and the drill record shows the restored point-in-time and check results (CK-13).

#### CK-14: Recurring-generation failure visibility (error flow)

- [e2e] Given three active recurring templates, when the monthly generation cycle completes, then the administrator's single generation-results screen shows 3 generated and 0 failed.
- [e2e] Given one template's generation is made to fail mid-cycle, when the monthly cycle completes, then the same screen flags the failed template and names the affected cycle (the month's missing invoices are visible in one screen), while the other templates' invoices still generate.

#### CK-15: Reversal of a mistaken entry (error flow)

- Given a $250 expense misclassified in closed May and discovered in July, when corrected, then May's stored entries are unchanged, July contains a visible $250 reversal plus the corrected posting, and both reference each other in the audit trail (HR-2, HR-10).
- Given any posted entry, when edit or delete is attempted through any interface, then the operation is impossible and no path alters stored history (HR-2).

**Definition of Done:**

- [ ] All hard rules HR-1…HR-10 verified by automated tests (property tests for invariants; explicit cases T-1…T-16 in the matrix), including every error flow listed in User Scenarios
- [ ] All six money flows (invoice, bill, import+review, reconciliation, correction, close) pass end-to-end against a clean environment, with overpayment, failed-reconciliation, duplicate-import, and reversal scenarios demonstrated
- [ ] Import idempotency proven: same content under a different filename creates zero duplicates
- [ ] Every delivered phase (0–6) is independently usable, with the phase's scope operable from the operator documentation alone
- [ ] Sovereignty demonstrated: full-cycle test passes with external network blocked; no third-party service in the money path; accountant role enforced read-only by negative tests
- [ ] Reporting: golden-file tests pin the report suite for a closed period; trial balance nets to $0.00 for every period; CPA bundle components complete and reconciling
- [ ] Coverage gate ≥95% enforced on the domain core and reports; every checklist item HR-1…HR-10 and CK-1…CK-15 carries at least one passing automated test or named regular check
- [ ] Cutover rehearsal: opening balances load to a $0.00 trial balance and the parallel-run comparison procedure is executable
- [ ] Backup/restore drill automated and its verification record produced; 7-year retention and nightly backup configured on self-owned storage

## Architecture Overview

Synthesized 2026-09-02 (SDD Phase 3, scratchpad-first). **References** — Research (Phase 2a):
`.specs/analysis/research-report.md` (7 technology areas; conflict flags F-1…F-9; live-verified pins —
where a research pin conflicts with older spec text, the research pin wins, per the 2026-09-02 verification).
Codebase impact (Phase 2b): `.specs/analysis/analysis-codebase-impact.md` — §1 target repo tree (the component
model below mirrors it 1:1), §2 estate integration points, §3 risks, §4 key interfaces. Business analysis
(Phase 2c): `.specs/analysis/business-analysis.md` — goals G1–G10, requirements BR-1…BR-23, constraints C1–C9.
Stack pins & traps: `.claude/skills/sovereign-ledger-stack/SKILL.md` (psycopg 3.3.5, fastapi 0.141.1,
ofxtools 1.1.1, argon2-cffi 25.1.0, vendored htmx.org 2.0.10, charset-normalizer 3.5.1, hypothesis 6.167.1;
traps 1–12). Scratchpad: `.specs/scratchpad/6a1f23d8.md`.

### Solution Strategy

**Architecture Pattern: Hexagonal (ports & adapters) around a pure double-entry core, delivered as one
server-rendered monolith.** The domain core (`ledger/`, plus pure `reports/` and `tax/`) knows nothing of
HTTP, SQL, or the filesystem; delivery adapters (`app/` routes, `importers/`, `scripts/` CLIs) depend inward
and are the only code that touches FastAPI, psycopg, or the network namespace. This is not a stylistic
choice: hard rule 1 ("domain core never touches network or DB") *is* the hexagonal kernel, and it is what
makes the invariant strategy (T-1 property tests, HR-1/HR-2) executable — the `hypothesis`
`RuleBasedStateMachine` drives the pure core directly, with no HTTP or DB in the loop, while DB-level
triggers re-verify the same invariants at the storage boundary (defense in depth, not redundancy).
Alternative approaches generated and rejected in the scratchpad: SQLAlchemy/Alembic layered service (violates
the locked no-ORM/no-Alembic decision), CQRS read models (violates "nothing cached, regenerable identically",
BR-11), event-sourced SurrealDB (no deferred-constraint/SSI story — research F-7), TigerBeetle and
Beancount/Fava (rejected at approach selection, 0.08/0.07).

The single most consequential resolution: the task's earlier DB-driver wording ("asyncpg") is superseded by
the live-verified research pin — **psycopg 3.3.5 in sync mode with plain `def` endpoints** (FastAPI
threadpool), per research-report §2 and SKILL.md's pinned install block. Sync psycopg + threadpool is the
simplest correct posture for a LAN, two-user app and pairs directly with the serializable-retry wrapper;
`db/session.py` is the only place that knows this.

**Key Architectural Decisions** (each: choice — reasoning — trade-off; full alternatives in the scratchpad):

1. **D-1 — Hexagonal monolith, single deployable.** One FastAPI process + one Postgres container. Money
   systems fail at integration seams; the fewest seams that still isolates the domain wins. Trade-off: no
   independent scaling of UI vs ledger — irrelevant at single-entity volume.
2. **D-2 — PostgreSQL 16 (16.15) as the sole system of record.** Deferred constraints, SSI serializable
   isolation, trigger-enforced immutability, and MVCC-consistent `pg_dump` are the exact capabilities the
   money rules need (research §1); deliberate deviation from the estate's SurrealDB preference (F-7).
   Trade-off: one more runtime than a pure-file system; justified by G3 (0% out-of-balance ever stored).
3. **D-3 — Signed BIGINT cents, USD only.** `journal_lines.amount_cents`: + = debit, − = credit. Immune to
   float error, trivially property-testable; BIGINT not INT4 (research §1); never the `money` type, never
   float; importers parse → `Decimal` → validate 2dp → integer cents at the boundary (SKILL trap 8).
   Trade-off: display formatting lives in templates (accepted; single currency).
4. **D-4 — psycopg 3.3.5, sync, plain `def` endpoints** (research pin supersedes earlier asyncpg wording).
   Server-side binding (injection-immune), `dict_row`, transaction blocks; FastAPI dependency injection for
   the pool so tests override it. Trade-off: threadpool concurrency model — a non-issue at this scale.
5. **D-5 — Plain ordered SQL migrations** (`db/migrations/0001…0006`, applied in numeric order by
   `scripts/init_db.py`; dbmate binary optional as a runner — the contract is the ordered SQL files
   themselves). No Alembic, no SQLAlchemy anywhere in the money path. Trade-off: hand-written SQL needs
   review discipline — which is exactly the spec's "reviewed like code" rule (hard rule 2).
6. **D-6 — Per-entry balance trigger, DEFERRABLE INITIALLY DEFERRED** (F-3, SKILL trap 4 + pattern
   example). A plain row trigger rejects mid-transaction states while lines insert one-by-one; the deferred
   constraint trigger fires at COMMIT after all lines exist. Defense in depth: triggers **and**
   `REVOKE UPDATE, DELETE` on the four append-only tables from the app role (SKILL layout invariants).
   Trade-off: an unbalanced entry is only rejected at COMMIT — acceptable because the pure core already
   refuses to construct one (HR-1 holds on every path).
7. **D-7 — SERIALIZABLE scoped to money mutations only** (payment allocation, reconciliation close, period
   close, posting); reads stay READ COMMITTED. Every serializable block runs inside a bounded
   retry-with-backoff wrapper for SQLSTATE 40001 (research §1; SKILL trap 5). Trade-off: retry complexity at
   a handful of call sites in exchange for anomaly-proof all-or-nothing allocation (T-5).
8. **D-8 — Append-only history + reversing-entry corrections + hash-chained audit.** No UPDATE/DELETE path
   exists on `journal_entries`/`journal_lines`/`accounts`/`fiscal_periods` (triggers + revoked privileges);
   every correction is a new reversal referencing the original (HR-2, CK-15, BR-15); `audit_log` is
   hash-chained so tampering is detectable (HR-10, T-15). Trade-off: "fix a typo" costs a reversal pair —
   the price of trustworthy books.
9. **D-9 — Import idempotency by canonicalized content hash**, never raw bytes (SKILL trap 7): normalize
   newlines/whitespace/decimals, then hash whole file (batch-level, HR-4/T-2) and per line (dedupe across
   overlapping statements); OFX/QFX lines key on the bank's `FITID` via ofxtools 1.1.1 (never ofxparse —
   F-1); CSV per-account profiles are version-stamped so a bank layout change cannot silently re-map old
   imports (SKILL trap 12); cp1252/latin-1 sniffed with charset-normalizer. Trade-off: canonicalization
   code must be maintained per format — bounded to `importers/`.
10. **D-10 — Gapless invoice numbers via a locked counter row inside the posting transaction** (F-5; SKILL
    trap 6). Postgres sequences burn numbers on rollback, which would fail CK-5/BR-23. Trade-off: a small
    serialization point on invoice creation — inherent to gaplessness.
11. **D-11 — Server-rendered Jinja2 + vendored HTMX 2.0.10.** `htmx.min.js` committed to `app/static/`
    (HR-3 forbids CDN); `jinja2-fragments` 1.12.0 (sponsfreixes/jinja2-fragments) renders HTMX partials from the same templates as full
    pages (import-review queue, F-6); partials send `Cache-Control: no-store`, after-POST flows use
    `HX-Redirect`/`HX-Trigger`; `hx-boost` keeps the review queue usable without JS. Sessions: itsdangerous
    signed cookies (`SameSite=Strict`, `https_only`) **plus a per-session CSRF token in a custom header on
    every POST** — two roles share the browser, so SameSite alone is insufficient (SKILL trap 10).
    Trade-off: no rich client interactivity — none is needed (SPA rejected at approach level).
12. **D-12 — argon2-cffi 25.1.0 called directly** (never passlib — F-4), OWASP-floor Argon2id parameters
    (m=19456 KiB, t=2, p=1) with `check_needs_rehash()` on login; exactly two roles (admin,
    accountant-read) enforced in a FastAPI dependency on every mutating route, negatively tested (CK-12,
    BR-17). Trade-off: parameter tuning is manual without passlib's abstraction — fine for two users.
13. **D-13 — Scheduling = systemd user timers invoking CLIs in the app container.** Nightly
    `pg_dump -Fc` → `/media/keith/NVMe/backups/sovereign-ledger/` → rclone `[gdrive-backup]` (closes the
    estate's unscheduled-backup gap, analysis §3 R2); 1st-of-month recurring generation runs
    `scripts/recurring_generate.py` guarded by `pg_advisory_lock` (double-tick safe, CK-6/CK-14; research
    §1). No scheduler in the app process. Trade-off: results visibility must be persisted by the CLI —
    done via the generation-results record the recurring screen reads.
14. **D-14 — Rootless Podman quadlets, loopback-only ports 11240 (app) / 11241 (db)**, both verified free
    (analysis §2.3); house quadlet style per analysis §2.2 (`WantedBy=default.target`, `Restart=always`,
    explicit `ContainerName=`, pinned `postgres:16.15`, named `.volume`, `:Z` on SELinux bind mounts,
    `Type=notify` auto for `.container`); images pinned; optional nginx/Tailscale front door later without
    app changes. Trade-off: rootless can't bind <1024 — irrelevant, 11240/11241 chosen.
15. **D-15 — Option A record-only money path as an architectural boundary.** There is *no outbound adapter*
    in the design — no payment-processor, bank-connectivity, or email client exists to compromise; invoices
    and statements render as PDFs (WeasyPrint over the same Jinja2 templates, version pinned at build time
    per research §2) for manual sending. Full-cycle operation is verified with external network blocked
    (HR-3, T-13, BR-18). Trade-off: Keith performs the human hops a SaaS would automate — the point.

**Trade-offs accepted (summary)**: sync-driver simplicity over async headroom; deferred-trigger rejection
timing over per-row strictness; recompute-everything reporting (nothing cached, BR-11) over snapshot speed —
at single-entity volume all are cheap; human review gates latency in exchange for HR-5 correctness.

### Component Breakdown

Components honor the analysis §1 repo tree exactly (greenfield — every file is NEW; "reuses" therefore means
estate conventions and SKILL.md patterns, per the scratchpad reuse analysis). Clean-Architecture layer map:
L1 entities/domain = `ledger/` (types, engine, entries, accounts, periods, audit); L2 use cases =
`ledger/` domain services (customers, invoices, payments, vendors, bills, bank_accounts, reconciliation,
recurring), `reports/`, `tax/`; L3 adapters = `app/routes`, `importers/`, `scripts/`; L4 frameworks =
FastAPI/uvicorn/psycopg 3/Podman/systemd/Jinja2/HTMX. Dependencies point inward only.

| Component | Path | Responsibilities | Boundary | Reuses From |
|-----------|------|------------------|----------|-------------|
| Domain types & engine | `ledger/types.py`, `ledger/engine.py` | Money (int cents), JournalLine (+debit/−credit), JournalEntry; balance invariant Σ=0, atomic posting; pure dataclasses in/out | Zero I/O; no fastapi/psycopg/requests imports (CI grep gate) | SKILL pattern examples; estate Python 3.12/uv baseline |
| Journal use cases | `ledger/entries.py`, `ledger/accounts.py`, `ledger/periods.py`, `ledger/audit.py` | Draft→post lifecycle; CoA + tax-mapping subtypes; fiscal period open/close/lock; hash-chained audit append | Pure; callers persist | SKILL trap 4 trigger contract |
| AR/AP use cases | `ledger/customers.py`, `invoices.py`, `payments.py`, `vendors.py`, `bills.py`, `recurring.py` | Invoices post on creation; all-or-nothing payment allocation; overpayment→customer_credits liability; recurring template generation logic | Pure; no scheduling, no HTTP | BR-1…BR-7 semantics |
| Bank & reconciliation | `ledger/bank_accounts.py`, `ledger/reconciliation.py` | bank_accounts 1:1 ledger accounts; import_batches (content-hash idempotency); bank_lines; $0.00-only reconciliation close + line locking | Pure decision logic; I/O in adapters | analysis §4 importer protocol |
| Delivery app | `app/main.py`, `app/routes/*.py` (12), `app/templates/`, `app/static/` | Session auth + CSRF + role gate; HTMX screens (CoA, entries, import review, reconcile, AR, AP, reports, close); `/healthz`; PDF render endpoints | Only `app/` (and `scripts/`) touch the DB pool; no outbound calls | estate FastAPI+Jinja2 precedent (site-pulse); analysis §4 route table |
| Importers | `importers/base.py`, `csv_generic.py`, `ofx.py`, `profiles.py` | BankImporter protocol (`detect`/`parse` → `BankLine` drafts); versioned per-account profiles; charset sniffing; canonicalized hashing | Produce drafts ONLY — never post | ofxtools 1.1.1; charset-normalizer 3.5.1 |
| Reports | `reports/*.py` (8 modules) | Trial balance, balance sheet, income statement (cash/accrual), cash flow, AR/AP aging, GL detail, customer statements, CPA bundle assembly | Pure functions over posted lines; nothing cached; regenerable for any past period | T-11 golden-file rig |
| Tax | `tax/schedule_c.py`, `tax/form_1099.py` | Account subtype → Schedule C line mapping; 1099-NEC tracking w/ configurable threshold (default $600) | Pure mapping, no I/O | BR-7/BR-13 |
| Persistence | `db/session.py`, `db/migrations/0001…0006.sql`, `db/seed/chart_of_accounts.py` | psycopg pool factory (app-side only); ordered schema: core → AR → AP → bank → access → recurring; CoA seed | Migrations are plain SQL, numeric order; 4 append-only tables trigger-protected + privilege-revoked | SKILL trigger/retry patterns |
| Operations | `scripts/init_db.py`, `backup.sh`, `restore.sh`, `recurring_generate.py`, `cpa_export.py`, `wave_cutover_import.py`; `deploy/*.container|.volume|.timer`; `Containerfile` | Apply migrations + seed; nightly backup + rclone; restore drill; recurring CLI; CPA export; Wave cutover; quadlets + timers | CLIs only; no web framework | estate quadlet style (6 verified units); `deploy/sovereign-ledger.timer` |
| Tests | `tests/` (T-1…T-16) | Property (`hypothesis` `RuleBasedStateMachine` on the pure core, `deadline=None`), e2e vs scratch Postgres, golden files, flow tests; ≥95% cov gate on `ledger/`+`reports/` | Tests import the core directly (proves zero-I/O) | SKILL trap 11 |
| Config | `config/settings.py`, `config/logging.py` | pydantic-settings, env-driven; no secrets in repo | — | analysis §2.1 pre-receive hook |

**Interactions:**

```
            ┌────────────────────────── adapters ──────────────────────────┐
 Keith/CPA │ app/ (FastAPI+HTMX)      importers/      scripts/ (CLI+timers)│
 (LAN/TS)  └──────┬───────────────────────┬──────────────────┬──────────────┘
                  │  domain API (pure)    │ drafts only      │
                  ▼                       ▼                  ▼
            ┌──────────────────────────────────────────────────────────────┐
            │                    ledger/  (pure core)                       │
            │  engine · entries · accounts · periods · audit                │
            │  invoices · payments · bills · recurring · reconciliation     │
            └───────────────────────────┬────────────────────────────────┘
                                        │ persistence (caller's job)
                                        ▼
                     db/session.py ──► PostgreSQL 16 (127.0.0.1:11241)
                                        ▲
                    reports/ + tax/ ────┘ read posted rows via app layer
```

**Boundary rules (enforceable):** (1) `ledger/` and `reports/` contain no I/O imports — CI grep gate
(`fastapi|psycopg|asyncpg|requests|httpx` in either tree fails the build); (2) only `app/` and `scripts/`
construct DB connections; (3) `importers/` output is always drafts — the only posting paths are the pure
core behind explicit human-accept endpoints (HR-5); (4) no module named `utils`/`helpers`/`common`/`shared`
(domain-named modules only).

### Data Flow — Six Money Flows (each ends in a balanced journal entry)

1. **Client billing (invoices + payments).** Invoice draft → made official ⇒ ONE serializable transaction:
   {lock counter row → gapless invoice number (D-10) → insert invoice + lines → post JE
   Dr AR / Cr Income → audit append}; status Draft→Sent/Posted; Overdue derived from due date (BR-1).
   PDF renders from the same template for manual sending (D-14, BR-23). Payment ⇒ ONE serializable
   transaction {allocate across open invoices all-or-nothing → flip statuses → residual → customer_credits
   liability, never income (HR-8) → JE Dr Bank / Cr AR}. Invariants: HR-1, HR-2, HR-8; tests T-5.
2. **Recurring tiers.** `sovereign-ledger-recurring.timer` (1st of month) → `podman run` CLI in app
   container → `pg_advisory_lock` (D-13) → per active template, invoke flow-1 posting → results recorded;
   failures flagged with template + affected customer on one screen (CK-6, CK-14, BR-4); price changes hit
   future cycles only; pause stops generation without touching history (BR-3). Test T-9.
3. **AP bills.** Vendor + bill with lines ⇒ JE Dr Expense / Cr AP at entry; partial payments
   Dr AP / Cr Bank leave the remainder visible in AP aging (BR-6; T-10); recurring bill templates reuse the
   flow-2 mechanics; void = reversal while unpaid (BR-6).
4. **Bank import / reconciliation.** Upload → charset-normalizer sniffs cp1252/latin-1 → ofxtools 1.1.1
   (FITID) or CSV via version-stamped profile → canonicalize → hash file + lines → `import_batches`
   dedupe: identical content re-imported = "already imported", zero duplicates under any filename (HR-4,
   T-2) → suggestions (auto-match to open invoice/bill, or learned category) land as drafts in the review
   queue → human accepts / edits / rejects; **nothing auto-posts** (HR-5, T-3, BR-9) → accept posts via
   D-7 transaction. Reconciliation: statement balance + cleared lines → completion refused until difference
   is exactly $0.00 → completing locks cleared lines (HR-7, T-4, BR-10).
5. **Reporting.** Pure functions (`reports/`, `tax/`) over posted lines as of any date; nothing cached
   (BR-11): trial balance always nets $0.00 (HR-9), P&L cash/accrual toggle (books accrual, cash derived),
   balance sheet with retained earnings derived, cash flow, AR/AP aging, GL detail, customer statements.
   Golden-file tests pin a closed quarter against its at-close snapshots (T-11); CPA bundle = one export:
   GL CSV + report PDFs + Schedule C summary + 1099-NEC tracking, Schedule C reconciling to year P&L
   (T-12, BR-13).
6. **Period close.** Admin-only, in fiscal order, refused while bank activity is unreconciled (BR-14) ⇒
   close transaction flips `fiscal_periods` to closed (trigger refuses later postings — HR-6, T-6,
   BR-20) → report snapshots frozen → CPA-bundle exportability confirmed. Late corrections never touch the
   closed period: reversing entry + corrected posting in the open period, cross-referenced in the audit
   trail (HR-2, CK-15, T-7, BR-15).

### Expected Changes

All files are NEW (greenfield — analysis §1). Tree with phase mapping; **P0–P6** per the analysis's
Tree ↔ Spec Phase Mapping and the task's build phases:

```
sovereign-ledger/                        # repo: gitea.netintegrate.net/soverigndataadmin/sovereign-ledger
├── pyproject.toml / uv.lock / .python-version   # uv; Python 3.12          [P0]
├── config/settings.py, logging.py               # env-driven config        [P0]
├── ledger/                                      # PURE core                [P0 core; P3/P4 domain modules]
│   ├── types.py, engine.py, entries.py, accounts.py, periods.py, audit.py      [P0]
│   ├── customers.py, invoices.py, payments.py, recurring.py                    [P3]
│   └── vendors.py, bills.py, bank_accounts.py, reconciliation.py               [P2/P4]
├── app/                                         # FastAPI + Jinja2/HTMX    [P1+]
│   ├── main.py, routes/{accounts,entries}.py, templates/                   [P1]
│   ├── routes/{import_review,bank,reconcile}.py                            [P2]
│   ├── routes/{customers,invoices,payments}.py                             [P3]
│   ├── routes/vendors.py                                                   [P4]
│   ├── routes/{reports,close}.py                                           [P5]
│   └── routes/auth.py; templates/+static/ (vendored htmx.min.js)           [P1–P6]
├── importers/ (base, csv_generic, ofx, profiles)                           [P2]
├── reports/ (trial_balance [P1]; full suite [P5, built throughout])
├── tax/ (schedule_c, form_1099)                                            [P5]
├── db/session.py; db/seed/chart_of_accounts.py                             [P0]
├── db/migrations/0001_core [P0] · 0004_bank [P2] · 0002_ar+0006_recurring [P3]
│                 · 0003_ap [P4] · 0005_access [P6]
├── scripts/ (init_db [P0]; wave_cutover_import [P1]; recurring_generate [P3];
│            cpa_export [P5]; backup.sh/restore.sh [P6, shipped early])
├── deploy/ (app+db quadlets, volume [P0]; backup timer [P0→P6]; recurring timer [P3])
├── tests/ (P0: conftest.py, test_engine.py, test_accounts.py, test_periods.py → T-1…T-16 per matrix)   [all]
└── Containerfile                                                           [P0]
```

Phase order P0→P6 is strictly additive and each phase is independently usable (C9): P0 core+schema+triggers+
property tests → P1 books exist (CoA, manual entries, TB, Wave opening balances) → P2 daily driver (import,
review/accept, reconciliation) → P3 AR (+recurring+timer) → P4 AP → P5 tax-ready (report suite, Schedule C,
CPA bundle, close) → P6 roles/audit-viewer/backup-drill automation. Later phases reuse earlier ones: P2+
reuse the P0 posting engine and D-7 retry wrapper; P3/P4 reuse the P2 suggestion queue; P5 snapshots reuse
the report suite built throughout.

## Implementation Process

*Decomposed 2026-09-02 by the tech-lead agent (scratchpad `88f99e33`). BASELINE_TIER assessment: the overall
task is **Complex** (breadth: ~15 modules across ledger core, DB, web, importers, reports, tax, deploy;
critical domain: data integrity, auth, payroll, irreversible migrations) → run baseline `opus`, with
per-step tiers below assigned by the Selection Rules (mechanical/adapter steps may drop to `sonnet`;
no step was hedged upward). Reviewer per phase is never below that phase's highest implementation tier.*

### Parallelization Overview

```
Phase 1 ── Foundation (books exist)
  [1] Scaffold + Money Engine ─┬─> [2] Schema+Triggers ──┐
                               └─> [3] Domain Services ──┴─> [4] Auth/CSRF ──> [5] App Shell ═ PHASE GATE 1 (T-8)
Phase 2 ── Daily Driver (import & review)
  [5] ──> [6] Importers ──> [7] Review Queue + Reconcile ═ PHASE GATE 2 (T-2/T-3/T-4)
Phase 3 ── AR & Recurring
  [7] ──> { [8] AR Domain ──> [9] AR Web } ∥ [10] Scheduler/Backup ∥ [12] Payroll ═ PHASE GATE 3 (T-5/T-11/T-14)
Phase 4 ── AP & Money UI Completion
  [9] ──> [11] AP Domain ──> [13] AP Web ──> [14] Reports ──> [15] Tax/Close ──> [16] E2E Suite ═ PHASE GATE 4
                                                     (∥ [17] Deploy/Runbook runs beside 15–16)
Phase 5 ── DoD Gate
  [16] + [17] ──> [18] DoD Gate ═ PHASE GATE 5 (sign-off)
```

| Step | Phase | Model | Agent | Depends on | Parallel with | Sub-Task File |
|------|-------|-------|-------|------------|---------------|---------------|
| 1 | 1 | opus | sdd:developer | — | Step 2 | 01-scaffold-money-engine.md |
| 2 | 1 | opus | sdd:developer | — | Step 1 | 02-schema-triggers-persistence.md |
| 3 | 1 | opus | sdd:developer | Steps 1, 2 | — | 03-ledger-domain-services.md |
| 4 | 1 | opus | sdd:developer | Step 3 | — | 04-auth-sessions-role-gate.md |
|  5 | 1 | opus | sdd:developer | Step 4 | — | 05-books-exist-app-shell.md |
|  6 | 2 | opus | sdd:developer | Steps 3, 5 | Steps 8, 12 | 06-bank-importers-idempotency.md |
|  7 | 2 | opus | sdd:developer | Step 6 | Steps 9, 11 | 07-review-queue-reconciliation.md |
|  8 | 3 | opus | sdd:developer | Steps 2, 3 | Steps 6, 12 | 08-ar-domain-services.md |
|  9 | 3 | opus | sdd:developer | Steps 4, 7, 8 | Step 11 | 09-ar-web-routes.md |
| 10 | 3 | sonnet | sdd:developer | Steps 4, 5, 8 | Steps 9, 11 | 10-scheduler-backup-restore.md |
| 11 | 3 | opus | sdd:developer | Steps 3, 8 | Steps 9, 10 | 11-ap-domain-services.md |
| 12 | 3 | opus | sdd:developer | Steps 3, 5, 8 | Steps 9, 10, 11 | 12-payroll-contractor-records.md |
| 13 | 4 | sonnet | sdd:developer | Steps 7, 11 | Step 15 | 13-ap-web-import-review.md |
| 14 | 4 | opus | sdd:developer | Steps 5, 13 | Step 15 | 14-reports-dashboard-audit.md |
| 15 | 4 | opus | sdd:developer | Steps 12, 14 | Step 17 | 15-tax-cpa-exports-close.md |
| 16 | 4 | opus | sdd:qa-engineer | Steps 6, 7, 9, 12, 13, 14, 15 | Step 17 | 16-e2e-moneyflows-hardrule-gates.md |
| 17 | 4 | sonnet | sdd:developer | Steps 5, 10 | Steps 15, 16 | 17-deploy-hardening-runbook.md |
| 18 | 5 | opus | sdd:qa-engineer | Steps 16, 17 | — | 18-dod-gate-coverage-boundary.md |

*Peak parallel width: 3 (target ~3 met). All dependencies resolve to same-or-earlier phases.
Step 8 legitimately starts in the Phase 2 execution window (its deps finish with Phase 2's start)
but its phase gate remains Phase 3; Step 12 similarly runs in the Phase 3 window.*

### Phase Overview

#### Phase 1 — Foundation: Books Exist
Steps: 1, 2, 3, 4, 5
Reviewer model: opus
Acceptance criteria that should be fulfilled:
- Every journal entry balances exactly (debits = credits) and unbalanced entries are never stored on any posting path (HR-1); recorded entries are immutable with corrections only via reversing entries (HR-2).
- Zero outbound calls — the app functions fully with external network blocked (HR-3); accountant role is refused on every write while reports stay readable (CK-12).
- Books-exist flow: create book, Wave cutover CSV yields correct opening balances (CK-1).
Checklist items:
- [ ] HR-1/HR-2 property tests green on the pure ledger core (T-1)
- [ ] Accountant-role write refusal verified on routes built so far (CK-12)
- [ ] Books-exist e2e: create book → Wave CSV opening balances → app shell served on 11240 (CK-1)
Rubrics: Ledger & Posting Correctness, Sovereignty & Access Compliance

#### Phase 2 — Daily Driver: Import & Review
Steps: 6, 7
Reviewer model: opus
Acceptance criteria that should be fulfilled:
- Import is idempotent by file content — same statement under any filename creates zero duplicates (HR-4); no imported line posts without explicit human accept (HR-5); reconciliation completes only at exactly $0.00 and locks cleared lines (HR-7).
Checklist items:
- [ ] Renamed duplicate statement re-imported → "already imported", zero duplicates (HR-4, T-2)
- [ ] 40-line batch → 12 suggested + 5 edited accepts = exactly 17 postings, 23 pending (HR-5, T-3)
- [ ] $13.75 gap refuses completion and displays the difference (HR-7, T-4)
Rubrics: Money-Flow Completeness, Ledger & Posting Correctness

#### Phase 3 — AR & Recurring
Steps: 8, 9, 10, 11, 12
Reviewer model: opus
Acceptance criteria that should be fulfilled:
- Overpayment is recorded as customer credit (liability), never income (HR-8); invoice officialization is one balanced entry (HR-1); trial balance nets $0.00 regenerable at any later date (HR-9); payroll is record-only per the Description's Option A.
Checklist items:
- [ ] $60 payment on $49 invoice → Paid + $11 customer credit, books balance (HR-8, T-5)
- [ ] AP domain: vendors, bills, bill payments with partial payments in AP aging; check register (CK-9)
- [ ] Monthly recurring-generation review: generated invoices = active templates (CK-14)
Rubrics: Money-Flow Completeness, Reporting & Tax-Export Fidelity

#### Phase 4 — AP & Money UI Completion
Steps: 13, 14, 15, 16, 17
Reviewer model: opus
Acceptance criteria that should be fulfilled:
- P&L cash/accrual, balance sheet, cash flow with drill-down for any past period (CK-10); posting into a closed or locked period refused (HR-6); audit log append-only and tamper-evident (HR-10); E2E hard-rule gates pass with network blocked (HR-3); nightly backup on self-owned storage plus monthly restore drill verified (CK-13).
Checklist items:
- [ ] Closed-quarter golden reports match at-close snapshots; TB nets $0.00 (HR-9, T-11)
- [ ] Full cycle succeeds with network blocked; accountant read-only on every write (HR-3, CK-12, T-13)
- [ ] Audit-log tamper attempt detected by hash-chain verification (HR-10, T-15)
- [ ] Restore drill: restored copy opens, TB nets $0.00, recent report regenerates (CK-13)
Rubrics: Reporting & Tax-Export Fidelity, Test Rigor & Invariant Coverage

#### Phase 5 — DoD Gate
Steps: 18
Reviewer model: opus
Acceptance criteria that should be fulfilled:
- All hard rules HR-1…HR-10 verified by automated tests (T-1…T-16), including every error flow; coverage gate ≥95% on the domain core and reports; every checklist item HR-1…HR-10 and CK-1…CK-15 carries a passing automated test or named regular check.
Checklist items:
- [ ] All HR-1…HR-10 covered by automated tests including every error flow
- [ ] Coverage gate ≥95% enforced; HR-1…HR-10 and CK-1…CK-15 each covered
- [ ] Evidence report cites real commands and their results
Rubrics: Test Rigor & Invariant Coverage, Phased Usability & Documentation