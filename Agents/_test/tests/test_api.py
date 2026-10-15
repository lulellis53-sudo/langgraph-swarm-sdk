"""HTTP API tests: runs, plans and error mapping."""

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from swarm_sdk.config.settings import Settings
from swarm_sdk.core.swarm import SwarmSDK
from swarm_sdk.retrieval.embeddings import HashEmbedder
from swarm_sdk.retrieval.rerank import IdentityReranker
from swarm_sdk.serving.http import create_app

from benchmark.tests.fakes import Script, ScriptedModel, answer


def sqlite_extension_loading_available() -> bool:
    conn = sqlite3.connect(":memory:")
    try:
        return hasattr(conn, "enable_load_extension")
    finally:
        conn.close()


pytestmark = pytest.mark.skipif(
    not sqlite_extension_loading_available(),
    reason="CPython build lacks sqlite3 extension loading; sqlite_vec cannot load",
)


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
        memory_backend="opencl",
    )
    sdk = SwarmSDK(
        settings,
        router_model=model,
        specialist_model=model,
        embedder=HashEmbedder(32),
        reranker=IdentityReranker(),
    )
    client = TestClient(create_app(sdk))
    health = client.get("/v1/health").json()
    assert health["status"] == "ok"
    assert isinstance(health.get("providers"), dict)
    response = client.post("/v1/runs", json={"text": "hello api", "thread_id": "http"})
    assert response.status_code == 200
    assert response.json()["text"] == "api-answer"
    assert response.json()["cached"] is False
