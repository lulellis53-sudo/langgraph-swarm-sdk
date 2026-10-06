"""Symbolic and numerical definitions of the formulas used across the SDK.

This module is intentionally lazy: sympy objects are created only when a
helper is called, so import time stays fast for production code that does not
need symbolic math.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

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
    return math.log(1.0 + (n_docs - df + 0.5) / (df + 0.5))


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

    Zero vectors are handled by returning ``0.0``. Uses ``math.fsum`` for
    improved precision on long vectors.
    """
    dot = math.fsum(float(ui) * float(vi) for ui, vi in zip(u, v, strict=True))
    norm_u = math.sqrt(math.fsum(float(ui) ** 2 for ui in u))
    norm_v = math.sqrt(math.fsum(float(vi) ** 2 for vi in v))
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

    Uses ``math.fsum`` for improved precision on long vectors.
    """
    if not scores:
        return []
    max_score = max(scores)
    exps = [math.exp(float(s) - max_score) for s in scores]
    total = math.fsum(exps)
    return [e / total for e in exps]


def cosine_similarity_arrow(u: Sequence[float], v: Sequence[float]) -> float:
    r"""Cosine similarity of two vectors using PyArrow compute.

    .. math::
        \operatorname{cos}(u, v) =
            \frac{u \cdot v}{\|u\|_2 \cdot \|v\|_2}

    This is the PyArrow-accelerated variant of :func:`cosine_similarity`.
    It requires the ``arrow`` optional extra (``pyarrow``). Zero vectors
    return ``0.0``.
    """
    import pyarrow as pa
    import pyarrow.compute as pc

    a = pa.array(u, type=pa.float64())
    b = pa.array(v, type=pa.float64())
    dot = float(pc.sum(pc.multiply(a, b)).as_py())
    norm_u = float(pc.sqrt(pc.sum(pc.power(a, pa.scalar(2)))).as_py())
    norm_v = float(pc.sqrt(pc.sum(pc.power(b, pa.scalar(2)))).as_py())
    if norm_u == 0.0 or norm_v == 0.0:
        return 0.0
    return dot / (norm_u * norm_v)


def l2_norm_arrow(vector: Sequence[float]) -> float:
    r"""Euclidean (L2) norm using PyArrow compute.

    .. math::
        \|x\|_2 = \sqrt{\sum_i x_i^2}

    Requires the ``arrow`` optional extra (``pyarrow``).
    """
    import pyarrow as pa
    import pyarrow.compute as pc

    arr = pa.array(vector, type=pa.float64())
    return float(pc.sqrt(pc.sum(pc.power(arr, pa.scalar(2)))).as_py())


def softmax_scores_arrow(scores: Sequence[float]) -> list[float]:
    r"""Numerically stable softmax using PyArrow compute.

    .. math::
        p_i = \frac{e^{s_i - \max_j s_j}}{\sum_j e^{s_j - \max_j s_j}}

    Requires the ``arrow`` optional extra (``pyarrow``). Returns an empty
    list for empty input.
    """
    import pyarrow as pa
    import pyarrow.compute as pc

    if not scores:
        return []
    arr = pa.array(scores, type=pa.float64())
    max_score = pc.max(arr)
    shifted = pc.subtract(arr, max_score)
    exps = pc.exp(shifted)
    total = pc.sum(exps)
    return [float(x) for x in pc.divide(exps, total).to_pylist()]


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

    Uses ``math.fsum`` for improved precision on long vectors.
    """
    return math.sqrt(math.fsum(float(xi) ** 2 for xi in vector))


def keyword_overlap_score(query_terms: set[str], doc_terms: set[str]) -> float:
    r"""Normalized lexical overlap between two token sets.

    .. math::
        \operatorname{overlap}(Q, D) = \frac{|Q \cap D|}{\max(|Q|, |D|)}

    Returns ``0.0`` when either set is empty, avoiding division by zero.
    """
    if not query_terms or not doc_terms:
        return 0.0
    intersection = query_terms & doc_terms
    denominator = max(len(query_terms), len(doc_terms))
    return len(intersection) / denominator


