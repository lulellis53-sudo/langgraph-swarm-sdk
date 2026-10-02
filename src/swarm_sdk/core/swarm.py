"""LangGraph handoff swarm plus a token-saving front door."""

from __future__ import annotations

import importlib
import json
import logging
import re
import threading
from typing import TYPE_CHECKING, Literal, Protocol, cast

from pydantic import BaseModel, Field, ValidationError

from swarm_sdk.agents.manifest import (
    AgentManifest,
    agents_root,
    langgraph_manifests,
    load_all_agent_manifests,
    role_contract,
)
from swarm_sdk.config.loader import SwarmFileConfig, load_swarm_config
from swarm_sdk.config.settings import Settings, load_merged_settings
from swarm_sdk.execution.executor import offload
from swarm_sdk.execution.fanout import fan_out
from swarm_sdk.gpu import set_enabled as set_opencl_enabled
from swarm_sdk.memory.base import MemoryHit, MemoryStore
from swarm_sdk.memory.sqlite_vec import SqliteVecStore
from swarm_sdk.models.chat import (
    complete_with_usage,
    last_ai_text,
    load_chat_model,
    message_tokens,
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
from swarm_sdk.prompting.budget import PackedPrompt, TokenBudget, count_text
from swarm_sdk.retrieval.cache import SemanticCache
from swarm_sdk.retrieval.embeddings import Embedder, FastEmbedder, HashEmbedder, LlamaCppEmbedder
from swarm_sdk.retrieval.recall import recall_hits
from swarm_sdk.retrieval.rerank import FastEmbedReranker, KeywordReranker, Reranker

if TYPE_CHECKING:
    from langchain_core.language_models.chat_models import BaseChatModel

logger = logging.getLogger(__name__)

ROUTER_SYSTEM = 'Route work. Reply with JSON only: {"mode":"parallel" or "swarm","tasks":[]}.'
RESEARCHER_PROMPT = "You are the researcher. Use only the supplied context. Be brief."
CODER_PROMPT = "You are the coder. Be brief."
REVIEWER_PROMPT = "You are the reviewer. Be brief."
# Fallback one-line prompts for the default trio when no manifest wires a node
# (e.g. an installed wheel used outside the repository, without ``Agents/``).
_DEFAULT_NODE_PROMPTS = {
    "researcher": RESEARCHER_PROMPT,
    "coder": CODER_PROMPT,
    "reviewer": REVIEWER_PROMPT,
}
_JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)


def _handoff(agent_name: str, description: str):
    """Keyword-only langgraph-swarm API: agent_name, optional name and description."""
    from langgraph_swarm import create_handoff_tool

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


