# Scratchpad — Business Analyst, Stage 1 (plan-task)
Project: Sovereign Ledger · Date: 2026-09-02 · ID: fbbbba0b

## Inputs read
- Persona: business-analyst.md (adopted: perfectionist BA, chain-of-thought, no implementation details, max 3 clarification markers, no human review in criteria, testable/measurable requirements only)
- Task spec: .specs/tasks/todo/build-sovereign-ledger.feature.md (Initial User Prompt, locked decisions, Option A, architecture summary, 15-table model, money flows, reports, phases 0–6, cutover, v1 exclusions)
- Judge methodology: judge.md (evaluator of the final artifact; used to self-grade before delivery)
- CLAUDE.md / constitution.md / README.md: NOT present in repo (greenfield; verified via ls)
- .specs/reports/ EMPTY → research-report.md not yet produced by parallel researcher; cross-reference skipped (permitted, never block). Noted in final doc.

## Stage 1 — Let's think step by step: root problem (needs vs wants)
1. User prompt says: replace Wave ("instead of paying for one"), needs to know what an accounting system that handles money requires.
2. NEED (root problem): trustworthy, permanent, tax-ready books for a single-member LLC (Outset Solutions LLC) with four revenue streams (Privacy Dawg $49/mo subs, Credit Dawg, HaaS leases, consulting) — owned outright, no recurring SaaS cost, no third party in the financial-data path, consumable by an outside CPA once a year.
3. WANT (chosen solution, locked): custom self-hosted double-entry system. Analysis treats solution as fixed; defines WHAT/WHY, never HOW (no Postgres/FastAPI/etc. in my requirements).
4. Wave replacement is also a RISK WINDOW: cutover must not corrupt history → parallel run + reconciliation to $0 (spec already mandates; I elevate to goal metric).

## Stage 2 — Let's think step by step: goals & metrics
Drafted measurable, technology-agnostic goals G1–G10 (cost=$0/mo; data ownership=zero third-party flows; balanced books=TB nets $0 + fail-closed; currency of books ≤5 business days; recurring drafts on the 1st 100%; close ≤3 business days; CPA bundle by Feb 15 with ≤2 follow-ups; duplicate import rate 0%; backup/restore drill monthly with RPO ≤24h; cutover parallel month difference $0.00).
Check: each metric observable without knowing implementation? Yes. Avoided "fast", "reliable" adjectives.

## Stage 3 — Let's think step by step: users
Keith = admin/sole bookkeeper (non-accountant; system must guard him with balance enforcement and simple flows). Outside CPA = read-only + export download; no posting/config. Two roles max per spec (users table: admin + accountant-read). Future successor served by plain exports + 7-year retention (no lock-in). Documented.

## Stage 4 — Let's think step by step: functional scope (business view)
Covered the six mandated areas (AR incl. recurring $49 tiers; AP; bank import + reconciliation; reporting; tax-prep export; period close) plus supporting scope the spec emphasizes: ledger foundation/CoA/opening balances, corrections & audit, data lifecycle (backup/retention/attachments). Every area described as business outcomes, not mechanisms (e.g., "payments post all-or-nothing with invoice status" rather than "serializable transactions").

## Stage 5 — Let's think step by step: non-goals
Explicit per spec: payment processing (Option A), payroll, multi-currency, inventory, sales-tax filing automation, automated filing, outbound email/bank-API sync (derived from Option A "zero external dependencies in money path" — labeled as derived, not as a quoted exclusion).
Implicit (my defaults, labeled as such): budgeting/forecasting, estimates/quotes, late fees/dunning, time tracking, public exposure/mobile, >2 roles, class tracking, multi-entity (explicit too). This avoids ambiguous scope = scope creep.

## Stage 6 — Let's think step by step: risks/assumptions/constraints
10 risks with impact/likelihood/mitigation (posting defects, parser drift, key-person, cutover error, data loss, unauthorized access, tax misclassification, unnoticed late payers, scope creep, silent recurring-generation failure — added an exception-view requirement BR-4 from this risk).
Assumptions A1–A8 flagged where business-level unverified (cash-basis Schedule C default, bank downloads available, no sales-tax obligation → marker Q3).
Constraints C1–C8 capture sovereign/self-hosted, no-cloud-SaaS money path, single USD entity, append-only, 7-yr retention, fiscal-boundary go-live + parallel month, private-network-only, phased delivery.

