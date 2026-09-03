"""Tests for tax recommendations and compliance guidance (Step 13, Phase 5).

Tests recommendation generation: deduction opportunities, compliance
requirements, tax optimization strategies, and prioritization logic.
"""

from datetime import date

import pytest

from ledger.tax_recommendations import (
    RecommendationError,
    RecommendationPriority,
    RecommendationStatus,
    RecommendationType,
    TaxRecommendation,
    TaxRecommendationSet,
    generate_compliance_recommendations,
    generate_deduction_recommendations,
    generate_optimization_recommendations,
    prioritize_recommendations,
)


class TestTaxRecommendation:
    """Test tax recommendation creation and validation."""

    def test_valid_recommendation_with_tax_impact(self):
        """Create recommendation with tax impact."""
        rec = TaxRecommendation(
            recommendation_id="TEST-001",
            recommendation_type=RecommendationType.DEDUCTION_OPPORTUNITY,
            priority=RecommendationPriority.HIGH,
            title="Test Recommendation",
            description="This is a test recommendation",
            estimated_tax_impact_cents=50000,
        )

        assert rec.recommendation_id == "TEST-001"
        assert rec.title == "Test Recommendation"
        assert rec.status == RecommendationStatus.OPEN
        assert rec.total_impact_cents() == 50000

    def test_valid_recommendation_with_compliance_risk(self):
        """Create recommendation with compliance risk."""
        rec = TaxRecommendation(
            recommendation_id="COMP-001",
            recommendation_type=RecommendationType.COMPLIANCE_REQUIREMENT,
            priority=RecommendationPriority.CRITICAL,
            title="Compliance Requirement",
            description="Required filing",
            estimated_compliance_risk_cents=100000,
        )

        assert rec.total_impact_cents() == 100000

    def test_recommendation_with_both_impacts(self):
        """Recommendation with tax impact and compliance risk."""
        rec = TaxRecommendation(
            recommendation_id="BOTH-001",
            recommendation_type=RecommendationType.TAX_OPTIMIZATION,
            priority=RecommendationPriority.HIGH,
            title="Combined Impact",
            description="Both tax and compliance benefit",
            estimated_tax_impact_cents=75000,
            estimated_compliance_risk_cents=25000,
        )

        assert rec.total_impact_cents() == 100000

    def test_empty_id_raises_error(self):
        """Empty recommendation ID raises error."""
        with pytest.raises(RecommendationError):
            TaxRecommendation(
                recommendation_id="",
                recommendation_type=RecommendationType.DEDUCTION_OPPORTUNITY,
                priority=RecommendationPriority.HIGH,
                title="Test",
                description="Test",
                estimated_tax_impact_cents=1000,
            )

    def test_empty_title_raises_error(self):
        """Empty title raises error."""
        with pytest.raises(RecommendationError):
            TaxRecommendation(
                recommendation_id="TEST-001",
                recommendation_type=RecommendationType.DEDUCTION_OPPORTUNITY,
                priority=RecommendationPriority.HIGH,
                title="",
                description="Test",
                estimated_tax_impact_cents=1000,
            )

    def test_empty_description_raises_error(self):
        """Empty description raises error."""
        with pytest.raises(RecommendationError):
            TaxRecommendation(
                recommendation_id="TEST-001",
                recommendation_type=RecommendationType.DEDUCTION_OPPORTUNITY,
                priority=RecommendationPriority.HIGH,
                title="Test",
                description="",
                estimated_tax_impact_cents=1000,
            )

    def test_zero_impact_raises_error(self):
        """Zero tax impact and zero compliance risk raises error."""
        with pytest.raises(RecommendationError):
            TaxRecommendation(
                recommendation_id="TEST-001",
                recommendation_type=RecommendationType.DEDUCTION_OPPORTUNITY,
                priority=RecommendationPriority.HIGH,
                title="Test",
                description="Test",
                estimated_tax_impact_cents=0,
                estimated_compliance_risk_cents=0,
            )

    def test_with_deadline(self):
        """Recommendation with deadline."""
        deadline = date(2024, 12, 31)
        rec = TaxRecommendation(
            recommendation_id="DEADLINE-001",
            recommendation_type=RecommendationType.EXPENSE_TIMING,
            priority=RecommendationPriority.HIGH,
            title="Year-End Expenses",
            description="Timing for discretionary expenses",
            estimated_tax_impact_cents=25000,
            deadline=deadline,
        )

        assert rec.deadline == deadline


