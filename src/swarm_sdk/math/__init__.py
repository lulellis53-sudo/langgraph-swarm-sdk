"""Symbolic and numerical definitions of the formulas used across the SDK.

This module is intentionally lazy: sympy objects are created only when a
helper is called, so import time stays fast for production code that does not
need symbolic math.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from swarm_sdk.math.dispatch import classify_math_task
from swarm_sdk.math.types import (
    MathBackend,
    MathDispatchDecision,
    MathMode,
    MathProblem,
    MathResult,
    MathTaskType,
    ThinkLevel,
    VerificationResult,
)
from swarm_sdk.math.verify import verify_math_solution

if TYPE_CHECKING:
    from collections.abc import Sequence

    import sympy as sp


def _sympy() -> Any:
    import sympy as sp

    return sp


def bm25_idf(n_docs: int, df: int) -> float:
    r"""Canonical BM25 IDF with the Robertson/Sparck Jones formulation.

    .. math::
        \operatorname{idf}(t) = \ln\!\left(
            1 + \frac{N - \operatorname{df}(t) + 0.5}{\operatorname{df}(t) + 0.5}
        \right)

    The ``+1`` inside the logarithm prevents ``log(0)`` for any valid
    ``df ∈ [1, N]``.
    """
    from math import log

    return log(1.0 + (n_docs - df + 0.5) / (df + 0.5))


def bm25_term_score(
    tf: int,
    doc_len: int,
    avgdl: float,
    idf: float,
    *,
    k1: float = 1.2,
    b: float = 0.75,
) -> float:
    r"""BM25 term score for a single query term.

    .. math::
        \operatorname{score}(t, D) = \operatorname{idf}(t) \cdot
        \frac{\operatorname{tf}(t, D) \cdot (k_1 + 1)}
             {\operatorname{tf}(t, D) + k_1 \cdot
              \left(1 - b + b \cdot \frac{|D|}{\operatorname{avgdl}}\right)}
    """
    denominator = tf + k1 * (1.0 - b + b * doc_len / avgdl)
    return idf * tf * (k1 + 1.0) / denominator


def bm25_score(
    query_terms: Sequence[str],
    doc_terms: Sequence[str],
    *,
    n_docs: int,
    df_map: dict[str, int] | None = None,
    k1: float = 1.2,
    b: float = 0.75,
    avgdl: float | None = None,
) -> float:
    """Full BM25 score of ``doc_terms`` against ``query_terms``.

    Args:
        query_terms: Query tokens.
        doc_terms: Document tokens.
        n_docs: Total number of documents in the corpus.
        df_map: Document-frequency map for each query term. If ``None``,
            ``df`` is derived from ``doc_terms`` (useful for single-doc checks).
        k1: Term saturation parameter.
        b: Length normalization parameter.
        avgdl: Average document length. If ``None``, computed from ``doc_terms``.

    Returns:
        The BM25 score as a float.
    """
    from collections import Counter

    q_counts = Counter(query_terms)
    tf_counts = Counter(doc_terms)
    doc_len = len(doc_terms)
    avgdl = avgdl if avgdl is not None else doc_len
    if avgdl == 0:
        return 0.0

    df_map = df_map or {term: 1 for term in q_counts}
    score = 0.0
    for term, q_count in q_counts.items():
        if q_count == 0 or term not in tf_counts:
            continue
        df = df_map.get(term, 1)
        idf = bm25_idf(n_docs, max(1, min(df, n_docs)))
        # Match the implementation in swarm_sdk.retrieval.hybrid, which scores
        # each distinct query term once regardless of its query frequency.
        score += bm25_term_score(tf_counts[term], doc_len, avgdl, idf, k1=k1, b=b)
    return score


def cosine_similarity(u: Sequence[float], v: Sequence[float]) -> float:
    r"""Cosine similarity of two vectors.

    .. math::
        \operatorname{cos}(u, v) =
            \frac{u \cdot v}{\|u\|_2 \cdot \|v\|_2}

    Zero vectors are handled by returning ``0.0``.
    """
    import math

    dot = sum(float(ui) * float(vi) for ui, vi in zip(u, v, strict=True))
    norm_u = math.sqrt(sum(float(ui) ** 2 for ui in u))
    norm_v = math.sqrt(sum(float(vi) ** 2 for vi in v))
    if norm_u == 0.0 or norm_v == 0.0:
        return 0.0
    return dot / (norm_u * norm_v)


def rrf_score(rank: int, k: int = 60) -> float:
    r"""Reciprocal rank fusion score for a 0-based rank.

    .. math::
        \operatorname{RRF}(r) = \frac{1}{k + r + 1}
    """
    return 1.0 / (k + rank + 1)


def softmax_scores(scores: Sequence[float]) -> list[float]:
    r"""Numerically stable softmax over a 1-D score vector.

    .. math::
        p_i = \frac{e^{s_i - \max_j s_j}}{\sum_j e^{s_j - \max_j s_j}}
    """
    import math

    if not scores:
        return []
    max_score = max(scores)
    exps = [math.exp(float(s) - max_score) for s in scores]
    total = sum(exps)
    return [e / total for e in exps]


def int8_scale(peak: float) -> float:
    r"""Symmetric per-row INT8 scale.

    .. math::
        \operatorname{scale} = \frac{\max(|x|)}{127}

    When ``peak == 0`` the scale is defined as ``1.0`` to avoid division by
    zero during quantization.
    """
    return peak / 127.0 if peak > 0.0 else 1.0


def int8_quantize(value: float, scale: float) -> int:
    r"""Quantize a single float to symmetric INT8.

    Uses round-half-to-even to match NumPy's ``rint``:

    .. math::
        q = \operatorname{clip}\!\left(\operatorname{rint}\!
            \left(\frac{x}{\operatorname{scale}}\right), -127, 127\right)
    """
    if scale == 0.0:
        return 0
    # Python ``round`` implements banker's rounding, matching ``np.rint``.
    rounded = round(float(value) / scale)
    return int(max(-127, min(127, rounded)))


def binary_cosine_estimate(hamming_distance: int, dim: int) -> float:
    r"""Estimate cosine similarity from Hamming distance of sign-quantized vectors.

    Sign quantization maps each dimension to :math:`\pm 1`. The expected cosine
    between two random unit vectors with a given Hamming distance is modeled as

    .. math::
        \hat{c} = \cos\!\left(\pi \cdot \frac{d_H}{\dim}\right)

    where :math:`d_H` is the Hamming distance. This maps
    :math:`d_H = 0 \to 1` and :math:`d_H = \dim \to -1`.
    """
    import math

    if dim <= 0:
        return 0.0
    return math.cos(math.pi * hamming_distance / dim)


def binary_score_to_cosine(score: float, dim: int) -> float:
    """Convert a ``dim - hamming_distance`` binary score back to cosine estimate.

    This is the inverse of the binary dot mapping used in the OpenCL kernel:
    ``score = dim - hamming_distance``.
    """
    return binary_cosine_estimate(int(dim - score), dim)


def l2_norm(vector: Sequence[float]) -> float:
    r"""Euclidean (L2) norm of a vector.

    .. math::
        \|x\|_2 = \sqrt{\sum_i x_i^2}
    """
    import math

    return math.sqrt(sum(float(xi) ** 2 for xi in vector))


def symbolic_bm25() -> "sp.Eq":  # noqa: UP037
    """Return a SymPy equation object for the full BM25 score."""
    sp = _sympy()
    t, tf, doc_len, avgdl, k1, b, n_docs, df = sp.symbols(
        "t tf doc_len avgdl k1 b N df", positive=True, real=True
    )
    idf = sp.log(1 + (n_docs - df + sp.Rational(1, 2)) / (df + sp.Rational(1, 2)))
    score = idf * (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * doc_len / avgdl))
    return sp.Eq(sp.Function("BM25")(t, tf, doc_len), score)


def symbolic_rrf() -> "sp.Eq":  # noqa: UP037
    """Return a SymPy equation object for RRF."""
    sp = _sympy()
    r, k = sp.symbols("r k", positive=True, integer=True)
    return sp.Eq(sp.Function("RRF")(r), 1 / (k + r + 1))


def symbolic_softmax() -> "sp.Eq":  # noqa: UP037
    """Return a SymPy equation object for softmax."""
    sp = _sympy()
    i, j = sp.symbols("i j", integer=True)
    s = sp.IndexedBase("s")
    max_s = sp.Function("max")
    expr = sp.exp(s[i] - max_s(s[j])) / sp.Sum(
        sp.exp(s[j] - max_s(s[j])), (j, 0, sp.Symbol("N", integer=True, positive=True))
    )
    return sp.Eq(sp.IndexedBase("p")[i], expr)


def symbolic_cosine() -> "sp.Eq":  # noqa: UP037
    """Return a SymPy equation object for cosine similarity."""
    sp = _sympy()
    n = sp.Symbol("n", integer=True, positive=True)
    i = sp.Symbol("i", integer=True, nonnegative=True)
    u = sp.IndexedBase("u")
    v = sp.IndexedBase("v")
    dot = sp.Sum(u[i] * v[i], (i, 0, n - 1))
    norm_u = sp.sqrt(sp.Sum(u[i] ** 2, (i, 0, n - 1)))
    norm_v = sp.sqrt(sp.Sum(v[i] ** 2, (i, 0, n - 1)))
    return sp.Eq(sp.Function("cos")(u, v), dot / (norm_u * norm_v))


__all__ = [
    "MathBackend",
    "MathDispatchDecision",
    "MathMode",
    "MathProblem",
    "MathResult",
    "MathTaskType",
    "ThinkLevel",
    "VerificationResult",
    "bm25_idf",
    "classify_math_task",
    "bm25_score",
    "bm25_term_score",
    "binary_cosine_estimate",
    "binary_score_to_cosine",
    "cosine_similarity",
    "int8_quantize",
    "int8_scale",
    "l2_norm",
    "rrf_score",
    "softmax_scores",
    "symbolic_bm25",
    "symbolic_cosine",
    "symbolic_rrf",
    "symbolic_softmax",
    "verify_math_solution",
]
