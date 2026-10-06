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
_PROJECT_ENV = Path(__file__).resolve().parents[3] / ".env"
KNOWN_NAMES = (
    "MEM0_API_KEY",
    "TAVILY_API_KEY",
    "BRAVE_API_KEY",
    "EXA_API_KEY",
    "OPENAI_API_KEY",
    "JEV_API_KEY",
)
_NAME = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")

type Runner = Callable[[Sequence[str]], str | None]


class VaultError(ValueError):
    """Raised for an invalid secret name (never carries a secret value)."""


def _keychain_args() -> list[str]:
    """Find the dedicated Keychain named by the owner-only parent project env file."""
    path = os.environ.get("SWARM_KEYCHAIN_PATH")
    if path is None:
        try:
            if (_PROJECT_ENV.stat().st_mode & 0o077) == 0:
                path = _dotenv_raw(
                    "SWARM_KEYCHAIN_PATH", _PROJECT_ENV
                )  # raw: decrypting needs this path
        except OSError:
            pass
    if path and any(char in path for char in '\r\n"\\'):
        raise VaultError("invalid Keychain path")
    return [str(Path(path).expanduser())] if path else []


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


ENC_PREFIX = "enc:v1:"
_FERNET_KEY_NAME = "DOTENV_FERNET_KEY"


def _find_cmd(name: str) -> list[str]:
    return ["security", "find-generic-password", "-s", f"{SERVICE_PREFIX}{name}", "-w"] + (
        _keychain_args()
    )


