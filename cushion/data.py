"""Load the bank data and precompute per-account stats.

Everything the app needs is computed once from monthly_summary.csv + loans.csv
(plus small lookup tables) and written to data/cache/*.parquet. The app only
reads those parquet files, so it starts in well under a second.

Definitions follow the track README exactly:
    I = median(money_in)
    S = median(money_out)
    H = median(household_bills)
    F = median(household_bills + insurance + loan_payments)
    B = mean(avg_daily_balance) over the account's last 6 rows, sorted by month
    P = loans.monthly_payment if the loan is still running at end of 2025
        (status C or D), else 0
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
CACHE = DATA / "cache"
STATS_PATH = CACHE / "stats.parquet"
MONTHLY_PATH = CACHE / "monthly.parquet"

N_BANDS = 10  # income deciles -> ~450 peers per band

# Spending categories (they add up to money_out in monthly_summary.csv)
CATEGORIES = {
    "household_bills": "Household bills",
    "insurance": "Insurance",
    "loan_payments": "Loan payments",
    "cash_withdrawals_genuine": "Cash withdrawals",
    "card_withdrawals": "Card purchases",
    "transfers_out_other": "Other transfers out",
    "bank_fees": "Bank fees",
}

MS_COLS = [
    "account_id", "month", "money_in", "money_out", "pension_in",
    "avg_daily_balance", "days_below_zero", *CATEGORIES.keys(),
]
RUNNING_LOAN = {"C", "D"}


def compute_account_stats(ms: pd.DataFrame, loans: pd.DataFrame) -> pd.DataFrame:
    """Per-account I, S, H, F, B, P plus descriptive extras. Pure function (testable)."""
    ms = ms.sort_values(["account_id", "month"])
    g = ms.groupby("account_id", sort=True)

    fixed = ms["household_bills"] + ms["insurance"] + ms["loan_payments"]
    out = pd.DataFrame({
        "I": g["money_in"].median(),
        "S": g["money_out"].median(),
        "H": g["household_bills"].median(),
        "F": fixed.groupby(ms["account_id"]).median(),
        "B": g.tail(6).groupby("account_id")["avg_daily_balance"].mean(),
        "n_months": g.size(),
        "first_month": g["month"].first(),
        "last_month": g["month"].last(),
        "pension_share": g["pension_in"].sum() / g["money_in"].sum().replace(0, np.nan),
        "months_overdrawn_pct": (ms["days_below_zero"] > 0).groupby(ms["account_id"]).mean(),
    })
    out["pension_share"] = out["pension_share"].fillna(0.0)

    # Share of total money out per category (shares sum to 1; robust to outlier months)
    totals = g[list(CATEGORIES)].sum()
    denom = totals.sum(axis=1).replace(0, np.nan)
    for c in CATEGORIES:
        out[f"share_{c}"] = (totals[c] / denom).fillna(0.0)

    # Loan payment P
    ln = loans.drop_duplicates("account_id").set_index("account_id")
    out["loan_status"] = ln["status"].reindex(out.index)
    running = out["loan_status"].isin(RUNNING_LOAN)
    out["P"] = np.where(running, ln["monthly_payment"].reindex(out.index), 0.0)
    out["P"] = out["P"].astype(float)
    out.index.name = "account_id"
    return out


def assign_income_bands(I: pd.Series, n: int = N_BANDS) -> tuple[pd.Series, list[float]]:
    """Equal-size income bands (deciles of I). Returns band (1..n) and the cut edges."""
    ranks = I.rank(method="first")
    band = pd.qcut(ranks, n, labels=False) + 1
    edges = [float(I[band == b].min()) for b in range(1, n + 1)] + [float(I.max())]
    return band.astype(int), edges


def band_for_income(income: float, edges: list[float]) -> int:
    """Band for a manually entered income, using the dataset's band edges."""
    for b in range(len(edges) - 1, 0, -1):
        if income >= edges[b - 1]:
            return b
    return 1


def _owner_age(DATA_DIR: Path) -> pd.Series:
    disp = pd.read_csv(DATA_DIR / "dispositions.csv", usecols=["client_id", "account_id", "type"])
    cl = pd.read_csv(DATA_DIR / "clients.csv", usecols=["client_id", "birth_date"])
    own = disp[disp["type"] == "owner"].merge(cl, on="client_id")
    age = 2025 - pd.to_datetime(own["birth_date"]).dt.year
    return pd.Series(age.values, index=own["account_id"]).groupby(level=0).first()


def build_cache(data_dir: Path = DATA) -> pd.DataFrame:
    ms = pd.read_csv(data_dir / "monthly_summary.csv", usecols=MS_COLS,
                     dtype={"month": "string"})
    loans = pd.read_csv(data_dir / "loans.csv",
                        usecols=["account_id", "monthly_payment", "status"])
    stats = compute_account_stats(ms, loans)
    stats["band"], _ = assign_income_bands(stats["I"])

    # Context used for the Key finding analysis
    acc = pd.read_csv(data_dir / "accounts.csv", usecols=["account_id", "district_id"]).set_index("account_id")
    dist = pd.read_csv(data_dir / "districts.csv",
                       usecols=["district_id", "region", "unemployment_rate_2023"]).set_index("district_id")
    district = acc["district_id"].reindex(stats.index)
    stats["region"] = district.map(dist["region"])
    stats["district_unemployment"] = district.map(dist["unemployment_rate_2023"])
    stats["owner_age"] = _owner_age(data_dir).reindex(stats.index)

    CACHE.mkdir(parents=True, exist_ok=True)
    stats.to_parquet(STATS_PATH)
    monthly = ms[["account_id", "month", "money_in", "money_out", "avg_daily_balance"]].copy()
    monthly["month"] = monthly["month"].astype(str)
    monthly.to_parquet(MONTHLY_PATH, index=False)
    return stats


def load_stats() -> pd.DataFrame:
    if not STATS_PATH.exists():
        return build_cache()
    return pd.read_parquet(STATS_PATH)


def load_monthly() -> pd.DataFrame:
    if not MONTHLY_PATH.exists():
        build_cache()
    return pd.read_parquet(MONTHLY_PATH)


def band_edges(stats: pd.DataFrame) -> list[float]:
    edges = [float(stats.loc[stats["band"] == b, "I"].min()) for b in range(1, N_BANDS + 1)]
    return edges + [float(stats["I"].max())]


if __name__ == "__main__":
    import time
    t = time.time()
    s = build_cache()
    print(f"built cache for {len(s)} accounts in {time.time() - t:.1f}s")
    print(s[["I", "S", "H", "F", "B", "P"]].describe().round(0))
