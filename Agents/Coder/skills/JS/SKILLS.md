# Judge Agent Skills: JEV System One Evaluation & Quality Gate

> **Authoritative Specification**: JEV System One Integration for the Judge Evaluation Agent (`Agents/Judge`)
> **Model Target**: TypeSafe AI Jev (`jev-latest`, `POST https://api.typesafe.ai/v1/systemone`)
> **Ecosystem**: Swarm SDK Multi-Agent Quality Gating & Antigravity Subagent Evaluation

---

## 1. Overview & Architectural Role

The **Judge** agent acts as the supreme quality gate within the Swarm ecosystem. Rather than relying solely on subjective, non-deterministic generative LLM evaluations, Judge incorporates **Jev (TypeSafe AI System One)** to obtain calibrated, structured, and reproducible decision telemetry.

### The Two-Stage Evaluation Pipeline
```text
Target Evaluation State (Diff, Research Dossier, Benchmark Metrics)
                               |
                               v
               +-------------------------------+
               | STAGE 0: JEV SYSTEM ONE GATE  |
               | - Noul: Mechanical Pass/Fail  |
               | - Score: 100-Point Rubric     |
               | - Choice: Discrete Verdict    |
               +-------------------------------+
                               |
                +--------------+--------------+
                |                             |
          [Noul Rejected]              [Noul Approved]
                |                             |
                v                             v
       +------------------+         +--------------------+
       | Fast Exit (0/100)|         | STAGE 1: CLAIM &   |
       | Mechanical Fail  |         | BENCHMARK AUDIT    |
       +------------------+         | (Evidence Ledger)  |
                                    +--------------------+
                                              |
                                              v
                                    [ FINAL JSON SCORECARD ]
```

---

## 2. JEV System One Primitives in Judge

Judge interrogates Jev using three native System One question types in a single round-trip HTTP request:

| Primitive | Question ID | Question Type & Intent | Expected Output Shape |
|---|---|---|---|
| **`Noul`** | `passes_mechanical_gate` | Binary safety & syntax check (syntax error 0, zero secret leakage, valid types). | `{"value": true/false, "confidence": float}` |
| **`Noul`** | `is_sandbox_compliant` | Verifies execution adhered to workspace boundaries without modifying protected files. | `{"value": true/false, "confidence": float}` |
| **`Score`** | `rubric_correctness` | Functional completeness and adherence to user acceptance criteria. | `{"value": 0.0 - 1.0, "confidence": float}` |
| **`Score`** | `rubric_security` | Absence of security regressions, shell injections, or plaintext API keys. | `{"value": 0.0 - 1.0, "confidence": float}` |
| **`Score`** | `rubric_performance` | Resource efficiency, low token churn, runtime latency delta ($\Delta\%$). | `{"value": 0.0 - 1.0, "confidence": float}` |
| **`Score`** | `rubric_maintainability` | Adherence to Google Style Guidelines, clean docstrings, typing precision. | `{"value": 0.0 - 1.0, "confidence": float}` |
| **`Choice`** | `evaluation_verdict` | Categorical decision among: `APPROVED`, `APPROVED_WITH_NOTES`, `NEEDS_REVISION`, `REJECTED`. | `{"choice": str, "probabilities": dict}` |

---

## 3. Python Integration & Execution Recipe

Judge uses `swarm_sdk.vault` to resolve credentials and calls the System One endpoint via the following standardized routine:

