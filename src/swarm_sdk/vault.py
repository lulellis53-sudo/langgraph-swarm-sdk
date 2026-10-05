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

import yaml

logger = logging.getLogger(__name__)

TIMEOUT_S = 5.0
SERVICE_PREFIX = "swarm/"
_PROJECT_ENV = Path(__file__).resolve().parents[2] / ".env"
KNOWN_NAMES = (
    "MEM0_API_KEY",
    "TAVILY_API_KEY",
    "BRAVE_API_KEY",
    "EXA_API_KEY",
    "OPENAI_API_KEY",
    "JEV_API_KEY",
    "CONTEXT7_API_KEY",
    "CONTEXT_DEV_API_KEY",
    "APIFY_TOKEN",
    "APIFY_API_KEY",
    "BRIGHT_DATA_API_TOKEN",
    "BRIGHTDATA_MCP_TOKEN",
    "BRIGHT_DATA_UNLOCKER_ZONE",
    "BRIGHT_DATA_BROWSER_ZONE",
    "APPWRITE_API_KEY",
    "APPWRITE_PROJECT_ID",
    "APPWRITE_ENDPOINT",
)
_NAME = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")

type Runner = Callable[[Sequence[str]], str | None]
type InputRunner = Callable[[Sequence[str], str], str | bool | None]


def _api_keychain_args() -> list[str]:
    """Path of APIKEYCHAIN when that file exists, else nothing.

    Swarm items use ``swarm/<NAME>``. The user key store uses
    ``APIKEYCHAIN/<NAME>`` in ``~/Library/Keychains/APIKEYCHAIN.keychain-db``
    (override with ``KEYS_KEYCHAIN``). A missing file skips the lookup.
    """
    raw = os.environ.get("KEYS_KEYCHAIN")
    path = (
        Path(raw).expanduser()
        if raw
        else Path.home() / "Library" / "Keychains" / "APIKEYCHAIN.keychain-db"
    )
    return [str(path)] if path.is_file() else []


def _keychain_args() -> list[str]:
    """Select a dedicated Keychain when configured, otherwise use the search list."""
    path = os.environ.get("SWARM_KEYCHAIN_PATH")
    if path is None:
        try:
            if (_PROJECT_ENV.stat().st_mode & 0o077) == 0:
                path = _from_dotenv("SWARM_KEYCHAIN_PATH", _PROJECT_ENV)
        except OSError:
            pass
    if path and any(char in path for char in '\r\n"\\'):
        raise VaultError("invalid Keychain path")
    return [str(Path(path).expanduser())] if path else []


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


_SAFE_VALUE = re.compile(r"[A-Za-z0-9_\-.~+/=:]+")


def parse_secrets(text: str) -> list[tuple[str, str]]:
    """Parse ``NAME=value`` or ``NAME,value`` lines; skip comments."""
    pairs: list[tuple[str, str]] = []
    for raw in text.splitlines():
        line = raw.strip().removeprefix("export ").lstrip()
        if not line or line.startswith("#"):
            continue
        cut = min((i for i in (line.find("="), line.find(",")) if i > 0), default=-1)
        if cut < 0:
            continue
        name, value = line[:cut].strip().strip("\"'"), line[cut + 1 :].strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        pairs.append((name, value))
    return pairs


