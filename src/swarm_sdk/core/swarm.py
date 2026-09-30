"""LangGraph handoff swarm plus a token-saving front door."""

from __future__ import annotations

import importlib
import json
import re
from typing import Literal, Protocol, cast

from langchain.agents import create_agent
from langchain_core.language_models.chat_models import BaseChatModel
from langgraph.checkpoint.memory import InMemorySaver
from langgraph_swarm import create_handoff_tool, create_swarm
from pydantic import BaseModel, Field, ValidationError

from swarm_sdk.agents.manifest import langgraph_manifests, load_all_agent_manifests
from swarm_sdk.config.loader import SwarmFileConfig, load_swarm_config
from swarm_sdk.config.settings import Settings, load_merged_settings
from swarm_sdk.execution.executor import offload
from swarm_sdk.execution.fanout import fan_out
from swarm_sdk.gpu import set_enabled as set_opencl_enabled
from swarm_sdk.memory.base import MemoryHit, MemoryStore
from swarm_sdk.memory.sqlite_vec import SqliteVecStore
from swarm_sdk.models.chat import complete_with_usage, last_ai_text, load_chat_model, usage_tokens
from swarm_sdk.models.selection import (
    THINK_TOKEN_BUDGET,
    FallbackChain,
    ModelSelector,
    ThinkLevel,
)
from swarm_sdk.observability.usage import UsageLog
from swarm_sdk.prompting.budget import PackedPrompt, TokenBudget
from swarm_sdk.retrieval.cache import SemanticCache
from swarm_sdk.retrieval.embeddings import Embedder, FastEmbedder, HashEmbedder, LlamaCppEmbedder
from swarm_sdk.retrieval.hybrid import hybrid_search
from swarm_sdk.retrieval.recall import recall_texts
from swarm_sdk.retrieval.rerank import FastEmbedReranker, KeywordReranker, Reranker

ROUTER_SYSTEM = 'Route work. Reply with JSON only: {"mode":"parallel" or "swarm","tasks":[]}.'
RESEARCHER_PROMPT = "You are the researcher. Use only the supplied context. Be brief."
CODER_PROMPT = "You are the coder. Be brief."
REVIEWER_PROMPT = "You are the reviewer. Be brief."
_JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)


def _handoff(agent_name: str, description: str):
    """Keyword-only langgraph-swarm API: agent_name, optional name and description."""
    return create_handoff_tool(
        agent_name=agent_name,
        name=f"transfer_to_{agent_name}",
        description=description,
    )


class RunResult(BaseModel):
    text: str
    cached: bool
    active_agent: str
    tokens: int
    mode: str


class RouteDecision(BaseModel):
    mode: Literal["parallel", "swarm"] = "swarm"
    tasks: list[str] = Field(default_factory=list)


def _parse_route(raw: str) -> RouteDecision:
    """Parse router output, defaulting to ``RouteDecision()`` on anything malformed."""
    match = _JSON_OBJECT.search(raw)
    if match is None:
        return RouteDecision()
    try:
        return RouteDecision.model_validate(json.loads(match.group(0)))
    except json.JSONDecodeError, ValidationError:
        return RouteDecision()


def _fastembed_available() -> bool:
    try:
        importlib.import_module("fastembed")
    except ImportError:
        return False
    return True


def default_embedder(settings: Settings) -> Embedder:
    batch = settings.embed_batch_size
    if settings.embed_backend == "llama-cpp":
        model_path = settings.llama_embed_model or settings.embed_model
        return LlamaCppEmbedder(
            model_path,
            settings.embed_dim,
            batch,
            n_ctx=settings.llama_n_ctx,
            n_gpu_layers=settings.llama_gpu_layers,
            n_batch=settings.llama_n_batch,
        )
    if settings.embed_backend == "hash" or not _fastembed_available():
        return HashEmbedder(settings.embed_dim, batch, settings.embed_model)
    return FastEmbedder(settings.embed_model, settings.embed_dim, batch)


def default_reranker(settings: Settings) -> Reranker:
    if not _fastembed_available():
        return KeywordReranker()
    return FastEmbedReranker(settings.rerank_model)


def open_store(settings: Settings) -> MemoryStore:
    if settings.memory_backend == "faiss":
        from swarm_sdk.memory.faiss_store import FaissStore

        return FaissStore(settings.embed_dim, gpu=settings.vector_gpu)
    if settings.memory_backend == "qdrant":
        from swarm_sdk.memory.qdrant_store import QdrantStore

        return QdrantStore(
            settings.memory_path,
            settings.embed_dim,
            quantization=settings.vector_quantization,
        )
    if settings.memory_backend == "opencl":
        from swarm_sdk.memory.opencl_store import OpenClVecStore

        return OpenClVecStore(settings.embed_dim, quantize=settings.opencl_quantize)
    if settings.memory_backend == "mem0":
        from swarm_sdk.memory.mem0_store import Mem0Store

        return Mem0Store.from_settings(settings)
    return SqliteVecStore(settings.memory_path, settings.embed_dim)


