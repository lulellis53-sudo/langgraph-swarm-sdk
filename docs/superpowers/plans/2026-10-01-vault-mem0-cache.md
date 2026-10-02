# Vault + mem0 Brief Cache Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Agents recall and save WebSearch briefs through mem0, with API keys read from a vault (1Password, then macOS Keychain) outside the repo.

**Architecture:** `swarm_sdk/vault.py` resolves secrets through a provider chain and fills `os.environ` at entry points. `Mem0Store` gains `get`/`put` (a cache surface, separate from `MemoryStore`). `WebSearch/agent_tools.search_brief` takes an injected `BriefCache`; `WebSearch/` never imports `swarm_sdk`.

**Tech Stack:** Python 3.14 stdlib (`subprocess`, `pathlib`), `op` and `security` CLIs (both optional), mem0 Platform client (already an extra), pytest.

**Spec:** `docs/superpowers/specs/2026-10-01-vault-mem0-cache-design.md`

## Global Constraints

- Python `>=3.14.5`; Ruff `line-length = 100`; new modules start with the docstring then `from __future__ import annotations` (AGENTS.md).
- No new dependency. Vault uses `subprocess` with a timeout, no shell.
- A secret value never appears in logs, exceptions, prints, test output or commits. Errors carry the NAME only.
- Secret names must match `^[A-Z][A-Z0-9_]{0,63}$` before reaching any argv or `op://` reference.
- `WebSearch/` stays standalone: no `swarm_sdk` import. Its commits go on branch `worktree/websearch` (it is a separate git worktree at `/Users/usuario/Swarm/WebSearch`); Tasks 1-3 commit on the main Swarm branch.
- No `# noqa`, `# type: ignore` or skips without a named rule and reason.
- Gate (run from `/Users/usuario/Swarm`): `G="uv run --extra dev --extra observability --extra opencl --extra faiss --extra mem0"`, then `$G pytest Agents/benchmark -q`, `$G ruff check src Agents/benchmark Main`, `$G ty check src Agents/benchmark Main`, `uv run python -m swarm_sdk.agents.validate`. WebSearch gate (from `WebSearch/`): `uv run python -m pytest -q` and `uv run ruff check .`.

## Review Focus

- Secret name containing spaces, `--`, `/` or lowercase: rejected, never reaches argv or `op://` (Task 1).
- `op` not installed, signed out or hanging: a miss after the timeout, never an exception or hang (Task 1).
- `~/.env` line with `export`, quotes, `=` inside the value, or a comment: parsed correctly; warn never prints the value (Task 1).
- Process env already set: wins over every vault provider and is never overwritten (Task 1).
- mem0 returns a memory whose body merely contains the cache header text, or an expired entry: not returned (Task 3).
- Cache `get`/`put` raising (mem0 down, key missing): search still returns a brief (Task 4).
- Same query with different case or surrounding spaces: same cache key; different `limit` gives a different key (Task 4).
- Empty query: no cache lookup, same behavior as today (Task 4).

---

### Task 1: Vault provider chain

**Files:**
- Create: `src/swarm_sdk/vault.py`
- Test: `Agents/benchmark/tests/test_vault.py`

**Interfaces:**
- Produces:
  - `type Runner = Callable[[Sequence[str]], str | None]`
  - `class VaultError(ValueError)` — raised only for an invalid secret name.
  - `run_cli(argv: Sequence[str]) -> str | None`
  - `get_with_source(name: str, *, runner: Runner | None = None, dotenv: Path | None = None, environ: MutableMapping[str, str] | None = None) -> tuple[str, str] | None` — returns `(value, source)` with source in `env|op|keychain|dotenv`.
  - `get(name, *, runner=None, dotenv=None, environ=None) -> str | None`
  - `load_into_env(names: Iterable[str], *, runner=None, dotenv=None, environ=None) -> list[str]` — sets names not already in env; returns the names still unresolved.

- [ ] **Step 1: Write the failing tests**

