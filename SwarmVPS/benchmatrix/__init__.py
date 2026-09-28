"""Cross-language SDK matrix benchmark: LangGraph (PY) vs Rig (RS).

One leg per language/SDK pair. Each leg is registered in ``LEGS`` with a
runner callable that returns a ``LegResult``; ``run_matrix`` executes every
leg, never failing the matrix because one leg skipped (or errored), and
renders a markdown table plus a JSON artifact.

The matrix is offline by construction: the Python leg drives the bench
suite with scripted chat (no live LLM), and the Rust leg drives a typed
rig-core agent loop against an in-process deterministic ``CompletionModel``
stub (zero network). Mastra (JS/TS) was removed by decision — LangGraph
only.
"""

from __future__ import annotations

from benchmatrix.harness import LEGS, Leg, LegResult, MatrixResult, get_leg, run_matrix

__all__ = ["LEGS", "Leg", "LegResult", "MatrixResult", "get_leg", "run_matrix"]
