"""Goal plan (build an emergency fund) and backup plan (if the shock hits).

Every number comes from the customer's own I, S, H, F, B, P and the chosen shock.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace

from .engine import Profile, Shock, ShockResult, apply_shock, runway, runway_number

FLEX_TRIM_GOAL = 0.10    # trim 10% of flexible spending to fund savings if no surplus
FLEX_TRIM_CRISIS = 0.25  # cut 25% of flexible spending in a crisis
SURPLUS_SAVE_SHARE = 0.5  # save half of the usual monthly surplus
SPREAD_MONTHS = 12        # spread a one-off bill over 12 instalments


@dataclass
class GoalPlan:
    target_months: int
    target: float
    have: float
    gap: float
    monthly_save: float
    months_to_goal: float | None   # None = already there; inf = not reachable as is
    source: str                     # where the monthly saving comes from
    steps: list[str]


def goal_plan(p: Profile, target_months: int = 3) -> GoalPlan:
    target = target_months * p.S
    have = max(p.B, 0.0)
    gap = max(target - have, 0.0)
    surplus = p.I - p.S
    steps: list[str] = []

    if gap <= 0:
        covered = have / p.S if p.S > 0 else float("inf")
        steps.append(f"Your buffer of ${have:,.0f} already covers {target_months} months of spending "
                     f"(${target:,.0f}). Keep it in a separate high-interest savings account.")
        if surplus > 0:
            steps.append(f"Next goal: 6 months (${6 * p.S:,.0f}). Saving half your usual surplus "
                         f"(${SURPLUS_SAVE_SHARE * surplus:,.0f}/month) gets you there in "
                         f"{_months(max(6 * p.S - have, 0), SURPLUS_SAVE_SHARE * surplus)}.")
        return GoalPlan(target_months, target, have, 0.0, 0.0, None, "already funded", steps)

    if surplus > 0:
        save = SURPLUS_SAVE_SHARE * surplus
        source = f"half of your usual surplus (you take in ${surplus:,.0f} more than you spend in a typical month)"
    else:
        save = FLEX_TRIM_GOAL * p.flexible
        source = (f"trimming 10% of flexible spending (cash, card and other transfers, "
                  f"${p.flexible:,.0f}/month), because you usually spend ${-surplus:,.0f} more than you take in")

    months = gap / save if save > 0 else math.inf
    steps.append(f"Target: {target_months} months of typical spending = ${target:,.0f}. "
                 f"You have ${have:,.0f}, so the gap is ${gap:,.0f}.")
    if save > 0:
        steps.append(f"Set an automatic transfer of ${save:,.0f} on payday, funded by {source}.")
        steps.append(f"At that pace you reach the goal in {_months(gap, save)}.")
        if gap > p.S > 0:
            steps.append(f"First milestone: one extra month of spending (${p.S:,.0f}) in {_months(p.S, save)}.")
    else:
        steps.append("There is no surplus and no flexible spending to trim: start with a small fixed "
                     "amount (e.g. $50/month) and review fixed costs and bills.")
    if p.P > 0:
        steps.append(f"Your loan costs ${p.P:,.0f}/month. Once it ends, redirect that payment to savings.")
    return GoalPlan(target_months, target, have, gap, save, months, source, steps)


@dataclass
class BackupStep:
    action: str
    detail: str
    runway: float | str
    gap: float = 0.0   # monthly shortfall after this step (spending - income)


@dataclass
class BackupPlan:
    survival_budget: float | None   # max monthly spending to last the shock duration
    cut_needed: float               # how much to cut from shocked spending to get there
    steps: list[BackupStep]
    final_runway: float | str


def backup_plan(p: Profile, shock: Shock, res: ShockResult) -> BackupPlan:
    """Ordered actions, each with the runway you'd have after doing it and all steps before it."""
    steps = [BackupStep("Do nothing", "Shocked numbers as they stand", res.runway, res.gap)]
    income, spending, one_off = res.income, res.spending, res.one_off

    # 1. Spread a big one-off over instalments (protects the buffer)
    if one_off > 0 and one_off > 0.25 * max(p.B, 0):
        monthly = one_off / SPREAD_MONTHS
        one_off, spending = 0.0, spending + monthly
        steps.append(BackupStep(
            "Spread the surprise bill",
            (f"Ask for a {SPREAD_MONTHS}-month payment plan: ${monthly:,.0f}/month instead of "
             f"${res.one_off:,.0f} up front")
            + (" (there are no savings to pay it, so it adds to the monthly shortfall)" if p.B <= 0 else ""),
            runway(p.B, one_off, spending, income), spending - income))

    # 2. Cut flexible spending
    cut = FLEX_TRIM_CRISIS * p.flexible
    if cut > 0:
        spending -= cut
        steps.append(BackupStep(
            f"Cut flexible spending by ${cut:,.0f}/month",
            f"25% less on cash, card and other transfers (flexible spending is ${p.flexible:,.0f}/month)",
            runway(p.B, one_off, spending, income), spending - income))

    # 3. Pause the loan payment
    if p.P > 0:
        spending -= p.P
        steps.append(BackupStep(
            "Ask the lender for a payment pause",
            f"Loan payment of ${p.P:,.0f}/month deferred while the shock lasts",
            runway(p.B, one_off, spending, income), spending - income))

    # 4. Negotiate the bill increase back down
    if shock.bills_up > 0 and p.H > 0:
        saved = shock.bills_up * p.H * 0.5
        spending -= saved
        steps.append(BackupStep(
            "Negotiate or switch providers",
            f"Win back half the bill increase: -${saved:,.0f}/month",
            runway(p.B, one_off, spending, income), spending - income))

    # Survival budget: spend at most this per month to last the whole shock window
    left = p.B - res.one_off
    if left > 0 and shock.duration > 0:
        budget = res.income + left / shock.duration
        cut_needed = max(res.spending - budget, 0.0)
    else:
        budget, cut_needed = None, max(res.spending - res.income, 0.0)
    return BackupPlan(budget, cut_needed, steps, steps[-1].runway)


def _months(amount: float, per_month: float) -> str:
    if per_month <= 0:
        return "never at this pace"
    m = math.ceil(amount / per_month)
    if m <= 1:
        return "about 1 month"
    if m > 120:
        return "more than 10 years"
    if m >= 24:
        return f"about {m / 12:.1f} years ({m} months)"
    return f"about {m} months"
