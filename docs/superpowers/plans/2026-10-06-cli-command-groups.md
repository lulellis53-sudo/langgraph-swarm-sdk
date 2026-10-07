# CLI command groups (agentic, spawn, swarm, parallel) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Organize the `low-swarm` CLI into four command groups — `agentic` (today's `run`, kept as an alias), `spawn`, `swarm`, `parallel` — exposing the SDK's goal decomposition, handoff swarm and wave-parallel plan execution.

**Architecture:** A new `swarm_sdk/commands/` package holds one module per new group. Each module exposes `register(subparsers) -> tuple[str, Handler]` and a `handle_*(args, console) -> int`. `cli.py` builds its parser and dispatch table from `commands.register_all`, and keeps `run` working through an alias. Handlers call the existing SDK entry points (`orchestrator.spawn`, `SwarmSDK.run`, `orchestrator.run_plan`/`make_factory`); tests replace those with fakes, so no model or API key is needed.

**Tech Stack:** Python 3.14, argparse, pydantic models already in `swarm_sdk.orchestrator`, pytest (`asyncio_mode=auto`), ruff, ty.

**Spec:** none written. The design was agreed in chat (the "Proposed command groups" table: `agentic`=`run` alias, `spawn GOAL`, `swarm TEXT`, `parallel --plan|--goal`; `vault`, `ingest`, `doctor` unchanged; `swarm-api`, `swarm-grpc`, `websearch` untouched). This plan carries it; rulings made without a spec are provisional.

## Global Constraints

- Working directory for every command: `/Users/usuario/Swarm/WebSearch`.
- No behavior change to existing commands: `run`, `vault`, `ingest`, `doctor` and `main([])` (prints help, returns 2) behave exactly as before; `tests/test_cli.py` and `tests/test_websearch_cli.py` keep passing.
- Python `>=3.14.5`; ruff `line-length = 100`; new modules start with the docstring and `from __future__ import annotations` (repo rule). `ty check src` diagnostics must stay at or below 15; touched files ruff-clean.
- Handlers return an exit code (0 success, 1 runtime failure, 2 usage/input error) and print errors to stderr as `error: <message>`; they never raise for bad input and never print tracebacks.
- Secrets never printed. Do not run pytest with failure output enabled where credentials could appear: always use `--tb=no` for suite-wide runs; targeted runs of the new tests may use `--tb=short`.
- Commit only if the user asked (the user did not): implementers do not commit and do not run `git add`; review packages are snapshot diffs.
- Test command (root `__init__.py` breaks default collection): `uv run --extra dev --extra faiss pytest -c /dev/null --rootdir=tests -o asyncio_mode=auto <paths> -q -p no:cacheprovider`. Full-suite variant: `uv run --extra dev --extra faiss --extra observability pytest -c /dev/null --rootdir=tests -o asyncio_mode=auto tests -q --tb=no -p no:cacheprovider --continue-on-collection-errors`.
- Baseline the full suite must not fall below: `2 failed, 524+ passed, 9 errors` where all failures/errors are in `tests/test_static_templates.py` (its template files were deleted by another process; not part of this plan).

## Review Focus

- `spawn --json` must print pure JSON (no table markup or panel) so it can be piped: test parses stdout with `json.loads`.
- Missing or empty agent manifests (this worktree has no `Agents/` directory) must produce `error: ...` and exit 2, not a traceback.
- `parallel` with an unreadable or invalid `--plan` file, or a plan with a dependency cycle / overlapping files (`run_plan` raises `ValueError`), must exit 2 / 1 with an `error:` line.
- `parallel --max-concurrency 0` (or negative) is rejected by argparse (`main` returns 2); without the flag the cap comes from `swarm_sdk.runtime.parallel_cap()`.
- `agentic` and `run` must dispatch to the same handler with identical flags (alias, not a copy), and `--help` lists all four groups.

---

## File Structure

| Path | Responsibility |
|---|---|
| `src/swarm_sdk/commands/__init__.py` (new) | `Handler` type and `register_all(subparsers)` returning `{command name: handler}` |
| `src/swarm_sdk/commands/spawn.py` (new) | `spawn GOAL` command |
| `src/swarm_sdk/commands/swarm.py` (new) | `swarm TEXT` command |
| `src/swarm_sdk/commands/parallel.py` (new) | `parallel` command |
| `src/swarm_sdk/cli.py` (modify) | build parser and dispatch via the registry; `run` gains the `agentic` alias |
| `tests/test_cli_commands.py` (new) | tests for the new commands and the alias |
| `README.md` (modify) | command-group table |

