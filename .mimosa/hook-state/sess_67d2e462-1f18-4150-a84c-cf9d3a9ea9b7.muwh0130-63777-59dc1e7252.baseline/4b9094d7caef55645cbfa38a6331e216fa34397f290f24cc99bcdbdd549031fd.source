"""Shared test utilities: environment capability checks."""

from __future__ import annotations

import os
import sqlite3

import pytest


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
