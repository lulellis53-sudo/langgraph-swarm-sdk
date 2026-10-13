"""LangGraph handoff swarm plus a token-saving front door."""

from __future__ import annotations

import importlib
import logging
import threading
from typing import TYPE_CHECKING, Protocol

from pydantic import BaseModel

from swarm_sdk.agents.manifest import (
    langgraph_manifests,
    load_all_agent_manifests,
)
from swarm_sdk.config.loader import SwarmFileConfig, load_swarm_config
from swarm_sdk.config.settings import Settings, load_merged_settings
from swarm_sdk.core.factories import (
    default_embedder,
    default_reranker,
    open_store,
)
from swarm_sdk.core.graph_builder import GraphBuilder
from swarm_sdk.core.jev_router import JevRouter
from swarm_sdk.core.memory_ops import MemoryOps
from swarm_sdk.core.prompts import (  # noqa: F401 -- API-freeze re-exports (test_api_freeze_core_swarm)
    _DEFAULT_NODE_PROMPTS,
    CODER_PROMPT,
    RESEARCHER_PROMPT,
    REVIEWER_PROMPT,
    ROUTER_SYSTEM,
    manifest_node_prompt,
)
from swarm_sdk.core.routing import RouteDecision, Router
from swarm_sdk.execution import fan_out, offload
from swarm_sdk.gpu import set_enabled as set_opencl_enabled
from swarm_sdk.memory.base import MemoryHit, MemoryStore
from swarm_sdk.models.chat import (
    last_ai_text,
    load_chat_model,
    usage_tokens,
)
from swarm_sdk.models.selection import (
    THINK_TOKEN_BUDGET,
    FallbackChain,
    ModelSelector,
    ThinkLevel,
)
from swarm_sdk.observability import metrics
from swarm_sdk.observability.usage import UsageLog
from swarm_sdk.prompting.budget import PackedPrompt, TokenBudget
from swarm_sdk.retrieval.cache import SemanticCache
from swarm_sdk.retrieval.embeddings import (
    Embedder,
)
from swarm_sdk.retrieval.rerank import Reranker

if TYPE_CHECKING:
    from langchain_core.language_models.chat_models import BaseChatModel
    from langchain_core.runnables import RunnableConfig
    from langgraph.checkpoint.base import BaseCheckpointSaver

logger = logging.getLogger(__name__)


class RunResult(BaseModel):
    """Outcome of one swarm run: text, serving mode, active agent, and token cost."""

    text: str
    cached: bool
    active_agent: str
    tokens: int
    mode: str


class CompiledGraph(Protocol):
    """Structural view of the compiled handoff-swarm graph."""

    def invoke(self, payload: dict[str, object], config: dict[str, object]) -> object:
        """Run the compiled graph on ``payload`` and return its final state."""


