# Optimizer Agent Skills: JEV System One Optimization & Concurrency Tuning

> **Authoritative Specification**: JEV System One Integration & Joint Efficiency-Value Engine for `Agents/Optimizer`
> **Target Models**: TypeSafe AI Jev (`jev-latest`, `POST https://api.typesafe.ai/v1/systemone`) & Local JEV Metric
> **Ecosystem**: Swarm SDK Runtime Profiling, AST Prompt Compression & Workflow Mutation

---

## 1. Overview & Architectural Role

The **Optimizer** agent is responsible for autonomous performance engineering, runtime latency/token reduction, and self-evolving workflow mutations across the Swarm SDK.

To make high-speed, calibrated decisions on *when*, *what*, and *how* to optimize without running costly exploratory full-benchmark loops, Optimizer integrates **Jev (TypeSafe AI System One)** alongside the mathematical **Joint Efficiency-Value (JEV)** objective function:

$$\text{JEV}(a_t, s_t) = V(a_t) - \lambda \cdot C(a_t) - \mu \cdot L(a_t) + \gamma \cdot E(s_{t+1})$$

```text
Target Workflow / Prompt / Execution Graph
                    |
                    v
    +-------------------------------+
    | STAGE 1: JEV SYSTEM ONE GATE  |
    | - Noul: should_optimize?      |
    | - Score: expected_delta_jev   |
    | - Choice: select_strategy     |
    +-------------------------------+
                    |
    +---------------+---------------+
    |                               |
[Noul: false (Optimal)]     [Noul: true (Bottlenecked)]
    |                               |
    v                               v
[Preserve Baseline]       +------------------------------------+
                          | STAGE 2: EXECUTE STRATEGY          |
                          | - AST Prompt Pruning               |
                          | - TaskGroup Parallel Fan-Out       |
                          | - Semantic Cache Priming           |
                          +------------------------------------+
                                            |
                                            v
                          +------------------------------------+
                          | STAGE 3: EMPIRICAL VERIFICATION    |
                          | Verify Delta JEV > 0 & Tests Pass  |
                          +------------------------------------+
```

---

## 2. JEV System One Primitives in Optimizer

Optimizer interrogates Jev using three native System One question types in a single round-trip HTTP request (`POST /v1/systemone`):

| Primitive | Question ID | Question Type & Intent | Expected Output Shape |
|---|---|---|---|
| **`Noul`** | `should_optimize` | Fast binary check whether the bottleneck warrants graph mutation or compression. | `{"value": true/false, "confidence": float}` |
| **`Noul`** | `is_safe_to_mutate` | Ensures the proposed mutation does not break behavioral correctness or tests. | `{"value": true/false, "confidence": float}` |
| **`Score`** | `expected_delta_jev` | Predicted improvement in Joint Efficiency-Value $[0.0, 1.0]$. | `{"value": float, "confidence": float}` |
| **`Score`** | `token_reduction_ratio` | Predicted fraction of prompt tokens saved by AST compression $[0.0, 1.0]$. | `{"value": float, "confidence": float}` |
| **`Score`** | `latency_speedup_ratio` | Predicted wall-clock latency reduction ratio $[0.0, 1.0]$. | `{"value": float, "confidence": float}` |
| **`Choice`** | `select_strategy` | Strategy selection: `AST_PROMPT_PRUNING`, `PARALLEL_TASKGROUP_FANOUT`, `SEMANTIC_CACHE_INSERTION`, `ASYNCIO_THREAD_OFFLOAD`, `NO_OP_PRESERVE`. | `{"choice": str, "probabilities": dict}` |

---

## 3. Mathematical JEV Parameter Matrix

When evaluating concrete token/latency metrics, Optimizer applies these effort-calibrated weights:

