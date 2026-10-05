"""Pillar 1: metric geometry, scalar quantization, HNSW, and product quantization."""

import heapq

import numpy as np

from algorithms.errors import AlgorithmInputError

__all__ = [
    "cosine_similarity",
    "euclidean_distance",
    "hamming_angular_cosine",
    "hnsw_greedy_search",
    "mips_lift",
    "sq8_encode_decode",
    "train_ivf_pq_codebooks",
]


def _vector(name: str, value: np.ndarray) -> np.ndarray:
    array = np.asarray(value, dtype=np.float64).reshape(-1)
    if array.size == 0:
        raise AlgorithmInputError(f"{name} is empty")
    return array


def euclidean_distance(left: np.ndarray, right: np.ndarray) -> float:
    """Return the Euclidean distance between two vectors."""
    u = _vector("left", left)
    v = _vector("right", right)
    if u.shape != v.shape:
        raise AlgorithmInputError("euclidean distance requires vectors of equal length")
    return float(np.linalg.norm(u - v))


def cosine_similarity(left: np.ndarray, right: np.ndarray) -> float:
    """Return the cosine similarity of two non-zero vectors."""
    u = _vector("left", left)
    v = _vector("right", right)
    if u.shape != v.shape:
        raise AlgorithmInputError("cosine similarity requires vectors of equal length")
    left_norm = float(np.linalg.norm(u))
    right_norm = float(np.linalg.norm(v))
    if left_norm == 0.0 or right_norm == 0.0:
        raise AlgorithmInputError("cosine similarity is undefined for a zero vector")
    return float(np.dot(u, v) / (left_norm * right_norm))


def mips_lift(vectors: np.ndarray, bound: float | None = None) -> np.ndarray:
    """Lift vectors so maximum inner product becomes Euclidean nearest neighbor.

    Args:
        vectors: Array of shape ``(n, d)``.
        bound: Radius ``M``. Defaults to the maximum row norm.

    Returns:
        Array of shape ``(n, d + 1)`` whose extra coordinate is
        ``sqrt(M^2 - ||u||^2)``.

    Raises:
        AlgorithmInputError: A row is longer than ``bound`` or the input is empty.
    """
    data = np.asarray(vectors, dtype=np.float64)
    if data.ndim != 2 or data.size == 0:
        raise AlgorithmInputError("MIPS lift requires a non-empty (n, d) array")
    norms = np.linalg.norm(data, axis=1)
    radius = float(np.max(norms) if bound is None else bound)
    if radius < 0.0 or np.any(norms > radius + 1e-12):
        raise AlgorithmInputError("MIPS bound is smaller than a vector norm")
    extra = np.sqrt(np.maximum(radius * radius - norms * norms, 0.0))
    return np.column_stack([data, extra])


def hamming_angular_cosine(left: np.ndarray, right: np.ndarray) -> float:
    """Map normalized Hamming distance of two sign codes to an angular cosine."""
    a = np.asarray(left).reshape(-1)
    b = np.asarray(right).reshape(-1)
    if a.shape != b.shape or a.size == 0:
        raise AlgorithmInputError("Hamming cosine requires equal non-empty codes")
    distance = int(np.count_nonzero(a != b))
    return float(np.cos(np.pi * distance / a.size))


def sq8_encode_decode(
    values: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, float, float]:
    """Quantize a sample to uint8 and reconstruct it on the same uniform grid.

    Returns:
        Codes, float32 reconstruction, range minimum, and bin width.
    """
    data = np.asarray(values, dtype=np.float64)
    if data.size == 0:
        raise AlgorithmInputError("SQ8 input is empty")
    if not np.all(np.isfinite(data)):
        raise AlgorithmInputError("SQ8 input must be finite")
    low = float(np.min(data))
    high = float(np.max(data))
    delta = (high - low) / 255.0 if high > low else 1.0
    codes = np.clip(np.round((data - low) / delta), 0, 255).astype(np.uint8)
    reconstructed = codes.astype(np.float32) * np.float32(delta) + np.float32(low)
    return codes, reconstructed, low, delta