class SwarmSDK:
    """Public entry point: routing, handoff swarm, fan-out, semantic cache, and memory."""

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
        max_threads: int = 200,
    ) -> None:
        """Assemble the SDK: settings, models, embedder, memory, cache, checkpointer.

        Args:
            settings: Runtime settings; None loads merged defaults.
            file_config: Parsed ``swarm.yaml``; None loads the packaged file.
            router_model: Override the router chat model (tests).
            specialist_model: Override all specialist chat models (tests).
            embedder: Override the embedding backend.
            reranker: Override the reranker.
            memory: Pre-opened memory store.
            cache: Pre-opened semantic cache.
            budget: Token budget for prompt packing.
            max_threads: Conversation-thread cap before LRU eviction (>= 2).

        Raises:
            ValueError: If ``max_threads`` is below 2.
        """
        if max_threads < 2:
            raise ValueError("max_threads must be at least 2")
        from swarm_sdk.vault import prime_runtime_secrets

        prime_runtime_secrets()
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
        self._jev = JevRouter(
            endpoint=self.settings.jev_endpoint,
            timeout_s=self.settings.jev_timeout_s,
        )
        from swarm_sdk.core.checkpoint import open_checkpointer

        self._compiled: CompiledGraph | None = None
        self._checkpointer = open_checkpointer(self.settings.checkpoint_path)
        self.max_threads = max_threads
        self._threads: dict[str, None] = {}
        self._threads_lock = threading.Lock()
        # Collaborators hold a back-reference; they move code, not state.
        self._router = Router(self)
        self._memory_ops = MemoryOps(self)
        self._graph_builder = GraphBuilder(self)

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> SwarmSDK:
        """Build the SDK from merged settings (env + ``swarm.yaml``)."""
        if settings is None:
            merged, file_cfg = load_merged_settings()
            return cls(merged, file_config=file_cfg)
        return cls(settings, file_config=load_swarm_config())

    def provider_health(self) -> dict[str, str]:
        """Circuit-breaker state per provider; the ``/v1/health`` payload."""
        return {name: breaker.state.value for name, breaker in self._fallback.breakers.items()}

    def compiled_graph(self, *, with_checkpointer: bool = True) -> CompiledGraph:
        """The compiled handoff swarm graph (LangGraph Server entry point).

        Args:
            with_checkpointer: ``False`` compiles without the SDK's own saver, for hosts
                (LangGraph Server) that inject and manage persistence themselves.
        """
        if with_checkpointer:
            return self._graph()
        return self._build_graph(None)

    @property
    def memory(self) -> MemoryStore:
        """Lazily opened vector memory store."""
        if self._memory is None:
            self._memory = open_store(self.settings)
        return self._memory

    @property
    def cache(self) -> SemanticCache:
        """Lazily opened semantic cache (exact + cosine)."""
        if self._cache is None:
            self._cache = SemanticCache(
                self.settings.cache_path,
                self.embedder,
                self.settings.semantic_threshold,
                ttl_days=self.settings.cache_ttl_days,
                use_index=self.settings.semantic_cache_on_gpu,
            )
        return self._cache

    def _budget_for(self, think_level: ThinkLevel) -> TokenBudget:
        """Create an isolated prompt budget for one run."""
        max_tokens = min(self.budget.max_tokens, self.settings.max_tokens)
        cap = THINK_TOKEN_BUDGET.get(think_level, self.settings.max_tokens)
        if think_level != "off" and cap > 0:
            max_tokens = min(max_tokens, cap)
        return TokenBudget(
            max_tokens=max_tokens,
            tool_cap=self.budget.tool_cap,
            tokenizer=self.budget.tokenizer,
        )

    async def run(self, text: str, thread_id: str = "default") -> RunResult:
        """Run one user turn through cache, router, and the chosen engine.

        Args:
        text: User message.
        thread_id: Conversation thread (checkpointer key).

        Returns:
        Reply text with mode, active agent, and token accounting.

        """
        if self.settings.server_url:
            from swarm_sdk.serving.client import run_on_server

            payload = await run_on_server(
                text,
                thread_id,
                server_url=self.settings.server_url,
                graph_id=self.settings.server_graph,
            )
            return RunResult.model_validate(payload)

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

        request_budget = self._budget_for(self.file_config.router.think_level)
        memories = await offload(self._recall, text)
        packed = request_budget.pack(system=ROUTER_SYSTEM, memories=memories, turns=[text])
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
        if answer.strip():
            # Empty answers are neither cached nor remembered: caching them
            # would answer future near-identical prompts with nothing.
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
        """Hybrid-retrieval memory hits: recall, dedupe, rerank, capped at ``top_k``."""
        return self._memory_ops.recall(query, top_k)

    def _recall(self, text: str) -> list[str]:
        """Recall memories for ``text``, ordered for the prompt (U-shape when enabled)."""
        return self._memory_ops.recall_for_prompt(text)

    def _remember(self, question: str, answer: str) -> None:
        """Persist a truncated question/answer pair as one embedded memory record."""
        self._memory_ops.remember(question, answer)

    async def _route_structured(self, user: str) -> tuple[RouteDecision | None, int]:
        """Ask the router for a ``RouteDecision`` via LangChain tool-calling."""
        return await self._router.route_structured(user)

    async def _route(self, packed: PackedPrompt) -> tuple[RouteDecision, int]:
        """Choose parallel fan-out or swarm handoff, returning the decision and tokens used."""
        return await self._router.route(packed)

    def _run_config(self, thread_id: str) -> dict[str, object]:
        """Build the LangGraph run config (thread id and recursion limit)."""
        return {
            "configurable": {"thread_id": thread_id},
            "recursion_limit": self.settings.recursion_limit,
        }

    def _is_new_thread(self, thread_id: str) -> bool:
        """True when the checkpointer holds no state for ``thread_id`` (survives restarts)."""
        # Typed as RunnableConfig so the checkpointer call type-checks.
        config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
        return self._checkpointer.get_tuple(config) is None

    def _register_thread(self, thread_id: str) -> bool:
        """Track ``thread_id``; return True if it is new. Evicts the oldest ids past the cap."""
        with self._threads_lock:
            if thread_id in self._threads:
                return False
            self._threads[thread_id] = None
            if len(self._threads) > self.max_threads:
                drop = max(1, self.max_threads // 4)
                for stale in list(self._threads)[:drop]:
                    del self._threads[stale]
                    if self.settings.checkpoint_path is None:
                        self._checkpointer.delete_thread(stale)
            metrics.set_active_threads(len(self._threads))
            return True

    async def _swarm(self, packed: PackedPrompt, thread_id: str) -> tuple[str, int, str]:
        """Run the handoff swarm for ``thread_id``; return answer, tokens and active agent."""
        graph = self._graph()
        user = packed.user or packed.system
        payload: dict[str, object] = {"messages": [{"role": "user", "content": user}]}
        self._register_thread(thread_id)

        def _call() -> dict[str, object]:
            # Checkpointer read is blocking disk I/O: keep it off the event loop.
            """Invoke the graph synchronously; runs in a worker thread via ``offload``."""
            if self._is_new_thread(thread_id):
                payload["active_agent"] = self._jev_default_agent(user)
            state = graph.invoke(payload, self._run_config(thread_id))
            if not isinstance(state, dict):
                raise TypeError("swarm state must be a dict")
            return state

        state = await offload(_call)
        messages = state.get("messages", [])
        if not isinstance(messages, list):
            messages = []
        answer = last_ai_text(messages)
        agent = state.get("active_agent") or self._default_agent
        reported = usage_tokens(messages)
        tokens = (
            reported
            if reported is not None
            else self.budget.count(packed.text) + self.budget.count(answer)
        )
        return answer, tokens, str(agent)

    def _router_model_loader(self) -> BaseChatModel:
        """Return the router model, loading it on first use."""
        if self._router_model is None:
            self._router_model = load_chat_model(self.settings.model or self.settings.router_model)
        return self._router_model

    def _specialist(self) -> BaseChatModel:
        """Return the default specialist model, loading it on first use."""
        if self._specialist_model is None:
            model_name = self.settings.model or self.settings.specialist_model
            self._specialist_model = load_chat_model(model_name)
        return self._specialist_model

    def _model_for_node(self, node: str) -> BaseChatModel:
        """Return the model for a handoff node: injected model, manifest model, or default."""
        return self._graph_builder.model_for_node(node)

    @property
    def _default_agent(self) -> str:
        """Entry node for new threads; ``researcher`` whenever it is wired."""
        return self._graph_builder.default_agent

    def _jev_default_agent(self, text: str) -> str:
        """Pick the entry agent using JEV's deterministic choice router."""
        return self._graph_builder.jev_default_agent(text)

    def _node_tools(self, manifest, peers: list[str]) -> list[object]:
        """Tools for one swarm node: capability-gated extras plus handoffs."""
        return self._graph_builder.node_tools(manifest, peers)

    def _node_middleware(self) -> list[object]:
        """Token-saving middleware for every swarm agent node."""
        return self._graph_builder.node_middleware()

    def _graph(self) -> CompiledGraph:
        """Return the compiled handoff graph, building it on first use."""
        if self._compiled is None:
            self._compiled = self._build_graph(self._checkpointer)
        return self._compiled

    def _build_graph(self, checkpointer: BaseCheckpointSaver | None) -> CompiledGraph:
        """Compile the handoff swarm from the Agents/ manifest catalog."""
        return self._graph_builder.build_graph(checkpointer)


__all__ = [
    "RouteDecision",
    "RunResult",
    "SwarmSDK",
    "default_embedder",
    "default_reranker",
    "open_store",
]


def _websearch_tools() -> list[object]:
    """LangChain web-search tools from the WebSearch package; empty when absent.

    The package lives in-repo (``WebSearch/``) or installable as ``websearch``;
    both import names are tried so an installed wheel without the source tree
    still finds it when the ``websearch`` extra is present.
    """
    for module in ("WebSearch.langchain_tools", "websearch.langchain_tools"):
        try:
            imported = importlib.import_module(module)
        except ImportError:
            continue
        return list(imported.websearch_langchain_tools())
    return []
