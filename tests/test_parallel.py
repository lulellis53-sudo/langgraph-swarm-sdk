
from pathlib import Path

import pytest
from tests.conftest import sqlite_extension_loading_available
from tests.fakes import Script, ScriptedModel, answer

from swarm_sdk.config import Settings
from swarm_sdk.embeddings import HashEmbedder
from swarm_sdk.rerank import IdentityReranker
from swarm_sdk.swarm import SwarmSDK

pytestmark = pytest.mark.skipif(
    not sqlite_extension_loading_available(),
    reason="CPython build lacks sqlite3 extension loading; sqlite_vec cannot load",
)


async def test_parallel_fanout_hides_full_history(tmp_path: Path) -> None:
    sentinel = "SENTINEL_HISTORY_SHOULD_NOT_LEAK"
    router = ScriptedModel(
        script=Script([answer('{"mode":"parallel","tasks":["alpha task","beta task"]}')])
    )
    specialist_script = Script([answer("done")])
    specialist = ScriptedModel(script=specialist_script)
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
    )
    result = await sdk.run(sentinel, "thread")
    assert result.mode == "parallel"
    assert result.active_agent == "synthesizer"
    assert result.text == "done"
    assert specialist_script.calls == 3
    assert all(sentinel not in prompt for prompt in specialist_script.seen)
    assert any(sentinel in prompt for prompt in router.script.seen)