## Stage 7 — Let's think step by step: BRs for under-specified items
Hunted gaps in the spec from a business standpoint (not restating what spec fixes):
- Invoice state model & overdue semantics → BR-1
- Payment allocation/overpayment→credit application/refunds semantics → BR-2 (G/W/T example $49 vs $60)
- Recurring tier definition (cadence, proration default, manual send) → BR-3; silent-miss visibility → BR-4
- AR visibility/statement contents → BR-5
- Vendor/bill lifecycle → BR-6
- 1099-NEC threshold mechanics (configurable, default $600, eligible flag, list-only) → BR-7
- Import profile persistence + idempotency guarantee → BR-8; review/accept/reject semantics → BR-9
- Reconciliation cadence/order + close-with-difference rejection → BR-10 (G/W/T)
- Report historical availability + TB-zero invariant for any period → BR-11
- Basis & Schedule C mapping expectations → BR-12; CPA bundle completeness → BR-13
- Close rules (admin-only, in-order, immutable snapshot, no un-close) → BR-14
- Corrections/audit expectations → BR-15 (renumbered below)
- Backup/restore drill verification criteria → BR-17
- Cutover depth → BR-18 (ties to marker Q1)
- Fiscal calendar & posting-into-open-period rule → BR-19
- Revenue-stream separation in CoA + subscription-count derivability → BR-20
- Delivery recording without transmission → BR-21
- Access/sovereignty verification (works with external network blocked; private network only) → BR-22/BR-23
Final numbering BR-1..BR-23 (audit=BR-16, roles=BR-15). Each has a testable acceptance criterion; complex ones in Given/When/Then. Zero implementation technologies named.

## Clarification markers (exactly 3, with defaults)
Q1 Wave history depth (default: opening balances + current-year YTD)
Q2 HaaS lease recognition & hardware cost treatment (default: monthly invoices; purchases expensed unless CPA capitalizes → manual journals)
Q3 Sales tax on invoices (default: none in v1)

## Error scenarios considered
Unbalanced posting rejected (G3); duplicate import blocked (G8/BR-8); overpayment→credit (BR-2); posting into closed period rejected (BR-19); reconciliation ≠ $0 blocks close (BR-10); restore drill integrity check (BR-17); missed recurring generation surfaced (BR-4); parser format change → manual journal fallback (R2).

## Self-critique loop (5 verification questions)
1. Are all requested sections present (problem, goals/metrics, users, scope, non-goals, risks/assumptions/constraints, BRs)? → Yes, verified against task instructions.
2. Is every BR testable and implementation-agnostic? → Reviewed each; no framework/DB/language named; each criterion observable.
3. Does anything hallucinate beyond the spec? → Defaults are labeled as assumptions/markers; 1099 threshold explicitly configurable; no invented dates (go-live rule only, date = Keith's decision).
4. Is scope boundary unambiguous (explicit vs implicit non-goals separated)? → Yes, two lists with derivation labels.
5. Standalone & complete without researcher report? → Yes; absence of research-report.md disclosed in doc header.
Adjustments: merged refund semantics into BR-2/BR-14 rather than a separate vague BR; added BR-4 exception visibility from risk R10; softened idle-timeout to configurable default.

## Verdict before delivery
All persona checklist boxes satisfiable: scratchpad ✓, step-by-step per stage ✓, task read ✓, WHAT/WHY ✓, boundaries ✓, ≥3 criteria (23 BRs) ✓, G/W/T for complex ✓, error scenarios ✓, no implementation detail in requirements ✓, DoD for doc ✓, self-critique ✓, no human-review criteria ✓, ≤3 markers ✓.

## Outcome (final, 2026-09-02)
- business-analysis.md WRITTEN (284 lines, verified by read-back): problem stmt; G1–G10; users (admin/read-only CPA); scope §4.1–4.8; non-goals §5 explicit+implicit; §6 R1–R10/A1–A8/C1–C9; BR-1…BR-23; Q1–Q3 markers with defaults; DoD all [x].
- Research report absent → disclosed in doc header, non-blocking (per task rules).
- Draft task file edited in place per user's mid-turn steering: Description, Scope Included/Excluded, User Scenarios, Acceptance Criteria (HR-1…10, CK-1…15), regular checks, rubric, test matrix T-1…T-16, DoD. Verified by full read-back of all 366 lines.