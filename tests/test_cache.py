from pathlib import Path

import numpy as np
from langchain_core.messages import AIMessage
from tests.fakes import Script, ScriptedModel, answer

from swarm_sdk.cache import SemanticCache
from swarm_sdk.config import Settings
from swarm_sdk.embeddings import HashEmbedder, unit
from swarm_sdk.rerank import IdentityReranker
from swarm_sdk.swarm import SwarmSDK


class SemanticBucketEmbedder:
    """Maps related prompts to the same unit vector for semantic-cache tests."""

    dim = 32

    def embed(self, texts: list[str], *, query: bool = False) -> np.ndarray:
        del query
        shared = unit(np.ones(self.dim, dtype=np.float32))
        rows = []
        for text in texts:
            if text.strip().lower().startswith("topic"):
                rows.append(shared)
            else:
                rows.append(HashEmbedder(self.dim).embed([text])[0])
        return np.stack(rows)


class SpyEmbedder:
    def __init__(self, inner: HashEmbedder | SemanticBucketEmbedder) -> None:
        self.inner = inner
        self.calls = 0
        self.dim = inner.dim

    def embed(self, texts: list[str], *, query: bool = False):
        self.calls += 1
        return self.inner.embed(texts, query=query)


def _sdk(tmp_path: Path, script: Script, embedder: SpyEmbedder) -> tuple[SwarmSDK, ScriptedModel]:
    model = ScriptedModel(script=script)
    settings = Settings(
        memory_path=str(tmp_path / "mem.db"),
        cache_path=str(tmp_path / "cache.db"),
        embed_dim=32,
        max_tokens=256,
    )
    sdk = SwarmSDK(
        settings,
        router_model=model,
        specialist_model=model,
        embedder=embedder,
        reranker=IdentityReranker(),
        cache=SemanticCache(settings.cache_path, embedder, threshold=0.97),
    )
    return sdk, model


async def test_exact_cache_hit_does_not_call_the_model(tmp_path: Path) -> None:
    embedder = SpyEmbedder(HashEmbedder(dim=32))
    script = Script(
        [
            AIMessage(content='{"mode":"swarm","tasks":[]}'),
            answer("from-model"),
        ]
    )
    sdk, model = _sdk(tmp_path, script, embedder)
    first = await sdk.run("Hello", "thread-1")
    calls = model.script.calls
    embeds = embedder.calls
    second = await sdk.run("hello", "thread-1")
    assert first.text == "from-model"
    assert first.cached is False
    assert second.cached is True
    assert second.text == "from-model"
    assert model.script.calls == calls
    assert embedder.calls == embeds


async def test_semantic_cache_hit_does_not_call_the_model(tmp_path: Path) -> None:
    embedder = SpyEmbedder(SemanticBucketEmbedder())
    script = Script(
        [
            AIMessage(content='{"mode":"swarm","tasks":[]}'),
            answer("semantic-answer"),
        ]
    )
    sdk, model = _sdk(tmp_path, script, embedder)
    await sdk.run("topic: one", "thread-a")
    calls = model.script.calls
    second = await sdk.run("topic: two", "thread-b")
    assert second.cached is True
    assert second.text == "semantic-answer"
    assert model.script.calls == calls