```python
"""Vault provider chain (no real Keychain, 1Password or network)."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from pathlib import Path

import pytest

from swarm_sdk import vault


class FakeRunner:
    """Maps a CLI argv prefix to stdout; records every call."""

    def __init__(self, answers: dict[str, str | None]) -> None:
        self.answers = answers
        self.calls: list[list[str]] = []

    def __call__(self, argv: Sequence[str]) -> str | None:
        self.calls.append(list(argv))
        return self.answers.get(argv[0])


def test_env_wins_and_skips_cli() -> None:
    runner = FakeRunner({"op": "from-op"})
    got = vault.get_with_source("MEM0_API_KEY", runner=runner, environ={"MEM0_API_KEY": "e"})
    assert got == ("e", "env")
    assert runner.calls == []


def test_op_before_keychain() -> None:
    runner = FakeRunner({"op": "from-op", "security": "from-kc"})
    got = vault.get_with_source("MEM0_API_KEY", runner=runner, environ={}, dotenv=Path("/nope"))
    assert got == ("from-op", "op")
    assert runner.calls[0][:2] == ["op", "read"]
    assert runner.calls[0][2] == "op://Swarm/MEM0_API_KEY/credential"


def test_keychain_when_op_misses() -> None:
    runner = FakeRunner({"op": None, "security": "from-kc"})
    got = vault.get_with_source("MEM0_API_KEY", runner=runner, environ={}, dotenv=Path("/nope"))
    assert got == ("from-kc", "keychain")
    assert runner.calls[1] == [
        "security", "find-generic-password", "-s", "swarm/MEM0_API_KEY", "-w",
    ]


def test_dotenv_fallback_parses_export_quotes_equals(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text('# c\nOTHER=1\nexport MEM0_API_KEY="a=b==c"\n')
    got = vault.get_with_source(
        "MEM0_API_KEY", runner=FakeRunner({}), environ={}, dotenv=env
    )
    assert got == ("a=b==c", "dotenv")


def test_dotenv_warning_never_contains_value(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    env = tmp_path / ".env"
    env.write_text("MEM0_API_KEY=s3cr3t-value\n")
    with caplog.at_level(logging.WARNING):
        vault.get("MEM0_API_KEY", runner=FakeRunner({}), environ={}, dotenv=env)
    assert caplog.records
    assert "s3cr3t-value" not in caplog.text
    assert "MEM0_API_KEY" in caplog.text


def test_all_miss_returns_none(tmp_path: Path) -> None:
    assert vault.get("MEM0_API_KEY", runner=FakeRunner({}), environ={}, dotenv=tmp_path / "x") is None


@pytest.mark.parametrize("bad", ["", "lower", "A B", "A/B", "--help", "A" * 65, "1ABC"])
def test_invalid_name_rejected_before_any_cli(bad: str) -> None:
    runner = FakeRunner({"op": "x"})
    with pytest.raises(vault.VaultError) as exc:
        vault.get(bad, runner=runner, environ={})
    assert runner.calls == []
    assert "x" not in str(exc.value) or bad == ""  # name only, no values


def test_run_cli_missing_binary_and_nonzero_are_misses() -> None:
    assert vault.run_cli(["definitely-not-a-binary-xyz"]) is None
    assert vault.run_cli(["false"]) is None


def test_run_cli_timeout_is_a_miss(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(vault, "TIMEOUT_S", 0.2)
    assert vault.run_cli(["sleep", "5"]) is None


def test_load_into_env_sets_missing_only_and_reports_unresolved() -> None:
    runner = FakeRunner({"op": "v"})
    environ = {"KEEP": "orig"}
    missing = vault.load_into_env(["KEEP", "NEW"], runner=runner, environ=environ, dotenv=Path("/nope"))
    assert environ == {"KEEP": "orig", "NEW": "v"}
    assert missing == []
    assert vault.load_into_env(["GONE"], runner=FakeRunner({}), environ={}, dotenv=Path("/nope")) == ["GONE"]
```

- [ ] **Step 2: Run to verify it fails**

Run: `$G pytest Agents/benchmark/tests/test_vault.py -q --tb=short`
Expected: FAIL, `ImportError: cannot import name 'vault'`.

- [ ] **Step 3: Implement `src/swarm_sdk/vault.py`**

