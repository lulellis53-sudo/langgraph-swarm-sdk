"""Run one Swarm agent from an ``@agent --Task`` command.

The command line names a folder under ``Agents/`` (or that folder's manifest
``name``) and the prompt that agent should answer:

    @coder --Task "Write a parser" --Effort HIGH --MaxMS 1500 --MaxTry 2

``--Effort`` overrides the manifest when it is present. ``--MaxMS`` and
``--MaxTry`` bound each attempt; they are not fields of ``agent.yaml``.
"""

import asyncio
import logging
import re
import shlex
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from swarm_sdk.agents.manifest import AgentManifest, agents_root, load_agent_manifest
from swarm_sdk.orchestrator.plan import StepOutput

logger = logging.getLogger(__name__)

__all__ = [
    "AgentSelectorError",
    "ResolvedTask",
    "TaskCommand",
    "TaskCommandError",
    "TaskRunError",
    "TaskSyntaxError",
    "parse_task_argv",
    "parse_task_command",
    "resolve_task",
    "run_task_command",
]

DEFAULT_MAX_MS = 60_000
DEFAULT_MAX_TRY = 3

_SELECTOR = re.compile(r"[A-Za-z][A-Za-z0-9_-]*")
_EFFORTS = frozenset({"low", "medium", "high"})
_SKIP = frozenset({"tests", "benchmark"})
_FLAGS = {
    "--task": "task",
    "-t": "task",
    "--effort": "effort",
    "--maxms": "ms",
    "--max-ms": "ms",
    "--maxtry": "try",
    "--max-try": "try",
}

type TaskRunner = Callable[["ResolvedTask"], Awaitable[StepOutput]]


class TaskCommandError(Exception):
    """Base error for an ``@agent --Task`` command."""


class TaskSyntaxError(TaskCommandError):
    """The command line does not match ``@agent --Task``."""


class AgentSelectorError(TaskCommandError):
    """No single ``Agents/*/agent.yaml`` matches the selector."""


class TaskRunError(TaskCommandError):
    """The agent did not finish inside the retry budget."""


@dataclass(frozen=True, slots=True)
class TaskCommand:
    """One parsed ``@agent --Task`` invocation.

    Attributes:
        selector: Agent token without the leading ``@``.
        prompt: Text after ``--Task``.
        effort: ``low``, ``medium``, or ``high`` when ``--Effort`` was set.
        max_ms: Per-attempt timeout in milliseconds.
        max_try: How many attempts to make before giving up.
    """

    selector: str
    prompt: str
    effort: str | None
    max_ms: int
    max_try: int


@dataclass(frozen=True, slots=True)
class ResolvedTask:
    """A command bound to one manifest on disk.

    Attributes:
        command: The parsed invocation.
        directory: Folder name under ``Agents/``.
        manifest: Validated manifest for that folder.
        agents_root: Directory that contains the agent folder.
    """

    command: TaskCommand
    directory: str
    manifest: AgentManifest
    agents_root: Path


def parse_task_command(text: str) -> TaskCommand:
    """Parse one ``@agent --Task`` command string.

    Args:
        text: The full command, including quotes around the prompt.

    Returns:
        The parsed command. Omitted ``--Effort`` stays ``None``.

    Raises:
        TaskSyntaxError: When the quotes, flags, or agent token are invalid.
    """
    try:
        argv = shlex.split(text, posix=True)
    except ValueError as err:
        raise TaskSyntaxError("could not parse the command quotes") from err
    return parse_task_argv(argv)


def parse_task_argv(argv: Sequence[str]) -> TaskCommand:
    """Parse an already split ``@agent --Task`` argument list.

    Args:
        argv: Tokens as the shell would pass them, without the program name.

    Returns:
        The parsed command.

    Raises:
        TaskSyntaxError: When a required piece is missing or a flag is unknown.
    """
    if not argv:
        raise TaskSyntaxError('expected @agent --Task "prompt"')
    selector: str | None = None
    prompt: str | None = None
    effort: str | None = None
    max_ms = DEFAULT_MAX_MS
    max_try = DEFAULT_MAX_TRY
    seen: set[str] = set()
    index = 0
    while index < len(argv):
        token = argv[index]
        if token.startswith("@"):
            if selector is not None:
                raise TaskSyntaxError("only one @agent is allowed")
            name = token[1:]
            if _SELECTOR.fullmatch(name) is None:
                raise TaskSyntaxError(f"invalid agent selector {token}")
            selector = name
            index += 1
            continue
        flag, inline = _split_flag(token)
        key = _FLAGS.get(flag.lower())
        if key is None:
            raise TaskSyntaxError(f"unknown argument {token}")
        if key in seen:
            raise TaskSyntaxError(f"duplicate argument {flag}")
        seen.add(key)
        if inline is None:
            index += 1
            if index >= len(argv):
                raise TaskSyntaxError(f"{flag} needs a value")
            value = argv[index]
        else:
            value = inline
        if value.startswith("-"):
            raise TaskSyntaxError(f"{flag} needs a value")
        if key == "task":
            if not value.strip():
                raise TaskSyntaxError("--Task must not be empty")
            prompt = value
        elif key == "effort":
            lowered = value.lower()
            if lowered not in _EFFORTS:
                raise TaskSyntaxError("--Effort must be low, medium, or high")
            effort = lowered
        elif key == "ms":
            max_ms = _positive_int(flag, value)
        else:
            max_try = _positive_int(flag, value)
        index += 1
    if selector is None:
        raise TaskSyntaxError("missing @agent")
    if prompt is None:
        raise TaskSyntaxError("missing --Task")
    return TaskCommand(
        selector=selector,
        prompt=prompt,
        effort=effort,
        max_ms=max_ms,
        max_try=max_try,
    )


