"""Unit tests for swarm_sdk.orchestrator.spawn and swarm_sdk.orchestrator.graph.

Validates goal decomposition, plan validation, self-correction retries, fallback plans,
and topological wave-barrier LangGraph execution.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage
from pydantic import ValidationError

from swarm_sdk.agents.manifest import AgentManifest, AgentTaskSpec, TokenBudgetSpec
from swarm_sdk.orchestrator.graph import build_graph, run_plan
from swarm_sdk.orchestrator.plan import Plan, PlanStep, StepOutput, UsageTotals
from swarm_sdk.orchestrator.spawn import (
    _fallback_plan,
    _validate_plan,
    jev_advice,
    make_factory,
    spawn,
)


@pytest.fixture
def mock_manifests() -> dict[str, AgentManifest]:
    """Provides standard test agent manifests."""
    return {
        "Orchestrator": AgentManifest(
            name="Orchestrator",
            role="coordinate the swarm and decompose goals",
            model="openai:gpt-4o",
            tasks=[AgentTaskSpec(id="decompose", description="Decompose goals into steps")],
        ),
        "Coder": AgentManifest(
            name="Coder",
            role="implement code changes and refactors",
            model="openai:gpt-4o",
            tasks=[AgentTaskSpec(id="code_task", description="Write code")],
        ),
        "Tester": AgentManifest(
            name="Tester",
            role="verify implementation and run tests",
            model="openai:gpt-4o",
            tasks=[AgentTaskSpec(id="test_task", description="Run pytest")],
        ),
    }


@pytest.fixture(autouse=True)
def _no_hosted_jev(monkeypatch: pytest.MonkeyPatch) -> None:
    """Plan tests must not call TypeSafe when a key is present in the environment."""
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.delenv("JEV_API_KEY", raising=False)


class TestSpawnDecomposition:
    """Test suite for orchestrator goal decomposition and plan validation."""

    @pytest.mark.asyncio
    async def test_spawn_valid_json_plan(self, mock_manifests: dict[str, AgentManifest]) -> None:
        """Orchestrator emits valid JSON plan -> validated and returned as Plan."""
        mock_model = MagicMock()
        mock_response = (
            "Here is the plan:\n"
            "{\n"
            '  "steps": [\n'
            "    {\n"
            '      "id": "S1",\n'
            '      "title": "implement module",\n'
            '      "description": "write src/core.py",\n'
            '      "agent": "Coder",\n'
            '      "task": "code_task",\n'
            '      "files": ["src/core.py"],\n'
            '      "depends_on": [],\n'
            '      "inputs": []\n'
            "    },\n"
            "    {\n"
            '      "id": "S2",\n'
            '      "title": "test module",\n'
            '      "description": "test src/core.py",\n'
            '      "agent": "Tester",\n'
            '      "task": "test_task",\n'
            '      "files": ["tests/test_core.py"],\n'
            '      "depends_on": ["S1"],\n'
            '      "inputs": ["S1"]\n'
            "    }\n"
            "  ]\n"
            "}"
        )

        with patch(
            "swarm_sdk.orchestrator.spawn.complete", new_callable=AsyncMock
        ) as mock_complete:
            mock_complete.return_value = mock_response
            plan = await spawn(
                "Build core module and test it",
                mock_manifests,
                model_override=mock_model,
                structured=False,
            )

            assert len(plan.steps) == 2
            assert plan.steps[0].id == "S1"
            assert plan.steps[0].agent == "Coder"
            assert plan.steps[1].id == "S2"
            assert plan.steps[1].depends_on == ["S1"]
            mock_complete.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_spawn_retry_on_initial_malformed_json(
        self, mock_manifests: dict[str, AgentManifest]
    ) -> None:
        """First reply is invalid JSON -> retry with feedback -> second reply succeeds."""
        mock_model = MagicMock()
        bad_response = "I am decomposing this... wait, no JSON here."
        good_response = (
            "{\n"
            '  "steps": [\n'
            '    {"id": "S1", "title": "step 1", "description": "do work", "agent": "Coder"}\n'
            "  ]\n"
            "}"
        )

        with patch(
            "swarm_sdk.orchestrator.spawn.complete", new_callable=AsyncMock
        ) as mock_complete:
            mock_complete.side_effect = [bad_response, good_response]
            plan = await spawn(
                "Do work", mock_manifests, model_override=mock_model, structured=False
            )

            assert len(plan.steps) == 1
            assert plan.steps[0].id == "S1"
            assert mock_complete.await_count == 2
            # Confirm feedback prompt was included in retry
            retry_prompt = mock_complete.call_args_list[1][0][2]
            assert "Your previous reply was rejected" in retry_prompt

    @pytest.mark.asyncio
    async def test_spawn_fallback_plan_on_double_failure(
        self, mock_manifests: dict[str, AgentManifest]
    ) -> None:
        """Both attempts fail -> fallback single-step plan returned."""
        mock_model = MagicMock()
        bad_response = "Invalid reply"

        with patch(
            "swarm_sdk.orchestrator.spawn.complete", new_callable=AsyncMock
        ) as mock_complete:
            mock_complete.return_value = bad_response
            plan = await spawn("Unrecoverable goal", mock_manifests, model_override=mock_model)

            assert len(plan.steps) == 1
            assert plan.steps[0].id == "S1"
            assert plan.steps[0].title == "handle goal directly"
            assert plan.steps[0].description == "Unrecoverable goal"
            assert plan.steps[0].agent == "Orchestrator"

    def test_jev_advice_abstains_without_a_key(self) -> None:
        """The plan hint does not invent a local Score or Choice."""
        brief = jev_advice("fix a typo in the docstring", ["Coder", "Tester"], environ={})
        assert brief.startswith("JEV abstained")
        assert "flash_lite" not in brief

    @pytest.mark.asyncio
    async def test_spawn_noul_blocks_without_calling_the_model(
        self, mock_manifests: dict[str, AgentManifest]
    ) -> None:
        """A destructive goal becomes a blocked plan and never reaches the model."""
        mock_model = MagicMock()
        with patch(
            "swarm_sdk.orchestrator.spawn.complete", new_callable=AsyncMock
        ) as mock_complete:
            plan = await spawn(
                "rm -rf /",
                mock_manifests,
                model_override=mock_model,
                structured=False,
            )

        assert plan.steps[0].title == "blocked"
        assert plan.steps[0].agent == "Orchestrator"
        assert plan.steps[0].description.startswith("deterministic safety block:")
        assert "unsafe_destructive_command" in plan.steps[0].description
        assert "JEV" not in plan.steps[0].description
        mock_complete.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_spawn_appends_jev_advice(self, mock_manifests: dict[str, AgentManifest]) -> None:
        """A safe goal still calls the model, with the JEV brief in the prompt."""
        mock_model = MagicMock()
        good = (
            '{"steps": [{"id": "S1", "title": "step", "description": "do work", "agent": "Coder"}]}'
        )
        with patch(
            "swarm_sdk.orchestrator.spawn.complete", new_callable=AsyncMock
        ) as mock_complete:
            mock_complete.return_value = good
            plan = await spawn(
                "fix a typo in the docstring",
                mock_manifests,
                model_override=mock_model,
                structured=False,
            )

        assert plan.steps[0].agent == "Coder"
        prompt = mock_complete.call_args_list[0][0][2]
        assert "JEV abstained" in prompt
        assert "flash_lite" not in prompt

    def test_validate_plan_unknown_agent(self, mock_manifests: dict[str, AgentManifest]) -> None:
        """Plan referencing agent not in manifests raises ValueError."""
        plan = Plan(
            steps=[PlanStep(id="S1", title="step", description="desc", agent="UnknownGhost")]
        )
        with pytest.raises(ValueError, match="plan references unknown agents"):
            _validate_plan(plan, mock_manifests)

    def test_validate_plan_forward_dependency(
        self, mock_manifests: dict[str, AgentManifest]
    ) -> None:
        """Step depending on a future/unknown step raises ValueError."""
        plan = Plan(
            steps=[
                PlanStep(
                    id="S1", title="step 1", description="desc", agent="Coder", depends_on=["S2"]
                ),
                PlanStep(id="S2", title="step 2", description="desc", agent="Tester"),
            ]
        )
        with pytest.raises(ValueError, match="depends on unknown or later step"):
            _validate_plan(plan, mock_manifests)

    def test_validate_plan_overlapping_files_in_wave(
        self, mock_manifests: dict[str, AgentManifest]
    ) -> None:
        """Sibling steps claiming identical write paths violate disjoint file invariant."""
        plan = Plan(
            steps=[
                PlanStep(
                    id="S1",
                    title="coder 1",
                    description="desc",
                    agent="Coder",
                    files=["src/common.py"],
                    depends_on=[],
                ),
                PlanStep(
                    id="S2",
                    title="coder 2",
                    description="desc",
                    agent="Coder",
                    files=["src/common.py"],
                    depends_on=[],
                ),
            ]
        )
        with pytest.raises(ValueError, match="both claim"):
            _validate_plan(plan, mock_manifests)


class TestWaveBarrierGraphExecution:
    """Test suite for LangGraph wave-barrier construction and execution."""

    def test_build_graph_structure(self) -> None:
        """Graph contains correct wave nodes and linear transitions."""
        plan = Plan(
            steps=[
                PlanStep(id="S1", title="s1", description="d1", agent="Coder", depends_on=[]),
                PlanStep(id="S2", title="s2", description="d2", agent="Tester", depends_on=["S1"]),
            ]
        )
        mock_factory = MagicMock()
        graph = build_graph(plan, mock_factory)

        assert "wave_0" in graph.nodes
        assert "wave_1" in graph.nodes

    @pytest.mark.asyncio
    async def test_run_plan_execution(self) -> None:
        """run_plan executes waves in sequence, accumulates usage, and returns PlanResult."""
        plan = Plan(
            steps=[
                PlanStep(
                    id="S1",
                    title="write",
                    description="write code",
                    agent="Coder",
                    files=["src/app.py"],
                    depends_on=[],
                ),
                PlanStep(
                    id="S2",
                    title="test",
                    description="verify code",
                    agent="Tester",
                    files=["tests/test_app.py"],
                    depends_on=["S1"],
                    inputs=["S1"],
                ),
            ]
        )

        def mock_factory(step: PlanStep):
            worker = MagicMock()

            async def mock_run(step_id, desc, inputs, files=(), task=""):
                return StepOutput(
                    step_id=step_id,
                    agent=step.agent,
                    content=f"Executed {step_id}",
                    prompt_tokens=100,
                    completion_tokens=50,
                    cached=False,
                    wall_s=0.05,
                    status="ok",
                )

            worker.run = mock_run
            return worker

        result = await run_plan(plan, mock_factory, max_concurrency=4)

        assert len(result.outputs) == 2
        assert result.outputs["S1"].content == "Executed S1"
        assert result.outputs["S2"].content == "Executed S2"
        assert result.usage.llm_calls == 2
        assert result.usage.prompt_tokens == 200
        assert result.usage.completion_tokens == 100
        assert result.usage.wall_s > 0
