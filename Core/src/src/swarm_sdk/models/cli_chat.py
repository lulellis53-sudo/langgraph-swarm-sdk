"""Chat models backed by a local agent CLI (``claude -p``, ``codex exec``, ``grok``).

These use the account the CLI is already logged into, so no API key or credit balance is
needed. The CLIs cannot return native tool calls, so tool use goes through a small JSON
protocol: when tools are bound the model is told to answer with exactly one JSON object,
``{"tool": name, "args": {...}}`` to call a tool or ``{"final": "..."}`` to finish. The reply is
parsed back into a normal ``AIMessage`` (with ``tool_calls`` when a tool was requested), so
``create_agent`` and the WebSearch browser agent work unchanged.

The prompt travels on stdin, never in argv. The CLIs run in an empty temporary directory with
their own tools disabled or read-only, so the model cannot touch the repository; every tool the
agent can use is one of the bound LangChain tools.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import uuid
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import ConfigDict, Field

if TYPE_CHECKING:
    from langchain_core.callbacks import CallbackManagerForLLMRun

#: ``(argv, stdin_text, timeout_s) -> stdout``; replaced in tests.
Runner = Callable[[Sequence[str], str, float], str]

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)
TOOL_PROTOCOL = (
    "You can call tools. Reply with EXACTLY one JSON object and nothing else.\n"
    'To call a tool: {"tool": "<tool name>", "args": {<arguments>}}\n'
    'To give the final answer: {"final": "<answer text>"}\n'
    "Call at most one tool per reply. Available tools (JSON schema):\n"
)


class CliError(RuntimeError):
    """The CLI could not be run, timed out, exited non-zero, or printed nothing."""


#: API credentials the child must not inherit: with one set, the CLI would use it instead of
#: its own login (and fail when that key has no balance).
_STRIP_ENV = frozenset(
    {"ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "OPENAI_API_KEY", "XAI_API_KEY"}
)
#: argv token replaced by the path of a temp file holding the prompt (for CLIs without stdin input).
PROMPT_FILE = "{PROMPT_FILE}"


def _failure_detail(proc: subprocess.CompletedProcess[str]) -> str:
    """The error lines of a failed CLI run (banners and progress logs are skipped)."""
    lines = [line.strip() for line in (proc.stderr or proc.stdout).splitlines() if line.strip()]
    errors = [line for line in lines if "error" in line.lower()]
    return " ".join((errors or lines[-2:])[:2])[:240]


def run_subprocess(argv: Sequence[str], stdin_text: str, timeout_s: float) -> str:
    """Run ``argv`` without a shell in an empty temp dir, feeding ``stdin_text``.

    The child does not inherit ``ANTHROPIC_API_KEY``, ``ANTHROPIC_AUTH_TOKEN`` or
    ``OPENAI_API_KEY``, so each CLI uses its own login.

    Raises:
        CliError: On a missing binary, a timeout, or a non-zero exit (stderr tail included).
    """
    env = {key: value for key, value in os.environ.items() if key not in _STRIP_ENV}
    try:
        with tempfile.TemporaryDirectory(prefix="swarm-cli-") as cwd:
            command = list(argv)
            if PROMPT_FILE in command:
                prompt_path = Path(cwd) / "prompt.txt"
                prompt_path.write_text(stdin_text, encoding="utf-8")
                command = [str(prompt_path) if part == PROMPT_FILE else part for part in command]
            proc = subprocess.run(
                command,
                input=None if PROMPT_FILE in argv else stdin_text,
                capture_output=True,
                text=True,
                timeout=timeout_s,
                check=False,
                cwd=cwd,
                env=env,
            )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CliError(f"{argv[0]}: {type(exc).__name__}: {exc}") from exc
    if proc.returncode != 0:
        raise CliError(f"{argv[0]} exited {proc.returncode}: {_failure_detail(proc)}")
    return proc.stdout


def _claude_argv(model: str) -> list[str]:
    argv = [
        "claude",
        "-p",
        "--output-format",
        "json",
        "--tools",
        "",
        "--no-session-persistence",
        "--disable-slash-commands",
        "--strict-mcp-config",
        "--setting-sources",
        "",
    ]
    return [*argv, "--model", model] if model and model != "default" else argv


def _codex_argv(model: str) -> list[str]:
    argv = ["codex", "exec", "--skip-git-repo-check", "--ephemeral", "-s", "read-only"]
    argv += ["--color", "never"]
    if model.startswith("profile:"):
        return [*argv, "-p", model.removeprefix("profile:")]
    return [*argv, "-m", model] if model and model != "default" else argv


def _claude_reply(stdout: str) -> tuple[str, int | None]:
    """Text and total tokens from ``claude -p --output-format json``."""
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise CliError("claude printed non-JSON output") from exc
    if not isinstance(data, dict) or data.get("is_error"):
        raise CliError(f"claude reported an error: {str(data.get('result', ''))[:200]}")
    usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    total = sum(
        int(usage.get(key) or 0)
        for key in ("input_tokens", "output_tokens", "cache_creation_input_tokens")
        + ("cache_read_input_tokens",)
    )
    return str(data.get("result", "")), total or None


def _codex_reply(stdout: str) -> tuple[str, int | None]:
    return stdout.strip(), None


def _grok_bin() -> str:
    """``grok`` on PATH, else the installer's ``~/.grok/bin/grok``."""
    return shutil.which("grok") or str(Path.home() / ".grok" / "bin" / "grok")


