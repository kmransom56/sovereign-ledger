-- Sovereign Ledger Tax Analytics (ClickHouse Engine)
-- Database: ledger_analytics
-- Real-time OLAP aggregations for deductions, depreciation curves, and quarterly projections

CREATE DATABASE IF NOT EXISTS ledger_analytics;

-- 1. Raw Tax Deduction Events (Time-Series Log)
CREATE TABLE IF NOT EXISTS ledger_analytics.tax_deduction_events (
    event_id UUID,
    user_id UInt64,
    transaction_date Date,
    category LowCardinality(String),
    amount_cents Int64,
    deductible_cents Int64,
    business_use_percent UInt8,
    deduction_type LowCardinality(String),
    limitation_type LowCardinality(String),
    created_at DateTime DEFAULT now()
) ENGINE = MergeTree()
PARTITION BY toYYYYMM(transaction_date)
ORDER BY (user_id, category, transaction_date, event_id);

-- 2. Monthly Deduction Summary (Aggregating Engine)
CREATE TABLE IF NOT EXISTS ledger_analytics.monthly_deduction_rollups (
    user_id UInt64,
    month Date,
    category LowCardinality(String),
    total_spend_cents SimpleAggregateFunction(sum, Int64),
    total_deductible_cents SimpleAggregateFunction(sum, Int64),
    transaction_count SimpleAggregateFunction(sum, UInt64)
) ENGINE = AggregatingMergeTree()
PARTITION BY toYear(month)
ORDER BY (user_id, category, month);

-- 3. Materialized View feeding Monthly Rollups from Raw Events
CREATE MATERIALIZED VIEW IF NOT EXISTS ledger_analytics.mv_monthly_deductions
TO ledger_analytics.monthly_deduction_rollups AS
SELECT
    user_id,
    toStartOfMonth(transaction_date) AS month,
    category,
    sum(amount_cents) AS total_spend_cents,
    sum(deductible_cents) AS total_deductible_cents,
    count() AS transaction_count
FROM ledger_analytics.tax_deduction_events
GROUP BY user_id, month, category;

-- 4. Capital Asset Depreciation Projections
CREATE TABLE IF NOT EXISTS ledger_analytics.depreciation_forecasts (
    user_id UInt64,
    asset_id UInt64,
    tax_year UInt16,
    method LowCardinality(String),
    depreciation_cents Int64,
    accumulated_depreciation_cents Int64,
    book_value_cents Int64,
    calculated_at DateTime DEFAULT now()
) ENGINE = ReplacingMergeTree(calculated_at)
ORDER BY (user_id, asset_id, tax_year);
