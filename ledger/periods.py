"""Fiscal-period state machine for the Sovereign Ledger (HR-6 core half).

A fiscal period is an accounting month carrying exactly one of three
statuses:

    open ──close──► closed ──lock──► locked

* ``open``   — postings dated inside the period are accepted.
* ``closed`` — postings are refused; corrections route through reversing
  entries dated in an OPEN period (CK-15).
* ``locked`` — terminal; nothing ever posts into it again.

Locked decisions honored here:

* HR-6 / T-6: posting into a closed or locked period is refused, and the
  refusal NAMES the period (see :func:`assert_postable`).
* Flow 6 (period close): periods close in fiscal order — closing a period
  while an earlier one is still open is refused (see :func:`close_period`).
* D-6 (trigger contract mirrored in core): the pure core decides the same
  refusals the storage boundary re-verifies; neither side allows what the
  other forbids.

Purity contract (hard rule 1): standard library only; no I/O of any kind,
no clock reads (periods and dates are supplied by the caller), no
randomness. ``scripts/check_boundaries.py`` fails the build if a forbidden
I/O token ever appears under ``ledger/``.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass, replace
from datetime import date
from enum import Enum
from typing import Iterable

__all__ = [
    "FiscalPeriod",
    "PeriodClosedError",
    "PeriodError",
    "PeriodSequenceError",
    "PeriodStatus",
    "PeriodTransitionError",
    "UnmappedDateError",
    "assert_postable",
    "close_period",
    "find_period",
    "lock_period",
    "monthly_periods",
    "transition_period",
]

#: Period names mirror ``fiscal_periods.name``: an accounting month 'YYYY-MM'.
_NAME_PATTERN = re.compile(r"\d{4}-\d{2}")


class PeriodError(ValueError):
    """Base class for fiscal-period domain errors."""


class PeriodTransitionError(PeriodError):
    """A status transition outside open→closed→locked was attempted."""


class PeriodSequenceError(PeriodError):
    """Periods close in fiscal order — an earlier period is still open."""


class PeriodClosedError(PeriodError):
    """Posting into a closed or locked period was refused (HR-6)."""


class UnmappedDateError(PeriodError):
    """No fiscal period covers the requested date."""


class PeriodStatus(Enum):
    """The three statuses the ``fiscal_periods.status`` CHECK allows (D-2)."""

    OPEN = "open"
    CLOSED = "closed"
    LOCKED = "locked"


_ALLOWED_TRANSITIONS: dict[PeriodStatus, tuple[PeriodStatus, ...]] = {
    PeriodStatus.OPEN: (PeriodStatus.CLOSED,),
    PeriodStatus.CLOSED: (PeriodStatus.LOCKED,),
    PeriodStatus.LOCKED: (),
}


@dataclass(frozen=True, slots=True)
class FiscalPeriod:
    """An accounting month — pure value object mirroring ``fiscal_periods``.

    Field mapping: ``name`` → ``name`` (UNIQUE, e.g. ``'2026-09'``);
    ``year`` → ``year``; ``start_date``/``end_date`` → the DATE columns;
    ``status`` → the ``open|closed|locked`` CHECK domain. The frozen
    dataclass encodes the append-only model (D-8): a status change is a
    NEW value the caller records — never a mutation of stored history.

    Structural rules mirror the storage contract: ``end_date >=
    start_date`` (the ``fiscal_periods_date_order`` CHECK) and a name
    consistent with ``year`` and the dates.
    """

    name: str
    year: int
    start_date: date
    end_date: date
    status: PeriodStatus = PeriodStatus.OPEN

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or _NAME_PATTERN.fullmatch(self.name) is None:
            raise ValueError("FiscalPeriod.name must look like 'YYYY-MM'")
        if isinstance(self.year, bool) or not isinstance(self.year, int):
            raise TypeError("FiscalPeriod.year must be an int")
        if type(self.start_date) is not date or type(self.end_date) is not date:
            raise TypeError("FiscalPeriod dates must be datetime.date (no datetime, no str)")
        if self.end_date < self.start_date:
            raise ValueError(
                f"fiscal period {self.name}: end_date {self.end_date.isoformat()} is before "
                f"start_date {self.start_date.isoformat()}"
            )
        if self.year != int(self.name[:4]) or self.year != self.start_date.year:
            raise ValueError(
                f"fiscal period {self.name}: year {self.year} disagrees with the name or start_date"
            )
        if int(self.name[5:7]) != self.start_date.month:
            raise ValueError(
                f"fiscal period {self.name}: name month {self.name[5:7]} does not match "
                f"start_date month {self.start_date.month:02d}"
            )
        if not isinstance(self.status, PeriodStatus):
            raise TypeError("FiscalPeriod.status must be a PeriodStatus")

    def covers(self, day: date) -> bool:
        """True when ``day`` falls inside this period (inclusive)."""
        if type(day) is not date:
            raise TypeError("covers() expects a datetime.date")
        return self.start_date <= day <= self.end_date


def transition_period(period: FiscalPeriod, target: PeriodStatus) -> FiscalPeriod:
    """Move ``period`` one step along open→closed→locked — nothing else.

    Locked is terminal: no transition leaves it, so history can never be
    rewritten through the status column (HR-2 in spirit at the calendar
    level).
    """
    if not isinstance(period, FiscalPeriod):
        raise TypeError(f"transition_period expects a FiscalPeriod; got {type(period).__name__}")
    if not isinstance(target, PeriodStatus):
        raise TypeError(f"transition_period target must be a PeriodStatus; got {type(target).__name__}")
    if target not in _ALLOWED_TRANSITIONS[period.status]:
        raise PeriodTransitionError(
            f"fiscal period {period.name}: {period.status.value} → {target.value} is not allowed "
            "(the only path is open → closed → locked, and locked is terminal)"
        )
    return replace(period, status=target)


def close_period(period: FiscalPeriod, all_periods: Iterable[FiscalPeriod] = ()) -> FiscalPeriod:
    """Close ``period`` — refused while an EARLIER period is still open.

    In-order enforcement (flow 6): closing out of order would freeze a
    later month while an earlier one still accepts postings, leaving a
    hole in the books — so the earliest still-open predecessor is named
    in the error. Pass the full calendar as ``all_periods``; with the
    default the caller has already asserted order.
    """
    if not isinstance(period, FiscalPeriod):
        raise TypeError(f"close_period expects a FiscalPeriod; got {type(period).__name__}")
    checked = list(all_periods)
    for other in checked:
        if not isinstance(other, FiscalPeriod):
            raise TypeError(
                f"all_periods must contain FiscalPeriod values; got {type(other).__name__}"
            )
    open_earlier = sorted(
        (
            other
            for other in checked
            if other.start_date < period.start_date and other.status is PeriodStatus.OPEN
        ),
        key=lambda other: (other.start_date, other.name),
    )
    if open_earlier:
        blocker = open_earlier[0]
        raise PeriodSequenceError(
            f"fiscal period {blocker.name} is still open; close it before {period.name} "
            "(periods close in fiscal order)"
        )
    return transition_period(period, PeriodStatus.CLOSED)


def lock_period(period: FiscalPeriod) -> FiscalPeriod:
    """Lock a CLOSED period — terminal; nothing ever posts into it again."""
    if not isinstance(period, FiscalPeriod):
        raise TypeError(f"lock_period expects a FiscalPeriod; got {type(period).__name__}")
    return transition_period(period, PeriodStatus.LOCKED)


def monthly_periods(year: int) -> tuple[FiscalPeriod, ...]:
    """The twelve calendar months of ``year``, all OPEN, in fiscal order."""
    if isinstance(year, bool) or not isinstance(year, int):
        raise TypeError(f"monthly_periods expects an int year; got {type(year).__name__}")
    periods: list[FiscalPeriod] = []
    for month in range(1, 13):
        last_day = calendar.monthrange(year, month)[1]
        periods.append(
            FiscalPeriod(
                name=f"{year:04d}-{month:02d}",
                year=year,
                start_date=date(year, month, 1),
                end_date=date(year, month, last_day),
            )
        )
    return tuple(periods)


def find_period(day: date, periods: Iterable[FiscalPeriod]) -> FiscalPeriod | None:
    """The period covering ``day``, or None when no period maps it."""
    if type(day) is not date:
        raise TypeError(f"find_period expects a datetime.date; got {type(day).__name__}")
    for period in periods:
        if period.covers(day):
            return period
    return None


def assert_postable(day: date, periods: Iterable[FiscalPeriod]) -> FiscalPeriod:
    """REFUSE any posting date not inside an OPEN period — and NAME it (HR-6).

    The refusal carries the period's name so the operator sees exactly
    which period is in the way::

        PeriodClosedError: fiscal period 2026-05 is closed; posting
        dated 2026-05-14 is refused (HR-6)

    Returns:
        The OPEN :class:`FiscalPeriod` covering ``day``.

    Raises:
        UnmappedDateError: no period covers ``day`` at all.
        PeriodClosedError: the covering period is closed or locked.
    """
    period = find_period(day, periods)
    if period is None:
        raise UnmappedDateError(
            f"no fiscal period covers {day.isoformat()}; create the period before posting"
        )
    if period.status is not PeriodStatus.OPEN:
        raise PeriodClosedError(
            f"fiscal period {period.name} is {period.status.value}; posting dated "
            f"{day.isoformat()} is refused (HR-6)"
        )
    return period