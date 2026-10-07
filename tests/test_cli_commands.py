"""Tests for the low-swarm command groups: spawn, swarm, parallel and the agentic alias."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from swarm_sdk import cli
from swarm_sdk.commands import markup_safe
from swarm_sdk.core.swarm import RunResult
from swarm_sdk.orchestrator.plan import Plan, PlanResult, PlanStep, StepOutput, UsageTotals


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
        "swarm_sdk.commands.spawn.load_all_agent_manifests",
        lambda agents_dir=None: {"Coder": MagicMock()},
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


class TestSpawnRobustness:
    def test_spawn_failure_is_an_error_exit(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        async def spawn(goal: str, manifests: object) -> Plan:
            raise RuntimeError("provider down")

        monkeypatch.setattr("swarm_sdk.commands.spawn.spawn", spawn)
        monkeypatch.setattr(
            "swarm_sdk.commands.spawn.load_all_agent_manifests",
            lambda agents_dir=None: {"Coder": MagicMock()},
        )
        assert cli.main(["spawn", "goal"]) == 1
        assert "error: provider down" in capsys.readouterr().err

    def test_bracketed_text_survives_rendering(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        async def spawn(goal: str, manifests: object) -> Plan:
            return Plan(
                steps=[
                    PlanStep(
                        id="S1",
                        title="Fix [bug] in [/parser]",
                        description="d",
                        agent="Coder",
                    )
                ]
            )

        monkeypatch.setattr("swarm_sdk.commands.spawn.spawn", spawn)
        monkeypatch.setattr(
            "swarm_sdk.commands.spawn.load_all_agent_manifests",
            lambda agents_dir=None: {"Coder": MagicMock()},
        )
        assert cli.main(["spawn", "goal [x]"]) == 0
        assert "Fix [bug] in [/parser]" in capsys.readouterr().out


def test_markup_safe_escapes_rich_markup() -> None:
    pytest.importorskip("rich")
    from rich.text import Text

    text = "[bold]x[/bold]"
    safe = markup_safe(text)
    assert safe != text
    assert Text.from_markup(safe).plain == text


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
        sdk = _FakeSDK(
            RunResult(text="all done", cached=False, active_agent="coder", tokens=7, mode="swarm")
        )
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

    def test_build_failure_is_reported_not_raised(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        def boom() -> _FakeSDK:
            raise RuntimeError("no settings")

        monkeypatch.setattr("swarm_sdk.commands.swarm._build_sdk", boom)
        assert cli.main(["swarm", "hello"]) == 1
        assert "error: no settings" in capsys.readouterr().err

    def test_markup_in_result_fields_is_not_interpreted(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        sdk = _FakeSDK(
            RunResult(text="[b]ans[/b]", cached=False, active_agent="[x]", tokens=1, mode="swarm")
        )
        monkeypatch.setattr("swarm_sdk.commands.swarm._build_sdk", lambda: sdk)
        assert cli.main(["swarm", "hello"]) == 0
        out = capsys.readouterr().out
        assert "[x]" in out and "[b]ans[/b]" in out


@pytest.fixture
def fake_engine(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    seen: dict[str, object] = {}

    async def run_plan(plan: Plan, factory: object, *, max_concurrency: int = 8) -> PlanResult:
        seen["cap"] = max_concurrency
        seen["steps"] = [s.id for s in plan.steps]
        return PlanResult(
            outputs={
                s.id: StepOutput(
                    step_id=s.id,
                    agent=s.agent,
                    content=f"out-{s.id}",
                    prompt_tokens=3,
                    completion_tokens=2,
                )
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
        "swarm_sdk.commands.parallel.load_all_agent_manifests",
        lambda agents_dir=None: {"Coder": MagicMock()},
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
        self,
        fake_engine: dict[str, object],
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        async def boom(plan: Plan, factory: object, *, max_concurrency: int = 8) -> PlanResult:
            raise ValueError("overlapping files in wave 1")

        monkeypatch.setattr("swarm_sdk.commands.parallel.run_plan", boom)
        assert cli.main(["parallel", "--goal", "g"]) == 1
        assert "error: overlapping files in wave 1" in capsys.readouterr().err

    def test_no_manifests_is_an_input_error(
        self,
        fake_engine: dict[str, object],
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setattr(
            "swarm_sdk.commands.parallel.load_all_agent_manifests", lambda agents_dir=None: {}
        )
        assert cli.main(["parallel", "--goal", "g"]) == 2
        assert "error:" in capsys.readouterr().err

    def test_spawn_runtime_failure_is_reported_not_raised(
        self,
        fake_engine: dict[str, object],
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        async def down(goal: str, manifests: object) -> Plan:
            raise RuntimeError("provider down")

        monkeypatch.setattr("swarm_sdk.commands.parallel.spawn", down)
        assert cli.main(["parallel", "--goal", "g"]) == 1
        assert "error: provider down" in capsys.readouterr().err

    def test_engine_runtime_failure_is_reported_not_raised(
        self,
        fake_engine: dict[str, object],
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        async def crash(plan: Plan, factory: object, *, max_concurrency: int = 8) -> PlanResult:
            raise RuntimeError("worker crashed")

        monkeypatch.setattr("swarm_sdk.commands.parallel.run_plan", crash)
        assert cli.main(["parallel", "--goal", "g"]) == 1
        assert "error: worker crashed" in capsys.readouterr().err

    def test_markup_in_result_fields_is_not_interpreted(
        self,
        fake_engine: dict[str, object],
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        async def odd(plan: Plan, factory: object, *, max_concurrency: int = 8) -> PlanResult:
            return PlanResult(
                outputs={
                    "[/y]": StepOutput(step_id="[/y]", agent="[x]", content="c"),
                },
                usage=UsageTotals(),
            )

        monkeypatch.setattr("swarm_sdk.commands.parallel.run_plan", odd)
        assert cli.main(["parallel", "--goal", "g"]) == 0
        out = capsys.readouterr().out
        assert "[x]" in out and "[/y]" in out


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