def _grok_argv(model: str) -> list[str]:
    argv = [
        _grok_bin(),
        "--prompt-file",
        PROMPT_FILE,
        "--output-format",
        "plain",
        "--tools",
        "",
        "--max-turns",
        "1",
        "--no-subagents",
        "--no-plan",
        "--disable-web-search",
    ]
    return [*argv, "-m", model] if model and model != "default" else argv


_ADAPTERS: dict[str, tuple[Callable[[str], list[str]], Callable[[str], tuple[str, int | None]]]] = {
    "claude-cli": (_claude_argv, _claude_reply),
    "codex-cli": (_codex_argv, _codex_reply),
    "grok-cli": (_grok_argv, _codex_reply),  # plain output: stdout is the reply
}


def parse_reply(text: str) -> tuple[str, dict[str, Any] | None]:
    """Split a model reply into ``(final_text, tool_call)``.

    A reply whose first JSON object has ``tool`` is a tool call; one with ``final`` is the
    answer; anything else is returned as plain text.
    """
    body = _FENCE.sub("", text.strip())
    start = body.find("{")
    if start >= 0:
        try:
            obj, _ = json.JSONDecoder().raw_decode(body[start:])
        except json.JSONDecodeError:
            obj = None
        if isinstance(obj, dict):
            if isinstance(obj.get("tool"), str):
                args = obj.get("args")
                return "", {"name": obj["tool"], "args": args if isinstance(args, dict) else {}}
            if "final" in obj:
                return str(obj["final"]), None
    return text.strip(), None


def _render(messages: Sequence[BaseMessage], tools: Sequence[dict[str, Any]]) -> str:
    lines: list[str] = []
    for message in messages:
        content = message.content if isinstance(message.content, str) else str(message.content)
        if isinstance(message, ToolMessage):
            lines.append(f"TOOL RESULT ({message.name or 'tool'}):\n{content}")
        elif isinstance(message, AIMessage):
            if message.tool_calls:
                call = message.tool_calls[0]
                lines.append(
                    f"ASSISTANT: {json.dumps({'tool': call['name'], 'args': call['args']})}"
                )
            else:
                lines.append(f"ASSISTANT: {content}")
        else:
            lines.append(f"{message.type.upper()}: {content}")
    if tools:
        schema = json.dumps([t["function"] for t in tools], indent=1)
        lines.append(TOOL_PROTOCOL + schema)
    lines.append("ASSISTANT:")
    return "\n\n".join(lines)


class CliChatModel(BaseChatModel):
    """A LangChain chat model that shells out to ``claude -p`` or ``codex exec``.

    Attributes:
        provider: ``claude-cli``, ``codex-cli`` or ``grok-cli``.
        model: Model for the CLI (``default`` keeps the CLI's own); for ``codex-cli``,
            ``profile:NAME`` selects a config profile (``codex -p NAME``).
        timeout_s: Per-call limit.
        tools: OpenAI-format tool specs set by :meth:`bind_tools`.
        runner: Process runner, replaceable in tests.
    """

    provider: str
    model: str = "default"
    timeout_s: float = 180.0
    tools: list[dict[str, Any]] = Field(default_factory=list)
    runner: Runner = run_subprocess
    model_config = ConfigDict(arbitrary_types_allowed=True)

    @property
    def _llm_type(self) -> str:
        return self.provider

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> CliChatModel:
        """Return a copy that knows ``tools``; the JSON protocol is added to every prompt."""
        del kwargs
        return self.model_copy(update={"tools": [convert_to_openai_tool(t) for t in tools]})

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        del stop, run_manager, kwargs
        build_argv, read_reply = _ADAPTERS[self.provider]
        stdout = self.runner(build_argv(self.model), _render(messages, self.tools), self.timeout_s)
        text, tokens = read_reply(stdout)
        if not text.strip():
            raise CliError(f"{self.provider} returned an empty reply")
        content, call = parse_reply(text) if self.tools else (text.strip(), None)
        meta = (
            {"input_tokens": 0, "output_tokens": tokens, "total_tokens": tokens} if tokens else None
        )
        message = AIMessage(
            content=content,
            tool_calls=[{**call, "id": f"call-{uuid.uuid4().hex[:12]}", "type": "tool_call"}]
            if call
            else [],
            usage_metadata=meta,
        )
        return ChatResult(generations=[ChatGeneration(message=message)])


def load_cli_model(provider: str, model: str = "default") -> CliChatModel:
    """Build the chat model for ``claude-cli:``, ``codex-cli:`` or ``grok-cli:<model>``."""
    if provider not in _ADAPTERS:
        raise ValueError(f"unknown CLI provider {provider!r}; choose from {sorted(_ADAPTERS)}")
    return CliChatModel(provider=provider, model=model)


CLI_PROVIDERS = frozenset(_ADAPTERS)

__all__ = [
    "CLI_PROVIDERS",
    "CliChatModel",
    "CliError",
    "load_cli_model",
    "parse_reply",
    "run_subprocess",
]