---

### Task 1: Registry and the `spawn` command

**Files:**
- Create: `src/swarm_sdk/commands/__init__.py`, `src/swarm_sdk/commands/spawn.py`, `tests/test_cli_commands.py`
- Modify: `src/swarm_sdk/cli.py` (`build_parser` ~line 460 and the dispatch tail of `main`)

**Interfaces:**
- Produces: `swarm_sdk.commands.Handler = Callable[[argparse.Namespace, Any], int]`; `swarm_sdk.commands.register_all(subparsers) -> dict[str, Handler]`; `swarm_sdk.commands.spawn.register(subparsers) -> tuple[str, Handler]` and `handle_spawn(args, console) -> int`. Tasks 2–3 append their module to `register_all` using the same `register` shape.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_cli_commands.py`:

```python
"""Tests for the low-swarm command groups: spawn, swarm, parallel and the agentic alias."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from swarm_sdk import cli
from swarm_sdk.orchestrator.plan import Plan, PlanStep


def _plan() -> Plan:
    return Plan(
        steps=[
            PlanStep(
                id="S1", title="implement", description="write it", agent="Coder", files=["a.py"]
            ),
            PlanStep(
                id="S2", title="verify", description="test it", agent="Tester", depends_on=["S1"]
            ),
        ]
    )


@pytest.fixture
def fake_spawn(monkeypatch: pytest.MonkeyPatch) -> None:
    async def spawn(goal: str, manifests: object) -> Plan:
        return _plan()

    monkeypatch.setattr("swarm_sdk.commands.spawn.spawn", spawn)
    monkeypatch.setattr(
        "swarm_sdk.commands.spawn.load_all_agent_manifests", lambda agents_dir=None: {"Coder": MagicMock()}
    )


class TestSpawn:
    def test_renders_waves(self, fake_spawn: None, capsys: pytest.CaptureFixture[str]) -> None:
        assert cli.main(["spawn", "build a thing"]) == 0
        out = capsys.readouterr().out
        assert "S1" in out and "S2" in out
        assert "Coder" in out and "Tester" in out
        assert "2 step(s) in 2 wave(s)" in out

    def test_json_output_is_pure_json(
        self, fake_spawn: None, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert cli.main(["spawn", "build a thing", "--json"]) == 0
        data = json.loads(capsys.readouterr().out)
        assert [step["id"] for step in data["steps"]] == ["S1", "S2"]
        assert data["steps"][1]["depends_on"] == ["S1"]

    def test_no_manifests_is_an_input_error(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setattr(
            "swarm_sdk.commands.spawn.load_all_agent_manifests", lambda agents_dir=None: {}
        )
        assert cli.main(["spawn", "goal"]) == 2
        assert "error:" in capsys.readouterr().err

    def test_unreadable_agents_dir_is_an_input_error(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        def boom(agents_dir: object = None) -> dict[str, object]:
            raise FileNotFoundError("no Agents directory")

        monkeypatch.setattr("swarm_sdk.commands.spawn.load_all_agent_manifests", boom)
        assert cli.main(["spawn", "goal"]) == 2
        assert "error:" in capsys.readouterr().err

    def test_goal_is_required(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert cli.main(["spawn"]) == 2
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --extra dev --extra faiss pytest -c /dev/null --rootdir=tests -o asyncio_mode=auto tests/test_cli_commands.py -q --tb=line -p no:cacheprovider`
Expected: FAIL (`spawn` is an unknown subcommand: `main` returns 2 and `swarm_sdk.commands` does not exist, so the `monkeypatch.setattr("swarm_sdk.commands.spawn.spawn", ...)` fixture errors with ModuleNotFoundError/AttributeError).

- [ ] **Step 3: Write the registry and the spawn command**

`src/swarm_sdk/commands/__init__.py`:

```python
"""Command groups for the ``low-swarm`` CLI: spawn, swarm, parallel."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from typing import Any

type Handler = Callable[[argparse.Namespace, Any], int]


def register_all(subparsers: Any) -> dict[str, Handler]:
    """Register every command group on ``subparsers``; return ``{command: handler}``."""
    from swarm_sdk.commands import spawn

    handlers: dict[str, Handler] = {}
    for module in (spawn,):
        name, handler = module.register(subparsers)
        handlers[name] = handler
    return handlers