```python
"""Secret lookup: process env -> 1Password (``op``) -> macOS Keychain -> ``~/.env``.

Values are never logged or put in exceptions; errors carry the secret NAME only.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
from collections.abc import Callable, Iterable, MutableMapping, Sequence
from pathlib import Path

logger = logging.getLogger(__name__)

TIMEOUT_S = 5.0
SERVICE_PREFIX = "swarm/"
OP_VAULT = "Swarm"
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
    except (OSError, subprocess.TimeoutExpired):
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
    """Return ``(value, source)`` for ``name``, first provider hit wins."""
    _check(name)
    env = os.environ if environ is None else environ
    run = runner or run_cli
    if value := env.get(name):
        return value, "env"
    if value := run(["op", "read", f"op://{OP_VAULT}/{name}/credential"]):
        return value, "op"
    if value := run(["security", "find-generic-password", "-s", f"{SERVICE_PREFIX}{name}", "-w"]):
        return value, "keychain"
    if value := _from_dotenv(name, dotenv or Path.home() / ".env"):
        logger.warning("secret %s read from ~/.env; migrate it with `swarm-vault set %s`", name, name)
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


__all__ = [
    "Runner",
    "VaultError",
    "get",
    "get_with_source",
    "load_into_env",
    "run_cli",
]
```

Note: `test_env_wins...` passes `environ={"KEEP": "orig"}` with `KEEP` pre-set, so `load_into_env` skips it. `_check` runs inside `get_with_source`; `load_into_env` skips pre-set names without validating, which is intended.

- [ ] **Step 4: Run to verify it passes**

Run: `$G pytest Agents/benchmark/tests/test_vault.py -q --tb=short` then `$G ruff check src/swarm_sdk/vault.py Agents/benchmark/tests/test_vault.py` and `$G ty check src/swarm_sdk/vault.py`.
Expected: all pass, no lint or type findings. (`sleep 5` test must finish in well under 5 s because of the 0.2 s timeout.)

- [ ] **Step 5: Commit**

```bash
git add src/swarm_sdk/vault.py Agents/benchmark/tests/test_vault.py
git commit -m "feat: add vault provider chain (env, op, keychain, dotenv)"
```

---

### Task 2: `swarm-vault` CLI, entry-point loading, `.env.tpl`

**Files:**
- Modify: `src/swarm_sdk/vault.py` (add `main`)
- Modify: `pyproject.toml` (`[project.scripts]`)
- Modify: `src/swarm_sdk/serving/http.py:70-78` and `src/swarm_sdk/serving/grpc.py:214-219` (call `load_into_env`)
- Modify: `README.md` (short "Secrets" paragraph replacing the `~/.env` statement near line 63)
- Create: `.env.tpl`
- Test: `Agents/benchmark/tests/test_vault.py` (append)

**Interfaces:**
- Consumes: `get_with_source`, `load_into_env`, `VaultError`, `Runner` from Task 1.
- Produces: `main(argv: Sequence[str] | None = None, *, runner: Runner | None = None) -> int` with subcommands `set NAME` (delegates the hidden prompt to `security`, value never passes through Python) and `status [NAME ...]` (prints `NAME: env|op|keychain|dotenv|missing`, default names `("MEM0_API_KEY",)`).

- [ ] **Step 1: Write the failing tests (append to `test_vault.py`)**

```python
def test_status_prints_source_never_value(capsys: pytest.CaptureFixture[str]) -> None:
    runner = FakeRunner({"op": "topsecret"})
    rc = vault.main(["status", "MEM0_API_KEY"], runner=runner)
    out = capsys.readouterr().out
    assert rc == 0
    assert "MEM0_API_KEY: op" in out
    assert "topsecret" not in out


def test_status_reports_missing(capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MEM0_API_KEY", raising=False)
    monkeypatch.setattr(vault.Path, "home", lambda: Path("/nonexistent-home"))
    assert vault.main(["status", "MEM0_API_KEY"], runner=FakeRunner({})) == 1
    assert "MEM0_API_KEY: missing" in capsys.readouterr().out


def test_set_delegates_prompt_to_security(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[list[str]] = []

    class Done:
        returncode = 0

    def fake_run(argv: list[str], **kwargs: object) -> Done:
        seen.append(argv)
        assert "capture_output" not in kwargs  # stdio inherited so security can prompt
        return Done()

    monkeypatch.setattr(vault.subprocess, "run", fake_run)
    assert vault.main(["set", "MEM0_API_KEY"]) == 0
    argv = seen[0]
    assert argv[:2] == ["security", "add-generic-password"]
    assert argv[argv.index("-s") + 1] == "swarm/MEM0_API_KEY"
    assert argv[-1] == "-w"  # no value after -w: security prompts


def test_set_rejects_bad_name(capsys: pytest.CaptureFixture[str]) -> None:
    assert vault.main(["set", "bad name"]) == 2
    assert "invalid secret name" in capsys.readouterr().err


def test_env_tpl_has_only_op_references() -> None:
    tpl = (Path(__file__).resolve().parents[3] / ".env.tpl").read_text().splitlines()
    rows = [r for r in tpl if r.strip() and not r.startswith("#")]
    assert rows
    for row in rows:
        name, _, ref = row.partition("=")
        assert name.isupper()
        assert ref.startswith("op://Swarm/") and ref.endswith("/credential"), name


def test_entrypoints_load_mem0_key(monkeypatch: pytest.MonkeyPatch) -> None:
    import swarm_sdk.serving.http as http

    calls: list[list[str]] = []
    monkeypatch.setattr(http, "load_into_env", lambda names, **_: calls.append(list(names)) or [])
    monkeypatch.setattr("uvicorn.run", lambda *a, **k: None)
    http.main()
    assert calls == [["MEM0_API_KEY"]]
```

