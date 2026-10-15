"""Sentry config loader tests: env-var names only, no-op without a DSN."""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest
from swarm_sdk.observability.sentry import (
    SentryFileConfig,
    default_sentry_config_path,
    init_sentry,
    load_sentry_config,
)

REPO_SENTRY_YAML = Path(__file__).resolve().parents[3] / "Main" / "config" / "sentry.yaml"

MINIMAL_YAML = """\
version: 1
sdk:
  dsn_env: TEST_SENTRY_DSN
  environment_env: TEST_SENTRY_ENV
  traces_sample_rate: 0.25
  send_default_pii: false
"""


@pytest.fixture
def config_file(tmp_path: Path) -> Path:
    path = tmp_path / "sentry.yaml"
    path.write_text(MINIMAL_YAML, encoding="utf-8")
    return path


def test_loads_repo_sentry_config_env_names_only() -> None:
    """The repo file parses and exposes env-var names, never a DSN value."""
    cfg = load_sentry_config(REPO_SENTRY_YAML)
    assert cfg is not None
    assert cfg.sdk.dsn_env == "SENTRY_DSN"
    assert cfg.sdk.environment_env == "SENTRY_ENVIRONMENT"
    assert cfg.sdk.traces_sample_rate == pytest.approx(0.1)
    assert cfg.sdk.send_default_pii is False


def test_missing_config_returns_none(tmp_path: Path) -> None:
    assert load_sentry_config(tmp_path / "absent.yaml") is None


def test_non_mapping_config_returns_none(tmp_path: Path) -> None:
    path = tmp_path / "sentry.yaml"
    path.write_text("- just\n- a\n- list\n", encoding="utf-8")
    assert load_sentry_config(path) is None


def test_default_path_respects_env_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "custom-sentry.yaml"
    target.write_text(MINIMAL_YAML, encoding="utf-8")
    monkeypatch.setenv("SWARM_SENTRY_CONFIG", str(target))
    resolved = default_sentry_config_path()
    assert resolved == target
    assert load_sentry_config() == SentryFileConfig.model_validate(
        {
            "sdk": {
                "dsn_env": "TEST_SENTRY_DSN",
                "environment_env": "TEST_SENTRY_ENV",
                "traces_sample_rate": 0.25,
            }
        }
    )


def test_init_sentry_is_noop_without_dsn(
    config_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("TEST_SENTRY_DSN", raising=False)
    assert init_sentry(config_file) is False


def test_init_sentry_is_noop_without_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TEST_SENTRY_DSN", "https://key@example.ingest.sentry.io/1")
    assert init_sentry(tmp_path / "absent.yaml") is False


def test_init_sentry_passes_config_values_and_never_logs_the_dsn(
    config_file: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    dsn = "https://secret-key@example.ingest.sentry.io/1"
    monkeypatch.setenv("TEST_SENTRY_DSN", dsn)
    monkeypatch.setenv("TEST_SENTRY_ENV", "bench")
    stub = types.ModuleType("sentry_sdk")
    captured: dict[str, object] = {}

    def fake_init(**kwargs: object) -> None:
        captured.update(kwargs)

    stub.init = fake_init  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "sentry_sdk", stub)

    with caplog.at_level("DEBUG"):
        assert init_sentry(config_file) is True

    assert captured == {
        "dsn": dsn,
        "environment": "bench",
        "traces_sample_rate": 0.25,
        "send_default_pii": False,
    }
    assert dsn not in caplog.text
