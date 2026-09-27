from pathlib import Path

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from tests.fakes import Script, ScriptedModel, answer

from swarm_sdk.api import create_app
from swarm_sdk.config import Settings
from swarm_sdk.embeddings import HashEmbedder
from swarm_sdk.rerank import IdentityReranker
from swarm_sdk.swarm import SwarmSDK


def test_health_and_run(tmp_path: Path) -> None:
    model = ScriptedModel(
        script=Script(
            [
                AIMessage(content='{"mode":"swarm","tasks":[]}'),
                answer("api-answer"),
            ]
        )
    )
    settings = Settings(
        memory_path=str(tmp_path / "mem.db"),
        cache_path=str(tmp_path / "cache.db"),
        embed_dim=32,
    )
    sdk = SwarmSDK(
        settings,
        router_model=model,
        specialist_model=model,
        embedder=HashEmbedder(32),
        reranker=IdentityReranker(),
    )
    client = TestClient(create_app(sdk))
    assert client.get("/v1/health").json() == {"status": "ok"}
    response = client.post("/v1/runs", json={"text": "hello api", "thread_id": "http"})
    assert response.status_code == 200
    assert response.json()["text"] == "api-answer"
    assert response.json()["cached"] is False