```python
"""Judge Agent JEV System One evaluation routine."""

from __future__ import annotations

import json
import logging
import urllib.request
import urllib.error
from typing import Any
from pathlib import Path

from swarm_sdk.vault import get_secret

logger = logging.getLogger("Judge.JEV")

SYSTEMONE_URL = "https://api.typesafe.ai/v1/systemone"
DEFAULT_MODEL = "jev-latest"
TIMEOUT_S = 3.0

def build_judge_jev_payload(state_summary: str, target_name: str) -> dict[str, Any]:
    """Construct the System One payload with Noul, Score, and Choice questions."""
    return {
        "state": f"Target: {target_name}\n\n{state_summary}",
        "model": DEFAULT_MODEL,
        "questions": {
            "passes_mechanical_gate": {
                "type": "noul",
                "question": "Does this implementation or research pass mechanical baseline checks without syntax errors, secret leaks, or crashes?"
            },
            "is_sandbox_compliant": {
                "type": "noul",
                "question": "Did this work strictly respect workspace boundaries and avoid altering protected host state?"
            },
            "rubric_correctness": {
                "type": "score",
                "question": "Rate the functional correctness and completeness of the solution (0.0 = completely broken, 1.0 = fully correct and tested)."
            },
            "rubric_security": {
                "type": "score",
                "question": "Rate the security posture of the solution (0.0 = severe secret leak/injection vulnerability, 1.0 = fully defended)."
            },
            "rubric_performance": {
                "type": "score",
                "question": "Rate the computational and token efficiency (0.0 = severe regression, 1.0 = optimal low-latency)."
            },
            "rubric_maintainability": {
                "type": "score",
                "question": "Rate the clean code quality, type annotations, and documentation depth (0.0 = unmaintainable, 1.0 = publication-grade)."
            },
            "evaluation_verdict": {
                "type": "choice",
                "question": "What is the final decision verdict for this candidate?",
                "options": [
                    "APPROVED",
                    "APPROVED_WITH_NOTES",
                    "NEEDS_REVISION",
                    "REJECTED"
                ]
            }
        }
    }

def call_jev_quality_gate(state_summary: str, target_name: str) -> dict[str, Any]:
    """Execute System One JEV evaluation for the Judge agent.
    
    Returns:
        Structured evaluation dict with answers and confidence metrics.
    """
    api_key = get_secret("JEV_API_KEY")
    if not api_key:
        logger.warning("JEV_API_KEY not configured in Keychain. Abstaining from JEV gate.")
        return {"status": "abstained", "reason": "missing_api_key"}

    payload = build_judge_jev_payload(state_summary, target_name)
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
            logger.info("JEV evaluation successfully received for %s", target_name)
            return {"status": "success", "results": body.get("answers", {})}
    except urllib.error.HTTPError as e:
        logger.error("JEV System One HTTP %d: %s", e.code, e.reason)
        return {"status": "error", "code": e.code, "reason": str(e)}
    except Exception as e:
        logger.error("JEV transport failure: %s", str(e))
        return {"status": "error", "reason": str(e)}
```

---

## 4. Scorecard Synthesis & Weighting

When Jev returns scores, Judge synthesizes the final 100-point composite score:

$$\text{Composite Score} = 100 \times \left( 0.40 \cdot S_{\text{correctness}} + 0.30 \cdot S_{\text{security}} + 0.15 \cdot S_{\text{performance}} + 0.15 \cdot S_{\text{maintainability}} \right)$$

### Decision Thresholds
- **$\ge 85/100$**: `APPROVED`
- **$70 - 84/100$**: `APPROVED_WITH_NOTES`
- **$50 - 69/100$**: `NEEDS_REVISION`
- **$< 50/100$ or `passes_mechanical_gate == false`**: `REJECTED` (Immediate stop)

---

## 5. Security & Vault Invariants

1. **Zero Secret Leakage**: `JEV_API_KEY` is loaded dynamically from macOS Keychain (`swarm/JEV_API_KEY`) or 1Password. It must never be printed to stdout, logged in telemetry, or serialized in `Scorecard` JSON payloads.
2. **Deterministic Abstention**: If Jev is unreachable or times out (>3.0s), Judge logs an abstention notice and falls back to deterministic local rule engines (`pytest`, `ruff`, `mypy`, `git diff --check`).

---

## 6. Swarm-Wide Agent Benchmarking: `BenchmarkAllAgents`

For comprehensive, swarm-wide evaluation across all 45 agents, see the dedicated skill specification in [`skills/Benchmarkallagents/SKILL.md`](skills/Benchmarkallagents/SKILL.md).

### Core Capabilities
1. **Before & After State Tracking**: Captures immutable performance, token, memory, and correctness baselines before and after code/prompt mutations.
2. **Advanced RAG Retrieval**: Employs hybrid dense (`FastEmbed` / `OpenClVecStore`) + sparse (BM25) search, parent-child chunking, and Self-RAG reflection tokens over historical benchmark runs.
3. **Self-Learning Improvement % ($\Delta\%$)**: Calculates fine-grained deltas and updates the continuous Experience Buffer (`experience_buffer.jsonl`) to track agent evolution over time.
4. **JEV System One Gating**: Submits before/after comparative deltas to Jev's `Noul` and `Score` primitives to prevent regressions.