def resolve_task(command: TaskCommand, *, agents_dir: Path | None = None) -> ResolvedTask:
    """Bind ``command`` to the one matching ``agent.yaml``.

    Args:
        command: Parsed invocation.
        agents_dir: Folder of ``Agents/*/agent.yaml``. Defaults to the Swarm tree.

    Returns:
        The directory, manifest, and agents root.

    Raises:
        AgentSelectorError: When the selector matches none or more than one agent,
            or the agents directory is missing.
    """
    root = agents_dir or agents_root()
    if not root.is_dir():
        raise AgentSelectorError(f"agents directory does not exist: {root}")
    needle = _aliases(command.selector)
    found: list[tuple[str, AgentManifest]] = []
    known: list[str] = []
    for path in sorted(root.glob("*/agent.yaml")):
        directory = path.parent.name
        if directory in _SKIP:
            continue
        known.append(directory)
        try:
            manifest = load_agent_manifest(path)
        except ValueError as err:
            raise AgentSelectorError(f"invalid manifest {path}") from err
        aliases = _aliases(directory) | _aliases(manifest.name)
        if needle & aliases:
            found.append((directory, manifest))
    if len(found) == 1:
        directory, manifest = found[0]
        return ResolvedTask(
            command=command,
            directory=directory,
            manifest=manifest,
            agents_root=root,
        )
    if not found:
        listed = ", ".join(known) if known else "(none)"
        raise AgentSelectorError(f"no agent matches @{command.selector}; known: {listed}")
    names = ", ".join(directory for directory, _manifest in found)
    raise AgentSelectorError(
        f"agent selector @{command.selector} matched more than one agent: {names}"
    )


async def run_task_command(
    command: TaskCommand,
    *,
    agents_dir: Path | None = None,
    runner: TaskRunner | None = None,
) -> StepOutput:
    """Resolve the agent and run the prompt with a timeout and retries.

    Args:
        command: Parsed invocation.
        agents_dir: Optional override for the ``Agents/`` directory.
        runner: Replacement for the worker call. Tests pass this so no provider
            is contacted. The default runner loads the manifest model.

    Returns:
        The worker output from the attempt that finished.

    Raises:
        AgentSelectorError: When the agent cannot be resolved.
        TaskRunError: When every attempt times out or raises.
    """
    resolved = resolve_task(command, agents_dir=agents_dir)
    invoke = runner or _run_with_worker
    last: Exception | None = None
    for attempt in range(1, command.max_try + 1):
        try:
            return await asyncio.wait_for(invoke(resolved), timeout=command.max_ms / 1000)
        except TimeoutError as err:
            last = err
            logger.warning("task attempt %s timed out", attempt)
        except TaskCommandError:
            raise
        except Exception as err:
            last = err
            logger.warning("task attempt %s failed: %s", attempt, type(err).__name__)
    assert last is not None
    raise TaskRunError(
        f"{resolved.directory} failed after {command.max_try} attempts ({type(last).__name__})"
    ) from last


def main_at(argv: Sequence[str]) -> int:
    """CLI entry for ``low-swarm @agent --Task "prompt"``.

    Args:
        argv: Arguments after the program name.

    Returns:
        ``0`` when the agent replies with status ``ok``, ``1`` when the run
        fails or the reply is blocked, ``2`` when the command is invalid.
    """
    import sys

    try:
        command = parse_task_argv(argv)
        output = asyncio.run(run_task_command(command))
    except (TaskSyntaxError, AgentSelectorError) as err:
        print(err, file=sys.stderr)
        return 2
    except TaskRunError as err:
        print(err, file=sys.stderr)
        return 1
    print(output.content)
    return 0 if output.status == "ok" else 1


def _split_flag(token: str) -> tuple[str, str | None]:
    """Split ``--Flag=value`` into the flag and an optional inline value."""
    if token.startswith("-") and "=" in token:
        flag, value = token.split("=", 1)
        return flag, value
    return token, None


def _positive_int(flag: str, raw: str) -> int:
    """Parse a flag value that must be an integer of at least 1."""
    if not raw.isdecimal():
        raise TaskSyntaxError(f"{flag} must be a positive integer")
    value = int(raw)
    if value < 1:
        raise TaskSyntaxError(f"{flag} must be a positive integer")
    return value


def _aliases(label: str) -> set[str]:
    """Case-folded forms of a directory or manifest name, with and without hyphens."""
    folded = label.casefold().replace("_", "-")
    return {folded, folded.replace("-", "")}


async def _run_with_worker(resolved: ResolvedTask) -> StepOutput:
    """Call the manifest's model with the task prompt."""
    from swarm_sdk.orchestrator.worker import WorkerAgent

    manifest = resolved.manifest
    if resolved.command.effort is not None:
        manifest = manifest.model_copy(update={"effort": resolved.command.effort})
    worker = WorkerAgent(manifest, agents_root=str(resolved.agents_root))
    return await worker.run("task", resolved.command.prompt, {})
