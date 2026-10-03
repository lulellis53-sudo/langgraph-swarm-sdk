"""Benchmark FastEmbed: CPU vs CoreML (GPU) ONNX Runtime execution providers.

Requires the jupyter extra (fastembed + onnxruntime on supported platforms):

    uv sync --extra jupyter
    uv run python Agents/benchmark/CPU_GPU.py
    uv run python Agents/benchmark/CPU_GPU.py --write-results --json
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from benchmark.metrics import Timer  # noqa: E402

RESULTS_DIR = Path(__file__).resolve().parent / "results" / "cpu_gpu"
DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
DEFAULT_SNIPPET = "Hybrid search combines dense embeddings with BM25 keywords for retrieval."


def _require_fastembed() -> Any:
    import importlib

    try:
        module = importlib.import_module("fastembed")
    except ImportError as exc:
        raise SystemExit("fastembed is not installed. Run: uv sync --extra jupyter") from exc
    return getattr(module, "TextEmbedding")


def _sample_documents(count: int, snippet: str) -> list[str]:
    return [f"{snippet} doc-{i}" for i in range(count)]


def _provider_configs(include_cuda: bool) -> list[tuple[str, list[Any]]]:
    configs: list[tuple[str, list[Any]]] = [
        ("cpu", ["CPUExecutionProvider"]),
        (
            "coreml_gpu",
            [
                (
                    "CoreMLExecutionProvider",
                    {"MLComputeUnits": "CPUAndGPU"},
                ),
                "CPUExecutionProvider",
            ],
        ),
    ]
    if include_cuda:
        configs.append(("cuda", ["CUDAExecutionProvider", "CPUExecutionProvider"]))
    return configs


def _bench_one(
    TextEmbedding: Any,
    *,
    label: str,
    providers: list[Any],
    model_name: str,
    documents: list[str],
    warmup: int,
    runs: int,
) -> dict[str, Any]:
    model = TextEmbedding(model_name=model_name, providers=providers)
    session = model.model.model
    active = list(session.get_providers())

    for _ in range(warmup):
        list(model.embed(documents[: min(8, len(documents))]))

    elapsed_ms: list[float] = []
    for _ in range(runs):
        with Timer() as timer:
            list(model.embed(documents))
        elapsed_ms.append(timer.elapsed_ms)

    mean_ms = statistics.mean(elapsed_ms)
    doc_count = len(documents)
    docs_per_sec = doc_count / (mean_ms / 1000.0) if mean_ms > 0 else 0.0

    return {
        "label": label,
        "providers_requested": providers,
        "providers_active": active,
        "model": model_name,
        "documents": doc_count,
        "runs": runs,
        "warmup": warmup,
        "mean_ms": round(mean_ms, 3),
        "stdev_ms": round(statistics.pstdev(elapsed_ms), 3) if len(elapsed_ms) > 1 else 0.0,
        "min_ms": round(min(elapsed_ms), 3),
        "max_ms": round(max(elapsed_ms), 3),
        "docs_per_sec": round(docs_per_sec, 2),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Benchmark CPU vs CoreML GPU embedders")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="FastEmbed model name")
    parser.add_argument("--docs", type=int, default=200, help="Number of documents to embed")
    parser.add_argument("--snippet", default=DEFAULT_SNIPPET, help="Base text for synthetic docs")
    parser.add_argument("--runs", type=int, default=10, help="Timed runs per configuration")
    parser.add_argument("--warmup", type=int, default=2, help="Warmup runs (untimed)")
    parser.add_argument(
        "--cuda",
        action="store_true",
        help="Also benchmark CUDAExecutionProvider when available",
    )
    parser.add_argument("--json", action="store_true", help="Print results as JSON")
    parser.add_argument(
        "--write-results",
        action="store_true",
        help="Write JSON to benchmark/results/cpu_gpu/ (gitignored)",
    )
    args = parser.parse_args(argv)

    if args.docs < 1 or args.runs < 1:
        print("--docs and --runs must be >= 1", file=sys.stderr)
        return 1

    TextEmbedding = _require_fastembed()
    documents = _sample_documents(args.docs, args.snippet)
    results: list[dict[str, Any]] = []
    failures: list[str] = []

    for label, providers in _provider_configs(args.cuda):
        try:
            row = _bench_one(
                TextEmbedding,
                label=label,
                providers=providers,
                model_name=args.model,
                documents=documents,
                warmup=args.warmup,
                runs=args.runs,
            )
            results.append(row)
        except Exception as exc:
            failures.append(f"{label}: {exc}")

    payload = {
        "timestamp": datetime.now(UTC).isoformat(),
        "results": results,
        "failures": failures,
    }

    if args.write_results:
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        out_path = RESULTS_DIR / f"{stamp}.json"
        out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"wrote {out_path}")

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        for row in results:
            print(
                f"{row['label']}\t"
                f"mean={row['mean_ms']}ms\t"
                f"docs/s={row['docs_per_sec']}\t"
                f"active={row['providers_active']}"
            )
        for msg in failures:
            print(f"FAIL\t{msg}", file=sys.stderr)

    return 1 if failures and not results else 0


if __name__ == "__main__":
    raise SystemExit(main())
