"""LangGraph handoff cap and the RAG dossier router."""

import numpy as np
import pytest

from swarm_sdk.core.handoff_guard import HandoffCycleError, HandoffTrail, advance_handoff
from swarm_sdk.retrieval.gate import Confidence
from swarm_sdk.retrieval.rag_route import (
    BGE_DIM,
    CragAction,
    QueryPath,
    Reflection,
    crag_action,
    plan_retrieval,
    pool_late_chunks,
    redis_hnsw_spec,
    reflect,
    route_query,
)


def test_handoff_depth_stops_a_loop() -> None:
    """A trail may move forward and stops when it returns to an earlier agent."""
    trail = HandoffTrail(active_agent="supervisor", visited=("supervisor",), max_depth=3)
    trail = trail.handoff("coder")
    assert trail.active_agent == "coder"
    assert trail.depth == 1
    with pytest.raises(HandoffCycleError):
        trail.handoff("supervisor")


def test_advance_handoff_rejects_self_and_the_cap() -> None:
    """An agent cannot hand off to itself, and depth past the cap is refused."""
    assert advance_handoff("lifeguard", "coder", 2, max_depth=2) == 2
    with pytest.raises(HandoffCycleError):
        advance_handoff("coder", "coder", 1, max_depth=2)
    with pytest.raises(HandoffCycleError):
        advance_handoff("lifeguard", "coder", 3, max_depth=2)


def test_relational_query_uses_the_graph_arm() -> None:
    """A comparison is a graph query. A plain lookup stays on dense search."""
    assert route_query("compare Redis and FAISS") is QueryPath.GRAPH
    assert route_query("where is the cache") is QueryPath.DENSE


def test_crag_and_self_rag_follow_the_confidence_gate() -> None:
    """High confidence proceeds and is supported. Low confidence asks for another retrieval."""
    assert crag_action(Confidence.HIGH) is CragAction.PROCEED
    assert crag_action(Confidence.AMBIGUOUS) is CragAction.MIXED
    assert crag_action(Confidence.LOW) is CragAction.WEB_FALLBACK
    assert reflect(Confidence.HIGH, kept=2) is Reflection.SUPPORTED
    assert reflect(Confidence.AMBIGUOUS, kept=1) is Reflection.IRRELEVANT
    assert reflect(Confidence.LOW, kept=0) is Reflection.RETRIEVE
    plan = plan_retrieval("how does A relate to B", Confidence.LOW, kept=0)
    assert plan.path is QueryPath.GRAPH
    assert plan.crag is CragAction.WEB_FALLBACK
    assert plan.reflection is Reflection.RETRIEVE


def test_late_chunk_pool_keeps_span_means() -> None:
    """Each span becomes the normalized mean of its token rows."""
    tokens = np.array([[1.0, 0.0], [1.0, 0.0], [0.0, 2.0]], dtype=np.float32)
    pooled = pool_late_chunks(tokens, [(0, 2), (2, 3)])
    assert pooled.shape == (2, 2)
    assert pooled[0] == pytest.approx(np.array([1.0, 0.0], dtype=np.float32))
    assert pooled[1] == pytest.approx(np.array([0.0, 1.0], dtype=np.float32))
    assert pool_late_chunks(tokens, []).shape == (0, 2)
    with pytest.raises(ValueError):
        pool_late_chunks(tokens, [(1, 1)])


def test_redis_hnsw_spec_matches_the_dossier() -> None:
    """The vector index is 384-d cosine HNSW and does not open a connection."""
    spec = redis_hnsw_spec()
    assert spec["index"] == "idx:rag"
    assert spec["prefix"] == "doc:"
    assert spec["algorithm"] == "HNSW"
    assert spec["distance"] == "COSINE"
    assert spec["dim"] == BGE_DIM