class CompiledGraph(Protocol):
    def invoke(self, payload: dict[str, object], config: dict[str, object]) -> object: ...


class SwarmSDK:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        file_config: SwarmFileConfig | None = None,
        router_model: BaseChatModel | None = None,
        specialist_model: BaseChatModel | None = None,
        embedder: Embedder | None = None,
        reranker: Reranker | None = None,
        memory: MemoryStore | None = None,
        cache: SemanticCache | None = None,
        budget: TokenBudget | None = None,
    ) -> None:
        if settings is None and file_config is None:
            settings, file_config = load_merged_settings()
        self.settings = settings or Settings()
        self.file_config = file_config or load_swarm_config()
        set_opencl_enabled(self.settings.opencl_enabled)
        self._router_model = router_model
        self._specialist_model = specialist_model
        self.embedder = embedder or default_embedder(self.settings)
        self.reranker = reranker or default_reranker(self.settings)
        self._memory = memory
        self._cache = cache
        self.budget = budget or TokenBudget(
            max_tokens=self.settings.max_tokens,
            tool_cap=self.settings.tool_cap,
        )
        self._fallback = FallbackChain(
            self.file_config.model_select,
            self.file_config.circuit_breaker,
        )
        self._selector = ModelSelector(self.file_config.model_select)
        self._langgraph_manifests = langgraph_manifests(load_all_agent_manifests())
        self.usage = UsageLog()
        self._compiled: CompiledGraph | None = None
        self._threads: set[str] = set()

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> SwarmSDK:
        if settings is None:
            merged, file_cfg = load_merged_settings()
            return cls(merged, file_config=file_cfg)
        return cls(settings, file_config=load_swarm_config())

    def provider_health(self) -> dict[str, str]:
        return {name: breaker.state.value for name, breaker in self._fallback.breakers.items()}

    @property
    def memory(self) -> MemoryStore:
        if self._memory is None:
            self._memory = open_store(self.settings)
        return self._memory

    @property
    def cache(self) -> SemanticCache:
        if self._cache is None:
            self._cache = SemanticCache(
                self.settings.cache_path,
                self.embedder,
                self.settings.semantic_threshold,
                ttl_days=self.settings.cache_ttl_days,
                use_index=self.settings.semantic_cache_on_gpu,
            )
        return self._cache

    def _cap_tokens(self, think_level: ThinkLevel) -> None:
        cap = THINK_TOKEN_BUDGET.get(think_level, self.settings.max_tokens)
        if think_level != "off" and cap > 0:
            self.budget.max_tokens = min(self.settings.max_tokens, cap)

    async def run(self, text: str, thread_id: str = "default") -> RunResult:
        if self.settings.peer_url:
            from swarm_sdk.serving.peer import async_post_json

            payload = await async_post_json(
                self.settings.peer_url,
                {"text": text, "thread_id": thread_id},
            )
            return RunResult.model_validate(payload)

        cached = await offload(self.cache.lookup, text)
        if cached is not None:
            self.usage.add("cache", 0, True)
            return RunResult(
                text=cached,
                cached=True,
                active_agent="cache",
                tokens=0,
                mode="cache",
            )

        self._cap_tokens(self.file_config.router.think_level)
        memories = await offload(self._recall, text)
        packed = self.budget.pack(system=ROUTER_SYSTEM, memories=memories, turns=[text])
        route, route_tokens = await self._route(packed)
        if route.mode == "parallel" and route.tasks:
            answer, tokens = await fan_out(
                self._specialist(),
                route.tasks,
                max_concurrency=self.file_config.parallelism.max_concurrency,
            )
            agent = "synthesizer"
            mode = "parallel"
        else:
            answer, tokens, agent = await self._swarm(packed, thread_id)
            mode = "swarm"
        tokens += route_tokens
        await offload(self.cache.store, text, answer)
        await offload(self._remember, text, answer)
        self.usage.add(agent, tokens, False)
        self.budget.max_tokens = self.settings.max_tokens
        return RunResult(
            text=answer,
            cached=False,
            active_agent=agent,
            tokens=tokens,
            mode=mode,
        )

    def recall(self, query: str, top_k: int | None = None) -> list[MemoryHit]:
        limit = top_k or self.settings.rerank_k
        retrieve = max(limit, self.settings.retrieve_k)
        search_text = getattr(self.memory, "search_text", None)
        if callable(search_text):
            hits = list(search_text(query, retrieve))
        else:
            vector = self.embedder.embed([query], query=True)[0]
            if self.settings.hybrid_enabled and self.file_config.hybrid_search.enabled:
                return hybrid_search(
                    query,
                    self.memory,
                    vector,
                    retrieve_k=retrieve,
                    config=self.file_config.hybrid_search.model_copy(update={"final_k": limit}),
                )
            hits = self.memory.search(vector, retrieve)
        if not hits:
            return []
        order = self.reranker.rerank(query, [hit.text for hit in hits])
        by_text = {hit.text: hit for hit in hits}
        ranked = [by_text[item] for item in order if item in by_text]
        return ranked[:limit]

    def _recall(self, text: str) -> list[str]:
        return recall_texts(
            text,
            self.memory,
            self.embedder,
            self.reranker,
            retrieve_k=self.settings.retrieve_k,
            rerank_k=self.settings.rerank_k,
            dedup_threshold=self.settings.dedup_threshold,
            hybrid=self.file_config.hybrid_search,
            hybrid_enabled=self.settings.hybrid_enabled,
        )

    def _remember(self, question: str, answer: str) -> None:
        record = f"Q: {question[:200]}\nA: {answer[:400]}"
        vector = self.embedder.embed([record], query=False)[0]
        self.memory.add(record, vector)

    async def _route(self, packed: PackedPrompt) -> tuple[RouteDecision, int]:
        if self._router_model is not None:
            raw, tokens = await complete_with_usage(self._router_model, ROUTER_SYSTEM, packed.text)
        else:
            raw, tokens = await self._fallback.complete_with_usage(
                ROUTER_SYSTEM,
                packed.text,
                think_level=self.file_config.router.think_level,
            )
        return _parse_route(raw), tokens

    async def _swarm(self, packed: PackedPrompt, thread_id: str) -> tuple[str, int, str]:
        graph = self._graph()
        user = packed.user or packed.system
        payload: dict[str, object] = {"messages": [{"role": "user", "content": user}]}
        if thread_id not in self._threads:
            payload["active_agent"] = "researcher"
            self._threads.add(thread_id)

        def _call() -> dict[str, object]:
            state = graph.invoke(payload, {"configurable": {"thread_id": thread_id}})
            if not isinstance(state, dict):
                raise TypeError("swarm state must be a dict")
            return state

        state = await offload(_call)
        messages = state.get("messages", [])
        if not isinstance(messages, list):
            messages = []
        answer = last_ai_text(messages)
        agent = state.get("active_agent") or "researcher"
        reported = usage_tokens(messages)
        tokens = (
            reported
            if reported is not None
            else self.budget.count(packed.text) + self.budget.count(answer)
        )
        return answer, tokens, str(agent)

    def _router(self) -> BaseChatModel:
        if self._router_model is None:
            self._router_model = load_chat_model(self.settings.router_model)
        return self._router_model

    def _specialist(self) -> BaseChatModel:
        if self._specialist_model is None:
            self._specialist_model = load_chat_model(self.settings.specialist_model)
        return self._specialist_model

    def _model_for_node(self, node: str) -> BaseChatModel:
        if self._specialist_model is not None:
            return self._specialist_model
        manifest = self._langgraph_manifests.get(node)
        if manifest is None:
            return self._specialist()
        if manifest.model:
            return load_chat_model(manifest.model)
        route = self._selector.select(manifest.think_level)
        return load_chat_model(route.name)

    def _graph(self) -> CompiledGraph:
        if self._compiled is None:
            researcher = create_agent(
                self._model_for_node("researcher"),
                tools=[
                    _handoff("coder", "Hand off coding."),
                    _handoff("reviewer", "Hand off review."),
                ],
                system_prompt=RESEARCHER_PROMPT,
                name="researcher",
            )
            coder = create_agent(
                self._model_for_node("coder"),
                tools=[
                    _handoff("researcher", "Hand off research."),
                    _handoff("reviewer", "Hand off review."),
                ],
                system_prompt=CODER_PROMPT,
                name="coder",
            )
            reviewer = create_agent(
                self._model_for_node("reviewer"),
                tools=[
                    _handoff("researcher", "Hand off research."),
                    _handoff("coder", "Hand off coding."),
                ],
                system_prompt=REVIEWER_PROMPT,
                name="reviewer",
            )
            workflow = create_swarm(
                [researcher, coder, reviewer],
                default_active_agent="researcher",
            )
            # Short-term: checkpointer (active_agent + messages per thread_id).
            # Long-term recall is SwarmSDK.memory (sqlite-vec / mem0 / …), not this store.
            self._compiled = cast(CompiledGraph, workflow.compile(checkpointer=InMemorySaver()))
        if self._compiled is None:
            raise RuntimeError("swarm graph was not compiled")
        return self._compiled


__all__ = [
    "RouteDecision",
    "RunResult",
    "SwarmSDK",
    "default_embedder",
    "default_reranker",
    "open_store",
]
