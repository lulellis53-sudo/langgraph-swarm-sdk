"""Shared test utilities: environment capability checks."""

from __future__ import annotations

import sqlite3


def sqlite_extension_loading_available() -> bool:
    """sqlite-vec needs a CPython built with SQLite extension loading.

    macOS CPython builds (system, framework, and python-build-standalone) compile
    the sqlite3 module without loadable-extension support, so sqlite_vec cannot
    load there. Linux CI runners have it; these tests run for real there.
    """
    conn = sqlite3.connect(":memory:")
    try:
        return hasattr(conn, "enable_load_extension")
    finally:
        conn.close()