class TestGenerateDeductionRecommendations:
    """Test deduction opportunity recommendations."""

    def test_no_gap_no_recommendation(self):
        """No gap between actual and potential yields no recommendation."""
        recs = generate_deduction_recommendations(
            actual_deductions_cents=100000,
            potential_deductions_cents=100000,
        )

        assert len(recs) == 0

    def test_small_gap_medium_priority(self):
        """Small deduction gap (< $5k) gets medium priority."""
        recs = generate_deduction_recommendations(
            actual_deductions_cents=100000,
            potential_deductions_cents=104000,  # $40 gap
            marginal_tax_rate=0.24,
        )

        assert len(recs) == 1
        assert recs[0].recommendation_id == "DED-UNCLAIMED-001"
        assert recs[0].priority == RecommendationPriority.MEDIUM
        assert recs[0].estimated_tax_impact_cents == int(4000 * 0.24)

    def test_large_gap_high_priority(self):
        """Large deduction gap (> $5k) gets high priority."""
        recs = generate_deduction_recommendations(
            actual_deductions_cents=50000,
            potential_deductions_cents=606000,  # $556k gap
            marginal_tax_rate=0.24,
        )

        assert len(recs) == 1
        assert recs[0].priority == RecommendationPriority.HIGH
        assert recs[0].estimated_tax_impact_cents == int(556000 * 0.24)

    def test_tax_impact_calculation(self):
        """Tax impact = gap * marginal rate."""
        gap = 50000
        rate = 0.32

        recs = generate_deduction_recommendations(
            actual_deductions_cents=100000,
            potential_deductions_cents=150000,
            marginal_tax_rate=rate,
        )

        expected_impact = int(gap * rate)
        assert recs[0].estimated_tax_impact_cents == expected_impact

    def test_recommendation_details(self):
        """Recommendation includes required details."""
        recs = generate_deduction_recommendations(
            actual_deductions_cents=50000,
            potential_deductions_cents=100000,
        )

        rec = recs[0]
        assert rec.recommendation_type == RecommendationType.DEDUCTION_OPPORTUNITY
        assert "Unclaimed" in rec.title
        assert rec.implementation_effort == "medium"
        assert rec.timeline == "before year-end"
        assert rec.next_steps is not None
        assert len(rec.next_steps) > 0


class TestGenerateComplianceRecommendations:
    """Test compliance and documentation recommendations."""

    def test_estimated_tax_recommendation(self):
        """Estimated tax payment generates critical recommendation."""
        recs = generate_compliance_recommendations(has_estimated_tax=True)

        assert any(r.recommendation_id == "COMP-EST-TAX-001" for r in recs)
        est_rec = next(r for r in recs if r.recommendation_id == "COMP-EST-TAX-001")
        assert est_rec.priority == RecommendationPriority.CRITICAL
        assert est_rec.recommendation_type == RecommendationType.QUARTERLY_PLANNING

    def test_home_office_recommendation(self):
        """Home office generates documentation recommendation."""
        recs = generate_compliance_recommendations(has_home_office=True)

        assert any(r.recommendation_id == "COMP-HOME-OFF-001" for r in recs)
        home_rec = next(r for r in recs if r.recommendation_id == "COMP-HOME-OFF-001")
        assert home_rec.priority == RecommendationPriority.MEDIUM
        assert home_rec.recommendation_type == RecommendationType.DOCUMENTATION

    def test_vehicle_expense_recommendation(self):
        """Vehicle expenses generate documentation recommendation."""
        recs = generate_compliance_recommendations(has_vehicle_expenses=True)

        assert any(r.recommendation_id == "COMP-VEHICLE-001" for r in recs)
        veh_rec = next(r for r in recs if r.recommendation_id == "COMP-VEHICLE-001")
        assert veh_rec.priority == RecommendationPriority.HIGH
        assert veh_rec.estimated_compliance_risk_cents == 750000

    def test_self_employment_tax_recommendation(self):
        """Self-employment income generates tax reporting recommendation."""
        recs = generate_compliance_recommendations(has_self_employment_income=True)

        assert any(r.recommendation_id == "COMP-SE-TAX-001" for r in recs)
        se_rec = next(r for r in recs if r.recommendation_id == "COMP-SE-TAX-001")
        assert se_rec.priority == RecommendationPriority.CRITICAL
        assert se_rec.recommendation_type == RecommendationType.COMPLIANCE_REQUIREMENT

    def test_high_deduction_ratio_recommendation(self):
        """High deduction ratio (>50%) generates record-keeping recommendation."""
        recs = generate_compliance_recommendations(high_deduction_ratio=True)

        assert any(r.recommendation_id == "COMP-HIGH-DED-001" for r in recs)
        high_rec = next(r for r in recs if r.recommendation_id == "COMP-HIGH-DED-001")
        assert high_rec.priority == RecommendationPriority.MEDIUM
        assert high_rec.recommendation_type == RecommendationType.RECORD_KEEPING

    def test_multiple_compliance_issues(self):
        """Multiple compliance issues generate multiple recommendations."""
        recs = generate_compliance_recommendations(
            has_estimated_tax=True,
            has_home_office=True,
            has_vehicle_expenses=True,
            has_self_employment_income=True,
            high_deduction_ratio=True,
        )

        assert len(recs) == 5