def _store_via_stdin(name: str, value: str) -> None:
    """Add or update a Keychain item with the value on stdin (hex), never in argv or ps."""
    command = (
        f"add-generic-password -s {SERVICE_PREFIX}{_check(name)} -a {getpass.getuser()} "
        f"-U -X {value.encode().hex()}"
    )
    keychain = _keychain_args()
    if keychain:
        command += f' "{keychain[0]}"'
    try:
        subprocess.run(
            ["/usr/bin/security", "-i"],
            input=command + "\n",
            capture_output=True,
            text=True,
            timeout=TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise VaultError(f"could not run security: {type(exc).__name__}") from exc


def _fernet(*, create: bool, runner: Runner | None = None):  # noqa: ANN202 - optional import
    """Fernet cipher keyed by the Keychain item ``DOTENV_FERNET_KEY`` (made when ``create``).

    The key lives only in the Keychain, so an ``.env`` that leaks (backup, commit, copy) holds
    ciphertext that is useless without this machine's login keychain.
    """
    from cryptography.fernet import Fernet

    run = runner or run_cli
    key = run(_find_cmd(_FERNET_KEY_NAME))
    if not key:
        if not create:
            return None
        key = Fernet.generate_key().decode()
        _store_via_stdin(_FERNET_KEY_NAME, key)
        if run(_find_cmd(_FERNET_KEY_NAME)) != key:  # read back: `security -i` hides failures
            raise VaultError("could not store the .env encryption key in the Keychain")
    return Fernet(key.encode())


def encrypt_value(value: str, *, runner: Runner | None = None) -> str:
    """Encrypt ``value`` for ``.env``; returns ``enc:v1:<token>``. Creates the key if needed."""
    if not value:
        raise ValueError("cannot encrypt an empty value")
    cipher = _fernet(create=True, runner=runner)
    assert cipher is not None  # create=True either returns a cipher or raises
    return ENC_PREFIX + cipher.encrypt(value.encode()).decode()


def decrypt_value(token: str, *, runner: Runner | None = None) -> str | None:
    """Decrypt an ``enc:v1:`` value; ``None`` without the key or on a bad token (never raises)."""
    from cryptography.fernet import InvalidToken

    cipher = _fernet(create=False, runner=runner)
    if cipher is None or not token.startswith(ENC_PREFIX):
        return None
    try:
        return cipher.decrypt(token.removeprefix(ENC_PREFIX).encode()).decode()
    except InvalidToken, UnicodeDecodeError:
        return None


def write_dotenv_entry(path: Path, name: str, value: str, *, runner: Runner | None = None) -> None:
    """Write ``NAME=enc:v1:...`` into ``path``, replacing that name's line, mode 0600.

    Other lines are kept as they are. The file is replaced atomically, so a failure leaves the
    old content in place.
    """
    _check(name)
    line = f"{name}={encrypt_value(value, runner=runner)}"
    try:
        existing = path.read_text().splitlines()
    except FileNotFoundError:
        existing = []
    out: list[str] = []
    replaced = False
    for raw in existing:
        head = raw.strip().removeprefix("export ").lstrip().partition("=")[0].strip()
        if head == name:
            if not replaced:
                out.append(line)
            replaced = True
        else:
            out.append(raw)
    if not replaced:
        out.append(line)
    tmp = path.with_name(f".{path.name}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as handle:
        handle.write("\n".join(out) + "\n")
    os.replace(tmp, path)
    path.chmod(0o600)


def _dotenv_raw(name: str, path: Path) -> str | None:
    """The unquoted value of ``NAME`` in ``path`` exactly as written, or ``None``."""
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


def _from_dotenv(name: str, path: Path, *, runner: Runner | None = None) -> str | None:
    value = _dotenv_raw(name, path)
    if value is not None and value.startswith(ENC_PREFIX):
        plain = decrypt_value(value, runner=runner)
        if plain is None:
            logger.warning("cannot decrypt %s in %s (key missing or token invalid)", name, path)
        return plain
    return value


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
        proc = subprocess.run(
            ["security", "-i"],
            input=(
                f"add-generic-password -a {getpass.getuser()} "
                f'-s {SERVICE_PREFIX}{name} -U -w "{value}"\n'
            ),
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
    for path in [dotenv] if dotenv else [Path.home() / ".env", Path.cwd() / ".env"]:
        value = _from_dotenv(name, path, runner=runner)
        if not value:
            continue
        if (_dotenv_raw(name, path) or "").startswith(ENC_PREFIX):
            return value, "dotenv-encrypted"
        logger.warning(
            "secret %s read from %s in plaintext; use `swarm-vault dotenv-set %s` or `set`",
            name,
            path,
            name,
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
    runner: Runner | None = None,
) -> bool:
    """Store a secret in the macOS Keychain.

    Validates name via ``_check(name)``.
    Rejects empty or whitespace-only secret values by raising ValueError.
    Without a ``runner`` the value goes to ``security -i`` on stdin (hex), never argv, honors
    ``SWARM_KEYCHAIN_PATH`` and is read back to confirm; a ``runner`` receives the argv form.
    Secret values are never logged or echoed in exceptions.
    Returns True on success, False on failure.
    """
    _check(name)
    if not secret_value or not secret_value.strip():
        raise ValueError(f"Secret value for {name} cannot be empty")

    cmd = [
        "/usr/bin/security",
        "add-generic-password",
        "-s",
        f"{SERVICE_PREFIX}{name}",
        "-a",
        getpass.getuser(),
        "-w",
        secret_value,
        "-U",
    ]

    if runner is not None:
        result = runner(cmd)
        if isinstance(result, bool):
            return result
        return result is not None

    if sys.platform != "darwin":
        return False

    try:
        # stdin (hex), not argv: the value stays out of `ps` and SWARM_KEYCHAIN_PATH is honored
        _store_via_stdin(name, secret_value)
        return run_cli(_find_cmd(name)) == secret_value
    except VaultError:
        return False


def get_openai_key(*, runner: Runner | None = None) -> str | None:
    """Return the OpenAI API key resolved from the vault."""
    return resolve("OPENAI_API_KEY", runner=runner)


def get_jev_key(*, runner: Runner | None = None) -> str | None:
    """Return the Jev API key resolved from the vault."""
    return resolve("JEV_API_KEY", runner=runner)


def set_openai_key(key: str, *, runner: Runner | None = None) -> bool:
    """Store the OpenAI API key into the macOS Keychain."""
    return set_secret("OPENAI_API_KEY", key, runner=runner)


def set_jev_key(key: str, *, runner: Runner | None = None) -> bool:
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
    if not args or args[0] not in {"set", "status", "import", "dotenv-set"}:
        print(
            "usage: swarm-vault set NAME | dotenv-set NAME [FILE] | import FILE | status [NAME]",
            file=sys.stderr,
        )
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
        if cmd == "dotenv-set":
            if not 1 <= len(names) <= 2:
                print("usage: swarm-vault dotenv-set NAME [FILE]", file=sys.stderr)
                return 2
            name = _check(names[0])
            target = Path(names[1]).expanduser() if len(names) == 2 else Path.cwd() / ".env"
            value = getpass.getpass(f"Value for {name} (hidden, stored encrypted): ").strip()
            if not value:
                print("empty value", file=sys.stderr)
                return 2
            write_dotenv_entry(target, name, value, runner=runner if runner else None)
            print(f"{name} stored encrypted in {target} (key: Keychain {_FERNET_KEY_NAME})")
            return 0
        if cmd == "set":
            if len(names) != 1:
                print("usage: swarm-vault set NAME", file=sys.stderr)
                return 2
            name = _check(names[0])
            if _keychain_args():
                # A positional keychain path cannot follow a value-less `-w` (it would be taken
                # as the password), so prompt here and write through `security -i` on stdin.
                value = getpass.getpass(f"Value for {name} (hidden): ").strip()
                if not value:
                    print("empty value", file=sys.stderr)
                    return 2
                _store_via_stdin(name, value)
                if (runner or run_cli)(_find_cmd(name)) != value:  # `security -i` hides failures
                    print(f"could not store {name} in the dedicated Keychain", file=sys.stderr)
                    return 1
                print(f"{name} stored in {_keychain_args()[0]}")
                return 0
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
    "decrypt_value",
    "encrypt_value",
    "get_with_source",
    "import_file",
    "load_into_env",
    "main",
    "parse_secrets",
    "prime_runtime_secrets",
    "referenced_names",
    "write_dotenv_entry",
    "resolve",
    "run_cli",
    "set_jev_key",
    "set_openai_key",
    "set_secret",
]
