"""Vault provider chain (no real Keychain or network)."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from pathlib import Path

import pytest

from swarm_sdk import vault


class FakeRunner:
    """Maps a CLI binary name to stdout; records every call."""

    def __init__(self, answers: dict[str, str | None]) -> None:
        self.answers = answers
        self.calls: list[list[str]] = []

    def __call__(self, argv: Sequence[str]) -> str | None:
        self.calls.append(list(argv))
        return self.answers.get(argv[0])


def test_env_wins_and_skips_cli() -> None:
    runner = FakeRunner({"security": "from-kc"})
    got = vault.get_with_source("MEM0_API_KEY", runner=runner, environ={"MEM0_API_KEY": "e"})
    assert got == ("e", "env")
    assert runner.calls == []


def test_keychain_lookup_argv() -> None:
    runner = FakeRunner({"security": "from-kc"})
    got = vault.get_with_source("MEM0_API_KEY", runner=runner, environ={}, dotenv=Path("/nope"))
    assert got == ("from-kc", "keychain")
    assert runner.calls == [["security", "find-generic-password", "-s", "swarm/MEM0_API_KEY", "-w"]]


def test_dotenv_fallback_parses_export_quotes_equals(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text('# c\nOTHER=1\nexport MEM0_API_KEY="a=b==c"\n')
    got = vault.get_with_source("MEM0_API_KEY", runner=FakeRunner({}), environ={}, dotenv=env)
    assert got == ("a=b==c", "dotenv")


def test_dotenv_warning_never_contains_value(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    env = tmp_path / ".env"
    env.write_text("MEM0_API_KEY=s3cr3t-value\n")
    with caplog.at_level(logging.WARNING):
        vault.get("MEM0_API_KEY", runner=FakeRunner({}), environ={}, dotenv=env)
    assert caplog.records
    assert "s3cr3t-value" not in caplog.text
    assert "MEM0_API_KEY" in caplog.text


def test_all_miss_returns_none(tmp_path: Path) -> None:
    got = vault.get("MEM0_API_KEY", runner=FakeRunner({}), environ={}, dotenv=tmp_path / "x")
    assert got is None


@pytest.mark.parametrize("bad", ["", "lower", "A B", "A/B", "--help", "A" * 65, "1ABC"])
def test_invalid_name_rejected_before_any_cli(bad: str) -> None:
    runner = FakeRunner({"security": "x"})
    with pytest.raises(vault.VaultError):
        vault.get(bad, runner=runner, environ={})
    assert runner.calls == []


def test_run_cli_missing_binary_and_nonzero_are_misses() -> None:
    assert vault.run_cli(["definitely-not-a-binary-xyz"]) is None
    assert vault.run_cli(["false"]) is None


def test_run_cli_timeout_is_a_miss(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(vault, "TIMEOUT_S", 0.2)
    assert vault.run_cli(["sleep", "5"]) is None


def test_load_into_env_sets_missing_only_and_reports_unresolved(tmp_path: Path) -> None:
    runner = FakeRunner({"security": "v"})
    environ = {"KEEP": "orig"}
    missing = vault.load_into_env(
        ["KEEP", "NEW"], runner=runner, environ=environ, dotenv=tmp_path / "x"
    )
    assert environ == {"KEEP": "orig", "NEW": "v"}
    assert missing == []
    gone = vault.load_into_env(["GONE"], runner=FakeRunner({}), environ={}, dotenv=tmp_path / "x")
    assert gone == ["GONE"]


def test_known_names_cover_the_four_provider_keys() -> None:
    assert set(vault.KNOWN_NAMES) == {
        "MEM0_API_KEY",
        "TAVILY_API_KEY",
        "BRAVE_API_KEY",
        "EXA_API_KEY",
    }
