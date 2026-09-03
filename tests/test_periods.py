"""Fiscal-period state machine suite (HR-6 / T-6 core half).

Covers the state machine exhaustively: allowed transitions
(open→closed→locked), every refused transition (open→locked, closed→open,
locked→anything), in-order close enforcement with the blocker period
named in the error, and ``assert_postable`` refusing closed, locked and
unmapped dates with the period NAMED (HR-6's operator-facing contract).

The May-closed/July-open calendar used here is the same scenario the
reversal tests (CK-15) and Step-2 DB tests (T-6/T-7) pin.

Purity (hard rule 1): no I/O, no clock reads — every date and calendar
is constructed in the test.
"""

from __future__ import annotations

from datetime import date

import pytest

from ledger.periods import (
    FiscalPeriod,
    PeriodClosedError,
    PeriodError,
    PeriodSequenceError,
    PeriodStatus,
    PeriodTransitionError,
    UnmappedDateError,
    assert_postable,
    close_period,
    find_period,
    lock_period,
    monthly_periods,
    transition_period,
)


def may_closed_july_open() -> list[FiscalPeriod]:
    """The CK-15 calendar: 2026 with January..May closed, June+ open."""
    cal = list(monthly_periods(2026))
    for i in range(5):
        cal[i] = close_period(cal[i], cal)
    return cal


# ---------------------------------------------------------------------------
# FiscalPeriod value object
# ---------------------------------------------------------------------------


def test_fiscal_period_defaults_and_shape() -> None:
    period = FiscalPeriod("2026-05", 2026, date(2026, 5, 1), date(2026, 5, 31))
    assert period.status is PeriodStatus.OPEN  # storage DEFAULT 'open'
    assert period.covers(date(2026, 5, 1)) and period.covers(date(2026, 5, 31))
    assert period.covers(date(2026, 5, 15))
    assert not period.covers(date(2026, 4, 30)) and not period.covers(date(2026, 6, 1))
    assert period.covers(date(2026, 5, 15)) is True


def test_fiscal_period_rejects_garbage() -> None:
    with pytest.raises(ValueError):
        FiscalPeriod("2026-5", 2026, date(2026, 5, 1), date(2026, 5, 31))  # bad name shape
    with pytest.raises(ValueError):
        FiscalPeriod("May-2026", 2026, date(2026, 5, 1), date(2026, 5, 31))
    with pytest.raises(TypeError):
        FiscalPeriod("2026-05", "2026", date(2026, 5, 1), date(2026, 5, 31))
    with pytest.raises(TypeError):
        FiscalPeriod("2026-05", 2026, "2026-05-01", date(2026, 5, 31))
    with pytest.raises(TypeError):
        FiscalPeriod("2026-05", 2026, date(2026, 5, 1, ), None)
    # fiscal_periods_date_order CHECK: end before start is refused
    with pytest.raises(ValueError):
        FiscalPeriod("2026-05", 2026, date(2026, 5, 31), date(2026, 5, 1))
    with pytest.raises(ValueError):
        FiscalPeriod("2026-05", 2025, date(2026, 5, 1), date(2026, 5, 31))  # year mismatch
    with pytest.raises(ValueError):
        FiscalPeriod("2026-06", 2026, date(2026, 5, 1), date(2026, 5, 31))  # month mismatch
    with pytest.raises(TypeError):
        FiscalPeriod("2026-05", 2026, date(2026, 5, 1), date(2026, 5, 31), status="open")
    with pytest.raises(TypeError):
        FiscalPeriod("2026-05", 2026, date(2026, 5, 1), date(2026, 5, 31), status=1)


def test_covers_rejects_non_date() -> None:
    period = FiscalPeriod("2026-05", 2026, date(2026, 5, 1), date(2026, 5, 31))
    with pytest.raises(TypeError):
        period.covers("2026-05-01")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        find_period("2026-05-01", [period])  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Transition state machine: open → closed → locked, nothing else
# ---------------------------------------------------------------------------


def test_allowed_transitions() -> None:
    period = FiscalPeriod("2026-05", 2026, date(2026, 5, 1), date(2026, 5, 31))
    closed = transition_period(period, PeriodStatus.CLOSED)
    assert closed.status is PeriodStatus.CLOSED
    assert period.status is PeriodStatus.OPEN  # original untouched (frozen value)
    locked = lock_period(closed)
    assert locked.status is PeriodStatus.LOCKED


def test_close_and_lock_require_correct_prior_state() -> None:
    period = FiscalPeriod("2026-05", 2026, date(2026, 5, 1), date(2026, 5, 31))
    with pytest.raises(PeriodTransitionError, match="not allowed"):
        lock_period(period)  # open → locked is refused
    closed = close_period(period)
    with pytest.raises(PeriodTransitionError, match="not allowed"):
        transition_period(closed, PeriodStatus.OPEN)  # no reopening
    locked = lock_period(closed)
    with pytest.raises(PeriodTransitionError, match="not allowed"):
        transition_period(locked, PeriodStatus.CLOSED)  # locked is terminal
    with pytest.raises(PeriodTransitionError, match="not allowed"):
        transition_period(locked, PeriodStatus.LOCKED)  # no self-transition
    with pytest.raises(PeriodTransitionError, match="not allowed"):
        transition_period(locked, PeriodStatus.OPEN)


