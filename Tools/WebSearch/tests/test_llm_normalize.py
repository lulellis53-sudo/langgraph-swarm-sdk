"""Offline tests for the Gemini-assisted normalization pass (token-saving)."""

from __future__ import annotations

import pytest
from WebSearch.Core.backend import llm_normalize as llm_mod
from WebSearch.Core.backend.llm_normalize import llm_normalize


def _gemini_response(text: str) -> dict:
    """Shape of a generateContent response carrying one text part."""
    return {"candidates": [{"content": {"parts": [{"text": text}]}}]}


def test_falls_back_to_local_cleaner_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """No GOOGLE_API_KEY: local ftfy/noise cleaning runs; no HTTP attempted."""
    for name in ("GOOGLE_API_KEY", "GOOGLE_API_KEY_1", "GOOGLE_API_KEY_2"):
        monkeypatch.delenv(name, raising=False)
    calls: list[str] = []
    from WebSearch.Core.frontend import http_utils

    monkeypatch.setattr(http_utils, "call_json", lambda *a, **k: calls.append("http") or None)
    out = llm_normalize("Itâ€™s a tÃ©st snippet with trailing spaces.   ")
    assert calls == []
    assert "Ã" not in out  # mojibake repaired locally


def test_accepts_strictly_shorter_model_output(monkeypatch: pytest.MonkeyPatch) -> None:
    """A shorter Gemini answer replaces the local cleanup."""
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
    noisy = (
        "Oct 11, 2026 — Cookie policy: we use cookies. Python 3.15 ships lazy "
        "imports. Cookie policy: we use cookies. --- Subscribe now! "
    )
    from WebSearch.Core.frontend import http_utils

    monkeypatch.setattr(
        http_utils,
        "call_json",
        lambda *a, **k: _gemini_response("Python 3.15 ships lazy imports."),
    )
    out = llm_normalize(noisy)
    assert out == "Python 3.15 ships lazy imports."


def test_rejects_longer_model_output(monkeypatch: pytest.MonkeyPatch) -> None:
    """A longer model answer is discarded; the local cleanup wins."""
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
    from WebSearch.Core.frontend import http_utils

    monkeypatch.setattr(
        http_utils,
        "call_json",
        lambda *a, **k: _gemini_response("x" * 500),
    )
    out = llm_normalize("short snippet")
    assert len(out) < 500
    assert "xxxx" not in out


def test_malformed_response_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unexpected JSON shape never raises; local cleanup is returned."""
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
    from WebSearch.Core.frontend import http_utils

    monkeypatch.setattr(http_utils, "call_json", lambda *a, **k: {"error": "quota"})
    out = llm_normalize("Another snippet needing cleanup ... ... done.")
    assert isinstance(out, str)


def test_normalize_tool_reports_char_savings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Webengine Normalize tool cleans docs and reports savings."""
    from WebSearch.Webengine import Normalize

    monkeypatch.setattr(llm_mod, "llm_normalize", lambda text, **k: "clean")
    tool = Normalize()
    assert tool.name == "web_normalize"
    result = tool.invoke({"documents": [{"url": "https://a.example/1", "text": "dirty text here"}]})
    assert result["count"] == 1
    assert result["documents"][0]["text"] == "clean"
    assert result["chars_saved"] == len("dirty text here") - len("clean")


def test_packaged_yaml_uses_gemini_38() -> None:
    """providers.yaml pins the google_search engine to gemini-3.8-flash."""
    from WebSearch.Core.frontend.registry import load_providers

    spec = next(s for s in load_providers().searchers if s.id == "google_search")
    assert spec.engine == "gemini-3.8-flash"