| Effort Level | Value Weight ($V$) | Cost Penalty ($\lambda$) | Latency Penalty ($\mu$) | Exploration ($\gamma$) | Optimization Objective |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **LOW** | $1.0$ | $0.40$ | $0.40$ | $0.05$ | Maximize throughput & minimum token cost |
| **MEDIUM** | $1.0$ | $0.25$ | $0.25$ | $0.10$ | Balanced latency/quality trade-off |
| **HIGH** | $1.0$ | $0.10$ | $0.20$ | $0.15$ | Maximum accuracy with acceptable latency |

---

## 4. Python Implementation: JEV Optimization Driver

```python
"""Optimizer Agent JEV System One Integration Driver."""

from __future__ import annotations

import json
import logging
import urllib.request
import urllib.error
from typing import Any
from pathlib import Path

from swarm_sdk.vault import get_secret

logger = logging.getLogger("Optimizer.JEV")

SYSTEMONE_URL = "https://api.typesafe.ai/v1/systemone"
DEFAULT_MODEL = "jev-latest"
TIMEOUT_S = 3.0

def build_optimizer_jev_payload(state_summary: str, target_component: str) -> dict[str, Any]:
    """Construct the System One payload to evaluate optimization opportunity."""
    return {
        "state": f"Target Component: {target_component}\nExecution Telemetry:\n{state_summary}",
        "model": DEFAULT_MODEL,
        "questions": {
            "should_optimize": {
                "type": "noul",
                "question": "Is this execution path bottlenecked enough to warrant graph mutation or prompt compression?"
            },
            "is_safe_to_mutate": {
                "type": "noul",
                "question": "Can this component be modified without breaking public interfaces or behavioral invariants?"
            },
            "expected_delta_jev": {
                "type": "score",
                "question": "Rate the predicted improvement in Joint Efficiency-Value (0.0 = zero gain or degradation, 1.0 = massive improvement)."
            },
            "token_reduction_ratio": {
                "type": "score",
                "question": "Estimate the expected token savings ratio (0.0 = no savings, 1.0 = 90%+ tokens pruned)."
            },
            "latency_speedup_ratio": {
                "type": "score",
                "question": "Estimate the expected execution speedup ratio (0.0 = no change, 1.0 = 5x+ speedup)."
            },
            "select_strategy": {
                "type": "choice",
                "question": "Which optimization strategy yields the highest Delta JEV?",
                "options": [
                    "AST_PROMPT_PRUNING",
                    "PARALLEL_TASKGROUP_FANOUT",
                    "SEMANTIC_CACHE_INSERTION",
                    "ASYNCIO_THREAD_OFFLOAD",
                    "NO_OP_PRESERVE"
                ]
            }
        }
    }

def call_optimizer_jev_gate(state_summary: str, target_component: str) -> dict[str, Any]:
    """Execute JEV System One evaluation for the Optimizer agent."""
    api_key = get_secret("JEV_API_KEY")
    if not api_key:
        logger.warning("JEV_API_KEY not configured. Falling back to local heuristic optimization.")
        return {"status": "abstained", "reason": "missing_api_key"}

    payload = build_optimizer_jev_payload(state_summary, target_component)
    data = json.dumps(payload).encode("utf-8")

    req = urllib.request.Request(
        SYSTEMONE_URL,
        data=data,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        },
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            logger.info("JEV optimization advice successfully received for %s", target_component)
            return {"status": "success", "results": body.get("answers", {})}
    except urllib.error.HTTPError as e:
        logger.error("JEV System One HTTP %d: %s", e.code, e.reason)
        return {"status": "error", "code": e.code, "reason": str(e)}
    except Exception as e:
        logger.error("JEV transport failure: %s", str(e))
        return {"status": "error", "reason": str(e)}
```

---

## 5. Security & Vault Invariants

- **Credential Dynamic Lookup**: `JEV_API_KEY` is loaded securely via `swarm_sdk.vault` from the macOS Keychain (`swarm/JEV_API_KEY`) or 1Password. Never commit, log, or hardcode API keys.
- **Rollback Guarantee**: Any mutation that fails tests or produces $\Delta\text{JEV} \le 0$ is reverted immediately.
