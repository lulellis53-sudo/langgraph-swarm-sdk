"""SwarmSDK integration: handoffs, parallel fan-out, and semantic/exact cache."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import numpy as np
from langchain_core.messages import AIMessage, HumanMessage
from tests.fakes import Script, ScriptedModel, answer, handoff

from swarm_sdk.config.settings import Settings
from swarm_sdk.core.swarm import SwarmSDK
from swarm_sdk.memory.opencl_store import OpenClVecStore
from swarm_sdk.models.chat import complete_with_usage, message_tokens, usage_tokens
from swarm_sdk.models.selection import FallbackChain, ModelRoute, ModelSelectConfig
from swarm_sdk.retrieval.cache import SemanticCache
from swarm_sdk.retrieval.embeddings import HashEmbedder, unit
from swarm_sdk.retrieval.rerank import IdentityReranker


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

    def embed(self, texts: list[str], *, query: bool = False) -> np.ndarray:
        self.calls += 1
        return self.inner.embed(texts, query=query)


def _settings(tmp_path: Path, *, max_tokens: int = 512) -> Settings:
    return Settings(
        memory_path=str(tmp_path / "mem.db"),
        cache_path=str(tmp_path / "cache.db"),
        embed_dim=32,
        max_tokens=max_tokens,
        memory_backend="opencl",
    )


def _sdk(
    tmp_path: Path,
    *,
    router: ScriptedModel,
    specialist: ScriptedModel,
    embedder: HashEmbedder | SpyEmbedder | None = None,
    cache: SemanticCache | None = None,
    memory: OpenClVecStore | None = None,
) -> SwarmSDK:
    embed = embedder or HashEmbedder(32)
    return SwarmSDK(
        _settings(tmp_path),
        router_model=router,
        specialist_model=specialist,
        embedder=embed,
        reranker=IdentityReranker(),
        cache=cache,
        memory=memory or OpenClVecStore(32),
    )


async def test_handoff_keeps_active_agent(tmp_path: Path) -> None:
    router = ScriptedModel(script=Script([answer('{"mode":"swarm","tasks":[]}')]))
    specialist = ScriptedModel(
        script=Script([handoff("coder"), answer("patched"), answer("still on coder")])
    )
    sdk = _sdk(
        tmp_path,
        router=router,
        specialist=specialist,
        memory=OpenClVecStore(32),
    )
    first = await sdk.run("please code this", "thread")
    assert first.active_agent == "coder"
    assert first.text == "patched"
    second = await sdk.run("continue the patch", "thread")
    assert second.active_agent == "coder"
    assert second.text == "still on coder"
    assert second.cached is False


async def test_parallel_fanout_hides_full_history(tmp_path: Path) -> None:
    sentinel = "SENTINEL_HISTORY_SHOULD_NOT_LEAK"
    router = ScriptedModel(
        script=Script([answer('{"mode":"parallel","tasks":["alpha task","beta task"]}')])
    )
    specialist_script = Script([answer("done")])
    specialist = ScriptedModel(script=specialist_script)
    sdk = _sdk(tmp_path, router=router, specialist=specialist)
    result = await sdk.run(sentinel, "thread")
    assert result.mode == "parallel"
    assert result.active_agent == "synthesizer"
    assert result.text == "done"
    assert specialist_script.calls == 3
    assert all(sentinel not in prompt for prompt in specialist_script.seen)
    assert any(sentinel in prompt for prompt in router.script.seen)


async def test_exact_cache_hit_does_not_call_the_model(tmp_path: Path) -> None:
    embedder = SpyEmbedder(HashEmbedder(dim=32))
    model = ScriptedModel(
        script=Script([AIMessage(content='{"mode":"swarm","tasks":[]}'), answer("from-model")])
    )
    settings = _settings(tmp_path, max_tokens=256)
    sdk = SwarmSDK(
        settings,
        router_model=model,
        specialist_model=model,
        embedder=embedder,
        reranker=IdentityReranker(),
        cache=SemanticCache(settings.cache_path, embedder, threshold=0.97),
    )
    first = await sdk.run("Hello", "thread-1")
    calls, embeds = model.script.calls, embedder.calls
    second = await sdk.run("hello", "thread-1")
    assert first.text == "from-model"
    assert first.cached is False
    assert second.cached is True
    assert second.text == "from-model"
    assert model.script.calls == calls
    assert embedder.calls == embeds


async def test_semantic_cache_hit_does_not_call_the_model(tmp_path: Path) -> None:
    embedder = SpyEmbedder(SemanticBucketEmbedder())
    model = ScriptedModel(
        script=Script(
            [AIMessage(content='{"mode":"swarm","tasks":[]}'), answer("semantic-answer")]
        )
    )
    settings = _settings(tmp_path, max_tokens=256)
    sdk = SwarmSDK(
        settings,
        router_model=model,
        specialist_model=model,
        embedder=embedder,
        reranker=IdentityReranker(),
        cache=SemanticCache(settings.cache_path, embedder, threshold=0.97),
    )
    await sdk.run("topic: one", "thread-a")
    calls = model.script.calls
    second = await sdk.run("topic: two", "thread-b")
    assert second.cached is True
    assert second.text == "semantic-answer"
    assert model.script.calls == calls


def test_semantic_cache_uses_wal(tmp_path: Path) -> None:
    cache = SemanticCache(str(tmp_path / "c.db"), HashEmbedder(16))
    assert cache._conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"


def test_semantic_cache_ttl_evicts_old_rows(tmp_path: Path) -> None:
    path = str(tmp_path / "c.db")
    embedder = HashEmbedder(16)
    cache = SemanticCache(path, embedder)
    cache.store("old question", "old answer")
    old = time.time() - 10 * 86400
    cache._conn.execute("UPDATE exact_cache SET inserted_at = ?", (old,))
    cache._conn.execute("UPDATE semantic_cache SET inserted_at = ?", (old,))
    cache._conn.commit()
    cache._conn.close()

    fresh = SemanticCache(path, embedder, ttl_days=1)
    assert fresh.lookup("old question") is None


def test_semantic_cache_ttl_none_keeps_rows(tmp_path: Path) -> None:
    path = str(tmp_path / "c.db")
    embedder = HashEmbedder(16)
    SemanticCache(path, embedder).store("q", "a")
    assert SemanticCache(path, embedder).lookup("q") == "a"


def test_semantic_cache_migrates_legacy_schema(tmp_path: Path) -> None:
    path = str(tmp_path / "legacy.db")
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE exact_cache (key TEXT PRIMARY KEY, response TEXT NOT NULL)")
    conn.execute(
        "CREATE TABLE semantic_cache (id INTEGER PRIMARY KEY, vector BLOB NOT NULL, "
        "response TEXT NOT NULL)"
    )
    conn.commit()
    conn.close()
    cache = SemanticCache(path, HashEmbedder(16), ttl_days=7)
    cache.store("q", "a")
    assert cache.lookup("q") == "a"


def test_indexed_lookup_matches_scan(tmp_path: Path) -> None:
    embedder = SemanticBucketEmbedder()
    path = str(tmp_path / "c.db")
    seed = SemanticCache(path, embedder, threshold=0.97)
    seed.store("topic alpha", "answer-a")
    seed.store("unrelated words here", "answer-b")

    scan = SemanticCache(path, embedder, threshold=0.97, use_index=False)
    indexed = SemanticCache(path, embedder, threshold=0.97, use_index=True)
    for query in ("topic beta", "unrelated words here", "totally new thing"):
        assert indexed.lookup(query) == scan.lookup(query)


def test_indexed_cache_sees_rows_stored_after_init(tmp_path: Path) -> None:
    embedder = SemanticBucketEmbedder()
    cache = SemanticCache(str(tmp_path / "c.db"), embedder, use_index=True)
    assert cache._index is not None
    assert cache.lookup("topic one") is None
    cache.store("topic one", "hit")
    assert cache.lookup("topic two") == "hit"


def test_indexed_cache_skips_wrong_dim_blobs(tmp_path: Path) -> None:
    path = str(tmp_path / "c.db")
    SemanticCache(path, HashEmbedder(16)).store("q", "a")
    other = SemanticCache(path, HashEmbedder(32), use_index=True)
    assert other.lookup("something else entirely") is None


def test_indexed_cache_empty_db(tmp_path: Path) -> None:
    cache = SemanticCache(str(tmp_path / "c.db"), HashEmbedder(16), use_index=True)
    assert cache.lookup("x") is None


def _ai(text: str, total: int | None) -> AIMessage:
    meta = (
        None
        if total is None
        else {"input_tokens": 1, "output_tokens": total - 1, "total_tokens": total}
    )
    return AIMessage(content=text, usage_metadata=meta)


def test_message_tokens_reads_total_and_falls_back_to_sum() -> None:
    assert message_tokens(_ai("x", 9)) == 9
    partial = {
        "role": "assistant",
        "content": "x",
        "usage_metadata": {"input_tokens": 3, "output_tokens": 4},
    }
    assert message_tokens(partial) == 7
    assert message_tokens(_ai("x", None)) is None
    assert message_tokens({"role": "assistant", "content": "x"}) is None


def test_usage_tokens_counts_only_current_turn() -> None:
    history = [
        HumanMessage(content="old"),
        _ai("old-a", 100),
        HumanMessage(content="new"),
        _ai("new-a", 7),
    ]
    assert usage_tokens(history) == 7
    assert usage_tokens([HumanMessage(content="q"), _ai("a", None)]) is None


async def test_complete_with_usage_prefers_provider_count() -> None:
    model = ScriptedModel(script=Script([_ai("hello", 42)]))
    assert await complete_with_usage(model, "sys", "user") == ("hello", 42)


async def test_complete_with_usage_estimates_when_provider_silent() -> None:
    model = ScriptedModel(script=Script([answer("hello there")]))
    text, tokens = await complete_with_usage(model, "sys", "user")
    assert text == "hello there"
    assert tokens > 0


class _RejectsResponseFormat(ScriptedModel):
    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        if "response_format" in kwargs:
            raise ValueError("response_format unsupported")
        return super()._generate(messages, stop, run_manager, **kwargs)


async def test_json_mode_falls_back_when_provider_rejects() -> None:
    model = _RejectsResponseFormat(script=Script([_ai("plain", 5)]))
    assert await complete_with_usage(model, "s", "u", json_mode=True) == ("plain", 5)


async def test_fallback_chain_reports_usage_and_complete_stays_str(monkeypatch) -> None:
    model = ScriptedModel(script=Script([_ai("hi", 7)]))
    monkeypatch.setattr("swarm_sdk.models.selection.load_chat_model", lambda name: model)
    chain = FallbackChain(ModelSelectConfig(routes=[ModelRoute(name="x:y", provider="x")]))
    assert await chain.complete_with_usage("s", "u") == ("hi", 7)
    assert await chain.complete("s", "u") == "hi"


async def test_run_tokens_are_provider_reported_swarm(tmp_path: Path) -> None:
    router = ScriptedModel(script=Script([_ai('{"mode":"swarm","tasks":[]}', 10)]))
    specialist = ScriptedModel(script=Script([_ai("ok", 32)]))
    sdk = _sdk(tmp_path, router=router, specialist=specialist)
    result = await sdk.run("please answer", "thread")
    assert result.tokens == 10 + 32


async def test_run_tokens_are_provider_reported_parallel(tmp_path: Path) -> None:
    router = ScriptedModel(
        script=Script([_ai('{"mode":"parallel","tasks":["a task","b task"]}', 10)])
    )
    specialist = ScriptedModel(script=Script([_ai("done", 5)]))
    sdk = _sdk(tmp_path, router=router, specialist=specialist)
    result = await sdk.run("please answer", "thread")
    assert result.mode == "parallel"
    assert result.tokens == 10 + 3 * 5
