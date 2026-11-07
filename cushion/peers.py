"""'Customers like me': compare a customer to everyone in the same income decile."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .data import CATEGORIES, N_BANDS, band_for_income
from .engine import NO_SHOCK, Profile, Shock, runway_number, runway_vector, apply_shock

BUCKETS = [(-0.01, 0.0, "0 (empty)"), (0.0, 3.0, "Under 3"), (3.0, 6.0, "3 to 6"),
           (6.0, 12.0, "6 to 12"), (12.0, 24.0, "12 to 24"), (24.0, 1e9, "24+ / no shortfall")]
BUCKET_LABELS = [b[2] for b in BUCKETS]


def bucket(r: float) -> str:
    for lo, hi, label in BUCKETS:
        if lo < r <= hi:
            return label
    return BUCKET_LABELS[-1]


def band_label(band: int, edges: list[float]) -> str:
    lo = edges[band - 1]
    hi = edges[band] if band < N_BANDS else None
    return f"${lo:,.0f} to ${hi:,.0f}/month" if hi else f"${lo:,.0f}+/month"


def pct_rank(value: float, others: np.ndarray) -> float:
    """Share of peers this value beats (ties count half). 0..100."""
    if len(others) == 0:
        return float("nan")
    return float(((others < value).sum() + 0.5 * (others == value).sum()) / len(others) * 100)


@dataclass
class PeerView:
    band: int
    label: str
    n: int
    medians: dict            # peer medians of I, S, H, F, B, cover
    bills_diff_pct: float | None
    spend_diff_pct: float | None
    buffer_diff_pct: float | None
    cover_months: float      # B / S for this customer
    before_rank: float       # % of peers with a shorter runway, before the shock
    after_rank: float
    peers_before: np.ndarray
    peers_after: np.ndarray
    shares: pd.DataFrame | None   # category share: you vs peers (None in manual mode)


def _diff(a: float, b: float) -> float | None:
    return None if b <= 0 else (a - b) / b * 100


def peer_view(stats: pd.DataFrame, edges: list[float], p: Profile, shock: Shock) -> PeerView:
    band = p.band or band_for_income(p.I, edges)
    peers = stats[stats["band"] == band]
    if p.account_id is not None:
        peers = peers.drop(index=p.account_id, errors="ignore")

    before = runway_vector(peers.B, peers.S, peers.H, peers.I, NO_SHOCK)
    after = runway_vector(peers.B, peers.S, peers.H, peers.I, shock)
    my_before = runway_number(apply_shock(p, NO_SHOCK).runway)
    my_after = runway_number(apply_shock(p, shock).runway)

    cover = peers.B / peers.S.replace(0, np.nan)
    med = {k: float(peers[k].median()) for k in ["I", "S", "H", "F", "B"]}
    med["cover"] = float(cover.median())

    shares = None
    if p.account_id is not None and p.account_id in stats.index:
        row = stats.loc[p.account_id]
        shares = pd.DataFrame({
            "category": list(CATEGORIES.values()),
            "you": [row[f"share_{c}"] * 100 for c in CATEGORIES],
            "peers": [peers[f"share_{c}"].median() * 100 for c in CATEGORIES],
        })
    else:  # manual mode: only the bills share is known
        shares = pd.DataFrame({
            "category": ["Household bills"],
            "you": [p.H / p.S * 100 if p.S > 0 else 0.0],
            "peers": [float((peers.H / peers.S.replace(0, np.nan)).median() * 100)],
        })

    return PeerView(
        band=band, label=band_label(band, edges), n=len(peers), medians=med,
        bills_diff_pct=_diff(p.H, med["H"]), spend_diff_pct=_diff(p.S, med["S"]),
        buffer_diff_pct=_diff(p.B, med["B"]),
        cover_months=(p.B / p.S) if p.S > 0 else float("inf"),
        before_rank=pct_rank(my_before, before), after_rank=pct_rank(my_after, after),
        peers_before=before, peers_after=after, shares=shares,
    )


def bucket_shares(values: np.ndarray) -> list[float]:
    labels = [bucket(v) for v in values]
    n = max(len(labels), 1)
    return [labels.count(b) / n * 100 for b in BUCKET_LABELS]


# ---------- Key finding: who runs out first? ----------
def finding_table(stats: pd.DataFrame, horizon: int = 6) -> pd.DataFrame:
    """Per income decile: share of customers who can't last `horizon` months after a layoff."""
    s = stats[stats["pension_share"] < 0.05]  # job loss doesn't stop a pension: exclude pensioners
    lay = runway_vector(s.B, s.S, s.H, s.I, Shock(job_loss=True, ei_rate=0.55))
    lay_cap = runway_vector(s.B, s.S, s.H, s.I, Shock(job_loss=True, ei_rate=0.55, ei_cap=True))
    df = pd.DataFrame({"band": s["band"], "fail": lay < horizon, "fail_cap": lay_cap < horizon,
                       "cover": s.B / s.S.replace(0, np.nan), "B": s.B, "S": s.S, "I": s.I})
    out = df.groupby("band").agg(n=("fail", "size"), fail=("fail", "mean"), fail_cap=("fail_cap", "mean"),
                                 cover=("cover", "median"), B=("B", "median"), S=("S", "median"),
                                 I=("I", "median"))
    out[["fail", "fail_cap"]] *= 100
    return out.reset_index()
