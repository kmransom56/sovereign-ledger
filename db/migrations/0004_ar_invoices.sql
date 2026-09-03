-- ============================================================================
-- 0004_ar_invoices.sql — AR invoice schema (Step 8, CK-17)
--
-- Implements:
--   CK-17: Invoice tracking domain → invoice_id, customer_name, due_date, amount_cents, status
--   D-17: Invoice lifecycle status (draft, issued, paid, overdue, cancelled)
--   D-30: Invoice must be valid on creation.
--   D-40: Generate UUID for invoice ID.
--   D-42: Load invoice by UUID.
--
-- Schema:
--   ar_invoices (invoice_id: uuid PRIMARY, customer_name: text, due_date: date, amount_cents: bigint signed int,
--              status: text enum)
--   Indexes:
--     ar_invoices_due_date (due_date)
--     ar_invoices_customer_name (customer_name)
--     ar_invoices_status (status)

CREATE TABLE IF NOT EXISTS ar_invoices (
    invoice_id UUID PRIMARY KEY,
    customer_name TEXT NOT NULL,
    due_date DATE NOT NULL,
    amount_cents BIGINT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',

    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_ar_invoices_due_date ON ar_invoices(due_date);
CREATE INDEX IF NOT EXISTS idx_ar_invoices_customer_name ON ar_invoices(customer_name);
CREATE INDEX IF NOT EXISTS idx_ar_invoices_status ON ar_invoices(status);