__all__ = ["Handler", "register_all"]
```

`src/swarm_sdk/commands/spawn.py`:

```python
"""``low-swarm spawn GOAL``: decompose a goal into a validated, wave-ordered plan."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Any

from swarm_sdk.agents.manifest import load_all_agent_manifests
from swarm_sdk.cli import create_panel, create_table
from swarm_sdk.commands import Handler
from swarm_sdk.orchestrator.spawn import spawn


def register(subparsers: Any) -> tuple[str, Handler]:
    parser = subparsers.add_parser("spawn", help="Decompose a goal into a plan of agent steps")
    parser.add_argument("goal", help="Free-text goal to decompose")
    parser.add_argument("--agents-dir", type=Path, default=None, help="Agents directory")
    parser.add_argument("--json", action="store_true", help="Print the plan as JSON only")
    return "spawn", handle_spawn


def handle_spawn(args: argparse.Namespace, console: Any) -> int:
    """Run the Orchestrator and print the plan (waves table, or JSON with ``--json``)."""
    try:
        manifests = load_all_agent_manifests(args.agents_dir)
    except (OSError, ValueError) as exc:
        print(f"error: cannot load agent manifests: {exc}", file=sys.stderr)
        return 2
    if not manifests:
        print("error: no agent manifests found (use --agents-dir)", file=sys.stderr)
        return 2

    plan = asyncio.run(spawn(args.goal, manifests))
    if args.json:
        print(plan.model_dump_json(indent=2))
        return 0
    try:
        waves = plan.waves()
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    table = create_table(title=f"Plan: {args.goal}")
    for column in ("Wave", "Step", "Agent", "Files", "Depends on"):
        table.add_column(column, style="bold" if column == "Wave" else None)
    for number, wave in enumerate(waves, 1):
        for step in wave:
            table.add_row(
                str(number),
                f"{step.id} {step.title}",
                step.agent,
                ", ".join(step.files) or "-",
                ", ".join(step.depends_on) or "-",
            )
    console.print(create_panel(table, title=f"{len(plan.steps)} step(s) in {len(waves)} wave(s)"))
    return 0
```

In `src/swarm_sdk/cli.py` `build_parser`, before `return parser`, add the registry call and keep the handlers on the parser object so `main` can dispatch:

```python
    from swarm_sdk.commands import register_all

    parser.set_defaults(_group_handlers=register_all(subparsers))
    return parser
```
In `main`, after `cmd = args.command` / `if not cmd: ...`, before the `if cmd == "run":` chain, add:
```python
    group_handler = args._group_handlers.get(cmd)
    if group_handler is not None:
        return group_handler(args, console)
```
(`parse_args` keeps the parser-level default `_group_handlers`; confirm with the tests.) `PlainTable.add_column` must accept `style=None`; if it does not, pass the keyword only for the "Wave" column (adapt the loop; do not change `PlainTable`).

- [ ] **Step 4: Run the tests to verify they pass**

Run the Step 2 command → PASS (5 tests). Then `uv run --extra dev --extra faiss pytest -c /dev/null --rootdir=tests -o asyncio_mode=auto tests/test_cli.py tests/test_websearch_cli.py -q --tb=short -p no:cacheprovider` → all pass (existing CLI unchanged). Then `uv run ruff check src/swarm_sdk/commands src/swarm_sdk/cli.py tests/test_cli_commands.py`, `uv run ruff format src/swarm_sdk/commands tests/test_cli_commands.py`, and `uv run --extra dev --extra observability ty check src 2>&1 | rg -c "^(error|warning)"` (≤ 15).

- [ ] **Step 5: Commit (only if the user asked)**

```bash
git add src/swarm_sdk/commands tests/test_cli_commands.py src/swarm_sdk/cli.py
git commit -m "feat(cli): add command registry and spawn command"
```

---

### Task 2: The `swarm` command

**Files:**
- Create: `src/swarm_sdk/commands/swarm.py`
- Modify: `src/swarm_sdk/commands/__init__.py` (add `swarm` to `register_all`), `tests/test_cli_commands.py`

**Interfaces:**
- Consumes: `register_all`, `Handler` (Task 1); `SwarmSDK.from_settings()` and `async SwarmSDK.run(text, thread_id="default") -> RunResult` where `RunResult(text: str, cached: bool, active_agent: str, tokens: int, mode: str)`.
- Produces: `swarm_sdk.commands.swarm.register`, `handle_swarm`, `_build_sdk() -> SwarmSDK` (the seam tests monkeypatch).

- [ ] **Step 1: Write the failing tests** (append to `tests/test_cli_commands.py`)

```python
from swarm_sdk.core.swarm import RunResult


class _FakeSDK:
    def __init__(self, result: RunResult | Exception) -> None:
        self.result = result
        self.calls: list[tuple[str, str]] = []

    async def run(self, text: str, thread_id: str = "default") -> RunResult:
        self.calls.append((text, thread_id))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class TestSwarm:
    def test_runs_and_prints_the_answer(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        sdk = _FakeSDK(RunResult(text="all done", cached=False, active_agent="coder", tokens=7, mode="swarm"))
        monkeypatch.setattr("swarm_sdk.commands.swarm._build_sdk", lambda: sdk)
        assert cli.main(["swarm", "fix the bug", "--thread-id", "t42"]) == 0
        out = capsys.readouterr().out
        assert "all done" in out and "coder" in out and "t42" in out
        assert sdk.calls == [("fix the bug", "t42")]

    def test_default_thread_id(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        sdk = _FakeSDK(RunResult(text="x", cached=True, active_agent="a", tokens=0, mode="swarm"))
        monkeypatch.setattr("swarm_sdk.commands.swarm._build_sdk", lambda: sdk)
        assert cli.main(["swarm", "hello"]) == 0
        assert sdk.calls == [("hello", "default")]

    def test_runtime_failure_is_reported_not_raised(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setattr(
            "swarm_sdk.commands.swarm._build_sdk", lambda: _FakeSDK(RuntimeError("provider down"))
        )
        assert cli.main(["swarm", "hello"]) == 1
        assert "error: provider down" in capsys.readouterr().err
```

- [ ] **Step 2: Run to verify failure**

Run the Task 1 Step 2 command. Expected: the three new tests FAIL (`swarm` is an unknown subcommand; `swarm_sdk.commands.swarm` missing).

- [ ] **Step 3: Implement**

`src/swarm_sdk/commands/swarm.py`:

```python
"""``low-swarm swarm TEXT``: run one message through the LangGraph handoff swarm."""

from __future__ import annotations

import argparse
import asyncio
import sys
from typing import TYPE_CHECKING, Any

from swarm_sdk.cli import create_panel, create_table
from swarm_sdk.commands import Handler

if TYPE_CHECKING:
    from swarm_sdk.core.swarm import SwarmSDK


def register(subparsers: Any) -> tuple[str, Handler]:
    parser = subparsers.add_parser("swarm", help="Run a message through the handoff swarm")
    parser.add_argument("text", help="Message for the swarm")
    parser.add_argument("--thread-id", default="default", help="Conversation thread id")
    return "swarm", handle_swarm


def _build_sdk() -> SwarmSDK:
    from swarm_sdk.core.swarm import SwarmSDK

    return SwarmSDK.from_settings()


def handle_swarm(args: argparse.Namespace, console: Any) -> int:
    """Run the swarm on ``args.text`` and print the summary table and the answer."""
    try:
        result = asyncio.run(_build_sdk().run(args.text, thread_id=args.thread_id))
    except (RuntimeError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    table = create_table(title="Swarm run")
    table.add_column("Dimension", style="bold")
    table.add_column("Result")
    table.add_row("Thread", args.thread_id)
    table.add_row("Active agent", result.active_agent)
    table.add_row("Mode", result.mode)
    table.add_row("Tokens", str(result.tokens))
    table.add_row("Cached", "yes" if result.cached else "no")
    console.print(create_panel(table, title="Swarm"))
    print(result.text)
    return 0
```

In `commands/__init__.py` change the import and loop: `from swarm_sdk.commands import spawn, swarm` and `for module in (spawn, swarm):`.

- [ ] **Step 4: Run to verify pass**

Task 1 Step 2 command → all pass; ruff check/format on touched files; ty count ≤ 15.

- [ ] **Step 5: Commit (only if the user asked)**

```bash
git add src/swarm_sdk/commands tests/test_cli_commands.py
git commit -m "feat(cli): add swarm command"
```

---

### Task 3: The `parallel` command

**Files:**
- Create: `src/swarm_sdk/commands/parallel.py`
- Modify: `src/swarm_sdk/commands/__init__.py`, `tests/test_cli_commands.py`

**Interfaces:**
- Consumes: Task 1 registry; `Plan` (`Plan.model_validate_json(text)`), `PlanResult(outputs: dict[str, StepOutput], usage: UsageTotals)` with `StepOutput(step_id, agent, content, prompt_tokens=0, completion_tokens=0, cached=False, wall_s=0.0, status="ok")` and `UsageTotals(prompt_tokens, completion_tokens, llm_calls, cached_calls, wall_s)` + `.total_tokens`; `async run_plan(plan, factory, *, max_concurrency=8) -> PlanResult` (raises `ValueError` on file-partition violation); `make_factory(manifests) -> factory`; `swarm_sdk.runtime.parallel_cap() -> int`.
- Produces: `swarm_sdk.commands.parallel.register`, `handle_parallel`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_cli_commands.py`)

```python
from pathlib import Path

from swarm_sdk.orchestrator.plan import PlanResult, StepOutput, UsageTotals


@pytest.fixture
def fake_engine(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    seen: dict[str, object] = {}

    async def run_plan(plan: Plan, factory: object, *, max_concurrency: int = 8) -> PlanResult:
        seen["cap"] = max_concurrency
        seen["steps"] = [s.id for s in plan.steps]
        return PlanResult(
            outputs={
                s.id: StepOutput(step_id=s.id, agent=s.agent, content=f"out-{s.id}", prompt_tokens=3, completion_tokens=2)
                for s in plan.steps
            },
            usage=UsageTotals(prompt_tokens=6, completion_tokens=4, llm_calls=2),
        )

    async def spawn(goal: str, manifests: object) -> Plan:
        seen["goal"] = goal
        return _plan()

    monkeypatch.setattr("swarm_sdk.commands.parallel.run_plan", run_plan)
    monkeypatch.setattr("swarm_sdk.commands.parallel.spawn", spawn)
    monkeypatch.setattr("swarm_sdk.commands.parallel.make_factory", lambda manifests: "factory")
    monkeypatch.setattr(
        "swarm_sdk.commands.parallel.load_all_agent_manifests", lambda agents_dir=None: {"Coder": MagicMock()}
    )
    monkeypatch.setattr("swarm_sdk.commands.parallel.parallel_cap", lambda: 5)
    return seen


class TestParallel:
    def test_goal_spawns_then_runs_with_default_cap(
        self, fake_engine: dict[str, object], capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert cli.main(["parallel", "--goal", "ship it"]) == 0
        out = capsys.readouterr().out
        assert fake_engine["goal"] == "ship it" and fake_engine["cap"] == 5
        assert "S1" in out and "out-S2" in out

    def test_plan_file_and_explicit_cap(
        self, fake_engine: dict[str, object], tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        plan_file = tmp_path / "plan.json"
        plan_file.write_text(_plan().model_dump_json(), encoding="utf-8")
        assert cli.main(["parallel", "--plan", str(plan_file), "--max-concurrency", "3"]) == 0
        assert fake_engine["cap"] == 3 and fake_engine["steps"] == ["S1", "S2"]
        assert "goal" not in fake_engine  # a plan file does not call spawn

    def test_json_output_is_pure_json(
        self, fake_engine: dict[str, object], capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert cli.main(["parallel", "--goal", "g", "--json"]) == 0
        data = json.loads(capsys.readouterr().out)
        assert set(data["outputs"]) == {"S1", "S2"}
        assert data["usage"]["llm_calls"] == 2

    def test_missing_plan_file_is_an_input_error(
        self, fake_engine: dict[str, object], tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert cli.main(["parallel", "--plan", str(tmp_path / "nope.json")]) == 2
        assert "error:" in capsys.readouterr().err

    def test_invalid_plan_json_is_an_input_error(
        self, fake_engine: dict[str, object], tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        bad = tmp_path / "bad.json"
        bad.write_text("{not json", encoding="utf-8")
        assert cli.main(["parallel", "--plan", str(bad)]) == 2
        assert "error:" in capsys.readouterr().err

    @pytest.mark.parametrize("value", ["0", "-2", "abc"])
    def test_non_positive_cap_is_rejected(self, fake_engine: dict[str, object], value: str) -> None:
        assert cli.main(["parallel", "--goal", "g", "--max-concurrency", value]) == 2

    def test_plan_and_goal_are_mutually_exclusive_and_one_is_required(
        self, fake_engine: dict[str, object], tmp_path: Path
    ) -> None:
        assert cli.main(["parallel"]) == 2
        assert cli.main(["parallel", "--goal", "g", "--plan", str(tmp_path / "p.json")]) == 2

    def test_plan_validation_error_from_the_engine_is_reported(
        self, fake_engine: dict[str, object], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        async def boom(plan: Plan, factory: object, *, max_concurrency: int = 8) -> PlanResult:
            raise ValueError("overlapping files in wave 1")

        monkeypatch.setattr("swarm_sdk.commands.parallel.run_plan", boom)
        assert cli.main(["parallel", "--goal", "g"]) == 1
        assert "error: overlapping files in wave 1" in capsys.readouterr().err

    def test_no_manifests_is_an_input_error(
        self, fake_engine: dict[str, object], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setattr("swarm_sdk.commands.parallel.load_all_agent_manifests", lambda agents_dir=None: {})
        assert cli.main(["parallel", "--goal", "g"]) == 2
        assert "error:" in capsys.readouterr().err
```

- [ ] **Step 2: Run to verify failure**

Task 1 Step 2 command. Expected: the nine new tests FAIL (`parallel` unknown / module missing).

- [ ] **Step 3: Implement**

`src/swarm_sdk/commands/parallel.py`:

```python
"""``low-swarm parallel``: run a plan in dependency waves with bounded parallelism."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from swarm_sdk.agents.manifest import load_all_agent_manifests
from swarm_sdk.cli import create_panel, create_table
from swarm_sdk.commands import Handler
from swarm_sdk.orchestrator.graph import run_plan
from swarm_sdk.orchestrator.plan import Plan
from swarm_sdk.orchestrator.spawn import make_factory, spawn
from swarm_sdk.runtime import parallel_cap


