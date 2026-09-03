-- Step 13: Tax Breaks & Optimization Features
-- SurrealDB Schema for deductions, tax projections, capital assets, and optimization tracking
-- Namespace: sovereign | Database: ledger

-- ============================================================================
-- Table: capital_assets
-- Purpose: Track depreciable business assets for depreciation calculation
-- ============================================================================
DEFINE TABLE OVERWRITE capital_assets SCHEMAFULL;

DEFINE FIELD OVERWRITE user_id ON capital_assets TYPE record<users> | string;
DEFINE FIELD OVERWRITE description ON capital_assets TYPE string;
DEFINE FIELD OVERWRITE asset_type ON capital_assets TYPE string
  ASSERT $value IN [
    'computer_equipment', 'furniture_fixtures', 'machinery_equipment',
    'vehicles', 'real_property', 'land', 'leasehold_improvements',
    'intangible_assets', 'other'
  ];
DEFINE FIELD OVERWRITE cost_basis_cents ON capital_assets TYPE int ASSERT $value > 0;
DEFINE FIELD OVERWRITE salvage_value_cents ON capital_assets TYPE int DEFAULT 0 ASSERT $value >= 0;
DEFINE FIELD OVERWRITE useful_life_years ON capital_assets TYPE int ASSERT $value > 0;
DEFINE FIELD OVERWRITE depreciation_method ON capital_assets TYPE string DEFAULT 'macrs_200db'
  ASSERT $value IN ['macrs_200db', 'macrs_150db', 'straight_line', 'section_179', 'bonus_depreciation'];
DEFINE FIELD OVERWRITE date_placed_in_service ON capital_assets TYPE datetime | string;
DEFINE FIELD OVERWRITE vendor_name ON capital_assets TYPE option<string>;
DEFINE FIELD OVERWRITE invoice_date ON capital_assets TYPE option<datetime | string>;
DEFINE FIELD OVERWRITE invoice_number ON capital_assets TYPE option<string>;
DEFINE FIELD OVERWRITE notes ON capital_assets TYPE option<string>;
DEFINE FIELD OVERWRITE created_at ON capital_assets TYPE option<datetime | string> DEFAULT time::now();
DEFINE FIELD OVERWRITE updated_at ON capital_assets TYPE option<datetime | string> DEFAULT time::now();

DEFINE INDEX OVERWRITE idx_capital_assets_user_id ON capital_assets FIELDS user_id;
DEFINE INDEX OVERWRITE idx_capital_assets_asset_type ON capital_assets FIELDS asset_type;


-- ============================================================================
-- Table: depreciation_schedules
-- Purpose: Year-by-year depreciation breakdown for each asset
-- ============================================================================
DEFINE TABLE OVERWRITE depreciation_schedules SCHEMAFULL;

DEFINE FIELD OVERWRITE user_id ON depreciation_schedules TYPE record<users> | string;
DEFINE FIELD OVERWRITE asset_id ON depreciation_schedules TYPE record<capital_assets> | string;
DEFINE FIELD OVERWRITE depreciation_year ON depreciation_schedules TYPE int;
DEFINE FIELD OVERWRITE depreciation_cents ON depreciation_schedules TYPE int DEFAULT 0 ASSERT $value >= 0;
DEFINE FIELD OVERWRITE accumulated_depreciation_cents ON depreciation_schedules TYPE int DEFAULT 0 ASSERT $value >= 0;
DEFINE FIELD OVERWRITE book_value_cents ON depreciation_schedules TYPE int DEFAULT 0 ASSERT $value >= 0;
DEFINE FIELD OVERWRITE created_at ON depreciation_schedules TYPE option<datetime | string> DEFAULT time::now();

DEFINE INDEX OVERWRITE idx_depr_asset_year ON depreciation_schedules FIELDS asset_id, depreciation_year UNIQUE;
DEFINE INDEX OVERWRITE idx_depreciation_schedules_user_id ON depreciation_schedules FIELDS user_id;


-- ============================================================================
-- Table: deduction_aggregates
-- Purpose: Summarized deductions by period, category for tax reporting
-- ============================================================================
DEFINE TABLE OVERWRITE deduction_aggregates SCHEMAFULL;

