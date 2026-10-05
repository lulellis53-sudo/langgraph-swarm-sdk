"""Pillar 6: Arrow columnar views and a streaming Welford accumulator.

PyArrow is imported inside the functions that need it. ``welford_stats`` is the
NumPy form of the same merge.
"""

import heapq
from pathlib import Path

import numpy as np

from algorithms.errors import AlgorithmDependencyError, AlgorithmInputError

__all__ = [
    "arrow_masked_l2_norm",
    "arrow_to_numpy_zerocopy",
    "stream_arrow_ipc_mips",
    "stream_arrow_welford_stats",
    "welford_stats",
]


def _pyarrow() -> object:
    try:
        import pyarrow as pa
    except ImportError as err:
        raise AlgorithmDependencyError("pyarrow is not installed") from err
    return pa


def _merge(
    count: int,
    mean: float,
    second: float,
    count_b: int,
    mean_b: float,
    second_b: float,
) -> tuple[int, float, float]:
    if count_b == 0:
        return count, mean, second
    if count == 0:
        return count_b, mean_b, second_b
    total = count + count_b
    delta = mean_b - mean
    merged_mean = mean + delta * (count_b / total)
    merged_second = second + second_b + delta * delta * (count * count_b / total)
    return total, merged_mean, merged_second


def welford_stats(values: np.ndarray) -> tuple[float, float, int]:
    """Return sample mean, sample variance, and count for a 1-D array.

    The variance uses the ``count - 1`` divisor. An empty array returns
    ``(0.0, 0.0, 0)``.
    """
    data = np.asarray(values, dtype=np.float64).reshape(-1)
    count, mean, second = _merge(
        0, 0.0, 0.0, int(data.size), float(np.mean(data)) if data.size else 0.0, 0.0
    )
    if data.size:
        second = float(np.sum((data - mean) ** 2))
        count = int(data.size)
    variance = second / (count - 1) if count > 1 else 0.0
    return mean, variance, count


def arrow_to_numpy_zerocopy(table: object, column_name: str) -> np.ndarray:
    """Return a zero-copy NumPy view of one Arrow column."""
    pa = _pyarrow()
    if not isinstance(table, pa.Table):
        raise AlgorithmInputError("expected a pyarrow.Table")
    column = table[column_name]
    array = column.combine_chunks() if column.num_chunks > 1 else column.chunk(0)
    return np.asarray(array.to_numpy(zero_copy_only=True))


def arrow_masked_l2_norm(table: object, column_name: str) -> float:
    """Return the L2 norm of the valid entries in a nullable Arrow column."""
    pa = _pyarrow()
    if not isinstance(table, pa.Table):
        raise AlgorithmInputError("expected a pyarrow.Table")
    column = table[column_name].combine_chunks()
    values = np.asarray(column.to_numpy(zero_copy_only=False), dtype=np.float64).reshape(-1)
    if column.null_count == 0:
        return float(np.linalg.norm(values))
    valid = np.asarray(column.is_valid().to_numpy(zero_copy_only=True), dtype=bool)
    return float(np.linalg.norm(values[valid]))


def stream_arrow_ipc_mips(
    ipc_path: str | Path,
    query_vec: np.ndarray,
    top_k: int = 10,
) -> list[tuple[float, int]]:
    """Scan a memory-mapped Arrow IPC file for the top inner-product rows.

    The file's ``embedding`` column must be a fixed-size list.

    Returns:
        ``(score, row)`` pairs, highest score first.
    """
    pa = _pyarrow()
    query = np.asarray(query_vec, dtype=np.float64).reshape(-1)
    if top_k < 1:
        raise AlgorithmInputError("top_k must be positive")
    if query.size == 0:
        raise AlgorithmInputError("MIPS query is empty")
    source = pa.memory_map(str(ipc_path), "r")
    reader = pa.ipc.RecordBatchFileReader(source)
    best: list[tuple[float, int]] = []
    offset = 0
    for batch_index in range(reader.num_record_batches):
        batch = reader.get_batch(batch_index)
        embeddings = batch.column("embedding")
        if not pa.types.is_fixed_size_list(embeddings.type):
            raise AlgorithmInputError("embedding column must be a fixed-size list")
        width = int(embeddings.type.list_size)
        if width != query.size:
            raise AlgorithmInputError("embedding width does not match the query")
        flat = np.asarray(embeddings.values.to_numpy(zero_copy_only=True), dtype=np.float64)
        matrix = flat.reshape((batch.num_rows, width))
        scores = matrix @ query
        for local, score in enumerate(scores):
            row_id = offset + local
            scored = (float(score), row_id)
            if len(best) < top_k:
                heapq.heappush(best, scored)
            elif scored[0] > best[0][0]:
                heapq.heapreplace(best, scored)
        offset += batch.num_rows
    return sorted(best, reverse=True)


def stream_arrow_welford_stats(
    ipc_path: str | Path,
    column_name: str,
) -> tuple[float, float, int]:
    """Stream sample mean and variance from one numeric column of an Arrow IPC file."""
    pa = _pyarrow()
    source = pa.memory_map(str(ipc_path), "r")
    reader = pa.ipc.RecordBatchFileReader(source)
    count = 0
    mean = 0.0
    second = 0.0
    for batch_index in range(reader.num_record_batches):
        batch = reader.get_batch(batch_index)
        column = batch.column(column_name)
        values = np.asarray(column.to_numpy(zero_copy_only=False), dtype=np.float64).reshape(-1)
        if column.null_count > 0:
            valid = np.asarray(column.is_valid().to_numpy(zero_copy_only=True), dtype=bool)
            values = values[valid]
        if values.size == 0:
            continue
        batch_mean = float(np.mean(values))
        batch_second = float(np.sum((values - batch_mean) ** 2))
        count, mean, second = _merge(
            count, mean, second, int(values.size), batch_mean, batch_second
        )
    variance = second / (count - 1) if count > 1 else 0.0
    return mean, variance, count
