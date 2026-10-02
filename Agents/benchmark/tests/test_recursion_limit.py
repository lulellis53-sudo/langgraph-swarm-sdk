from pathlib import Path

from fastapi.testclient import TestClient
from langgraph.errors import GraphRecursionError

from benchmark.tests.fakes import Script, ScriptedModel, answer
from swarm_sdk.config.settings import Settings
from swarm_sdk.core.swarm import SwarmSDK
from swarm_sdk.retrieval.embeddings import HashEmbedder
from swarm_sdk.retrieval.rerank import IdentityReranker
from swarm_sdk.serving.http import create_app


class _LoopingSDK:
    async def run(self, text: str, thread_id: str = "default"):
        raise GraphRecursionError("Recursion limit of 50 reached")


def test_run_config_carries_recursion_limit(tmp_path: Path) -> None:
    model = ScriptedModel(script=Script([answer("ok")]))
    sdk = SwarmSDK(
        Settings(
            memory_path=str(tmp_path / "m.db"),
            cache_path=str(tmp_path / "c.db"),
            embed_dim=32,
            memory_backend="opencl",
            recursion_limit=7,
        ),
        router_model=model,
        specialist_model=model,
        embedder=HashEmbedder(32),
        reranker=IdentityReranker(),
    )
    assert sdk._run_config("t") == {"configurable": {"thread_id": "t"}, "recursion_limit": 7}


def test_loop_maps_to_508() -> None:
    client = TestClient(create_app(_LoopingSDK()))
    response = client.post("/v1/runs", json={"text": "hi", "thread_id": "t"})
    assert response.status_code == 508
    assert response.json() == {"detail": "handoff loop: recursion limit reached"}
