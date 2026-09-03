-- Step 13: Tax Breaks & Optimization Features (Phase 2)
-- Schema for deductions, tax projections, capital assets, and optimization tracking

-- ============================================================================
-- Table: capital_assets
-- Purpose: Track depreciable business assets for depreciation calculation
-- Locked: HR-1 (append-only), D-3 (cents), T-10 (placed-in-service trigger)
-- ============================================================================

CREATE TABLE capital_assets (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    description VARCHAR(255) NOT NULL,
    asset_type VARCHAR(50) NOT NULL CHECK(asset_type IN (
        'computer_equipment', 'furniture_fixtures', 'machinery_equipment',
        'vehicles', 'real_property', 'land', 'leasehold_improvements',
        'intangible_assets', 'other'
    )),
    cost_basis_cents BIGINT NOT NULL CHECK(cost_basis_cents > 0),
    salvage_value_cents BIGINT NOT NULL DEFAULT 0 CHECK(salvage_value_cents >= 0),
    depreciable_basis_cents BIGINT NOT NULL GENERATED ALWAYS AS (cost_basis_cents - salvage_value_cents) STORED,
    useful_life_years INTEGER NOT NULL CHECK(useful_life_years > 0),
    depreciation_method VARCHAR(50) NOT NULL DEFAULT 'macrs_200db' CHECK(depreciation_method IN (
        'macrs_200db', 'macrs_150db', 'straight_line', 'section_179', 'bonus_depreciation'
    )),
    date_placed_in_service DATE NOT NULL,
    vendor_name VARCHAR(255),
    invoice_date DATE,
    invoice_number VARCHAR(100),
    notes TEXT,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_capital_assets_user_id ON capital_assets(user_id);
CREATE INDEX idx_capital_assets_asset_type ON capital_assets(asset_type);
CREATE INDEX idx_capital_assets_placed_in_service ON capital_assets(date_placed_in_service);


-- ============================================================================
-- Table: depreciation_schedules
-- Purpose: Year-by-year depreciation breakdown for each asset
-- Locked: HR-1 (append-only), D-3 (cents)
-- ============================================================================

CREATE TABLE depreciation_schedules (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    asset_id INTEGER NOT NULL REFERENCES capital_assets(id) ON DELETE CASCADE,
    depreciation_year INTEGER NOT NULL,
    depreciation_cents BIGINT NOT NULL DEFAULT 0 CHECK(depreciation_cents >= 0),
    accumulated_depreciation_cents BIGINT NOT NULL DEFAULT 0 CHECK(accumulated_depreciation_cents >= 0),
    book_value_cents BIGINT NOT NULL DEFAULT 0 CHECK(book_value_cents >= 0),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(asset_id, depreciation_year)
);

CREATE INDEX idx_depreciation_schedules_user_id ON depreciation_schedules(user_id);
CREATE INDEX idx_depreciation_schedules_asset_id ON depreciation_schedules(asset_id);
CREATE INDEX idx_depreciation_schedules_year ON depreciation_schedules(depreciation_year);


-- ============================================================================
-- Table: deduction_aggregates
-- Purpose: Summarized deductions by period, category for tax reporting
-- Locked: D-3 (cents), HR-1 (computed from posted bills)
-- ============================================================================

CREATE TABLE deduction_aggregates (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    deduction_category VARCHAR(50) NOT NULL CHECK(deduction_category IN (
        'supplies', 'utilities', 'rent', 'equipment', 'repairs', 'insurance',
        'vehicle', 'meals', 'travel', 'professional_services', 'advertising',
        'subscriptions', 'education', 'phone', 'home_office', 'other'
    )),
    total_amount_cents BIGINT NOT NULL DEFAULT 0 CHECK(total_amount_cents >= 0),
    total_deductible_cents BIGINT NOT NULL DEFAULT 0 CHECK(total_deductible_cents >= 0),
    average_business_use_percent INTEGER NOT NULL DEFAULT 100 CHECK(average_business_use_percent >= 0 AND average_business_use_percent <= 100),
    expense_count INTEGER NOT NULL DEFAULT 0 CHECK(expense_count >= 0),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, period_start, period_end, deduction_category)
);

