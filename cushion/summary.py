"""Plain-English summary: Gemini when available, template otherwise.

Only the customer's summary numbers (no account ID, no transactions) are sent.
The template is always computed first, so the app never depends on the API.
"""
from __future__ import annotations

import json
import os
import queue
import re
import threading
import time

# Asked at the same time; the first valid answer wins. In Nov 2026 tests the larger Flash models
# (3.7, 3.8) timed out server-side and 3.5/3.6 Flash took 6-8 s. The Lite models usually answer
# in about 2 s, but either one occasionally takes 10 s or more.
GEMINI_MODELS = ("gemini-3.5-flash-lite", "gemini-3.1-flash-lite")
TOTAL_BUDGET_S = 8   # worst case the page waits this long before using the template

SYSTEM = (
    "You are Cushion, a friendly financial resilience coach at a Canadian bank. "
    "Write a summary of 2 or 3 short sentences (max 70 words) for a non-expert customer, "
    "speaking to them as 'you'. "
    "Use ONLY the facts you are given, copying numbers and the words 'more'/'less' exactly; "
    "never invent or recompute numbers. "
    "Sentence 1: how the customer compares to similar customers, and how many months their savings cover. "
    "Sentence 2: what the shock does to how long their savings last, and whether they get through the "
    "shock window. Sentence 3: the single next step, as given. "
    "Write natural sentences in plain English; do not repeat the fact labels word for word. "
    "No jargon, no markdown, no greetings."
)


def _pct_phrase(diff: float | None, what: str) -> str | None:
    if diff is None:
        return None
    if abs(diff) < 3:
        return f"spend about the same on {what} as similar customers"
    return f"spend {abs(diff):.0f}% {'more' if diff > 0 else 'less'} on {what} than similar customers"


def _runway_words(r) -> str:
    if isinstance(r, str):
        return "with no monthly shortfall"
    if r <= 0:
        return "with no cushion left at all"
    if r >= 120:
        return "for 10+ years"
    return f"for about {r:.1f} months"


def template_summary(f: dict) -> str:
    comp = _pct_phrase(f.get("bills_vs_peers_pct"), "household bills") \
        or _pct_phrase(f.get("spending_vs_peers_pct"), "everyday spending") \
        or "are compared with customers in the same income band"
    cover = f["cover_months"]
    cover_txt = "almost no savings to fall back on" if cover < 0.5 else \
        f"savings that would cover about {cover:.1f} months of your usual spending"
    s1 = f"You {comp}, with {cover_txt}."
    before, after = f["runway_before"], f["runway_after"]
    if f["shock"] == "none":
        s2 = ("Right now your income covers your spending, so your savings are not being drawn down."
              if isinstance(before, str) else
              ("Right now there is no savings buffer, so any shortfall hits immediately." if before <= 0
               else f"Right now your savings would last {_runway_words(before)}."))
    elif not isinstance(after, str) and after <= 0:
        s2 = (f"With {f['shock']}, there is no savings buffer left to absorb it, so you would not get "
              f"through the {f['duration']}-month window.")
    elif isinstance(after, str):
        s2 = (f"Even with {f['shock']}, your income still covers your spending, "
              f"so you get through the {f['duration']}-month window.")
    else:
        s2 = (f"With {f['shock']}, your savings last {_runway_words(after)} "
              + ("(before: no monthly shortfall), " if isinstance(before, str)
                 else f"(before: {_runway_words(before)}), ")
              + ("so you get through the " if f["makes_it"] else "so you would not get through the ")
              + f"{f['duration']}-month window.")
    s3 = f"Next step: {f['next_step']}."
    return " ".join([s1, s2, s3])


def _runway_fact(r) -> str:
    if isinstance(r, str):
        return "no monthly shortfall (income covers spending)"
    if r <= 0:
        return "0 months (no savings left to draw on)"
    if r >= 120:
        return "10+ years"
    return f"{r:.1f} months"


def _vs_peers(diff) -> str | None:
    if diff is None:
        return None
    if abs(diff) < 3:
        return "about the same as similar customers"
    if diff <= -99:
        return "almost nothing, far below similar customers"
    return f"{abs(diff):.0f}% {'more' if diff > 0 else 'less'} than similar customers"


