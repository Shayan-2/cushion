"""Plotly charts. Colour roles are fixed across the app:
blue = this customer / before, orange = after the shock, gray = peers."""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from .engine import Profile, ShockResult, runway_number
from .peers import BUCKET_LABELS, bucket, bucket_shares

BLUE = "#2a78d6"
ORANGE = "#eb6834"
GRAY = "#9a9893"
LIGHT_GRAY = "#cfcdc8"
INK = "#0b0b0b"
MUTED = "#52514e"
GRID = "#e9e8e4"


def _layout(fig: go.Figure, title: str | None = None, height: int = 360, **kw) -> go.Figure:
    fig.update_layout(
        title=dict(text=title, font=dict(size=18, color=INK), x=0, xanchor="left") if title else None,
        template="plotly_white", height=height,
        font=dict(size=15, color=MUTED),
        margin=dict(l=10, r=10, t=50 if title else 10, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="right", x=1, title=None),
        hoverlabel=dict(font_size=14), plot_bgcolor="white", paper_bgcolor="white", **kw,
    )
    fig.update_xaxes(gridcolor=GRID, zeroline=False, linecolor=GRID)
    fig.update_yaxes(gridcolor=GRID, zeroline=False, linecolor=GRID)
    return fig


def money_history(m: pd.DataFrame) -> go.Figure:
    m = m.tail(24)
    fig = go.Figure()
    fig.add_scatter(x=m["month"], y=m["money_in"], name="Money in", mode="lines+markers",
                    line=dict(color=BLUE, width=2), marker=dict(size=7),
                    hovertemplate="%{x}<br>In: $%{y:,.0f}<extra></extra>")
    fig.add_scatter(x=m["month"], y=m["money_out"], name="Money out", mode="lines+markers",
                    line=dict(color=ORANGE, width=2), marker=dict(size=7),
                    hovertemplate="%{x}<br>Out: $%{y:,.0f}<extra></extra>")
    fig.update_yaxes(tickprefix="$", tickformat=",.0f", rangemode="tozero")
    return _layout(fig, "Money in and out, last 24 months", hovermode="x unified")


def balance_history(m: pd.DataFrame, B: float) -> go.Figure:
    m = m.tail(24)
    fig = go.Figure()
    fig.add_scatter(x=m["month"], y=m["avg_daily_balance"], name="Average daily balance",
                    mode="lines+markers", line=dict(color=BLUE, width=2), marker=dict(size=7),
                    hovertemplate="%{x}<br>$%{y:,.0f}<extra></extra>", showlegend=False)
    fig.add_hline(y=B, line=dict(color=GRAY, dash="dash", width=2),
                  annotation_text=f"Buffer B = ${B:,.0f} (last 6 months)", annotation_position="top left",
                  annotation_font=dict(color=MUTED, size=14))
    fig.update_yaxes(tickprefix="$", tickformat=",.0f")
    return _layout(fig, "Savings balance, last 24 months")


def projection(p: Profile, before: ShockResult, after: ShockResult, duration: int) -> go.Figure:
    horizon = int(max(12, duration + 6))
    t = np.linspace(0, horizon, horizon * 10 + 1)
    fig = go.Figure()
    for res, name, color, dash in [(before, "Before the shock", GRAY, "dash"),
                                   (after, "After the shock", ORANGE, "solid")]:
        bal = np.maximum(res.buffer_left - res.gap * t, 0)
        fig.add_scatter(x=t, y=bal, name=name, mode="lines", line=dict(color=color, width=3, dash=dash),
                        hovertemplate="Month %{x:.1f}<br>$%{y:,.0f}<extra>" + name + "</extra>")
    r = runway_number(after.runway)
    if r < horizon:
        fig.add_scatter(x=[r], y=[0], mode="markers+text", marker=dict(size=14, color=ORANGE,
                        line=dict(color="white", width=2)), text=[f"Runs out: month {r:.1f}"],
                        textposition="top center", textfont=dict(size=15, color=INK), showlegend=False,
                        hoverinfo="skip")
    fig.add_vline(x=duration, line=dict(color=MUTED, dash="dot", width=2),
                  annotation_text=f"Shock window: {duration} months", annotation_position="top",
                  annotation_font=dict(size=14, color=MUTED))
    fig.update_xaxes(title="Months from today", dtick=2)
    fig.update_yaxes(tickprefix="$", tickformat=",.0f", rangemode="tozero")
    fig = _layout(fig, "Savings left, month by month", height=400, hovermode="x unified")
    fig.update_layout(legend=dict(orientation="h", yanchor="top", y=-0.22, xanchor="left", x=0),
                      margin=dict(b=40))
    return fig


def shares(df: pd.DataFrame) -> go.Figure:
    df = df.iloc[::-1]
    fig = go.Figure()
    fig.add_bar(y=df["category"], x=df["peers"], name="Similar customers (median)", orientation="h",
                marker=dict(color=LIGHT_GRAY, cornerradius=4),
                hovertemplate="%{y}<br>Peers: %{x:.1f}%<extra></extra>")
    fig.add_bar(y=df["category"], x=df["you"], name="This customer", orientation="h",
                marker=dict(color=BLUE, cornerradius=4), text=[f"{v:.0f}%" for v in df["you"]],
                textposition="outside", textfont=dict(color=INK),
                hovertemplate="%{y}<br>You: %{x:.1f}%<extra></extra>")
    fig.update_xaxes(ticksuffix="%", rangemode="tozero")
    return _layout(fig, "Where each $100 of spending goes", height=60 + 52 * len(df),
                   barmode="group", bargap=0.25, bargroupgap=0.08)