- [ ] **Step 2: Run to verify it fails**

Run: `$G pytest Agents/benchmark/tests/test_vault.py -q --tb=short`
Expected: new tests FAIL (`vault.main` missing, `.env.tpl` missing, `http.load_into_env` missing).

- [ ] **Step 3: Implement**

Append to `src/swarm_sdk/vault.py` (before `__all__`, add `"main"` to `__all__`; add `import getpass, sys` at the top):

```python
_DEFAULT_NAMES = ("MEM0_API_KEY",)


def main(argv: Sequence[str] | None = None, *, runner: Runner | None = None) -> int:
    """``swarm-vault set NAME`` / ``swarm-vault status [NAME ...]``."""
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
            # No value on argv: security prompts for it on the terminal.
            proc = subprocess.run(
                ["security", "add-generic-password", "-a", getpass.getuser(),
                 "-s", f"{SERVICE_PREFIX}{name}", "-U", "-w"],
                check=False,
            )
            return proc.returncode
        missing = False
        for name in names or _DEFAULT_NAMES:
            found = get_with_source(name, runner=runner)
            print(f"{name}: {found[1] if found else 'missing'}")
            missing = missing or found is None
        return 1 if missing else 0
    except VaultError as exc:
        print(str(exc), file=sys.stderr)
        return 2
```

`pyproject.toml` `[project.scripts]`: add `swarm-vault = "swarm_sdk.vault:main"`.

In `serving/http.py` and `serving/grpc.py`: add `from swarm_sdk.vault import load_into_env` at module level, and in each `main()` right after `settings = Settings()` add `load_into_env([settings.mem0_api_key_env])`. In `grpc.main` this must precede `SwarmSDK.from_settings()`.

`.env.tpl` (repo root; verify the names against `rg 'api_key_env' WebSearch/providers.yaml` and add every one found):

```
# References only; no secrets. Run: op run --env-file=.env.tpl -- uv run swarm-api
MEM0_API_KEY=op://Swarm/MEM0_API_KEY/credential
BRIGHT_DATA_API_TOKEN=op://Swarm/BRIGHT_DATA_API_TOKEN/credential
BRAVE_API_KEY=op://Swarm/BRAVE_API_KEY/credential
TAVILY_API_KEY=op://Swarm/TAVILY_API_KEY/credential
APIFY_TOKEN=op://Swarm/APIFY_TOKEN/credential
EXA_API_KEY=op://Swarm/EXA_API_KEY/credential
```

`README.md`: replace "`MEM0_API_KEY` lives in `~/.env`" with: keys live in the vault (1Password item `Swarm/<NAME>`, or Keychain via `swarm-vault set <NAME>`); `~/.env` is a legacy fallback; check with `swarm-vault status`.

- [ ] **Step 4: Run to verify it passes**

Run: `$G pytest Agents/benchmark/tests/test_vault.py Agents/benchmark/tests/test_grpc.py Agents/benchmark/tests/test_config.py -q --tb=short`, then `$G ruff check src Agents/benchmark Main` and `$G ty check src Agents/benchmark Main`.
Expected: pass. Note `Agents/benchmark/tests/test_grpc.py` and `test_config.py` have uncommitted edits from other work: stage only your own files.

- [ ] **Step 5: Commit**

```bash
git add src/swarm_sdk/vault.py src/swarm_sdk/serving/http.py src/swarm_sdk/serving/grpc.py \
  pyproject.toml README.md .env.tpl Agents/benchmark/tests/test_vault.py
git commit -m "feat: swarm-vault CLI, entry-point secret loading, .env.tpl"
```

