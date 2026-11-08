"""Cushion: how long would your savings last if life hits?  Run with:  streamlit run app.py"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from cushion import charts
from cushion.data import band_edges, band_for_income, load_monthly, load_stats
from cushion.engine import (
    EI_MAX_WEEKLY_2026, NO_SHOCK, PRESETS, Profile, Shock, apply_shock, format_runway, runway_number,
)
from cushion.peers import finding_table, peer_view
from cushion.plans import backup_plan, goal_plan
from cushion.summary import summarize

st.set_page_config(page_title="Cushion", page_icon="🛟", layout="wide")

st.markdown("""
<style>
.block-container {padding-top: 1.6rem; padding-bottom: 2rem; max-width: 1400px;}
[data-testid="stMetricValue"] {font-size: 2.1rem;}
[data-testid="stMetricLabel"] p {font-size: 1.0rem;}
.big-card {min-height: 150px; border-radius: 14px; padding: 18px 22px; border: 1px solid #e3e2de; background: #fcfcfb;}
.big-card .lbl {font-size: 1.05rem; color: #52514e; margin-bottom: 2px;}
.big-card .val {font-size: 2.6rem; font-weight: 700; color: #0b0b0b; line-height: 1.15;}
.big-card .sub {font-size: 0.95rem; color: #52514e;}
.verdict-ok {border-left: 8px solid #008300;}
.verdict-bad {border-left: 8px solid #e34948;}
.summary {font-size: 1.25rem; line-height: 1.55; padding: 16px 20px; border-radius: 12px;
          background: #eef5fd; border: 1px solid #cde2fb; color: #0b0b0b;}
.summary .src {font-size: 0.8rem; color: #52514e; display:block; margin-top:6px;}
.foot {font-size: 0.85rem; color: #6b6a66; margin-top: 2.5rem; border-top: 1px solid #e3e2de; padding-top: 10px;}
</style>
""", unsafe_allow_html=True)


# ---------------- data (cached, loads once) ----------------
@st.cache_resource(show_spinner="Loading customer data...")
def get_data():
    stats = load_stats()
    monthly = load_monthly().set_index("account_id").sort_index()
    return stats, monthly, band_edges(stats)


@st.cache_data(show_spinner=False)
def get_finding():
    stats, _, _ = get_data()
    return finding_table(stats)


@st.cache_data(show_spinner=False, ttl=3600)
def cached_summary(facts_items: tuple, use_ai: bool):
    return summarize(dict(facts_items), use_ai)


stats, monthly, edges = get_data()

SAMPLES = {
    "Comfortable": 31431,       # earns more than spends, big buffer
    "Tight month to month": 20854,  # spends more than earns, small buffer
    "Has a car/home loan": 20134,   # running loan, OK so far
    "Loan in arrears": 57247,       # running loan, client in debt, negative buffer
    "Pensioner": 20253,             # most income is pension
}

# ---------------- session defaults ----------------
DEFAULTS = dict(acct_text=str(SAMPLES["Tight month to month"]), job_loss=True, ei_pct=55, bills_pct=0,
                oneoff_months=0.0, oneoff_dollars=0, duration=6, ei_cap=False,
                preset="Laid off: EI 55% for 6 months", mode="Bank customer",
                m_income=7500, m_spend=7400, m_bills=1500, m_savings=22000)
for k, v in DEFAULTS.items():
    st.session_state.setdefault(k, v)


def set_preset(name: str):
    s = PRESETS[name]
    st.session_state.update(job_loss=s.job_loss, ei_pct=int(round(s.ei_rate * 100)),
                            bills_pct=int(round(s.bills_up * 100)), oneoff_months=float(s.one_off_months),
                            oneoff_dollars=int(s.one_off_dollars), duration=int(s.duration),
                            ei_cap=s.ei_cap, preset=name)


def set_account(aid: int):
    st.session_state.update(acct_text=str(aid), mode="Bank customer")


def mark_custom():
    st.session_state.preset = "Custom"


# ---------------- sidebar: inputs ----------------
with st.sidebar:
    st.markdown("## 🛟 Cushion")
    st.markdown("**1 · Pick a customer**")
    mode = st.radio("Input", ["Bank customer", "Manual entry"], key="mode", horizontal=True,
                    label_visibility="collapsed")
    if mode == "Bank customer":
        st.text_input("Account ID", key="acct_text", placeholder="e.g. 20854",
                      help="Any account_id from the bank data (4,500 customers).")
        st.caption("Sample customers")
        for label, aid in SAMPLES.items():
            st.button(f"{label} · {aid}", key=f"s_{aid}", on_click=set_account, args=(aid,), width="stretch")
    else:
        st.slider("Monthly income ($)", 0, 40000, step=100, key="m_income")
        st.slider("Monthly spending ($)", 0, 40000, step=100, key="m_spend")
        st.slider("Rent and household bills ($)", 0, 10000, step=50, key="m_bills",
                  help="Part of monthly spending")
        st.slider("Savings buffer ($)", 0, 80000, step=500, key="m_savings",
                  help="Needed for runway. Default = median customer.")

    st.divider()
    st.markdown("**2 · Pick a shock**")
    for i, name in enumerate(PRESETS):
        st.button(name, key=f"p_{i}", on_click=set_preset, args=(name,), width="stretch",
                            type="primary" if st.session_state.preset == name else "secondary")
    with st.expander("Adjust the shock size", expanded=True):
        st.toggle("Job loss (income replaced by EI)", key="job_loss", on_change=mark_custom)
        st.slider("EI pays this % of usual income", 0, 100, step=5, key="ei_pct", on_change=mark_custom,
                  disabled=not st.session_state.job_loss)
        st.checkbox(f"Apply 2026 EI maximum (${EI_MAX_WEEKLY_2026:.0f}/week)", key="ei_cap",
                    on_change=mark_custom, disabled=not st.session_state.job_loss,
                    help="Off by default to match the judges' rule. Government of Canada 2026 maximum.")
        st.slider("Household bills / rent go up by (%)", 0, 100, step=5, key="bills_pct", on_change=mark_custom)
        st.slider("Surprise cost (months of typical spending)", 0.0, 3.0, step=0.25, key="oneoff_months",
                  on_change=mark_custom)
        st.number_input("Plus a surprise cost in dollars", 0, 200000, step=500, key="oneoff_dollars",
                        on_change=mark_custom)
        st.slider("Shock lasts (months)", 1, 24, key="duration", on_change=mark_custom)
    use_ai = st.toggle("AI summary (Gemini)", value=True,
                       help="Falls back to a template summary with no key, no internet, or an API error.")

# ---------------- resolve the customer ----------------
profile: Profile | None = None
if mode == "Bank customer":
    raw = st.session_state.acct_text.strip().replace(",", "")
    if not raw.isdigit():
        st.warning("Type an account ID (numbers only), or click a sample customer in the sidebar.")
    else:
        aid = int(raw)
        if aid in stats.index:
            profile = Profile.from_row(aid, stats.loc[aid])
        else:
            near = stats.index[(abs(stats.index.to_series() - aid)).argsort()[:3]].tolist()
            st.error(f"We couldn't find account **{aid}**. Account IDs run from {stats.index.min()} to "
                     f"{stats.index.max()}. Closest IDs: {', '.join(map(str, near))}.")
else:
    I, S, H, B = (float(st.session_state[k]) for k in ["m_income", "m_spend", "m_bills", "m_savings"])
    H = min(H, S) if S > 0 else H
    profile = Profile(I=I, S=S, H=H, F=H, B=B, P=0.0, band=band_for_income(I, edges))

if profile is None:
    st.stop()

shock = Shock(job_loss=st.session_state.job_loss, ei_rate=st.session_state.ei_pct / 100,
              ei_cap=st.session_state.ei_cap, bills_up=st.session_state.bills_pct / 100,
              one_off_months=st.session_state.oneoff_months, one_off_dollars=st.session_state.oneoff_dollars,
              duration=st.session_state.duration)
base = apply_shock(profile, NO_SHOCK)
res = apply_shock(profile, shock)
pv = peer_view(stats, edges, profile, shock)
row = stats.loc[profile.account_id] if profile.account_id is not None else None


def sentence(t: str) -> str:
    return t[:1].upper() + t[1:]


def shock_text(s: Shock, p: Profile) -> str:
    parts = []
    if s.job_loss:
        parts.append(f"a job loss with EI paying {s.ei_rate:.0%} of income" + (" (capped)" if s.ei_cap else ""))
    if s.bills_up:
        parts.append(f"household bills up {s.bills_up:.0%}")
    oneoff = s.one_off_months * p.S + s.one_off_dollars
    if oneoff:
        parts.append(f"a surprise bill of ${oneoff:,.0f}")
    return " and ".join(parts) if parts else "none"


def no_buffer_reason() -> str:
    if profile.B <= 0:
        return (f"There is no savings buffer: the average balance is ${profile.B:,.0f}. Any shortfall "
                "hits immediately, so the backup plan has to close the monthly gap.")
    return (f"The surprise cost (${res.one_off:,.0f}) is bigger than the buffer (${profile.B:,.0f}). "
            "Step 1 is to spread it out.")


gp = goal_plan(profile, 3)
bp = backup_plan(profile, shock, res)

# ---------------- header ----------------
who = f"Customer {profile.account_id}" if profile.account_id else "Manual customer"
meta = f"Income band {pv.band} of 10 ({pv.label}) · compared with {pv.n} similar customers"
if row is not None:
    meta += f" · {int(row.n_months)} months of data ({row.first_month} to {row.last_month})"
st.markdown(f"# {who}")
st.caption(meta)

shocked = not shock.is_none
c1, c2, c3 = st.columns([1, 1, 1.3])
with c1:
    st.markdown(f"""<div class="big-card"><div class="lbl">Runway today</div>
    <div class="val">{format_runway(base.runway)}</div>
    <div class="sub">Buffer ${profile.B:,.0f} · in ${profile.I:,.0f} · out ${profile.S:,.0f} per month</div></div>""",
                unsafe_allow_html=True)
with c2:
    st.markdown(f"""<div class="big-card" style="border-color:#f3b49a;background:#fff7f3">
    <div class="lbl">Runway after the shock</div>
    <div class="val" style="color:#c2410c">{format_runway(res.runway) if shocked else "No shock picked"}</div>
    <div class="sub">In ${res.income:,.0f} · out ${res.spending:,.0f} per month · one-off ${res.one_off:,.0f}</div></div>""",
                unsafe_allow_html=True)
with c3:
    r_after = runway_number(res.runway)
    if not shocked:
        ok, head, sub = runway_number(base.runway) >= 6, "No shock applied", "Pick a shock in the sidebar."
    elif res.makes_it:
        ok, head = True, f"✅ Makes it through the {shock.duration}-month shock"
        sub = ((f"Money lasts {format_runway(res.runway).lower()}, with "
                f"${max(res.buffer_left - res.gap * shock.duration, 0):,.0f} left at the end")
               if res.gap > 0 else
               f"Income still covers spending; ${res.buffer_left:,.0f} of savings left after any one-off cost")
    elif r_after <= 0:
        ok, head = False, "⚠️ No cushion: short from day one"
        sub = no_buffer_reason() if profile.B <= 0 else (
            f"The ${res.one_off:,.0f} surprise cost is more than the ${profile.B:,.0f} buffer.")
    else:
        ok = False
        head = f"⚠️ Runs out {shock.duration - r_after:.1f} months early"
        sub = (f"To last {shock.duration} months, keep spending under ${bp.survival_budget:,.0f}/month "
               f"(cut ${bp.cut_needed:,.0f})" if bp.survival_budget is not None
               else no_buffer_reason())
    st.markdown(f"""<div class="big-card {'verdict-ok' if ok else 'verdict-bad'}"><div class="lbl">Verdict</div>
    <div class="val" style="font-size:1.6rem">{head}</div><div class="sub" style="font-size:1.05rem">{sub}</div></div>""",
                unsafe_allow_html=True)

# Plain-English summary (only summary numbers are sent to the API)
facts = {
    "monthly_income": round(profile.I), "monthly_spending": round(profile.S),
    "household_bills": round(profile.H), "savings_buffer": round(profile.B),
    "bills_vs_peers_pct": None if pv.bills_diff_pct is None else round(pv.bills_diff_pct),
    "spending_vs_peers_pct": None if pv.spend_diff_pct is None else round(pv.spend_diff_pct),
    "cover_months": round(min(pv.cover_months, 120), 1),
    "shock": shock_text(shock, profile), "duration": shock.duration,
    "runway_before": base.runway, "runway_after": res.runway, "makes_it": bool(res.makes_it),
    "next_step": (f"{bp.steps[1].action.lower()}, which cuts the monthly shortfall to ${max(bp.steps[1].gap, 0):,.0f}"
                  if profile.B <= 0 else
                  f"{bp.steps[1].action.lower()}, which stretches the runway to "
                  f"{format_runway(bp.steps[1].runway).lower()}") if (len(bp.steps) > 1 and shocked and not res.makes_it)
                 else (f"save ${gp.monthly_save:,.0f}/month toward a 3-month emergency fund of ${gp.target:,.0f}"
                       if gp.gap > 0 and gp.monthly_save > 0 else "keep the buffer in a separate savings account and "
                       "aim for 6 months of spending"),
}
with st.spinner("Writing summary..."):
    text, src = cached_summary(tuple(facts.items()), use_ai)
st.markdown(f'<div class="summary">{text}<span class="src">Summary: '
            f'{"AI (Gemini), from summary numbers only" if src == "Gemini" else "template (no AI used)"}</span></div>',
            unsafe_allow_html=True)
st.write("")

# ---------------- tabs ----------------
t1, t2, t3, t4, t5 = st.tabs(["① Know the customer", "② Shock", "③ Plan", "④ Customers like me", "★ Key finding"])

with t1:
    m = st.columns(4)
    m[0].metric("Typical monthly income (I)", f"${profile.I:,.0f}", border=True,
                help="Median of money_in across all months")
    m[1].metric("Typical monthly spending (S)", f"${profile.S:,.0f}", border=True,
                help="Median of money_out across all months")
    m[2].metric("Savings buffer (B)", f"${profile.B:,.0f}", border=True,
                help="Mean of avg_daily_balance over the last 6 months")
    m[3].metric("Runway today", "No shortfall" if isinstance(base.runway, str) else format_runway(base.runway),
                border=True,
                help="Buffer ÷ (spending − income). 'No shortfall' when income covers spending.")
    m = st.columns(4)
    m[0].metric("Fixed costs (F)", f"${profile.F:,.0f}", border=True,
                help="Median of household bills + insurance + loan payments")
    m[1].metric("Household bills (H)", f"${profile.H:,.0f}", border=True, help="Median of household_bills")
    m[2].metric("Loan payment (P)", f"${profile.P:,.0f}", border=True,
                help="Monthly payment if the loan is still running at end of 2025 (status C or D)")
    m[3].metric("Months of spending saved", f"{max(min(pv.cover_months, 120), 0) + 0.0:.1f}", border=True,
                help="Buffer ÷ typical spending: how long savings last with zero income")

    notes = []
    if profile.B <= 0:
        notes.append("This customer's average balance is **negative**: there is no buffer, so any shortfall "
                     "is immediate.")
    if profile.I < profile.S:
        notes.append(f"They already spend **${profile.S - profile.I:,.0f} more than they take in** in a typical month.")
    if row is not None and row.pension_share > 0.3:
        notes.append(f"**{row.pension_share:.0%} of income is a pension.** A job loss may not cut it, so the "
                     "job-loss shock is a worst case here.")
    if row is not None and row.loan_status == "D":
        notes.append("Their loan is **running but in arrears** (status D).")
    if row is not None and row.n_months < 18:
        notes.append(f"Only {int(row.n_months)} months of history: medians are less certain.")
    for n in notes:
        st.info(n)

    if profile.account_id is not None:
        hist = monthly.loc[[profile.account_id]].reset_index()
        a, b = st.columns(2)
        a.plotly_chart(charts.money_history(hist), config={"displayModeBar": False})
        b.plotly_chart(charts.balance_history(hist, profile.B), config={"displayModeBar": False})

with t2:
    st.markdown(f"**Shock:** {sentence(shock_text(shock, profile))}" + (f" · lasting {shock.duration} months"
                                                                           if shocked else ""))
    tbl = pd.DataFrame({
        "": ["Monthly income", "Monthly spending", "Monthly shortfall (gap)", "One-off cost",
             "Buffer left after one-off", "Runway"],
        "Before": [f"${base.income:,.0f}", f"${base.spending:,.0f}", f"${max(base.gap, 0):,.0f}", "$0",
                   f"${base.buffer_left:,.0f}", format_runway(base.runway)],
        "After shock": [f"${res.income:,.0f}", f"${res.spending:,.0f}", f"${max(res.gap, 0):,.0f}",
                        f"${res.one_off:,.0f}", f"${res.buffer_left:,.0f}", format_runway(res.runway)],
    })
    a, b = st.columns([1, 1.5])
    with a:
        st.dataframe(tbl, hide_index=True, row_height=44)
        st.caption("Runway = buffer left ÷ monthly shortfall, capped at 120 months, rounded to 1 decimal. "
                   "If the one-off cost uses up the whole buffer, runway is 0.")
    b.plotly_chart(charts.projection(profile, base, res, shock.duration), config={"displayModeBar": False})

with t3:
    a, b = st.columns(2)
    with a:
        st.subheader("🎯 Goal plan: emergency fund")
        months = st.segmented_control("Target", [3, 6], default=3, format_func=lambda x: f"{x} months",
                                      key="goal_months") or 3
        gp = goal_plan(profile, months)
        prog = 1.0 if gp.target <= 0 else min(gp.have / gp.target, 1.0)
        st.progress(prog, text=f"${gp.have:,.0f} of ${gp.target:,.0f} ({prog:.0%})")
        g = st.columns(2)
        g[0].metric("Save each month", f"${gp.monthly_save:,.0f}" if gp.gap > 0 else "Done", border=True)
        g[1].metric("Time to goal", "Already there" if gp.months_to_goal is None else
                    ("Not at this pace" if gp.months_to_goal == float("inf") or gp.months_to_goal > 120
                     else f"{gp.months_to_goal:.0f} months"), border=True)
        for s in gp.steps:
            st.markdown(f"- {s}")
    with b:
        st.subheader("🛟 Backup plan: if the shock hits")
        if not shocked:
            st.info("Pick a shock in the sidebar to see the backup plan.")
        else:
            if bp.survival_budget is not None:
                st.metric(f"Survival budget to last {shock.duration} months",
                          f"${bp.survival_budget:,.0f}/month",
                          delta=(f"-${bp.cut_needed:,.0f} vs now" if bp.cut_needed > 0 else "no cut needed"),
                          delta_color="inverse" if bp.cut_needed > 0 else "off", border=True,
                          help="Shocked income + buffer left ÷ shock length")
            else:
                st.warning(no_buffer_reason())
            no_buffer = profile.B <= 0
            st.markdown("**Actions, in order** (" + ("monthly shortfall" if no_buffer else "runway")
                        + " after each one, cumulative):")
            for i, s in enumerate(bp.steps[1:], 1):
                result = (("closes the gap" if s.gap <= 0 else f"${s.gap:,.0f}/month short") if no_buffer
                          else format_runway(s.runway))
                st.markdown(f"{i}. **{s.action}**: {s.detail} → **{result}**")
            if shock.job_loss:
                st.markdown(f"{len(bp.steps)}. **Apply for EI right away**: apply within 4 weeks of the last "
                            "day of work so benefits aren't delayed.")
            st.plotly_chart(charts.backup_gap(bp.steps) if no_buffer else charts.backup_steps(bp.steps, shock.duration),
                            config={"displayModeBar": False})

with t4:
    st.markdown(f"Similar customers = the **{pv.n} customers in income band {pv.band} of 10** ({pv.label}).")
    k = st.columns(4)

    def fmt_diff(d):
        return None if d is None else f"{d:+.0f}% vs peers"
    k[0].metric("Household bills", f"${profile.H:,.0f}", fmt_diff(pv.bills_diff_pct), delta_color="inverse",
                border=True, help=f"Peer median ${pv.medians['H']:,.0f}")
    k[1].metric("Spending", f"${profile.S:,.0f}", fmt_diff(pv.spend_diff_pct), delta_color="inverse",
                border=True, help=f"Peer median ${pv.medians['S']:,.0f}")
    k[2].metric("Buffer", f"${profile.B:,.0f}", fmt_diff(pv.buffer_diff_pct), border=True,
                help=f"Peer median ${pv.medians['B']:,.0f}")
    k[3].metric("Longer runway than",
                f"{(pv.after_rank if shocked else pv.before_rank):.0f}% of peers",
                (f"{pv.after_rank - pv.before_rank:+.0f} pts vs before" if shocked else None), border=True,
                help="Share of similar customers whose runway is shorter than this customer's. Peers get the "
                     "same shock.")
    a, b = st.columns([1, 1.2])
    a.plotly_chart(charts.shares(pv.shares), config={"displayModeBar": False})
    b.plotly_chart(charts.runway_position(pv.peers_before, pv.peers_after, runway_number(base.runway),
                                          runway_number(res.runway), shocked), config={"displayModeBar": False})
    st.caption(f"Peers get the same shock. Before the shock this customer has a longer runway than "
               f"{pv.before_rank:.0f}% of peers; after it, {pv.after_rank:.0f}%.")

with t5:
    ft = get_finding()
    top, low = ft.iloc[-1], ft.iloc[:2]
    st.subheader("Higher earners are the most fragile: 3 in 4 top earners can't survive a 6-month layoff")
    st.markdown(
        f"""In the top income decile, **{top.fail:.0f}%** of customers run out of savings before a 6-month
layoff on EI ends, compared with **{low.fail.mean():.0f}%** in the bottom two deciles. Buffers do grow with
income (median **${ft.B.iloc[0]:,.0f} → ${top.B:,.0f}**), but spending grows much faster
(**${ft.S.iloc[0]:,.0f} → ${top.S:,.0f}**), so savings cover only **{top.cover:.1f} months** of spending at the
top versus **{ft.cover.iloc[0]:.1f}** at the bottom. With the real 2026 EI weekly maximum, the top three
deciles are almost all exposed ({ft.fail_cap.iloc[-3]:.0f}–{ft.fail_cap.iloc[-1]:.0f}%).""")
    st.plotly_chart(charts.finding_chart(ft), config={"displayModeBar": False})
    with st.expander("How we checked this"):
        st.markdown(f"""
- Runway uses the judges' definitions (I, S, H, B), EI = 55% of usual income, 6-month window.
- **Pensioners are excluded** ({4500 - int(ft.n.sum())} accounts where pension is 5%+ of income), since a job
  loss would not stop a pension. Including them makes the low-income deciles look even safer.
- Same pattern when we keep only accounts with 24+ months of history (all 3,660 such accounts: top decile 77%,
  bottom decile 6%), so it is not driven by new accounts with little data.
- Rank correlation between income and layoff runway: about −0.68.
- Caveat: "spending" is all money out, including transfers; high earners may move money to savings
  elsewhere that this bank can't see.
""")
        st.dataframe(ft.rename(columns={"band": "Decile", "n": "Customers", "fail": "% run out (EI 55%)",
                                        "fail_cap": "% run out (EI max)", "cover": "Median months covered",
                                        "B": "Median buffer", "S": "Median spending", "I": "Median income"})
                     .round(1), hide_index=True)

st.markdown("""<div class="foot">
<b>About the data.</b> Real anonymized Czech bank data (PKDD'99 Discovery Challenge Financial dataset, CTU Prague
Relational Dataset Repository) converted to CAD by the organizers. These are <b>not Canadian customers</b>.
EI rate (55%) and the 2026 EI maximum ($729/week) are from the Government of Canada; household bills stand in for
rent. Peer groups are income deciles (about 450 customers each) and are broad. Cushion is a demonstration, not
financial advice.</div>""", unsafe_allow_html=True)
