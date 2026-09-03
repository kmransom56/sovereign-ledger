"""Capital asset and depreciation tracking (Step 13, Phase 1).

Immutable value objects for tracking depreciable business assets,
calculating depreciation using various methods (MACRS, straight-line,
Section 179, bonus depreciation), and managing asset pools.

Locked decisions honored:

* D-3: Money as signed integer USD cents; all depreciation in cents
* HR-1: Append-only; depreciation schedules computed from asset data, never mutated
* CK-5/CK-6: Validation at creation time (frozen dataclasses with __post_init__)
* T-10: Depreciation deferred until asset placed in service (not purchase)
* T-11: Depreciation limited by cost basis and applicable recovery periods

Purity contract (hard rule 1): standard library only; no I/O of any kind,
no clock reads, no randomness.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Iterable

__all__ = [
    "AssetType",
    "DepreciationMethod",
    "CapitalAsset",
    "AssetPool",
    "DepreciationSchedule",
    "DepreciationYear",
    "AssetError",
    "calculate_macrs_depreciation",
    "calculate_straight_line_depreciation",
    "calculate_section_179_deduction",
    "calculate_bonus_depreciation",
    "create_depreciation_schedule",
]


class AssetError(ValueError):
    """Base error for capital asset operations."""


class AssetType(Enum):
    """IRS asset categories for depreciation classification."""

    COMPUTER_EQUIPMENT = "computer_equipment"  # 5-year MACRS
    FURNITURE_FIXTURES = "furniture_fixtures"  # 7-year MACRS
    MACHINERY_EQUIPMENT = "machinery_equipment"  # 5-7 year MACRS
    VEHICLES = "vehicles"  # 5-year MACRS
    REAL_PROPERTY = "real_property"  # 27.5-year (residential) or 39-year (commercial)
    LAND = "land"  # Non-depreciable
    LEASEHOLD_IMPROVEMENTS = "leasehold_improvements"  # 15-year MACRS
    INTANGIBLE_ASSETS = "intangible_assets"  # 15-year straight-line
    OTHER = "other"  # 7-year MACRS (default)


class DepreciationMethod(Enum):
    """Depreciation calculation method."""

    MACRS_200DB = "macrs_200db"  # 200% declining balance (MACRS standard)
    MACRS_150DB = "macrs_150db"  # 150% declining balance
    STRAIGHT_LINE = "straight_line"  # Straight-line (alternate depreciation)
    SECTION_179 = "section_179"  # Full deduction in year placed in service
    BONUS_DEPRECIATION = "bonus_depreciation"  # 100% bonus in year placed in service


@dataclass(frozen=True)
class CapitalAsset:
    """A depreciable business capital asset.

    Represents a fixed asset eligible for depreciation, tracking
    acquisition cost, date placed in service, and depreciation method.
    """

    asset_id: int
    description: str
    asset_type: AssetType
    cost_basis_cents: int  # Full acquisition cost (in cents)
    salvage_value_cents: int = 0  # Estimated salvage value (usually 0 for MACRS)
    date_placed_in_service: date = date.today()
    depreciable_basis_cents: int = 0  # cost_basis - salvage_value
    useful_life_years: int = 0  # MACRS recovery period in years
    depreciation_method: DepreciationMethod = DepreciationMethod.MACRS_200DB
    notes: str | None = None
    vendor_name: str | None = None
    invoice_date: date | None = None
    invoice_number: str | None = None

    def __post_init__(self) -> None:
        if not self.description or not self.description.strip():
            raise AssetError("Asset description is required")
        if self.cost_basis_cents <= 0:
            raise AssetError("Cost basis must be positive")
        if self.salvage_value_cents < 0:
            raise AssetError("Salvage value must be non-negative")
        if self.salvage_value_cents >= self.cost_basis_cents:
            raise AssetError("Salvage value must be less than cost basis")
        if self.useful_life_years < 0:
            raise AssetError("Useful life must be non-negative")

    def depreciable_basis(self) -> int:
        """Calculate depreciable basis (cost - salvage value)."""
        return self.cost_basis_cents - self.salvage_value_cents


@dataclass(frozen=True)
class DepreciationYear:
    """Depreciation for a single year."""

    year: int
    depreciation_cents: int
    accumulated_depreciation_cents: int  # Cumulative through this year
    book_value_cents: int  # Cost basis - accumulated depreciation

    def __post_init__(self) -> None:
        if self.depreciation_cents < 0:
            raise AssetError("Depreciation must be non-negative")
        if self.accumulated_depreciation_cents < 0:
            raise AssetError("Accumulated depreciation must be non-negative")
        if self.book_value_cents < 0:
            raise AssetError("Book value must be non-negative")


@dataclass(frozen=True)
class DepreciationSchedule:
    """Complete depreciation schedule for an asset.

    Shows depreciation by year from placement in service until
    fully depreciated, with accumulated depreciation and book value.
    """

    asset_id: int
    description: str
    cost_basis_cents: int
    depreciable_basis_cents: int
    depreciation_method: DepreciationMethod
    date_placed_in_service: date
    useful_life_years: int
    total_depreciation_years: int
    years: list[DepreciationYear]
    total_depreciation_cents: int

    def __post_init__(self) -> None:
        if self.cost_basis_cents <= 0:
            raise AssetError("Cost basis must be positive")
        if self.depreciable_basis_cents < 0:
            raise AssetError("Depreciable basis must be non-negative")
        if self.depreciable_basis_cents > self.cost_basis_cents:
            raise AssetError("Depreciable basis cannot exceed cost basis")
        if not self.years:
            raise AssetError("Depreciation schedule must have at least one year")
        if self.total_depreciation_years <= 0:
            raise AssetError("Total depreciation years must be positive")
        if self.total_depreciation_cents < 0:
            raise AssetError("Total depreciation must be non-negative")

        # Verify depreciation years are sequential
        for i, dep_year in enumerate(self.years):
            if i > 0:
                if dep_year.year != self.years[i - 1].year + 1:
                    raise AssetError("Depreciation years must be sequential")
            if dep_year.accumulated_depreciation_cents > self.depreciable_basis_cents:
                raise AssetError(
                    f"Accumulated depreciation ({dep_year.accumulated_depreciation_cents}) "
                    f"exceeds depreciable basis ({self.depreciable_basis_cents})"
                )


@dataclass(frozen=True)
class AssetPool:
    """A pool of similar assets for combined depreciation reporting.

    Groups assets of same type and vintage for simplified depreciation
    calculation and reporting.
    """

    pool_id: int
    pool_name: str
    asset_type: AssetType
    date_placed_in_service: date
    total_cost_basis_cents: int
    total_depreciable_basis_cents: int
    asset_count: int
    depreciation_method: DepreciationMethod
    useful_life_years: int
    depreciation_schedule: DepreciationSchedule

    def __post_init__(self) -> None:
        if not self.pool_name or not self.pool_name.strip():
            raise AssetError("Pool name is required")
        if self.total_cost_basis_cents <= 0:
            raise AssetError("Total cost basis must be positive")
        if self.total_depreciable_basis_cents < 0:
            raise AssetError("Total depreciable basis must be non-negative")
        if self.asset_count <= 0:
            raise AssetError("Asset count must be positive")
        if self.useful_life_years <= 0:
            raise AssetError("Useful life must be positive")


def calculate_macrs_depreciation(
    cost_basis_cents: int,
    recovery_period_years: int,
    year_number: int,
    half_year_convention: bool = True,
) -> int:
    """Calculate MACRS (Modified Accelerated Cost Recovery System) depreciation.

    Uses 200% declining balance switching to straight-line, with half-year
    or mid-quarter convention.

    Args:
        cost_basis_cents: Asset cost basis in cents
        recovery_period_years: MACRS recovery period (3, 5, 7, 10, 15, 20, 27.5, 39)
        year_number: Year of depreciation (1-indexed)
        half_year_convention: If True, assumes half-year; else mid-quarter

    Returns:
        Depreciation amount in cents for the year
    """
    if cost_basis_cents <= 0:
        raise AssetError("Cost basis must be positive")
    if recovery_period_years <= 0:
        raise AssetError("Recovery period must be positive")
    if year_number < 1:
        raise AssetError("Year number must be >= 1")

    # MACRS rates by recovery period and year (IRS tables, simplified)
    # These are 200% DB switching to SL percentages
    macrs_rates = {
        3: [0.3333, 0.4445, 0.1481, 0.0741],
        5: [0.2000, 0.3200, 0.1920, 0.1152, 0.1152, 0.0576],
        7: [0.1429, 0.2449, 0.1749, 0.1249, 0.0893, 0.0892, 0.0893, 0.0446],
        10: [0.1000, 0.1800, 0.1440, 0.1152, 0.0922, 0.0737, 0.0655, 0.0655, 0.0656, 0.0328],
        15: [0.0500, 0.0950, 0.0855, 0.0770, 0.0693, 0.0623, 0.0590, 0.0590, 0.0591, 0.0590,
             0.0591, 0.0590, 0.0591, 0.0590, 0.0591, 0.0295],
        20: [0.0375, 0.0722, 0.0668, 0.0618, 0.0571, 0.0528, 0.0489, 0.0447, 0.0447, 0.0447,
             0.0447, 0.0448, 0.0447, 0.0448, 0.0447, 0.0448, 0.0447, 0.0448, 0.0447, 0.0448, 0.0224],
    }

    # For real property (27.5 and 39 years), use straight-line
    if recovery_period_years in (27.5, 39):
        annual_rate = 1.0 / recovery_period_years
        if half_year_convention and year_number == 1:
            annual_rate = annual_rate / 2
        elif half_year_convention and year_number == recovery_period_years + 1:
            annual_rate = annual_rate / 2
        return int(cost_basis_cents * annual_rate)

    # For personal property, use MACRS table
    if recovery_period_years not in macrs_rates:
        # Default to 7-year if not found
        recovery_period_years = 7

    rates = macrs_rates[recovery_period_years]
    if year_number > len(rates):
        return 0  # Asset fully depreciated

    rate = rates[year_number - 1]
    return int(cost_basis_cents * rate)


def calculate_straight_line_depreciation(
    cost_basis_cents: int,
    salvage_value_cents: int,
    useful_life_years: int,
    year_number: int,
    half_year_convention: bool = True,
) -> int:
    """Calculate straight-line depreciation.

    Equal depreciation each year: (Cost - Salvage) / Useful Life

    Args:
        cost_basis_cents: Asset cost in cents
        salvage_value_cents: Estimated salvage value
        useful_life_years: Useful life in years
        year_number: Year of depreciation (1-indexed)
        half_year_convention: If True, half depreciation in year 1 and last year

    Returns:
        Depreciation amount in cents for the year
    """
    if cost_basis_cents <= 0:
        raise AssetError("Cost basis must be positive")
    if salvage_value_cents < 0:
        raise AssetError("Salvage value must be non-negative")
    if useful_life_years <= 0:
        raise AssetError("Useful life must be positive")
    if year_number < 1:
        raise AssetError("Year number must be >= 1")

    depreciable_basis = cost_basis_cents - salvage_value_cents
    annual_depreciation = int(depreciable_basis / useful_life_years)

    # Half-year convention
    if half_year_convention:
        if year_number == 1 or year_number == useful_life_years + 1:
            return annual_depreciation // 2

    if year_number > useful_life_years:
        return 0  # Asset fully depreciated

    return annual_depreciation


def calculate_section_179_deduction(
    cost_basis_cents: int,
    cumulative_179_cents: int,
    annual_limit_cents: int = 1160000 * 100,  # 2024 limit in cents
    taxable_income_cents: int = 0,
) -> int:
    """Calculate Section 179 expensing deduction.

    Section 179 allows expensing up to annual limit in year placed in service,
    limited by cumulative investments and taxable income.

    Args:
        cost_basis_cents: Asset cost basis
        cumulative_179_cents: Total Section 179 deductions already taken this year
        annual_limit_cents: Current year limit (default 2024: $1,160,000)
        taxable_income_cents: Taxable income (optional limitation)

    Returns:
        Section 179 deduction amount in cents
    """
    if cost_basis_cents <= 0:
        raise AssetError("Cost basis must be positive")
    if cumulative_179_cents < 0:
        raise AssetError("Cumulative 179 must be non-negative")
    if annual_limit_cents <= 0:
        raise AssetError("Annual limit must be positive")

    # Available 179 for this asset
    available = annual_limit_cents - cumulative_179_cents
    deduction = min(cost_basis_cents, available)

    # Limited by taxable income if provided
    if taxable_income_cents > 0:
        deduction = min(deduction, taxable_income_cents)

    return max(0, deduction)


def calculate_bonus_depreciation(
    cost_basis_cents: int,
    percentage: float = 1.0,
    qualified: bool = True,
) -> int:
    """Calculate bonus depreciation (100% or percentage).

    In recent years, IRS allows bonus depreciation (often 100%) for
    qualified business property in the year placed in service.

    Args:
        cost_basis_cents: Asset cost basis
        percentage: Bonus percentage (0.0-1.0; 1.0 = 100%)
        qualified: Whether asset qualifies for bonus depreciation

    Returns:
        Bonus depreciation amount in cents
    """
    if cost_basis_cents <= 0:
        raise AssetError("Cost basis must be positive")
    if not (0 <= percentage <= 1.0):
        raise AssetError("Bonus percentage must be 0-1.0")

    if not qualified:
        return 0

    return int(cost_basis_cents * percentage)


def create_depreciation_schedule(
    asset_id: int,
    description: str,
    cost_basis_cents: int,
    salvage_value_cents: int,
    depreciation_method: DepreciationMethod,
    date_placed_in_service: date,
    recovery_period_years: int,
) -> DepreciationSchedule:
    """Create a complete depreciation schedule for an asset.

    Calculates year-by-year depreciation, accumulated depreciation,
    and book value using specified method.

    Args:
        asset_id: Unique asset identifier
        description: Asset description
        cost_basis_cents: Asset acquisition cost
        salvage_value_cents: Estimated salvage value
        depreciation_method: Method to use (MACRS, straight-line, etc.)
        date_placed_in_service: Date asset placed in service
        recovery_period_years: Useful life/recovery period

    Returns:
        DepreciationSchedule with year-by-year breakdown
    """
    if cost_basis_cents <= 0:
        raise AssetError("Cost basis must be positive")
    if recovery_period_years <= 0:
        raise AssetError("Recovery period must be positive")

    depreciable_basis = cost_basis_cents - salvage_value_cents

    years: list[DepreciationYear] = []
    accumulated_cents = 0
    year_count = recovery_period_years

    # Add extra year for half-year convention (MACRS and straight-line)
    if depreciation_method in (DepreciationMethod.MACRS_200DB, DepreciationMethod.MACRS_150DB, DepreciationMethod.STRAIGHT_LINE):
        year_count = recovery_period_years + 1

    for year_num in range(1, year_count + 1):
        if depreciation_method == DepreciationMethod.SECTION_179:
            # 100% in first year, nothing in others
            annual_depreciation = cost_basis_cents if year_num == 1 else 0
        elif depreciation_method == DepreciationMethod.BONUS_DEPRECIATION:
            # 100% in first year, nothing in others
            annual_depreciation = cost_basis_cents if year_num == 1 else 0
        elif depreciation_method in (DepreciationMethod.MACRS_200DB, DepreciationMethod.MACRS_150DB):
            annual_depreciation = calculate_macrs_depreciation(
                cost_basis_cents, recovery_period_years, year_num
            )
        else:  # STRAIGHT_LINE
            annual_depreciation = calculate_straight_line_depreciation(
                cost_basis_cents, salvage_value_cents, recovery_period_years, year_num
            )

        accumulated_cents += annual_depreciation
        # Cap accumulated depreciation at depreciable basis
        accumulated_cents = min(accumulated_cents, depreciable_basis)

        book_value = cost_basis_cents - accumulated_cents

        years.append(
            DepreciationYear(
                year=date_placed_in_service.year + year_num - 1,
                depreciation_cents=annual_depreciation,
                accumulated_depreciation_cents=accumulated_cents,
                book_value_cents=book_value,
            )
        )

        if accumulated_cents >= depreciable_basis:
            break  # Fully depreciated

    total_depreciation = sum(year.depreciation_cents for year in years)

    return DepreciationSchedule(
        asset_id=asset_id,
        description=description,
        cost_basis_cents=cost_basis_cents,
        depreciable_basis_cents=depreciable_basis,
        depreciation_method=depreciation_method,
        date_placed_in_service=date_placed_in_service,
        useful_life_years=recovery_period_years,
        total_depreciation_years=len(years),
        years=years,
        total_depreciation_cents=total_depreciation,
    )
