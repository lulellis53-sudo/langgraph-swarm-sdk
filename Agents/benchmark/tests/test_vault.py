"""Vault provider chain (no real Keychain or network)."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from pathlib import Path

import pytest

from swarm_sdk import vault


@pytest.fixture(autouse=True)
def use_default_keychain(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SWARM_KEYCHAIN_PATH", raising=False)
    monkeypatch.setattr(vault, "_PROJECT_ENV", Path("/no-project-env"))


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


def test_dedicated_keychain_path_is_used_for_lookup(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "vault.keyychain"
    monkeypatch.setenv("SWARM_KEYCHAIN_PATH", str(path))
    runner = FakeRunner({"security": "from-kc"})

    assert vault.get_with_source("MEM0_API_KEY", runner=runner, environ={}) == (
        "from-kc",
        "keychain",
    )
    assert runner.calls[0][-1] == str(path)


def test_owner_only_project_env_selects_dedicated_keychain(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    env = tmp_path / ".env"
    env.write_text("SWARM_KEYCHAIN_PATH=/tmp/test.keychain\n")
    env.chmod(0o600)
    monkeypatch.setattr(vault, "_PROJECT_ENV", env)
    runner = FakeRunner({"security": "from-kc"})
    vault.get_with_source("MEM0_API_KEY", runner=runner, environ={})
    assert runner.calls[0][-1] == "/tmp/test.keychain"


def test_shared_project_env_cannot_select_keychain(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    env = tmp_path / ".env"
    env.write_text("SWARM_KEYCHAIN_PATH=/tmp/test.keychain\n")
    env.chmod(0o644)
    monkeypatch.setattr(vault, "_PROJECT_ENV", env)
    runner = FakeRunner({"security": "from-kc"})
    vault.get_with_source("MEM0_API_KEY", runner=runner, environ={})
    assert runner.calls[0][-1] == "-w"


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
        "OPENAI_API_KEY",
        "JEV_API_KEY",
    }


def test_status_prints_source_never_value(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("MEM0_API_KEY", raising=False)
    runner = FakeRunner({"security": "topsecret"})
    rc = vault.main(["status", "MEM0_API_KEY"], runner=runner)
    out = capsys.readouterr().out
    assert rc == 0
    assert "MEM0_API_KEY: keychain" in out
    assert "topsecret" not in out


def test_status_defaults_to_known_names_and_reports_missing(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in vault.KNOWN_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(vault.Path, "home", lambda: Path("/nonexistent-home"))
    assert vault.main(["status"], runner=FakeRunner({})) == 1
    out = capsys.readouterr().out
    for name in vault.KNOWN_NAMES:
        assert f"{name}: missing" in out


def test_set_delegates_prompt_to_security(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[list[str]] = []

    class Done:
        returncode = 0

    def fake_run(argv: list[str], **kwargs: object) -> Done:
        seen.append(argv)
        assert "capture_output" not in kwargs  # stdio inherited so security can prompt
        return Done()

    monkeypatch.setattr(vault.subprocess, "run", fake_run)
    assert vault.main(["set", "MEM0_API_KEY"]) == 0
    argv = seen[0]
    assert argv[:2] == ["security", "add-generic-password"]
    assert argv[argv.index("-s") + 1] == "swarm/MEM0_API_KEY"
    assert argv[-1] == "-w"  # nothing after -w: security prompts for the value


def test_set_rejects_bad_name(capsys: pytest.CaptureFixture[str]) -> None:
    assert vault.main(["set", "bad name"]) == 2
    assert "invalid secret name" in capsys.readouterr().err


def test_env_example_lists_only_names() -> None:
    path = Path(__file__).resolve().parents[3] / ".env.example"
    rows = [r for r in path.read_text().splitlines() if r.strip() and not r.startswith("#")]
    assert {r.partition("=")[0] for r in rows} == set(vault.KNOWN_NAMES)
    assert all(r.partition("=")[2] == "" for r in rows)


def test_http_entrypoint_primes_referenced_names(monkeypatch: pytest.MonkeyPatch) -> None:
    import swarm_sdk.serving.http as http

    calls: list[list[str]] = []
    monkeypatch.setattr(
        http, "prime_runtime_secrets", lambda **_: calls.append(list(vault.referenced_names()))
    )
    monkeypatch.setattr("uvicorn.run", lambda *a, **k: None)
    http.main()
    assert calls == [list(vault.referenced_names())]


def test_import_stores_via_stdin_never_argv_or_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    src = tmp_path / "keys.csv"
    src.write_text(
        'name,value\nTAVILY_API_KEY,tvly-SECRET1\nexport EXA_API_KEY="exa SECRET"\nbad name=x\n'
    )
    calls: list[tuple[list[str], str]] = []

    class Done:
        returncode = 0

    def fake_run(argv: list[str], **kwargs: object) -> Done:
        calls.append((argv, str(kwargs["input"])))
        return Done()

    monkeypatch.setattr(vault.subprocess, "run", fake_run)
    assert vault.main(["import", str(src)]) == 1  # one skipped
    out = capsys.readouterr().out
    assert "stored: TAVILY_API_KEY" in out and "skipped: EXA_API_KEY, bad name" in out
    assert "SECRET" not in out
    assert len(calls) == 1
    argv, stdin = calls[0]
    assert argv == ["security", "-i"]  # no value on argv
    assert "-s swarm/TAVILY_API_KEY" in stdin and "tvly-SECRET1" in stdin


def test_prime_runtime_secrets_fills_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Priming resolves referenced names into the env exactly once."""
    import swarm_sdk.vault as vault

    monkeypatch.setattr(vault, "_PRIMED", False)
    env: dict[str, str] = {}
    unresolved = vault.prime_runtime_secrets(
        runner=lambda argv: "kc-value" if any("MEM0_API_KEY" in a for a in argv) else None,
        environ=env,
    )
    assert env.get("MEM0_API_KEY") == "kc-value"
    assert "MEM0_API_KEY" not in unresolved
    assert vault._PRIMED is True
    assert vault.prime_runtime_secrets(environ=env) == []


def test_referenced_names_cover_swarm_and_search() -> None:
    import swarm_sdk.vault as vault

    names = vault.referenced_names()
    assert "OPENAI_API_KEY" in names  # swarm.yaml router
    assert "TAVILY_API_KEY" in names and "MEM0_API_KEY" in names  # KNOWN_NAMES


def test_set_with_dedicated_keychain_sends_value_on_stdin(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SWARM_KEYCHAIN_PATH", str(tmp_path / "swarm.keychain-db"))
    monkeypatch.setattr(vault.getpass, "getpass", lambda prompt="": "s3cret")
    seen: dict[str, object] = {}

    class Done:
        returncode = 0

    def fake_run(argv: list[str], **kwargs: object) -> Done:
        seen["argv"] = argv
        seen["input"] = kwargs.get("input")
        return Done()

    monkeypatch.setattr(vault.subprocess, "run", fake_run)
    monkeypatch.setattr(vault.sys, "platform", "darwin")
    assert vault.main(["set", "MEM0_API_KEY"]) == 0
    assert seen["argv"] == ["/usr/bin/security", "-i"]
    command = str(seen["input"])
    assert "s3cret" not in command  # hex-encoded, never plain
    assert command.rstrip().endswith(f'"{tmp_path / "swarm.keychain-db"}"')