def hnsw_greedy_search(
    query: np.ndarray,
    entry_node: int,
    graph: dict[int, list[int]],
    vectors: np.ndarray,
    ef_search: int = 16,
) -> list[tuple[float, int]]:
    """Search one HNSW layer with a greedy beam ordered by L2 distance.

    Args:
        query: Query vector.
        entry_node: Node where the search starts.
        graph: Adjacency lists for this layer.
        vectors: Row ``i`` is the vector stored at node ``i``.
        ef_search: Beam width.

    Returns:
        ``(distance, node)`` pairs, nearest first.
    """
    data = np.asarray(vectors, dtype=np.float64)
    if data.ndim != 2 or data.shape[0] == 0:
        raise AlgorithmInputError("HNSW vectors must have shape (n, d)")
    needle = np.asarray(query, dtype=np.float64).reshape(-1)
    if needle.shape != (data.shape[1],):
        raise AlgorithmInputError("HNSW query dimension does not match the vectors")
    if ef_search < 1:
        raise AlgorithmInputError("ef_search must be positive")
    if not 0 <= entry_node < data.shape[0]:
        raise AlgorithmInputError("HNSW entry node is outside the vector table")

    entry_dist = float(np.linalg.norm(data[entry_node] - needle))
    visited = {entry_node}
    candidates: list[tuple[float, int]] = [(entry_dist, entry_node)]
    best: list[tuple[float, int]] = [(-entry_dist, entry_node)]
    while candidates:
        current_dist, current = heapq.heappop(candidates)
        furthest = -best[0][0]
        if current_dist > furthest and len(best) >= ef_search:
            break
        for neighbor in graph.get(current, []):
            if neighbor in visited:
                continue
            if not 0 <= neighbor < data.shape[0]:
                raise AlgorithmInputError(f"HNSW neighbor {neighbor} is outside the table")
            visited.add(neighbor)
            dist = float(np.linalg.norm(data[neighbor] - needle))
            if dist < furthest or len(best) < ef_search:
                heapq.heappush(candidates, (dist, neighbor))
                heapq.heappush(best, (-dist, neighbor))
                if len(best) > ef_search:
                    heapq.heappop(best)
    return sorted((-neg_dist, node) for neg_dist, node in best)


def train_ivf_pq_codebooks(
    data: np.ndarray,
    m_subspaces: int = 8,
    k_centroids: int = 256,
    *,
    iterations: int = 10,
    rng: np.random.Generator | None = None,
) -> np.ndarray:
    """Train product-quantization centroids on ``m`` orthogonal subspaces.

    Args:
        data: Training rows of shape ``(n, d)``. ``d`` must divide ``m_subspaces``.
        m_subspaces: Number of subspaces.
        k_centroids: Centroids in each subspace.
        iterations: Lloyd iterations per subspace.
        rng: Sampler for the initial centroids. A default generator is used when omitted.

    Returns:
        Codebooks of shape ``(m_subspaces, k_centroids, d / m_subspaces)``.
    """
    rows = np.asarray(data, dtype=np.float32)
    if rows.ndim != 2 or rows.shape[0] == 0:
        raise AlgorithmInputError("PQ training data must have shape (n, d)")
    if m_subspaces < 1 or rows.shape[1] % m_subspaces != 0:
        raise AlgorithmInputError("subspace count must divide the vector dimension")
    if k_centroids < 1 or k_centroids > rows.shape[0]:
        raise AlgorithmInputError("centroid count must lie between 1 and the row count")
    if iterations < 1:
        raise AlgorithmInputError("PQ training needs at least one iteration")
    generator = np.random.default_rng() if rng is None else rng
    n_rows, dimension = rows.shape
    sub_dim = dimension // m_subspaces
    codebooks = np.zeros((m_subspaces, k_centroids, sub_dim), dtype=np.float32)
    for subspace in range(m_subspaces):
        block = rows[:, subspace * sub_dim : (subspace + 1) * sub_dim]
        chosen = generator.choice(n_rows, k_centroids, replace=False)
        centroids = block[chosen].copy()
        for _ in range(iterations):
            distances = np.linalg.norm(block[:, None, :] - centroids[None, :, :], axis=2)
            assignments = np.argmin(distances, axis=1)
            for centroid in range(k_centroids):
                members = assignments == centroid
                if np.any(members):
                    centroids[centroid] = block[members].mean(axis=0)
        codebooks[subspace] = centroids
    return codebooks