class TestGenerateOptimizationRecommendations:
    """Test tax optimization strategy recommendations."""

    def test_expense_timing_recommendation(self):
        """Income generates expense timing strategy recommendation."""
        recs = generate_optimization_recommendations(
            business_income_cents=100000,
            current_deductions_cents=30000,
        )

        assert any(r.recommendation_id == "OPT-TIMING-001" for r in recs)
        timing_rec = next(r for r in recs if r.recommendation_id == "OPT-TIMING-001")
        assert timing_rec.recommendation_type == RecommendationType.EXPENSE_TIMING
        assert timing_rec.priority == RecommendationPriority.MEDIUM
        assert timing_rec.timeline == "in November/December"

    def test_loss_carryforward_recommendation(self):
        """Quarterly losses generate loss strategy recommendation."""
        recs = generate_optimization_recommendations(
            business_income_cents=100000,
            current_deductions_cents=30000,
            has_quarterly_losses=True,
        )

        assert any(r.recommendation_id == "OPT-LOSS-001" for r in recs)
        loss_rec = next(r for r in recs if r.recommendation_id == "OPT-LOSS-001")
        assert loss_rec.priority == RecommendationPriority.HIGH
        assert loss_rec.recommendation_type == RecommendationType.TAX_OPTIMIZATION

    def test_entity_structure_recommendation(self):
        """Entity structure review always included."""
        recs = generate_optimization_recommendations(
            business_income_cents=100000,
            current_deductions_cents=30000,
        )

        assert any(r.recommendation_id == "OPT-ENTITY-001" for r in recs)
        entity_rec = next(r for r in recs if r.recommendation_id == "OPT-ENTITY-001")
        assert entity_rec.priority == RecommendationPriority.LOW
        assert entity_rec.recommendation_type == RecommendationType.ENTITY_STRUCTURE

    def test_timing_impact_calculation(self):
        """Expense timing impact = income * 0.10 * marginal rate."""
        business_income = 500000
        recs = generate_optimization_recommendations(
            business_income_cents=business_income,
            current_deductions_cents=100000,
        )

        timing_rec = next(r for r in recs if r.recommendation_id == "OPT-TIMING-001")
        expected_impact = int(business_income * 0.10 * 0.24)
        assert timing_rec.estimated_tax_impact_cents == expected_impact

    def test_zero_income_no_timing_recommendation(self):
        """Zero business income results in no timing recommendation."""
        recs = generate_optimization_recommendations(
            business_income_cents=0,
            current_deductions_cents=0,
        )

        # Only entity structure should be present
        assert len(recs) == 1
        assert recs[0].recommendation_id == "OPT-ENTITY-001"


