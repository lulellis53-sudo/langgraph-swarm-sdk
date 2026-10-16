"""Tests for the LangSmith tracing switch."""

from __future__ import annotations

import pytest

from orchestration.tracing import tracing_enabled


def test_disabled_without_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LANGSMITH_TRACING", raising=False)
    monkeypatch.setenv("LANGSMITH_API_KEY", "placeholder")
    assert tracing_enabled() is False


def test_disabled_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    assert tracing_enabled() is False


def test_disabled_with_blank_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "   ")
    assert tracing_enabled() is False


def test_enabled_with_flag_and_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LANGSMITH_TRACING", "TRUE")
    monkeypatch.setenv("LANGSMITH_API_KEY", "placeholder")
    assert tracing_enabled() is True


def test_disabled_when_flag_is_false(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    monkeypatch.setenv("LANGSMITH_API_KEY", "placeholder")
    assert tracing_enabled() is False