def bm25_keyword_rerank_score(
    query: str,
    document: str,
    *,
    k1: float = 1.2,
    b: float = 0.75,
) -> float:
    r"""BM25-style lexical score for reranking a single document against a query.

    The corpus is treated as the single document being scored, so document
    frequency is derived from the document itself and IDF collapses to a
    constant. The formula reduces to the term-saturation component:

    .. math::
        \operatorname{score}(Q, D) = \sum_{t \in Q \cap D}
            \frac{\operatorname{tf}(t, D) \cdot (k_1 + 1)}
                 {\operatorname{tf}(t, D) + k_1 \cdot
                  \left(1 - b + b \cdot \frac{|D|}{\operatorname{avgdl}}\right)}

    where ``avgdl`` is taken as ``|D|`` so length normalization disappears.
    """
    from collections import Counter

    q_terms = query.lower().split()
    d_terms = document.lower().split()
    if not q_terms or not d_terms:
        return 0.0
    q_counts = Counter(q_terms)
    d_counts = Counter(d_terms)
    doc_len = len(d_terms)
    avgdl = doc_len
    score = 0.0
    for term in q_counts:
        tf = d_counts.get(term, 0)
        if tf == 0:
            continue
        denominator = tf + k1 * (1.0 - b + b * doc_len / avgdl)
        score += tf * (k1 + 1.0) / denominator
    return score


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


def symbolic_int8_quantization() -> "sp.Eq":  # noqa: UP037
    """Return a SymPy equation object for symmetric INT8 quantization."""
    sp = _sympy()
    x, scale = sp.symbols("x scale", real=True)
    q = sp.Max(-127, sp.Min(127, sp.round(x / scale)))
    return sp.Eq(sp.IndexedBase("q")[x], q)


def verify_cosine_symbolic() -> bool:
    """Use SymPy to verify :func:`cosine_similarity` matches its definition.

    Returns ``True`` when the numerical implementation equals the symbolic
    cosine formula for random vectors. Intended for property tests and CI.
    """
    import random

    import numpy as np

    sp = _sympy()

    for _ in range(20):
        n = random.randint(2, 64)
        u = sp.MatrixSymbol("u", n, 1)
        v = sp.MatrixSymbol("v", n, 1)
        dot = (u.T * v)[0, 0]
        norm_u = sp.sqrt((u.T * u)[0, 0])
        norm_v = sp.sqrt((v.T * v)[0, 0])
        expr = dot / (norm_u * norm_v)
        numeric = sp.lambdify((u, v), expr, modules="numpy")
        a = [random.uniform(-1.0, 1.0) for _ in range(n)]
        b = [random.uniform(-1.0, 1.0) for _ in range(n)]
        expected = float(numeric(np.array(a).reshape(-1, 1), np.array(b).reshape(-1, 1)))
        got = cosine_similarity(a, b)
        if not math.isclose(got, expected, rel_tol=1e-12, abs_tol=1e-12):
            return False
    return True


def verify_bm25_term_symbolic(*, k1: float = 1.2, b: float = 0.75) -> bool:
    """Use SymPy to verify the scalar BM25 term score matches its definition.

    Returns ``True`` when the numerical implementation equals the symbolic
    formula for random positive inputs. This is intended for property tests
    and CI, not for hot-path runtime use.
    """
    sp = _sympy()
    tf, doc_len, avgdl, idf = sp.symbols(
        "tf doc_len avgdl idf", positive=True, real=True
    )
    k1s, bs = sp.symbols("k1 b", positive=True, real=True)
    symbolic = idf * (tf * (k1s + 1)) / (
        tf + k1s * (1 - bs + bs * doc_len / avgdl)
    )
    numeric = sp.lambdify(
        (tf, doc_len, avgdl, idf, k1s, bs),
        symbolic,
        modules="math",
    )
    import random

    for _ in range(20):
        vals = {
            "tf": math.floor(1 + 10 * random.random()),
            "doc_len": math.floor(1 + 100 * random.random()),
            "avgdl": 1 + 100 * random.random(),
            "idf": random.random() * 5,
        }
        expected = numeric(
            vals["tf"], vals["doc_len"], vals["avgdl"], vals["idf"], k1, b
        )
        got = bm25_term_score(
            int(vals["tf"]),
            int(vals["doc_len"]),
            float(vals["avgdl"]),
            float(vals["idf"]),
            k1=k1,
            b=b,
        )
        if not math.isclose(got, expected, rel_tol=1e-12):
            return False
    return True


__all__ = [
    "bm25_idf",
    "bm25_keyword_rerank_score",
    "bm25_score",
    "bm25_term_score",
    "binary_cosine_estimate",
    "binary_score_to_cosine",
    "cosine_similarity",
    "cosine_similarity_arrow",
    "int8_quantize",
    "int8_scale",
    "keyword_overlap_score",
    "l2_norm",
    "l2_norm_arrow",
    "rrf_score",
    "softmax_scores",
    "softmax_scores_arrow",
    "symbolic_bm25",
    "symbolic_cosine",
    "symbolic_int8_quantization",
    "symbolic_rrf",
    "symbolic_softmax",
    "verify_bm25_term_symbolic",
    "verify_cosine_symbolic",
]
