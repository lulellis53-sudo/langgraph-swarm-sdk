"""Measure bounded vector-search latency, CPU cost, memory, and Recall@K."""

from __future__ import annotations

import argparse
import json
import os
import resource
import statistics
import time
from pathlib import Path

import numpy as np

from swarm_sdk.gpu import opencl_status, set_enabled
from swarm_sdk.memory.opencl_store import OpenClVecStore


def _percentile(values: list[float], percentile: float) -> float:
    return float(np.percentile(np.asarray(values, dtype=np.float64), percentile))


def _peak_rss_bytes() -> int:
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # macOS reports bytes; Linux reports KiB.
    return int(value if __import__("sys").platform == "darwin" else value * 1024)


def run(rows: int, dim: int, queries: int, k: int, seed: int = 7) -> dict[str, object]:
    rng = np.random.default_rng(seed)
    vectors = rng.standard_normal((rows, dim), dtype=np.float32)
    vectors /= np.maximum(np.linalg.norm(vectors, axis=1, keepdims=True), 1e-12)
    query_vectors = rng.standard_normal((queries, dim), dtype=np.float32)
    query_vectors /= np.maximum(np.linalg.norm(query_vectors, axis=1, keepdims=True), 1e-12)
    profiles: list[dict[str, object]] = []
    prior_threshold = os.environ.get("SWARM_OPENCL_MIN_ROWS")
    # Measure the real OpenCL backend independent of its conservative runtime threshold.
    os.environ["SWARM_OPENCL_MIN_ROWS"] = "1"

    for backend, enabled in (("numpy", False), ("opencl", True)):
        set_enabled(enabled)
        for chunk_rows in (64, 128, 256, 512, 1024, 2048, 4096):
            store = OpenClVecStore(dim, max_vectors=rows, chunk_rows=chunk_rows)
            for index, vector in enumerate(vectors):
                store.add(str(index), vector)

            latencies_ms: list[float] = []
            cpu_start = time.process_time()
            recall: list[float] = []
            for query in query_vectors:
                started = time.perf_counter()
                hits = store.search(query, k)
                latencies_ms.append((time.perf_counter() - started) * 1000)
                actual = {hit.id for hit in hits}
                exact_scores = vectors @ query
                expected_indexes = np.argpartition(
                    exact_scores, -min(k, rows)
                )[-min(k, rows) :]
                expected = set(expected_indexes.tolist())
                recall.append(len(actual & expected) / len(expected) if expected else 1.0)
            profiles.append(
                {
                    "backend": backend,
                    "chunk_rows": chunk_rows,
                    "p50_ms": statistics.median(latencies_ms),
                    "p95_ms": _percentile(latencies_ms, 95),
                    "cpu_ms": (time.process_time() - cpu_start) * 1000,
                    "peak_rss_bytes": _peak_rss_bytes(),
                    "resident_vector_bytes": store.resident_bytes,
                    "recall_at_k": statistics.mean(recall),
                }
            )
    set_enabled(True)
    if prior_threshold is None:
        os.environ.pop("SWARM_OPENCL_MIN_ROWS", None)
    else:
        os.environ["SWARM_OPENCL_MIN_ROWS"] = prior_threshold

    eligible = [item for item in profiles if float(item["recall_at_k"]) >= 0.999]
    best = min(eligible or profiles, key=lambda item: float(item["p95_ms"]))
    return {
        "backend": opencl_status(),
        "workload": {"rows": rows, "dim": dim, "queries": queries, "k": k, "seed": seed},
        "profiles": profiles,
        "recommended_backend": best["backend"],
        "recommended_chunk_rows": best["chunk_rows"],
        "selection": "lowest p95 among profiles with Recall@K >= 0.999",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=4096)
    parser.add_argument("--dim", type=int, default=1024)
    parser.add_argument("--queries", type=int, default=50)
    parser.add_argument("--k", type=int, default=10)
    parser.add_argument("--write-results", action="store_true")
    args = parser.parse_args()
    report = run(args.rows, args.dim, args.queries, args.k)
    output = json.dumps(report, indent=2)
    if args.write_results:
        path = Path(__file__).resolve().parents[2] / "results" / "gpu_retrieval"
        path.mkdir(parents=True, exist_ok=True)
        target = path / "latest.json"
        target.write_text(output + "\n", encoding="utf-8")
        print(f"Wrote {target}")
    print(output)


if __name__ == "__main__":
    main()
