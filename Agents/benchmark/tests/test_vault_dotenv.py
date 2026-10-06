"""Encrypted ``.env`` entries: Fernet key in the Keychain, ciphertext in the file."""

from __future__ import annotations

import logging
import stat
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from swarm_sdk import vault

SECRET = "oauth-token-0123456789-abcdef"


class FakeKeychain:
    """Stands in for ``security find-generic-password`` and the key writer."""

    def __init__(self) -> None:
        self.items: dict[str, str] = {}

    def run(self, argv: Sequence[str]) -> str | None:
        service = argv[argv.index("-s") + 1].removeprefix("swarm/")
        return self.items.get(service)

    def store(self, name: str, value: str) -> None:
        self.items[name] = value


@pytest.fixture
def keychain(monkeypatch: pytest.MonkeyPatch) -> FakeKeychain:
    monkeypatch.delenv("SWARM_KEYCHAIN_PATH", raising=False)
    fake = FakeKeychain()
    monkeypatch.setattr(vault, "_store_via_stdin", fake.store)
    return fake


def test_encrypt_round_trip_creates_the_key_once(keychain: FakeKeychain) -> None:
    token = vault.encrypt_value(SECRET, runner=keychain.run)
    assert token.startswith("enc:v1:") and SECRET not in token
    assert set(keychain.items) == {"DOTENV_FERNET_KEY"}
    key = keychain.items["DOTENV_FERNET_KEY"]
    assert vault.decrypt_value(token, runner=keychain.run) == SECRET
    vault.encrypt_value("another", runner=keychain.run)
    assert keychain.items["DOTENV_FERNET_KEY"] == key  # reused, not regenerated


def test_decrypt_is_none_without_the_key_or_for_a_tampered_or_foreign_token(
    keychain: FakeKeychain,
) -> None:
    token = vault.encrypt_value(SECRET, runner=keychain.run)
    assert vault.decrypt_value(token, runner=FakeKeychain().run) is None  # no key
    assert vault.decrypt_value(token[:-4] + "AAAA", runner=keychain.run) is None  # tampered
    assert vault.decrypt_value("plain-value", runner=keychain.run) is None  # not enc:v1:
    from cryptography.fernet import Fernet

    other = FakeKeychain()
    other.items["DOTENV_FERNET_KEY"] = Fernet.generate_key().decode()  # a different key
    assert vault.decrypt_value(token, runner=other.run) is None


def test_empty_values_are_refused(keychain: FakeKeychain) -> None:
    with pytest.raises(ValueError, match="empty"):
        vault.encrypt_value("", runner=keychain.run)


def test_write_dotenv_entry_replaces_one_line_keeps_the_rest_and_is_0600(
    keychain: FakeKeychain, tmp_path: Path
) -> None:
    env = tmp_path / ".env"
    env.write_text("# comment\nA=1\nexport CODEX_OAUTH_TOKEN=old-plain\nB=2\n")
    env.chmod(0o644)
    vault.write_dotenv_entry(env, "CODEX_OAUTH_TOKEN", SECRET, runner=keychain.run)
    text = env.read_text()
    lines = text.splitlines()
    assert lines[0] == "# comment" and lines[1] == "A=1" and lines[3] == "B=2"
    assert lines[2].startswith("CODEX_OAUTH_TOKEN=enc:v1:")
    assert SECRET not in text and "old-plain" not in text
    assert stat.S_IMODE(env.stat().st_mode) == 0o600
    assert not (tmp_path / ".env.tmp").exists()
    vault.write_dotenv_entry(env, "NEW_NAME", "v", runner=keychain.run)  # appended
    assert env.read_text().splitlines()[-1].startswith("NEW_NAME=enc:v1:")
    with pytest.raises(vault.VaultError):
        vault.write_dotenv_entry(env, "bad name", "v", runner=keychain.run)


