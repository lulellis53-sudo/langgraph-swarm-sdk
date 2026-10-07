"""``low-swarm spawn GOAL``: decompose a goal into a validated, wave-ordered plan."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Any

from swarm_sdk.agents.manifest import load_all_agent_manifests
from swarm_sdk.cli import create_panel, create_table
from swarm_sdk.commands import Handler, markup_safe
from swarm_sdk.orchestrator.spawn import spawn


def register(subparsers: Any) -> tuple[str, Handler]:
    parser = subparsers.add_parser("spawn", help="Decompose a goal into a plan of agent steps")
    parser.add_argument("goal", help="Free-text goal to decompose")
    parser.add_argument("--agents-dir", type=Path, default=None, help="Agents directory")
    parser.add_argument("--json", action="store_true", help="Print the plan as JSON only")
    return "spawn", handle_spawn


def handle_spawn(args: argparse.Namespace, console: Any) -> int:
    """Run the Orchestrator and print the plan (waves table, or JSON with ``--json``)."""
    try:
        manifests = load_all_agent_manifests(args.agents_dir)
    except (OSError, ValueError) as exc:
        print(f"error: cannot load agent manifests: {exc}", file=sys.stderr)
        return 2
    if not manifests:
        print("error: no agent manifests found (use --agents-dir)", file=sys.stderr)
        return 2

    try:
        plan = asyncio.run(spawn(args.goal, manifests))
    except (RuntimeError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(plan.model_dump_json(indent=2))
        return 0
    try:
        waves = plan.waves()
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    table = create_table(title=f"Plan: {markup_safe(args.goal)}")
    for column in ("Wave", "Step", "Agent", "Files", "Depends on"):
        table.add_column(column, style="bold" if column == "Wave" else None)
    for number, wave in enumerate(waves, 1):
        for step in wave:
            table.add_row(
                str(number),
                markup_safe(f"{step.id} {step.title}"),
                markup_safe(step.agent),
                markup_safe(", ".join(step.files)) or "-",
                markup_safe(", ".join(step.depends_on)) or "-",
            )
    console.print(create_panel(table, title=f"{len(plan.steps)} step(s) in {len(waves)} wave(s)"))
    return 0
