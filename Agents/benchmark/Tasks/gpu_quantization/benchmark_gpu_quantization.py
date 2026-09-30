"""Compare float32, INT8, and 1-bit OpenClVecStore modes: latency, memory, Recall@K."""

from __future__ import annotations

import argparse
import json
import os
import resource
import statistics
import sys
import time
from pathlib import Path
from typing import Any, cast

import numpy as np

from swarm_sdk.gpu import opencl_available, opencl_status, set_enabled
from swarm_sdk.memory.opencl_store import OpenClVecStore


def _percentile(values: list[float], percentile: float) -> float:
    return float(np.percentile(np.asarray(values, dtype=np.float64), percentile))


def _peak_rss_bytes() -> int:
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # macOS reports bytes; Linux reports KiB.
    return int(value if sys.platform == "darwin" else value * 1024)


def run(rows: int, dim: int, queries: int, k: int, seed: int = 7) -> dict[str, Any]:
    rng = np.random.default_rng(seed)
    vectors = rng.standard_normal((rows, dim), dtype=np.float32)
    vectors /= np.maximum(np.linalg.norm(vectors, axis=1, keepdims=True), 1e-12)
    query_vectors = rng.standard_normal((queries, dim), dtype=np.float32)
    query_vectors /= np.maximum(np.linalg.norm(query_vectors, axis=1, keepdims=True), 1e-12)
    profiles: list[dict[str, object]] = []
    prior_threshold = os.environ.get("SWARM_OPENCL_MIN_ROWS")
    # Measure the real OpenCL backend independent of its conservative runtime threshold.
    os.environ["SWARM_OPENCL_MIN_ROWS"] = "1"

    backends: list[tuple[str, bool]] = [("numpy", False)]
    if opencl_available():
        backends.append(("opencl", True))

    for backend, enabled in backends:
        set_enabled(enabled)
        for mode in ("none", "int8", "binary"):
            store = OpenClVecStore(dim, max_vectors=rows, quantize=mode)  # type: ignore[arg-type]
            for index, vector in enumerate(vectors):
                store.add(str(index), np.asarray(vector))

            latencies_ms: list[float] = []
            cpu_start = time.process_time()
            recall: list[float] = []
            for query in query_vectors:
                started = time.perf_counter()
                hits = store.search(query, k)
                latencies_ms.append((time.perf_counter() - started) * 1000)
                actual = {hit.id for hit in hits}
                expected_scores = vectors @ query
                expected_indexes = np.argpartition(expected_scores, -min(k, rows))[-min(k, rows) :]
                expected = set(expected_indexes.tolist())
                recall.append(len(actual & expected) / len(expected) if expected else 1.0)
            profiles.append(
                {
                    "backend": backend,
                    "quantize": mode,
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

    qualifying = [item for item in profiles if cast(float, item["recall_at_k"]) >= 0.9]
    best_by_recall = (
        min(qualifying, key=lambda item: cast(int, item["resident_vector_bytes"]))
        if qualifying
        else None
    )
    return {
        "backend": opencl_status(),
        "workload": {"rows": rows, "dim": dim, "queries": queries, "k": k, "seed": seed},
        "profiles": profiles,
        "best_by_recall": dict(best_by_recall) if best_by_recall else None,
        "selection": "smallest resident footprint among modes with Recall@K >= 0.9",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=20000)
    parser.add_argument("--dim", type=int, default=384)
    parser.add_argument("--queries", type=int, default=50)
    parser.add_argument("--k", type=int, default=10)
    parser.add_argument("--write-results", action="store_true")
    args = parser.parse_args()
    report = run(args.rows, args.dim, args.queries, args.k)
    output = json.dumps(report, indent=2)
    if args.write_results:
        path = Path(__file__).resolve().parents[2] / "results" / "gpu_quantization"
        path.mkdir(parents=True, exist_ok=True)
        target = path / "latest.json"
        target.write_text(output + "\n", encoding="utf-8")
        print(f"Wrote {target}")
    print(output)


if __name__ == "__main__":
    main()
