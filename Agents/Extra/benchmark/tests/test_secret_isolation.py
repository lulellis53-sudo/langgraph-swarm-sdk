"""Credentials stay out of tests, tracked files and outbound prompts."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from swarm_sdk import vault
from swarm_sdk.redact import REDACTED, SECRET_RE, redact_secrets

_ROOT = Path(__file__).resolve().parents[3]
# test_config.py feeds this literal to the loader to prove an inline api_key is rejected.
_REJECTION_FIXTURE = 'bad = {"api_key": "sk-'


def test_tests_cannot_resolve_any_registry_secret() -> None:
    names = vault.referenced_names()
    assert names
    assert all(name not in os.environ for name in names)
    assert all(vault.get(name) is None for name in names)


def test_dotenv_is_owner_only_and_untracked() -> None:
    env_file = _ROOT / ".env"
    if env_file.exists():
        assert env_file.stat().st_mode & 0o077 == 0, ".env must be chmod 600"
    tracked = subprocess.run(
        ["git", "ls-files", ".env"], cwd=_ROOT, capture_output=True, text=True, timeout=30
    ).stdout
    assert tracked.strip() == ""


def test_no_key_shaped_token_in_tracked_files() -> None:
    files = subprocess.run(
        ["git", "ls-files", "-z"], cwd=_ROOT, capture_output=True, text=True, timeout=60
    ).stdout.split("\0")
    offenders: list[str] = []
    for name in filter(None, files):
        path = _ROOT / name
        if not path.is_file() or path.stat().st_size > 2_000_000:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError, OSError:
            continue
        offenders += [
            f"{name}:{n}"
            for n, line in enumerate(text.splitlines(), 1)
            if SECRET_RE.search(line) and _REJECTION_FIXTURE not in line
        ]
    # Paths and line numbers only: the matching value is never put in the message.
    assert offenders == []


@pytest.mark.parametrize(
    "secret",
    [
        "AQ." + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4",
        "sk-" + "abcdefghijklmnopqrstuvwx",
        "ghp_" + "A" * 36,
        "gsk_" + "b" * 24,
    ],
)
def test_redact_masks_key_shapes(secret: str) -> None:
    out = redact_secrets(f"use {secret} for the call")
    assert secret not in out
    assert REDACTED in out


def test_redact_masks_env_assignments_and_keeps_plain_text() -> None:
    assert redact_secrets("OPENAI_API_KEY=abc123xyz") == f"OPENAI_API_KEY={REDACTED}"
    assert redact_secrets("refactor the key-value cache") == "refactor the key-value cache"
