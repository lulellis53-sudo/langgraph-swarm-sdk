"""Benchmark harness — end to end first.

``run_all`` attempts a full swarm turn before any micro-benchmark, mirroring
the project's own priority order. Every other measurement runs offline, with
no API keys and no services.
"""

import argparse
import json
import subprocess
import sys
import time
from collections.abc import Callable
from statistics import fmean

_PAYLOAD = {
    "thread_id": "bench",
    "messages": [
        {"role": "user", "content": "Explain swarm routing in one sentence."},
        {
            "role": "assistant",
            "content": "Swarm routing moves control between specialised agents via handoff tools.",
        },
    ],
    "metadata": {"agents": 12, "checkpointer": "memory"},
}


def _timed(fn: Callable[[], object], *, repeats: int) -> dict:
    times: list[float] = []
    for _ in range(repeats):
        start = time.perf_counter()
        fn()
        times.append(time.perf_counter() - start)
    return {"mean_ms": round(fmean(times) * 1000, 3), "repeats": repeats}


def bench_import(*, repeats: int = 3) -> dict:
    """Cold-import cost of the SDK compared to LangChain itself."""

    def cold(module: str) -> Callable[[], None]:
        def run() -> None:
            subprocess.run([sys.executable, "-c", f"import {module}"], check=True)

        return run

    return {
        "langswarm": _timed(cold("langswarm"), repeats=repeats),
        "langchain": _timed(cold("langchain"), repeats=repeats),
    }


def bench_blueprint(*, repeats: int = 20) -> dict:
    """YAML load plus schema validation of the twelve-agent definition."""
    from langswarm.blueprint import load_blueprint
    from langswarm.config import settings

    return _timed(lambda: load_blueprint(settings.config_path), repeats=repeats)


def bench_serde(*, repeats: int = 200) -> dict:
    """Round-trip throughput: orjson vs stdlib json vs MessagePack."""
    from langswarm.codec import json_dumps, json_loads, msgpack_decode, msgpack_encode

    return {
        "orjson": _timed(lambda: json_loads(json_dumps(_PAYLOAD)), repeats=repeats),
        "stdlib_json": _timed(
            lambda: json.loads(json.dumps(_PAYLOAD)), repeats=repeats
        ),
        "msgpack": _timed(
            lambda: msgpack_decode(msgpack_encode(_PAYLOAD)), repeats=repeats
        ),
    }


def bench_tokenization(*, documents: int = 256, repeats: int = 5) -> dict:
    """Tokenization throughput with the tokenizers library."""
    try:
        from tokenizers import Tokenizer
    except ImportError:
        return {"skipped": "tokenizers is not installed"}

    tokenizer = Tokenizer.from_pretrained("bert-base-uncased")
    texts = ["Routing a twelve-agent swarm through explicit handoff tools."] * documents

    result = _timed(lambda: [tokenizer.encode(text) for text in texts], repeats=repeats)
    result["texts_per_second"] = round(
        documents / (result["mean_ms"] / 1000), 1
    )
    return result


def bench_embeddings(*, documents: int = 64, repeats: int = 1) -> dict:
    """Local embedding throughput on CPU (downloads the model on first run)."""
    from langswarm.config import settings
    from langswarm.embeddings import FastEmbeddings

    model = FastEmbeddings(model_name=settings.embedding_model)
    texts = ["swarm routing and handoffs between specialised agents."] * documents

    result = _timed(lambda: model.embed_documents(texts), repeats=repeats)
    result["docs_per_second"] = round(documents / (result["mean_ms"] / 1000), 1)
    return result


def bench_e2e(*, question: str = "In one sentence: why use a swarm?", repeats: int = 1) -> dict:
    """One full conversational turn through the twelve-agent swarm."""
    from langswarm.blueprint import load_blueprint
    from langswarm.config import settings
    from langswarm.runner import run_swarm
    from langswarm.swarm import build_from_blueprint

    app = build_from_blueprint(load_blueprint(settings.config_path))
    return _timed(lambda: run_swarm(app, question, thread_id="bench-e2e"), repeats=repeats)


def run_all(*, e2e: bool = False) -> dict:
    """Run the suite in end-to-end-first order."""
    report: dict = {"e2e": None}
    if e2e:
        report["e2e"] = bench_e2e()
    report["import"] = bench_import()
    report["blueprint"] = bench_blueprint()
    report["serde"] = bench_serde()
    report["tokenization"] = bench_tokenization()
    report["embeddings"] = bench_embeddings()
    return report


def bench_tool():
    """Return the benchmark tool used by the BenchmarkRunner agent."""

    def run_benchmark() -> str:
        """Run the offline benchmark suite and return the results as text."""
        from langswarm.codec import json_dumps

        report = {name: value for name, value in run_all().items() if value is not None}
        return json_dumps(report).decode()

    return run_benchmark


def _render(report: dict) -> None:
    from rich.console import Console
    from rich.table import Table

    table = Table(title="Langswarm benchmark report")
    table.add_column("benchmark")
    table.add_column("mean_ms", justify="right")
    table.add_column("repeats", justify="right")

    def rows(prefix: str, node: dict) -> None:
        for key, value in node.items():
            name = f"{prefix}.{key}" if prefix else key
            if isinstance(value, dict):
                if "mean_ms" in value:
                    table.add_row(name, str(value["mean_ms"]), str(value["repeats"]))
                else:
                    rows(name, value)

    rows("", report)
    Console().print(table)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="langswarm.bench", description="Benchmark the Langswarm SDK."
    )
    parser.add_argument(
        "--e2e", action="store_true", help="Include one full swarm turn (needs keys)."
    )
    parser.add_argument(
        "--json", action="store_true", help="Print the raw orjson report instead of a table."
    )
    args = parser.parse_args()

    report = run_all(e2e=args.e2e)
    if args.json:
        from langswarm.codec import json_dumps

        print(json_dumps(report).decode())
    else:
        _render(report)


if __name__ == "__main__":
    main()