def test_transition_and_close_reject_garbage() -> None:
    period = FiscalPeriod("2026-05", 2026, date(2026, 5, 1), date(2026, 5, 31))
    with pytest.raises(TypeError):
        transition_period("2026-05", PeriodStatus.CLOSED)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        transition_period(period, "closed")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        close_period("2026-05")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        lock_period("2026-05")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        close_period(period, all_periods=["not-a-period"])  # type: ignore[list-item]


def test_error_hierarchy() -> None:
    assert issubclass(PeriodTransitionError, PeriodError)
    assert issubclass(PeriodSequenceError, PeriodError)
    assert issubclass(PeriodClosedError, PeriodError)
    assert issubclass(UnmappedDateError, PeriodError)
    assert issubclass(PeriodError, ValueError)


# ---------------------------------------------------------------------------
# In-order close enforcement (flow 6): the blocker period is named
# ---------------------------------------------------------------------------


def test_close_out_of_order_names_blocker() -> None:
    cal = monthly_periods(2026)
    june, july = cal[5], cal[6]
    with pytest.raises(PeriodSequenceError, match="2026-01 is still open"):
        close_period(july, cal)
    with pytest.raises(PeriodSequenceError, match="2026-01 is still open"):
        close_period(june, cal)


def test_close_in_order_succeeds() -> None:
    cal = list(monthly_periods(2026))
    for i in range(12):
        cal[i] = close_period(cal[i], cal)
    assert all(period.status is PeriodStatus.CLOSED for period in cal)


def test_close_with_no_calendar_context_closes() -> None:
    """The default skips sequence enforcement (caller pre-asserted order)."""
    period = FiscalPeriod("2026-05", 2026, date(2026, 5, 1), date(2026, 5, 31))
    assert close_period(period).status is PeriodStatus.CLOSED


def test_closed_predecessors_do_not_block() -> None:
    cal = list(monthly_periods(2026))
    cal[0] = close_period(cal[0], cal)
    cal[1] = close_period(cal[1], cal)  # predecessor closed → no blocker
    assert cal[1].status is PeriodStatus.CLOSED


def test_locked_earlier_periods_do_not_block() -> None:
    cal = list(monthly_periods(2026))
    cal[0] = lock_period(close_period(cal[0], cal))
    cal[1] = close_period(cal[1], cal)
    assert cal[1].status is PeriodStatus.CLOSED


def test_monthly_periods_twelve_months() -> None:
    cal = monthly_periods(2026)
    assert len(cal) == 12
    assert cal[0].name == "2026-01" and cal[11].name == "2026-12"
    assert cal[1].start_date == date(2026, 2, 1)
    assert cal[1].end_date == date(2026, 2, 28)
    assert cal[11].end_date == date(2026, 12, 31)
    with pytest.raises(TypeError):
        monthly_periods("2026")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# assert_postable: refuses with the period NAMED (HR-6 operator contract)
# ---------------------------------------------------------------------------


def test_assert_postable_open_period_returns_it() -> None:
    cal = may_closed_july_open()
    assert assert_postable(date(2026, 7, 3), cal) is cal[6]
    assert assert_postable(date(2026, 6, 30), cal) is cal[5]
    # Every closed period refuses with its name — nothing returns it.
    with pytest.raises(PeriodClosedError, match="2026-01 is closed"):
        assert_postable(date(2026, 1, 1), cal)


def test_assert_postable_refuses_closed_period_named() -> None:
    cal = may_closed_july_open()
    with pytest.raises(PeriodClosedError, match="2026-05 is closed.*2026-05-14"):
        assert_postable(date(2026, 5, 14), cal)
    with pytest.raises(PeriodClosedError, match="2026-01 is closed"):
        assert_postable(date(2026, 1, 31), cal)


def test_assert_postable_refuses_locked_period_named() -> None:
    cal = may_closed_july_open()
    cal[0] = lock_period(cal[0])
    with pytest.raises(PeriodClosedError, match="2026-01 is locked.*2026-01-15"):
        assert_postable(date(2026, 1, 15), cal)


def test_assert_postable_refuses_unmapped_date_named() -> None:
    cal = monthly_periods(2026)
    with pytest.raises(UnmappedDateError, match="no fiscal period covers 2027-03-03"):
        assert_postable(date(2027, 3, 3), cal)
    with pytest.raises(UnmappedDateError, match="create the period before posting"):
        assert_postable(date(2025, 12, 31), cal)


def test_find_period_maps_and_misses() -> None:
    cal = monthly_periods(2026)
    assert find_period(date(2026, 5, 14), cal) is cal[4]
    assert find_period(date(2027, 5, 14), cal) is None


def test_property_no_path_posts_into_closed_period() -> None:
    """The sub-task property: assert_postable refuses with the named period."""
    from hypothesis import given, settings
    from hypothesis import strategies as st

    cal = may_closed_july_open()
    closed_periods = {period.name for period in cal if period.status is not PeriodStatus.OPEN}

    @given(day=st.dates(min_value=date(2026, 1, 1), max_value=date(2026, 12, 31)))
    @settings(deadline=None, max_examples=120)
    def check(day: date) -> None:
        covering = find_period(day, cal)
        assert covering is not None
        if covering.name in closed_periods:
            with pytest.raises(PeriodClosedError, match=covering.name):
                assert_postable(day, cal)
        else:
            assert assert_postable(day, cal) is covering

    check()