def import_file(path: Path) -> tuple[list[str], list[str]]:
    """Store every valid pair from ``path`` in the Keychain; return ``(stored, skipped)`` NAMEs.

    Values go to ``security -i`` on stdin, never argv, and are never printed.
    A pair is skipped when its name is invalid, its value is empty or has unsafe characters.
    """
    stored: list[str] = []
    skipped: list[str] = []
    for name, value in parse_secrets(path.read_text()):
        if _NAME.fullmatch(name) is None or _SAFE_VALUE.fullmatch(value) is None:
            if name.lower() != "name":  # header row of a CSV
                skipped.append(name[:70])
            continue
        keychain = _keychain_args()
        command = (
            f'add-generic-password -a {getpass.getuser()} -s {SERVICE_PREFIX}{name} -U -w "{value}"'
        )
        if keychain:
            command += f' "{keychain[0]}"'
        proc = subprocess.run(
            ["security", "-i"],
            input=command + "\n",
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        (stored if proc.returncode == 0 else skipped).append(name)
    return stored, skipped


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
    if value := run(
        [
            "security",
            "find-generic-password",
            "-s",
            f"{SERVICE_PREFIX}{name}",
            "-w",
            *_keychain_args(),
        ]
    ):
        return value, "keychain"
    api_keychain = _api_keychain_args()
    if api_keychain and (
        value := run(
            [
                "security",
                "find-generic-password",
                "-s",
                f"APIKEYCHAIN/{name}",
                "-w",
                *api_keychain,
            ]
        )
    ):
        return value, "apikeychain"
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


def resolve(
    name: str,
    *,
    runner: Runner | None = None,
    dotenv: Path | None = None,
    environ: MutableMapping[str, str] | None = None,
) -> str | None:
    """Resolve the secret value for ``name`` or None."""
    return get(name, runner=runner, dotenv=dotenv, environ=environ)


def get_secret(
    name: str,
    fallback_env: bool = True,
    *,
    runner: Runner | None = None,
    dotenv: Path | None = None,
    environ: MutableMapping[str, str] | None = None,
) -> str | None:
    """Return the secret value for ``name``.

    When ``fallback_env`` is True, checks environment variables first, then macOS Keychain,
    then legacy dotenv. When False, bypasses environment variables to query the Keychain.
    """
    if not fallback_env:
        return get(name, runner=runner, dotenv=dotenv, environ={})
    return get(name, runner=runner, dotenv=dotenv, environ=environ)


def set_secret(
    name: str,
    secret_value: str,
    runner: InputRunner | None = None,
) -> bool:
    """Store a secret in the macOS Keychain.

    Validates name via ``_check(name)``.
    Rejects empty or whitespace-only secret values by raising ValueError.
    Sends the value to ``security -i`` on stdin, never in process arguments.
    Secret values are never logged or echoed in exceptions.
    Returns True on success, False on failure.
    """
    _check(name)
    if not secret_value or not secret_value.strip():
        raise ValueError(f"Secret value for {name} cannot be empty")
    cmd = ["/usr/bin/security", "-i"]
    command = (
        f"add-generic-password -s {SERVICE_PREFIX}{name} -a {getpass.getuser()} "
        f"-U -X {secret_value.encode().hex()}"
    )
    keychain = _keychain_args()
    if keychain:
        command += f' "{keychain[0]}"'
    command += "\n"

    if runner is not None:
        result = runner(cmd, command)
        if isinstance(result, bool):
            return result
        return result is not None

    if sys.platform != "darwin":
        return False

    try:
        proc = subprocess.run(
            cmd,
            input=command,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_S,
            check=False,
        )
        return proc.returncode == 0
    except OSError, subprocess.TimeoutExpired:
        return False


def get_openai_key(*, runner: Runner | None = None) -> str | None:
    """Return the OpenAI API key resolved from the vault."""
    return resolve("OPENAI_API_KEY", runner=runner)


def get_jev_key(*, runner: Runner | None = None) -> str | None:
    """Return the Jev API key resolved from the vault."""
    return resolve("JEV_API_KEY", runner=runner)


def set_openai_key(key: str, *, runner: InputRunner | None = None) -> bool:
    """Store the OpenAI API key into the macOS Keychain."""
    return set_secret("OPENAI_API_KEY", key, runner=runner)


def set_jev_key(key: str, *, runner: InputRunner | None = None) -> bool:
    """Store the Jev API key into the macOS Keychain."""
    return set_secret("JEV_API_KEY", key, runner=runner)


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


def referenced_names() -> tuple[str, ...]:
    """Every ``api_key_env`` name in the packaged configs plus ``KNOWN_NAMES``."""
    cfg_dir = Path(__file__).resolve().parent / "agents" / "config"
    names: set[str] = set(KNOWN_NAMES)
    for file in ("swarm.yaml", "model_registry.yaml"):
        try:
            data = yaml.safe_load((cfg_dir / file).read_text(encoding="utf-8"))
        except OSError:
            continue
        stack: list[object] = [data]
        while stack:
            node = stack.pop()
            if isinstance(node, dict):
                for key, value in node.items():
                    if (
                        key in {"api_key_env", "base_url_env"}
                        and isinstance(value, str)
                        and _NAME.fullmatch(value)
                    ):
                        names.add(value)
                    stack.append(value)
            elif isinstance(node, list):
                stack.extend(node)
    return tuple(sorted(names))


_PRIMED = False


def prime_runtime_secrets(
    *,
    runner: Runner | None = None,
    dotenv: Path | None = None,
    environ: MutableMapping[str, str] | None = None,
) -> list[str]:
    """Idempotently resolve every referenced key name into the environment.

    Runs once per process; later calls are no-ops. Swarm agents (LangChain
    model loaders) and third-party code reading ``os.environ`` — the WebSearch
    searchers included — then see Keychain-resolved keys.

    Returns:
        list[str]: Names that could not be resolved from any provider.
    """
    global _PRIMED
    if _PRIMED:
        return []
    _PRIMED = True
    return load_into_env(referenced_names(), runner=runner, dotenv=dotenv, environ=environ)


def main(argv: Sequence[str] | None = None, *, runner: Runner | None = None) -> int:
    """Run ``swarm-vault set NAME`` or ``swarm-vault status [NAME ...]``."""
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] not in {"set", "status", "import"}:
        print("usage: swarm-vault set NAME | import FILE | status [NAME ...]", file=sys.stderr)
        return 2
    cmd, names = args[0], args[1:]
    try:
        if cmd == "import":
            if len(names) != 1:
                print("usage: swarm-vault import FILE", file=sys.stderr)
                return 2
            stored, skipped = import_file(Path(names[0]).expanduser())
            print(f"stored: {', '.join(stored) or '-'}")
            print(f"skipped: {', '.join(skipped) or '-'}")
            return 1 if skipped or not stored else 0
        if cmd == "set":
            if len(names) != 1:
                print("usage: swarm-vault set NAME", file=sys.stderr)
                return 2
            name = _check(names[0])
            if _keychain_args():
                # `security` stops option parsing at the Keychain positional, so a trailing
                # `-w` prompt would be ignored: prompt here and send the value on stdin.
                value = getpass.getpass(f"Value for {name}: ")
                if not value.strip():
                    print("empty value", file=sys.stderr)
                    return 2
                return 0 if set_secret(name, value) else 1
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
    "get_jev_key",
    "get_openai_key",
    "get_secret",
    "get_with_source",
    "import_file",
    "load_into_env",
    "main",
    "parse_secrets",
    "prime_runtime_secrets",
    "referenced_names",
    "resolve",
    "run_cli",
    "set_jev_key",
    "set_openai_key",
    "set_secret",
]
