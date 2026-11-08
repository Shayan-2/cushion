import pytest

from cushion import summary


@pytest.fixture(autouse=True)
def never_call_gemini(monkeypatch):
    """Tests must never hit the network, even if a key is in the env or .streamlit/secrets.toml."""
    monkeypatch.setattr(summary, "_ask_gemini", lambda key, facts: None)
