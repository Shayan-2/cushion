import numpy as np
import pandas as pd
import pytest

from cushion.data import band_for_income, compute_account_stats, assign_income_bands
from cushion.engine import (
    EI_MAX_MONTHLY_2026, NO_SHORTFALL, PRESETS, Profile, Shock, apply_shock, runway,
    runway_number, runway_vector,
)

# A simple customer: earns 5,000, spends 4,000, bills 1,000, buffer 12,000
P0 = Profile(I=5000, S=4000, H=1000, F=1500, B=12000, P=0)


# ---------- runway() ----------
def test_runway_basic_division_and_rounding():
    # buffer 10,000 / gap 3,000 = 3.333 -> 3.3
    assert runway(10000, 0, 5000, 2000) == 3.3


def test_runway_zero_buffer():
    assert runway(0, 0, 5000, 1000) == 0


def test_runway_negative_buffer():
    assert runway(-500, 0, 5000, 1000) == 0


def test_runway_one_off_eats_whole_buffer():
    # buffer_left <= 0 wins even when there is no shortfall
    assert runway(3000, 3000, 1000, 5000) == 0
    assert runway(3000, 4000, 1000, 5000) == 0


def test_runway_no_shortfall():
    assert runway(1000, 0, 4000, 5000) == NO_SHORTFALL
    assert runway(1000, 0, 5000, 5000) == NO_SHORTFALL  # gap exactly 0


def test_runway_cap_120():
    assert runway(1_000_000, 0, 1001, 1000) == 120


def test_runway_just_under_cap():
    assert runway(119_000, 0, 2000, 1000) == 119.0


def test_runway_number_maps_no_shortfall_to_cap():
    assert runway_number(NO_SHORTFALL) == 120
    assert runway_number(4.2) == 4.2


# ---------- shocks ----------
def test_no_shock_is_baseline():
    r = apply_shock(P0, Shock())
    assert (r.income, r.spending, r.one_off) == (5000, 4000, 0)
    assert r.runway == NO_SHORTFALL


def test_job_loss_ei_55():
    r = apply_shock(P0, PRESETS["Laid off: EI 55% for 6 months"])
    assert r.income == pytest.approx(0.55 * 5000)
    assert r.spending == 4000
    # 12000 / (4000 - 2750) = 9.6
    assert r.runway == 9.6
    assert r.makes_it  # 9.6 >= 6


def test_bills_up_15():
    r = apply_shock(P0, PRESETS["Rent and bills up 15%"])
    assert r.spending == pytest.approx(4000 + 0.15 * 1000)
    assert r.runway == NO_SHORTFALL  # still earns more than spends


def test_furnace_one_month_of_spending():
    r = apply_shock(P0, PRESETS["Furnace dies: 1 month of spending"])
    assert r.one_off == 4000
    assert r.buffer_left == 8000
    assert r.runway == NO_SHORTFALL


def test_furnace_with_existing_shortfall():
    p = Profile(I=3000, S=4000, H=1000, F=1500, B=10000)
    r = apply_shock(p, Shock(one_off_months=1.0))
    assert r.runway == round((10000 - 4000) / 1000, 1)  # 6.0


def test_job_loss_plus_bills_mix():
    r = apply_shock(P0, PRESETS["Job loss + bills up 15%"])
    # spending 4150, income 2750, gap 1400 -> 12000/1400 = 8.571 -> 8.6
    assert r.runway == 8.6


def test_perfect_storm():
    r = apply_shock(P0, PRESETS["Perfect storm: all three"])
    # left 8000, gap 1400 -> 5.714 -> 5.7, fails the 6-month horizon
    assert r.runway == 5.7
    assert not r.makes_it


def test_dollar_one_off_adds_to_month_multiple():
    r = apply_shock(P0, Shock(one_off_months=0.5, one_off_dollars=1000))
    assert r.one_off == 3000


def test_ei_cap_only_when_enabled():
    rich = Profile(I=20000, S=15000, H=2000, F=3000, B=30000)
    assert apply_shock(rich, Shock(job_loss=True)).income == 11000
    assert apply_shock(rich, Shock(job_loss=True, ei_cap=True)).income == pytest.approx(EI_MAX_MONTHLY_2026)


def test_zero_income_account():
    p = Profile(I=0, S=0, H=0, F=0, B=500)
    assert apply_shock(p, Shock(job_loss=True)).runway == NO_SHORTFALL
    assert apply_shock(p, Shock(one_off_dollars=600)).runway == 0