def _positive_int(text: str) -> int:
    try:
        value = int(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"not an integer: {text!r}") from exc
    if value < 1:
        raise argparse.ArgumentTypeError("must be >= 1")
    return value


def register(subparsers: Any) -> tuple[str, Handler]:
    parser = subparsers.add_parser(
        "parallel", help="Execute a plan in dependency waves with bounded parallelism"
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--plan", type=Path, help="Plan JSON file (as printed by `spawn --json`)")
    source.add_argument("--goal", help="Goal to decompose with `spawn`, then execute")
    parser.add_argument("--agents-dir", type=Path, default=None, help="Agents directory")
    parser.add_argument(
        "--max-concurrency", type=_positive_int, default=None, help="Max in-flight steps per wave"
    )
    parser.add_argument("--json", action="store_true", help="Print the result as JSON only")
    return "parallel", handle_parallel


def _load_plan(args: argparse.Namespace, manifests: dict[str, Any]) -> Plan:
    if args.plan is not None:
        return Plan.model_validate_json(args.plan.read_text(encoding="utf-8"))
    return asyncio.run(spawn(args.goal, manifests))


def handle_parallel(args: argparse.Namespace, console: Any) -> int:
    """Load or spawn a plan, execute it through ``run_plan``, and print the outputs."""
    try:
        manifests = load_all_agent_manifests(args.agents_dir)
    except (OSError, ValueError) as exc:
        print(f"error: cannot load agent manifests: {exc}", file=sys.stderr)
        return 2
    if not manifests:
        print("error: no agent manifests found (use --agents-dir)", file=sys.stderr)
        return 2

    try:
        plan = _load_plan(args, manifests)
    except (OSError, ValueError, ValidationError) as exc:
        print(f"error: cannot load plan: {exc}", file=sys.stderr)
        return 2

    cap = args.max_concurrency or parallel_cap()
    try:
        result = asyncio.run(run_plan(plan, make_factory(manifests), max_concurrency=cap))
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(result.model_dump_json(indent=2))
        return 0

    table = create_table(title=f"Parallel run (cap {cap})")
    for column in ("Step", "Agent", "Status", "Tokens", "Cached", "Wall (s)"):
        table.add_column(column, style="bold" if column == "Step" else None)
    for output in result.outputs.values():
        table.add_row(
            output.step_id,
            output.agent,
            output.status,
            str(output.prompt_tokens + output.completion_tokens),
            "yes" if output.cached else "no",
            f"{output.wall_s:.2f}",
        )
    usage = result.usage
    console.print(
        create_panel(
            table,
            title=(
                f"{len(result.outputs)} step(s), {usage.total_tokens} tokens, "
                f"{usage.llm_calls} LLM call(s), {usage.wall_s:.2f} s"
            ),
        )
    )
    print(result.answer)
    return 0
```

Add `parallel` to `register_all` (`from swarm_sdk.commands import parallel, spawn, swarm`; `for module in (spawn, swarm, parallel):`). Note `make_factory` is called with only `manifests` here; the tests replace it.

- [ ] **Step 4: Run to verify pass**

Task 1 Step 2 command → all pass; ruff check/format; ty ≤ 15. Also run `uv run python -c "import swarm_sdk.commands.parallel"` (no circular import with `cli`).

- [ ] **Step 5: Commit (only if the user asked)**

```bash
git add src/swarm_sdk/commands tests/test_cli_commands.py
git commit -m "feat(cli): add parallel command"
```

---

### Task 4: `agentic` alias, help listing and docs

**Files:**
- Modify: `src/swarm_sdk/cli.py` (the `run` subparser and the dispatch), `tests/test_cli_commands.py`, `README.md`

**Interfaces:**
- Consumes: Tasks 1–3 (all four groups registered).
- Produces: `low-swarm agentic ...` accepted anywhere `low-swarm run ...` is, dispatched to `handle_run`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_cli_commands.py`)

