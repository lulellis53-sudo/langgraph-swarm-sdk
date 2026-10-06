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

    def __call__(self, argv: Sequence[str]) -> str | None:
        self.calls.append(list(argv))
        cmd_key = argv[0]
        if cmd_key in self.answers:
            return self.answers[cmd_key]
        return self.default


def test_known_names_includes_openai_and_jev() -> None:
    assert "OPENAI_API_KEY" in vault.KNOWN_NAMES
    assert "JEV_API_KEY" in vault.KNOWN_NAMES


def test_get_openai_key_from_keychain() -> None:
    runner = FakeRunner(default="sk-proj-openai-key-abc")
    key = vault.get_openai_key(runner=runner)
    assert key == "sk-proj-openai-key-abc"
    assert len(runner.calls) == 1
    call = runner.calls[0]
    # Assert the contract, not the whole argv: a dedicated Keychain path
    # (SWARM_KEYCHAIN_PATH) appends an extra argument when configured.
    assert call[:5] == ["security", "find-generic-password", "-s", "swarm/OPENAI_API_KEY", "-w"]


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
    assert runner.calls[0][:5] == [
        "security",
        "find-generic-password",
        "-s",
        "swarm/JEV_API_KEY",
        "-w",
    ]


def test_set_secret_success() -> None:
    runner = FakeRunner(default="")
    user = getpass.getuser()
    secret = "sk-proj-123456789"
    ok = vault.set_secret("OPENAI_API_KEY", secret, runner=runner)
    assert ok is True
    assert len(runner.calls) == 1
    call = runner.calls[0]
    assert call[0] == "/usr/bin/security"
    assert call[1] == "add-generic-password"
    assert "-s" in call and call[call.index("-s") + 1] == "swarm/OPENAI_API_KEY"
    assert "-a" in call and call[call.index("-a") + 1] == user
    assert "-w" in call and call[call.index("-w") + 1] == secret
    assert "-U" in call


def test_read_falls_back_to_secondary_namespace() -> None:
    """A key absent from ``swarm/`` is read from ``APIKEYCHAIN/`` (read-only fallback)."""

    def runner(argv: Sequence[str]) -> str | None:
        service = argv[argv.index("-s") + 1]
        return "jina-test-value" if service == "APIKEYCHAIN/JINA_API_KEY" else None

    assert vault.get("JINA_API_KEY", runner=runner, environ={}) == "jina-test-value"


def test_primary_namespace_wins_over_fallback() -> None:
    """When both namespaces hold the key, ``swarm/`` is authoritative."""

    def runner(argv: Sequence[str]) -> str | None:
        service = argv[argv.index("-s") + 1]
        if service == "swarm/TAVILY_API_KEY":
            return "primary-value"
        if service == "APIKEYCHAIN/TAVILY_API_KEY":
            return "fallback-value"
        return None

    assert vault.get("TAVILY_API_KEY", runner=runner, environ={}) == "primary-value"


def test_fallback_reads_only_when_primary_is_empty() -> None:
    """The fallback namespace is not queried once the primary namespace answers."""

    seen: list[str] = []

    def runner(argv: Sequence[str]) -> str | None:
        service = argv[argv.index("-s") + 1]
        seen.append(service)
        return "primary-value" if service == "swarm/BRAVE_API_KEY" else None

    assert vault.get("BRAVE_API_KEY", runner=runner, environ={}) == "primary-value"
    assert seen == ["swarm/BRAVE_API_KEY"]


def test_fallback_read_uses_default_keychain_search_list() -> None:
    """Fallback lookups must not pin the dedicated Keychain; those items live in the login one."""

    def runner(argv: Sequence[str]) -> str | None:
        service = argv[argv.index("-s") + 1]
        return "api-keychain-value" if service.startswith("APIKEYCHAIN/") else None

    vault.get("EXA_API_KEY", runner=runner, environ={})
    # The fallback probe appends nothing beyond "-w" (no dedicated keychain path).
    assert vault._find_cmd_default("APIKEYCHAIN/EXA_API_KEY") == [
        "security",
        "find-generic-password",
        "-s",
        "APIKEYCHAIN/EXA_API_KEY",
        "-w",
    ]


def test_fallbacks_can_be_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """``SWARM_KEYCHAIN_FALLBACKS=""`` restores primary-only reads."""
    monkeypatch.setenv("SWARM_KEYCHAIN_FALLBACKS", "")
    assert vault._fallback_prefixes() == ()

    def runner(argv: Sequence[str]) -> str | None:
        service = argv[argv.index("-s") + 1]
        return "only-fallback" if service.startswith("APIKEYCHAIN/") else None

    assert vault.get("JINA_API_KEY", runner=runner, environ={}) is None


def test_write_verification_stays_primary_only() -> None:
    """A write must never verify against a fallback item, or a failed write looks successful."""
    assert vault._find_cmd("JINA_API_KEY")[3] == "swarm/JINA_API_KEY"


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

    def broken_runner(argv: Sequence[str]) -> str | None:
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
    call = runner.calls[0]
    assert call[call.index("-s") + 1] == "swarm/OPENAI_API_KEY"
    assert call[call.index("-w") + 1] == "sk-new-openai-key"


def test_set_jev_key_convenience() -> None:
    runner = FakeRunner(default="")
    ok = vault.set_jev_key("jev-new-key-123", runner=runner)
    assert ok is True
    assert len(runner.calls) == 1
    call = runner.calls[0]
    assert call[call.index("-s") + 1] == "swarm/JEV_API_KEY"
    assert call[call.index("-w") + 1] == "jev-new-key-123"


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
