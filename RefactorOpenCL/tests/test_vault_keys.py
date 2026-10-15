"""Tests for VaultKeyManager OpenAI and Jev Keychain secret management."""

from __future__ import annotations

import getpass
import logging
from collections.abc import Sequence

import pytest

from swarm_sdk import vault


class FakeRunner:
    """Mock runner recording CLI commands and returning preconfigured outputs."""

    def __init__(
        self, answers: dict[str, str | None] | None = None, default: str | None = None
    ) -> None:
        self.answers = answers or {}
        self.default = default
        self.calls: list[list[str]] = []
        self.inputs: list[str] = []

    def __call__(self, argv: Sequence[str], input_text: str | None = None) -> str | None:
        self.calls.append(list(argv))
        if input_text is not None:
            self.inputs.append(input_text)
        cmd_key = argv[0]
        if cmd_key in self.answers:
            return self.answers[cmd_key]
        return self.default


@pytest.fixture(autouse=True)
def use_default_keychain(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SWARM_KEYCHAIN_PATH", raising=False)


def test_known_names_includes_openai_and_jev() -> None:
    assert "OPENAI_API_KEY" in vault.KNOWN_NAMES
    assert "JEV_API_KEY" in vault.KNOWN_NAMES


def test_get_openai_key_from_keychain(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    runner = FakeRunner(default="sk-proj-openai-key-abc")
    key = vault.get_openai_key(runner=runner)
    assert key == "sk-proj-openai-key-abc"
    assert len(runner.calls) == 1
    assert runner.calls[0] == [
        "security",
        "find-generic-password",
        "-s",
        "swarm/OPENAI_API_KEY",
        "-w",
    ]


def test_get_openai_key_env_precedence(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env-override")
    runner = FakeRunner(default="sk-keychain-value")
    key = vault.get_openai_key(runner=runner)
    assert key == "sk-env-override"
    assert runner.calls == []


def test_get_jev_key_from_keychain() -> None:
    runner = FakeRunner(default="jev-test-key-xyz")
    key = vault.get_jev_key(runner=runner)
    assert key == "jev-test-key-xyz"
    assert len(runner.calls) == 1
    assert runner.calls[0] == ["security", "find-generic-password", "-s", "swarm/JEV_API_KEY", "-w"]


def test_set_secret_success() -> None:
    runner = FakeRunner(default="")
    user = getpass.getuser()
    secret = "sk-proj-123456789"
    ok = vault.set_secret("OPENAI_API_KEY", secret, runner=runner)
    assert ok is True
    assert runner.calls == [["/usr/bin/security", "-i"]]
    assert secret not in " ".join(runner.calls[0])
    assert f"-a {user}" in runner.inputs[0]
    assert "-s swarm/OPENAI_API_KEY" in runner.inputs[0]
    assert f"-X {secret.encode().hex()}" in runner.inputs[0]


def test_set_secret_failure() -> None:
    runner = FakeRunner(default=None)
    ok = vault.set_secret("OPENAI_API_KEY", "sk-proj-test", runner=runner)
    assert ok is False


@pytest.mark.parametrize("empty_val", ["", "   ", "\t\n"])
def test_set_secret_rejects_empty_value(empty_val: str) -> None:
    runner = FakeRunner(default="")
    with pytest.raises(ValueError, match="cannot be empty"):
        vault.set_secret("OPENAI_API_KEY", empty_val, runner=runner)
    assert runner.calls == []


@pytest.mark.parametrize(
    "bad_name",
    ["", "bad-name", "lower_key", "1_NUM", "SPACES HERE", "KEY/WITH/SLASH"],
)
def test_set_secret_rejects_invalid_name(bad_name: str) -> None:
    runner = FakeRunner(default="")
    with pytest.raises(vault.VaultError):
        vault.set_secret(bad_name, "valid-secret-value", runner=runner)
    assert runner.calls == []


def test_set_secret_does_not_leak_secret_in_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "SUPER_SENSITIVE_SECRET_XYZ987"

    def broken_runner(argv: Sequence[str], input_text: str) -> str | None:
        raise RuntimeError("Keychain write error")

    with pytest.raises(Exception) as exc_info:
        try:
            vault.set_secret("OPENAI_API_KEY", secret, runner=broken_runner)
        except RuntimeError:
            raise

    assert secret not in str(exc_info.value)


def test_set_secret_does_not_leak_secret_in_logs(caplog: pytest.LogCaptureFixture) -> None:
    secret = "SUPER_SENSITIVE_SECRET_XYZ987"
    runner = FakeRunner(default="")
    with caplog.at_level(logging.DEBUG):
        vault.set_secret("OPENAI_API_KEY", secret, runner=runner)

    for record in caplog.records:
        assert secret not in record.getMessage()


def test_set_openai_key_convenience() -> None:
    runner = FakeRunner(default="")
    ok = vault.set_openai_key("sk-new-openai-key", runner=runner)
    assert ok is True
    assert len(runner.calls) == 1
    assert runner.calls == [["/usr/bin/security", "-i"]]
    assert "-s swarm/OPENAI_API_KEY" in runner.inputs[0]
    assert f"-X {b'sk-new-openai-key'.hex()}" in runner.inputs[0]


def test_set_jev_key_convenience() -> None:
    runner = FakeRunner(default="")
    ok = vault.set_jev_key("jev-new-key-123", runner=runner)
    assert ok is True
    assert len(runner.calls) == 1
    assert runner.calls == [["/usr/bin/security", "-i"]]
    assert "-s swarm/JEV_API_KEY" in runner.inputs[0]
    assert f"-X {b'jev-new-key-123'.hex()}" in runner.inputs[0]


def test_get_secret_fallback_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "env-secret-val")
    runner = FakeRunner(default="keychain-secret-val")

    # fallback_env=True should read from env
    val_env = vault.get_secret("OPENAI_API_KEY", fallback_env=True, runner=runner)
    assert val_env == "env-secret-val"
    assert runner.calls == []

    # fallback_env=False should bypass env and read from Keychain
    val_kc = vault.get_secret("OPENAI_API_KEY", fallback_env=False, runner=runner)
    assert val_kc == "keychain-secret-val"
    assert len(runner.calls) == 1


def test_resolve_alias() -> None:
    runner = FakeRunner(default="resolved-val")
    assert vault.resolve("JEV_API_KEY", runner=runner, environ={}) == "resolved-val"
