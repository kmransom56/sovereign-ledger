# Sovereign Ledger — Marketing Copy Templates

## LinkedIn Headlines (3 variants)

### Variant 1: Technical
"Built a zero-trust accounting system for defense contractors with 451 automated tests and military-grade Argon2id auth. Sovereign Ledger: self-hosted, immutable, audit-ready. #DefenseTech #ZeroTrust #GovCon"

### Variant 2: Business
"Defense contractors shouldn't trust Intuit with their financial data. Sovereign Ledger: self-hosted double-entry accounting with trigger-enforced immutability and DCAA-compliant audit trails. 98% test coverage. #GovCon #DCAA #Accounting"

### Variant 3: Founder
"SDVOSB-built accounting platform running on sovereign infrastructure. No cloud egress, no third-party data access, no SaaS subscription spiral. Sovereign Ledger is production-ready with 451 tests. Demo at AFTC Industry Days Sep 17. #SDVOSB #SovereignTech"

---

## Cold Email — Defense Contractor CFO

**Subject:** Sovereign Accounting System — Self-Hosted, DCAA-Ready

Dear [Name],

As a defense contractor, your financial records contain some of your most sensitive data. Yet most contractors store them on Intuit's cloud — accessible to third-party employees, subject to cross-border data residency, and modifiable by any admin with a login.

Sovereign Ledger is different. It's a complete double-entry accounting system that runs on your own infrastructure:

- **Immutable by design**: PostgreSQL triggers prevent modification or deletion of posted entries
- **Military-grade auth**: Argon2id password hashing at OWASP minimum strength (19 MB memory cost per verification)
- **Zero cloud egress**: All processing occurs on your servers — no data leaves your network
- **DCAA-aligned**: Every transaction timestamped, user-attributed, and trigger-guarded
- **451 automated tests**: 98% coverage on core ledger logic

Pricing starts at $50/month for a single entity (vs. $200/month for QuickBooks Online Advanced). Implementation takes 1–2 days including Wave CSV cutover.

I'd welcome 15 minutes to show you a live demo. We're presenting at AFTC Industry Days on September 17.

Best regards,
Keith Ransom
CEO & Principal Engineer, NetIntegrate Systems LLC
SDVOSB | CAGE 8V9X2 | keith@outsetrealestate.com | 470-301-3653

---

## Cold Email — IT Security Director

**Subject:** Zero-Trust Financial System for Your On-Prem Infrastructure

Dear [Name],

Your defense contractor clients need accounting systems that don't violate zero-trust principles. Every QuickBooks login, every Xero API call, every Wave export sends financial data through a third party's infrastructure.

Sovereign Ledger is a self-hosted alternative:

**Security stack:**
- Argon2id (m=19456, t=2, p=1) — OWASP minimum, GPU cracking cost >$20K/hr
- itsdangerous HMAC-SHA256 signed cookies with SameSite=Strict
- Per-session CSRF tokens via X-CSRF-Token header
- Role-based access (admin/accountant) enforced at DI level
- Podman rootless containers — no daemon, no privileged access

**Deployment:**
- Podman quadlets on any Linux server (4 GB RAM minimum)
- PostgreSQL 16 with trigger-enforced immutability
- No cloud dependencies, no external API calls
- Full source code access for security review

I'd be happy to walk you through the architecture and security model. We have 451 automated tests validating every authentication and authorization path.

Regards,
Keith Ransom
NetIntegrate Systems LLC — SDVOSB, CAGE 8V9X2
keith@outsetrealestate.com | 470-301-3653

---

## Landing Page Copy

### Headline
**Sovereign Ledger — Zero-Trust Accounting for Defense Contractors**

### Subheadline
Self-hosted double-entry accounting with military-grade security, immutable audit trails, and zero cloud egress. Built by an SDVOSB for government contractors.

### Hero Stats
- **451** Automated Tests
- **98%** Core Code Coverage
- **0** Cloud Egress Points
- **$50/mo** Starting Price

