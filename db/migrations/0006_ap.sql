-- AP support: vendors, bills, payments (Step 12).

-- Vendors/suppliers
CREATE TABLE vendors (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    tax_id VARCHAR(50),  -- EIN, etc.
    contact_name VARCHAR(255),
    email VARCHAR(255),
    phone VARCHAR(20),
    address TEXT,
    city VARCHAR(100),
    state VARCHAR(2),
    zip_code VARCHAR(10),
    payment_terms VARCHAR(50),  -- "net30", "net60", "due_on_receipt", etc.
    is_active BOOLEAN DEFAULT true,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Expense categories (e.g., Software, Utilities, Professional Services)
CREATE TABLE expense_categories (
    id SERIAL PRIMARY KEY,
    code VARCHAR(20) NOT NULL UNIQUE,  -- "SW", "UTIL", "PROF", etc.
    name VARCHAR(100) NOT NULL,
    description TEXT,
    account_id INTEGER REFERENCES accounts(id),  -- Link to chart of accounts for posting
    tax_deductible BOOLEAN DEFAULT true,  -- For tax reporting
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Bills from vendors
CREATE TABLE bills (
    id SERIAL PRIMARY KEY,
    bill_number VARCHAR(50) NOT NULL UNIQUE,
    vendor_id INTEGER NOT NULL REFERENCES vendors(id),
    bill_date DATE NOT NULL,
    due_date DATE NOT NULL,
    period_end DATE,  -- For recurring expenses (e.g., monthly software)
    total_amount_cents INTEGER NOT NULL,
    paid_amount_cents INTEGER DEFAULT 0,
    status VARCHAR(50) DEFAULT 'draft',  -- draft, posted, paid, overdue, voided
    memo TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Bill line items
CREATE TABLE bill_items (
    id SERIAL PRIMARY KEY,
    bill_id INTEGER NOT NULL REFERENCES bills(id),
    expense_category_id INTEGER NOT NULL REFERENCES expense_categories(id),
    description VARCHAR(255) NOT NULL,
    quantity NUMERIC(10, 2) DEFAULT 1,
    unit_price_cents INTEGER NOT NULL,
    amount_cents INTEGER NOT NULL,
    business_use_percent NUMERIC(3, 1) DEFAULT 100.0,  -- For mixed-use expenses (0-100)
    deductible_amount_cents INTEGER NOT NULL,  -- amount_cents * business_use_percent / 100
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Bill payments
CREATE TABLE bill_payments (
    id SERIAL PRIMARY KEY,
    bill_id INTEGER NOT NULL REFERENCES bills(id),
    payment_date DATE NOT NULL,
    amount_cents INTEGER NOT NULL,
    payment_method VARCHAR(50),  -- "check", "ach", "credit_card", "cash", etc.
    reference_number VARCHAR(100),  -- Check number, ACH ref, etc.
    posted_entry_id INTEGER REFERENCES journal_entries(id),  -- Journal entry for payment posting
    memo TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for common queries
CREATE INDEX idx_vendors_active ON vendors(is_active);
CREATE INDEX idx_bills_vendor ON bills(vendor_id);
CREATE INDEX idx_bills_status ON bills(status);
CREATE INDEX idx_bills_due_date ON bills(due_date);
CREATE INDEX idx_bill_items_category ON bill_items(expense_category_id);
CREATE INDEX idx_bill_payments_bill ON bill_payments(bill_id);
CREATE INDEX idx_expense_categories_active ON expense_categories(is_active);

-- View for AP aging (unpaid/partially paid bills)
CREATE VIEW ap_aging AS
SELECT
    b.id,
    b.bill_number,
    v.name as vendor_name,
    b.bill_date,
    b.due_date,
    b.total_amount_cents,
    b.paid_amount_cents,
    (b.total_amount_cents - b.paid_amount_cents) as outstanding_cents,
    CASE
        WHEN b.status = 'paid' THEN 'Paid'
        WHEN CURRENT_DATE > b.due_date THEN 'Overdue'
        ELSE 'Current'
    END as aging_status,
    (CURRENT_DATE - b.due_date) as days_overdue
FROM bills b
JOIN vendors v ON b.vendor_id = v.id
WHERE b.status NOT IN ('voided')
ORDER BY b.due_date ASC;
