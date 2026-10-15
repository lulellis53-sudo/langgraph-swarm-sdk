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


def _find_repo_root(anchor: Path) -> Path:
    for parent in (anchor, *anchor.parents):
        if (parent / "pyproject.toml").is_file() or (parent / ".git").exists():
            return parent
    return anchor.parents[2]


_PROJECT_ENV = _find_repo_root(Path(__file__).resolve()) / ".env"
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

# Successful lookups only; missing names stay uncached so a later `keys set` is visible.
_SECRET_CACHE: dict[str, str] = {}


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


def _api_keychain_args() -> list[str]:
    """APIKEYCHAIN path when that file exists.

    Items there use the service ``APIKEYCHAIN/<NAME>``. ``KEYS_KEYCHAIN``
    overrides the default ``~/Library/Keychains/APIKEYCHAIN.keychain-db``.
    """
    raw = os.environ.get("KEYS_KEYCHAIN")
    path = (
        Path(raw).expanduser()
        if raw
        else Path.home() / "Library" / "Keychains" / "APIKEYCHAIN.keychain-db"
    )
    return [str(path)] if path.is_file() else []


class VaultError(ValueError):
    """Raised for an invalid secret name (never carries a secret value)."""


def run_cli(argv: Sequence[str]) -> str | None:
    """Run a CLI without a shell; return stripped stdout, or None on any failure."""
    try:
        proc = subprocess.run(
            list(argv), capture_output=True, text=True, timeout=TIMEOUT_S, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or None


def _check(name: str) -> str:
    """Return ``name`` if it is a valid secret name, else raise ``VaultError``."""
    if not _NAME.fullmatch(name):
        raise VaultError(f"invalid secret name: {name[:70]!r}")
    return name


def _from_dotenv(name: str, path: Path) -> str | None:
    """Read ``name`` from a dotenv file; ``None`` when the file or key is missing."""
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


def clear_cache() -> None:
    """Drop memoized secret values (call after rotating keys)."""
    _SECRET_CACHE.clear()


def get(
    name: str,
    *,
    runner: Runner | None = None,
    dotenv: Path | None = None,
    environ: MutableMapping[str, str] | None = None,
) -> str | None:
    """Return the secret value for ``name`` or None.

    Default lookups (no ``runner``/``dotenv``/``environ``) memoize successful
    values for the life of the process; call :func:`clear_cache` after rotation.
    Environment variables still win over the memo.
    """
    _check(name)
    env = os.environ if environ is None else environ
    if value := env.get(name):
        return value
    use_cache = runner is None and dotenv is None and environ is None
    if use_cache:
        cached = _SECRET_CACHE.get(name)
        if cached is not None:
            return cached
    found = get_with_source(name, runner=runner, dotenv=dotenv, environ=environ)
    value = found[0] if found else None
    if use_cache and value:
        _SECRET_CACHE[name] = value
    return value


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
        ok = result if isinstance(result, bool) else result is not None
        if ok:
            clear_cache()
        return ok

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
        if proc.returncode == 0:
            clear_cache()
            return True
        return False
    except (OSError, subprocess.TimeoutExpired):
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


# Thin backwards-compatible shim: the ``swarm-vault`` console script entry point
# (``swarm_sdk.vault:main`` in pyproject) imports from this module. The
# implementation lives in :mod:`swarm_sdk.commands.vault_cli`; importing it here
# (after every definition above) avoids a circular import. CLI output belongs in
# that module; library code must not print.
from swarm_sdk.commands.vault_cli import main  # noqa: E402

__all__ = [
    "KNOWN_NAMES",
    "Runner",
    "VaultError",
    "clear_cache",
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
