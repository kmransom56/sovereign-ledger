-- ============================================================================
-- 0004_ar.sql — Accounts Receivable schema (Step 8, Phase 3)
--
-- Implements AR domain:
--   Customers, invoices with line items, payments with allocation,
--   overpayment → customer_credits liability, recurring templates.
--
-- Locked decisions honored:
--   D-10  Gapless invoice numbers via locked counter row inside posting xn
--   D-7   SERIALIZABLE for payment allocation (all-or-nothing)
--   HR-1  Every entry balances (Dr AR / Cr Income)
--   HR-8  Overpayment → customer_credits liability, not income
--   CK-6  Recurring templates generate exactly one invoice per cycle
--   CK-7  Payment allocation in serializable transaction
--
-- Table creation order respects FK dependencies.
-- ============================================================================

-- ================================================================ customers --
CREATE TABLE customers (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,           -- client name
    tax_id      TEXT,                            -- 1099 tracking (EIN/SSN if contractor)
    email       TEXT,                            -- contact email for statements
    address     TEXT,                            -- mailing address
    notes       TEXT,                            -- internal notes
    status      TEXT NOT NULL DEFAULT 'active'
                CHECK (status IN ('active', 'inactive', 'archived')),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_customers_status ON customers (status);

-- ================================================================ invoices --
-- An invoice is the master record for billing. It posts immediately upon
-- creation (not on send or payment) per CK-5: Dr AR / Cr Income in one
-- balanced entry. Status transitions: Draft → Posted → Paid (or Void).
-- Paid means 100% of the invoice amount has been received (payments allocated).
CREATE TABLE invoices (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    invoice_number  BIGINT NOT NULL UNIQUE,     -- gapless via locked counter (D-10)
    customer_id     BIGINT NOT NULL REFERENCES customers (id),
    issue_date      DATE NOT NULL,
    due_date        DATE NOT NULL,
    memo            TEXT,                        -- description for customer
    total_amount_cents BIGINT NOT NULL
                    CONSTRAINT invoices_amount_nonneg CHECK (total_amount_cents >= 0),
    status          TEXT NOT NULL DEFAULT 'draft'
                    CHECK (status IN ('draft', 'posted', 'paid', 'void')),
    posted_entry_id BIGINT REFERENCES journal_entries (id),
                    -- null until posted; once posted, immutable via FK consistency
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT invoices_dates CHECK (due_date >= issue_date)
);

CREATE INDEX idx_invoices_customer ON invoices (customer_id);
CREATE INDEX idx_invoices_status ON invoices (status);
CREATE INDEX idx_invoices_entry ON invoices (posted_entry_id);

-- ====================================================== invoice_lines --
-- Line items on an invoice. Each line is tied to an account (income account
-- for goods/services, or deferred revenue, etc.) so tax mapping is at the
-- line level, and the P&L drill-down works (GL detail → invoice detail).
CREATE TABLE invoice_lines (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    invoice_id      BIGINT NOT NULL REFERENCES invoices (id) ON DELETE CASCADE,
    account_id      BIGINT NOT NULL REFERENCES accounts (id),
                    -- income account (e.g. 'Services Revenue'); customer_id implicit via invoice
    description     TEXT NOT NULL,              -- "Privacy Dawg - Monthly Service"
    quantity        INTEGER NOT NULL DEFAULT 1
                    CONSTRAINT invoice_lines_qty_positive CHECK (quantity > 0),
    unit_price_cents BIGINT NOT NULL
                    CONSTRAINT invoice_lines_price_nonneg CHECK (unit_price_cents >= 0),
    amount_cents    BIGINT NOT NULL             -- quantity * unit_price_cents
                    CONSTRAINT invoice_lines_amount_nonneg CHECK (amount_cents >= 0),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_invoice_lines_invoice ON invoice_lines (invoice_id);
CREATE INDEX idx_invoice_lines_account ON invoice_lines (account_id);

-- ================================================================ payments --
-- A payment record represents money received from a customer and allocated
-- across one or more invoices. Payment records are inserted AFTER the money
-- arrives in the bank and is accepted as a bank line (Phase 2). The payment
-- allocation is all-or-nothing: either the entire payment is allocated
-- (flipping invoice statuses and posting the bank/AR entry) or it rolls back.
-- Serializable transaction enforced at the API layer (D-7 retry wrapper).
CREATE TABLE payments (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    customer_id     BIGINT NOT NULL REFERENCES customers (id),
    payment_date    DATE NOT NULL,
    amount_cents    BIGINT NOT NULL
                    CONSTRAINT payments_amount_positive CHECK (amount_cents > 0),
    memo            TEXT,                        -- e.g., "Check #1234"
    bank_line_id    BIGINT,                      -- optional FK to the bank line that triggered this payment
    posted_entry_id BIGINT REFERENCES journal_entries (id),
                    -- the Dr Bank / Cr AR entry; null until posted
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_payments_customer ON payments (customer_id);
CREATE INDEX idx_payments_date ON payments (payment_date);

-- ================================================= payment_allocations --
-- A payment allocation links a payment to an invoice and the amount applied.
-- Strictly: SUM(amount_cents) for a payment_id must equal payments.amount_cents.
-- This is enforced by the all-or-nothing transaction logic in the pure domain.
CREATE TABLE payment_allocations (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    payment_id      BIGINT NOT NULL REFERENCES payments (id) ON DELETE CASCADE,
    invoice_id      BIGINT NOT NULL REFERENCES invoices (id),
    amount_cents    BIGINT NOT NULL
                    CONSTRAINT payment_allocations_amount_positive CHECK (amount_cents > 0),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (payment_id, invoice_id)             -- one allocation per (payment, invoice) pair
);

CREATE INDEX idx_payment_allocations_payment ON payment_allocations (payment_id);
CREATE INDEX idx_payment_allocations_invoice ON payment_allocations (invoice_id);

-- ============================================================ customer_credits --
-- A customer credit is a liability (negative AR) that arises from overpayment
-- on an invoice. If a customer pays $60 on a $49 invoice, the $11 overage
-- becomes a customer_credits row (liability acct in ledger, dr/cr tracked
-- in the overpayment posting). The credit is applied to later invoices
-- exactly like a payment (CK-8).
CREATE TABLE customer_credits (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    customer_id     BIGINT NOT NULL REFERENCES customers (id),
    amount_cents    BIGINT NOT NULL
                    CONSTRAINT customer_credits_amount_positive CHECK (amount_cents > 0),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_customer_credits_customer ON customer_credits (customer_id);

-- ====================================================== recurring_templates --
-- A recurring template (e.g., "$49/mo Privacy Dawg subscription") that
-- generates an invoice on a fixed schedule (1st of month). The systemd
-- timer (P6, deploy/) invokes the CLI, which fetches active templates
-- and calls the pure domain's generation logic.
--
-- Price changes: updating the amount affects future generations only;
-- past cycles are untouched (BR-3). Pausing a template stops generation
-- without touching its history (BR-3).
CREATE TABLE recurring_templates (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    customer_id     BIGINT NOT NULL REFERENCES customers (id),
    name            TEXT NOT NULL,              -- "Privacy Dawg - Monthly"
    description     TEXT,                        -- narrative for the customer
    amount_cents    BIGINT NOT NULL
                    CONSTRAINT recurring_templates_amount_positive CHECK (amount_cents > 0),
    due_days_offset INTEGER NOT NULL DEFAULT 30,
                    -- invoice due date = issue date + this many days
    status          TEXT NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active', 'paused', 'ended')),
    active_from     DATE NOT NULL,              -- when the template starts generating
    active_until    DATE,                        -- NULL = indefinite; once set, no future invoices after this date
    line_account_id BIGINT NOT NULL REFERENCES accounts (id),
                    -- income account for the line item (e.g., subscription revenue)
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT recurring_templates_dates CHECK (active_until IS NULL OR active_until >= active_from)
);

CREATE INDEX idx_recurring_templates_customer ON recurring_templates (customer_id);
CREATE INDEX idx_recurring_templates_status ON recurring_templates (status);

-- ================================================== recurring_generations --
-- A record of when a recurring template was generated (success or failure).
-- Used to detect missing invoices (e.g., "expected April generation, none found")
-- and flag failures on the admin dashboard (CK-14).
CREATE TABLE recurring_generations (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    template_id     BIGINT NOT NULL REFERENCES recurring_templates (id),
    cycle_date      DATE NOT NULL,              -- the 1st of the month (or configured day)
    generated_invoice_id BIGINT REFERENCES invoices (id),
                    -- NULL if generation failed
    error_message   TEXT,                        -- if failed, why? for admin visibility
    attempted_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (template_id, cycle_date)
);

CREATE INDEX idx_recurring_generations_template ON recurring_generations (template_id);
CREATE INDEX idx_recurring_generations_cycle ON recurring_generations (cycle_date);

-- ============================================== invoice_number_counter --
-- D-10: Gapless invoice numbers via a locked counter row.
-- The posting transaction locks this row, increments it, and uses the number.
-- Postgres SERIAL/SEQUENCES burn numbers on rollback; this approach preserves them.
CREATE TABLE invoice_number_counter (
    id              BIGINT PRIMARY KEY DEFAULT 1,
    next_number     BIGINT NOT NULL DEFAULT 1,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT invoice_number_counter_single_row CHECK (id = 1)
);

INSERT INTO invoice_number_counter (id, next_number, updated_at)
    VALUES (1, 1000, now());  -- start at 1000 for readability

-- ============================================================= Permissions --
-- Grant the app role access to AR tables. Invoices and payments are posted
-- (immutable after posting) via the domain core, so the app role can INSERT
-- but not UPDATE/DELETE on the main tables (rows created during posting are
-- immutable; corrections are reversing entries in the ledger, not invoice edits).

GRANT SELECT, INSERT ON customers TO ledger_app;
GRANT SELECT, INSERT ON invoices TO ledger_app;
GRANT SELECT, INSERT ON invoice_lines TO ledger_app;
GRANT SELECT, INSERT ON payments TO ledger_app;
GRANT SELECT, INSERT ON payment_allocations TO ledger_app;
GRANT SELECT, INSERT ON customer_credits TO ledger_app;
GRANT SELECT, INSERT, UPDATE ON recurring_templates TO ledger_app;
                -- UPDATE for pause/resume
GRANT SELECT, INSERT ON recurring_generations TO ledger_app;
GRANT SELECT, INSERT, UPDATE ON invoice_number_counter TO ledger_app;
                -- UPDATE for the counter increment (D-10)
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO ledger_app;

-- ============================================================= Updates to invoices --
-- Allow status transitions on invoices (draft → posted → paid).
-- The domain layer enforces validity (e.g., can't flip to Paid without
-- sufficient allocations); the DB allows only specific transitions.
GRANT UPDATE (status) ON invoices TO ledger_app;
GRANT UPDATE (posted_entry_id) ON invoices TO ledger_app;  -- set once on posting

-- ============================================================= Updates to payments --
GRANT UPDATE (posted_entry_id) ON payments TO ledger_app;  -- set once on posting
