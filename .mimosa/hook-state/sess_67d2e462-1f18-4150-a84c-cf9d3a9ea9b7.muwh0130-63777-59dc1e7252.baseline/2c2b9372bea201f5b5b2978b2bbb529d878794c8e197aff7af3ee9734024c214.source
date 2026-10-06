"""Score small model tasks and separate provider wait from local benchmark time."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import tempfile
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

_ROOT = Path(__file__).resolve().parents[2]
_TASK = Path(__file__).resolve().parent / "Tasks" / "model_effort" / "task.yaml"
_REGISTRY = _ROOT / "src" / "swarm_sdk" / "agents" / "config" / "model_registry.yaml"


@dataclass(frozen=True)
class BenchmarkCase:
    id: str
    task_type: str
    prompt: str
    expected: str


@dataclass(frozen=True)
class ModelReply:
    text: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    token_source: str = "provider"


type Invoker = Callable[[str, str, str], ModelReply]


@dataclass(frozen=True)
class AutoRoute:
    model: str
    effort: str
    mode: str


_AUTO_DIRECT_PROVIDERS = frozenset(
    {
        "openai",
        "anthropic",
        "google",
        "groq",
        "cohere",
        "mistral",
        "xai",
        "openrouter",
        "sambanova",
        "fireworks",
    }
)


def select_auto_route(
    entries: list[dict[str, Any]],
    *,
    credential_available: Callable[[str], bool],
    codex_profile: str | None,
) -> AutoRoute:
    """Choose one credentialed low-effort API route, then a Codex CLI fallback."""
    effort_order = {"low": 0, "medium": 1, "high": 2}
    ordered = sorted(
        entries,
        key=lambda item: (
            effort_order.get(item.get("effort", "medium"), 3),
            item.get("priority", 100),
        ),
    )
    for entry in ordered:
        model = entry.get("name", "")
        if (
            entry.get("provider") not in {"codex", "claude-code"}
            and model.split(":", 1)[0] in _AUTO_DIRECT_PROVIDERS
            and (key := entry.get("api_key_env"))
            and credential_available(key)
        ):
            return AutoRoute(model, entry.get("effort", "medium"), "live")
    if codex_profile:
        for entry in entries:
            if entry.get("provider") == "codex":
                return AutoRoute(entry["name"], entry.get("effort", "medium"), "codex")
    raise RuntimeError("no eligible LLM route has a credential or Codex profile")


def run_autonomous(
    cases: Iterable[BenchmarkCase],
    route: tuple[str, str],
    invoke: Invoker,
    *,
    max_total_tokens: int,
) -> dict[str, Any]:
    """Run fixed cases across task types until the reported-token budget stops it."""
    if max_total_tokens <= 0:
        raise ValueError("max_total_tokens must be positive")
    buckets: dict[str, list[BenchmarkCase]] = {}
    for case in cases:
        buckets.setdefault(case.task_type, []).append(case)
    ordered = [
        case
        for index in range(max((len(items) for items in buckets.values()), default=0))
        for items in buckets.values()
        if index < len(items)
        for case in [items[index]]
    ]
    rows: list[dict[str, Any]] = []
    total = 0
    largest = 0
    stopped_reason: str | None = None
    error_type: str | None = None
    for case in ordered:
        if rows and total + largest > max_total_tokens:
            stopped_reason = "projected_token_budget"
            break
        try:
            row = run_case(case, *route, invoke)
        except Exception as exc:
            stopped_reason = "agent_error"
            error_type = type(exc).__name__
            break
        rows.append(row)
        tokens = row["total_tokens"]
        if tokens is None:
            stopped_reason = "unreported_usage"
            break
        total += tokens
        largest = max(largest, tokens)
        if total > max_total_tokens:
            stopped_reason = "reported_token_budget"
            break
    return {
        "cases": rows,
        "groups": aggregate(rows),
        "expected_cases": len(ordered),
        "reported_tokens": total,
        "complete": stopped_reason is None,
        "stopped_reason": stopped_reason,
        "error_type": error_type,
    }


def load_cases() -> list[BenchmarkCase]:
    data = yaml.safe_load(_TASK.read_text(encoding="utf-8"))
    return [BenchmarkCase(**item) for item in data["cases"]]


def load_routes(names: Iterable[str] | None = None) -> list[tuple[str, str]]:
    requested = set(names or ())
    data = yaml.safe_load(_REGISTRY.read_text(encoding="utf-8"))
    routes = [
        (entry["name"], entry["effort"])
        for entry in data["providers"]
        if not requested or entry["name"] in requested
    ]
    missing = requested - {name for name, _ in routes}
    if missing:
        raise ValueError(f"unknown model route(s): {', '.join(sorted(missing))}")
    return routes


def _normalize(value: str) -> str:
    return " ".join(value.strip().casefold().split()).rstrip(".")


def run_case(
    case: BenchmarkCase,
    model: str,
    effort: str,
    invoke: Invoker,
    *,
    clock: Callable[[], float] = time.perf_counter,
) -> dict[str, Any]:
    """Measure local time as wall time minus the measured model-call interval."""
    start = clock()
    prompt = case.prompt
    call_start = clock()
    reply = invoke(model, effort, prompt)
    call_end = clock()
    score = float(_normalize(reply.text) == _normalize(case.expected))
    end = clock()
    wall_ms = max(0.0, (end - start) * 1000)
    model_ms = max(0.0, (call_end - call_start) * 1000)
    has_usage = reply.input_tokens is not None and reply.output_tokens is not None
    return {
        "case_id": case.id,
        "task_type": case.task_type,
        "model": model,
        "effort": effort,
        "score": score,
        "input_tokens": reply.input_tokens if has_usage else None,
        "output_tokens": reply.output_tokens if has_usage else None,
        "total_tokens": (reply.input_tokens + reply.output_tokens if has_usage else None),
        "token_source": reply.token_source if has_usage else "unreported",
        "wall_ms": wall_ms,
        "model_ms": model_ms,
        "overhead_ms": max(0.0, wall_ms - model_ms),
    }


def run_suite(
    cases: Iterable[BenchmarkCase], routes: Iterable[tuple[str, str]], invoke: Invoker
) -> list[dict[str, Any]]:
    return [run_case(case, model, effort, invoke) for model, effort in routes for case in cases]


def aggregate(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for row in rows:
        key = (row["task_type"], row["model"], row["effort"])
        groups.setdefault(key, []).append(row)
    result: list[dict[str, Any]] = []
    for (task_type, model, effort), items in sorted(groups.items()):
        reported = [item["total_tokens"] for item in items if item["total_tokens"] is not None]
        result.append(
            {
                "task_type": task_type,
                "model": model,
                "effort": effort,
                "cases": len(items),
                "mean_score": round(sum(item["score"] for item in items) / len(items), 4),
                "reported_token_cases": len(reported),
                "total_tokens": sum(reported) if reported else None,
                "average_tokens": round(sum(reported) / len(reported), 2) if reported else None,
                "average_overhead_ms": round(
                    sum(item["overhead_ms"] for item in items) / len(items), 3
                ),
                "average_model_ms": round(sum(item["model_ms"] for item in items) / len(items), 3),
                "average_wall_ms": round(sum(item["wall_ms"] for item in items) / len(items), 3),
            }
        )
    return result


def _scripted(cases: list[BenchmarkCase]) -> Invoker:
    from swarm_sdk.prompting.budget import count_text

    expected = {case.prompt: case.expected for case in cases}

    def invoke(_model: str, _effort: str, prompt: str) -> ModelReply:
        answer = expected[prompt]
        return ModelReply(answer, count_text(prompt), count_text(answer), "estimated")

    return invoke


def _live(names: list[str]) -> Invoker:
    from dotenv import load_dotenv

    from swarm_sdk.models.chat import load_chat_model, message_text
    from swarm_sdk.vault import load_into_env

    load_dotenv(_ROOT / ".env")
    registry = yaml.safe_load(_REGISTRY.read_text(encoding="utf-8"))
    entries = {item["name"]: item for item in registry["providers"]}
    credential_names = {value for name in names if (value := entries[name].get("api_key_env"))}
    missing = load_into_env(sorted(credential_names))
    if missing:
        raise ValueError(f"missing credential/config names: {', '.join(missing)}")
    models = {name: load_chat_model(name) for name in names}

    def invoke(model: str, _effort: str, prompt: str) -> ModelReply:
        from langchain_core.messages import HumanMessage

        message = models[model].invoke([HumanMessage(content=prompt)])
        usage = getattr(message, "usage_metadata", None) or {}
        return ModelReply(
            message_text(message), usage.get("input_tokens"), usage.get("output_tokens")
        )

    return invoke


def _codex(profile: str) -> Invoker:
    """Invoke a named Codex CLI profile in a read-only, empty working directory."""
    if re.fullmatch(r"[A-Za-z0-9_-]+", profile) is None:
        raise ValueError("Codex profile must be a simple name")

    def invoke(model: str, effort: str, prompt: str) -> ModelReply:
        with tempfile.TemporaryDirectory(prefix="swarm_codex_bench_") as working:
            answer_file = Path(working) / "answer.txt"
            proc = subprocess.run(
                [
                    "codex",
                    "exec",
                    "-p",
                    profile,
                    "-m",
                    model.split(":", 1)[1],
                    "-c",
                    f"model_reasoning_effort={effort}",
                    "-s",
                    "read-only",
                    "-C",
                    working,
                    "--skip-git-repo-check",
                    "--ephemeral",
                    "--json",
                    "-o",
                    str(answer_file),
                ],
                input=prompt,
                capture_output=True,
                text=True,
                timeout=180,
                check=False,
            )
            if proc.returncode != 0:
                raise RuntimeError(f"Codex CLI failed for {model} (exit {proc.returncode})")
            answer = answer_file.read_text(encoding="utf-8").strip()
            input_tokens: int | None = None
            output_tokens: int | None = None
            for line in proc.stdout.splitlines():
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if event.get("type") == "turn.completed":
                    usage = event.get("usage") or {}
                    input_tokens = usage.get("input_tokens")
                    output_tokens = usage.get("output_tokens")
            return ModelReply(answer, input_tokens, output_tokens, "codex")

    return invoke


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Benchmark task scores by model and effort")
    parser.add_argument("--model", action="append", default=[], help="registry model name")
    parser.add_argument("--live", action="store_true", help="call selected provider models")
    parser.add_argument("--auto", action="store_true", help="select an available LLM agent")
    parser.add_argument("--codex-profile", help="run selected Codex route via codex exec -p")
    parser.add_argument("--max-total-tokens", type=int, default=50000)
    parser.add_argument("--write-results", action="store_true")
    parser.add_argument("--json", action="store_true", help="print full per-case JSON report")
    args = parser.parse_args(argv)
    if args.live and not args.model:
        parser.error("--live requires at least one --model")
    if args.auto and args.live:
        parser.error("--auto cannot combine with --live")
    if args.codex_profile and (args.live or (not args.auto and not args.model)):
        parser.error("--codex-profile requires --model unless --auto is set")
    if args.max_total_tokens <= 0:
        parser.error("--max-total-tokens must be positive")
    cases = load_cases()
    routes = load_routes(args.model)
    registry = yaml.safe_load(_REGISTRY.read_text(encoding="utf-8"))
    codex_names = {
        entry["name"] for entry in registry["providers"] if entry.get("provider") == "codex"
    }
    report: dict[str, Any]
    if args.auto:
        from dotenv import load_dotenv

        from swarm_sdk.vault import get_with_source

        load_dotenv(_ROOT / ".env")
        profile_dir = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
        task_config = yaml.safe_load(_TASK.read_text(encoding="utf-8"))
        profile = args.codex_profile or task_config.get("auto", {}).get("codex_profile")
        profile_exists = bool(profile and (profile_dir / f"{profile}.config.toml").is_file())
        if args.codex_profile and not profile_exists:
            parser.error(f"Codex profile {profile} is not installed")
        eligible = [
            entry
            for entry in registry["providers"]
            if not args.model or entry["name"] in args.model
        ]
        available: dict[str, bool] = {}

        def credential_available(name: str) -> bool:
            if name not in available:
                available[name] = get_with_source(name) is not None
            return available[name]

        selected = select_auto_route(
            eligible,
            credential_available=credential_available,
            codex_profile=profile if profile_exists else None,
        )
        invoke = _codex(profile) if selected.mode == "codex" else _live([selected.model])
        report = run_autonomous(
            cases,
            (selected.model, selected.effort),
            invoke,
            max_total_tokens=args.max_total_tokens,
        )
        report.update(
            {
                "mode": "auto",
                "selected_model": selected.model,
                "selected_effort": selected.effort,
                "agent_mode": selected.mode,
            }
        )
    elif args.codex_profile:
        if any(name not in codex_names for name, _ in routes):
            parser.error("--codex-profile accepts only registry routes with provider: codex")
        invoke = _codex(args.codex_profile)
        mode = "codex"
    elif args.live:
        if any(name in codex_names for name, _ in routes):
            parser.error("Codex routes require --codex-profile, not --live")
        invoke = _live(args.model)
        mode = "live"
    else:
        invoke = _scripted(cases)
        mode = "scripted"
    if not args.auto:
        rows = run_suite(cases, routes, invoke)
        report = {"mode": mode, "cases": rows, "groups": aggregate(rows)}
    else:
        rows = report["cases"]
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"mode: {report['mode']} | rows: {len(rows)}")
        if args.auto:
            print(
                f"selected: {report['selected_model']} | complete: {report['complete']} | "
                f"stop: {report['stopped_reason'] or '-'}"
            )
        print("task_type\tmodel\teffort\tmean_score\tavg_tokens\tavg_overhead_ms")
        for group in report["groups"]:
            print(
                f"{group['task_type']}\t{group['model']}\t{group['effort']}\t"
                f"{group['mean_score']:.3f}\t{group['average_tokens']}\t"
                f"{group['average_overhead_ms']:.3f}"
            )
    if args.write_results:
        output = Path(__file__).parent / "results" / "model_effort" / "latest.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