CREATE INDEX idx_deduction_aggregates_user_id ON deduction_aggregates(user_id);
CREATE INDEX idx_deduction_aggregates_period ON deduction_aggregates(period_start, period_end);
CREATE INDEX idx_deduction_aggregates_category ON deduction_aggregates(deduction_category);


-- ============================================================================
-- Table: estimated_tax_payments
-- Purpose: Track quarterly and annual estimated tax payments
-- Locked: D-3 (cents), T-10 (payment trigger)
-- ============================================================================

CREATE TABLE estimated_tax_payments (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    tax_year INTEGER NOT NULL,
    quarter INTEGER NOT NULL CHECK(quarter >= 1 AND quarter <= 4),
    payment_date DATE NOT NULL,
    amount_cents BIGINT NOT NULL CHECK(amount_cents >= 0),
    payment_method VARCHAR(50),  -- 'check', 'ach', 'credit_card', 'cash'
    reference_number VARCHAR(100),
    safe_harbor_method VARCHAR(50) CHECK(safe_harbor_method IN ('90_current', '100_prior', '110_prior')),
    notes TEXT,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, tax_year, quarter)
);

CREATE INDEX idx_estimated_tax_payments_user_id ON estimated_tax_payments(user_id);
CREATE INDEX idx_estimated_tax_payments_tax_year ON estimated_tax_payments(tax_year);
CREATE INDEX idx_estimated_tax_payments_payment_date ON estimated_tax_payments(payment_date);


-- ============================================================================
-- Table: tax_form_mappings
-- Purpose: Map deduction categories and accounts to tax form lines
-- Locked: Configuration reference (not audit data)
-- ============================================================================

CREATE TABLE tax_form_mappings (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    tax_form VARCHAR(50) NOT NULL,  -- 'Schedule C', 'Schedule E', 'Form 4562', etc.
    form_line VARCHAR(20) NOT NULL,  -- 'Line 1', 'Line 8', etc.
    form_line_description VARCHAR(255),
    deduction_category VARCHAR(50),  -- References deduction_aggregates.deduction_category
    account_id INTEGER REFERENCES accounts(id),
    percentage_allocation INTEGER DEFAULT 100 CHECK(percentage_allocation >= 0 AND percentage_allocation <= 100),
    notes TEXT,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_tax_form_mappings_user_id ON tax_form_mappings(user_id);
CREATE INDEX idx_tax_form_mappings_form ON tax_form_mappings(tax_form);
CREATE INDEX idx_tax_form_mappings_account_id ON tax_form_mappings(account_id);


-- ============================================================================
-- Table: deduction_audit_trail
-- Purpose: Immutable audit trail of deduction calculations and changes
-- Locked: HR-1 (append-only), D-3 (cents)
-- ============================================================================

CREATE TABLE deduction_audit_trail (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    bill_id INTEGER REFERENCES bills(id) ON DELETE SET NULL,
    deduction_category VARCHAR(50) NOT NULL,
    transaction_date DATE NOT NULL,
    amount_cents BIGINT NOT NULL,
    deductible_amount_cents BIGINT NOT NULL,
    business_use_percent INTEGER NOT NULL CHECK(business_use_percent >= 0 AND business_use_percent <= 100),
    deduction_type VARCHAR(50) NOT NULL DEFAULT 'ordinary' CHECK(deduction_type IN (
        'ordinary', 'reasonable_salary', 'home_office', 'vehicle_mileage',
        'meal_entertainment', 'education', 'charitable', 'casualty_loss',
        'hobby_related', 'nondeductible'
    )),
    limitation_type VARCHAR(50) NOT NULL DEFAULT 'none' CHECK(limitation_type IN (
        'none', 'percentage', 'passive_activity', 'hobby_loss', 'amt_exclusion'
    )),
    notes TEXT,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, bill_id)
);

