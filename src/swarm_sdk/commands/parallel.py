"""``low-swarm parallel``: run a plan in dependency waves with bounded parallelism."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Any

from swarm_sdk.agents.manifest import load_all_agent_manifests
from swarm_sdk.cli import create_panel, create_table
from swarm_sdk.commands import Handler, markup_safe
from swarm_sdk.orchestrator.graph import run_plan
from swarm_sdk.orchestrator.plan import Plan
from swarm_sdk.orchestrator.spawn import make_factory, spawn
from swarm_sdk.runtime import parallel_cap


def _positive_int(text: str) -> int:
    try:
        value = int(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"not an integer: {text!r}") from exc
    if value < 1:
        raise argparse.ArgumentTypeError("must be >= 1")
    return value


def register(subparsers: Any) -> tuple[str, Handler]:
    """Add the ``parallel`` subcommand and return its (name, handler) pair.

    Args:
        subparsers: argparse subparsers collection of the root CLI parser.

    Returns:
        Tuple of the command name and the handler bound to it.
    """
    parser = subparsers.add_parser(
        "parallel", help="Execute a plan in dependency waves with bounded parallelism"
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--plan", type=Path, help="Plan JSON file (as printed by `spawn --json`)")
    source.add_argument("--goal", help="Goal to decompose with `spawn`, then execute")
    parser.add_argument("--agents-dir", type=Path, default=None, help="Agents directory")
    parser.add_argument(
        "--max-concurrency", type=_positive_int, default=None, help="Max in-flight steps per wave"
    )
    parser.add_argument("--json", action="store_true", help="Print the result as JSON only")
    return "parallel", handle_parallel


def _load_plan(args: argparse.Namespace, manifests: dict[str, Any]) -> Plan:
    if args.plan is not None:
        return Plan.model_validate_json(args.plan.read_text(encoding="utf-8"))
    return asyncio.run(spawn(args.goal, manifests))


def handle_parallel(args: argparse.Namespace, console: Any) -> int:
    """Load or spawn a plan, execute it through ``run_plan``, and print the outputs."""
    try:
        manifests = load_all_agent_manifests(args.agents_dir)
    except (OSError, ValueError) as exc:
        print(f"error: cannot load agent manifests: {exc}", file=sys.stderr)
        return 2
    if not manifests:
        print("error: no agent manifests found (use --agents-dir)", file=sys.stderr)
        return 2

    try:
        plan = _load_plan(args, manifests)
    except (OSError, ValueError) as exc:
        print(f"error: cannot load plan: {exc}", file=sys.stderr)
        return 2
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    cap = args.max_concurrency or parallel_cap()
    try:
        result = asyncio.run(run_plan(plan, make_factory(manifests), max_concurrency=cap))
    except (RuntimeError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(result.model_dump_json(indent=2))
        return 0

    table = create_table(title=f"Parallel run (cap {cap})")
    for column in ("Step", "Agent", "Status", "Tokens", "Cached", "Wall (s)"):
        table.add_column(column, style="bold" if column == "Step" else None)
    for output in result.outputs.values():
        table.add_row(
            markup_safe(output.step_id),
            markup_safe(output.agent),
            markup_safe(output.status),
            str(output.prompt_tokens + output.completion_tokens),
            "yes" if output.cached else "no",
            f"{output.wall_s:.2f}",
        )
    usage = result.usage
    console.print(
        create_panel(
            table,
            title=(
                f"{len(result.outputs)} step(s), {usage.total_tokens} tokens, "
                f"{usage.llm_calls} LLM call(s), {usage.wall_s:.2f} s"
            ),
        )
    )
    print(result.answer)
    return 0