def test_get_reads_the_encrypted_entry_and_labels_the_source(
    keychain: FakeKeychain, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    env = tmp_path / ".env"
    vault.write_dotenv_entry(env, "CODEX_OAUTH_TOKEN", SECRET, runner=keychain.run)
    with caplog.at_level(logging.WARNING):
        found = vault.get_with_source(
            "CODEX_OAUTH_TOKEN", runner=keychain.run, dotenv=env, environ={}
        )
    assert found == (SECRET, "dotenv-encrypted")
    assert "plaintext" not in caplog.text and SECRET not in caplog.text


def test_get_warns_for_plaintext_and_fails_closed_without_the_key(
    keychain: FakeKeychain, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    env = tmp_path / ".env"
    env.write_text("PLAIN_TOKEN=plain-value\n")
    with caplog.at_level(logging.WARNING):
        found = vault.get_with_source("PLAIN_TOKEN", runner=keychain.run, dotenv=env, environ={})
    assert found == ("plain-value", "dotenv") and "plaintext" in caplog.text

    vault.write_dotenv_entry(env, "ENC_TOKEN", SECRET, runner=keychain.run)
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        missing = vault.get_with_source(
            "ENC_TOKEN", runner=FakeKeychain().run, dotenv=env, environ={}
        )
    assert missing is None and "cannot decrypt ENC_TOKEN" in caplog.text
    assert SECRET not in caplog.text


def test_dotenv_set_cli_prompts_encrypts_and_never_echoes_the_value(
    keychain: FakeKeychain,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    env = tmp_path / ".env"
    monkeypatch.setattr(vault.getpass, "getpass", lambda prompt="": f"  {SECRET}  ")
    assert vault.main(["dotenv-set", "CODEX_OAUTH_TOKEN", str(env)], runner=keychain.run) == 0
    out = capsys.readouterr()
    assert SECRET not in out.out + out.err and "stored encrypted" in out.out
    assert vault.get("CODEX_OAUTH_TOKEN", runner=keychain.run, dotenv=env, environ={}) == SECRET
    monkeypatch.setattr(vault.getpass, "getpass", lambda prompt="": "   ")
    assert vault.main(["dotenv-set", "CODEX_OAUTH_TOKEN", str(env)], runner=keychain.run) == 2
    assert vault.main(["dotenv-set"], runner=keychain.run) == 2


def test_settings_import_does_not_export_ciphertext_as_an_environment_variable(
    tmp_path: Path,
) -> None:
    (tmp_path / ".env").write_text("CODEX_OAUTH_TOKEN=enc:v1:abc\nPLAIN_OK=1\n")
    code = (
        "import os, swarm_sdk.config.settings;"
        "print(os.environ.get('CODEX_OAUTH_TOKEN'), os.environ.get('PLAIN_OK'))"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env={"HOME": str(tmp_path), "PATH": "/usr/bin:/bin", "PYTHONPATH": ":".join(sys.path)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.stdout.strip() == "None 1", proc.stderr[-300:]


def test_a_key_that_cannot_be_read_back_raises_instead_of_encrypting_with_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SWARM_KEYCHAIN_PATH", raising=False)
    monkeypatch.setattr(vault, "_store_via_stdin", lambda name, value: None)  # silently fails
    with pytest.raises(vault.VaultError, match="could not store"):
        vault.encrypt_value(SECRET, runner=lambda argv: None)


def test_the_key_is_stored_through_stdin_not_argv(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SWARM_KEYCHAIN_PATH", raising=False)
    seen: dict[str, Any] = {}

    def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        seen.update(argv=argv, **kwargs)
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(vault.subprocess, "run", fake_run)
    vault._store_via_stdin("DOTENV_FERNET_KEY", "k" * 44)
    argv = [str(part) for part in seen["argv"]]
    assert argv == ["/usr/bin/security", "-i"]
    assert ("k" * 44) not in " ".join(argv)
    assert ("k" * 44).encode().hex() in str(seen["input"])


def test_set_with_a_dedicated_keychain_prompts_here_and_verifies(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("SWARM_KEYCHAIN_PATH", str(tmp_path / "vault.keychain-db"))
    monkeypatch.setattr(vault.getpass, "getpass", lambda prompt="": f" {SECRET} ")
    store: dict[str, str] = {}
    monkeypatch.setattr(vault, "_store_via_stdin", lambda name, value: store.update({name: value}))
    monkeypatch.setattr(vault.subprocess, "run", lambda *a, **k: pytest.fail("no argv path"))

    def runner(argv: Sequence[str]) -> str | None:
        assert argv[-1].endswith("vault.keychain-db")  # reads the dedicated keychain too
        return store.get(argv[argv.index("-s") + 1].removeprefix("swarm/"))

    assert vault.main(["set", "BRAVE_API_KEY"], runner=runner) == 0
    out = capsys.readouterr()
    assert store == {"BRAVE_API_KEY": SECRET} and SECRET not in out.out + out.err
    monkeypatch.setattr(vault, "_store_via_stdin", lambda name, value: None)  # silent failure
    assert vault.main(["set", "BRAVE_API_KEY"], runner=lambda argv: None) == 1
    monkeypatch.setattr(vault.getpass, "getpass", lambda prompt="": "  ")
    assert vault.main(["set", "BRAVE_API_KEY"], runner=runner) == 2


def test_set_secret_without_a_runner_uses_stdin_and_confirms(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SWARM_KEYCHAIN_PATH", raising=False)
    monkeypatch.setattr(vault.sys, "platform", "darwin")
    store: dict[str, str] = {}
    monkeypatch.setattr(vault, "_store_via_stdin", lambda name, value: store.update({name: value}))
    monkeypatch.setattr(vault, "run_cli", lambda argv: store.get("JEV_API_KEY"))
    assert vault.set_secret("JEV_API_KEY", SECRET) is True and store["JEV_API_KEY"] == SECRET
    monkeypatch.setattr(vault, "run_cli", lambda argv: None)  # read-back finds nothing
    assert vault.set_secret("JEV_API_KEY", SECRET) is False