DEFINE FIELD OVERWRITE user_id ON deduction_aggregates TYPE record<users> | string;
DEFINE FIELD OVERWRITE period_start ON deduction_aggregates TYPE datetime | string;
DEFINE FIELD OVERWRITE period_end ON deduction_aggregates TYPE datetime | string;
DEFINE FIELD OVERWRITE deduction_category ON deduction_aggregates TYPE string
  ASSERT $value IN [
    'supplies', 'utilities', 'rent', 'equipment', 'repairs', 'insurance',
    'vehicle', 'meals', 'travel', 'professional_services', 'advertising',
    'subscriptions', 'education', 'phone', 'home_office', 'other'
  ];
DEFINE FIELD OVERWRITE total_amount_cents ON deduction_aggregates TYPE int DEFAULT 0 ASSERT $value >= 0;
DEFINE FIELD OVERWRITE total_deductible_cents ON deduction_aggregates TYPE int DEFAULT 0 ASSERT $value >= 0;
DEFINE FIELD OVERWRITE average_business_use_percent ON deduction_aggregates TYPE int DEFAULT 100
  ASSERT $value >= 0 AND $value <= 100;
DEFINE FIELD OVERWRITE expense_count ON deduction_aggregates TYPE int DEFAULT 0 ASSERT $value >= 0;
DEFINE FIELD OVERWRITE created_at ON deduction_aggregates TYPE option<datetime | string> DEFAULT time::now();
DEFINE FIELD OVERWRITE updated_at ON deduction_aggregates TYPE option<datetime | string> DEFAULT time::now();

DEFINE INDEX OVERWRITE idx_deduction_user_period_cat ON deduction_aggregates
  FIELDS user_id, period_start, period_end, deduction_category UNIQUE;


-- ============================================================================
-- Table: estimated_tax_payments
-- Purpose: Track quarterly and annual estimated tax payments
-- ============================================================================
DEFINE TABLE OVERWRITE estimated_tax_payments SCHEMAFULL;

DEFINE FIELD OVERWRITE user_id ON estimated_tax_payments TYPE record<users> | string;
DEFINE FIELD OVERWRITE tax_year ON estimated_tax_payments TYPE int;
DEFINE FIELD OVERWRITE quarter ON estimated_tax_payments TYPE int ASSERT $value >= 1 AND $value <= 4;
DEFINE FIELD OVERWRITE payment_date ON estimated_tax_payments TYPE datetime | string;
DEFINE FIELD OVERWRITE amount_cents ON estimated_tax_payments TYPE int ASSERT $value >= 0;
DEFINE FIELD OVERWRITE payment_method ON estimated_tax_payments TYPE option<string>;
DEFINE FIELD OVERWRITE reference_number ON estimated_tax_payments TYPE option<string>;
DEFINE FIELD OVERWRITE safe_harbor_method ON estimated_tax_payments TYPE option<string>
  ASSERT $value == NONE OR $value IN ['90_current', '100_prior', '110_prior'];
DEFINE FIELD OVERWRITE notes ON estimated_tax_payments TYPE option<string>;
DEFINE FIELD OVERWRITE created_at ON estimated_tax_payments TYPE option<datetime | string> DEFAULT time::now();

DEFINE INDEX OVERWRITE idx_est_tax_user_year_quarter ON estimated_tax_payments
  FIELDS user_id, tax_year, quarter UNIQUE;


-- ============================================================================
-- Table: tax_form_mappings
-- Purpose: Map deduction categories and accounts to tax form lines
-- ============================================================================
DEFINE TABLE OVERWRITE tax_form_mappings SCHEMAFULL;

DEFINE FIELD OVERWRITE user_id ON tax_form_mappings TYPE record<users> | string;
DEFINE FIELD OVERWRITE tax_form ON tax_form_mappings TYPE string;
DEFINE FIELD OVERWRITE form_line ON tax_form_mappings TYPE string;
DEFINE FIELD OVERWRITE form_line_description ON tax_form_mappings TYPE option<string>;
DEFINE FIELD OVERWRITE deduction_category ON tax_form_mappings TYPE option<string>;
DEFINE FIELD OVERWRITE account_id ON tax_form_mappings TYPE option<record<accounts> | string>;
DEFINE FIELD OVERWRITE percentage_allocation ON tax_form_mappings TYPE int DEFAULT 100
  ASSERT $value >= 0 AND $value <= 100;
DEFINE FIELD OVERWRITE notes ON tax_form_mappings TYPE option<string>;
DEFINE FIELD OVERWRITE created_at ON tax_form_mappings TYPE option<datetime | string> DEFAULT time::now();
DEFINE FIELD OVERWRITE updated_at ON tax_form_mappings TYPE option<datetime | string> DEFAULT time::now();


