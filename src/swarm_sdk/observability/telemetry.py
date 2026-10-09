"""Unified Telemetry Collector and Aggregator.

Aggregates execution metrics (token counts, latency, RPM, JEV score, success rates)
from all per-agent `Benchmarks/telemetry.jsonl` files into a single report.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import polars as pl


def collect_agent_telemetry(agents_dir: Path | str = "Agents") -> pl.DataFrame:
    """Scan all agent folders and aggregate `Benchmarks/telemetry.jsonl` records.

    Args:
        agents_dir: Path to the root Agents directory.

    Returns:
        Polars DataFrame containing all aggregated telemetry records.
    """
    base_path = Path(agents_dir)
    records: list[dict[str, Any]] = []

    for telemetry_file in base_path.glob("**/Benchmarks/telemetry.jsonl"):
        agent_name = telemetry_file.parent.parent.name
        try:
            with open(telemetry_file, encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    data = json.loads(line)
                    if "agent" not in data:
                        data["agent"] = agent_name
                    records.append(data)
        except Exception:
            continue

    if not records:
        return pl.DataFrame(
            schema={
                "agent": pl.Utf8,
                "timestamp": pl.Utf8,
                "token_count": pl.Int64,
                "latency_ms": pl.Float64,
                "throughput_rpm": pl.Float64,
                "jev_score": pl.Float64,
                "success_rate": pl.Float64,
                "status": pl.Utf8,
            }
        )

    return pl.DataFrame(records)


def summarize_telemetry(df: pl.DataFrame) -> dict[str, Any]:
    """Calculate system-wide aggregate metrics across all agents.

    Args:
        df: Polars DataFrame of raw telemetry records.

    Returns:
        Dictionary summarizing total tokens, average latency, throughput, and average JEV score.
    """
    if df.is_empty():
        return {
            "total_agents": 0,
            "total_tokens": 0,
            "avg_latency_ms": 0.0,
            "avg_throughput_rpm": 0.0,
            "avg_jev_score": 0.0,
            "overall_success_rate": 0.0,
        }

    return {
        "total_agents": int(df["agent"].n_unique()),
        "total_tokens": int(df["token_count"].sum()) if "token_count" in df.columns else 0,
        "avg_latency_ms": float(df["latency_ms"].mean()) if "latency_ms" in df.columns else 0.0,
        "avg_throughput_rpm": float(df["throughput_rpm"].mean())
        if "throughput_rpm" in df.columns
        else 0.0,
        "avg_jev_score": float(df["jev_score"].mean()) if "jev_score" in df.columns else 0.0,
        "overall_success_rate": float(df["success_rate"].mean())
        if "success_rate" in df.columns
        else 0.0,
    }


def main() -> None:
    """CLI entrypoint for running telemetry collection and printing summary."""
    df = collect_agent_telemetry()
    summary = summarize_telemetry(df)
    print("=== SWARM TELEMETRY AGGREGATION REPORT ===")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
