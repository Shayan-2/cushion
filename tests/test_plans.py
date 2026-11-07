import math

import pytest

from cushion.engine import Profile, Shock, apply_shock, runway_number
from cushion.plans import backup_plan, goal_plan

SURPLUS = Profile(I=5000, S=4000, H=1000, F=1500, B=6000)
DEFICIT = Profile(I=3000, S=4000, H=1000, F=1500, B=2000)


def test_goal_plan_uses_half_of_surplus():
    g = goal_plan(SURPLUS, 3)
    assert g.target == 12000 and g.gap == 6000
    assert g.monthly_save == 500
    assert g.months_to_goal == 12


def test_goal_plan_deficit_trims_flexible_spending():
    g = goal_plan(DEFICIT, 3)
    assert g.monthly_save == pytest.approx(0.10 * (4000 - 1500))
    assert g.months_to_goal == pytest.approx(10000 / 250)


def test_goal_plan_already_funded():
    g = goal_plan(Profile(I=5000, S=1000, H=0, F=0, B=50000), 3)
    assert g.gap == 0 and g.months_to_goal is None


def test_goal_plan_nothing_to_save():
    g = goal_plan(Profile(I=1000, S=2000, H=2000, F=2000, B=0), 3)
    assert g.monthly_save == 0 and math.isinf(g.months_to_goal)


def test_backup_plan_steps_never_shorten_runway():
    p = Profile(I=6000, S=6000, H=2000, F=3000, B=9000, P=500)
    shock = Shock(job_loss=True, bills_up=0.15, one_off_months=1.0)
    bp = backup_plan(p, shock, apply_shock(p, shock))
    vals = [runway_number(s.runway) for s in bp.steps]
    assert vals == sorted(vals)
    assert [s.action for s in bp.steps][0] == "Do nothing"
    assert any("payment pause" in s.action for s in bp.steps)


def test_survival_budget():
    shock = Shock(job_loss=True, duration=6)
    res = apply_shock(SURPLUS, shock)
    bp = backup_plan(SURPLUS, shock, res)
    # income 2750 + 6000/6 = 3750; spending 4000 -> cut 250
    assert bp.survival_budget == pytest.approx(3750)
    assert bp.cut_needed == pytest.approx(250)


def test_loan_pause_only_counts_payments_actually_made():
    # P from loans.csv is 5000, but only 300 of loan payments appear in spending (F - H)
    p = Profile(I=5000, S=6000, H=1000, F=1300, B=-100, P=5000)
    bp = backup_plan(p, Shock(), apply_shock(p, Shock()))
    pause = [s for s in bp.steps if "payment pause" in s.action][0]
    assert "$300" in pause.detail and "only" in pause.detail


def test_no_loan_no_pause_step():
    bp = backup_plan(SURPLUS, Shock(job_loss=True), apply_shock(SURPLUS, Shock(job_loss=True)))
    assert not any("payment pause" in s.action for s in bp.steps)
