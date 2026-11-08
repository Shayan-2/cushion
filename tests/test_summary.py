"""Summary guards: what is sent to Gemini, and which Gemini answers are accepted. No network."""
from cushion import summary as s

FACTS = {
    "monthly_income": 3747, "monthly_spending": 4098, "household_bills": 1046, "savings_buffer": 10346,
    "bills_vs_peers_pct": 28, "spending_vs_peers_pct": -1, "cover_months": 2.5,
    "shock": "a job loss with EI paying 55% of income", "duration": 6,
    "runway_before": 29.5, "runway_after": 5.1, "makes_it": False,
    "next_step": "cut flexible spending by $506/month, which stretches the runway to 6.8 months",
}


def test_facts_spell_out_direction():
    f = s.llm_facts(FACTS)
    assert f["their household bills are"] == "28% more than similar customers"
    assert f["their everyday spending is"] == "about the same as similar customers"
    assert s.llm_facts({**FACTS, "bills_vs_peers_pct": -41})["their household bills are"].startswith("41% less")


def test_facts_never_include_account_id_or_raw_fields():
    f = s.llm_facts({**FACTS, "account_id": 20854})
    assert "20854" not in str(f)
    assert all("pct" not in k for k in f)


def test_negative_cover_is_clamped():
    assert s.llm_facts({**FACTS, "cover_months": -0.04})["their savings cover"].startswith("0.0 months")


def test_no_shock_drops_after_fields():
    f = s.llm_facts({**FACTS, "shock": "none", "runway_after": 29.5, "makes_it": True})
    assert not any("with the shock" in k or "window" in k for k in f)


def test_special_runways_are_words():
    f = s.llm_facts({**FACTS, "runway_before": "no shortfall (120+)", "runway_after": 0.0})
    assert f["how long savings last today"].startswith("no monthly shortfall")
    assert f["with the shock, savings last"].startswith("0 months")


GOOD = ("Your household bills are 28% more than similar customers, and your savings cover 2.5 months. "
        "After a job loss, your savings last 5.1 months, so you do not get through the 6-month window. "
        "Cut flexible spending by $506/month, which stretches the runway to 6.8 months.")


def test_accepts_faithful_text():
    assert s.looks_ok(GOOD, s.llm_facts(FACTS))


def test_rejects_invented_number():
    assert not s.looks_ok(GOOD.replace("5.1 months", "7.4 months"), s.llm_facts(FACTS))
    assert not s.looks_ok(GOOD.replace("$506", "$600"), s.llm_facts(FACTS))


def test_rejects_cut_off_or_empty_text():
    f = s.llm_facts(FACTS)
    assert not s.looks_ok(GOOD[:150], f)
    assert not s.looks_ok("", f)


def test_hung_api_falls_back_within_budget(monkeypatch):
    import time
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(s, "TOTAL_BUDGET_S", 0.5)
    monkeypatch.setattr(s, "_ask_gemini", lambda key, facts: time.sleep(5) or "late")
    t = time.monotonic()
    text, src = s.summarize(FACTS)
    assert src == "template" and time.monotonic() - t < 1.5


def test_gemini_text_is_used_when_it_passes(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(s, "_ask_gemini", lambda key, facts: GOOD)
    assert s.summarize(FACTS) == (GOOD, "Gemini")


def test_no_key_uses_template(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(s, "gemini_summary", lambda f: None)
    text, src = s.summarize(FACTS)
    assert src == "template" and "5.1 months" in text