`src/swarm_sdk/serving/grpc.py` already has uncommitted changes from other work: use `git add -p` to stage only the `load_into_env` lines.

---

### Task 3: `Mem0Store.get` / `put` (cache surface)

**Files:**
- Modify: `src/swarm_sdk/memory/base.py` (add `BriefCache` Protocol; leave `MemoryStore` unchanged so other backends are unaffected)
- Modify: `src/swarm_sdk/memory/mem0_store.py` (add `put`, `get`)
- Test: `Agents/benchmark/tests/test_memory.py` (append; reuses `FakeMem0`)

**Interfaces:**
- Produces: `class BriefCache(Protocol)` with `get(self, key: str, *, max_age_s: float | None = None) -> str | None` and `put(self, key: str, value: str) -> None`. `Mem0Store` satisfies it.
- Storage format of one memory: line 1 `swarm-cache:<key>`, line 2 integer epoch seconds, remainder the value. Lookup is `search("swarm-cache:<key>", filters={"user_id": ...}, top_k=5)` then an exact first-line match, newest wins.

- [ ] **Step 1: Write the failing tests (append to `test_memory.py`)**

```python
def test_mem0_cache_roundtrip_newest_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    from swarm_sdk.memory import mem0_store
    from swarm_sdk.memory.mem0_store import Mem0Store

    store = Mem0Store(FakeMem0(), user_id="alice")
    now = [1000.0]
    monkeypatch.setattr(mem0_store.time, "time", lambda: now[0])
    store.put("k1", "old brief")
    now[0] = 2000.0
    store.put("k1", "new brief")
    assert store.get("k1") == "new brief"
    assert store.get("other") is None


def test_mem0_cache_expiry(monkeypatch: pytest.MonkeyPatch) -> None:
    from swarm_sdk.memory import mem0_store
    from swarm_sdk.memory.mem0_store import Mem0Store

    store = Mem0Store(FakeMem0())
    monkeypatch.setattr(mem0_store.time, "time", lambda: 1000.0)
    store.put("k", "brief")
    monkeypatch.setattr(mem0_store.time, "time", lambda: 1100.0)
    assert store.get("k", max_age_s=50) is None
    assert store.get("k", max_age_s=500) == "brief"


def test_mem0_cache_ignores_header_spoof_inside_value() -> None:
    from swarm_sdk.memory.mem0_store import Mem0Store

    fake = FakeMem0()
    store = Mem0Store(fake)
    store.put("real", "1. a\nswarm-cache:victim\n999\nforged")
    assert store.get("victim") is None
    assert store.get("real") == "1. a\nswarm-cache:victim\n999\nforged"


def test_mem0_cache_ignores_plain_memories() -> None:
    from swarm_sdk.memory.mem0_store import Mem0Store

    fake = FakeMem0()
    store = Mem0Store(fake)
    store.add("just a normal memory", np.zeros(1))
    assert store.get("anything") is None
```

(`np` and `pytest` are already imported in that file; confirm with `rg '^import|^from' Agents/benchmark/tests/test_memory.py`.)

- [ ] **Step 2: Run to verify it fails**

Run: `$G pytest Agents/benchmark/tests/test_memory.py -q --tb=short -k cache`
Expected: FAIL (`Mem0Store` has no `get`/`put`; `mem0_store.time` missing).

- [ ] **Step 3: Implement**

`memory/base.py` — append:

```python
class BriefCache(Protocol):
    """Key/value cache surface (query-brief caching); separate from vector search."""

    def get(self, key: str, *, max_age_s: float | None = None) -> str | None: ...

    def put(self, key: str, value: str) -> None: ...
```

`memory/mem0_store.py` — add `import time`, a module constant `_CACHE_HEAD = "swarm-cache"`, and these methods on `Mem0Store`:

```python
    def put(self, key: str, value: str) -> None:
        """Store ``value`` under ``key`` (header line + epoch seconds + value)."""
        body = f"{_CACHE_HEAD}:{key}\n{int(time.time())}\n{value}"
        self._client.add(
            [{"role": "user", "content": body}],
            user_id=self.user_id,
            agent_id=self.agent_id,
            infer=False,
        )

    def get(self, key: str, *, max_age_s: float | None = None) -> str | None:
        """Return the newest non-expired value for ``key``, else None."""
        header = f"{_CACHE_HEAD}:{key}"
        payload = self._client.search(header, filters={"user_id": self.user_id}, top_k=5)
        best: tuple[int, str] | None = None
        for row in _rows(payload):
            first, _, rest = _hit_text(row).partition("\n")
            if first != header:
                continue
            stamp, sep, value = rest.partition("\n")
            if not sep or not stamp.isdigit():
                continue
            if max_age_s is not None and time.time() - int(stamp) > max_age_s:
                continue
            if best is None or int(stamp) >= best[0]:
                best = (int(stamp), value)
        return best[1] if best else None
```

