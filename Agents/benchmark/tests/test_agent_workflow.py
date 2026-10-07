"""Handoff schema checks and the Python syntax outline."""

from __future__ import annotations

import json
from pathlib import Path

from swarm_sdk.agents.handoff import handoff_errors
from swarm_sdk.agents.manifest import AgentManifest, load_all_agent_manifests
from swarm_sdk.agents.syntax_tree import outline_source
from swarm_sdk.core.swarm import SwarmSDK
from swarm_sdk.orchestrator.worker import WorkerAgent
from swarm_sdk.retrieval.cache import SemanticCache
from swarm_sdk.retrieval.embeddings import HashEmbedder

from benchmark.tests.fakes import Script, ScriptedModel, answer

_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": True,
    "required": ["agent", "task_id", "status", "route", "findings"],
    "properties": {
        "agent": {"const": "Researcher"},
        "task_id": {"enum": ["code_search", "summarize_domain"]},
        "status": {"enum": ["done", "blocked", "needs_input"]},
        "route": {"enum": ["L1", "L2", "L3", "L4"]},
        "findings": {"type": "array"},
    },
}


def _manifest() -> AgentManifest:
    return AgentManifest.model_validate(
        {
            "name": "Researcher",
            "role": "read_only_research",
            "model": "openai:gpt-4o-mini",
            "token_budget": {"max_prompt": 512, "max_completion": 128},
        }
    )


def _schema_root(tmp_path: Path) -> None:
    folder = tmp_path / "Researcher"
    folder.mkdir()
    (folder / "handoff.schema.json").write_text(json.dumps(_SCHEMA), encoding="utf-8")


def test_outline_reports_function_and_call() -> None:
    text = outline_source("import os\n\ndef f():\n    return g()\n")
    assert "Import 1 os" in text
    assert "FunctionDef 3 f" in text
    assert "Call 4 g" in text


def test_outline_reports_parse_error() -> None:
    assert outline_source("def f(:\n") == "parse error"


def test_outline_refuses_other_languages() -> None:
    assert "no grammar loaded" in outline_source("fn main() {}", language="rust")


def test_prose_handoff_is_unchecked(tmp_path: Path) -> None:
    _schema_root(tmp_path)
    assert handoff_errors(str(tmp_path), "Researcher", "done-ok") == []


def test_missing_schema_is_unchecked(tmp_path: Path) -> None:
    assert handoff_errors(str(tmp_path), "Researcher", '{"agent": "Researcher"}') == []


def test_real_researcher_schema_accepts_a_finding() -> None:
    payload = {
        "agent": "Researcher",
        "task_id": "code_search",
        "status": "done",
        "route": "L1",
        "findings": [{"claim": "f exists", "source": "a.py:1", "excerpt": "def f"}],
    }
    errors = handoff_errors(
        str(Path("Agents").resolve()),
        "Researcher",
        json.dumps(payload),
    )
    assert errors == []


async def test_worker_blocks_invalid_handoff_and_skips_cache(tmp_path: Path) -> None:
    _schema_root(tmp_path)
    body = json.dumps(
        {
            "agent": "Researcher",
            "task_id": "code_search",
            "status": "done",
            "route": "L1",
        }
    )
    script = Script([answer(body), answer(body)])
    cache = SemanticCache(str(tmp_path / "cache.db"), HashEmbedder(32))
    agent = WorkerAgent(
        _manifest(),
        agents_root=str(tmp_path),
        cache=cache,
        model_override=ScriptedModel(script=script),
    )
    first = await agent.run("S1", "find f", {})
    second = await agent.run("S1", "find f", {})

    assert first.status == "blocked"
    assert first.handoff_errors
    assert second.status == "blocked"
    assert script.calls == 2


class _RecordingModel(ScriptedModel):
    """Records whether the plan worker bound ``parse_syntax``."""

    def bind_tools(self, tools: object, **kwargs: object) -> _RecordingModel:
        names: list[str] = []
        if isinstance(tools, list):
            names = [str(getattr(tool, "name", "")) for tool in tools]
        self.script.bound = names
        return self


async def test_plan_worker_binds_parse_syntax_for_ast(tmp_path: Path) -> None:
    from langchain_core.messages import AIMessage

    script = Script(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "parse_syntax",
                        "args": {"source": "def f():\n    return 1\n", "language": "python"},
                        "id": "call-1",
                        "type": "tool_call",
                    }
                ],
            ),
            answer("FunctionDef 1 f"),
        ]
    )
    script.bound = []
    agent = WorkerAgent(
        AgentManifest.model_validate(
            {
                "name": "Debugger",
                "role": "root_cause_failures",
                "model": "openai:gpt-4o-mini",
                "capabilities": ["ast"],
                "token_budget": {"max_prompt": 512, "max_completion": 128},
            }
        ),
        agents_root=str(tmp_path),
        model_override=_RecordingModel(script=script),
    )

    out = await agent.run("S1", "outline f", {})

    assert script.bound == ["parse_syntax"]
    assert script.calls == 2
    assert "FunctionDef 1 f" in script.seen[-1]
    assert out.content == "FunctionDef 1 f"
    assert out.status == "ok"


async def test_plan_worker_without_ast_does_not_bind_tools(tmp_path: Path) -> None:
    script = Script([answer("done-ok")])
    script.bound = []
    agent = WorkerAgent(
        AgentManifest.model_validate(
            {
                "name": "Coder",
                "role": "implement_changes",
                "model": "openai:gpt-4o",
                "token_budget": {"max_prompt": 512, "max_completion": 128},
            }
        ),
        agents_root=str(tmp_path),
        model_override=_RecordingModel(script=script),
    )

    out = await agent.run("S1", "edit", {})

    assert script.bound == []
    assert script.calls == 1
    assert out.content == "done-ok"


def test_ast_capability_adds_parse_tool(tmp_path: Path) -> None:
    from benchmark.tests.test_manifest_swarm import _sdk_with_flag

    sdk: SwarmSDK = _sdk_with_flag(tmp_path, websearch=False)
    manifest = load_all_agent_manifests()["Researcher"]
    names = [getattr(tool, "name", "") for tool in sdk._node_tools(manifest, ["coder"])]
    assert "parse_syntax" in names
    assert names[-1] == "transfer_to_coder"