-- ============================================================================
-- Table: deduction_audit_trail
-- Purpose: Immutable audit trail of deduction calculations and changes
-- ============================================================================
DEFINE TABLE OVERWRITE deduction_audit_trail SCHEMAFULL;

DEFINE FIELD OVERWRITE user_id ON deduction_audit_trail TYPE record<users> | string;
DEFINE FIELD OVERWRITE bill_id ON deduction_audit_trail TYPE option<record<bills> | string>;
DEFINE FIELD OVERWRITE deduction_category ON deduction_audit_trail TYPE string;
DEFINE FIELD OVERWRITE transaction_date ON deduction_audit_trail TYPE datetime | string;
DEFINE FIELD OVERWRITE amount_cents ON deduction_audit_trail TYPE int;
DEFINE FIELD OVERWRITE deductible_amount_cents ON deduction_audit_trail TYPE int;
DEFINE FIELD OVERWRITE business_use_percent ON deduction_audit_trail TYPE int ASSERT $value >= 0 AND $value <= 100;
DEFINE FIELD OVERWRITE deduction_type ON deduction_audit_trail TYPE string DEFAULT 'ordinary'
  ASSERT $value IN [
    'ordinary', 'reasonable_salary', 'home_office', 'vehicle_mileage',
    'meal_entertainment', 'education', 'charitable', 'casualty_loss',
    'hobby_related', 'nondeductible'
  ];
DEFINE FIELD OVERWRITE limitation_type ON deduction_audit_trail TYPE string DEFAULT 'none'
  ASSERT $value IN ['none', 'percentage', 'passive_activity', 'hobby_loss', 'amt_exclusion'];
DEFINE FIELD OVERWRITE notes ON deduction_audit_trail TYPE option<string>;
DEFINE FIELD OVERWRITE created_at ON deduction_audit_trail TYPE option<datetime | string> DEFAULT time::now();

DEFINE INDEX OVERWRITE idx_deduction_audit_user_bill ON deduction_audit_trail FIELDS user_id, bill_id UNIQUE;


-- ============================================================================
-- Table: tax_break_opportunities
-- Purpose: Identified tax optimization opportunities and strategies
-- ============================================================================
DEFINE TABLE OVERWRITE tax_break_opportunities SCHEMAFULL;

DEFINE FIELD OVERWRITE user_id ON tax_break_opportunities TYPE record<users> | string;
DEFINE FIELD OVERWRITE opportunity_type ON tax_break_opportunities TYPE string;
DEFINE FIELD OVERWRITE description ON tax_break_opportunities TYPE string;
DEFINE FIELD OVERWRITE current_deduction_cents ON tax_break_opportunities TYPE int DEFAULT 0 ASSERT $value >= 0;
DEFINE FIELD OVERWRITE potential_deduction_cents ON tax_break_opportunities TYPE int DEFAULT 0 ASSERT $value >= 0;
DEFINE FIELD OVERWRITE tax_savings_cents ON tax_break_opportunities TYPE int DEFAULT 0 ASSERT $value >= 0;
DEFINE FIELD OVERWRITE estimated_marginal_rate ON tax_break_opportunities TYPE float DEFAULT 0.24
  ASSERT $value >= 0.0 AND $value <= 1.0;
DEFINE FIELD OVERWRITE status ON tax_break_opportunities TYPE string DEFAULT 'available'
  ASSERT $value IN ['available', 'in_progress', 'claimed', 'ineligible'];
DEFINE FIELD OVERWRITE applicable_from ON tax_break_opportunities TYPE option<datetime | string>;
DEFINE FIELD OVERWRITE applicable_until ON tax_break_opportunities TYPE option<datetime | string>;
DEFINE FIELD OVERWRITE implementation_difficulty ON tax_break_opportunities TYPE option<string>
  ASSERT $value == NONE OR $value IN ['low', 'medium', 'high'];
DEFINE FIELD OVERWRITE requirements ON tax_break_opportunities TYPE option<array>;
DEFINE FIELD OVERWRITE notes ON tax_break_opportunities TYPE option<string>;
DEFINE FIELD OVERWRITE created_at ON tax_break_opportunities TYPE option<datetime | string> DEFAULT time::now();
DEFINE FIELD OVERWRITE updated_at ON tax_break_opportunities TYPE option<datetime | string> DEFAULT time::now();