def llm_facts(f: dict) -> dict:
    """The facts as unambiguous phrases, so the model can't flip a sign or misread a field."""
    d = f["duration"]
    out = {
        "monthly income": f"${f['monthly_income']:,.0f}",
        "monthly spending": f"${f['monthly_spending']:,.0f}",
        "their household bills are": _vs_peers(f.get("bills_vs_peers_pct")),
        "their everyday spending is": _vs_peers(f.get("spending_vs_peers_pct")),
        "their savings cover": f"{(f['cover_months'] if f['cover_months'] > 0 else 0.0):.1f} months of usual spending",
        "the shock": f["shock"],
        "how long savings last today": _runway_fact(f["runway_before"]),
        "with the shock, savings last": _runway_fact(f["runway_after"]),
        "outcome": (f"they get through the {d}-month shock window" if f["makes_it"]
                    else f"they do not get through the {d}-month shock window"),
        "next step": f["next_step"],
    }
    if f["shock"] == "none":
        out["the shock"] = "no shock applied: describe how long their savings last today instead"
        for k in ("with the shock, savings last", "outcome"):
            out.pop(k)
    return {k: v for k, v in out.items() if v is not None}


def _numbers(s: str) -> set[str]:
    return {n.replace(",", "").rstrip(".") for n in re.findall(r"\d[\d,]*\.?\d*", s)}


def looks_ok(text: str, facts: dict) -> bool:
    """Reject output that is cut off or contains a number we did not give the model."""
    if not text or len(text) < 40 or text[-1] not in ".!" or len(text.split()) > 110:
        return False
    allowed = _numbers(json.dumps(facts, ensure_ascii=False))
    allowed |= {n.split(".")[0] for n in allowed} | {"3", "6", "10", "0"}
    return _numbers(text) <= allowed


def gemini_summary(f: dict) -> str | None:
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        try:  # Streamlit Community Cloud secrets
            import streamlit as st
            key = st.secrets.get("GEMINI_API_KEY")
        except Exception:
            key = None
    if not key:
        return None
    try:
        facts = llm_facts(f)
    except Exception:
        return None
    # The client's own timeout is not a hard limit (it can retry or hang), so the call runs in a
    # background thread and we stop waiting after TOTAL_BUDGET_S no matter what.
    box: list[str | None] = [None]
    worker = threading.Thread(target=lambda: box.__setitem__(0, _ask_gemini(key, facts)), daemon=True)
    worker.start()
    worker.join(TOTAL_BUDGET_S)
    return None if worker.is_alive() else box[0]


def _ask_gemini(key: str, facts: dict) -> str | None:
    """Ask every model at once and keep the first answer that passes looks_ok.
    Response times vary a lot from call to call, so racing beats waiting on one model."""
    try:
        from google import genai
        client = genai.Client(api_key=key)
    except Exception:
        return None
    prompt = "Customer facts (CAD):\n" + json.dumps(facts, indent=1, ensure_ascii=False)
    answers: queue.Queue = queue.Queue()

    def ask(model: str) -> None:
        try:
            interaction = client.interactions.create(
                model=model,
                system_instruction=SYSTEM,
                input=prompt,
                generation_config={"thinking_level": "low", "max_output_tokens": 2048},
                timeout=TOTAL_BUDGET_S,
            )
            text = " ".join((getattr(interaction, "output_text", None) or "").split())
            answers.put(text if looks_ok(text, facts) else None)
        except Exception:
            answers.put(None)

    for model in GEMINI_MODELS:
        threading.Thread(target=ask, args=(model,), daemon=True).start()
    deadline = time.monotonic() + TOTAL_BUDGET_S
    for _ in GEMINI_MODELS:
        try:
            text = answers.get(timeout=max(deadline - time.monotonic(), 0))
        except queue.Empty:
            return None
        if text:
            return text
    return None


def summarize(f: dict, use_ai: bool = True) -> tuple[str, str]:
    """Returns (text, source) where source is 'Gemini' or 'template'."""
    if use_ai:
        text = gemini_summary(f)
        if text:
            return text, "Gemini"
    return template_summary(f), "template"
