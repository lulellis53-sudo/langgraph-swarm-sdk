"""Core domain: SwarmSDK orchestrator facade."""

from __future__ import annotations

from swarm_sdk.core.allocator import AllocatorManager, GuardReport, MemoryStats
from swarm_sdk.core.compression import (
    CompressedScratchpadPool,
    LazyModule,
    SwarmBufferEntry,
    ZstdStateCompressor,
    hybrid_jit,
    is_jit_disabled,
    lazy_import,
)
from swarm_sdk.core.jev_router import (
    ChoiceDecision,
    JevRouter,
    NoulDecision,
    ScoreDecision,
)
from swarm_sdk.core.lifeguard_ast import (
    LifeguardAuditReport,
    LifeguardViolation,
    MetaLifeguardAuditor,
    audit_code,
)
from swarm_sdk.core.minimalloc import Buffer, Configuration, MiniMalloc, Solution, SolverType
from swarm_sdk.core.rules import HostInvariants, HostRuleEngine
from swarm_sdk.core.swarm import (
    RouteDecision,
    RunResult,
    SwarmSDK,
    default_embedder,
    default_reranker,
    open_store,
)

__all__ = [
    "AllocatorManager",
    "Buffer",
    "ChoiceDecision",
    "CompressedScratchpadPool",
    "Configuration",
    "GuardReport",
    "HostInvariants",
    "HostRuleEngine",
    "JevRouter",
    "LazyModule",
    "LifeguardAuditReport",
    "LifeguardViolation",
    "MemoryStats",
    "MetaLifeguardAuditor",
    "MiniMalloc",
    "NoulDecision",
    "RouteDecision",
    "RunResult",
    "ScoreDecision",
    "Solution",
    "SolverType",
    "SwarmBufferEntry",
    "SwarmSDK",
    "ZstdStateCompressor",
    "audit_code",
    "default_embedder",
    "default_reranker",
    "hybrid_jit",
    "is_jit_disabled",
    "lazy_import",
    "open_store",
]
