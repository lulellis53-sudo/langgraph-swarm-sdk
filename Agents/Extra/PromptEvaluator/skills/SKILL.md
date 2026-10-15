# PromptEvaluator Skill: Enterprise G-Eval Engine

> **Scope**: G-Eval rubric definitions, Chain-of-Thought scoring patterns, and hallucination audit pipelines.

---

## 1. G-Eval Scoring Rubric Pattern

```python
from pydantic import BaseModel, Field

class GEvalCriteria(BaseModel):
    relevance: float = Field(..., ge=1.0, le=5.0, description="Relevance to user prompt")
    factual_accuracy: float = Field(..., ge=1.0, le=5.0, description="Factual accuracy score")
    instruction_following: float = Field(..., ge=1.0, le=5.0, description="Fidelity to system constraints")
    coherence: float = Field(..., ge=1.0, le=5.0, description="Logical flow and coherence")

def calculate_g_eval_score(criteria: GEvalCriteria) -> float:
    """Compute weighted normalized G-Eval score [0.0, 1.0]."""
    weights = {"relevance": 0.25, "factual_accuracy": 0.35, "instruction_following": 0.25, "coherence": 0.15}
    total = (
        criteria.relevance * weights["relevance"] +
        criteria.factual_accuracy * weights["factual_accuracy"] +
        criteria.instruction_following * weights["instruction_following"] +
        criteria.coherence * weights["coherence"]
    )
    return total / 5.0
```

---

## 2. Hallucination Detection Pipeline

1. **Source Context Parsing**: Split grounding context into verifiable factual assertions.
2. **Output Claim Extraction**: Extract atomic claims from the generated response.
3. **Entailment Verification**: Verify each atomic claim against source context assertions; flag ungrounded claims as hallucinations.


---

## 3. DataDriftDetector: Statistical & Concept Drift Engine

### 3.1 Population Stability Index (PSI) Calculation
$$\text{PSI} = \sum \left( (P_{\text{actual}} - P_{\text{baseline}}) \times \ln\left(\frac{P_{\text{actual}}}{P_{\text{baseline}}}\right) \right)$$
- $\text{PSI} < 0.1$: No significant drift (Baseline stable).
- $0.1 \le \text{PSI} < 0.25$: Moderate drift (Warning threshold).
- $\text{PSI} \ge 0.25$: Severe drift (Trigger prompt/model retraining alert).

```python
import numpy as np

def calculate_psi(baseline: np.ndarray, actual: np.ndarray, num_bins: int = 10) -> float:
    """Calculate Population Stability Index between baseline and actual distributions."""
    counts_base, bin_edges = np.histogram(baseline, bins=num_bins)
    counts_actual, _ = np.histogram(actual, bins=bin_edges)

    p_base = counts_base / len(baseline) + 1e-4
    p_actual = counts_actual / len(actual) + 1e-4

    psi_val = np.sum((p_actual - p_base) * np.log(p_actual / p_base))
    return float(psi_val)
```

### 3.2 Kolmogorov-Smirnov (KS) Drift Test
Runs two-sample KS test to compare incoming embedding vector distributions against historical baselines:
$$\text{KS\_stat} = \sup_x |F_{\text{actual}}(x) - F_{\text{baseline}}(x)|$$
Triggers `retraining_alerting` when $p$-value $< 0.05$.
