# Sovereign Ledger — Subscription Pricing & Business Model

## Overview

Sovereign Ledger is monetized through a tiered SaaS subscription model with professional services add-ons. The system is self-hosted by the customer (on their infrastructure), but NetIntegrate provides:
- Software license (source code access + updates)
- Implementation services (deployment, Wave cutover, configuration)
- Ongoing support (security patches, feature updates, compliance mapping)
- Training (admin/accountant onboarding)

---

## Subscription Tiers

### Tier 1: Sovereign Starter — $50/month

**Target:** Small defense contractors (single entity, ≤$5M revenue)

**Includes:**
- Core double-entry ledger (accounts, journal entries, trial balance)
- Chart of accounts with federal categories
- Fiscal period management (open/close/lock)
- Wave CSV cutover import
- 1 entity, 2 users (1 admin + 1 accountant)
- Email support (48-hour response)
- Quarterly security patches

**Limits:**
- No AR/AP modules
- No bank import/reconciliation
- No tax management
- No customer portal

**Cost to serve:** ~$5/mo (Podman hosting overhead on customer's infra)
**Gross margin:** 90%

---

### Tier 2: Defense Pro — $150/month

**Target:** Mid-size government contractors (multi-entity, $5M–$50M revenue)

**Includes:**
- Everything in Starter, plus:
- Accounts Receivable (customers, invoices, payments, aging)
- Accounts Payable (vendors, bills, payments, 1099 prep)
- Banking & Reconciliation (OFX import, CSV import, match workflow)
- Tax Management (rates, calculations, optimization, projections)
- Capital Assets (depreciation, Section 179)
- Recurring Transactions
- Customer Portal
- 3 entities, 5 users
- Email + phone support (24-hour response)
- Monthly security patches + feature updates

**Limits:**
- No custom compliance mapping
- No multi-entity consolidation

**Cost to serve:** ~$15/mo (support time, patch development)
**Gross margin:** 90%

---

### Tier 3: Sovereign Enterprise — $500–$2,000/month (custom)

**Target:** Large contractors, primes ($50M+ revenue, multi-entity)

**Includes:**
- Everything in Defense Pro, plus:
- Multi-entity consolidation
- Custom compliance mapping (DCAA, FAR, NIST 800-171)
- Custom DCAA-compliant report generation
- Role-based access with custom roles (beyond admin/accountant)
- Unlimited entities, unlimited users
- Priority support (4-hour response, dedicated engineer)
- On-site training (2 days/year included)
- Custom integration development
- SLA with uptime guarantee

**Cost to serve:** ~$100/mo (dedicated support engineer time allocation)
**Gross margin:** 70–85%

---

## Professional Services

| Service | Price | Duration | Description |
|---|---|---|---|
| System Installation | $2,500 | 1 day | Podman setup, PostgreSQL init, Wave cutover, user creation |
| System Installation (complex) | $5,000 | 2 days | Multi-entity, custom CoA, OFX bank integration, training |
| Compliance Mapping | $3,000–$8,000 | 1–2 weeks | DCAA/FAR/NIST configuration, custom report templates, audit trail verification |
| Security Audit | $5,000–$15,000 | 1–3 weeks | OWASP Top 10 assessment, penetration testing, remediation report |
| Training (on-site) | $1,000/day | 1–3 days | Admin training, accountant training, compliance officer briefing |
| Training (virtual) | $500/half-day | 4 hours | Same content, remote delivery |
| Custom Integration | $150/hour | TBD | API integration with existing ERP, payroll, or procurement systems |

---

## Revenue Projection (12-Month)

### Year 1 — Launch Phase (Sep 2026 – Aug 2027)

| Month | Starter | Defense Pro | Enterprise | Services | MRR | Cumulative |
|---|---|---|---|---|---|---|
| Sep | 0 | 0 | 0 | $2,500 (1 install) | $0 | $2,500 |
| Oct | 1 | 0 | 0 | $5,000 (2 installs) | $50 | $7,550 |
| Nov | 2 | 0 | 0 | $2,500 | $100 | $10,150 |
| Dec | 3 | 1 | 0 | $5,000 (1 compliance) | $300 | $15,450 |
| Jan | 4 | 1 | 0 | $3,000 | $350 | $18,800 |
| Feb | 5 | 2 | 0 | $7,500 (1 audit) | $550 | $26,850 |
| Mar | 6 | 2 | 0 | $3,000 | $600 | $30,450 |
| Apr | 7 | 3 | 0 | $5,000 | $800 | $36,250 |
| May | 8 | 3 | 1 | $12,000 (1 enterprise install) | $1,300 | $49,550 |
| Jun | 9 | 4 | 1 | $3,000 | $1,550 | $54,100 |
| Jul | 10 | 4 | 1 | $8,000 (1 compliance + 1 audit) | $1,700 | $63,800 |
| Aug | 10 | 5 | 1 | $5,000 | $1,750 | $70,550 |

**Year 1 Total: ~$70,550** (subscription: $10,500 + services: $60,050)

### Year 2 — Growth Phase (projected)

| Metric | Value |
|---|---|
| Starting MRR | $1,750 |
| Target MRR (end of Y2) | $8,000–$15,000 |
| New customers | 30–60 |
| Services revenue | $80K–$150K |
| **Year 2 Total** | **$150K–$300K** |

### Year 3 — Scale Phase (projected)

| Metric | Value |
|---|---|
| Target MRR | $20,000–$50,000 |
| Enterprise customers | 5–10 |
| **Year 3 Total** | **$400K–$1M** |

---

## Customer Acquisition Cost (CAC) Estimates

| Channel | CAC | Target |
|---|---|---|
| AFTC Industry Days demo | $0 (already attending) | 2–5 leads |
| LinkedIn content (organic) | $50–$100 (time) | 5–10 leads/quarter |
| Defense News / C4ISR articles | $500–$1,000 (placement) | 10–20 leads |
| Direct cold email | $20–$50 (time + tools) | 50–100 sends → 5–10 leads |
| Conference presentations | $1,000–$3,000 (travel) | 10–30 leads |

**Target CAC:** $200–$500 per Defense Pro customer
**LTV (Defense Pro, 3-year retention):** $5,400 + ~$10,000 services = ~$15,400
**LTV:CAC ratio:** 30:1+ (excellent)

---

## Competitive Pricing Analysis

| Product | Entry Price | Multi-Entity | CUI-Ready | Immutability |
|---|---|---|---|---|
| QuickBooks Online Simple | $30/mo | $30/mo each | ✗ | ✗ |
| QuickBooks Online Advanced | $200/mo | $200/mo each | ✗ | ✗ |
| Xero Established | $80/mo | $80/mo each | ✗ | ✗ |
| Zoho Books Ultimate | $120/mo | Add-on | ✗ | ✗ |
| NetSuite | $999/mo+ | Included | Add-on | Configurable |
| **Sovereign Ledger Starter** | **$50/mo** | **N/A** | **✓** | **✓** |
| **Sovereign Ledger Defense Pro** | **$150/mo** | **3 included** | **✓** | **✓** |

**Key differentiator:** Sovereign Ledger is the only accounting platform with trigger-enforced immutability, Argon2id at OWASP minimum, and zero cloud egress at any price point.

---

## Revenue Diversification

### Content Revenue (Year 1)
- White paper downloads: $49–$199 each, target 50–100 downloads = $2.5K–$20K
- LinkedIn articles (free) → lead generation → services revenue
- Conference speaking (free) → lead generation → services revenue

### Future Products (Year 2+)
- **Sovereign Payroll**: Self-hosted payroll module ($75/mo add-on)
- **Sovereign Procurement**: Purchase order + vendor management ($100/mo add-on)
- **Sovereign Inventory**: Stock tracking + cost of goods ($75/mo add-on)
- **Sovereign Audit**: Automated DCAA compliance checker ($200/mo add-on)

---

## Key Assumptions

1. **Self-hosted model**: Customer provides infrastructure. NetIntegrate provides software + support, not hosting. This keeps cost-to-serve low and margins high.
2. **SDVOSB advantage**: Federal set-aside contracts give preference to SDVOSB firms. Target SDVOSB-eligible accounting system requirements.
3. **Defense contractor market**: ~200,000+ SAM.gov registered contractors. Even 0.01% market share = 20 customers.
4. **No cloud costs**: Unlike SaaS competitors, Sovereign Ledger has near-zero marginal infrastructure cost per customer.
5. **Source code access**: Customers can audit the codebase themselves (unlike closed-source competitors), reducing sales friction with security-conscious buyers.