class TestPrioritizeRecommendations:
    """Test recommendation prioritization and sorting."""

    def test_sort_by_priority(self):
        """Recommendations sorted by priority (critical → low)."""
        recs = [
            TaxRecommendation(
                recommendation_id="LOW-001",
                recommendation_type=RecommendationType.DOCUMENTATION,
                priority=RecommendationPriority.LOW,
                title="Low Priority",
                description="Low priority recommendation",
                estimated_tax_impact_cents=1000,
            ),
            TaxRecommendation(
                recommendation_id="CRIT-001",
                recommendation_type=RecommendationType.COMPLIANCE_REQUIREMENT,
                priority=RecommendationPriority.CRITICAL,
                title="Critical Issue",
                description="Critical recommendation",
                estimated_tax_impact_cents=100000,
            ),
            TaxRecommendation(
                recommendation_id="MED-001",
                recommendation_type=RecommendationType.TAX_OPTIMIZATION,
                priority=RecommendationPriority.MEDIUM,
                title="Medium Priority",
                description="Medium recommendation",
                estimated_tax_impact_cents=10000,
            ),
        ]

        sorted_recs = prioritize_recommendations(recs)

        assert sorted_recs[0].priority == RecommendationPriority.CRITICAL
        assert sorted_recs[1].priority == RecommendationPriority.MEDIUM
        assert sorted_recs[2].priority == RecommendationPriority.LOW

    def test_sort_by_impact_within_priority(self):
        """Within same priority, sort by impact (highest first)."""
        recs = [
            TaxRecommendation(
                recommendation_id="HIGH-SMALL",
                recommendation_type=RecommendationType.DEDUCTION_OPPORTUNITY,
                priority=RecommendationPriority.HIGH,
                title="Small Impact",
                description="Small impact recommendation",
                estimated_tax_impact_cents=5000,
            ),
            TaxRecommendation(
                recommendation_id="HIGH-LARGE",
                recommendation_type=RecommendationType.DEDUCTION_OPPORTUNITY,
                priority=RecommendationPriority.HIGH,
                title="Large Impact",
                description="Large impact recommendation",
                estimated_tax_impact_cents=50000,
            ),
            TaxRecommendation(
                recommendation_id="HIGH-MED",
                recommendation_type=RecommendationType.DEDUCTION_OPPORTUNITY,
                priority=RecommendationPriority.HIGH,
                title="Medium Impact",
                description="Medium impact recommendation",
                estimated_tax_impact_cents=25000,
            ),
        ]

        sorted_recs = prioritize_recommendations(recs)

        assert sorted_recs[0].estimated_tax_impact_cents == 50000
        assert sorted_recs[1].estimated_tax_impact_cents == 25000
        assert sorted_recs[2].estimated_tax_impact_cents == 5000

    def test_total_impact_includes_compliance_risk(self):
        """Sorting uses total_impact (tax + compliance risk)."""
        recs = [
            TaxRecommendation(
                recommendation_id="TAX-ONLY",
                recommendation_type=RecommendationType.DEDUCTION_OPPORTUNITY,
                priority=RecommendationPriority.HIGH,
                title="Tax Impact Only",
                description="Tax only",
                estimated_tax_impact_cents=30000,
                estimated_compliance_risk_cents=0,
            ),
            TaxRecommendation(
                recommendation_id="COMP-ONLY",
                recommendation_type=RecommendationType.COMPLIANCE_REQUIREMENT,
                priority=RecommendationPriority.HIGH,
                title="Compliance Risk Only",
                description="Compliance only",
                estimated_tax_impact_cents=0,
                estimated_compliance_risk_cents=50000,
            ),
        ]

        sorted_recs = prioritize_recommendations(recs)

        # Compliance-only (50k total) should come before tax-only (30k total)
        assert sorted_recs[0].recommendation_id == "COMP-ONLY"
        assert sorted_recs[1].recommendation_id == "TAX-ONLY"

    def test_empty_list(self):
        """Empty recommendation list returns empty."""
        sorted_recs = prioritize_recommendations([])
        assert len(sorted_recs) == 0

    def test_single_recommendation(self):
        """Single recommendation returns single recommendation."""
        rec = TaxRecommendation(
            recommendation_id="SINGLE-001",
            recommendation_type=RecommendationType.DEDUCTION_OPPORTUNITY,
            priority=RecommendationPriority.HIGH,
            title="Single Recommendation",
            description="Only recommendation",
            estimated_tax_impact_cents=1000,
        )

        sorted_recs = prioritize_recommendations([rec])
        assert len(sorted_recs) == 1
        assert sorted_recs[0].recommendation_id == "SINGLE-001"


class TestTaxRecommendationSet:
    """Test recommendation set creation and aggregation."""

    def test_valid_recommendation_set(self):
        """Create valid recommendation set."""
        recs = [
            TaxRecommendation(
                recommendation_id="REC-1",
                recommendation_type=RecommendationType.DEDUCTION_OPPORTUNITY,
                priority=RecommendationPriority.HIGH,
                title="Recommendation 1",
                description="First recommendation",
                estimated_tax_impact_cents=50000,
            ),
        ]

        rec_set = TaxRecommendationSet(
            period_start=date(2024, 1, 1),
            period_end=date(2024, 12, 31),
            total_potential_tax_savings_cents=50000,
            total_compliance_risk_cents=0,
            recommendations=recs,
        )

        assert rec_set.total_potential_tax_savings_cents == 50000
        assert len(rec_set.recommendations) == 1

    def test_invalid_period_order(self):
        """Period end before start raises error."""
        rec = TaxRecommendation(
            recommendation_id="TEST-001",
            recommendation_type=RecommendationType.DEDUCTION_OPPORTUNITY,
            priority=RecommendationPriority.HIGH,
            title="Test",
            description="Test",
            estimated_tax_impact_cents=1000,
        )

        with pytest.raises(RecommendationError):
            TaxRecommendationSet(
                period_start=date(2024, 12, 31),
                period_end=date(2024, 1, 1),
                total_potential_tax_savings_cents=1000,
                total_compliance_risk_cents=0,
                recommendations=[rec],
            )

    def test_empty_recommendations_raises_error(self):
        """Empty recommendations list raises error."""
        with pytest.raises(RecommendationError):
            TaxRecommendationSet(
                period_start=date(2024, 1, 1),
                period_end=date(2024, 12, 31),
                total_potential_tax_savings_cents=0,
                total_compliance_risk_cents=0,
                recommendations=[],
            )