def runway_position(peers_before, peers_after, my_before: float, my_after: float, shocked: bool) -> go.Figure:
    fig = go.Figure()
    fig.add_bar(x=BUCKET_LABELS, y=bucket_shares(peers_before), name="Peers before the shock",
                marker=dict(color=LIGHT_GRAY, cornerradius=4),
                hovertemplate="%{x} months<br>%{y:.0f}% of peers<extra>Before</extra>")
    if shocked:
        fig.add_bar(x=BUCKET_LABELS, y=bucket_shares(peers_after), name="Peers after the shock",
                    marker=dict(color=ORANGE, cornerradius=4),
                    hovertemplate="%{x} months<br>%{y:.0f}% of peers<extra>After</extra>")
    marks = [(my_before, "You before", -0.2 if shocked else 0.0)]
    if shocked:
        marks.append((my_after, "You after", 0.2))
    for val, label, off in marks:
        i = BUCKET_LABELS.index(bucket(val))
        fig.add_annotation(x=i + off, y=0, yref="paper", yanchor="bottom", ay=-150, ax=0,
                           text=f"<b>{label}</b>", showarrow=True, arrowhead=2, arrowwidth=2,
                           arrowcolor=BLUE, font=dict(size=15, color=INK), bgcolor="white")
    fig.update_xaxes(title="Months of runway", type="category")
    fig.update_yaxes(ticksuffix="%", title="Share of peers")
    return _layout(fig, "Runway compared with similar customers", height=400, barmode="group", bargap=0.2)


def backup_steps(steps, duration: int) -> go.Figure:
    labels = [s.action for s in steps][::-1]
    vals = [min(runway_number(s.runway), 36) for s in steps][::-1]
    text = ["No shortfall" if isinstance(s.runway, str) else f"{s.runway:.1f} mo" for s in steps][::-1]
    colors = [ORANGE if i == len(steps) - 1 else BLUE for i in range(len(steps))]
    fig = go.Figure(go.Bar(y=labels, x=vals, orientation="h", text=text, textposition="outside",
                           marker=dict(color=colors, cornerradius=4), textfont=dict(color=INK),
                           hovertemplate="%{y}<br>%{text}<extra></extra>"))
    fig.add_vline(x=duration, line=dict(color=MUTED, dash="dot", width=2),
                  annotation_text=f"{duration}-month goal", annotation_position="top",
                  annotation_font=dict(size=14, color=MUTED))
    fig.update_xaxes(title="Months of runway (chart capped at 36)", range=[0, 40])
    return _layout(fig, "Each step stretches the runway", height=90 + 55 * len(steps), showlegend=False)


def backup_gap(steps) -> go.Figure:
    """For customers with no buffer: how each step shrinks the monthly shortfall."""
    labels = [s.action for s in steps][::-1]
    vals = [s.gap for s in steps][::-1]
    text = [f"${v:,.0f}/mo short" if v > 0 else "Gap closed" for v in vals]
    colors = [ORANGE if i == len(steps) - 1 else BLUE for i in range(len(steps))]
    fig = go.Figure(go.Bar(y=labels, x=[max(v, 0) for v in vals], orientation="h", text=text,
                           textposition="outside", marker=dict(color=colors, cornerradius=4),
                           textfont=dict(color=INK), hovertemplate="%{y}<br>%{text}<extra></extra>"))
    fig.update_xaxes(title="Monthly shortfall ($)", tickprefix="$", tickformat=",.0f",
                     range=[0, max(max(vals), 1) * 1.6])
    return _layout(fig, "Monthly shortfall after each step", height=90 + 55 * len(steps),
                   showlegend=False)


def finding_chart(t: pd.DataFrame) -> go.Figure:
    x = [f"D{b}" for b in t["band"]]
    fig = go.Figure()
    fig.add_bar(x=x, y=t["fail"], name="EI at 55% of income (judges' rule)",
                marker=dict(color=BLUE, cornerradius=4), text=[f"{v:.0f}%" for v in t["fail"]],
                textposition="outside", textfont=dict(color=INK),
                customdata=np.stack([t["n"], t["I"]], axis=1),
                hovertemplate="Decile %{x}: %{y:.0f}% run out<br>%{customdata[0]} customers, "
                              "median income $%{customdata[1]:,.0f}<extra></extra>")
    fig.add_bar(x=x, y=t["fail_cap"], name="With the real 2026 EI maximum ($729/week)",
                marker=dict(color=ORANGE, cornerradius=4),
                hovertemplate="Decile %{x}: %{y:.0f}% run out (EI cap)<extra></extra>")
    fig.update_yaxes(ticksuffix="%", range=[0, 110], title="Run out before 6 months")
    fig.update_xaxes(title="Income decile (D1 = lowest income, D10 = highest)")
    return _layout(fig, "Share of customers who run out of savings within a 6-month layoff",
                   height=420, barmode="group", bargap=0.2)