### Why Sovereign Ledger?
Your financial data is too sensitive for someone else's cloud. Sovereign Ledger runs entirely on your infrastructure — no third-party access, no cross-border data residency, no subscription spiral.

### Key Features
- **Double-Entry Engine**: Strict balance enforcement, integer cents (no float errors)
- **AR/AP**: Customer invoices, vendor bills, payment allocation, aging reports
- **Banking**: OFX import with hash-based deduplication, reconciliation workflow
- **Tax**: Rate management, invoice tax calculation, optimization recommendations
- **Audit Trail**: Immutable posted entries, user-attributed, trigger-guarded
- **Role-Based Access**: Admin vs. accountant separation, boundary-enforced

### Security Highlights
- Argon2id at OWASP minimum (19 MB memory cost, GPU cracking >$20K/hr)
- itsdangerous signed cookies (HMAC-SHA256, SameSite=Strict)
- Per-session CSRF tokens with header validation
- PostgreSQL trigger-enforced immutability
- Podman rootless container isolation

### Pricing
| Tier | Price | Best For |
|---|---|---|
| Sovereign Starter | $50/mo | Single entity, 2 users, core ledger |
| Defense Pro | $150/mo | 3 entities, 5 users, AR/AP + tax |
| Enterprise | Custom | Multi-entity, custom compliance, unlimited |

### CTA
Schedule a 15-minute live demo. See the system running on sovereign infrastructure at app.netintegrate.net.

---

## Twitter/X Thread (5 posts)

### Post 1
Most defense contractors use QuickBooks to manage their finances.

But QuickBooks stores your data on Intuit's cloud. Anyone at Intuit can access it. Data may leave US jurisdiction. And any admin can edit or delete entries.

There's a better way. 🧵

### Post 2
Sovereign Ledger: a self-hosted double-entry accounting system built for defense contractors.

• 451 automated tests
• 98% core coverage
• Argon2id auth (OWASP minimum)
• Immutable audit trails
• Zero cloud egress

Runs on your infrastructure. Your data stays yours.

### Post 3
The security stack:

🔐 Argon2id (19 MB memory cost per hash — GPU cracking >$20K/hr)
🍪 itsdangerous signed cookies (HMAC-SHA256, SameSite=Strict)
🛡️ Per-session CSRF tokens
👥 Role-based access (admin/accountant, DI-enforced)
📦 Podman rootless containers

### Post 4
Every transaction is:
✅ Timestamped (microsecond precision)
✅ User-attributed (who posted it)
✅ Trigger-guarded (can't be modified or deleted)
✅ DCAA-aligned
✅ NIST 800-171 compatible

No cloud provider can guarantee this.

### Post 5
Built by NetIntegrate Systems LLC — an SDVOSB.

Pricing: $50/mo starter → $150/mo defense pro → enterprise custom.

Live demo at AFTC Industry Days, Sep 17.

Your financial data is too sensitive for someone else's cloud.

keith@outsetrealestate.com | 470-301-3653

---

## One-Pager Leave-Behind (printable)

**SOVEREIGN LEDGER**
Zero-Trust Accounting for Defense Contractors

**What:** Self-hosted double-entry accounting system with military-grade security and immutable audit trails.

**Who:** NetIntegrate Systems LLC (SDVOSB, CAGE 8V9X2, NAICS 541512)

**Why:** Cloud accounting (QuickBooks, Xero) exposes financial data to third-party access, cross-border residency, and admin-editable records. Sovereign Ledger eliminates these risks.

**Security:** Argon2id (OWASP minimum) · Signed cookies (SameSite=Strict) · Per-session CSRF tokens · Role-based access · Trigger-enforced immutability

**Features:** Core ledger · AR/AP · Banking & reconciliation · Tax management · Capital assets · Recurring transactions · Customer portal

**Testing:** 451 automated tests · 98% core coverage · 8 DB migrations · E2E workflows

**Pricing:** $50/mo Starter · $150/mo Defense Pro · Enterprise custom

**Contact:** Keith Ransom · keith@outsetrealestate.com · 470-301-3653 · app.netintegrate.net