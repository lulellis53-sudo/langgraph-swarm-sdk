"""Secret lookup: process env -> macOS Keychain -> legacy ``~/.env``.

Keychain items are stored as service ``swarm/<NAME>``; the Keychain encrypts them at rest.
Values are never logged or put in exceptions; errors carry the secret NAME only.
"""

from __future__ import annotations

import getpass
import logging
import os
import re
import subprocess
import sys
from collections.abc import Callable, Iterable, MutableMapping, Sequence
from pathlib import Path

logger = logging.getLogger(__name__)

TIMEOUT_S = 5.0
SERVICE_PREFIX = "swarm/"
KNOWN_NAMES = ("MEM0_API_KEY", "TAVILY_API_KEY", "BRAVE_API_KEY", "EXA_API_KEY")
_NAME = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")

type Runner = Callable[[Sequence[str]], str | None]


class VaultError(ValueError):
    """Raised for an invalid secret name (never carries a secret value)."""


def run_cli(argv: Sequence[str]) -> str | None:
    """Run a CLI without a shell; return stripped stdout, or None on any failure."""
    try:
        proc = subprocess.run(
            list(argv), capture_output=True, text=True, timeout=TIMEOUT_S, check=False
        )
    except OSError, subprocess.TimeoutExpired:
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or None


def _check(name: str) -> str:
    if not _NAME.fullmatch(name):
        raise VaultError(f"invalid secret name: {name[:70]!r}")
    return name


def _from_dotenv(name: str, path: Path) -> str | None:
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return None
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        line = line.removeprefix("export ").lstrip()
        key, sep, value = line.partition("=")
        if sep and key.strip() == name:
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            return value or None
    return None


def get_with_source(
    name: str,
    *,
    runner: Runner | None = None,
    dotenv: Path | None = None,
    environ: MutableMapping[str, str] | None = None,
) -> tuple[str, str] | None:
    """Return ``(value, source)`` for ``name``; first provider hit wins.

    Raises:
        VaultError: When ``name`` is not an upper-case env-var name.
    """
    _check(name)
    env = os.environ if environ is None else environ
    run = runner or run_cli
    if value := env.get(name):
        return value, "env"
    if value := run(["security", "find-generic-password", "-s", f"{SERVICE_PREFIX}{name}", "-w"]):
        return value, "keychain"
    if value := _from_dotenv(name, dotenv or Path.home() / ".env"):
        logger.warning(
            "secret %s read from ~/.env; migrate it with `swarm-vault set %s`", name, name
        )
        return value, "dotenv"
    return None


def get(
    name: str,
    *,
    runner: Runner | None = None,
    dotenv: Path | None = None,
    environ: MutableMapping[str, str] | None = None,
) -> str | None:
    """Return the secret value for ``name`` or None."""
    found = get_with_source(name, runner=runner, dotenv=dotenv, environ=environ)
    return found[0] if found else None


def load_into_env(
    names: Iterable[str],
    *,
    runner: Runner | None = None,
    dotenv: Path | None = None,
    environ: MutableMapping[str, str] | None = None,
) -> list[str]:
    """Set each unset name in the environment; return the names still unresolved."""
    env = os.environ if environ is None else environ
    unresolved: list[str] = []
    for name in names:
        if name in env:
            continue
        value = get(name, runner=runner, dotenv=dotenv, environ=env)
        if value is None:
            unresolved.append(name)
        else:
            env[name] = value
    return unresolved


def main(argv: Sequence[str] | None = None, *, runner: Runner | None = None) -> int:
    """Run ``swarm-vault set NAME`` or ``swarm-vault status [NAME ...]``."""
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] not in {"set", "status"}:
        print("usage: swarm-vault set NAME | status [NAME ...]", file=sys.stderr)
        return 2
    cmd, names = args[0], args[1:]
    try:
        if cmd == "set":
            if len(names) != 1:
                print("usage: swarm-vault set NAME", file=sys.stderr)
                return 2
            name = _check(names[0])
            # No value on argv: `security` prompts for it on the terminal.
            proc = subprocess.run(
                [
                    "security",
                    "add-generic-password",
                    "-a",
                    getpass.getuser(),
                    "-s",
                    f"{SERVICE_PREFIX}{name}",
                    "-U",
                    "-w",
                ],
                check=False,
            )
            return proc.returncode
        missing = False
        for name in names or KNOWN_NAMES:
            found = get_with_source(name, runner=runner)
            print(f"{name}: {found[1] if found else 'missing'}")
            missing = missing or found is None
        return 1 if missing else 0
    except VaultError as exc:
        print(str(exc), file=sys.stderr)
        return 2


__all__ = [
    "KNOWN_NAMES",
    "Runner",
    "VaultError",
    "get",
    "get_with_source",
    "load_into_env",
    "main",
    "run_cli",
]
