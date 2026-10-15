"""Helper-LLM client driven by ``providers.yaml``.

Two provider kinds:

* ``api`` (default): an OpenAI-compatible ``/chat/completions`` endpoint with keys from the
  environment (the launcher fills it from the Keychain).
* ``cli``: an official command-line agent that is already logged in through OAuth (Claude Code,
  Codex). The prompt goes in on stdin, the process runs in an empty temporary directory with only a
  short allow-list of environment variables (so none of your API keys reach it), and it is killed at
  ``maxms``. Its own OAuth tokens are never read here.

Providers are tried in file order. One is skipped when it is disabled, unavailable (no key / binary
missing), or rejected (401/402/403/404); transient failures (429, 5xx, timeouts) are retried
``maxretry`` times first. Override a model with ``<NAME>_MODEL`` and move one provider to the front
with ``LLM_FIRST=<name>``. ``WEBSCRAPER_PROVIDERS`` points at another YAML file.
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx2
import yaml

#: Answer budget (max output tokens) per ``effort`` level (``api`` providers only).
EFFORT_TOKENS: dict[str, int] = {"low": 300, "medium": 800, "high": 1500, "xhigh": 3000}
#: Statuses worth another attempt on the same key.
TRANSIENT = {408, 425, 429, 500, 502, 503, 504}
#: Statuses that mean this key/model will not work: move on without retrying.
PERMANENT = {401, 402, 403, 404, 409}
#: First retry waits this long, doubling each time (tests set it to 0).
RETRY_BASE_S = 0.5
#: Environment variables a ``cli`` provider may inherit. Nothing else, so no API key leaks to it.
CLI_ENV_ALLOWLIST = (
    "PATH",
    "HOME",
    "USER",
    "LOGNAME",
    "SHELL",
    "LANG",
    "LC_ALL",
    "TMPDIR",
    "CODEX_HOME",
    "CLAUDE_CONFIG_DIR",
    "XDG_CONFIG_HOME",
    "SSL_CERT_FILE",
    "HTTPS_PROXY",
    "HTTP_PROXY",
    "NO_PROXY",
    "ALL_PROXY",
)
_THINK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_FIELDS = {
    "name",
    "kind",
    "base_url",
    "keys",
    "model",
    "effort",
    "maxretry",
    "maxms",
    "enabled",
    "extra_body",
    "command",
}


class LLMError(RuntimeError):
    """Raised when no provider could answer."""


class ConfigError(ValueError):
    """Raised for an invalid ``providers.yaml``."""


@dataclass(frozen=True)
class Provider:
    name: str
    base_url: str
    key_envs: tuple[str, ...]
    model: str  # default; override with <NAME>_MODEL
    effort: str = "medium"
    maxretry: int = 1
    maxms: int = 60000
    enabled: bool = True
    extra_body: dict[str, Any] = field(default_factory=dict)  # merged into every request
    kind: str = "api"
    command: tuple[str, ...] = ()  # cli only; "{model}" is replaced

    def keys(self) -> list[str]:
        """Every configured key for this provider, in order."""
        return [v for e in self.key_envs if (v := os.environ.get(e))]

    def chosen_model(self) -> str:
        return os.environ.get(f"{self.name.upper()}_MODEL") or self.model

    @property
    def max_tokens(self) -> int:
        return EFFORT_TOKENS[self.effort]

    @property
    def available(self) -> bool:
        """Has a key (api) or an executable on PATH (cli)."""
        if self.kind == "cli":
            return shutil.which(self.command[0]) is not None
        return bool(self.keys())

    def argv(self) -> list[str]:
        """The command line of a ``cli`` provider with ``{model}`` filled in."""
        model = self.chosen_model()
        return [part.replace("{model}", model) for part in self.command]


def providers_path() -> Path:
    """The YAML file in use: ``WEBSCRAPER_PROVIDERS`` or ``providers.yaml`` next to this module."""
    return Path(
        os.environ.get("WEBSCRAPER_PROVIDERS") or Path(__file__).with_name("providers.yaml")
    )


def parse_providers(raw: Any) -> tuple[Provider, ...]:
    """Validate a parsed ``providers.yaml`` and build the providers (defaults merged in)."""
    if not isinstance(raw, dict) or not isinstance(raw.get("providers"), list):
        raise ConfigError("providers.yaml needs a top-level 'providers' list")
    defaults = {"effort": "medium", "maxretry": 1, "maxms": 60000, "enabled": True, "kind": "api"}
    defaults.update(raw.get("defaults") or {})
    out: list[Provider] = []
    seen: set[str] = set()
    for i, item in enumerate(raw["providers"], 1):
        if not isinstance(item, dict):
            raise ConfigError(f"provider #{i} must be a mapping")
        unknown = set(item) - _FIELDS
        if unknown:
            raise ConfigError(f"provider #{i}: unknown field(s) {sorted(unknown)}")
        cfg = {**defaults, **item}
        name = cfg.get("name")
        if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9_-]*", name):
            raise ConfigError(f"provider #{i}: 'name' must be lowercase letters, digits, - or _")
        if name in seen:
            raise ConfigError(f"duplicate provider {name!r}")
        seen.add(name)
        kind = cfg["kind"]
        if kind not in ("api", "cli"):
            raise ConfigError(f"{name}: kind must be 'api' or 'cli'")
        if not isinstance(cfg.get("model"), str) or not cfg["model"]:
            raise ConfigError(f"{name}: 'model' is required")
        keys: Any = cfg.get("keys") or []
        command: Any = cfg.get("command") or []
        if kind == "api":
            if not isinstance(cfg.get("base_url"), str) or not cfg["base_url"]:
                raise ConfigError(f"{name}: 'base_url' is required")
            if command:
                raise ConfigError(f"{name}: 'command' is only for kind: cli")
            if (
                not isinstance(keys, list)
                or not keys
                or not all(isinstance(k, str) and re.fullmatch(r"[A-Z][A-Z0-9_]*", k) for k in keys)
            ):
                raise ConfigError(f"{name}: 'keys' must be a list of environment variable names")
        else:
            if keys or cfg.get("base_url") or cfg.get("extra_body"):
                raise ConfigError(
                    f"{name}: a cli provider takes 'command', not keys/base_url/extra_body"
                )
            if (
                not isinstance(command, list)
                or not command
                or not all(isinstance(c, str) for c in command)
            ):
                raise ConfigError(f"{name}: 'command' must be a non-empty list of strings")
        if cfg["effort"] not in EFFORT_TOKENS:
            raise ConfigError(f"{name}: effort must be one of {sorted(EFFORT_TOKENS)}")
        if not isinstance(cfg["maxretry"], int) or isinstance(cfg["maxretry"], bool):
            raise ConfigError(f"{name}: maxretry must be an integer")
        if not 0 <= cfg["maxretry"] <= 5:
            raise ConfigError(f"{name}: maxretry must be between 0 and 5")
        if not isinstance(cfg["maxms"], int) or isinstance(cfg["maxms"], bool) or cfg["maxms"] <= 0:
            raise ConfigError(f"{name}: maxms must be a positive integer (milliseconds)")
        if not isinstance(cfg["enabled"], bool):
            raise ConfigError(f"{name}: enabled must be true or false")
        extra = cfg.get("extra_body") or {}
        if not isinstance(extra, dict) or {"model", "messages"} & set(extra):
            raise ConfigError(f"{name}: extra_body must be a mapping without model/messages")
        out.append(
            Provider(
                name=name,
                base_url=(cfg.get("base_url") or "").rstrip("/"),
                key_envs=tuple(keys),
                model=cfg["model"],
                effort=cfg["effort"],
                maxretry=cfg["maxretry"],
                maxms=cfg["maxms"],
                enabled=cfg["enabled"],
                extra_body=extra,
                kind=kind,
                command=tuple(command),
            )
        )
    return tuple(out)


def load_providers(path: Path | None = None) -> tuple[Provider, ...]:
    """Read and validate ``providers.yaml`` (raises ``ConfigError`` when missing or invalid)."""
    target = path or providers_path()
    try:
        raw = yaml.safe_load(target.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(f"cannot read {target}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"{target} is not valid YAML: {exc}") from exc
    return parse_providers(raw)


#: Every provider in ``providers.yaml``, disabled ones included.
PROVIDERS: tuple[Provider, ...] = load_providers()


def clean_answer(text: str) -> str:
    """Drop ``<think>…</think>`` blocks (MiniMax and some reasoning models put them in content)."""
    return _THINK.sub("", text).strip()


def _order(providers: tuple[Provider, ...]) -> tuple[Provider, ...]:
    """Enabled providers in file order, with ``LLM_FIRST`` moved to the front."""
    first = (os.environ.get("LLM_FIRST") or "").lower()
    return tuple(sorted((p for p in providers if p.enabled), key=lambda p: p.name != first))


async def _post(
    client: httpx2.AsyncClient, prov: Provider, key: str, body: dict[str, Any]
) -> tuple[str, httpx2.Response | None]:
    """POST once per attempt, retrying transient failures; returns ``(status, response)``.

    ``status`` is the final HTTP code or the exception name. Keys never appear in it.
    """
    status = "no attempt"
    for attempt in range(prov.maxretry + 1):
        if attempt:
            await asyncio.sleep(RETRY_BASE_S * 2 ** (attempt - 1))
        try:
            resp = await client.post(
                f"{prov.base_url}/chat/completions",
                json=body,
                headers={"Authorization": f"Bearer {key}"},
                timeout=prov.maxms / 1000,
            )
        except httpx2.HTTPError as exc:
            status = type(exc).__name__
            continue
        status = str(resp.status_code)
        if resp.status_code in TRANSIENT:
            continue
        return status, resp
    return status, None


def _cli_env() -> dict[str, str]:
    """The only environment a cli provider sees: no API keys, no secrets."""
    return {k: os.environ[k] for k in CLI_ENV_ALLOWLIST if k in os.environ}


async def run_cli(prov: Provider, prompt: str) -> tuple[str, str]:
    """Run a ``cli`` provider once; returns ``(status, answer)`` (``"ok"`` on success).

    The prompt is sent on stdin. The child runs in an empty temporary directory with
    :func:`_cli_env` and is killed after ``maxms``. A timeout is retried ``maxretry`` times; any
    other failure (login expired, usage limit, crash) is reported at once.
    """
    status = "no attempt"
    for attempt in range(prov.maxretry + 1):
        if attempt:
            await asyncio.sleep(RETRY_BASE_S * 2 ** (attempt - 1))
        with tempfile.TemporaryDirectory(prefix="llm-cli-") as cwd:
            try:
                proc = await asyncio.create_subprocess_exec(
                    *prov.argv(),
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                    cwd=cwd,
                    env=_cli_env(),
                )
            except OSError as exc:
                return type(exc).__name__, ""
            try:
                out, _ = await asyncio.wait_for(
                    proc.communicate(prompt.encode()), timeout=prov.maxms / 1000
                )
            except TimeoutError:
                proc.kill()
                await proc.wait()
                status = "timeout"
                continue
        if proc.returncode != 0:
            return f"exit {proc.returncode}", ""
        return "ok", clean_answer(out.decode(errors="replace"))
    return status, ""


async def chat(
    prompt: str,
    system: str | None = None,
    *,
    max_tokens: int | None = None,
    providers: tuple[Provider, ...] | None = None,
    client: httpx2.AsyncClient | None = None,
) -> tuple[str, str]:
    """Return ``(answer, "provider/model")`` from the first provider that answers.

    ``max_tokens`` overrides each api provider's ``effort`` budget (cli providers ignore it).
    """
    messages: list[dict[str, str]] = ([{"role": "system", "content": system}] if system else []) + [
        {"role": "user", "content": prompt}
    ]
    cli_prompt = f"{system}\n\n{prompt}" if system else prompt
    errors: list[str] = []
    own = client is None
    client = client or httpx2.AsyncClient()
    try:
        for prov in _order(PROVIDERS if providers is None else providers):
            model = prov.chosen_model()
            if prov.kind == "cli":
                if not prov.available:
                    errors.append(f"{prov.name}: {prov.command[0]} not found")
                    continue
                status, text = await run_cli(prov, cli_prompt)
                if status == "ok" and text:
                    return text, f"{prov.name}/{model}"
                errors.append(f"{prov.name}: {status if status != 'ok' else 'empty answer'}")
                continue
            keys = prov.keys()
            if not keys:
                errors.append(f"{prov.name}: no key")
                continue
            body: dict[str, Any] = {
                **prov.extra_body,
                "model": model,
                "messages": messages,
                "max_tokens": max_tokens or prov.max_tokens,
            }
            for n, key in enumerate(keys, 1):
                status, resp = await _post(client, prov, key, body)
                if resp is None or resp.status_code in PERMANENT:
                    errors.append(f"{prov.name}#{n}: {status}")
                    continue
                resp.raise_for_status()
                text = clean_answer(resp.json()["choices"][0]["message"].get("content") or "")
                if text:
                    return text, f"{prov.name}/{model}"
                errors.append(f"{prov.name}#{n}: empty answer")
    finally:
        if own:
            await client.aclose()
    raise LLMError("no provider answered (" + "; ".join(errors) + ")")


async def probe(
    providers: tuple[Provider, ...] | None = None, *, client: httpx2.AsyncClient | None = None
) -> list[tuple[str, str, str]]:
    """Send a tiny "hi" with every key of every provider; returns ``(label, status, model)``.

    ``status`` is the HTTP code or exception name (``disabled`` / ``no key`` / ``not found`` when
    nothing was sent; ``ok`` for a cli provider that answered). Keys are never included. No retries.
    """
    own = client is None
    client = client or httpx2.AsyncClient()
    rows: list[tuple[str, str, str]] = []
    try:
        for prov in PROVIDERS if providers is None else providers:
            if not prov.enabled:
                rows.append((prov.name, "disabled", prov.chosen_model()))
                continue
            if prov.kind == "cli":
                if not prov.available:
                    rows.append((prov.name, "not found", prov.chosen_model()))
                    continue
                status, text = await run_cli(prov, "hi")
                rows.append(
                    (prov.name, status if status != "ok" or text else "empty", prov.chosen_model())
                )
                continue
            keys = prov.keys()
            if not keys:
                rows.append((prov.name, "no key", prov.chosen_model()))
                continue
            for n, key in enumerate(keys, 1):
                body = {
                    **prov.extra_body,
                    "model": prov.chosen_model(),
                    "messages": [{"role": "user", "content": "hi"}],
                    "max_tokens": 5,
                }
                try:
                    resp = await client.post(
                        f"{prov.base_url}/chat/completions",
                        json=body,
                        headers={"Authorization": f"Bearer {key}"},
                        timeout=min(prov.maxms / 1000, 40.0),
                    )
                    status = str(resp.status_code)
                except httpx2.HTTPError as exc:
                    status = type(exc).__name__
                rows.append((f"{prov.name}#{n}", status, prov.chosen_model()))
    finally:
        if own:
            await client.aclose()
    return rows