```python
class TestAgenticAndHelp:
    def test_agentic_is_an_alias_of_run(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen: list[str] = []

        def fake_run(args: object, console: object) -> int:
            seen.append(getattr(args, "command"))
            return 0

        monkeypatch.setattr(cli, "handle_run", fake_run)
        assert cli.main(["run", "task one"]) == 0
        assert cli.main(["agentic", "task two"]) == 0
        assert seen == ["run", "agentic"]

    def test_help_lists_all_command_groups(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert cli.main(["--help"]) in (0, 2)
        out = capsys.readouterr().out
        for name in ("run", "agentic", "spawn", "swarm", "parallel", "vault", "ingest", "doctor"):
            assert name in out
```

- [ ] **Step 2: Run to verify failure**

Task 1 Step 2 command. Expected: `test_agentic_is_an_alias_of_run` FAILS (`agentic` unknown); `test_help_lists_all_command_groups` may fail on `agentic`.

- [ ] **Step 3: Implement**

In `cli.py` `build_parser`, change the `run` subparser creation to `p_run = subparsers.add_parser("run", aliases=["agentic"], help="Run autonomous code synthesis or refactoring task (alias: agentic)")`, leaving every `p_run.add_argument(...)` untouched. In `main`, change `if cmd == "run":` to `if cmd in {"run", "agentic"}:`. Keep the dispatch registry lookup from Task 1 before it. Add to `README.md`, next to the existing `low-swarm` usage (find it with `rg -n "low-swarm" README.md`), this table (create a short "Command groups" subsection if there is none):

