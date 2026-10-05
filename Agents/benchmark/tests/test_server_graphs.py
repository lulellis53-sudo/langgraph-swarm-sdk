"""LangGraph Server deployment: graph factories, langgraph.json, SDK client."""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any

import pytest

from benchmark.tests.fakes import Script, ScriptedModel, answer, structured
from swarm_sdk.config.settings import Settings
from swarm_sdk.core.swarm import SwarmSDK
from swarm_sdk.memory.opencl_store import OpenClVecStore
from swarm_sdk.retrieval.embeddings import HashEmbedder
from swarm_sdk.retrieval.rerank import IdentityReranker
from swarm_sdk.server.graphs import plan_graph, swarm_graph


def _sdk(tmp_path: Path, model: ScriptedModel) -> SwarmSDK:
    settings = Settings(
        memory_path=str(tmp_path / "mem.db"),
        cache_path=str(tmp_path / "cache.db"),
        embed_dim=32,
        max_tokens=512,
        memory_backend="opencl",
    )
    return SwarmSDK(
        settings,
        router_model=model,
        specialist_model=model,
        embedder=HashEmbedder(32),
        reranker=IdentityReranker(),
        memory=OpenClVecStore(32),
    )


def test_swarm_graph_factory_builds_manifest_swarm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sdk = _sdk(tmp_path, ScriptedModel(script=Script([answer("ok")])))
    monkeypatch.setattr(SwarmSDK, "from_settings", classmethod(lambda cls: sdk))

    graph = swarm_graph()

    assert {"researcher", "coder", "reviewer"} <= set(graph.nodes)


def test_swarm_graph_for_server_carries_no_own_checkpointer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sdk = _sdk(tmp_path, ScriptedModel(script=Script([answer("ok")])))
    monkeypatch.setattr(SwarmSDK, "from_settings", classmethod(lambda cls: sdk))

    served: Any = swarm_graph()
    local: Any = sdk.compiled_graph()
    assert served.checkpointer is None
    assert local.checkpointer is not None


def test_langgraph_json_maps_importable_factories() -> None:
    config = json.loads(Path("langgraph.json").read_text(encoding="utf-8"))

    assert config["dependencies"] == ["."]
    for graph_id, target in config["graphs"].items():
        module_path, _, attr = target.partition(":")
        module_name = module_path.removeprefix("./").removesuffix(".py").replace("/", ".")
        factory = getattr(importlib.import_module(module_name), attr)
        assert callable(factory), graph_id
    assert set(config["graphs"]) == {"swarm", "plan"}


_PLAN_ARGS: dict[str, Any] = {
    "steps": [
        {
            "id": "S1",
            "title": "a",
            "description": "research it",
            "agent": "Coder",
            "task": "",
            "files": [],
            "depends_on": [],
            "inputs": [],
        },
        {
            "id": "S2",
            "title": "b",
            "description": "test it",
            "agent": "Tester",
            "task": "",
            "files": [],
            "depends_on": [],
            "inputs": [],
        },
    ]
}


async def test_plan_graph_runs_plan_end_to_end(monkeypatch) -> None:
    # Agents require the key env var to be set; the scripted model never uses it.
    monkeypatch.setenv("OPENAI_API_KEY", "test-sentinel")
    model = ScriptedModel(
        script=Script(
            [
                structured("Plan", _PLAN_ARGS),
                answer("ok-1"),
                answer("ok-2"),
            ]
        )
    )
    graph = plan_graph(model_override=model)

    final = await graph.ainvoke({"goal": "build it"}, {"recursion_limit": 10})

    assert final["plan"].steps[0].agent == "Coder"
    result = final["result"]
    assert sorted(result["outputs"]) == ["S1", "S2"]
    assert result["usage"]["llm_calls"] == 2


def test_client_payload_extraction(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    import langgraph_sdk
    from langchain_core.messages import AIMessage

    import swarm_sdk.serving.client as client_module

    class _FakeRuns:
        """Fake LangGraph runs API returning a canned final state."""

        async def wait(self, thread_id: str, assistant_id: str, **kwargs: Any) -> dict[str, Any]:
            del thread_id, assistant_id, kwargs
            return {
                "messages": [
                    {"role": "user", "content": "hi"},
                    AIMessage(
                        content="patched",
                        usage_metadata={"input_tokens": 3, "output_tokens": 9, "total_tokens": 12},
                    ),
                ],
                "active_agent": "coder",
            }

    class _FakeClient:
        """Fake LangGraph client exposing the fake runs API."""

        runs = _FakeRuns()

    monkeypatch.setattr(langgraph_sdk, "get_client", lambda **kwargs: _FakeClient())

    payload = asyncio.run(
        client_module.run_on_server("hi", "t", server_url="http://127.0.0.1:2024")
    )

    assert payload["text"] == "patched"
    assert payload["active_agent"] == "coder"
    assert payload["tokens"] == 12
    assert payload["mode"] == "server"


async def test_swarm_run_delegates_to_server(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings(
        memory_path=str(tmp_path / "mem.db"),
        cache_path=str(tmp_path / "cache.db"),
        embed_dim=32,
        memory_backend="opencl",
        server_url="http://127.0.0.1:2024",
    )
    model = ScriptedModel(script=Script([answer("ok")]))
    sdk = SwarmSDK(
        settings,
        router_model=model,
        specialist_model=model,
        embedder=HashEmbedder(32),
        reranker=IdentityReranker(),
        memory=OpenClVecStore(32),
    )
    captured: dict[str, str] = {}

    async def fake_run_on_server(
        text: str, thread_id: str = "default", *, server_url: str, graph_id: str = "swarm"
    ) -> dict[str, Any]:
        del graph_id
        captured.update({"text": text, "thread_id": thread_id, "server_url": server_url})
        return {
            "text": "remote",
            "cached": False,
            "active_agent": "coder",
            "tokens": 5,
            "mode": "server",
        }

    monkeypatch.setattr("swarm_sdk.serving.client.run_on_server", fake_run_on_server)

    result = await sdk.run("hello", "thread-7")

    assert result.mode == "server"
    assert result.text == "remote"
    assert result.active_agent == "coder"
    assert result.tokens == 5
    assert captured["server_url"] == "http://127.0.0.1:2024"
