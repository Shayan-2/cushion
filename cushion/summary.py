"""Plain-English summary: Gemini when available, template otherwise.

Only the customer's summary numbers (no account ID, no transactions) are sent.
The template is always computed first, so the app never depends on the API.
"""
from __future__ import annotations

import json
import os

GEMINI_MODEL = "gemini-3.8-flash"
TIMEOUT_S = 8

SYSTEM = (
    "You are Cushion, a friendly financial resilience coach at a Canadian bank. "
    "Write a summary of 2 or 3 short sentences (max 70 words) for a non-expert customer. "
    "Use ONLY the numbers in the JSON you are given, rounded as shown; never invent numbers. "
    "Sentence 1: how the customer compares to similar customers (bills or spending, and how many "
    "months their savings cover). Sentence 2: what the shock does to their runway and whether they "
    "make it through the shock window. Sentence 3: the single most useful next step from the plan. "
    "Plain English, no jargon, no markdown, no greetings, dollars in CAD."
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
    if f["shock"] == "none":
        s2 = f"Right now your money would last {_runway_words(f['runway_before'])}."
    else:
        s2 = (f"With {f['shock']}, your buffer lasts {_runway_words(f['runway_after'])} "
              f"(before: {_runway_words(f['runway_before'])}), "
              + ("so you get through the "
                 if f["makes_it"] else "so you would not get through the ")
              + f"{f['duration']}-month window.")
    s3 = f"Next step: {f['next_step']}."
    return " ".join([s1, s2, s3])


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
        from google import genai
        client = genai.Client(api_key=key)
        interaction = client.interactions.create(
            model=GEMINI_MODEL,
            system_instruction=SYSTEM,
            input="Customer numbers (CAD):\n" + json.dumps(f),
            generation_config={"thinking_level": "low", "max_output_tokens": 1024},
            timeout=TIMEOUT_S,
        )
        text = (getattr(interaction, "output_text", None) or "").strip()
        return text or None
    except Exception:
        return None


def summarize(f: dict, use_ai: bool = True) -> tuple[str, str]:
    """Returns (text, source) where source is 'Gemini' or 'template'."""
    if use_ai:
        text = gemini_summary(f)
        if text:
            return text, "Gemini"
    return template_summary(f), "template"
