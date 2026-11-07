"""Smoke-test the whole Streamlit app headlessly: many accounts x every shock preset."""
import os

import pytest
from streamlit.testing.v1 import AppTest

from cushion.engine import PRESETS

APP = os.path.join(os.path.dirname(__file__), "..", "app.py")

ACCOUNTS = [
    31431,  # comfortable
    20854,  # spends more than earns
    20134,  # running loan
    57247,  # loan in arrears, negative buffer
    20253,  # pensioner
    32078,  # negative buffer
    21132,  # zero income and zero spending
    26939,  # zero income, some spending
    49649,  # only 12 months of data
    42988,  # high income, loan D
]


@pytest.fixture(autouse=True)
def no_ai(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)


def run(acct=None, preset=None, mode=None, timeout=30):
    at = AppTest.from_file(APP, default_timeout=timeout)
    at.run()
    if mode:
        at.radio(key="mode").set_value(mode).run()
    if acct is not None:
        at.text_input(key="acct_text").set_value(str(acct)).run()
    if preset:
        idx = list(PRESETS).index(preset)
        at.button(key=f"p_{idx}").click().run()
    return at


@pytest.mark.parametrize("acct", ACCOUNTS)
@pytest.mark.parametrize("preset", list(PRESETS))
def test_every_account_and_preset(acct, preset):
    at = run(acct, preset)
    assert not at.exception, at.exception
    assert not at.error, [e.value for e in at.error]
    assert at.markdown  # rendered something


@pytest.mark.parametrize("bad", ["99999999", "abc", "", "12"])
def test_unknown_ids_show_friendly_message(bad):
    at = run(bad)
    assert not at.exception
    assert at.error or at.warning


def test_manual_mode():
    at = run(mode="Manual entry", preset="Job loss + bills up 15%")
    assert not at.exception
    at.slider(key="m_savings").set_value(0).run()
    assert not at.exception


def test_custom_shock_sliders():
    at = run(20854)
    at.slider(key="bills_pct").set_value(50).run()
    at.slider(key="oneoff_months").set_value(3.0).run()
    at.number_input(key="oneoff_dollars").set_value(5000).run()
    at.checkbox(key="ei_cap").check().run()
    assert not at.exception
