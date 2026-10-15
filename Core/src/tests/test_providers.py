"""Provider routing tests that never make a model request."""

import pytest

from langswarm.providers import PROVIDERS, parse_model_id, provider_status


def test_parse_provider_model_pair() -> None:
    assert parse_model_id("groq:llama-3") == ("groq", "llama-3")
    assert parse_model_id("gpt-4o") == ("openai", "gpt-4o")


def test_provider_status_never_returns_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-only")
    rows = provider_status()
    assert set(PROVIDERS) == {row["provider"] for row in rows}
    assert all("test-only" not in str(row.values()) for row in rows)
    assert next(row for row in rows if row["provider"] == "openai")["key_set"] is True