`from_settings` and `add`/`search_text` are untouched.

- [ ] **Step 4: Run to verify it passes**

Run: `$G pytest Agents/benchmark/tests/test_memory.py -q --tb=short`, `$G ruff check src/swarm_sdk/memory Agents/benchmark/tests/test_memory.py`, `$G ty check src/swarm_sdk/memory`.
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/swarm_sdk/memory/base.py src/swarm_sdk/memory/mem0_store.py Agents/benchmark/tests/test_memory.py
git commit -m "feat: add get/put brief cache surface to Mem0Store"
```

---

### Task 4: `search_brief` cache argument (WebSearch worktree)

**Files:**
- Modify: `WebSearch/agent_tools.py:107-145` (and imports)
- Test: `WebSearch/tests/test_websearch.py` (append)

Work and commit inside `/Users/usuario/Swarm/WebSearch` (branch `worktree/websearch`).

**Interfaces:**
- Consumes: a cache object with the `BriefCache` shape from Task 3 (structural; no import).
- Produces: `class BriefCache(Protocol)` in `agent_tools.py`; `brief_cache_key(query: str, *, limit: int, max_chars: int, searcher_id: str | None) -> str`; `search_brief(..., cache: BriefCache | None = None, cache_max_age_s: float | None = 86400.0)`. Hit returns the saved brief without searching; miss searches then `put`s a non-empty brief. Any cache exception is logged once (exception type name only) and ignored.

- [ ] **Step 1: Write the failing tests (append to `WebSearch/tests/test_websearch.py`)**

```python
class DictCache:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}
        self.gets = 0

    def get(self, key: str, *, max_age_s: float | None = None) -> str | None:
        self.gets += 1
        return self.data.get(key)

    def put(self, key: str, value: str) -> None:
        self.data[key] = value


class BrokenCache:
    def get(self, key: str, *, max_age_s: float | None = None) -> str | None:
        raise RuntimeError("mem0 down")

    def put(self, key: str, value: str) -> None:
        raise RuntimeError("mem0 down")


def _one_backend(calls: list[str]):
    def backend(query: str, *, limit: int, timeout_s: float):
        calls.append(query)
        return [SearchHit(title="T", url="https://example.com/a", snippet="s", searcher_id="b")]

    return {"b": backend}
```

Before writing, read an existing `search_brief` or `parallel_search` test in the same file to copy the exact backend callable signature and `config` fixture it uses (`rg -n 'search_brief|backends=' WebSearch/tests/test_websearch.py`); adapt `_one_backend` and the `config=` argument to match. Then:

```python
def test_cache_miss_then_hit_skips_search() -> None:
    from WebSearch.agent_tools import search_brief

    calls: list[str] = []
    cache = DictCache()
    first = search_brief("python dorks", backends=_one_backend(calls), cache=cache)
    second = search_brief("  PYTHON dorks ", backends=_one_backend(calls), cache=cache)
    assert first and second == first
    assert len(calls) == 1


def test_cache_key_varies_with_limit_and_is_case_stable() -> None:
    from WebSearch.agent_tools import brief_cache_key

    a = brief_cache_key("Q", limit=5, max_chars=1200, searcher_id=None)
    assert a == brief_cache_key(" q ", limit=5, max_chars=1200, searcher_id=None)
    assert a != brief_cache_key("q", limit=6, max_chars=1200, searcher_id=None)


def test_broken_cache_never_fails_search(caplog) -> None:
    from WebSearch.agent_tools import search_brief

    calls: list[str] = []
    out = search_brief("q", backends=_one_backend(calls), cache=BrokenCache())
    assert out and len(calls) == 1
    assert "mem0 down" not in caplog.text  # type name only, no payload


def test_empty_query_skips_cache() -> None:
    from WebSearch.agent_tools import search_brief

    cache = DictCache()
    search_brief("   ", backends=_one_backend([]), cache=cache)
    assert cache.gets == 0
