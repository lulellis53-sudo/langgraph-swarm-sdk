"""Shared test utilities: environment capability checks."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

from swarm_sdk import vault


def sqlite_extension_loading_available() -> bool:
    """sqlite-vec needs a CPython built with SQLite extension loading.

    Requires BOTH a SQLite library with loadable-extension support AND Python
    configured with ``--enable-loadable-sqlite-extensions`` (disabled by
    default; macOS builds never have it). CI sets SWARM_REQUIRE_SQLITE_EXT=1
    to turn a missing capability into a loud failure instead of silent skips.
    """
    conn = sqlite3.connect(":memory:")
    try:
        return hasattr(conn, "enable_load_extension")
    finally:
        conn.close()


def pytest_configure(config: pytest.Config) -> None:
    required = os.environ.get("SWARM_REQUIRE_SQLITE_EXT") == "1"
    if required and not sqlite_extension_loading_available():
        raise pytest.UsageError(
            "SWARM_REQUIRE_SQLITE_EXT=1 but this Python lacks sqlite3 extension "
            "loading (needs --enable-loadable-sqlite-extensions at build time); "
            "sqlite_vec tests cannot run for real"
        )


@pytest.fixture(autouse=True)
def _isolate_secrets(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Keep real credentials out of every test in ``WebSearch/tests``.

    Clears each env name the configs reference, blocks the macOS Keychain CLI, hides the
    project ``.env`` and points ``~`` at an empty directory so no fallback finds a real
    secret. Tests that need a key set it explicitly (``monkeypatch.setenv`` or an injected
    vault runner).
    """
    for name in (*vault.referenced_names(), "SWARM_KEYCHAIN_PATH", "KEYS_KEYCHAIN"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(vault, "run_cli", lambda argv: None)
    monkeypatch.setattr(vault, "_PROJECT_ENV", tmp_path / "absent.env")
    monkeypatch.setenv("HOME", str(tmp_path))
