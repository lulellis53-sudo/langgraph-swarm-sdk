---
name: semantic-caching
description: Use when designing, integrating, or debugging semantic embedding similarity caches for LLM queries, vector search deduplication, or sub-5ms fast-path responses.
---

# Semantic Caching

## Overview

Semantic caching intercepts queries before they reach expensive LLM inference engines or distributed vector databases. By evaluating the high-dimensional cosine similarity between inbound query embeddings and previously cached queries, the system returns validated responses in sub-2ms latency while reducing token spend to zero.

**Core principle:** If the semantic distance $d(q_{\text{new}}, q_{\text{cached}}) \le \epsilon$, recomputing the response is computational waste.

---

## When to Use

**Always:**
- Repetitive user queries in search and conversational systems.
- High-cost LLM workflows (multi-turn agents, code generation, summarization).
- Latency-critical APIs where P95 must stay under $50\text{ ms}$.
- Embedding generation deduplication across document ingestion pipelines.

**When to Bypass:**
- State-mutating commands (e.g. file writes, git commits, database updates).
- User-specific private data queries without strict tenant scoping.
- Non-deterministic queries requiring real-time timestamps or live external stock/weather feeds.

---

## The Iron Laws of Semantic Caching

```
1. ZERO CACHE HITS WITHOUT COSINE SIMILARITY ≥ THRESHOLD (Default τ = 0.96)
2. TENANT ISOLATION: A CACHE ENTRY IS NEVER SHARED ACROSS TENANT BOUNDARIES
3. NEVER CACHE MUTATING ACTIONS OR UNVALIDATED RESPONSES
```

---

## Architectural Pipeline

```
                                  [Inbound Query]
                                         │
                                [Generate Embedding]
                                         │
                          ┌──────────────┴──────────────┐
                          ▼                             ▼
                 [Exact SHA-256 Hit?]         [Compute Cosine Sim]
                  (Match in L1 RAM)            (Dot Product over Matrix)
                          │                             │
                     Return Cache                       ▼
                    (Latency < 1ms)            Max Sim ≥ Threshold?
                                               (e.g., τ ≥ 0.96)
                                                        │
                                            ┌───────────┴───────────┐
                                           YES                      NO
                                            │                       │
                                            ▼                       ▼
                                   [Return Cached Item]    [Cache Miss: Execute]
                                     (Latency < 3ms)       [Downstream LLM / DB]
                                                                    │
                                                           [Store in Cache with]
                                                           [TTL & LRU Eviction ]
```

---

## Operational Workflow

### 1. Vector Normalization
Always $L_2$-normalize query embeddings prior to distance calculation:
$$\hat{q} = \frac{q}{\|q\|_2 + 10^{-12}}, \quad S_{\cos}(\hat{q}_1, \hat{q}_2) = \hat{q}_1 \cdot \hat{q}_2$$
This reduces cosine similarity computation to a single contiguous BLAS matrix-vector product (`M @ q_norm`).

### 2. Threshold Calibration
- **$\tau \ge 0.98$ (Ultra-Strict)**: Code generation, syntax queries, exact mathematical calculations.
- **$\tau \ge 0.95$ (Standard Semantic)**: Fact-finding, conceptual explanations, documentation search.
- **$\tau < 0.90$ (Forbidden)**: High risk of false-positive cache collisions and semantic drift.

### 3. Eviction & TTL Management
- **LRU / FIFO Eviction**: Enforce bounded memory size ($N_{\max} \in [10^4, 10^5]$ items).
- **Time-to-Live (TTL)**: Invalidate cache entries after fixed duration ($T_{\text{TTL}} = 24\text{ hours}$ default) or upon upstream repository changes.

---

## Reference Implementation Blueprint

```python
from __future__ import annotations
import time
from dataclasses import dataclass, field
import numpy as np

@dataclass
class SemanticCacheEntry:
    query_text: str
    query_vector: np.ndarray  # Pre-normalized unit vector
    response: dict
    created_at: float = field(default_factory=time.time)
    tenant_id: str = "default"

class SemanticCache:
    """Production-grade semantic cache with cosine threshold gating."""

    def __init__(
        self,
        similarity_threshold: float = 0.96,
        max_entries: int = 10000,
        ttl_seconds: float = 86400.0,
    ) -> None:
        self.threshold = similarity_threshold
        self.max_entries = max_entries
        self.ttl = ttl_seconds
        self.entries: list[SemanticCacheEntry] = []
        self._matrix: np.ndarray | None = None

    def query(self, query_vec: np.ndarray, tenant_id: str = "default") -> dict | None:
        if not self.entries or self._matrix is None:
            return None
        now = time.time()
        q_norm = query_vec / (np.linalg.norm(query_vec) + 1e-12)
        sims = self._matrix @ q_norm
        best_idx = int(np.argmax(sims))
        
        if sims[best_idx] >= self.threshold:
            entry = self.entries[best_idx]
            if entry.tenant_id == tenant_id and (now - entry.created_at) < self.ttl:
                return entry.response
        return None

    def insert(self, query_text: str, query_vec: np.ndarray, response: dict, tenant_id: str = "default") -> None:
        if len(self.entries) >= self.max_entries:
            self.entries.pop(0)
            if self._matrix is not None:
                self._matrix = self._matrix[1:]
        q_norm = query_vec / (np.linalg.norm(query_vec) + 1e-12)
        entry = SemanticCacheEntry(query_text, q_norm, response, tenant_id=tenant_id)
        self.entries.append(entry)
        if self._matrix is None:
            self._matrix = q_norm.reshape(1, -1)
        else:
            self._matrix = np.vstack([self._matrix, q_norm])
```

---

## Verification & Quality Gates

Before declaring semantic cache integration complete:
- [ ] Measure exact cache hit latency ($< 3\text{ ms}$).
- [ ] Verify non-matching test queries (sim $< 0.85$) correctly miss and trigger LLM execution.
- [ ] Verify near-identical paraphrases (sim $\ge 0.97$) successfully hit and return valid payloads.
- [ ] Ensure tenant boundary isolation (Tenant A cannot access Tenant B cached responses).
