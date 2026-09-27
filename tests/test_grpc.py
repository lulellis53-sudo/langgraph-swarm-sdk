from pathlib import Path

from langchain_core.messages import AIMessage
from tests.fakes import Script, ScriptedModel, answer

from swarm_sdk.config import Settings
from swarm_sdk.embeddings import HashEmbedder
from swarm_sdk.pb import swarm_pb2
from swarm_sdk.rerank import IdentityReranker
from swarm_sdk.swarm import SwarmSDK


def test_grpc_run_and_recall(tmp_path: Path) -> None:
    from swarm_sdk.grpc_server import SwarmServicer

    model = ScriptedModel(
        script=Script(
            [
                AIMessage(content='{"mode":"swarm","tasks":[]}'),
                answer("grpc-answer"),
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
    servicer = SwarmServicer(sdk)
    response = servicer.Run(swarm_pb2.RunRequest(text="hello grpc", thread_id="g"), None)
    assert response.text == "grpc-answer"
    assert response.cached is False
    recalled = servicer.Recall(swarm_pb2.RecallRequest(query="hello grpc", top_k=2), None)
    assert recalled.hits
    assert "grpc-answer" in recalled.hits[0].text
