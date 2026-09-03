# Sovereign Ledger — LinkedIn Article

## Why I Built a Zero-Trust Accounting System for Defense Contractors

*By Keith Ransom, CEO & Principal Engineer, NetIntegrate Systems LLC*

---

As a service-disabled veteran and defense contractor, I've seen firsthand how our industry handles financial data. And it terrifies me.

Most defense contractors — from small SDVOSBs to large primes — run their books on QuickBooks Online, Xero, or Wave. These are fine platforms for small businesses. But for companies handling CUI, ITAR-regarded data, and DCAA-audited cost records, they introduce unacceptable risks:

**Your financial data sits on someone else's cloud.** Intuit employees can access it. Data may reside in Canadian data centers. And any admin with a login can edit or delete posted entries — destroying the audit trail that DCAA requires.

**The security model is proprietary and opaque.** You can't audit their authentication system. You can't verify their password hashing standards. You can't inspect their access logs.

**The costs scale with entities.** A multi-entity contractor running QuickBooks Online Advanced pays $200/month per entity. Five entities = $12,000/year — just for the privilege of having your data on someone else's server.

---

## A Different Approach

I built Sovereign Ledger to solve this problem. It's a complete double-entry accounting system that runs entirely on your own infrastructure. No cloud. No third-party access. No subscription spiral.

### Military-Grade Security

The security stack is built to OWASP standards:

- **Argon2id password hashing** at OWASP minimum configuration (m=19456, t=2, p=1). Each hash verification consumes 19 MB of memory — making GPU cracking cost-prohibitive (>$20,000/hour). Cloud brute-force attacks would cost $150+ for a single 6-month attempt.

- **Cryptographically signed cookies** using itsdangerous with HMAC-SHA256. SameSite=Strict prevents CSRF. Secure flag enforces HTTPS-only transport.

- **Per-session CSRF tokens** required via X-CSRF-Token header on every mutation. Tokens rotate on authentication events.

- **Role-based access control** with admin/accountant separation enforced at the dependency injection level — not just at the route level where it can be bypassed.

### Immutable by Design

This is the feature that cloud platforms can't match: **posted entries cannot be modified or deleted**.

Sovereign Ledger uses PostgreSQL triggers to enforce immutability at the database level. Once a journal entry is posted, it's permanent. Every transaction is:
- Timestamped with microsecond precision
- Attributed to the user who posted it
- Linked to an immutable journal sequence
- Protected by a trigger that rejects UPDATE and DELETE operations

No admin can "fix" an entry by deleting it. Corrections require reversing entries — exactly what DCAA auditors want to see.

### 451 Tests, 98% Core Coverage

I didn't just build this system — I proved it works. Sovereign Ledger has 451 automated tests covering:
- Money engine (integer cents, no floating-point errors)
- Double-entry balance enforcement
- Authentication and authorization flows
- CSRF token validation
- Period locking and immutability
- Bank import idempotency (hash-based deduplication)
- E2E workflows (login → post entry → trial balance → immutability check)

The core ledger module has 98% code coverage. Every line is exercised.

---

## The Feature Set

Sovereign Ledger isn't a prototype. It's a complete accounting platform:

- **Core Ledger**: Chart of accounts, journal entries, trial balance, fiscal period management
- **Accounts Receivable**: Customer management, invoicing with line items and tax, payment allocation, aging reports, customer portal
- **Accounts Payable**: Vendor management, bill entry, payment processing, 1099 preparation data
- **Banking**: OFX import with hash-based deduplication, CSV generic importer, reconciliation workflow
- **Tax Management**: Rate management with jurisdictions, invoice tax calculations, optimization recommendations (S-corp, Section 179, QBI), tax projections with scenario modeling
- **Capital Assets**: Depreciation schedules, Section 179 expense election, asset disposal with gain/loss
- **Recurring Transactions**: Template-based automated generation

---

## Why This Matters for Defense Contractors

If you're a government contractor, your financial system is a compliance tool, not just a bookkeeping tool. DCAA auditors don't just want to see your numbers — they want to see how those numbers were recorded, who recorded them, and whether they can be trusted.

Sovereign Ledger answers all three questions:
1. **How**: Double-entry with strict balance enforcement and integer cents
2. **Who**: Every entry attributed to a named user with timestamp
3. **Trust**: PostgreSQL trigger-enforced immutability — entries cannot be altered

And it does this on infrastructure you control. No cloud egress. No third-party access. No data leaving your network.

---

## The Business Case

| Factor | QuickBooks Online Advanced | Sovereign Ledger Defense Pro |
|---|---|---|
| Monthly cost (3 entities) | $600/mo ($200 × 3) | $150/mo (3 included) |
| Annual savings | — | $5,400/yr |
| Data sovereignty | ✗ (Intuit cloud) | ✓ (your infrastructure) |
| Immutability | ✗ (admin can edit) | ✓ (trigger-enforced) |
| CUI compatibility | ✗ (requires DCMA waiver) | ✓ (NIST 800-171 aligned) |
| Source code access | ✗ | ✓ (full audit) |

A 3-entity defense contractor saves $5,400/year on subscription costs alone, while gaining immutable audit trails, military-grade authentication, and complete data sovereignty.

---

## Built by an SDVOSB, for Government Contractors

NetIntegrate Systems LLC is a Service-Disabled Veteran-Owned Small Business (SDVOSB, CAGE 8V9X2, UEI Z9N3M4K7L8V1). We understand defense contracting because we are defense contractors.

Sovereign Ledger is deployed on our own sovereign infrastructure at app.netintegrate.net — the same infrastructure we use for our own accounting. We eat our own dog food.

**Pricing starts at $50/month for a single entity.** Implementation takes 1–2 days including Wave CSV cutover and Podman deployment.

I'll be presenting a live demo at AFTC Industry Days on September 17. If you're attending, I'd love to show you what zero-trust accounting looks like.

**Contact:** keith@outsetrealestate.com | 470-301-3653 | app.netintegrate.net

---

*Keith Ransom is the CEO & Principal Engineer of NetIntegrate Systems LLC, a SDVOSB providing zero-trust infrastructure solutions for defense contractors. He has 20+ years in network engineering, security architecture, and software development.*