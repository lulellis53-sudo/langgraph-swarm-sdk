"""Tests for the @agent --Task command."""

import asyncio
from pathlib import Path

import pytest

from swarm_sdk.cli import main
from swarm_sdk.orchestrator.plan import StepOutput
from swarm_sdk.orchestrator.task_command import (
    AgentSelectorError,
    ResolvedTask,
    TaskCommand,
    TaskRunError,
    TaskSyntaxError,
    parse_task_argv,
    parse_task_command,
    resolve_task,
    run_task_command,
)

_MANIFEST = """\
version: 1
name: {name}
role: fixture
model: anthropic:claude-sonnet-4.6
think_level: medium
effort: high
api_key_env: CLAUDE_OAUTH_TOKEN
token_budget:
  max_prompt: 128
  max_completion: 32
"""


def _agent(root: Path, directory: str, name: str) -> None:
    folder = root / directory
    folder.mkdir(parents=True)
    (folder / "agent.yaml").write_text(_MANIFEST.format(name=name), encoding="utf-8")


def test_parse_quoted_task_and_limits() -> None:
    """Quotes, effort, timeout, and retries survive one command line."""
    command = parse_task_command(
        '@Coder --Task "Write a parser" --Effort HIGH --MaxMS 1500 --MaxTry 2'
    )
    assert command == TaskCommand(
        selector="Coder",
        prompt="Write a parser",
        effort="high",
        max_ms=1500,
        max_try=2,
    )


def test_parse_argv_defaults() -> None:
    """A shell-split command defaults the limits and leaves effort unset."""
    command = parse_task_argv(["@coder", "--Task", "ping"])
    assert command.selector == "coder"
    assert command.prompt == "ping"
    assert command.effort is None
    assert command.max_ms == 60_000
    assert command.max_try == 3


@pytest.mark.parametrize(
    "text",
    [
        "@coder",
        '--Task "only a prompt"',
        '@coder --Task "x" --Effort MAX',
        '@coder --Task "x" --MaxMS 0',
        '@coder --Task "x" --nope',
        '@coder --Task "x" --Task "again"',
        '@coder @reviewer --Task "x"',
    ],
)
def test_parse_rejects_bad_commands(text: str) -> None:
    """Missing, duplicate, and unknown pieces raise a syntax error."""
    with pytest.raises(TaskSyntaxError):
        parse_task_command(text)


def test_resolve_directory_and_manifest_name(tmp_path: Path) -> None:
    """@name matches the folder or the manifest name, ignoring case and hyphens."""
    agents = tmp_path / "Agents"
    _agent(agents, "Coder", "Coder")
    _agent(agents, "Benchmarker", "Benchmarker")
    by_folder = resolve_task(parse_task_command('@coder --Task "a"'), agents_dir=agents)
    by_name = resolve_task(
        parse_task_command('@Benchmarker --Task "b"'),
        agents_dir=agents,
    )
    assert by_folder.directory == "Coder"
    assert by_folder.manifest.model == "anthropic:claude-sonnet-4.6"
    assert by_name.directory == "Benchmarker"
    assert by_name.manifest.name == "Benchmarker"


def test_resolve_unknown_and_ambiguous(tmp_path: Path) -> None:
    """Zero matches and two matches are both selector errors."""
    agents = tmp_path / "Agents"
    _agent(agents, "Coder", "Coder")
    _agent(agents, "Helper", "coder")
    with pytest.raises(AgentSelectorError, match="no agent"):
        resolve_task(parse_task_command('@missing --Task "a"'), agents_dir=agents)
    with pytest.raises(AgentSelectorError, match="more than one"):
        resolve_task(parse_task_command('@coder --Task "a"'), agents_dir=agents)


def test_run_retries_then_returns(tmp_path: Path) -> None:
    """A failing attempt is retried until the runner returns."""
    agents = tmp_path / "Agents"
    _agent(agents, "Coder", "Coder")
    seen: list[str] = []

    async def runner(resolved: ResolvedTask) -> StepOutput:
        seen.append(resolved.command.prompt)
        if len(seen) == 1:
            raise RuntimeError("transient")
        return StepOutput(step_id="task", agent=resolved.directory, content="done")

    command = parse_task_command('@coder --Task "fix it" --MaxTry 2')
    output = asyncio.run(run_task_command(command, agents_dir=agents, runner=runner))
    assert output.content == "done"
    assert seen == ["fix it", "fix it"]


def test_run_stops_after_the_timeout(tmp_path: Path) -> None:
    """Each attempt is bounded by --MaxMS."""
    agents = tmp_path / "Agents"
    _agent(agents, "Coder", "Coder")

    async def runner(resolved: ResolvedTask) -> StepOutput:
        await asyncio.sleep(5)
        return StepOutput(step_id="task", agent=resolved.directory, content="late")

    command = parse_task_command('@coder --Task "slow" --MaxMS 30 --MaxTry 1')
    with pytest.raises(TaskRunError, match="TimeoutError"):
        asyncio.run(run_task_command(command, agents_dir=agents, runner=runner))


def test_cli_prints_the_agent_reply(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """low-swarm @agent --Task prints the reply and does not treat @ as a subcommand."""

    async def fake(command: TaskCommand, **kwargs: object) -> StepOutput:
        assert command.prompt == "hello"
        assert command.selector == "coder"
        return StepOutput(step_id="task", agent="Coder", content="ok-body")

    monkeypatch.setattr("swarm_sdk.orchestrator.task_command.run_task_command", fake)
    assert main(["@coder", "--Task", "hello"]) == 0
    assert capsys.readouterr().out.strip() == "ok-body"


def test_real_coder_selector() -> None:
    """The installed Coder persona is reachable as @coder."""
    agents = Path(__file__).resolve().parents[1] / "Agents"
    manifest = agents / "Coder" / "agent.yaml"
    if not manifest.is_file():
        pytest.skip("Coder manifest is not in this tree")
    resolved = resolve_task(parse_task_command('@coder --Task "ping"'), agents_dir=agents)
    assert resolved.directory == "Coder"
    assert resolved.manifest.name == "Coder"