def test_vector_matches_scalar():
    rng = np.random.default_rng(0)
    n = 500
    B = rng.uniform(-5000, 60000, n)
    S = rng.uniform(0, 20000, n)
    H = rng.uniform(0, 5000, n)
    I = rng.uniform(0, 25000, n)
    for shock in PRESETS.values():
        vec = runway_vector(B, S, H, I, shock)
        for k in range(n):
            p = Profile(I=I[k], S=S[k], H=H[k], F=0, B=B[k])
            assert vec[k] == pytest.approx(runway_number(apply_shock(p, shock).runway), abs=0.051)


# ---------- per-account stats ----------
def _ms(account_id, rows):
    cols = ["money_in", "money_out", "household_bills", "insurance", "loan_payments", "avg_daily_balance"]
    df = pd.DataFrame(rows, columns=["month", *cols])
    df["account_id"] = account_id
    for c in ["pension_in", "days_below_zero", "bank_fees", "cash_withdrawals_genuine",
              "card_withdrawals", "transfers_out_other"]:
        df[c] = 0.0
    return df


def test_stats_definitions_and_last_6_rows_sorted():
    # 8 months, given out of order; B must use the last 6 by month
    rows = [(f"2025-{m:02d}", 1000 * m, 500 * m, 100 * m, 10, 50 if m > 4 else 0, 100 * m)
            for m in [8, 1, 3, 2, 7, 4, 6, 5]]
    ms = _ms(1, rows)
    loans = pd.DataFrame({"account_id": [1], "monthly_payment": [250.0], "status": ["C"]})
    s = compute_account_stats(ms, loans).loc[1]
    assert s.I == 4500  # median of 1000..8000
    assert s.S == 2250
    assert s.H == 450
    # F = median(100m + 10 + loan) for m=1..8 -> values 110,210,310,410,560,660,760,860 -> (410+560)/2
    assert s.F == 485
    assert s.B == np.mean([300, 400, 500, 600, 700, 800])
    assert s.P == 250
    assert s.n_months == 8


def test_few_months_uses_all_rows_for_buffer():
    rows = [("2025-01", 100, 50, 0, 0, 0, 1000), ("2025-02", 100, 50, 0, 0, 0, 3000)]
    s = compute_account_stats(_ms(7, rows), pd.DataFrame(columns=["account_id", "monthly_payment", "status"])).loc[7]
    assert s.B == 2000
    assert s.P == 0


@pytest.mark.parametrize("status,expected", [("A", 0), ("B", 0), ("C", 300), ("D", 300)])
def test_loan_payment_only_if_running(status, expected):
    rows = [("2025-01", 100, 50, 0, 0, 0, 1000)]
    loans = pd.DataFrame({"account_id": [3], "monthly_payment": [300.0], "status": [status]})
    assert compute_account_stats(_ms(3, rows), loans).loc[3].P == expected


def test_no_loan_account_has_zero_payment():
    rows = [("2025-01", 100, 50, 0, 0, 0, 1000)]
    loans = pd.DataFrame({"account_id": [999], "monthly_payment": [300.0], "status": ["C"]})
    s = compute_account_stats(_ms(4, rows), loans).loc[4]
    assert s.P == 0
    assert pd.isna(s.loan_status)


def test_income_bands_equal_size_and_manual_lookup():
    I = pd.Series(np.arange(1000, dtype=float) * 10)
    band, edges = assign_income_bands(I, 10)
    assert band.value_counts().tolist() == [100] * 10
    assert band_for_income(0, edges) == 1
    assert band_for_income(5000, edges) == 6
    assert band_for_income(1e9, edges) == 10


# ---------- summary fallback ----------
def test_template_summary_never_needs_api(monkeypatch):
    from cushion.summary import summarize
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    facts = {"bills_vs_peers_pct": 12, "spending_vs_peers_pct": 3, "cover_months": 2.0,
             "shock": "a job loss with EI paying 55% of income", "duration": 6,
             "runway_before": NO_SHORTFALL, "runway_after": 4.2, "makes_it": False,
             "next_step": "cut flexible spending by $300/month"}
    text, src = summarize(facts)
    assert src == "template"
    assert "12% more on household bills" in text and "4.2 months" in text and "would not get through" in text
