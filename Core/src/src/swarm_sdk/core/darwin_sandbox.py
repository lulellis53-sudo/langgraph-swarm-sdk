"""Run a command under a macOS Seatbelt profile that confines untrusted scripts.

The profile starts from ``(allow default)`` and then takes away what an untrusted
computation never needs: network access, spawning processes, writing outside one
directory, and reading anything under the user's home except the Python install.
Reads elsewhere (``/etc``, ``/usr``) stay allowed, so this is defense in depth for
short scripts, not a full container. On other platforms it is a no-op.
"""

from __future__ import annotations

import os
import site
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path

SANDBOX_EXEC = "/usr/bin/sandbox-exec"


def sandbox_available() -> bool:
    """Return True when this host can enforce Seatbelt profiles."""
    return sys.platform == "darwin" and os.access(SANDBOX_EXEC, os.X_OK)


def python_read_roots() -> frozenset[Path]:
    """Directories the running interpreter needs to read: prefixes and site-packages."""
    roots = {Path(sys.prefix), Path(sys.base_prefix), *map(Path, site.getsitepackages())}
    return frozenset(root.resolve() for root in roots)


def _quote(path: Path) -> str:
    """Return ``path`` as a Seatbelt string literal."""
    escaped = str(path).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def build_profile(
    workdir: Path,
    *,
    readable: Iterable[Path] = (),
    home: Path | None = None,
) -> str:
    """Build the Seatbelt profile text.

    Later rules win in Seatbelt, so the broad denies come first and the narrow allows
    after them.

    Args:
        workdir: The only directory the command may write to; also readable.
        readable: Extra directories the command may read even when they sit under
            ``home`` (for example the Python install).
        home: Home directory whose contents are hidden; defaults to the user's home.

    Returns:
        Profile text for ``sandbox-exec -p``.
    """
    home_dir = (home or Path.home()).resolve()
    allowed_reads = [workdir.resolve(), *(Path(p).resolve() for p in readable)]
    reads = " ".join(f"(subpath {_quote(path)})" for path in allowed_reads)
    return "\n".join(
        [
            "(version 1)",
            "(allow default)",
            "(deny network*)",
            "(deny process-fork)",
            "(deny file-write*)",
            f'(allow file-write* (subpath {_quote(workdir.resolve())}) (literal "/dev/null"))',
            f"(deny file-read* (subpath {_quote(home_dir)}))",
            f"(allow file-read* {reads})",
        ]
    )


def wrap_command(argv: Sequence[str], workdir: Path) -> list[str]:
    """Return ``argv`` prefixed with ``sandbox-exec`` when sandboxing is available.

    Args:
        argv: The command to run.
        workdir: The only writable directory; the Python install stays readable.

    Returns:
        The sandboxed command, or ``argv`` unchanged off macOS.
    """
    if not sandbox_available():
        return list(argv)
    profile = build_profile(workdir, readable=python_read_roots())
    return [SANDBOX_EXEC, "-p", profile, *argv]


__all__ = [
    "SANDBOX_EXEC",
    "build_profile",
    "python_read_roots",
    "sandbox_available",
    "wrap_command",
]