def manifest_node_prompt(agents_root: str, manifest: AgentManifest) -> str:
    """System prompt for one manifest-wired swarm node.

    Preference order: the role contract (``Agents/{Name}/AGENTS.md``), then the
    manifest ``role`` line, then a one-line default naming the node.

    Args:
        agents_root: Directory holding the ``Agents/{Name}/`` folders.
        manifest: Validated manifest of the wired agent.

    Returns:
        The prompt text, truncated to the manifest's prompt budget.
    """
    contract = role_contract(agents_root, manifest.name)
    text = contract or manifest.role
    if not text:
        node = manifest.langgraph_node or manifest.name.lower()
        return f"You are the {node}. Be brief."
    budget = TokenBudget(max_tokens=manifest.token_budget.max_prompt)
    return budget.pack(system=text, memories=[], turns=[]).system


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
        max_threads: int = 200,
    ) -> None:
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
        from swarm_sdk.core.checkpoint import open_checkpointer

        self._compiled: CompiledGraph | None = None
        self._checkpointer = open_checkpointer(self.settings.checkpoint_path)
        self.max_threads = max_threads
        self._threads: dict[str, None] = {}
        self._threads_lock = threading.Lock()

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> SwarmSDK:
        if settings is None:
            merged, file_cfg = load_merged_settings()
            return cls(merged, file_config=file_cfg)
        return cls(settings, file_config=load_swarm_config())

    def provider_health(self) -> dict[str, str]:
        return {name: breaker.state.value for name, breaker in self._fallback.breakers.items()}

    def compiled_graph(self) -> CompiledGraph:
        """The compiled handoff swarm graph (LangGraph Server entry point)."""
        return self._graph()

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
        return recall_hits(
            query,
            self.memory,
            self.embedder,
            self.reranker,
            retrieve_k=max(top_k or self.settings.rerank_k, self.settings.retrieve_k),
            rerank_k=top_k or self.settings.rerank_k,
            dedup_threshold=self.settings.dedup_threshold,
            hybrid=self.file_config.hybrid_search,
            hybrid_enabled=self.settings.hybrid_enabled,
        )

    def _recall(self, text: str) -> list[str]:
        return [hit.text for hit in self.recall(text)]

    def _remember(self, question: str, answer: str) -> None:
        record = f"Q: {question[:200]}\nA: {answer[:400]}"
        vector = self.embedder.embed([record], query=False)[0]
        self.memory.add(record, vector)

    async def _route_structured(self, user: str) -> tuple[RouteDecision | None, int]:
        """Ask the router for a ``RouteDecision`` via LangChain tool-calling.

        Args:
            user: The packed router prompt body (memories + user text).

        Returns:
            ``(decision, tokens)`` on a parseable reply, else ``(None, 0)`` so
            the caller falls back to the JSON-mode + regex path.
        """
        from langchain_core.messages import HumanMessage, SystemMessage

        try:
            structured = self._router().with_structured_output(RouteDecision, include_raw=True)
        except NotImplementedError:
            return None, 0
        result = await offload(
            structured.invoke,
            [SystemMessage(content=ROUTER_SYSTEM), HumanMessage(content=user)],
        )
        if not isinstance(result, dict):
            return None, 0
        parsed = result.get("parsed")
        if not isinstance(parsed, RouteDecision):
            return None, 0
        tokens = message_tokens(result.get("raw"))
        if tokens is None:
            tokens = count_text(ROUTER_SYSTEM) + count_text(user)
        return parsed, tokens

    async def _route(self, packed: PackedPrompt) -> tuple[RouteDecision, int]:
        user = packed.suffix or packed.prefix
        if self.settings.router_structured_output:
            decision, tokens = await self._route_structured(user)
            if decision is not None:
                return decision, tokens
        json_mode = self.settings.router_structured_output
        if self._router_model is not None:
            raw, tokens = await complete_with_usage(
                self._router_model,
                ROUTER_SYSTEM,
                user,
                json_mode=json_mode,
            )
        else:
            raw, tokens = await self._fallback.complete_with_usage(
                ROUTER_SYSTEM,
                user,
                think_level=self.file_config.router.think_level,
                json_mode=json_mode,
            )
        return _parse_route(raw), tokens

    def _run_config(self, thread_id: str) -> dict[str, object]:
        return {
            "configurable": {"thread_id": thread_id},
            "recursion_limit": self.settings.recursion_limit,
        }

    def _is_new_thread(self, thread_id: str) -> bool:
        """True when the checkpointer holds no state for ``thread_id`` (survives restarts)."""
        config = {"configurable": {"thread_id": thread_id}}
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
        graph = self._graph()
        user = packed.user or packed.system
        payload: dict[str, object] = {"messages": [{"role": "user", "content": user}]}
        self._register_thread(thread_id)
        if self._is_new_thread(thread_id):
            payload["active_agent"] = self._default_agent

        def _call() -> dict[str, object]:
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

    @property
    def _default_agent(self) -> str:
        """Entry node for new threads; ``researcher`` whenever it is wired."""
        nodes = set(self._langgraph_manifests) or set(_DEFAULT_NODE_PROMPTS)
        return "researcher" if "researcher" in nodes else sorted(nodes)[0]

    def _node_tools(self, manifest: AgentManifest | None, peers: list[str]) -> list[object]:
        """Tools for one swarm node: capability-gated extras plus handoffs.

        A manifest advertising the ``web_search`` capability also gets the
        WebSearch LangChain tools when ``Settings.enable_websearch_tools`` is
        set and the package is importable; otherwise only handoff tools.
        """
        handoffs = [_handoff(peer, f"Hand off {peer} work.") for peer in peers]
        if (
            manifest is not None
            and self.settings.enable_websearch_tools
            and "web_search" in manifest.capabilities
        ):
            return [*_websearch_tools(), *handoffs]
        return handoffs

    def _graph(self) -> CompiledGraph:
        if self._compiled is None:
            from langchain.agents import create_agent
            from langgraph_swarm import create_swarm

            # Nodes come from the Agents/ catalog: every manifest that wires a
            # ``langgraph_node`` becomes a specialist; prompts are that persona's
            # role contract. Without a catalog the default trio stands in.
            nodes = sorted(self._langgraph_manifests) or sorted(_DEFAULT_NODE_PROMPTS)
            root = str(agents_root())
            agents = []
            for node in nodes:
                manifest = self._langgraph_manifests.get(node)
                prompt = (
                    manifest_node_prompt(root, manifest)
                    if manifest is not None
                    else _DEFAULT_NODE_PROMPTS.get(node, f"You are the {node}. Be brief.")
                )
                peers = [peer for peer in nodes if peer != node]
                agents.append(
                    # Mixed handoff/websearch tool objects; the static overloads
                    # only track the literal tool-list shape (cf. load_chat_model).
                    create_agent(  # ty: ignore[no-matching-overload]
                        self._model_for_node(node),
                        tools=self._node_tools(manifest, peers),
                        system_prompt=prompt,
                        name=node,
                    )
                )
            workflow = create_swarm(agents, default_active_agent=self._default_agent)
            # Short-term: checkpointer (active_agent + messages per thread_id).
            # Long-term recall is SwarmSDK.memory (sqlite-vec / mem0 / …), not this store.
            self._compiled = cast(CompiledGraph, workflow.compile(checkpointer=self._checkpointer))
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
