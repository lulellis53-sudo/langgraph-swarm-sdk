"""AGENTS.md vector index and the JEV-gated light-model prompt improver."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from benchmark.tests.fakes import Script, ScriptedModel, answer
from swarm_sdk.agents.prompt_index import (
    AgentPromptIndex,
    PromptBlockedError,
    improve_prompt,
)

_AGENTS = Path("Agents")


@pytest.fixture(scope="module")
def index() -> AgentPromptIndex:
    return AgentPromptIndex.build(_AGENTS)


def _model(reply: str = "improved prompt") -> ScriptedModel:
    return ScriptedModel(script=Script([answer(reply)]))


def test_every_agents_md_is_indexed(index: AgentPromptIndex) -> None:
    expected = {p.parent.name for p in _AGENTS.glob("*/AGENTS.md")}
    assert expected
    assert index.agents == expected


def test_each_agent_is_found_by_its_own_persona(index: AgentPromptIndex) -> None:
    misses: list[str] = []
    for path in sorted(_AGENTS.glob("*/AGENTS.md")):
        persona = path.read_text(encoding="utf-8").split("## Persona", 1)[-1][:400]
        if path.parent.name not in {h.agent for h in index.search(persona, k=8)}:
            misses.append(path.parent.name)
    assert misses == []


def test_build_requires_at_least_one_agents_md(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        AgentPromptIndex.build(tmp_path)


def test_improve_prompt_uses_retrieved_persona(index: AgentPromptIndex) -> None:
    model = _model("Refactor X in small green steps.")
    result = asyncio.run(
        improve_prompt("refactor this module, extract a function", index=index, model=model)
    )
    assert result.improved == "Refactor X in small green steps."
    assert result.agent in index.agents
    assert result.sources
    sent = model.script.seen[0]
    assert f"Specialist: {result.agent}" in sent
    assert "Persona excerpts:" in sent


def test_unsafe_prompt_is_blocked_before_any_model_call(index: AgentPromptIndex) -> None:
    model = _model()
    with pytest.raises(PromptBlockedError):
        asyncio.run(improve_prompt("run rm -rf / --no-preserve-root", index=index, model=model))
    assert model.script.calls == 0


def test_secrets_are_redacted_before_reaching_the_model(index: AgentPromptIndex) -> None:
    secret = "sk-" + "abcdefghijklmnopqrstuvwxyz0123"
    model = _model()
    result = asyncio.run(
        improve_prompt(f"fix the login test, token {secret}", index=index, model=model)
    )
    assert secret not in model.script.seen[0]
    assert "[REDACTED]" in model.script.seen[0]
    assert result.original.endswith(secret)