```markdown
| Command | What it does |
|---|---|
| `low-swarm agentic TASK` (alias `run`) | Autonomous code synthesis state machine |
| `low-swarm spawn GOAL [--json] [--agents-dir DIR]` | Decompose a goal into a wave-ordered plan |
| `low-swarm swarm TEXT [--thread-id ID]` | Run a message through the handoff swarm |
| `low-swarm parallel (--plan FILE \| --goal TEXT) [--max-concurrency N] [--json]` | Execute a plan in dependency waves with bounded parallelism |
| `low-swarm vault`, `ingest`, `doctor` | Keychain, RAG ingest, host diagnostics (unchanged) |
```

- [ ] **Step 4: Run to verify pass**

Task 1 Step 2 command → all pass; then the full suite command (`--tb=no`) → at most the baseline failures; `uv run ruff check src tests/test_cli_commands.py` clean for touched files; `uv run --extra dev --extra observability ty check src 2>&1 | rg -c "^(error|warning)"` ≤ 15; `uv run python -m compileall -q src`; `uv run python scratch/merge_tools/check_imports.py` → `0 failing module(s)`; `uv run python -m swarm_sdk.cli --help | head -20` lists the four groups.

- [ ] **Step 5: Commit (only if the user asked)**

```bash
git add src/swarm_sdk/cli.py tests/test_cli_commands.py README.md
git commit -m "feat(cli): agentic alias, help listing and docs for command groups"
```
