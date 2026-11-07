"""Runway and shock engine. Pure functions, no I/O, so they are easy to test.

Runway (track README definition):
    buffer_left = B - one_off_costs
    gap         = spending_after_shock - income_after_shock
    if buffer_left <= 0:  runway = 0
    elif gap <= 0:        runway = "no shortfall (120+)"
    else:                 runway = min(buffer_left / gap, 120)
rounded to 1 decimal.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

import numpy as np
import pandas as pd

NO_SHORTFALL = "no shortfall (120+)"
RUNWAY_CAP = 120.0

# Government of Canada: 2026 maximum weekly EI regular benefit is $729
# (55% of maximum insurable earnings of $68,900). Optional, off by default.
EI_MAX_WEEKLY_2026 = 729.0
EI_MAX_MONTHLY_2026 = EI_MAX_WEEKLY_2026 * 52 / 12  # ~ $3,159


def runway(buffer: float, one_off_costs: float, spending: float, income: float) -> float | str:
    """Months the buffer lasts. Returns a float (0..120, 1 decimal) or NO_SHORTFALL."""
    buffer_left = buffer - one_off_costs
    gap = spending - income
    if buffer_left <= 0:
        return 0.0
    if gap <= 0:
        return NO_SHORTFALL
    return round(min(buffer_left / gap, RUNWAY_CAP), 1)


def runway_number(r: float | str) -> float:
    """Numeric version for charts and ranking: NO_SHORTFALL counts as the 120 cap."""
    return RUNWAY_CAP if isinstance(r, str) else float(r)


def format_runway(r: float | str) -> str:
    if isinstance(r, str):
        return "No shortfall (120+)"
    if r >= RUNWAY_CAP:
        return "120+ months"
    return f"{r:.1f} months"


@dataclass(frozen=True)
class Profile:
    """One customer's typical month (all CAD)."""
    I: float                 # typical monthly money in
    S: float                 # typical monthly spending (money out)
    H: float                 # typical household bills
    F: float                 # typical fixed costs (bills + insurance + loan payments)
    B: float                 # savings buffer
    P: float = 0.0           # running loan monthly payment
    account_id: int | None = None
    n_months: int | None = None
    band: int | None = None
    extras: dict = field(default_factory=dict, compare=False)

    @property
    def flexible(self) -> float:
        """Spending that is not a fixed cost (cash, card, other transfers, fees)."""
        return max(self.S - self.F, 0.0)

    @classmethod
    def from_row(cls, account_id: int, row: pd.Series) -> "Profile":
        return cls(I=float(row["I"]), S=float(row["S"]), H=float(row["H"]), F=float(row["F"]),
                   B=float(row["B"]), P=float(row["P"]), account_id=int(account_id),
                   n_months=int(row["n_months"]), band=int(row["band"]))


@dataclass(frozen=True)
class Shock:
    job_loss: bool = False
    ei_rate: float = 0.55           # share of usual income replaced while out of work
    ei_cap: bool = False            # apply the 2026 EI weekly maximum
    bills_up: float = 0.0           # household bills increase, e.g. 0.15 = +15%
    one_off_months: float = 0.0     # surprise cost in months of typical spending (1.0 = S)
    one_off_dollars: float = 0.0    # plus a fixed-dollar surprise cost
    duration: int = 6               # months the shock lasts (the "do they make it" horizon)

    @property
    def is_none(self) -> bool:
        return not self.job_loss and self.bills_up == 0 and self.one_off_months == 0 and self.one_off_dollars == 0


@dataclass(frozen=True)
class ShockResult:
    income: float
    spending: float
    one_off: float
    buffer_left: float
    gap: float
    runway: float | str
    makes_it: bool


def shocked_income(I: float, shock: Shock) -> float:
    if not shock.job_loss:
        return I
    inc = shock.ei_rate * I
    if shock.ei_cap:
        inc = min(inc, EI_MAX_MONTHLY_2026)
    return inc


def apply_shock(p: Profile, shock: Shock) -> ShockResult:
    income = shocked_income(p.I, shock)
    spending = p.S + shock.bills_up * p.H
    one_off = shock.one_off_months * p.S + shock.one_off_dollars
    r = runway(p.B, one_off, spending, income)
    return ShockResult(income=income, spending=spending, one_off=one_off,
                       buffer_left=p.B - one_off, gap=spending - income, runway=r,
                       makes_it=runway_number(r) >= shock.duration)


def runway_vector(B, S, H, I, shock: Shock) -> np.ndarray:
    """Vectorised runway (numeric, NO_SHORTFALL -> 120) for many accounts at once."""
    B, S, H, I = (np.asarray(x, dtype=float) for x in (B, S, H, I))
    income = shock.ei_rate * I if shock.job_loss else I
    if shock.job_loss and shock.ei_cap:
        income = np.minimum(income, EI_MAX_MONTHLY_2026)
    spending = S + shock.bills_up * H
    left = B - (shock.one_off_months * S + shock.one_off_dollars)
    gap = spending - income
    with np.errstate(divide="ignore", invalid="ignore"):
        r = np.where(gap > 0, np.minimum(left / gap, RUNWAY_CAP), RUNWAY_CAP)
    r = np.where(left <= 0, 0.0, r)
    return np.round(r, 1)


# One-click presets that match the example twist cards
NO_SHOCK = Shock()
PRESETS: dict[str, Shock] = {
    "No shock": NO_SHOCK,
    "Laid off: EI 55% for 6 months": Shock(job_loss=True, ei_rate=0.55, duration=6),
    "Furnace dies: 1 month of spending": Shock(one_off_months=1.0),
    "Job loss + bills up 15%": Shock(job_loss=True, ei_rate=0.55, bills_up=0.15, duration=6),
    "Rent and bills up 15%": Shock(bills_up=0.15),
    "Perfect storm: all three": Shock(job_loss=True, ei_rate=0.55, bills_up=0.15,
                                                           one_off_months=1.0, duration=6),
}


def with_changes(shock: Shock, **kw) -> Shock:
    return replace(shock, **kw)
