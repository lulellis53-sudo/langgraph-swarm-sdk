from pathlib import Path

from tests.fakes import Script, ScriptedModel, answer, handoff

from swarm_sdk.config import Settings
from swarm_sdk.embeddings import HashEmbedder
from swarm_sdk.memory.sqlite_vec import SqliteVecStore
from swarm_sdk.rerank import IdentityReranker
from swarm_sdk.swarm import SwarmSDK


async def test_handoff_keeps_active_agent(tmp_path: Path) -> None:
    router = ScriptedModel(script=Script([answer('{"mode":"swarm","tasks":[]}')]))
    specialist = ScriptedModel(
        script=Script(
            [
                handoff("coder"),
                answer("patched"),
                answer("still on coder"),
            ]
        )
    )
    settings = Settings(
        memory_path=str(tmp_path / "mem.db"),
        cache_path=str(tmp_path / "cache.db"),
        embed_dim=32,
        max_tokens=512,
    )
    sdk = SwarmSDK(
        settings,
        router_model=router,
        specialist_model=specialist,
        embedder=HashEmbedder(32),
        reranker=IdentityReranker(),
        memory=SqliteVecStore(settings.memory_path, 32),
    )
    first = await sdk.run("please code this", "thread")
    assert first.active_agent == "coder"
    assert first.text == "patched"
    second = await sdk.run("continue the patch", "thread")
    assert second.active_agent == "coder"
    assert second.text == "still on coder"
    assert second.cached is False
