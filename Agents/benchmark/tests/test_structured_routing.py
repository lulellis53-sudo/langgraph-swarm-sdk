"""LangChain ``with_structured_output`` routing and planning (with regex fallback)."""

from __future__ import annotations

from pathlib import Path

import pytest

from langchain_core.language_models.chat_models import BaseChatModel

from benchmark.tests.fakes import (
    Script,
    ScriptedModel,
    answer,
    structured,
)
from swarm_sdk.agents.manifest import AgentManifest
from swarm_sdk.config.settings import Settings
from swarm_sdk.core.swarm import SwarmSDK
from swarm_sdk.memory.opencl_store import OpenClVecStore
from swarm_sdk.orchestrator.spawn import spawn
from swarm_sdk.retrieval.embeddings import HashEmbedder
from swarm_sdk.retrieval.rerank import IdentityReranker


@pytest.fixture(autouse=True)
def _no_hosted_jev(monkeypatch: pytest.MonkeyPatch) -> None:
    """Spawn tests must not call TypeSafe when a key is present in the environment."""
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.delenv("JEV_API_KEY", raising=False)


def _router_sdk(
    tmp_path: Path, model: ScriptedModel, *, structured_output: bool = True
) -> SwarmSDK:
    settings = Settings(
        memory_path=str(tmp_path / "mem.db"),
        cache_path=str(tmp_path / "cache.db"),
        embed_dim=32,
        max_tokens=512,
        memory_backend="opencl",
        router_structured_output=structured_output,
    )
    return SwarmSDK(
        settings,
        router_model=model,
        specialist_model=model,
        embedder=HashEmbedder(32),
        reranker=IdentityReranker(),
        memory=OpenClVecStore(32),
    )


async def test_route_uses_structured_tool_call(tmp_path: Path) -> None:
    script = Script([structured("RouteDecision", {"mode": "parallel", "tasks": ["a"]}, total=7)])
    sdk = _router_sdk(tmp_path, ScriptedModel(script=script))

    decision, tokens = await sdk._route(sdk.budget.pack(system="s", memories=[], turns=["q"]))

    assert (decision.mode, decision.tasks) == ("parallel", ["a"])
    assert tokens == 7
    assert script.calls == 1


async def test_route_falls_back_to_regex_on_plain_reply(tmp_path: Path) -> None:
    raw = '{"mode":"parallel","tasks":["b"]}'
    script = Script([answer(raw)])
    sdk = _router_sdk(tmp_path, ScriptedModel(script=script))

    decision, _ = await sdk._route(sdk.budget.pack(system="s", memories=[], turns=["q"]))

    assert (decision.mode, decision.tasks) == ("parallel", ["b"])
    assert script.calls == 2  # structured attempt, then the legacy JSON-mode call


async def test_route_off_flag_skips_structured_path(tmp_path: Path) -> None:
    script = Script([answer('{"mode":"swarm","tasks":[]}')])
    sdk = _router_sdk(tmp_path, ScriptedModel(script=script), structured_output=False)

    decision, _ = await sdk._route(sdk.budget.pack(system="s", memories=[], turns=["q"]))

    assert decision.mode == "swarm"
    assert script.calls == 1


class _NoBindTools(ScriptedModel):
    """Scripted model without a ``bind_tools`` override."""

    bind_tools = BaseChatModel.bind_tools  # type: ignore[method-assign]


async def test_route_unsupported_model_uses_json_mode(tmp_path: Path) -> None:
    script = Script([answer('{"mode":"swarm","tasks":[]}')])
    sdk = _router_sdk(tmp_path, _NoBindTools(script=script))

    decision, _ = await sdk._route(sdk.budget.pack(system="s", memories=[], turns=["q"]))

    assert decision.mode == "swarm"
    assert script.calls == 1


def _manifests() -> dict[str, AgentManifest]:
    manifest = AgentManifest(name="Coder", role="implement_changes", model="openai:gpt-4o")
    return {"Coder": manifest}


async def test_spawn_uses_structured_tool_call() -> None:
    plan_args = {
        "steps": [
            {
                "id": "S1",
                "title": "do it",
                "description": "implement",
                "agent": "Coder",
                "task": "",
                "files": [],
                "depends_on": [],
                "inputs": [],
            }
        ]
    }
    model = ScriptedModel(script=Script([structured("Plan", plan_args)]))

    plan = await spawn("goal", _manifests(), model_override=model)

    assert plan.steps[0].agent == "Coder"
    assert model.script.calls == 1


async def test_spawn_falls_back_after_invalid_plan() -> None:
    bad = {
        "steps": [
            {
                "id": "S1",
                "title": "x",
                "description": "d",
                "agent": "Ghost",
                "task": "",
                "files": [],
                "depends_on": [],
                "inputs": [],
            }
        ]
    }
    good = {
        "steps": [
            {
                "id": "S1",
                "title": "y",
                "description": "d",
                "agent": "Coder",
                "task": "",
                "files": [],
                "depends_on": [],
                "inputs": [],
            }
        ]
    }
    model = ScriptedModel(script=Script([structured("Plan", bad), structured("Plan", good)]))

    plan = await spawn("goal", _manifests(), model_override=model)

    assert plan.steps[0].agent == "Coder"
    assert model.script.calls == 2
