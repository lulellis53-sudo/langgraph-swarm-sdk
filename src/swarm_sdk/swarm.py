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

from swarm_sdk.cache import SemanticCache
from swarm_sdk.config import Settings
from swarm_sdk.embeddings import Embedder, FastEmbedder, HashEmbedder
from swarm_sdk.memory.base import MemoryHit, MemoryStore
from swarm_sdk.memory.sqlite_vec import SqliteVecStore
from swarm_sdk.parallel import fan_out
from swarm_sdk.providers import complete, last_ai_text, load_chat_model
from swarm_sdk.rerank import FastEmbedReranker, KeywordReranker, Reranker
from swarm_sdk.retrieval import recall_texts
from swarm_sdk.runtime import offload
from swarm_sdk.tokens import PackedPrompt, TokenBudget
from swarm_sdk.transport import async_post_json
from swarm_sdk.usage import UsageLog

ROUTER_SYSTEM = (
    'Route work. Reply with JSON only: {"mode":"parallel" or "swarm","tasks":[]}.'
)
RESEARCHER_PROMPT = "You are the researcher. Use only the supplied context. Be brief."
CODER_PROMPT = "You are the coder. Be brief."
REVIEWER_PROMPT = "You are the reviewer. Be brief."
_JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)


class RunResult(BaseModel):
    text: str
    cached: bool
    active_agent: str
    tokens: int
    mode: str


class RouteDecision(BaseModel):
    mode: Literal["parallel", "swarm"] = "swarm"
    tasks: list[str] = Field(default_factory=list)


def _fastembed_available() -> bool:
    try:
        importlib.import_module("fastembed")
    except ImportError:
        return False
    return True


def default_embedder(settings: Settings) -> Embedder:
    if not _fastembed_available():
        return HashEmbedder(settings.embed_dim)
    return FastEmbedder(settings.embed_model, settings.embed_dim)


def default_reranker(settings: Settings) -> Reranker:
    if not _fastembed_available():
        return KeywordReranker()
    return FastEmbedReranker(settings.rerank_model)


def open_store(settings: Settings) -> MemoryStore:
    if settings.memory_backend == "faiss":
        from swarm_sdk.memory.faiss_store import FaissStore

        return FaissStore(settings.embed_dim)
    if settings.memory_backend == "qdrant":
        from swarm_sdk.memory.qdrant_store import QdrantStore

        return QdrantStore(settings.memory_path, settings.embed_dim)
    return SqliteVecStore(settings.memory_path, settings.embed_dim)


class CompiledGraph(Protocol):
    def invoke(self, payload: dict[str, object], config: dict[str, object]) -> object: ...


class SwarmSDK:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        router_model: BaseChatModel | None = None,
        specialist_model: BaseChatModel | None = None,
        embedder: Embedder | None = None,
        reranker: Reranker | None = None,
        memory: MemoryStore | None = None,
        cache: SemanticCache | None = None,
        budget: TokenBudget | None = None,
    ) -> None:
        self.settings = settings or Settings()
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
        self.usage = UsageLog()
        self._compiled: CompiledGraph | None = None
        self._threads: set[str] = set()

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> SwarmSDK:
        return cls(settings or Settings())

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
            )
        return self._cache

    async def run(self, text: str, thread_id: str = "default") -> RunResult:
        if self.settings.peer_url:
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

        memories = await offload(self._recall, text)
        packed = self.budget.pack(system=ROUTER_SYSTEM, memories=memories, turns=[text])
        route = await self._route(packed)
        if route.mode == "parallel" and route.tasks:
            answer, tokens = await fan_out(self._specialist(), route.tasks)
            agent = "synthesizer"
            mode = "parallel"
        else:
            answer, tokens, agent = await self._swarm(packed, thread_id)
            mode = "swarm"
        await offload(self.cache.store, text, answer)
        await offload(self._remember, text, answer)
        self.usage.add(agent, tokens, False)
        return RunResult(
            text=answer,
            cached=False,
            active_agent=agent,
            tokens=tokens,
            mode=mode,
        )

    def recall(self, query: str, top_k: int | None = None) -> list[MemoryHit]:
        limit = top_k or self.settings.rerank_k
        vector = self.embedder.embed([query])[0]
        hits = self.memory.search(vector, max(limit, self.settings.retrieve_k))
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
        )

    def _remember(self, question: str, answer: str) -> None:
        record = f"Q: {question[:200]}\nA: {answer[:400]}"
        vector = self.embedder.embed([record])[0]
        self.memory.add(record, vector)

    async def _route(self, packed: PackedPrompt) -> RouteDecision:
        raw = await complete(self._router(), ROUTER_SYSTEM, packed.text)
        match = _JSON_OBJECT.search(raw)
        if match is None:
            return RouteDecision()
        try:
            payload = json.loads(match.group(0))
        except json.JSONDecodeError:
            return RouteDecision()
        try:
            return RouteDecision.model_validate(payload)
        except ValidationError:
            return RouteDecision()

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
        tokens = self.budget.count(packed.text) + self.budget.count(answer)
        return answer, tokens, str(agent)

    def _router(self) -> BaseChatModel:
        if self._router_model is None:
            self._router_model = load_chat_model(self.settings.router_model)
        return self._router_model

    def _specialist(self) -> BaseChatModel:
        if self._specialist_model is None:
            self._specialist_model = load_chat_model(self.settings.specialist_model)
        return self._specialist_model

    def _graph(self) -> CompiledGraph:
        if self._compiled is None:
            model = self._specialist()
            researcher = create_agent(
                model,
                tools=[
                    create_handoff_tool(agent_name="coder", description="Hand off coding."),
                    create_handoff_tool(agent_name="reviewer", description="Hand off review."),
                ],
                system_prompt=RESEARCHER_PROMPT,
                name="researcher",
            )
            coder = create_agent(
                model,
                tools=[
                    create_handoff_tool(agent_name="researcher", description="Hand off research."),
                    create_handoff_tool(agent_name="reviewer", description="Hand off review."),
                ],
                system_prompt=CODER_PROMPT,
                name="coder",
            )
            reviewer = create_agent(
                model,
                tools=[
                    create_handoff_tool(agent_name="researcher", description="Hand off research."),
                    create_handoff_tool(agent_name="coder", description="Hand off coding."),
                ],
                system_prompt=REVIEWER_PROMPT,
                name="reviewer",
            )
            workflow = create_swarm(
                [researcher, coder, reviewer],
                default_active_agent="researcher",
            )
            self._compiled = cast(CompiledGraph, workflow.compile(checkpointer=InMemorySaver()))
        if self._compiled is None:
            raise RuntimeError("swarm graph was not compiled")
        return self._compiled
