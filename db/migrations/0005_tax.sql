-- Tax support: rates, jurisdiction management, and tax calculations (Step 11).

-- Tax jurisdictions (states, countries, local)
CREATE TABLE tax_jurisdictions (
    id SERIAL PRIMARY KEY,
    code VARCHAR(20) NOT NULL UNIQUE,  -- "CA", "TX", "US-FEDERAL", etc.
    name VARCHAR(255) NOT NULL,
    tax_type VARCHAR(50) NOT NULL,  -- "sales_tax", "vat", "gst", "hst"
    region_type VARCHAR(50),  -- "state", "country", "local"
    active BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Tax rates effective on specific dates
CREATE TABLE tax_rates (
    id SERIAL PRIMARY KEY,
    jurisdiction_id INTEGER NOT NULL REFERENCES tax_jurisdictions(id),
    rate_percent NUMERIC(5, 3) NOT NULL,  -- 8.5, 10.0, etc. (percentage points)
    effective_from DATE NOT NULL,
    effective_until DATE,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Customer tax exemptions (resale certs, tax-exempt status)
CREATE TABLE customer_tax_exemptions (
    id SERIAL PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers(id),
    jurisdiction_id INTEGER NOT NULL REFERENCES tax_jurisdictions(id),
    exemption_number VARCHAR(100),  -- Resale cert number, etc.
    exemption_type VARCHAR(50),  -- "resale", "nonprofit", "government", "foreign"
    effective_from DATE NOT NULL,
    effective_until DATE,
    active BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(customer_id, jurisdiction_id, exemption_type)
);

-- Invoice line item taxes (many-to-many with rates applied)
CREATE TABLE invoice_line_taxes (
    id SERIAL PRIMARY KEY,
    invoice_id INTEGER NOT NULL REFERENCES invoices(id),
    invoice_line_id INTEGER NOT NULL REFERENCES invoice_lines(id),
    jurisdiction_id INTEGER NOT NULL REFERENCES tax_jurisdictions(id),
    tax_rate_id INTEGER NOT NULL REFERENCES tax_rates(id),
    taxable_amount_cents INTEGER NOT NULL,  -- Amount to which tax applies
    tax_amount_cents INTEGER NOT NULL,  -- Calculated tax (signed integer cents)
    exemption_id INTEGER REFERENCES customer_tax_exemptions(id),  -- If exempted
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Tax liability account (for tracking tax payable)
CREATE TABLE tax_liability (
    id SERIAL PRIMARY KEY,
    jurisdiction_id INTEGER NOT NULL REFERENCES tax_jurisdictions(id),
    invoice_id INTEGER REFERENCES invoices(id),
    period_end DATE NOT NULL,  -- Monthly, quarterly, or annual period
    collected_cents INTEGER NOT NULL,  -- Total tax collected (signed integer)
    paid_cents INTEGER DEFAULT 0,  -- Amount paid to jurisdiction
    posted_entry_id INTEGER REFERENCES journal_entries(id),  -- Journal entry for recording
    status VARCHAR(50) DEFAULT 'accrued',  -- accrued, paid, settled, filed
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Tax filing records (monthly/quarterly/annual filings)
CREATE TABLE tax_filings (
    id SERIAL PRIMARY KEY,
    jurisdiction_id INTEGER NOT NULL REFERENCES tax_jurisdictions(id),
    filing_period_start DATE NOT NULL,
    filing_period_end DATE NOT NULL,
    filing_type VARCHAR(50),  -- "monthly", "quarterly", "annual"
    total_sales_cents INTEGER NOT NULL,
    tax_collected_cents INTEGER NOT NULL,
    tax_paid_cents INTEGER NOT NULL,
    filing_date DATE,
    reference_number VARCHAR(100),  -- Confirmation number from filing
    status VARCHAR(50) DEFAULT 'draft',  -- draft, filed, paid, reconciled
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for common queries
CREATE INDEX idx_tax_rates_jurisdiction_effective ON tax_rates(jurisdiction_id, effective_from DESC);
CREATE INDEX idx_customer_exemptions_jurisdiction ON customer_tax_exemptions(customer_id, jurisdiction_id);
CREATE INDEX idx_invoice_line_taxes_invoice ON invoice_line_taxes(invoice_id);
CREATE INDEX idx_tax_liability_jurisdiction_period ON tax_liability(jurisdiction_id, period_end);
CREATE INDEX idx_tax_filings_jurisdiction_period ON tax_filings(jurisdiction_id, filing_period_start);