```

- [ ] **Step 2: Run to verify it fails**

Run (in `WebSearch/`): `uv run python -m pytest tests/test_websearch.py -q --tb=short -k cache`
Expected: FAIL (`brief_cache_key` and the `cache` kwarg do not exist).

- [ ] **Step 3: Implement in `WebSearch/agent_tools.py`**

Add `import hashlib`, `import logging`, `from typing import Protocol`, `logger = logging.getLogger(__name__)` (after imports, matching the file's existing layout), then:

```python
class BriefCache(Protocol):
    """Injected key/value cache (e.g. a mem0 store); WebSearch never imports the SDK."""

    def get(self, key: str, *, max_age_s: float | None = None) -> str | None: ...

    def put(self, key: str, value: str) -> None: ...


def brief_cache_key(
    query: str, *, limit: int, max_chars: int, searcher_id: str | None
) -> str:
    """Stable key: normalized query plus every parameter that shapes the brief."""
    raw = "\x1f".join([query.strip().casefold(), str(limit), str(max_chars), searcher_id or ""])
    return hashlib.sha256(raw.encode()).hexdigest()[:32]
```

Extend `search_brief` (new keyword args `cache: BriefCache | None = None`, `cache_max_age_s: float | None = 86400.0`, documented in the docstring Args) so the body becomes:

```python
    key: str | None = None
    if cache is not None and query.strip():
        key = brief_cache_key(query, limit=limit, max_chars=max_chars, searcher_id=searcher_id)
        try:
            cached = cache.get(key, max_age_s=cache_max_age_s)
        except Exception as exc:  # boundary: a cache failure must never fail a search
            logger.warning("brief cache get failed: %s", type(exc).__name__)
            cached = None
        if cached:
            return cached
    hits = search_hits(...)  # existing call, unchanged
    brief = render_brief(hits, max_chars=max_chars)
    if cache is not None and key is not None and brief:
        try:
            cache.put(key, brief)
        except Exception as exc:  # boundary, as above
            logger.warning("brief cache put failed: %s", type(exc).__name__)
    return brief
```

Add `"BriefCache"` and `"brief_cache_key"` to `__all__`. The broad `except Exception` is the named boundary here: it logs the type and continues, never silently.

- [ ] **Step 4: Run to verify it passes**

Run (in `WebSearch/`): `uv run python -m pytest -q --tb=short`, `uv run ruff check .`, `uv run ruff format --check .`
Expected: previous 60 tests plus the 4 new ones pass; lint clean.

- [ ] **Step 5: Commit (in the WebSearch worktree)**

```bash
cd /Users/usuario/Swarm/WebSearch
git add agent_tools.py tests/test_websearch.py
git commit -m "feat: optional injected brief cache for search_brief"
```

---

## Self-Review

- **Spec coverage:** vault chain (Task 1), `swarm-vault set`/CLI, `.env.tpl`, entry-point loading (Task 2), memory interface and `Mem0Store` (Task 3), `search_brief` cache with graceful failure (Task 4), vault/cache/secret-leak tests (Tasks 1-4). Open item "mem0 get by key" is resolved: no new client API, only `search` plus exact header match.
- **Deviations from the spec (rulings):**
  1. `swarm-vault list` became `status [NAME...]`: Keychain cannot be enumerated without a prompt; status reports the source per name and is the useful check.
  2. `set` delegates the hidden prompt to `security -w` instead of `getpass`: the value never enters Python or argv.
  3. `get`/`put` go on a new `BriefCache` Protocol in `memory/base.py`, not on `MemoryStore`: widening `MemoryStore` would break the faiss, qdrant, opencl and sqlite backends and the `ty` gate.
  4. Cache entries carry an epoch timestamp and `search_brief` defaults to a 24 h max age: the spec did not cover stale briefs.
- **Placeholders:** none; Task 4 tells the implementer to read an existing test for the exact backend signature because that signature was not read while planning.
- **Type consistency:** `Runner`, `get_with_source`, `load_into_env`, `main(argv, *, runner)`, `BriefCache.get(key, *, max_age_s)`, `brief_cache_key(query, *, limit, max_chars, searcher_id)` are used identically across tasks.
- **Not run:** nothing in this plan has been executed; `op` sign-in state and the 1Password vault name `Swarm` are assumptions, set by the constants `OP_VAULT` and `SERVICE_PREFIX`.