CREATE INDEX idx_deduction_audit_trail_user_id ON deduction_audit_trail(user_id);
CREATE INDEX idx_deduction_audit_trail_bill_id ON deduction_audit_trail(bill_id);
CREATE INDEX idx_deduction_audit_trail_transaction_date ON deduction_audit_trail(transaction_date);
CREATE INDEX idx_deduction_audit_trail_category ON deduction_audit_trail(deduction_category);


-- ============================================================================
-- Table: tax_break_opportunities
-- Purpose: Identified tax optimization opportunities and strategies
-- Locked: D-3 (cents), computation from current state
-- ============================================================================

CREATE TABLE tax_break_opportunities (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    opportunity_type VARCHAR(100) NOT NULL,  -- 'home_office', 'vehicle_mileage', 'quarterly_payments', etc.
    description TEXT NOT NULL,
    current_deduction_cents BIGINT NOT NULL DEFAULT 0 CHECK(current_deduction_cents >= 0),
    potential_deduction_cents BIGINT NOT NULL DEFAULT 0 CHECK(potential_deduction_cents >= 0),
    tax_savings_cents BIGINT NOT NULL DEFAULT 0 CHECK(tax_savings_cents >= 0),
    estimated_marginal_rate NUMERIC(5, 3) NOT NULL DEFAULT 0.24 CHECK(estimated_marginal_rate >= 0 AND estimated_marginal_rate <= 1.0),
    status VARCHAR(50) NOT NULL DEFAULT 'available' CHECK(status IN (
        'available', 'in_progress', 'claimed', 'ineligible'
    )),
    applicable_from DATE,
    applicable_until DATE,
    implementation_difficulty VARCHAR(50) CHECK(implementation_difficulty IN ('low', 'medium', 'high')),
    requirements TEXT,  -- JSON array of requirement strings
    notes TEXT,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_tax_break_opportunities_user_id ON tax_break_opportunities(user_id);
CREATE INDEX idx_tax_break_opportunities_type ON tax_break_opportunities(opportunity_type);
CREATE INDEX idx_tax_break_opportunities_status ON tax_break_opportunities(status);
CREATE INDEX idx_tax_break_opportunities_applicable ON tax_break_opportunities(applicable_from, applicable_until);


-- ============================================================================
-- Permissions & Row-Level Security (RLS)
-- Purpose: Ensure users can only access their own data
-- ============================================================================

ALTER TABLE capital_assets ENABLE ROW LEVEL SECURITY;
ALTER TABLE depreciation_schedules ENABLE ROW LEVEL SECURITY;
ALTER TABLE deduction_aggregates ENABLE ROW LEVEL SECURITY;
ALTER TABLE estimated_tax_payments ENABLE ROW LEVEL SECURITY;
ALTER TABLE tax_form_mappings ENABLE ROW LEVEL SECURITY;
ALTER TABLE deduction_audit_trail ENABLE ROW LEVEL SECURITY;
ALTER TABLE tax_break_opportunities ENABLE ROW LEVEL SECURITY;

CREATE POLICY capital_assets_owner ON capital_assets FOR ALL USING (user_id = CURRENT_USER_ID());
CREATE POLICY depreciation_schedules_owner ON depreciation_schedules FOR ALL USING (user_id = CURRENT_USER_ID());
CREATE POLICY deduction_aggregates_owner ON deduction_aggregates FOR ALL USING (user_id = CURRENT_USER_ID());
CREATE POLICY estimated_tax_payments_owner ON estimated_tax_payments FOR ALL USING (user_id = CURRENT_USER_ID());
CREATE POLICY tax_form_mappings_owner ON tax_form_mappings FOR ALL USING (user_id = CURRENT_USER_ID());
CREATE POLICY deduction_audit_trail_owner ON deduction_audit_trail FOR ALL USING (user_id = CURRENT_USER_ID());
CREATE POLICY tax_break_opportunities_owner ON tax_break_opportunities FOR ALL USING (user_id = CURRENT_USER_ID());
